"""Structural checks on SKILL.md files.

lint_plugin.py already covers frontmatter and the clean-room denylist. These
cover the contract between a skill and the CLI it calls: a skill that
references a subcommand that does not exist fails at the worst possible
moment, in front of a client.
"""
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


# #58 (F5, F6): a summary line is read by the vault owner and the EA, so it may not
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
    assert text.index("sync m365-record") > dispatch, (
        "there is no pre-dispatch settled-outcomes banking any more — "
        "every sync m365-record call happens after workers return")


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


def test_sync_recordings_worker_outcomes_are_a_closed_vocabulary():
    text = read_skill("sync-recordings")
    for token in ("written:", "no-transcript", "forbidden",
                  "fetch-error", "auth-error", "possible-duplicate-of",
                  "already-synced", "skip-listed"):
        assert token in text, f"outcome vocabulary is missing {token}"
    assert "never writes the seen-events cache" in text, (
        "the single-writer rule must be stated")


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
    ref = read_ref("sync-recordings", "worker-contract.md")
    assert "seenevents.py:234-242" in ref, (
        "the written/recording_id enforcement actually sits at "
        "seenevents.py:234-242 (_validate_outcome's written branch), not "
        "the outcome-vocabulary check above it"
    )
    assert "seenevents.py:214-223" not in ref


def test_sync_recordings_states_the_start_date_bound():
    text = read_skill("sync-recordings")
    assert "sync.start-date" in text
    assert 'dates window --vault "$VAULT"' in text, (
        "the clamp only holds when the skill passes the vault")


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
PLACEHOLDERS = {'"$VAULT"': "/placeholder/vault", "<tz>": "Europe/Brussels"}


def fenced_dates_window_invocations(text: str):
    import shlex
    found = []
    for block in FENCED_BLOCK_RE.findall(text):
        for line in block.replace("\\\n", " ").splitlines():
            if "dates window" not in line:
                continue
            command = line[line.index("dates window"):]
            for token, value in PLACEHOLDERS.items():
                command = command.replace(token, value)
            found.append(shlex.split(command))
    return found


@pytest.mark.parametrize("path", SKILL_FILES + REF_FILES,
                         ids=lambda p: p.parent.name)
def test_every_fenced_dates_window_invocation_parses(path):
    parser = cli.build_parser()
    for tokens in fenced_dates_window_invocations(
            path.read_text(encoding="utf-8")):
        try:
            parser.parse_args(tokens)
        except SystemExit:
            pytest.fail(
                f"{path.parent.name} prescribes a dates window invocation "
                f"argparse refuses: {' '.join(tokens)}")


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
    assert "full-event JSON" in flat, (
        "rule 8 must cover event reads — a live run re-typed events from "
        "memory and garbled transcript URLs and ids before self-correcting")
