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
# Skills invoke the CLI through the $VAULTLIB convention rather than repeating
# the path, so match either form: `cli.py <group> <action>` or
# `"$VAULTLIB" <group> <action>`. Group and action names may carry digits
# (m365) — a class without them silently exempts those invocations.
INVOCATION_RE = re.compile(r'(?:cli\.py|\$\{?VAULTLIB\}?)"?\s+([a-z0-9-]+)\s+([a-z0-9-]+)')


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


NET_NEW = {"report-feedback", "health-check", "upgrade-vault", "setup-my-brain"}


def test_expected_skills_exist():
    # Each skill task appends its own name here as it lands, so this test is
    # always satisfiable by the task that touches it.
    names = {path.parent.name for path in SKILL_FILES}
    assert {"new-project", "update-entity", "log-decision",
            "sync-recordings", "evening-sync", "report-feedback",
            "health-check", "upgrade-vault", "setup-my-brain"} <= names


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


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_cli_invocation_named_by_a_skill_exists(path):
    implemented = known_subcommands()
    text = path.read_text(encoding="utf-8")
    referenced = set(INVOCATION_RE.findall(text))
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
    """#54 acceptance: timezone, exec slug, and adapter enablement come from
    config.json. The prose context files carry style and narrative only, so
    no skill may name the two files that used to hold machine decisions.

    `setup-my-brain` is exempt from the `tools-and-systems` half only, because
    it is the *writer* of the portfolio: the interview walks all five context
    stems by name and writes each through `context write`. Naming a file you
    fill is not reading config out of it. The `identity.md` half still binds
    every skill — nothing has any business reading the exec's name or timezone
    out of that file — and the invariant that actually matters for the writer
    is checked below, on the machine fields themselves.
    """
    text = path.read_text(encoding="utf-8")
    assert "identity.md" not in text, f"{path.parent.name} reads prose config"
    if path.parent.name != "setup-my-brain":
        assert "tools-and-systems" not in text, (
            f"{path.parent.name} reads prose config")


def test_setup_my_brain_writes_machine_decisions_through_config():
    """The other half of the rule above: the one skill allowed to name the
    prose files must still route timezone, the executive slug, adapter
    enablement and the account hints through `config write`, never into a
    context block — and must run the binding gate on what it wrote, which is
    the entire point of #54's ceremony."""
    text = read_skill("setup-my-brain")
    for field in ("--field executive", "--field timezone",
                  "--field adapters.plaud.enabled",
                  "--field adapters.m365.enabled",
                  "--field adapters.plaud.account_hint",
                  "--field adapters.m365.account_hint"):
        assert f"config write --vault \"$VAULT\" {field}" in text, (
            f"setup-my-brain must set {field} through config write")
    assert "config verify-account --vault \"$VAULT\" --adapter plaud" in text
    assert "config verify-account --vault \"$VAULT\" --adapter m365" in text


# #58 (F5, F6): a summary line is read by the exec and the EA, so it may not
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
            f"in words the exec can read"
        )
    assert "**Meetings you ticked as reviewed:**" in text, (
        f"{name}: the fold result needs a plain-speech summary line"
    )


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
    from it would promise the exec one thing and deliver another."""
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
    # Decision 16: one catch-up note covers the window; the exec is told so.
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
    # leaves tomorrow with no note — found by the exec next morning, and
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


def test_evening_sync_states_unattended_catchup_behaviour():
    section = _evening_sync().split("## Unattended mode", 1)
    assert len(section) == 2, "evening-sync has no Unattended mode section"
    body = section[1].split("\n## ", 1)[0].lower()
    assert "catch-up" in body or "catchup" in body, (
        "unattended mode caps and flags rather than composing a mega-recap; "
        "finding F4 is that this mode has no coverage at all"
    )
