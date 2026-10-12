"""sync update-queue: the deterministic data layer under /evening-sync.

Ports build_update_queue.py minus --auto-fix (parked toward /health-check) and
minus allowedTags (decision tags were dropped in P1a). Attendees are person
slugs in the product, so metrics join on slug — and the vault owner is
excluded from key-people by slug, never by display name.
"""
import json
import subprocess
import sys
from datetime import date, datetime
import re
from pathlib import Path

import pytest

from vaultlib import project, updatequeue

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def make_vault(tmp_path: Path) -> Path:
    for folder in ("99-workflow-config", "20-meetings", "30-projects", "50-people"):
        (tmp_path / folder).mkdir()
    write_person(tmp_path, "owner-morgan")
    return tmp_path


def write_person(root: Path, slug: str) -> None:
    (root / "50-people" / f"{slug}.md").write_text(
        f'---\nperson-name: "X"\nslug: {slug}\nrelationship:\n---\n',
        encoding="utf-8")


def write_project(root: Path, slug: str, *, status="active",
                  last_updated="2026-06-01", state_updated=None,
                  with_metrics=True) -> Path:
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", "type: project", f'project-name: "{slug}"', f"slug: {slug}",
             f"status: {status}", "project-type: initiative", "entity: acme",
             "owner: owner-morgan", "created: 2026-01-01",
             f"last-updated: {last_updated}"]
    if state_updated is not None:
        lines += [f"state-updated: {state_updated}"]
    if with_metrics:
        lines += ["meetings-7d: 9", "meetings-30d: 9", "key-people: [stale-slug]"]
    lines += ["---", "", "## Decisions", "", "## Open Items", "",
              "## Related Meetings", ""]
    (folder / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return folder / "index.md"


def write_meeting(root: Path, stem: str, *, date_value="2026-06-10T10:00",
                  review_status="confirmed", projects=(), attendees=(),
                  type_value="meeting", confirmed_at=None) -> None:
    proj = ", ".join(projects)
    att = ", ".join(attendees)
    lines = ["---", f"date: {date_value}", f"type: {type_value}",
             f"review_status: {review_status}",
             f"projects: [{proj}]", f"attendees: [{att}]"]
    if confirmed_at is not None:
        lines += [f"confirmed-at: {confirmed_at}"]
    lines += ["---", "", "- x", ""]
    (root / "20-meetings" / f"{stem}.md").write_text(
        "\n".join(lines), encoding="utf-8")


def write_decision(root: Path, project: str, stem: str) -> None:
    folder = root / "30-projects" / project / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.md").write_text("\n".join([
        "---", "type: decision", f"project: {project}", "date: 2026-06-02",
        "status: active", 'summary: "A prior decision."', "supersedes:",
        "reviewed: true", "---", "", "**Decision** — x.", "",
        "**Why** — y.", "", "**Implications** — z.", "",
    ]), encoding="utf-8")


def test_metrics_windows_exclusion_and_tie_break(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    write_person(root, "bo-marsh")
    index = write_project(root, "alpha", last_updated="2026-06-12")
    # Inside 7d; the owner attends everything and must not appear in key-people.
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "owner-morgan"))
    # Inside 30d only (2026-05-20 > 2026-05-13, but <= 2026-06-05).
    write_meeting(root, "m2", date_value="2026-05-20T09:00",
                  projects=("alpha",), attendees=("bo-marsh", "owner-morgan"))
    # Exactly on the 7d edge: 2026-06-05 is NOT strictly greater than d7.
    write_meeting(root, "m3", date_value="2026-06-05T09:00",
                  projects=("alpha",), attendees=("bo-marsh", "owner-morgan"))
    # needs-review never counts.
    write_meeting(root, "m4", date_value="2026-06-11T09:00",
                  review_status="needs-review",
                  projects=("alpha",), attendees=("ana-fields",))

    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 1" in text
    assert "meetings-30d: 3" in text
    # In the 90d window: bo-marsh 2 (m2, m3), ana-fields 1 (m1); owner excluded.
    assert "key-people: [bo-marsh, ana-fields]" in text
    assert result["confirmedMeetings"] == 3
    # owner-morgan, ana-fields, bo-marsh
    assert result["metricsWritten"] == {"projects": 1, "people": 3}

    person = (root / "50-people" / "bo-marsh.md").read_text(encoding="utf-8")
    assert "meetings-7d: 0" in person and "meetings-30d: 2" in person


def test_key_people_ties_break_by_slug(tmp_path):
    root = make_vault(tmp_path)
    for slug in ("zed-quill", "ana-fields"):
        write_person(root, slug)
    write_project(root, "alpha", last_updated="2026-06-12")
    write_meeting(root, "m1", date_value="2026-06-10T10:00", projects=("alpha",),
                  attendees=("zed-quill", "ana-fields", "owner-morgan"))
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert "key-people: [ana-fields, zed-quill]" in text


def test_queue_membership_and_projection(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    write_project(root, "alpha", last_updated="2026-06-01")
    write_project(root, "beta", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_project(root, "gamma", status="paused", last_updated="2026-01-01")
    write_decision(root, "alpha", "2026-06-02-a-prior-decision")
    write_meeting(root, "new-alpha", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "owner-morgan"))
    # Same day as beta's state write, but before it -> not queued.
    write_meeting(root, "old-beta", date_value="2026-06-12T10:00",
                  projects=("beta",), attendees=("ana-fields",))
    # Paused projects are never queued, even with newer meetings.
    write_meeting(root, "for-gamma", date_value="2026-06-10T10:00",
                  projects=("gamma",), attendees=("ana-fields",))

    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    queue = result["projectsNeedingUpdate"]
    assert [entry["slug"] for entry in queue] == ["alpha"]
    entry = queue[0]
    assert entry["indexPath"] == "30-projects/alpha/index.md"
    assert entry["decisionsDir"] == "30-projects/alpha/decisions/"
    assert entry["lastUpdated"] == "2026-06-01"
    assert entry["stateUpdated"] is None  # never touched -> day-level fallback
    assert entry["newCount"] == 1
    assert entry["newFiles"] == ["20-meetings/new-alpha.md"]
    assert entry["existingDecisions"][0]["stem"] == "2026-06-02-a-prior-decision"
    assert entry["existingDecisions"][0]["summary"] == "A prior decision."


def test_upserts_metrics_when_fields_are_absent_and_writes_only_on_change(
        tmp_path, mark_stale):
    root = make_vault(tmp_path)
    index = write_project(root, "alpha", with_metrics=False,
                          last_updated="2026-06-12")
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 0" in text and "key-people: []" in text
    stale = mark_stale(index)  # a rewrite has to move the stamp by decades
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert index.stat().st_mtime_ns == stale  # unchanged content -> no rewrite


def test_broken_files_warn_and_the_run_continues(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    (root / "20-meetings" / "broken.md").write_text("no frontmatter",
                                                    encoding="utf-8")
    write_project(root, "beta", last_updated="not-a-date")
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert any("broken.md" in w for w in result["warnings"])
    assert any("last-updated" in w and "beta" in w for w in result["warnings"])
    assert result["metricsWritten"]["projects"] == 2


def test_scalar_projects_and_attendees_warn_and_count_once(tmp_path):
    """`projects: alpha` without brackets is a string, and iterating a string
    yields characters — the meeting would silently join to no project at all."""
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    index = write_project(root, "alpha", last_updated="2026-06-01")
    (root / "20-meetings" / "m1.md").write_text("\n".join([
        "---", "date: 2026-06-10T10:00", "type: meeting",
        "review_status: confirmed", "projects: alpha", "attendees: ana-fields",
        "---", "", "- x", "",
    ]), encoding="utf-8")
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert any("m1.md" in w and "projects" in w and "list" in w
               for w in result["warnings"])
    assert any("m1.md" in w and "attendees" in w and "list" in w
               for w in result["warnings"])
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 1" in text
    assert "key-people: [ana-fields]" in text
    assert [entry["slug"] for entry in result["projectsNeedingUpdate"]] == ["alpha"]


def test_non_string_list_frontmatter_warns_instead_of_crashing(tmp_path):
    """A non-string non-list (`projects: 42`) used to raise TypeError out of
    the indexer and reach the caller as the CLI's malformed-payload backstop."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-01")
    (root / "20-meetings" / "m1.md").write_text("\n".join([
        "---", "date: 2026-06-10T10:00", "type: meeting",
        "review_status: confirmed", "projects: 42", "attendees: [ana-fields]",
        "---", "", "- x", "",
    ]), encoding="utf-8")
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert any("m1.md" in w and "projects" in w for w in result["warnings"])
    assert result["projectsNeedingUpdate"] == []


def test_owner_slug_is_validated(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(updatequeue.UpdateQueueError, match="person note"):
        updatequeue.run(root, today="2026-06-12", owner="ghost-owner")
    with pytest.raises(updatequeue.UpdateQueueError):
        updatequeue.run(root, today="2026-06-12", owner="Not A Slug")
    with pytest.raises(updatequeue.UpdateQueueError, match="--today"):
        updatequeue.run(root, today="12-06-2026", owner="owner-morgan")


def test_self_check_trips_on_a_silent_skip():
    confirmed = [{"file": "20-meetings/m.md", "date": date(2026, 6, 10),
                  "datetime": datetime(2026, 6, 10, 10, 0),
                  "projects": ["alpha"], "attendees": []}]
    warnings = updatequeue.self_check(
        confirmed, queued_slugs=set(),
        active_stamps={"alpha": (date(2026, 6, 1), None)})
    assert len(warnings) == 1 and "SELF-CHECK" in warnings[0]
    # Queued, up-to-date, or non-active projects never trip it.
    assert updatequeue.self_check(confirmed, {"alpha"},
                                  {"alpha": (date(2026, 6, 1), None)}) == []
    assert updatequeue.self_check(confirmed, set(),
                                  {"alpha": (date(2026, 6, 12), None)}) == []
    assert updatequeue.self_check(confirmed, set(), {}) == []


def test_same_day_meeting_queues_when_no_state_updated(tmp_path):
    """Issue #98: the queue compared days with a strict `>`, so a meeting
    confirmed on the same day the project state was last written was dropped
    from the queue forever. With no `state-updated` the threshold falls back
    to the last-updated day at 00:00 — day-granularity `>=`, erring toward
    queuing."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    write_meeting(root, "same-day", date_value="2026-06-12T10:00",
                  projects=("alpha",))
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    queue = result["projectsNeedingUpdate"]
    assert [entry["slug"] for entry in queue] == ["alpha"]
    assert queue[0]["newFiles"] == ["20-meetings/same-day.md"]
    assert queue[0]["stateUpdated"] is None


def test_state_updated_timestamp_splits_a_day(tmp_path):
    """Once the stamp exists the comparison is by the minute, so the same day
    has a before and an after."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "before-the-write", date_value="2026-06-12T10:00",
                  projects=("alpha",))
    write_meeting(root, "after-the-write", date_value="2026-06-12T19:00",
                  projects=("alpha",))
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    queue = result["projectsNeedingUpdate"]
    assert [entry["slug"] for entry in queue] == ["alpha"]
    assert queue[0]["newCount"] == 1
    assert queue[0]["newFiles"] == ["20-meetings/after-the-write.md"]
    assert queue[0]["stateUpdated"] == "2026-06-12T18:00"
    assert result["warnings"] == []


def test_date_only_meeting_errs_toward_queuing(tmp_path):
    """A bare `date: YYYY-MM-DD` carries no time. Reading it as end-of-day
    means an untimed meeting queues rather than vanishing."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "untimed", date_value="2026-06-12",
                  projects=("alpha",))
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert [entry["slug"]
            for entry in result["projectsNeedingUpdate"]] == ["alpha"]


def test_unparseable_state_updated_warns_and_falls_back(tmp_path):
    """A garbage stamp must not silence the project the way an unparseable
    last-updated does — warn about the field and fall back to the day."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="garbage")
    write_meeting(root, "same-day", date_value="2026-06-12T10:00",
                  projects=("alpha",))
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert any("state-updated" in w and "alpha" in w
               for w in result["warnings"])
    assert [entry["slug"]
            for entry in result["projectsNeedingUpdate"]] == ["alpha"]


def test_offset_bearing_dates_do_not_crash_the_run(tmp_path):
    """A hand-edited `date: ...+02:00` parses into an *aware* datetime, and
    order-comparing aware against a naive threshold raises TypeError — which
    cli.py reports as a malformed payload and which aborts the whole vault's
    queue after earlier projects have already had metrics rewritten. Wall
    clock is the only frame this module has, so the offset is dropped, the
    way m365.py and dates.py already do."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    write_project(root, "beta", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:30+02:00")
    write_meeting(root, "aware-alpha", date_value="2026-06-12T10:00+02:00",
                  projects=("alpha",))
    write_meeting(root, "aware-beta", date_value="2026-06-12T19:00+02:00",
                  projects=("beta",))
    result = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert sorted(entry["slug"]
                  for entry in result["projectsNeedingUpdate"]) == ["alpha",
                                                                   "beta"]
    # The offset is dropped, not honoured: 19:00 wall clock is after 18:30.
    beta = next(e for e in result["projectsNeedingUpdate"]
                if e["slug"] == "beta")
    assert beta["stateUpdated"] == "2026-06-12T18:30"


def test_touch_then_rerun_converges(tmp_path):
    """The stamp is what stops churn: once `project touch` records the moment
    the state was synthesized, the same meeting no longer queues."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    write_meeting(root, "same-day", date_value="2026-06-12T10:00",
                  projects=("alpha",))
    first = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert [entry["slug"]
            for entry in first["projectsNeedingUpdate"]] == ["alpha"]
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  timestamp="2026-06-12T19:30")
    second = updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert second["projectsNeedingUpdate"] == []
    assert [w for w in second["warnings"] if "SELF-CHECK" in w] == []


def test_self_check_catches_the_day_granularity_drop():
    """Independence is the point: the sweep is a day-granularity `>=` and only
    a recorded state-updated timestamp suppresses it — so the strict-`>` day
    comparison the queue used to run gets caught here rather than passing
    silently, which is what the two passes are for."""
    confirmed = [{"file": "20-meetings/m.md", "date": date(2026, 6, 12),
                  "datetime": datetime(2026, 6, 12, 10, 0),
                  "projects": ["alpha"], "attendees": []}]
    warnings = updatequeue.self_check(
        confirmed, queued_slugs=set(),
        active_stamps={"alpha": (date(2026, 6, 12), None)})
    assert len(warnings) == 1 and "SELF-CHECK" in warnings[0]
    # A state-updated timestamp after the meeting is the one piece of evidence
    # that suppresses the flag.
    assert updatequeue.self_check(
        confirmed, set(),
        {"alpha": (date(2026, 6, 12), datetime(2026, 6, 12, 18, 0))}) == []


def test_self_check_flags_unparseable_last_updated(tmp_path):
    """A project that can never be queued is the worst silent skip of all, so
    the self-check names it instead of skipping it."""
    confirmed = [{"file": "20-meetings/m.md", "date": date(2026, 6, 12),
                  "datetime": datetime(2026, 6, 12, 10, 0),
                  "projects": ["alpha"], "attendees": []}]
    warnings = updatequeue.self_check(confirmed, set(), {"alpha": None})
    assert len(warnings) == 1
    assert "unparseable" in warnings[0] and "alpha" in warnings[0]


def test_cli_update_queue_envelope(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    proc = subprocess.run(
        [sys.executable, str(CLI), "sync", "update-queue",
         "--vault", str(root), "--today", "2026-06-12",
         "--owner", "owner-morgan"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["projectsNeedingUpdate"] == []


import shutil

FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"


def copy_fixture_vault(tmp_path: Path) -> Path:
    target = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def test_fixture_vault_is_a_fixed_point_of_update_queue(tmp_path):
    """The demo vault is a converged evening-run snapshot at 2026-06-15: the
    checked-in metric stamps ARE update-queue's output, so a run changes
    nothing. This pins metric arithmetic against real fixture data AND keeps
    the stamps honest (P2a lesson: fixture stamps must survive scrutiny)."""
    root = copy_fixture_vault(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    result = updatequeue.run(root, today="2026-06-15",
                             owner="morgan-ellery")
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    assert after == before
    assert result["meetingsIndexed"] == 9
    assert result["confirmedMeetings"] == 6
    assert result["projectsNeedingUpdate"] == []
    assert result["warnings"] == []
    assert result["metricsWritten"] == {"projects": 4, "people": 10}


def test_a_note_updates_project_state_but_is_not_counted_as_a_meeting(tmp_path):
    """Both halves in one test on purpose: a refactor that satisfies one and
    drops the other is exactly the silent regression this guards.

    A forwarded email carrying project context must reach project-state
    synthesis and decision capture — that is why captures route here at all.
    It must not inflate meetings-7d, which feeds Projects.base: counting an
    email as a meeting is the quiet kind of falsehood the vault's third
    golden rule forbids.
    """
    root = make_vault(tmp_path)
    write_person(root, "priya-nathan")
    write_project(root, "yard-automation", last_updated="2026-06-01")
    write_meeting(root, "10-06-26-capture", type_value="note",
                  date_value="2026-06-10T09:00",
                  projects=["yard-automation"], attendees=["priya-nathan"])

    result = updatequeue.run(root, "2026-06-12", "owner-morgan")

    index = (root / "30-projects" / "yard-automation" / "index.md").read_text(
        encoding="utf-8")
    assert "meetings-7d: 0" in index
    assert "meetings-30d: 0" in index
    assert "key-people: []" in index

    person = (root / "50-people" / "priya-nathan.md").read_text(
        encoding="utf-8")
    assert "meetings-7d: 0" in person
    assert "meetings-30d: 0" in person

    queued = [entry["slug"] for entry in result["projectsNeedingUpdate"]]
    assert queued == ["yard-automation"]
    assert result["projectsNeedingUpdate"][0]["newFiles"] == [
        "20-meetings/10-06-26-capture.md"]


def test_a_meeting_alongside_a_note_counts_once(tmp_path):
    """The filter must remove notes, not everything."""
    root = make_vault(tmp_path)
    write_person(root, "priya-nathan")
    write_project(root, "yard-automation", last_updated="2026-06-01")
    write_meeting(root, "10-06-26-capture", type_value="note",
                  date_value="2026-06-10T09:00",
                  projects=["yard-automation"], attendees=["priya-nathan"])
    write_meeting(root, "10-06-26-steerco", type_value="steerco",
                  date_value="2026-06-10T14:00",
                  projects=["yard-automation"], attendees=["priya-nathan"])

    updatequeue.run(root, "2026-06-12", "owner-morgan")

    index = (root / "30-projects" / "yard-automation" / "index.md").read_text(
        encoding="utf-8")
    assert "meetings-7d: 1" in index
    assert "key-people: [priya-nathan]" in index


# --- confirmation time (dryrun issue 1) -------------------------------------
#
# A tick folded *after* the project's last state update must queue the meeting
# even when the meeting itself happened before that update. Without the stamp
# the predicate compared meeting time alone and dropped it forever, and the
# self-check read "meeting older than state-updated" as proof it had been
# incorporated — which is false when the confirmation came later.


def test_meeting_confirmed_after_state_update_queues(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "old-but-just-confirmed", date_value="2026-06-10T10:00",
                  projects=["alpha"], confirmed_at="2026-06-13T09:00")
    result = updatequeue.run(root, "2026-06-13", "owner-morgan")
    queued = {e["slug"]: e for e in result["projectsNeedingUpdate"]}
    assert "alpha" in queued
    assert queued["alpha"]["newFiles"] == ["20-meetings/old-but-just-confirmed.md"]
    assert not [w for w in result["warnings"] if "SELF-CHECK" in w]


def test_meeting_confirmed_before_state_update_stays_incorporated(tmp_path):
    """Confirmed at 09:00, state written at 18:00: the evening run saw it.
    Neither the queue nor the self-check may re-raise it."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "seen", date_value="2026-06-10T10:00",
                  projects=["alpha"], confirmed_at="2026-06-12T09:00")
    result = updatequeue.run(root, "2026-06-13", "owner-morgan")
    assert result["projectsNeedingUpdate"] == []
    assert not [w for w in result["warnings"] if "SELF-CHECK" in w]


def test_meeting_without_stamp_behaves_exactly_as_before(tmp_path):
    """Every already-confirmed note in a deployed vault lacks the stamp. It
    must fall back to the meeting datetime alone — no reprocessing storm on
    the first run after upgrade."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "legacy", date_value="2026-06-10T10:00",
                  projects=["alpha"])
    result = updatequeue.run(root, "2026-06-13", "owner-morgan")
    assert result["projectsNeedingUpdate"] == []
    assert not [w for w in result["warnings"] if "SELF-CHECK" in w]


def test_self_check_warns_when_a_late_confirmation_is_dropped():
    """The bug's second half: the sweep used to suppress its flag on
    `datetime < state-updated`, treating an older meeting as incorporated. A
    confirmation stamped after state-updated is the counter-evidence, and the
    flag must fire — naming the stamp, so the reader knows why."""
    confirmed = [{"file": "20-meetings/m.md", "date": date(2026, 6, 10),
                  "datetime": datetime(2026, 6, 10, 10, 0),
                  "confirmed_at": datetime(2026, 6, 13, 9, 0),
                  "projects": ["alpha"], "attendees": []}]
    stamps = {"alpha": (date(2026, 6, 12), datetime(2026, 6, 12, 18, 0))}
    warnings = updatequeue.self_check(confirmed, queued_slugs=set(),
                                      active_stamps=stamps)
    assert len(warnings) == 1 and "SELF-CHECK" in warnings[0]
    assert "confirmed-at 2026-06-13T09:00" in warnings[0]
    # Queued, it is silent; confirmed before the state was written, silent.
    assert updatequeue.self_check(confirmed, {"alpha"}, stamps) == []
    confirmed[0]["confirmed_at"] = datetime(2026, 6, 12, 9, 0)
    assert updatequeue.self_check(confirmed, set(), stamps) == []


def test_unparseable_confirmed_at_warns_and_falls_back(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "odd", date_value="2026-06-10T10:00",
                  projects=["alpha"], confirmed_at="garbage")
    result = updatequeue.run(root, "2026-06-13", "owner-morgan")
    assert result["projectsNeedingUpdate"] == []
    assert any("confirmed-at" in w and "odd.md" in w for w in result["warnings"])


def test_reconcile_then_queue_picks_up_the_late_tick(tmp_path):
    """End to end, the shape the field report describes: yesterday's evening
    run touched the project; today the vault owner ticks yesterday's meeting;
    tonight's run must queue it."""
    from vaultlib import syncjob
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12",
                  state_updated="2026-06-12T18:00")
    write_meeting(root, "yesterday", date_value="2026-06-12T10:00",
                  review_status="needs-review", projects=["alpha"])
    text = (root / "20-meetings" / "yesterday.md").read_text(encoding="utf-8")
    (root / "20-meetings" / "yesterday.md").write_text(
        text.replace("review_status: needs-review",
                     "review_status: needs-review\nreviewed: true"),
        encoding="utf-8")

    folded = syncjob.reconcile_reviews(root, timestamp="2026-06-13T11:00")
    assert folded["flipped"] == ["20-meetings/yesterday.md"]

    result = updatequeue.run(root, "2026-06-13", "owner-morgan")
    assert [e["slug"] for e in result["projectsNeedingUpdate"]] == ["alpha"]
    assert result["projectsNeedingUpdate"][0]["newFiles"] == [
        "20-meetings/yesterday.md"]


# --- message logs as activity (D1) -----------------------------------------

def vault_with_project_and_owner(tmp_path, slug, state_updated):
    root = make_vault(tmp_path)
    write_person(root, "morgan-ellery")
    write_project(root, slug, state_updated=state_updated)
    return root


def write_log(root, day, groups, updated_at):
    from vaultlib import msglog
    data = {"schema": 1, "date": day, "ids": [g["gid"] for g in groups],
            "groups": groups}
    projects = sorted({p for g in groups for p in g["projects"]})
    weak = sorted({p for g in groups for p in g["projects_weak"]})
    msglog.save_log(root, data, {
        "type": "message-log", "date": day, "updated-at": updated_at,
        "projects": projects, "projects-weak": weak,
        "people": sorted({p for g in groups for p in g["people"]}),
        "messages-read": len(groups)})


def g(gid, projects=(), weak=(), people=()):
    return {"gid": gid, "key": f"mail:{gid}", "kind": "mail", "label": gid,
            "chat_type": None, "people": list(people), "names": {},
            "participants": [], "projects": list(projects),
            "projects_weak": list(weak), "entities": [],
            "needs_owner": False,
            "points": [{"text": "x", "cites": [gid]}]}


def test_a_strong_log_after_state_updated_queues_the_project(tmp_path):
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-09-29T19:00")
    write_log(root, "2026-09-30",
              [g("a1", projects=["acme-industries-rollout"])],
              "2026-09-30T18:52")
    queue = updatequeue.run(root, "2026-09-30", "morgan-ellery")[
        "projectsNeedingUpdate"]
    assert queue[0]["slug"] == "acme-industries-rollout"
    assert queue[0]["newLogs"] == ["2026-09-30-messages"]
    assert queue[0]["newFiles"] == [] and queue[0]["newCount"] == 1


def test_a_weak_log_never_queues(tmp_path):
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-09-29T19:00")
    write_log(root, "2026-09-30",
              [g("a1", projects=["acme-industries-rollout"],
                 weak=["acme-industries-rollout"])], "2026-09-30T18:52")
    assert updatequeue.run(root, "2026-09-30", "morgan-ellery")[
        "projectsNeedingUpdate"] == []


def _set_state_updated(root, slug, stamp):
    index = root / "30-projects" / slug / "index.md"
    text = index.read_text(encoding="utf-8")
    index.write_text(re.sub(r"state-updated: .*", f"state-updated: {stamp}", text),
                     encoding="utf-8")


def test_a_requeued_source_stays_queued_until_a_later_state_update(tmp_path):
    from vaultlib import msgstate
    slug = "acme-industries-rollout"
    root = vault_with_project_and_owner(tmp_path, slug, "2026-10-01T19:00")
    msgstate.requeue_add(root, slug, "2026-09-30-messages", at="2026-10-01T19:30")
    for _ in range(2):  # a re-run before stage 4 wrote the state loses nothing
        queue = updatequeue.run(root, "2026-10-01", "morgan-ellery")[
            "projectsNeedingUpdate"]
        assert queue[0]["removedSources"] == ["2026-09-30-messages"]
    _set_state_updated(root, slug, "2026-10-01T19:30")  # same minute: kept
    assert updatequeue.run(root, "2026-10-01", "morgan-ellery")[
        "projectsNeedingUpdate"][0]["removedSources"] == ["2026-09-30-messages"]
    _set_state_updated(root, slug, "2026-10-01T20:45")  # stage 4 ran after it
    assert updatequeue.run(root, "2026-10-01", "morgan-ellery")[
        "projectsNeedingUpdate"] == []
    assert msgstate.requeue_list(root) == []


def test_a_damaged_log_warns_and_the_queue_continues(tmp_path):
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-09-29T19:00")
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-messages.md").write_text(
        "---\ntype: message-log\n---\nno data block\n", encoding="utf-8")
    out = updatequeue.run(root, "2026-09-30", "morgan-ellery")
    assert any("2026-09-30-messages.md" in w for w in out["warnings"])


def test_people_get_message_counters(tmp_path):
    from vaultlib import markdown, person
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-09-29T19:00")
    person.ensure(root, "Sam Lee", "2026-09-01")
    write_log(root, "2026-09-30", [g("a1", people=["sam-lee"]),
                                   g("a2", people=["sam-lee"])],
              "2026-09-30T18:52")
    write_log(root, "2026-09-10", [g("b1", people=["sam-lee"])],
              "2026-09-10T18:52")
    updatequeue.run(root, "2026-09-30", "morgan-ellery")
    fm, _ = markdown.split_frontmatter(
        (root / "50-people" / "sam-lee.md").read_text(encoding="utf-8"))
    assert (int(fm["messages-7d"]), int(fm["messages-30d"])) == (2, 3)


def test_a_group_without_people_warns_and_the_queue_continues(tmp_path):
    import re
    from vaultlib import msglog
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-09-29T19:00")
    group = g("x")
    msglog.save_log(root, {"schema": 1, "date": "2026-09-30", "ids": ["x"],
                           "groups": [group]},
                    {"type": "message-log", "date": "2026-09-30",
                     "updated-at": "2026-09-30T18:52", "projects": [],
                     "people": [], "messages-read": 1})
    log = root / "_messages" / "2026-09-30-messages.md"
    text = log.read_text(encoding="utf-8")
    stripped = re.sub(r'\s*"people": \[\],?', "", text, count=1)
    assert stripped != text
    log.write_text(stripped, encoding="utf-8")
    out = updatequeue.run(root, "2026-09-30", "morgan-ellery")
    assert any("group 'x'" in w for w in out["warnings"])


def test_malformed_requeue_entries_warn_and_never_abort(tmp_path):
    from vaultlib import msgstate
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-10-01T19:00")
    state = msgstate.load(root)
    state["requeue"] = [{}, "junk", {"slug": 3, "log": "l"},
                        {"slug": "acme-industries-rollout",
                         "log": "2026-09-29-messages"},
                        {"slug": "acme-industries-rollout",
                         "log": "2026-09-30-messages", "at": "2026-10-01T19:30"}]
    msgstate.save(root, state)
    out = updatequeue.run(root, "2026-10-01", "morgan-ellery")
    assert len([w for w in out["warnings"] if "malformed requeue" in w]) == 4
    assert out["projectsNeedingUpdate"][0]["removedSources"] == [
        "2026-09-30-messages"]


def test_a_requeued_slug_with_no_active_project_warns(tmp_path):
    from vaultlib import msgstate
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-10-01T19:00")
    msgstate.requeue_add(root, "ghost-project", "2026-09-30-messages",
                         at="2026-10-01T09:00")
    out = updatequeue.run(root, "2026-10-01", "morgan-ellery")
    assert any("ghost-project" in w and "no active project" in w
               for w in out["warnings"])
    assert out["projectsNeedingUpdate"] == []


def test_a_strong_log_older_than_state_updated_does_not_queue(tmp_path):
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-09-30T19:00")
    write_log(root, "2026-09-30",
              [g("a1", projects=["acme-industries-rollout"])],
              "2026-09-30T18:52")
    assert updatequeue.run(root, "2026-09-30", "morgan-ellery")[
        "projectsNeedingUpdate"] == []


# --- #242: people learn when they were last met and on which projects ---

def write_person_with(root: Path, slug: str, extra: str = "") -> Path:
    path = root / "50-people" / f"{slug}.md"
    path.write_text(f'---\nperson-name: "X"\nslug: {slug}\nrelationship:\n'
                    f"{extra}---\n", encoding="utf-8")
    return path


def person_fm(root: Path, slug: str) -> dict:
    from vaultlib import markdown
    data, _ = markdown.split_frontmatter(
        (root / "50-people" / f"{slug}.md").read_text(encoding="utf-8"))
    return data


def test_last_met_is_the_latest_confirmed_meeting_attended(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    write_meeting(root, "m1", date_value="2026-03-02T10:00", attendees=("ana-fields",))
    write_meeting(root, "m2", date_value="2026-06-10T10:00", attendees=("ana-fields",))
    # not counted: unconfirmed, a capture rather than a meeting, and one that
    # has not happened yet
    write_meeting(root, "m3", date_value="2026-06-11T10:00",
                  review_status="needs-review", attendees=("ana-fields",))
    write_meeting(root, "m4", date_value="2026-06-11T11:00",
                  type_value="note", attendees=("ana-fields",))
    write_meeting(root, "m5", date_value="2026-06-20T10:00", attendees=("ana-fields",))
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert str(person_fm(root, "ana-fields")["last-met"]) == "2026-06-10"


def test_someone_never_met_gets_no_last_met_and_a_stale_one_is_cleared(tmp_path):
    root = make_vault(tmp_path)
    path = write_person_with(root, "bo-marsh", "last-met: 2026-01-01\n")
    write_person(root, "cy-never")
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert person_fm(root, "bo-marsh")["last-met"] is None
    assert "\nlast-met:\n" in path.read_text(encoding="utf-8")
    assert "last-met" not in (root / "50-people" / "cy-never.md").read_text(encoding="utf-8")


def test_projects_gain_the_projects_of_confirmed_meetings_and_keep_hand_entries(tmp_path):
    root = make_vault(tmp_path)
    write_person_with(root, "ana-fields", "projects: [hand-picked, alpha]\n")
    write_meeting(root, "m1", projects=("alpha", "beta"), attendees=("ana-fields",))
    write_meeting(root, "m2", projects=("gamma",), review_status="needs-review",
                  attendees=("ana-fields",))
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    # add-only: hand entries stay in place, new ones are appended sorted
    assert person_fm(root, "ana-fields")["projects"] == ["hand-picked", "alpha", "beta"]


def test_projects_already_complete_are_not_rewritten(tmp_path):
    root = make_vault(tmp_path)
    # a block list the owner's property editor wrote must survive untouched
    path = write_person_with(root, "ana-fields",
                             "projects:\n  - beta\n  - alpha\nlast-met: 2026-06-10\n"
                             "meetings-7d: 1\nmeetings-30d: 1\n"
                             "messages-7d: 0\nmessages-30d: 0\n")
    write_meeting(root, "m1", projects=("alpha", "beta"), attendees=("ana-fields",))
    before = path.read_bytes()
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert path.read_bytes() == before


def test_adding_a_project_keeps_hand_entries_that_need_quoting(tmp_path):
    # Review on #245: re-emitting the list bare turned "[[Acme Rollout]]"
    # into a nested list and split "Ops, EMEA" into two projects.
    import yaml
    root = make_vault(tmp_path)
    path = write_person_with(root, "ana-fields",
                             'projects:\n  - "[[Acme Rollout]]"\n  - "Ops, EMEA"\n'
                             '  - "x: y #z"\n  - alpha\n')
    write_meeting(root, "m1", projects=("zeta",), attendees=("ana-fields",))
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text.split("---")[1])
    assert parsed["projects"] == ["[[Acme Rollout]]", "Ops, EMEA", "x: y #z", "alpha", "zeta"]
    assert person_fm(root, "ana-fields")["projects"] == parsed["projects"]
    # plain slugs stay bare
    assert ", alpha, zeta]" in text


def write_owner_note(root: Path, name: str, frontmatter: str) -> None:
    folder = root / "80-thoughts-ideas"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(f"---\n{frontmatter}---\nthought\n", encoding="utf-8")


def test_an_included_note_queues_a_project_with_no_new_meetings(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    write_owner_note(root, "idea.md", "include: true\nprojects: [acme-crm]\n")
    result = updatequeue.run(root, "2026-06-21", "owner-morgan")
    [entry] = result["projectsNeedingUpdate"]
    assert entry["slug"] == "acme-crm"
    assert entry["newNotes"] == ["80-thoughts-ideas/idea.md"]
    assert entry["newFiles"] == [] and entry["newCount"] == 1


def test_unticked_unlinked_and_inactive_notes_queue_nothing(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    write_project(root, "acme-old", status="closed")
    write_owner_note(root, "a.md", "include: false\nprojects: [acme-crm]\n")
    write_owner_note(root, "b.md", "include: true\n")
    write_owner_note(root, "c.md", "include: true\nprojects: [acme-old]\n")
    assert updatequeue.run(root, "2026-06-21", "owner-morgan")["projectsNeedingUpdate"] == []


def test_an_oversized_note_does_not_queue(tmp_path):
    from vaultlib import notes
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    folder = root / "80-thoughts-ideas"
    folder.mkdir()
    (folder / "long.md").write_text(
        "---\ninclude: true\nprojects: [acme-crm]\n---\n" + "x" * (notes.MAX_BODY_CHARS + 1),
        encoding="utf-8")
    assert updatequeue.run(root, "2026-06-21", "owner-morgan")["projectsNeedingUpdate"] == []


def test_every_queue_entry_carries_new_notes(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm")
    write_meeting(root, "10-06-26-x", projects=["acme-crm"])
    [entry] = updatequeue.run(root, "2026-06-21", "owner-morgan")["projectsNeedingUpdate"]
    assert entry["newNotes"] == []


def test_a_note_whose_project_cannot_queue_is_listed_as_not_queued(tmp_path):
    # An unparseable last-updated keeps the project out of the queue, so the
    # note's projects are non-empty but it appears in no entry's newNotes:
    # the write-back must not mark it absorbed.
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="someday")
    write_project(root, "beta", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    write_owner_note(root, "stuck.md", "include: true\nprojects: [acme-crm]\n")
    write_owner_note(root, "fine.md", "include: true\nprojects: [beta]\n")
    write_owner_note(root, "loose.md", "include: true\n")
    result = updatequeue.run(root, "2026-06-21", "owner-morgan")
    assert result["notesNotQueued"] == ["80-thoughts-ideas/stuck.md"]
    assert [e["slug"] for e in result["projectsNeedingUpdate"]] == ["beta"]


def test_notes_not_queued_is_empty_when_every_note_queued(tmp_path):
    root = make_vault(tmp_path)
    assert updatequeue.run(root, "2026-06-21", "owner-morgan")["notesNotQueued"] == []


def test_project_written_at_noon_is_not_requeued_without_new_input(tmp_path):
    """#271: the on-demand run wrote state at 12:00 after the 09:00 meeting
    was accepted at 11:30; the evening run has nothing new for it."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-10-12",
                  state_updated="2026-10-12T12:00")
    write_meeting(root, "morning", date_value="2026-10-12T09:00",
                  projects=["alpha"], confirmed_at="2026-10-12T11:30")
    result = updatequeue.run(root, "2026-10-12", "owner-morgan")
    assert result["projectsNeedingUpdate"] == []
    assert not [w for w in result["warnings"] if "SELF-CHECK" in w]


def test_mail_read_in_the_evening_requeues_a_project_written_at_noon(tmp_path):
    """#271: mail from this morning is read by the evening run; its log is
    stamped with the evening write time, so the project queues again."""
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-10-12T12:00")
    write_log(root, "2026-10-12",
              [g("m1", projects=["acme-industries-rollout"])],
              "2026-10-12T21:05")
    queue = updatequeue.run(root, "2026-10-12", "morgan-ellery")[
        "projectsNeedingUpdate"]
    assert [e["slug"] for e in queue] == ["acme-industries-rollout"]
    assert queue[0]["newLogs"] == ["2026-10-12-messages"]
