"""Structural checks on SKILL.md files.

lint_plugin.py already covers frontmatter and the clean-room denylist. These
cover the contract between a skill and the CLI it calls: a skill that
references a subcommand that does not exist fails at the worst possible
moment, in front of a client.
"""
import json
import re
from pathlib import Path

import pytest

from vaultlib import cli, feedback

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "plugin" / "skills"

SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))
REF_FILES = sorted(SKILLS_DIR.glob("*/references/*.md"))
# Skills invoke the CLI through the $VAULTLIB convention rather than repeating
# the path, so match either form: `cli.py <group> <action>` or
# `"$VAULTLIB" <group> <action>`. Group and action names may carry digits
# (m365) — a class without them silently exempts those invocations.
INVOCATION_RE = re.compile(r'(?:cli\.py|\$\{?VAULTLIB\}?)"?\s+([a-z0-9-]+)\s+([a-z0-9-]+)')

# Issue #129 lever 1: the m365 worker's tools stay open (no `tools:`
# allowlist — a per-deployment connector cannot be named on a fixed list),
# but the tools it structurally never needs are named on disallowedTools
# instead. A later PR reuses this exact list for the probe agent that
# measures what each of these tools costs in base context.
M365_WORKER_DISALLOWED_TOOLS = [
    "Agent", "Workflow", "WebFetch", "WebSearch", "NotebookEdit", "Skill",
    "SlashCommand", "TodoWrite", "Artifact", "ListAgents", "ReportFindings",
    "ShareOnboardingGuide", "Monitor", "SendMessage", "PushNotification",
    "RemoteTrigger", "TaskStop", "CronCreate", "CronDelete", "CronList",
]


def known_subcommands() -> set:
    """(group, action) pairs the CLI actually implements."""
    parser = cli.build_parser()
    pairs = set()
    for action in parser._subparsers._group_actions[0].choices.items():
        group, sub = action
        nested = sub._subparsers
        if nested is None:
            continue
        for name in nested._group_actions[0].choices:
            pairs.add((group, name))
    return pairs


NET_NEW = {"report-feedback", "health-check", "upgrade-vault", "setup-my-brain",
           "schedule-daily-loop", "provision-vault"}


def test_expected_skills_exist():
    # Each skill task appends its own name here as it lands, so this test is
    # always satisfiable by the task that touches it.
    names = {path.parent.name for path in SKILL_FILES}
    assert {"new-project", "update-entity", "log-decision",
            "sync-recordings", "evening-sync", "report-feedback",
            "health-check", "upgrade-vault", "setup-my-brain",
            "schedule-daily-loop", "provision-vault"} <= names


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_records_provenance(path):
    head = path.read_text(encoding="utf-8").split("---")[1]
    if path.parent.name in NET_NEW:
        assert "origin: net-new" in head, (
            f"{path.parent.name}: net-new skills declare origin: net-new")
        assert "upstreamed-from" not in head
    else:
        assert "upstreamed-from: busdev@" in head, (
            f"{path.parent.name}: ported skills record upstreamed-from")


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_states_its_surface_requirement(path):
    text = path.read_text(encoding="utf-8")
    assert "Cowork" in text and "Claude Code" in text, (
        f"{path.parent.name}: must state that writes need Cowork or Claude Code — "
        "plugins do not load in Chat, so the skill has to say so rather than fail"
    )


@pytest.mark.parametrize("path", SKILL_FILES + REF_FILES, ids=lambda p: p.parent.name)
def test_every_cli_invocation_named_by_a_skill_exists(path):
    implemented = known_subcommands()
    text = path.read_text(encoding="utf-8")
    referenced = set(INVOCATION_RE.findall(text))
    if path.name == "SKILL.md":
        assert referenced, f"{path.parent.name}: no CLI invocation found"
    unknown = referenced - implemented
    assert not unknown, (
        f"{path.parent.name} references subcommands the CLI does not implement: "
        f"{sorted(unknown)}"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_does_not_instruct_hand_written_frontmatter(path):
    text = path.read_text(encoding="utf-8").lower()
    for phrase in ("write the frontmatter", "emit the following frontmatter",
                   "create the file with this frontmatter"):
        assert phrase not in text, (
            f"{path.parent.name}: writes go through the CLI, never model-authored "
            "frontmatter — that is the whole point of the deterministic layer"
        )


def test_plugin_claude_md_documents_interpreter_resolution():
    # Assert the fallback SEQUENCE, not three presence checks: "python" is a
    # substring of "python3", so a presence check on it can never fail
    # independently and the test claims coverage it does not have.
    text = (REPO_ROOT / "plugin" / "CLAUDE.md").read_text(encoding="utf-8")
    parts = text.split("## Interpreter resolution", 1)
    assert len(parts) == 2, "plugin/CLAUDE.md has no Interpreter resolution section"
    section = parts[1].split("\n## ", 1)[0]
    chain = re.findall(r"`(python3|python|py -3)`", section)
    assert chain[:3] == ["python3", "python", "py -3"], (
        "plugin/CLAUDE.md must document the interpreter fallback chain in "
        "order: a clean Mac has no real python3 and Windows python3 is often a "
        f"Store alias stub. Found {chain[:3]}"
    )


def test_log_decision_documents_both_modes():
    text = (SKILLS_DIR / "log-decision" / "SKILL.md").read_text(encoding="utf-8")
    assert "--foreground" in text and "--background" in text, (
        "the mode flag is the interface #16's evening run calls; both halves "
        "have to be written down"
    )


def test_log_decision_forbids_prompting_in_background_mode():
    # The lab's production failure: an unattended run that asks a question
    # exits having done nothing.
    text = (SKILLS_DIR / "log-decision" / "SKILL.md").read_text(encoding="utf-8")
    assert "never ask" in text.lower() or "never prompt" in text.lower(), (
        "background mode must state that it never blocks on a prompt"
    )


def test_plugin_claude_md_documents_the_bare_stem_boundary():
    text = (REPO_ROOT / "plugin" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "bare" in text.lower() and "supersedes" in text, (
        "the wikilink-never-crosses-the-boundary rule belongs next to the "
        "pipe-escaping rule — they are the same lesson twice"
    )


def read_skill(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def read_ref(skill: str, name: str) -> str:
    return (SKILLS_DIR / skill / "references" / name).read_text(encoding="utf-8")


def test_sync_skills_gate_connectors_through_config():
    """#54: adapter enablement and account binding are deterministic —
    both sync skills must read the config and run the verify gate."""
    for name in ("sync-recordings", "evening-sync"):
        text = read_skill(name)
        assert "config read" in text, f"{name} must read the deployment config"
        assert "verify-account" in text, f"{name} must run the binding gate"


def test_sync_recordings_states_the_scratch_hygiene_rule():
    assert "## Scratch hygiene" in read_skill("sync-recordings")


def test_new_project_resolves_owner_from_config():
    assert "config read" in read_skill("new-project")


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_skill_reads_machine_decisions_from_prose(path):
    """#54 acceptance: timezone, owner slug, and adapter enablement come from
    config.json. The prose context files carry style and narrative only, so
    no skill may name the two files that used to hold machine decisions.

    `setup-my-brain` is exempt from the `tools-and-systems` half only, because
    it is the *writer* of the portfolio: the interview walks all five context
    stems by name and writes each through `context write`. Naming a file you
    fill is not reading config out of it. The `identity.md` half still binds
    every skill — nothing has any business reading the vault owner's name or
    timezone out of that file — and the invariant that actually matters for
    the writer is checked below, on the machine fields themselves.
    """
    text = path.read_text(encoding="utf-8")
    assert "identity.md" not in text, f"{path.parent.name} reads prose config"
    if path.parent.name != "setup-my-brain":
        assert "tools-and-systems" not in text, (
            f"{path.parent.name} reads prose config")


def test_setup_my_brain_writes_machine_decisions_through_config():
    """The other half of the rule above: the one skill allowed to name the
    prose files must still route timezone, the owner slug, adapter
    enablement and the account hints through `config write`, never into a
    context block — and must run the binding gate on what it wrote, which is
    the entire point of #54's ceremony."""
    text = read_skill("setup-my-brain")
    for field in ("--field owner", "--field timezone",
                  "--field adapters.plaud.enabled",
                  "--field adapters.m365.enabled",
                  "--field adapters.plaud.account_hint",
                  "--field adapters.m365.account_hint"):
        assert f"config write --vault \"$VAULT\" {field}" in text, (
            f"setup-my-brain must set {field} through config write")
    assert "config verify-account --vault \"$VAULT\" --adapter plaud" in text
    assert "config verify-account --vault \"$VAULT\" --adapter m365" in text


# #58 (F5, F6): a summary line is read by the vault owner, so it may not
# quote a frontmatter value, a result key, or a retired status at them. The
# retired-status check covers the whole file, not just the summary block.
RETIRED_OR_OPAQUE = (
    "needs-attention",
    "needs_attention_ticks",
    "Reviewed ticks folded",
    "reviewed: false)",
)


@pytest.mark.parametrize("name", ["sync-recordings", "evening-sync"])
def test_sync_summaries_speak_plainly(name):
    text = read_skill(name)
    for token in RETIRED_OR_OPAQUE:
        assert token not in text, (
            f"{name}: {token!r} is a field name or a retired status — say it "
            f"in words the vault owner can read"
        )
    assert "**Meetings you ticked as reviewed:**" in text, (
        f"{name}: the fold result needs a plain-speech summary line"
    )


# #110: dedup must run BEFORE the fetch (the measured $8/run failure was
# full event reads for candidates the ledger then discarded), and no adapter
# may reach before the vault's own start date.
#
# Task 3.3: the orchestrator no longer fetches the full event or derives
# ids itself — that moved into the worker (`m365 ids` then `sync dedup`,
# per `worker-contract.md`'s Fetching — M365 section). So SKILL.md's own
# ordering claim shrinks to "triage gates dispatch", and the ids-before-dedup
# ordering is asserted against the file that now owns it.
def test_sync_recordings_triages_m365_before_the_fetch():
    text = read_skill("sync-recordings")
    assert "sync m365-triage" in text, "the pre-fetch cache gate is missing"
    assert "sync m365-record" in text, (
        "outcomes must be recorded back or every run re-fetches")
    assert text.index("sync m365-triage") < text.index("### 6."), (
        "triage must gate dispatch, not follow it")
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert ref.index("m365 ids") < ref.index("sync dedup"), (
        "the worker contract must still derive ids before it dedups — "
        "SKILL.md no longer makes either call itself")


# Fix wave 2, CRITICAL: a run whose only m365 candidates are known
# cross-adapter duplicates dispatches zero worker batches and zero probes,
# so deferring the `duplicate` bucket's banking to "step 6's next per-batch
# outcomes call" means that call never happens — the loop survives forever.
def test_sync_recordings_step1_banks_duplicate_bucket_immediately():
    text = read_skill("sync-recordings")
    step1 = text.split("### 1.")[1].split("### 2.")[0]
    assert step1.index("sync m365-triage") < step1.index("sync m365-record"), (
        "the duplicate bucket must be banked right after triage, inside "
        "step 1 — not deferred to a batch call a zero-dispatch run never "
        "makes"
    )
    assert "never deferred" in step1, (
        "step 1 must mirror the probe-wave banking language: banked "
        "immediately, in its own call, never deferred"
    )


# The #122 failure shape — a fleet of extraction subagents each paid ~62k
# tokens to learn "nothing to write" — is prevented by triage gating
# dispatch and by workers fetching FIRST (a negative is a first-tool-call
# exit), not by centralizing fetches. The orchestrator stays the seen-events
# cache's only writer.
#
# Task 3.3: dedup used to be a second orchestrator-side gate, run once
# across the whole batch before dispatch. It is now the worker's own first
# move after deriving ids (one occurrence at a time), so there is no longer
# a pre-dispatch `sync m365-record` call to pin — the settled-outcomes
# banking it used to feed was deleted; workers surface everything, including
# already-synced, via outcome lines the batch banks after the fact.
def test_sync_recordings_dispatches_workers_only_after_triage_and_dedup():
    text = read_skill("sync-recordings")
    assert "survived triage" in text, (
        "the dispatch gate must condition dispatch on triage")
    assert '"forbidden"' in text, (
        "a cross-tenant 403 needs a recorded outcome or it refetches forever")
    dispatch = text.index("### 6.")
    assert text.index("sync m365-triage") < dispatch, (
        "triage must run before dispatch")
    # Fix wave 2: step 1 now also banks the triage-caught `duplicate` bucket
    # immediately (a run with zero worker/probe dispatch must still bank it
    # — see test_sync_recordings_step1_banks_duplicate_bucket_immediately),
    # so one "sync m365-record" occurrence now legitimately precedes
    # dispatch. There must still be at least one AFTER dispatch, for the
    # worker-batch banking that only runs once workers return.
    occurrences = [m.start() for m in re.finditer("sync m365-record", text)]
    assert any(idx > dispatch for idx in occurrences), (
        "there is no worker-batch settled-outcomes banking any more — "
        "some sync m365-record call must still happen after workers return")


# Cost round 2: workers run as the plugin's own agent types, which pin the
# model and (for plaud/inbox) the tool surface structurally — a live run
# measured 13 generic workers inheriting the session's full base context
# and, silently, its model. The m365 worker's tools stay open because that
# connector's server name differs per deployment and an agent allowlist
# cannot name it (verified: ToolSearch cannot load past the allowlist, and
# an unanchored mcp__* entry is ignored).
def test_sync_recordings_dispatch_names_the_worker_agent_types():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    step6_flat = re.sub(r"\s+", " ", step6)
    assert "second-brain:sync-worker" in step6_flat, (
        "step 6 must dispatch the plugin's worker agent type by name")
    assert "second-brain:sync-worker-m365" in step6_flat, (
        "m365 recordings need their own agent type — its tool surface differs")
    assert "model: sonnet" in step6_flat, (
        "the generic-subagent fallback must pass the model explicitly")

    agents_dir = SKILLS_DIR.parent / "agents"
    agent = (agents_dir / "sync-worker.md").read_text(encoding="utf-8")
    front = agent.split("---")[1]
    assert "name: sync-worker" in front
    assert "model: sonnet" in front, "the model mandate must be structural"
    assert "tools:" in front, "the plaud/inbox tool surface must be trimmed"
    for tool in ("ToolSearch", "Bash", "Read", "Write",
                 "mcp__plaud__get_transcript", "mcp__plaud__get_note"):
        assert tool in front, f"worker tools must include {tool}"

    m365 = (agents_dir / "sync-worker-m365.md").read_text(encoding="utf-8")
    m365_front = m365.split("---")[1]
    assert "name: sync-worker-m365" in m365_front
    assert "model: sonnet" in m365_front, (
        "the model mandate must be structural for the m365 worker too")
    assert "tools:" not in m365_front, (
        "the m365 worker's tools must stay open — a fixed list cannot name "
        "a per-deployment connector, and a wrong list silently kills the fetch")
    disallowed_lines = [
        line for line in m365_front.splitlines()
        if line.strip().startswith("disallowedTools:")]
    assert disallowed_lines, "the m365 worker must declare disallowedTools"
    disallowed = [
        name.strip()
        for name in disallowed_lines[0].split(":", 1)[1].split(",")]
    assert disallowed == M365_WORKER_DISALLOWED_TOOLS, (
        "the m365 worker's disallowedTools must match the issue #129 "
        "lever-1 list exactly, existing 8 first")

    for content in (agent, m365):
        body = re.sub(r"\s+", " ", content.split("---", 2)[2])
        assert "worker contract" in body and "outcome line" in body
        assert "next_cursor" not in content, (
            "fetch mechanics live in references/worker-contract.md, "
            "not the agent definition")


# Task 4.1: the haiku recheck probe. It reuses the m365 worker's exact
# disallowedTools list (the constant above is shared for exactly this
# reason) and its tool surface stays open for the same per-deployment
# connector reason the worker's does — only the model and the contract it
# reads differ.
def test_sync_probe_m365_agent_frontmatter():
    agents_dir = SKILLS_DIR.parent / "agents"
    probe = (agents_dir / "sync-probe-m365.md").read_text(encoding="utf-8")
    front = probe.split("---")[1]
    assert "name: sync-probe-m365" in front
    assert "model: haiku" in front, (
        "the probe is a cheap recheck — the model mandate must be structural")
    assert "tools:" not in front, (
        "the probe's tools must stay open — same per-deployment connector "
        "constraint as the m365 worker's read_resource")
    disallowed_lines = [
        line for line in front.splitlines()
        if line.strip().startswith("disallowedTools:")]
    assert disallowed_lines, "the probe must declare disallowedTools"
    disallowed = [
        name.strip()
        for name in disallowed_lines[0].split(":", 1)[1].split(",")]
    assert disallowed == M365_WORKER_DISALLOWED_TOOLS, (
        "the probe's disallowedTools must equal the m365 worker's exactly "
        "— it costs the same base-context tools, per issue #129 lever 1")

    body = re.sub(r"\s+", " ", probe.split("---", 2)[2])
    assert "probe contract" in body and "outcome line" in body
    assert "dispatched without a briefing" in body, (
        "the probe needs the same missing-briefing refusal as the worker"
    )


# PR B fix round 1, IMPORTANT-1: the agent definition still framed the probe
# as recheck-only ("Recheck probe for one M365 occurrence"; "previously
# settled no-transcript on a provisional basis"), contradicting
# probe-contract.md's own probe-first framing — every M365 first look is
# probed now, not just a recheck.
def test_sync_probe_m365_agent_is_framed_as_first_look_capable():
    agents_dir = SKILLS_DIR.parent / "agents"
    probe = (agents_dir / "sync-probe-m365.md").read_text(encoding="utf-8")
    description = probe.split("---")[1]
    body = re.sub(r"\s+", " ", probe.split("---", 2)[2])
    assert "previously settled" not in body.lower(), (
        "the agent must not frame every dispatch as a recheck of an "
        "already-settled no-transcript occurrence"
    )
    assert "recheck probe" not in description.lower(), (
        "the description must not call this a recheck-only probe"
    )
    assert "first look" in body.lower(), (
        "the body must say the probe also covers a first look, not just a "
        "recheck"
    )


def test_sync_probe_m365_contract_exists_and_covers_outcomes():
    ref = read_ref("sync-recordings", "probe-contract.md")
    assert "still-no-transcript" in ref
    assert "transcript-found" in ref
    assert "forbidden" in ref
    assert "no-access" in ref
    assert "fetch-error" in ref
    assert "auth-error" in ref
    assert "worker-contract.md" in ref, (
        "the probe contract must defer to the worker contract for fetch "
        "mechanics rather than duplicate them (one protocol, two depths)")
    assert "Fetching" in ref and "M365" in ref, (
        "the probe contract must point at the worker contract's M365 fetch "
        "section, not just name the file")


# PR B final-review fix, MINOR: a malformed event (non-UTC end, missing
# start.dateTime, another required key absent) makes `m365 ids` itself
# raise — that is not a transcript-existence classification the probe can
# make, so it must be a named fetch-error, not silently swallowed or
# misclassified as still-no-transcript.
def test_sync_probe_m365_contract_names_an_ids_refusal_as_fetch_error():
    ref = read_ref("sync-recordings", "probe-contract.md")
    flat = re.sub(r"\s+", " ", ref)
    ids_idx = flat.index("m365 ids --events")
    ids_clause = flat[ids_idx: ids_idx + 500]
    assert "fetch-error" in ids_clause, (
        "an m365 ids refusal must be named next to the ids call itself, "
        "not left implicit"
    )
    assert "non-UTC" in ids_clause or "end.timeZone" in ids_clause, (
        "the non-UTC end.timeZone refusal case must be named"
    )
    assert "start.dateTime" in ids_clause, (
        "the missing start.dateTime refusal case must be named"
    )
    outcomes_section = ref.split("## The outcome line")[1]
    assert "m365 ids" in outcomes_section, (
        "the outcome table's fetch-error row must also cover an ids "
        "refusal, not just transport failures"
    )


def test_sync_probe_m365_contract_never_extracts_or_touches_the_cache():
    ref = read_ref("sync-recordings", "probe-contract.md")
    assert "never" in ref.lower() and "meeting write" in ref, (
        "the probe must state it never calls meeting write")
    assert "seen-events cache" in ref, (
        "rule-8's carve-out and the never-touch-the-cache rule must both be "
        "stated explicitly, not implied")


def test_sync_recordings_worker_outcomes_are_a_closed_vocabulary():
    text = read_skill("sync-recordings")
    for token in ("written:", "no-transcript", "forbidden", "no-access",
                  "fetch-error", "auth-error", "possible-duplicate-of",
                  "already-synced", "skip-listed"):
        assert token in text, f"outcome vocabulary is missing {token}"
    assert "never writes the seen-events cache" in text, (
        "the single-writer rule must be stated")


def test_no_access_classification_prose_is_consistent_everywhere():
    """Defect #124: a 403 on the transcript read was banked as forbidden,
    terminal, on the claim "another tenant owns it" — false for the
    majority of an exec's calendar, meetings they attended but did not
    organise. Graph code 3003 ("does not have access to lookup meeting")
    distinguishes that case from a genuine cross-tenant 403, and the same
    classification wording must appear everywhere a worker or probe makes
    the 403 call: both contract files, and every SKILL.md mention."""
    texts = {
        "worker-contract.md": read_ref("sync-recordings", "worker-contract.md"),
        "probe-contract.md": read_ref("sync-recordings", "probe-contract.md"),
        "SKILL.md": read_skill("sync-recordings"),
    }
    for name, text in texts.items():
        assert "3003" in text, f"{name} is missing the Graph 3003 code"
        assert "does not have access to lookup meeting" in text, (
            f"{name} is missing the Graph error text")
        assert "no-access" in text, f"{name} is missing the no-access outcome"
        # Review finding #2 (round 1): a 403 with an unreadable body, or no
        # readable Graph code at all, had no rule. Orchestrator ruling: it
        # defaults to no-access — the safer default, since not-the-organizer
        # is the majority class and a true cross-tenant forbidden is the
        # rarity. Stated in the same sentence as the 3003 rule everywhere.
        assert "no readable Graph" in text, (
            f"{name} is missing the no-readable-Graph-code default rule")


def test_sync_recordings_filtered_buckets_include_no_access():
    """Review finding #1 (round 1): step 1's description of `filtered`
    enumerated only the pre-#124 buckets (written, skipped, forbidden,
    no-transcript) — no-access is a fifth bucket the CLI counts, and
    leaving it out of this sentence means the "M365 fetches saved" total
    the summary reports from it can silently drop no-access occurrences."""
    text = read_skill("sync-recordings")
    idx = text.index("`filtered` counts occurrences")
    clause = text[idx: idx + 300]
    assert "no-access" in clause, (
        "the filtered-buckets sentence must name the no-access bucket, "
        "the same way it names forbidden and no-transcript")


def test_sync_recordings_summary_names_m365_forget():
    """Review finding #3 (round 1): `sync m365-forget` was only named in
    cli.py and its own tests — nothing told a consultant it existed. The
    standing no-access sentence in the summary section must point at the
    recheck command right after it."""
    text = read_skill("sync-recordings")
    idx = text.index("no-access` count is greater than 0")
    clause = text[idx: idx + 700]
    assert "sync m365-forget" in clause, (
        "the standing no-access sentence must be followed by the "
        "m365-forget recheck recipe")
    assert "--outcome no-access" in clause


def test_sync_recordings_per_event_no_access_listing_covers_the_probe_too():
    """Review finding #7 (round 1): the per-event no-access listing named
    only the worker's reply; a probe's no-access reply (step 6, the probe
    banking bullets) settles the very same way and must be listed too."""
    flat = re.sub(r"\s+", " ", read_skill("sync-recordings"))
    idx = flat.index("Per event, list")
    clause = flat[idx: idx + 300]
    assert "probe" in clause.lower(), (
        "the per-event no-access listing must cover probe replies, not "
        "just worker replies")


def test_sync_recordings_worker_contract_carries_the_fetch_mechanics():
    text = read_skill("sync-recordings")
    assert "references/worker-contract.md" in text, (
        "step 6 must point workers at the contract file")
    step1 = text.split("## The three adapters")[1].split("### 6.")[0]
    assert "Never call" in step1 and "mcp__plaud__get_transcript" in step1, (
        "step 1 must forbid the orchestrator fetching")
    assert "next_cursor" not in step1, (
        "pagination mechanics belong to the worker contract, not step 1")
    assert "never fetched in this context" in step1, (
        "step 1 must state the M365 transcript is worker-fetched")
    ref = read_ref("sync-recordings", "worker-contract.md")
    for phrase in ("next_cursor", "transcript_url", "plaud reassemble",
                   "m365 reassemble", "sync collide", "meeting write",
                   "payload-contract.md", "verbatim"):
        assert phrase in ref, f"worker contract is missing {phrase}"


# Task 3.2: workers fetch their own M365 event and derive their own ids —
# the orchestrator no longer hands a worker a pre-read event file or a
# transcript_url by default.
def test_sync_recordings_worker_contract_m365_fetches_its_own_event():
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "calendar:///" in ref, (
        "the M365 fetch section must name the event URI form the worker "
        "reads verbatim")
    assert "already-synced:" in ref, (
        "a worker that dedups its own id must be able to settle as "
        "already-synced without fetching a transcript"
    )
    assert "recording-id:" in ref, (
        "written/possible-duplicate-of lines must carry the recording id "
        "the orchestrator banks against the seen-events ledger"
    )
    assert "Pre-fetched event variant" in ref, (
        "a briefing that already carries the event file and ids (PR 4's "
        "probe flow) must still be a documented variant, not dropped"
    )
    m365_fetch = ref.split("## Fetching — M365")[1].split(
        "## Attendees and confidence")[0]
    assert 'm365 ids --events "$SCRATCH/m365_event_<n>.ids-in.json"' in m365_fetch, (
        "ids must be derived from a one-element array, not the batch "
        "m365_events.json the orchestrator used to build"
    )
    assert m365_fetch.index("m365 ids") < m365_fetch.index("sync dedup"), (
        "ids must be derived before the dedup check")
    assert m365_fetch.index("sync dedup") < m365_fetch.index(
        'read_resource` call on the `transcript_url`'), (
        "dedup must gate the transcript fetch — an already-synced id stops "
        "before the transcript is ever read")


# PR review, round 2: `sync dedup` returns THREE buckets — new, synced, and
# skipped (syncjob.py:294-307) — but the contract only ever defined a reply
# for `synced`. An id on the permanent skip list that reached dedup got no
# settled outcome at all, so skip-list enforcement silently vanished once
# dedup moved worker-side.
def test_sync_recordings_worker_contract_m365_settles_the_skip_list_bucket():
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "skip-listed:" in ref, (
        "the worker must reply to a dedup `skipped` id with its own "
        "settled outcome, not silently drop the skip-list check")
    m365_fetch = ref.split("## Fetching — M365")[1].split(
        "## Attendees and confidence")[0]
    assert "skip-listed:" in m365_fetch, (
        "the skip-listed reply belongs in the fetch section, next to the "
        "already-synced reply it parallels")
    assert m365_fetch.index("sync dedup") < m365_fetch.index(
        "skip-listed:"), "skip-listed must follow the dedup call that finds it"
    outcomes_section = ref.split("## The outcome line")[1]
    assert "skip-listed:" in outcomes_section, (
        "the outcome table must list skip-listed as a real reply")
    assert '"skipped"' in outcomes_section, (
        "the contract must say a skip-listed line banks as a \"skipped\" "
        "outcome, the value seenevents.py's OUTCOMES actually accepts")
    assert "no `recording_id`" in outcomes_section, (
        "banking a skip-listed line must not require a recording_id — "
        "seenevents.py only requires one for a written outcome")
    assert "no-transcript-url" in m365_fetch, (
        "m365 ids skipping an event for no-transcript-url must map to the "
        "same no-transcript outcome as a transcript that came back empty")


# Intra-run stem-collision race: two workers in one run can capture the SAME
# meeting from two sources (a Plaud recording plus the meeting's own Teams
# transcript) and derive the same meeting-note stem. The payload filename is
# therefore keyed by the briefing's scratch stem — unique per worker by
# construction — never the meeting-note stem; the vault-note side of the race
# is settled inside `meeting write` (exclusive create + the
# cross-source-duplicate conflict), which both contract layers must surface.
def test_sync_recordings_payload_files_are_keyed_by_scratch_stem():
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "$SCRATCH/<stem>.payload.json" not in ref, (
        "the payload filename must never be the meeting-note stem — two "
        "workers syncing one meeting from two sources derive the same stem "
        "and race on the shared file")
    assert "$SCRATCH/<scratch stem>.payload.json" in ref, (
        "the payload file is keyed by the briefing's scratch stem, which "
        "the orchestrator makes unique per worker")
    assert "cross-source-duplicate" in ref, (
        "the worker must know a write can come back flagged "
        "cross-source-duplicate and mention the conflict kind in its "
        "outcome line")


def test_sync_recordings_counts_cross_source_duplicates():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    assert "cross-source-duplicate" in step6, (
        "step 6 must count a written cross-source-duplicate conflict under "
        "Possible duplicates, like confirmed-target — it is the same "
        "one-conversation-twice failure, caught at write time")


# ---------------------------------------------------------------------------
# A2 / A4 (prose halves): step 1's triage call gains --collide, banks its
# duplicate bucket as skipped with no dispatch; step 6's possible-duplicate-of
# handling settles unattended automatically through `sync settle-duplicate`
# instead of deferring; the watermark no longer holds for a deferred
# duplicate (there is not one any more); the summary reports what actually
# happened instead of a permanent "deferred" state.


def test_sync_recordings_step1_triage_call_passes_collide():
    text = read_skill("sync-recordings")
    step1 = text.split("### 1.")[1].split("### 2.")[0]
    assert "--collide" in step1, (
        "step 1's m365-triage invocation must pass --collide so a known "
        "cross-adapter duplicate never reaches dispatch"
    )
    assert '"outcome": "skipped"' in step1, (
        "a triage-time duplicate has no m365 id yet, so it banks as a "
        "plain skipped seen-events entry, not a written one"
    )
    assert "no dispatch" in step1.lower() or "never dispatch" in \
        step1.lower(), (
        "the triage-caught duplicate bucket must say plainly that it "
        "skips dispatch entirely"
    )


def test_sync_recordings_step6_possible_duplicate_uses_settle_duplicate():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    assert "sync settle-duplicate" in step6, (
        "the unattended (and the interactive drop-it) path must settle "
        "through the one CLI verb that validates first, then writes the "
        "skip-list line and (for M365) the seen-events entry, in order"
    )
    assert "sync unsettle-duplicate" in step6, (
        "the settle line must carry its own undo command — bare sync "
        "unskip is not enough for an M365 recording"
    )
    assert "collision: accepted" in step6, (
        "the interactive write-it-anyway path is a re-dispatch with this "
        "briefing field, not a bare meeting write --note of a stashed "
        "payload"
    )


def test_sync_recordings_no_longer_defers_cross_adapter_duplicates():
    text = read_skill("sync-recordings")
    assert "defers until an interactive run settles it" not in text, (
        "unattended duplicates are auto-skipped now, never deferred"
    )
    assert "Possible cross-adapter duplicates:** {N} — deferred" not in \
        text
    step1 = text.split("### 1.")[1].split("### 2.")[0]
    assert "and neither does a cross-adapter duplicate" not in step1, (
        "a cross-adapter duplicate always gets an outcome now (settled via "
        "sync settle-duplicate), so it is no longer grouped with the "
        "failed-transport no-outcome-line case"
    )


def test_sync_recordings_watermark_no_longer_holds_for_a_deferred_duplicate():
    text = read_skill("sync-recordings")
    watermark = text.split("**Advance the watermark")[1].split(
        "### 7.")[0]
    assert "deferred" not in watermark.lower(), (
        "there is no more deferred cross-adapter duplicate for the "
        "watermark to hold open for — it auto-settles instead"
    )
    assert "fetch-error" in watermark, (
        "the fetch-error retry sentence must survive this edit unchanged"
    )


def test_sync_recordings_summary_reports_cross_adapter_duplicates_skipped():
    text = read_skill("sync-recordings")
    assert "**Cross-adapter duplicates skipped:**" in text
    assert "sync unsettle-duplicate --id" in text
    assert "**Possible cross-adapter duplicates:**" not in text


# ---------------------------------------------------------------------------
# Fix round 1 on PR A. Task review findings, SKILL.md half.


def test_sync_recordings_cross_adapter_duplicates_has_two_undo_shapes():
    """IMPORTANT: a triage-caught duplicate has no recording_id yet — only
    the id-scoped `sync m365-forget --event-id --start-utc` can undo it. A
    worker-settled one has a real recording_id but, for M365, also carries
    a seen-events entry `sync unskip` alone cannot reach — `sync
    unsettle-duplicate` reverses both. Both shapes must be named."""
    text = read_skill("sync-recordings")
    assert "sync unsettle-duplicate --id" in text
    assert "sync m365-forget --event-id" in text
    assert "--start-utc" in text


def test_sync_recordings_no_longer_offers_bare_unskip_as_the_undo():
    """The incomplete fix from an earlier round: sync unskip alone leaves a
    worker-settled M365 duplicate's seen-events entry in place, permanently
    filtering the occurrence out of every future triage. Nothing in the
    skill may point at it as if it were sufficient any more."""
    text = read_skill("sync-recordings")
    assert "undo: `sync unskip --id" not in text
    assert "the undo is `sync unskip --id" not in text


def test_sync_recordings_drops_the_settled_from_either_net_claim():
    """The triage net never calls sync settle-duplicate at all — it banks
    straight through sync m365-record (no recording_id exists yet) — so a
    sentence claiming settle_duplicate settles occurrences 'from either
    net' is simply wrong."""
    text = read_skill("sync-recordings")
    assert "from either net" not in text


def test_sync_recordings_rules_block_attributes_duplicates_to_the_right_net():
    """Final re-review residual: the rules-block passage right after 'gets
    no outcome line' used to say every cross-adapter duplicate settles
    through `sync settle-duplicate` (step 6), 'whichever net catches it' —
    including the triage bucket, which has no recording_id and never
    reaches settle-duplicate at all (it banks via sync m365-record in step
    1, per test_sync_recordings_step1_banks_duplicate_bucket_immediately).
    The passage must attribute each net to its own verb."""
    text = read_skill("sync-recordings")
    idx = text.index("A cross-adapter duplicate always gets")
    clause = text[idx: idx + 500]
    assert "whichever net catches it" not in clause, (
        "the single shared verb framing must be gone"
    )
    assert "duplicate` bucket" in clause and "step 1" in clause, (
        "the triage-bucket path must be named as step 1's own"
    )
    assert clause.index("sync m365-record") < clause.index(
        "sync settle-duplicate"), (
        "the triage-bucket's sync m365-record must be named before "
        "settle-duplicate, matching which net actually uses which verb"
    )


def test_sync_recordings_possible_duplicates_reads_warnings_from_outcome_lines():
    """SPEC GAP: the summary's Possible-duplicates line must say the
    imprecise/weak-overlap warnings come from a worker's own outcome line
    (which now carries meeting write's warnings verbatim), not from
    'meeting write' as if the orchestrator ever saw its raw JSON directly."""
    text = read_skill("sync-recordings")
    idx = text.index("**Possible duplicates:**")
    clause = text[idx: idx + 400]
    assert "outcome line" in clause, (
        "the clause must say these warnings arrive via a worker's outcome "
        "line, not directly from meeting write"
    )


def test_sync_recordings_no_dated_internal_run_economics():
    """MINOR 7: internal run-economics detail (a specific measured date, a
    specific prior-run date, dollar figures) does not belong in a skill a
    client-facing consultant reads — keep the rule and a one-clause reason,
    drop the metrics."""
    text = read_skill("sync-recordings")
    assert "measured 2026-09-17" not in text
    assert "since 2026-09-15" not in text
    assert "26% problem" not in text
    assert not re.search(r"\$\d", text), (
        "no dollar figures belong in the shipped skill prose"
    )


def test_sync_recordings_workers_dispatched_line_names_duplicate_bucket():
    """Fix wave 2: a triage-caught duplicate is a fourth reason an m365
    candidate never reaches dispatch, alongside the cache, external, and
    not-ended reasons already enumerated — it must be named too."""
    text = read_skill("sync-recordings")
    idx = text.index("m365 candidates not dispatched were")
    clause = text[idx: idx + 200]
    assert "duplicate" in clause


def test_sync_recordings_worker_contract_m365_resolves_its_own_attendees():
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "person ensure" in ref, (
        "the worker must resolve attendees itself, not just copy a "
        "pre-resolved list from its prompt")
    assert "confidence-inputs" in ref, (
        "the briefing carries the two precomputed booleans, never a final "
        "confidence, for m365")
    assert "high-if-no-new-attendees" in ref
    assert "medium-if-at-most-one-new" in ref
    assert '"created"' in ref, (
        "the worker must read person ensure's own created field to count "
        "new people, not invent knownness semantics"
    )
    assert "new-people" in ref, (
        "settled outcome lines for a drafted m365 payload must report new "
        "people so the orchestrator can total them without reading the "
        "worker's scratch files"
    )


# Review round 1: `meeting write` requires confidence-reasons whenever
# confidence is set (meeting.py:105-109), one entry per closed-vocabulary
# group including attendees (meeting.py:116-134) — a worker that computes
# `confidence` itself must also compute the attendees-group reason itself,
# or every m365 write refuses.
def test_sync_recordings_worker_contract_m365_derives_the_attendees_reason():
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "confidence-reasons" in ref, (
        "confidence and confidence-reasons travel together — a contract "
        "that only computes confidence leaves meeting write refusing every "
        "m365 payload"
    )
    assert "all-attendees-known" in ref
    assert "new-attendees:{N}" in ref or "new-attendees:" in ref, (
        "the parameterized attendees-group reason must be named, with its "
        "N >= 1 floor"
    )
    section = ref.split("## Attendees and confidence")[1].split(
        "## Reassemble")[0]
    assert "confidence-reasons" in section, (
        "the derivation belongs in the Attendees and confidence section, "
        "next to the count it depends on"
    )
    extract = ref.split("## Extract and write")[1].split(
        "```bash")[0]
    assert "confidence-reasons" in extract, (
        "the Extract and write exception clause must name the "
        "confidence-reasons attendees entry as worker-derived too, not "
        "just attendees and confidence"
    )

    payload_ref = read_ref("sync-recordings", "payload-contract.md")
    assert "confidence-reasons" in payload_ref.split("```json")[0], (
        "payload-contract.md's routing-fields paragraph must carry the "
        "same M365 exception as worker-contract.md, or a worker reading "
        "both files hits a direct contradiction"
    )


def test_sync_recordings_worker_contract_seenevents_citation_is_accurate():
    """PR #216 review: a line-number citation rots on every commit that
    touches the file above it (this PR's own collide/settle-duplicate
    additions already shifted this exact citation twice). Cite by symbol
    instead — `seenevents._validate_outcome`'s `written` branch — and
    forbid every `seenevents.py:<digits>` line citation anywhere in the
    contract, not just the one this citation used to be."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "seenevents._validate_outcome" in ref, (
        "the written/recording_id enforcement must be cited by symbol — "
        "_validate_outcome's written branch — not by line number"
    )
    assert "written" in ref.split("seenevents._validate_outcome")[1][:40], (
        "the citation must name the written branch specifically, not just "
        "the function"
    )
    assert not re.search(r"seenevents\.py:\d", ref), (
        "no seenevents.py:<line> citation may remain anywhere in the "
        "contract — line numbers rot on every commit"
    )


# ---------------------------------------------------------------------------
# PR A / A3 (prose half): the worker contract's M365 collision check moves
# before the transcript fetch (`sync collide`, right after `m365 ids` derives
# recorded_local/event_duration_min), replacing the old post-reassemble
# section that drafted a payload nobody was allowed to write.


def test_sync_recordings_worker_contract_collide_runs_before_transcript_read():
    ref = read_ref("sync-recordings", "worker-contract.md")
    m365_fetch = ref.split("## Fetching — M365")[1].split(
        "## Attendees and confidence")[0]
    assert "sync collide" in m365_fetch, (
        "the collision check must move into the Fetching — M365 section, "
        "before the transcript is ever read"
    )
    assert m365_fetch.index("sync collide") < m365_fetch.index(
        'read_resource` call on the `transcript_url`'), (
        "sync collide must run before the transcript read it is meant to "
        "save the cost of"
    )
    assert m365_fetch.index("sync dedup") < m365_fetch.index("sync collide"), (
        "collide follows dedup — an already-synced or skip-listed id never "
        "reaches the collision check at all"
    )


def test_sync_recordings_worker_contract_ids_call_carries_the_timezone():
    ref = read_ref("sync-recordings", "worker-contract.md")
    m365_fetch = ref.split("## Fetching — M365")[1].split(
        "## Attendees and confidence")[0]
    assert 'm365 ids --events "$SCRATCH/m365_event_<n>.ids-in.json" ' \
        '--timezone <timezone from your prompt>' in m365_fetch, (
        "ids must be derived with the timezone so the result carries "
        "recorded_local/event_duration_min for the collide check right "
        "after it"
    )


def test_sync_recordings_worker_contract_possible_duplicate_no_longer_names_payload():
    """The old post-reassemble collision check drafted the payload before
    reporting a collision ('payload at <path>'); the new pre-fetch check
    stops before anything is drafted at all, and the write-time refusal
    (meeting write's own cross-adapter-duplicate) never had a payload path
    to report either — a human re-dispatches a fresh worker instead of
    reusing one."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "payload at" not in ref
    assert "Draft the payload anyway" not in ref


def test_sync_recordings_worker_contract_meeting_write_cross_adapter_refusal():
    """A1 makes `meeting write` itself refuse a precise cross-adapter
    collision, for every worker type — the contract's Extract and write
    section (shared by all adapters) must say what to do about it, and how
    the collision:accepted re-dispatch skips the early check and passes
    --accept-collision."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    extract = ref.split("## Extract and write")[1].split(
        "## The outcome line")[0]
    assert "cross-adapter-duplicate" in extract, (
        "the write-time refusal kind must be named in Extract and write"
    )
    assert "--accept-collision" in extract, (
        "a collision:accepted re-dispatch passes --accept-collision to "
        "meeting write"
    )
    assert "collision: accepted" in ref, (
        "the briefing field name that triggers the re-dispatch path must "
        "be named somewhere in the contract"
    )
    outcome_table = ref.split("## The outcome line")[1]
    assert "existing:" in outcome_table, (
        "the possible-duplicate-of row must name the existing id clause "
        "both the pre-fetch and the write-time collision reply carry"
    )


# ---------------------------------------------------------------------------
# Fix round 1 on PR A. Task review findings, worker-contract.md half.


def test_sync_recordings_worker_contract_collision_check_uses_strong_wording():
    """CRITICAL: collide's 15-minute grace makes a merely-adjacent meeting
    a "precise" match with ~zero real overlap; the collision check must act
    on `strong` matches only, and say so."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    m365_fetch = ref.split("## Fetching — M365")[1].split(
        "## Attendees and confidence")[0]
    assert "flagged `strong: true`" in m365_fetch, (
        "the collision check must gate on collide's own strong field, "
        "named explicitly, not just 'precise'/non-imprecise"
    )
    assert "precise (non-`imprecise`) match whose" not in m365_fetch, (
        "the old wording that acted on any precise match must be gone"
    )


def test_sync_recordings_worker_contract_skips_collision_without_duration():
    """IMPORTANT: event_duration_min is only present when the event has an
    end; without it there is nothing to query sync collide with, and the
    worker must skip its own check rather than crash or guess — the
    write-time net (meeting write's own check) still applies regardless."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    m365_fetch = ref.split("## Fetching — M365")[1].split(
        "## Attendees and confidence")[0]
    assert "event_duration_min" in m365_fetch and "absent" in m365_fetch
    flat = re.sub(r"\s+", " ", m365_fetch)
    assert "skip" in flat.lower() and "collision check" in flat.lower(), (
        "the contract must say to skip the collision check (not the whole "
        "step) when event_duration_min is absent"
    )


def test_sync_recordings_worker_contract_pre_fetched_variant_runs_ids_locally():
    """IMPORTANT: the pre-fetched variant used to skip both the event fetch
    AND id derivation, so it never had recorded_local/event_duration_min for
    its own collision check at all. It must still run `m365 ids` locally
    (a CLI call on the briefing's own event file, not a Graph call — the
    single-call ceiling stands) and cross-check the result against what the
    briefing already named."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    variant = ref.split("**Pre-fetched event variant.**")[1].split(
        "## Attendees and confidence")[0]
    flat = re.sub(r"\s+", " ", variant)
    assert "m365 ids" in flat, (
        "the pre-fetched variant must still run m365 ids locally to get "
        "recorded_local/event_duration_min for its own collision check"
    )
    assert "skip steps 1 and 2" not in flat, (
        "the variant no longer skips step 2 — only step 1, the Graph fetch"
    )
    assert "skip step 1" in flat or "skip only step 1" in flat, (
        "the variant must say it skips only the Graph event fetch"
    )
    assert "fetch-error: pre-fetched ids disagree" in flat, (
        "a mismatch between the locally-derived ids and the briefing's own "
        "must be a named, reportable failure, not silently trusted"
    )
    assert "not a Graph call" in flat or "not a graph call" in flat.lower(), (
        "must state the local m365 ids call does not count against the "
        "single-Graph-call-per-step ceiling"
    )
    assert "events-*array* file" in flat or "array file" in flat.lower(), (
        "the ids call must be paired explicitly with the events-array "
        "file, never the bare event object — m365 ids refuses anything "
        "that is not a JSON array"
    )
    ids_idx = flat.index("m365 ids")
    ids_clause = flat[ids_idx: ids_idx + 120]
    assert "array" in ids_clause.lower(), (
        "the m365 ids invocation itself must be immediately qualified as "
        "using the array file"
    )


def test_sync_recordings_worker_contract_written_appends_meeting_write_warnings():
    """SPEC GAP: meeting write can return `warnings` (an accepted collision,
    an imprecise/weak-overlap match) that never reached the summary because
    nothing told the worker to carry them into its outcome line — exactly
    the same obligation reassemble's own warnings already carry."""
    ref = read_ref("sync-recordings", "worker-contract.md")
    extract = ref.split("## Extract and write")[1].split(
        "## The outcome line")[0]
    flat = re.sub(r"\s+", " ", extract)
    assert "warnings" in flat and "verbatim" in flat, (
        "Extract and write must say to carry meeting write's own warnings "
        "into the outcome line verbatim, the same way Reassemble's are"
    )


def test_sync_recordings_states_the_start_date_bound():
    text = read_skill("sync-recordings")
    assert "sync.start-date" in text
    assert 'dates window --vault "$VAULT"' in text, (
        "the clamp only holds when the skill passes the vault")


def test_sync_recordings_start_date_shorthand_names_a_real_flag():
    """#121: the illustrative `dates window --vault "$VAULT"` shorthand
    reads as a runnable command, but the CLI requires --start (or
    --trailing-days) — a session that took it literally burned a retry
    loop on exit 2 before reading the help. Every mention must carry the
    missing flag, or say "with the item's timestamp", inline — checked
    with re.finditer over ALL occurrences (review finding #6, round 1),
    not just the first, so a reintroduced bare shorthand anywhere in the
    file fails this test rather than hiding behind an earlier, fixed one."""
    text = read_skill("sync-recordings")
    matches = list(re.finditer(r'dates window --vault "\$VAULT"', text))
    assert matches, "no dates window --vault \"$VAULT\" mention found at all"
    for match in matches:
        tail = text[match.end(): match.end() + 200]
        assert ("--start" in tail or "--trailing-days" in tail
                or "item's timestamp" in tail
                or "item's own timestamp" in tail), (
            f"bare shorthand at offset {match.start()} must name a real "
            "flag or the item's timestamp inline, never look like a "
            "complete, runnable call on its own"
        )


@pytest.mark.parametrize("name", ["setup-my-brain", "provision-vault",
                                  "upgrade-vault"])
def test_provisioning_writes_the_sync_start_date(name):
    # upgrade-vault is the tune-up path the CHANGELOG points pre-existing
    # vaults at; it must resolve the entry too, not just report it.
    text = read_skill(name)
    assert "--field sync.start-date" in text, (
        f"{name} must stamp the vault's horizon (#110)")


@pytest.mark.parametrize("name", ["setup-my-brain", "upgrade-vault"])
def test_default_config_missing_list_matches_config_read(name):
    """Both skills teach the agent what a template-default vault's `missing`
    looks like, as a hard "exactly" — a stale list reads as an anomaly at the
    exact moment the skill is telling the agent to trust it."""
    text = read_skill(name)
    assert '`["owner", "sync.start-date", "timezone"]`' in text, (
        f"{name}: the fresh-vault missing list drifted from config.read()")
    assert '`["owner", "timezone"]`' not in text, (
        f"{name}: still claims the pre-#110 two-entry missing list")


def test_sync_recordings_routes_non_meetings_to_a_type_note():
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "type: note" in text, "no non-meeting destination documented"
    assert "calendar-not-applicable" in text
    # The ambiguity rule is the load-bearing sentence: a wrongly written note
    # sits in Triage, a wrongly parked file is invisible.
    assert "write the `note`" in text


def test_sync_recordings_sweeps_the_inbox():
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "sync archive" in text, "the sweep the README promises is missing"
    assert "90-archive/inbox/" in text


def extract_disclosure_blockquote(text: str) -> str:
    """Pull the `> `-quoted disclosure paragraph out of a skill body.

    Robust to reflowing (line breaks inside the blockquote are unwrapped and
    whitespace is collapsed) but not to a wording change — the joined result
    is compared for exact equality against `feedback.DISCLOSURE`, the single
    source of truth the CLI stamps into every posted issue.
    """
    lines = text.splitlines()
    start = None
    marker = "What this report contains and how it is used"
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">") and marker in line:
            start = i
            break
    assert start is not None, "disclosure blockquote not found"
    collected = []
    for line in lines[start:]:
        stripped = line.lstrip()
        if not stripped.startswith(">"):
            break
        collected.append(stripped[1:].strip())
    joined = " ".join(collected)
    return re.sub(r"\s+", " ", joined).strip()


@pytest.mark.parametrize("name", ["report-feedback", "health-check"])
def test_disclosure_blockquote_matches_feedback_disclosure(name):
    """M1: the disclosure shown at every share nudge must be the exact text
    `feedback.send` stamps into the posted issue body — a skill that drifts
    from it would promise the vault owner one thing and deliver another."""
    text = read_skill(name)
    extracted = extract_disclosure_blockquote(text)
    assert extracted == feedback.DISCLOSURE, (
        f"{name}: rendered disclosure does not match feedback.DISCLOSURE "
        "word-for-word"
    )


def test_sync_recordings_no_longer_asks_the_user_to_archive_by_hand():
    """F0: the skill used to tell the user to do the thing the plugin
    promised to do and never did."""
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "so the user can archive them" not in text


def test_sync_recordings_parks_through_the_one_call_that_records_why():
    """A park is a permanent suppression. The skill must reach it through
    `sync park`, which cannot run without a reason — not through a bare
    `sync skip` plus `sync archive`, which can."""
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "sync park" in text
    assert "--reason" in text
    park_block = text.split("sync park", 1)[1][:400]
    assert "--reason" in park_block, "the park invocation itself must carry --reason"


def _evening_sync() -> str:
    return read_skill("evening-sync")


def _normalized(text: str) -> str:
    # Markdown prose is hard-wrapped for readability, so a multi-word phrase
    # can legitimately span a line break. Collapse whitespace runs to a
    # single space before matching so re-wrapping the prose (an ordinary
    # markdown edit) can never flip one of these assertions — the check is
    # about the words, not about where the lines happen to break.
    return re.sub(r"\s+", " ", text)


def test_evening_sync_states_the_no_back_fill_rule():
    # Decision 16: one catch-up note covers the window; the vault owner is told so.
    text = _evening_sync().lower()
    assert "back-fill" in text, (
        "the no-back-fill decision was real but unstated, which is the "
        "finding — the skill has to say it"
    )


def test_evening_sync_consumes_the_catchup_facts_rather_than_deriving_them():
    text = _evening_sync()
    for key in ("business_days_missed", "over_threshold",
                "recap_detail_from", "business_days_not_detailed"):
        assert key in text, f"stage 1 must consume {key} from dates plan"


def test_evening_sync_payload_example_carries_the_recap_window():
    # recap_window is optional in the CLI for backward compatibility, so
    # this test is the only thing keeping the idempotence guard wired up.
    text = _evening_sync()
    assert '"recap_window"' in text, (
        "without recap_window in the payload there is no fingerprint and no "
        "catch-up banner — the guard is silently off"
    )


def test_evening_sync_mandates_wikilinks_for_looked_up_names():
    # Anchored on the mandate sentence itself, not on the word "wikilink":
    # that already appears in stage 4, and "never" appears 19 times, so the
    # loose form of this assertion passes before the mandate is written.
    # Matched against normalized whitespace: both phrases are multi-word and
    # markdown hard-wrapping could otherwise split either across a line
    # break the next time this paragraph is reflowed.
    text = _normalized(_evening_sync())
    assert "never a name you recalled" in text, (
        "decision 19: a plain-prose name cannot be validated by anything, so "
        "the skill has to require the linked form in stage 6"
    )
    assert "refuses a link that resolves to nothing" in text, (
        "the skill has to say what the CLI does about it, or a model reads "
        "the mandate as advice"
    )


def test_evening_sync_recovers_from_a_link_refusal_rather_than_ending_the_run():
    # `_check_links` raises before a byte is written, so a stage-6 refusal
    # leaves tomorrow with no note — found by the vault owner next morning, and
    # flatly against both the failure-isolated stage promise and rule 7
    # ("a refused calendar still writes the note"). The CLI cannot fix this
    # for itself: only the caller knows which link to drop or rename. So the
    # recovery has to be written down here, bounded, or a model improvises.
    # Normalized whitespace: both anchors are multi-word and this paragraph
    # will be reflowed sooner or later.
    text = _normalized(_evening_sync()).lower()
    assert "retry the write once" in text, (
        "stage 6 must say to fix the link and retry once — an unbounded "
        "retry loop is the other way this goes wrong"
    )
    assert "never end the run without a note" in text, (
        "the bound needs the reason attached, or a model reads the retry as "
        "optional and exits on the refusal"
    )


def test_evening_sync_retry_fixes_every_named_offender_not_just_the_first():
    # Issue #78: `_check_links` used to raise on the first offender, so a
    # recap with two independently-bad links exhausted the single retry on
    # the first and still failed on the second — no note for tomorrow. The
    # CLI now names every offender in one error; the skill has to say the
    # retry must address all of them, or a model fixes only the first link
    # it sees and repeats the original bug on the second retry attempt.
    # Normalized whitespace: this is a multi-word phrase absent from the
    # file today (verified with grep before writing this test), and this
    # paragraph will be reflowed sooner or later.
    text = _normalized(_evening_sync()).lower()
    assert "fix or drop every link the error names" in text, (
        "the guard paragraph must say to act on every named offender, not "
        "just the first, so the single retry is always enough"
    )


def test_evening_sync_states_unattended_catchup_behaviour():
    section = _evening_sync().split("## Unattended mode", 1)
    assert len(section) == 2, "evening-sync has no Unattended mode section"
    body = section[1].split("\n## ", 1)[0].lower()
    assert "catch-up" in body or "catchup" in body, (
        "unattended mode caps and flags rather than composing a mega-recap; "
        "finding F4 is that this mode has no coverage at all"
    )


def test_evening_sync_stage4_dispatch_is_a_blocking_batch_cap():
    # A live run dispatched a 4th subagent within 30 seconds of narrating
    # "dispatching the first 3", then spawned the batch in the background and
    # polled it for ~12 minutes despite this skill's prior "never poll"
    # warning. The cap now has to be structural: one message of blocking
    # calls IS the batch, and the batch returning IS the only signal to send
    # the next one. Anchored on the operative sentence, not just "blocking"
    # or "batch", which both already appear elsewhere in this stage.
    text = _normalized(_evening_sync())
    stage4 = text.split("## Stage 4", 1)[1].split("## Stage 5", 1)[0]
    assert "at most 3" in stage4 and "blocking Agent calls" in stage4, (
        "stage 4 must say the batch is capped at 3 blocking Agent calls, "
        "not just that dispatch happens 'up to 3 in parallel'"
    )
    assert "no background mode for this fan-out" in stage4, (
        "the instruction must foreclose background dispatch outright, not "
        "just warn against polling it afterward"
    )


def test_sync_recordings_step6_dispatch_is_a_blocking_batch_cap():
    text = _normalized(read_skill("sync-recordings"))
    step6 = text.split("### 6.", 1)[1].split("### 7.", 1)[0]
    assert "at most ~4" in step6 and "blocking Agent calls" in step6, (
        "step 6 must say the worker/probe batches are capped at ~4 blocking "
        "Agent calls, mirroring evening-sync stage 4's restructuring"
    )
    assert "no background mode for this fan-out" in step6, (
        "the instruction must foreclose background dispatch outright, not "
        "just warn against polling it afterward"
    )


# The discovery-window regression: the skill used to prescribe a bare
# `dates window --vault "$VAULT"` for step-1 discovery — an invocation that
# does not parse (--start was required), so orchestrators improvised windows
# that reached a week into the future. test_every_cli_invocation_named_by_a_
# skill_exists only checks (group, action) pairs exist, which is exactly how
# that shipped. Two pins close the hole: every fenced `dates window`
# invocation must parse against the real argparse parser, and the M365
# discovery paragraph must prescribe the trailing form as a fenced block,
# not as prose.

FENCED_BLOCK_RE = re.compile(r"```(?:bash)?\n(.*?)```", re.DOTALL)
PLACEHOLDERS = {'"$VAULT"': "/placeholder/vault", "<tz>": "Europe/Brussels",
                "<next_business_day>": "2026-09-21"}


def fenced_invocations(text: str, subcommand: str):
    """Every fenced `<group> <action>` invocation in a skill, as argv tokens
    with the prose placeholders substituted — so argparse can be asked
    whether the skill prescribes something the CLI actually accepts."""
    import shlex
    found = []
    for block in FENCED_BLOCK_RE.findall(text):
        for line in block.replace("\\\n", " ").splitlines():
            if subcommand not in line:
                continue
            command = line[line.index(subcommand):]
            for token, value in PLACEHOLDERS.items():
                command = command.replace(token, value)
            found.append(shlex.split(command))
    return found


def fenced_dates_window_invocations(text: str):
    return fenced_invocations(text, "dates window")


@pytest.mark.parametrize("subcommand", ["dates window", "m365 agenda", "discover window",
                                        "discover build", "discover answer",
                                        "discover check", "discover clock-start",
                                        "discover clock-check"])
@pytest.mark.parametrize("path", SKILL_FILES + REF_FILES,
                         ids=lambda p: p.parent.name)
def test_every_fenced_invocation_of_a_parsed_subcommand_parses(path, subcommand):
    parser = cli.build_parser()
    for tokens in fenced_invocations(path.read_text(encoding="utf-8"), subcommand):
        try:
            parser.parse_args(tokens)
        except SystemExit:
            pytest.fail(
                f"{path.parent.name} prescribes a {subcommand} invocation "
                f"argparse refuses: {' '.join(tokens)}")


def test_evening_sync_stage5_leaves_the_heading_time_to_the_cli():
    """The 2026-09-21 daily note showed every meeting two hours early: the
    connector answers starts as a UTC wall clock, and Stage 5 asked the
    model, in prose, to "render times in the vault owner's local timezone".
    One run copied UTC. The time now comes from `m365 agenda` and travels
    into the payload verbatim — the prose instruction must not come back."""
    text = (SKILLS_DIR / "evening-sync" / "SKILL.md").read_text(encoding="utf-8")
    stage5 = text[text.index("## Stage 5"):text.index("## Stage 6")]
    assert fenced_invocations(stage5, "m365 agenda"), (
        "Stage 5 must prescribe a fenced `m365 agenda` invocation")
    assert "--timezone <tz>" in stage5 and "--date <next_business_day>" in stage5, (
        "the agenda call must carry the vault timezone and the local day")
    assert "verbatim" in stage5 and "`time`" in stage5, (
        "Stage 5 must say the agenda's `time` goes into the payload verbatim")
    assert "render times in the vault owner's local timezone" not in stage5, (
        "timezone conversion is the CLI's job, never a prose instruction")
    assert "start.dateTime" in stage5, (
        "Stage 5 must name the field the orchestrator is not to read")


def test_sync_recordings_discovery_window_is_a_fenced_trailing_invocation():
    text = read_skill("sync-recordings")
    m365 = text.split("**Microsoft 365**")[1].split("### 2.")[0]
    invocations = fenced_dates_window_invocations(m365)
    assert invocations, (
        "step 1 must prescribe the discovery window as a fenced invocation — "
        "a prose-only mention is how a non-parsing call shipped")
    assert any("--trailing-days" in tokens and "--vault" in tokens
               for tokens in invocations), (
        "the discovery window must be the trailing form, vault-clamped")


def test_sync_recordings_reports_deferred_future_meetings():
    text = read_skill("sync-recordings")
    assert "not-ended" in text, (
        "triage's deferred-future bucket must be surfaced, not lumped into "
        "no-transcript outcomes")
    assert text.index("not-ended") < text.index("### 2."), (
        "the deferral is a step-1 triage fact")


def test_sync_recordings_extends_verbatim_rule_to_event_json():
    rules = read_skill("sync-recordings").split("## The three adapters")[0]
    flat = re.sub(r"\s+", " ", rules)
    assert "event's kept keys" in flat, (
        "rule 8 must cover event reads — a live run re-typed events from "
        "memory and garbled transcript URLs and ids before self-correcting. "
        "Events are trimmed to specific keys now, so the obligation is no "
        "longer phrased as 'full-event JSON'")


# Task 4.2: the triage split that routes a recheck-no-transcript survivor to
# a probe instead of straight into the routing extract a normal survivor
# gets.
def test_sync_recordings_triage_splits_fetch_by_reason_for_probes():
    text = read_skill("sync-recordings")
    step1 = text.split("### 1.")[1].split("### 2.")[0]
    assert '"unseen"' in step1 or "unseen" in step1
    assert "unkeyed" in step1
    assert "recheck-no-transcript" in step1
    assert step1.index("sync m365-triage") < step1.index("recheck-no-transcript"), (
        "the reason split is read off sync m365-triage's own fetch list")
    flat = re.sub(r"\s+", " ", step1)
    assert "probe dispatch" in flat.lower(), (
        "a recheck-no-transcript survivor must be named as routed to the "
        "probe dispatch list, not the ordinary routing extract"
    )


# PR B (probe-first): #173's parked blocker is met (external-organizer
# filter from #124 already exists), and the field measurement it asked for
# found 5 of 8 M365 dispatches in one run ending without a transcript.
# Every M365 first look becomes a Haiku probe now, not just a recheck.
def test_sync_recordings_every_fetch_reason_is_probed():
    text = read_skill("sync-recordings")
    step1 = text.split("### 1.")[1].split("### 2.")[0]
    flat = re.sub(r"\s+", " ", step1)
    assert "ordinary worker in step 6" not in flat, (
        "an unseen/unkeyed entry must no longer be described as getting a "
        "worker directly — it goes onto the probe dispatch list first, "
        "same as a recheck"
    )
    split_idx = flat.index("probe dispatch list")
    clause = flat[max(0, split_idx - 400):split_idx]
    for reason in ("unseen", "unkeyed", "recheck-no-transcript"):
        assert reason in clause, (
            f"the probe dispatch list must be described as holding every "
            f"fetch reason, missing {reason}"
        )


def test_sync_recordings_no_unseen_worker_dispatch():
    text = read_skill("sync-recordings")
    workflow = text.split("## The three adapters")[1].split("### 7.")[0]
    flat = re.sub(r"\s+", " ", workflow)
    assert "no m365 worker is ever dispatched" in flat.lower(), (
        "the dispatch gate must state plainly that no M365 worker is ever "
        "dispatched except through a probe's promotion"
    )
    assert "a worker is dispatched only for the ones a probe promotes" in (
        flat.lower()), (
        "M365 worker dispatch must be conditioned on probe promotion, "
        "never on triage survival alone"
    )


def test_sync_recordings_step6_dispatches_probes_before_worker_batches():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    assert "second-brain:sync-probe-m365" in step6, (
        "step 6 must dispatch the probe agent type by name")
    probe_idx = step6.index("second-brain:sync-probe-m365")
    worker_idx = step6.index("second-brain:sync-worker-m365")
    assert probe_idx < worker_idx, (
        "probes dispatch before the ordinary worker batches, per the brief")
    flat = re.sub(r"\s+", " ", step6)
    assert "references/probe-contract.md" in flat, (
        "the probe briefing must point at its own contract file"
    )
    assert "m365_probe_<n>" in flat, (
        "the probe's scratch stem must be named so scratch sweep catches it"
    )
    assert "up to ~4" in flat, (
        "probes dispatch in the same bounded batch size as workers"
    )


def test_sync_recordings_probe_outcomes_are_handled():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    flat = re.sub(r"\s+", " ", step6)
    assert "still-no-transcript" in flat
    assert "transcript-found" in flat
    assert '"outcome": "no-transcript"' in flat, (
        "a still-no-transcript probe reply banks as a no-transcript "
        "outcome, refreshing checked_at and restarting the 6h hold"
    )
    assert "checked_at" in flat and "6h" in flat, (
        "the still-no-transcript bank must be tied explicitly to refreshing "
        "the recheck hold"
    )
    assert "pre-fetched event variant" in flat.lower(), (
        "a transcript-found probe must hand its follow-up worker the "
        "worker contract's pre-fetched event variant, not a fresh fetch"
    )
    assert "dedup" in flat, (
        "the pre-fetched variant still starts the follow-up worker at "
        "dedup — the dedup gate is never skipped"
    )
    # transcript-found is a real fetch survivor: it must still get the same
    # routing extract and step 3-5 signals an unseen/unkeyed survivor gets.
    found_clause = flat[flat.index("transcript-found"):]
    assert "m365_routing.json" in found_clause
    assert "like any" in found_clause or "same as any" in found_clause, (
        "the brief requires this to read as 'route it like any fetch "
        "survivor', not as a special case"
    )
    assert "recording_id" in found_clause and "transcript_url" in found_clause, (
        "the promotion briefing must carry both recording_id and "
        "transcript_url — the promoted worker's pre-fetched cross-check "
        "(m365 ids run locally against the probe's event file) needs both "
        "to detect a mismatch"
    )


# PR B fix round 1, IMPORTANT-2: SKILL.md's promotion briefing wrongly told
# the orchestrator the promoted worker's OWN scratch stem was m365_probe_<n>
# — contradicting worker-contract.md, which names m365_event_<n>.ids-in.json
# / .dedup.json / .transcript.json literally, and scopes the probe's stem to
# the event *file* it hands the worker, never the worker's own stem.
def test_sync_recordings_promoted_worker_keeps_its_own_scratch_stem():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    flat = re.sub(r"\s+", " ", step6)
    assert "m365_probe_<n>.event.json" in flat, (
        "the promotion briefing must name the probe's event file path "
        "explicitly"
    )
    assert "m365_event_<n>" in flat, (
        "the promoted worker's own scratch stem must still be named as "
        "m365_event_<n>, never the probe's"
    )
    assert "the scratch stem is the probe's own" not in flat.lower(), (
        "the worker's scratch stem must never be described as the "
        "probe's — only the event file it reads is the probe's"
    )
    assert "never `m365_event_<n>`" not in flat.lower(), (
        "must not claim the worker's stem is anything other than "
        "m365_event_<n>"
    )


# PR B final-review fix, CRITICAL: `m365 ids` refuses anything but a JSON
# array, but the promotion briefing only ever named the probe's event
# *object* file (m365_probe_<n>.event.json) — the array the probe also
# wrote (m365_probe_<n>.events.json, per probe-contract.md step 2) never
# reached the worker. Both paths must be named, and it must be clear which
# call each feeds.
def test_sync_recordings_promotion_briefing_names_both_probe_event_paths():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    flat = re.sub(r"\s+", " ", step6)
    assert "m365_probe_<n>.event.json" in flat, (
        "the object file (for reassemble/attendees) must be named"
    )
    assert "m365_probe_<n>.events.json" in flat, (
        "the one-element array file (for the worker's own m365 ids call) "
        "must also be named — m365 ids refuses a bare object"
    )
    events_idx = flat.index("m365_probe_<n>.events.json")
    events_clause = flat[max(0, events_idx - 50): events_idx + 250]
    assert "ids" in events_clause, (
        "the array file must be described next to the ids call it feeds, "
        "not left for the reader to guess which file goes where"
    )
    event_idx = flat.index("m365_probe_<n>.event.json")
    event_clause = flat[max(0, event_idx - 100): event_idx + 250]
    assert "reassemble" in event_clause or "attendee" in event_clause, (
        "the object file must be described next to what it feeds "
        "(reassemble / attendee reading), distinct from the array file"
    )


# PR B fix round 2 (resolving the tension flagged in fix round 1): under
# probe-first, an m365 row on the step-5 plan has already been promoted, so
# its recording_id IS known (the promoting probe's transcript-found line
# carried it) — "there is no recording id for it yet at step 5" is no
# longer true, and dropping the row must both bank the seen-events entry
# (unchanged mechanism) and write the permanent skip-list line, since the
# id is now known and the skip list is what survives the cache's own
# retention horizon.
def test_sync_recordings_step5_m365_drop_is_a_two_write_path():
    text = read_skill("sync-recordings")
    step5 = text.split("### 5.")[1].split("### 6.")[0]
    flat = re.sub(r"\s+", " ", step5)
    assert "no recording id for it yet at step 5" not in flat.lower(), (
        "the stale claim must be gone — a promoted row's recording_id is "
        "already known by step 5"
    )
    assert '"outcome": "skipped"' in flat, (
        "dropping an m365 row must still bank the seen-events entry, "
        "unchanged from before probe-first"
    )
    assert "m365:<hex>" in flat, (
        "dropping an m365 row must also write the permanent skip-list "
        "line now that its recording_id is known"
    )
    m365_skip_idx = flat.index("--id m365:<hex>")
    skip_clause = flat[max(0, m365_skip_idx - 40): m365_skip_idx + 200]
    assert "sync skip" in skip_clause and "--reason" in skip_clause, (
        "the m365 skip-list write needs a reason, same as any other sync "
        "skip call"
    )
    assert flat.index('"outcome": "skipped"') < m365_skip_idx, (
        "the seen-events bank and the skip-list write must both be "
        "described, seen-events first — that's the write that stops "
        "triage from re-listing the occurrence immediately"
    )
    assert "skip-listed" in flat, (
        "the paragraph must explain why the skip-list write matters: a "
        "promoted worker's own dedup call checks it and replies "
        "skip-listed before ever re-fetching a transcript"
    )
    assert "sync unskip --id m365:<hex>" in flat, (
        "the drop's undo must name sync unskip for the skip-list half"
    )
    assert "sync m365-forget --event-id <id> --start-utc <utc>" in flat, (
        "the drop's undo must name sync m365-forget for the seen-events "
        "half — mirroring step 7's two-write settle-duplicate undo"
    )


# PR B final-review fix, IMPORTANT: step 5 claimed m365 rows are probed
# before the plan is shown, but nothing said the probe wave (step 6) must
# run before step 5 in interactive mode, and the transcript-found bullet
# looped a promoted entry back through "steps 3-5" — which would mean a
# second plan/confirmation for that one row. Interactive mode must show
# exactly one plan, after every probe in the wave has settled.
def test_sync_recordings_interactive_plan_runs_once_after_every_probe():
    text = read_skill("sync-recordings")
    step5 = text.split("### 5.")[1].split("### 6.")[0]
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    step5_flat = re.sub(r"\s+", " ", step5)
    step6_flat = re.sub(r"\s+", " ", step6)

    assert "probed first" in step5_flat.lower() or (
        "every m365 occurrence is probed first" in step5_flat.lower()), (
        "step 5 must state plainly that probing happens before the plan "
        "is ever shown, in interactive mode"
    )
    assert "second table" in step5_flat.lower() or (
        "second confirmation" in step5_flat.lower()), (
        "step 5 must rule out a promoted row getting its own separate "
        "confirmation"
    )

    assert "before step 5" in step6_flat.lower(), (
        "step 6's probe-wave paragraph must point at step 5 and say this "
        "wave runs before it, in interactive mode"
    )

    found_clause = step6_flat[step6_flat.index("transcript-found"):]
    assert "steps 3–5" not in found_clause and "steps 3-5" not in found_clause, (
        "the transcript-found bullet must not send a promoted row back "
        "through step 5 individually — step 5 runs once, for every row, "
        "not per promotion"
    )
    assert "steps 3–4" in found_clause or "steps 3-4" in found_clause, (
        "the transcript-found bullet must still run the routing/confidence "
        "steps (3-4) for a promoted row, just not step 5 again"
    )
    assert "never step 5 again" in found_clause.lower() or (
        "runs once" in found_clause.lower()), (
        "the transcript-found bullet must say explicitly that this row "
        "does not get its own step-5 pass"
    )


def test_sync_recordings_probes_summary_line():
    text = read_skill("sync-recordings")
    summary = text.split("### 7.")[1]
    assert "probes (" in summary, (
        "the workers-dispatched line must report the probe batch: N probes "
        "(N no-transcript · N transcript-found · N no-access · N forbidden "
        "· N fetch-error)"
    )
    probes_clause = summary[summary.index("probes ("):]
    for outcome in ("no-transcript", "transcript-found", "no-access",
                    "forbidden", "fetch-error"):
        assert outcome in probes_clause, (
            f"the probe sub-tally must cover every probe outcome, missing "
            f"{outcome}")
    assert "still-no-transcript" not in probes_clause, (
        "the summary banks a probe's still-no-transcript reply as a "
        "no-transcript outcome — the tally must use the banked name"
    )
    assert "M365 first looks answered by a probe" in text, (
        "probe-first needs its own headline count, separate from the "
        "workers-dispatched line"
    )
    assert "promoted m365" in summary, (
        "the workers-dispatched m365 count must be named as promoted "
        "workers only, never a first-look dispatch"
    )


def _heredoc_json(text: str, filename: str) -> dict:
    """The JSON body of `cat > "$SCRATCH/<filename>" <<'JSON' … JSON`."""
    start = text.index(filename)
    open_tag = text.index("<<'JSON'\n", start) + len("<<'JSON'\n")
    close_tag = text.index("\nJSON\n", open_tag)
    return json.loads(text[open_tag:close_tag])


def test_evening_sync_payload_example_is_the_v2_contract():
    text = read_skill("evening-sync")
    payload = _heredoc_json(text, "daily-note.payload.json")
    assert isinstance(payload["recap"], dict), "recap must be the structured v2 object"
    assert {"glance", "themes", "pulse", "decisions", "watch", "carried_forward", "sync_notes"} <= set(payload["recap"])
    assert "meetings" not in payload["recap"]["glance"], "the glance's first line is computed by the CLI"
    assert set(payload["meetings"][0]["prep"]) == {"attendees", "last_meeting", "context"}
    assert "recap_window" in payload


def test_evening_sync_project_state_example_matches_the_cli():
    text = read_skill("evening-sync")
    state = _heredoc_json(text, "project-state")
    assert {"as_of", "stage", "hot_potatoes", "coming_up", "owe"} <= set(state)
    assert "project state write" in text
    assert "Rewrite the `> [!summary]+ **Now**` callout" not in text


def test_evening_sync_routes_mechanics_to_sync_notes():
    text = read_skill("evening-sync")
    assert "sync_notes" in text
    assert "Watch is content only" in text or "**Watch** is content only" in text


# ---------------------------------------------------------------------------
# PR C: rule 10 (connector calls are never delegated to a subagent) and
# CLI-enforced fetch-error parking.

def test_sync_recordings_rules_block_states_connector_calls_are_never_delegated():
    """Rule 10 is a first statement, not a restatement — grep general-purpose
    under plugin/ was empty before this PR. The rules block must name every
    connector tool the rule covers, plus the word 'subagent', and the whole
    skill must never suggest a generic subagent as the way to make one."""
    text = read_skill("sync-recordings")
    rules_block = text.split("## The three adapters")[0]
    for tool in ("get_current_user", "get_me", "list_files",
                "outlook_calendar_search"):
        assert tool in rules_block, (
            f"rule 10 must name {tool!r} in the rules block")
    assert "subagent" in rules_block.lower()
    assert "general-purpose" not in text, (
        "sync-recordings must never point at a generic subagent for a "
        "connector call — the only subagents it dispatches are step 6's "
        "worker and probe agent types"
    )


def test_sync_recordings_names_sync_fetch_error():
    """The new CLI-enforced parking verb must be named in SKILL.md's step 6,
    not just exist in cli.py — a skill that never calls it never parks
    anything."""
    text = read_skill("sync-recordings")
    assert "sync fetch-error" in text
    assert "fetch_errors_batch.json" in text


def test_sync_recordings_rule6_states_the_cli_side_counting():
    text = read_skill("sync-recordings")
    rules_block = text.split("## The three adapters")[0]
    assert "Errors are not recorded" in rules_block
    assert "distinct UTC days" in rules_block


def test_sync_recordings_summary_names_parked_after_fetch_errors():
    text = read_skill("sync-recordings")
    summary = text.split("## Sync Complete")[1].split("```")[0]
    assert "**Parked after repeated fetch-errors:**" in summary
    assert "sync unskip --id" in summary


def test_sync_recordings_parked_fetch_error_undo_has_two_shapes_for_m365():
    """Fix round 1, IMPORTANT-1: mirror PR A's two-shape undo rule — a
    parked m365 id has two writes (the skip-list line and a seen-events
    `skipped` entry), so `sync unskip` alone is not the whole story, same
    as a worker-settled cross-adapter duplicate."""
    text = read_skill("sync-recordings")
    summary_block = re.sub(r"\s+", " ", text.split("## Sync Complete")[1].split("```")[0])
    assert "sync m365-forget --event-id" in summary_block
    idx = text.index("`Parked after repeated fetch-errors` reports")
    gloss = re.sub(r"\s+", " ", text[idx: idx + 900])
    assert "sync m365-forget --event-id" in gloss
    assert "is a separate matter" not in gloss


def test_sync_recordings_worker_and_probe_contracts_gain_the_recording_id_clause():
    worker = read_ref("sync-recordings", "worker-contract.md")
    probe = read_ref("sync-recordings", "probe-contract.md")
    for ref in (worker, probe):
        assert "recording-id: <ns:id>" in ref


def test_sync_recordings_runlog_mentions_fetch_error_parking():
    text = read_skill("sync-recordings")
    unattended = text.split("## Unattended mode")[1]
    assert "fetch-error parked" in unattended or \
        "fetch-error" in unattended.split("runlog append")[1][:400]


# ---------------------------------------------------------------------------
# Final review of PR C: five minors.

def test_sync_recordings_skipped_errors_line_excludes_parked():
    """Item 2: 'will retry next run' must not silently include ids the same
    run just parked — those never retry."""
    text = read_skill("sync-recordings")
    summary = text.split("## Sync Complete")[1].split("```")[0]
    assert "**Skipped / errors:**" in summary
    line = [l for l in summary.splitlines() if l.startswith("**Skipped / errors:**")][0]
    assert "excluding any parked this run" in line


def test_sync_recordings_fetch_error_never_attributed_to_inbox():
    """Item 3: an inbox item has no fetch step at all (worker-contract.md's
    own outcome row names only Plaud and M365), so SKILL.md must not claim
    an inbox fetch-error line ever carries a recording-id clause."""
    worker = read_ref("sync-recordings", "worker-contract.md")
    row = [l for l in worker.splitlines() if l.startswith("| `fetch-error:")][0]
    assert "Plaud" in row and "M365" in row
    assert "inbox" not in row.lower()

    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1]
    assert "Plaud and inbox: always" not in step6
    assert "Plaud or inbox" not in step6
    assert "an inbox item has no fetch" in step6.lower() or \
        "inbox recording never has one" in step6


def test_sync_recordings_watermark_gloss_names_the_park():
    """Item 4: the watermark section already explains a persistently
    failing item keeps retrying regardless of the watermark — it must also
    say that retrying stops once sync fetch-error parks it."""
    text = read_skill("sync-recordings")
    idx = text.index("A batch's `fetch-error` outcomes do not hold this back")
    passage = re.sub(r"\s+", " ", text[idx: idx + 400])
    assert "until `sync fetch-error` parks it on its third failing day" in passage


def test_setup_discovery_worker_agent_frontmatter():
    agents_dir = SKILLS_DIR.parent / "agents"
    worker = (agents_dir / "setup-discovery-worker.md").read_text(encoding="utf-8")
    front = worker.split("---")[1]
    assert "name: setup-discovery-worker" in front
    assert "model: sonnet" in front, "verbatim transcription is the trust point"
    assert "tools:" not in front, (
        "the worker's tools must stay open — connector tool names differ per "
        "deployment, exactly as for sync-worker-m365")
    disallowed_lines = [line for line in front.splitlines()
                        if line.strip().startswith("disallowedTools:")]
    assert disallowed_lines, "the discovery worker must declare disallowedTools"
    disallowed = [name.strip()
                  for name in disallowed_lines[0].split(":", 1)[1].split(",")]
    assert disallowed == M365_WORKER_DISALLOWED_TOOLS
    body = re.sub(r"\s+", " ", worker.split("---", 2)[2])
    assert "discovery contract" in body and "outcome line" in body
    assert "dispatched without a briefing" in body


def test_discovery_contract_pins_the_privacy_rules():
    from vaultlib import discover
    contract = re.sub(r"\s+", " ", read_ref("setup-my-brain", "discovery-contract.md"))
    assert "never call `chat_message_search`" in contract
    assert "one folder at a time" in contract
    assert "never add, merge or guess a row" in contract
    assert "Inbox" in contract and "never read the Inbox" in contract
    assert "round-robin" in contract
    assert 'discover clock-check --dir "$SCRATCH"' in contract
    assert "m365_<source>.p<n>.payload.json" in contract
    for source in discover.SOURCES:
        assert f"`{source}`" in contract, f"the contract must name source {source}"
    for source in discover.PAGE_CAPS:
        assert f"page_caps.{source}" in contract
    assert discover.BROADCAST_LIMIT == 15 and "more than 15" in contract


def test_setup_my_brain_shows_only_what_the_check_passed():
    text = read_skill("setup-my-brain")
    assert "Nothing is shown to the owner that `discover check` did not pass" in text
    assert "Show only what is under `passed`" in text
    assert "Entities come from the vault owner, never from the calendar" not in text, (
        "rule 5 was replaced: organisations may be proposed, only the owner confirms")


def test_setup_my_brain_asks_the_company_rules_question_before_reading():
    text = read_skill("setup-my-brain")
    # The Requirements section names `discover build --consume` early; the
    # ordering that matters is against the first real read, step 2's call.
    assert text.index("Does your company have rules") < text.index(
        'discover build --vault "$VAULT"')


def test_setup_my_brain_never_reads_chat_text():
    assert "Chat message text is never read" in read_skill("setup-my-brain")


def test_setup_my_brain_dispatches_the_worker_and_consumes_raw_reads():
    text = read_skill("setup-my-brain")
    assert "setup-discovery-worker" in text
    assert "references/discovery-contract.md" in text
    builds = [line for line in text.splitlines() if "discover build --vault" in line]
    assert len(builds) == 1, "one build for the one read"
    assert all("--consume" in line and "--expect" in line for line in builds), (
        "the read deletes its raw rows and enforces the worker's counts")


def test_setup_my_brain_is_written_for_the_owner_alone():
    text = read_skill("setup-my-brain")
    assert "on their own" in text
    assert "consultant's own record" not in text, (
        "there is no consultant in the room any more")


def test_setup_my_brain_asks_consent_before_anything_is_read():
    text = read_skill("setup-my-brain")
    assert text.index("May I look through your calendar") < text.index("discover clock-start")
    assert "Nothing is read without their explicit yes" in text


def test_setup_my_brain_bounds_the_read_by_time():
    text = read_skill("setup-my-brain")
    assert 'discover clock-start --dir "$SCRATCH" --budget 300' in text
    assert "up to 5 minutes" in text
    assert "--read" not in text


def test_setup_my_brain_never_provisions():
    text = read_skill("setup-my-brain")
    assert "never provision" in text.lower()
    assert "Never run `/provision-vault`" in text


def test_setup_my_brain_asks_identity_instead_of_discovering_it():
    text = read_skill("setup-my-brain")
    for gone in ("working-day", "system-sender", "`language` entries"):
        assert gone not in text, f"setup-my-brain still proposes from {gone}"
    assert "working hours" in text


def test_setup_my_brain_announces_the_first_evening_note():
    assert "I'll now write tomorrow's note" in read_skill("setup-my-brain")
