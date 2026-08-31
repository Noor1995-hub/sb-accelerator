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
                  type_value="meeting") -> None:
    proj = ", ".join(projects)
    att = ", ".join(attendees)
    (root / "20-meetings" / f"{stem}.md").write_text("\n".join([
        "---", f"date: {date_value}", f"type: {type_value}",
        f"review_status: {review_status}",
        f"projects: [{proj}]", f"attendees: [{att}]", "---", "", "- x", "",
    ]), encoding="utf-8")


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


def test_upserts_metrics_when_fields_are_absent_and_writes_only_on_change(tmp_path):
    root = make_vault(tmp_path)
    index = write_project(root, "alpha", with_metrics=False,
                          last_updated="2026-06-12")
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 0" in text and "key-people: []" in text
    before = index.stat().st_mtime_ns
    updatequeue.run(root, today="2026-06-12", owner="owner-morgan")
    assert index.stat().st_mtime_ns == before  # unchanged content -> no rewrite


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
