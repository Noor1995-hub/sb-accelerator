"""Which commands the shipped vault prose names, and to whom.

lint_plugin.py's third job blocks one direction (#84: no shipped prose may name
a command that does not exist). These cover the other direction, and the
question a name-existence check structurally cannot see: audience.

`Start here.md` is the handover. playbooks/provisioning-runbook.md tells the
consultant to open the vault, leave the vault owner on that note, and step
back — no script, no walkthrough. So it must still name the command the daily
loop runs on, and must never hand the vault owner one that only a delaware
consultant should run.
"""
import re
from pathlib import Path

from lint_plugin import scan_skill_references, shipped_skills

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
START_HERE = TEMPLATE / "Start here.md"

# Same shape as the linter's, deliberately restated: this module asserts what
# the prose says, and a shared constant would let a regex change quietly move
# both the guard and its own audience checks at once.
SLASH_RE = re.compile(r"`/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`")

# Consultant-led: delaware runs it, at a visit, with the vault on screen.
# upgrade-vault can be lossy ("not something to hand the vault owner to run
# alone") and setup-my-brain is a once-ever two-hour interview run by the
# consultant and the vault owner together. provision-vault runs before the
# vault owner has a vault to be handed a command in, touches a credential
# that must never appear in chat, and is never invoked by a self-serve skill
# the way schedule-daily-loop is invoked by setup-my-brain below — nothing
# calls it once setup day is over. None of the three belongs in a note whose
# whole audience is the vault owner.
CONSULTANT_LED = {"setup-my-brain", "upgrade-vault", "provision-vault"}

# Safe to run unaccompanied by the vault owner.
#
# schedule-daily-loop is here despite being invoked by consultant-led
# setup-my-brain, because being invoked by one is not the same as being one.
# Neither rationale above applies: it is not lossy (a wrong time is fixed by
# re-running it) and it is not a two-hour interview. Re-running it after a
# machine change is a designed-for case rather than a tolerated one — the
# routine has to be created on the machine that will run it, so a vault
# owner who moves the evening run to a new laptop has no other way to move
# it.
SELF_SERVE = {"evening-sync", "health-check", "sync-recordings", "log-decision",
              "new-project", "update-entity", "report-feedback",
              "schedule-daily-loop"}

# The vault's only egress path is `feedback send`, so the skills that invoke it
# are the skills that can transmit. Derived below rather than trusted here.
TRANSMITS_TO_DELAWARE = {"report-feedback", "health-check"}

# Start here is an orientation card — five things, then close the note — not a
# command reference. So the floor is the daily loop only; the rest of
# SELF_SERVE is permitted there, not required.
MUST_NAME = {"evening-sync"}


def named_in(path: Path) -> set[str]:
    return set(SLASH_RE.findall(path.read_text(encoding="utf-8")))


def test_every_shipped_skill_is_classified_by_audience():
    """Exact equality, not the `<=` used elsewhere in this suite. That pattern
    is right where each task appends its own name; it is wrong here, because
    the point is that a new skill cannot ship without someone deciding whether
    the vault owner is allowed to run it. Under `<=` a consultant-only skill
    lands unclassified and then leaks into Start here with nothing objecting."""
    assert not (CONSULTANT_LED & SELF_SERVE), "a skill has one audience"
    assert CONSULTANT_LED | SELF_SERVE == shipped_skills(REPO_ROOT), (
        "a new, renamed or retired skill must leave every name here in exactly "
        "one audience bucket")


def test_start_here_names_only_commands_the_owner_can_run_alone():
    """#84's regression in audience terms rather than existence terms:
    /morning-brief is in neither bucket, so it fails here too — and silencing
    that by adding it to SELF_SERVE fails the partition test above, because no
    such skill ships. The two interlock; neither can be quieted on its own."""
    handed_over = named_in(START_HERE)
    assert handed_over <= SELF_SERVE, (
        f"Start here.md hands the vault owner {sorted(handed_over - SELF_SERVE)} "
        "— consultant-led or non-existent commands do not belong in the "
        "orientation note")


def test_start_here_names_the_command_the_daily_loop_runs_on():
    assert MUST_NAME <= named_in(START_HERE), (
        f"Start here.md must name {sorted(MUST_NAME)}: the daily loop is the "
        "first thing the note exists to explain, and the vault owner has "
        "nowhere else that tells them the command")


def test_the_shipped_trees_name_no_command_that_does_not_exist():
    """The linter's own check, run against the real repo from pytest.
    lint_plugin.py runs in one CI job; this runs in all three pytest jobs and
    in a bare local `pytest -q`, which is where prose actually gets edited."""
    assert scan_skill_references(REPO_ROOT, shipped_skills(REPO_ROOT)) == []


def test_audience_buckets_are_not_generalised_beyond_the_orientation_note():
    """Guardrail on the rule above, not on the prose: the five context
    placeholders and ontology.md name /setup-my-brain as *provenance* ("filled
    by the onboarding interview"), not as an instruction. An audience rule
    applied vault-wide would flag those correct lines, so this records that
    they are expected to name a consultant-led command."""
    elsewhere = set()
    for path in sorted(TEMPLATE.rglob("*.md")):
        if path != START_HERE:
            elsewhere |= named_in(path)
    assert elsewhere & CONSULTANT_LED, (
        "template prose outside Start here.md is expected to reference "
        "consultant-led commands descriptively — if that stops being true, "
        "delete this test rather than widening the audience rule")


def transmitting_skills() -> set:
    """Skills that can send anything out of the vault: the ones whose SKILL.md
    invokes the CLI's `feedback send`, which is the single egress path."""
    skills = REPO_ROOT / "plugin" / "skills"
    return {d.name for d in skills.iterdir()
            if (d / "SKILL.md").is_file()
            and "feedback send" in (d / "SKILL.md").read_text(encoding="utf-8")}


def egress_callout() -> str:
    """The one callout in Start here that claims what leaves the vault.

    Found by content rather than by line number so reflowing the note cannot
    break it, and asserted unique so a second egress claim elsewhere in the
    note cannot quietly contradict this one."""
    blocks, current = [], []
    for line in START_HERE.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    claims = [b for b in blocks if "delaware" in b]
    assert len(claims) == 1, (
        f"expected exactly one callout in Start here.md claiming what leaves "
        f"the vault, found {len(claims)}")
    return claims[0]


def test_the_transmitting_skills_are_the_ones_we_think_they_are():
    """Derived from the SKILL.mds, so a third skill growing a `feedback send`
    call fails here first and forces the note to be reconsidered."""
    assert transmitting_skills() == TRANSMITS_TO_DELAWARE


def test_the_egress_callout_names_every_command_that_can_transmit():
    """The note claimed /report-feedback was "the only command that talks to
    delaware" and then recommended /health-check four lines later — which
    sends over the identical `feedback send` path, on the same explicit yes.
    A false exclusivity claim about data egress, in the note that is the
    client's whole handover. Neither the existence guard nor the audience
    test can see this: both commands exist, and both are self-serve."""
    named = set(SLASH_RE.findall(egress_callout()))
    assert TRANSMITS_TO_DELAWARE <= named, (
        f"the egress callout omits {sorted(TRANSMITS_TO_DELAWARE - named)} — "
        "every command that can send data out has to be named where the note "
        "tells the vault owner what leaves the vault")
