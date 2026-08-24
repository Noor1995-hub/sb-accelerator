"""sync update-queue: the deterministic data layer under /evening-sync.

Ports build_update_queue.py minus --auto-fix (parked toward /health-check) and
minus allowedTags (decision tags were dropped in P1a). Attendees are person
slugs in the product, so metrics join on slug — and the executive is excluded
from key-people by slug, never by display name.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from vaultlib import updatequeue

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def make_vault(tmp_path: Path) -> Path:
    for folder in ("99-workflow-config", "20-meetings", "30-projects", "50-people"):
        (tmp_path / folder).mkdir()
    write_person(tmp_path, "exec-morgan")
    return tmp_path


def write_person(root: Path, slug: str) -> None:
    (root / "50-people" / f"{slug}.md").write_text(
        f'---\nperson-name: "X"\nslug: {slug}\nrelationship:\n---\n',
        encoding="utf-8")


def write_project(root: Path, slug: str, *, status="active",
                  last_updated="2026-06-01", with_metrics=True) -> Path:
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", "type: project", f'project-name: "{slug}"', f"slug: {slug}",
             f"status: {status}", "project-type: initiative", "entity: acme",
             "owner: exec-morgan", "created: 2026-01-01",
             f"last-updated: {last_updated}"]
    if with_metrics:
        lines += ["meetings-7d: 9", "meetings-30d: 9", "key-people: [stale-slug]"]
    lines += ["---", "", "## Decisions", "", "## Open Items", "",
              "## Related Meetings", ""]
    (folder / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return folder / "index.md"


def write_meeting(root: Path, stem: str, *, date_value="2026-06-10T10:00",
                  review_status="confirmed", projects=(), attendees=()) -> None:
    proj = ", ".join(projects)
    att = ", ".join(attendees)
    (root / "20-meetings" / f"{stem}.md").write_text("\n".join([
        "---", f"date: {date_value}", "type: meeting",
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
    # Inside 7d; exec attends everything and must not appear in key-people.
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "exec-morgan"))
    # Inside 30d only (2026-05-20 > 2026-05-13, but <= 2026-06-05).
    write_meeting(root, "m2", date_value="2026-05-20T09:00",
                  projects=("alpha",), attendees=("bo-marsh", "exec-morgan"))
    # Exactly on the 7d edge: 2026-06-05 is NOT strictly greater than d7.
    write_meeting(root, "m3", date_value="2026-06-05T09:00",
                  projects=("alpha",), attendees=("bo-marsh", "exec-morgan"))
    # needs-review never counts.
    write_meeting(root, "m4", date_value="2026-06-11T09:00",
                  review_status="needs-review",
                  projects=("alpha",), attendees=("ana-fields",))

    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 1" in text
    assert "meetings-30d: 3" in text
    # In the 90d window: bo-marsh 2 (m2, m3), ana-fields 1 (m1); exec excluded.
    assert "key-people: [bo-marsh, ana-fields]" in text
    assert result["confirmedMeetings"] == 3
    # exec-morgan, ana-fields, bo-marsh
    assert result["metricsWritten"] == {"projects": 1, "people": 3}

    person = (root / "50-people" / "bo-marsh.md").read_text(encoding="utf-8")
    assert "meetings-7d: 0" in person and "meetings-30d: 2" in person


def test_key_people_ties_break_by_slug(tmp_path):
    root = make_vault(tmp_path)
    for slug in ("zed-quill", "ana-fields"):
        write_person(root, slug)
    write_project(root, "alpha", last_updated="2026-06-12")
    write_meeting(root, "m1", date_value="2026-06-10T10:00", projects=("alpha",),
                  attendees=("zed-quill", "ana-fields", "exec-morgan"))
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert "key-people: [ana-fields, zed-quill]" in text


def test_queue_membership_and_projection(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    write_project(root, "alpha", last_updated="2026-06-01")
    write_project(root, "beta", last_updated="2026-06-12")
    write_project(root, "gamma", status="paused", last_updated="2026-01-01")
    write_decision(root, "alpha", "2026-06-02-a-prior-decision")
    write_meeting(root, "new-alpha", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "exec-morgan"))
    # Dated exactly on beta's last-updated day: not strictly after -> not queued.
    write_meeting(root, "old-beta", date_value="2026-06-12T10:00",
                  projects=("beta",), attendees=("ana-fields",))
    # Paused projects are never queued, even with newer meetings.
    write_meeting(root, "for-gamma", date_value="2026-06-10T10:00",
                  projects=("gamma",), attendees=("ana-fields",))

    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    queue = result["projectsNeedingUpdate"]
    assert [entry["slug"] for entry in queue] == ["alpha"]
    entry = queue[0]
    assert entry["indexPath"] == "30-projects/alpha/index.md"
    assert entry["decisionsDir"] == "30-projects/alpha/decisions/"
    assert entry["lastUpdated"] == "2026-06-01"
    assert entry["newCount"] == 1
    assert entry["newFiles"] == ["20-meetings/new-alpha.md"]
    assert entry["existingDecisions"][0]["stem"] == "2026-06-02-a-prior-decision"
    assert entry["existingDecisions"][0]["summary"] == "A prior decision."


def test_upserts_metrics_when_fields_are_absent_and_writes_only_on_change(tmp_path):
    root = make_vault(tmp_path)
    index = write_project(root, "alpha", with_metrics=False,
                          last_updated="2026-06-12")
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 0" in text and "key-people: []" in text
    before = index.stat().st_mtime_ns
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    assert index.stat().st_mtime_ns == before  # unchanged content -> no rewrite


def test_broken_files_warn_and_the_run_continues(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    (root / "20-meetings" / "broken.md").write_text("no frontmatter",
                                                    encoding="utf-8")
    write_project(root, "beta", last_updated="not-a-date")
    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
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
    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    assert any("m1.md" in w and "projects" in w and "list" in w
               for w in result["warnings"])
    assert any("m1.md" in w and "attendees" in w and "list" in w
               for w in result["warnings"])
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 1" in text
    assert "key-people: [ana-fields]" in text
    assert [entry["slug"] for entry in result["projectsNeedingUpdate"]] == ["alpha"]


def test_non_string_list_frontmatter_warns_instead_of_crashing(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-01")
    (root / "20-meetings" / "m1.md").write_text("\n".join([
        "---", "date: 2026-06-10T10:00", "type: meeting",
        "review_status: confirmed", "projects: 42", "attendees: [ana-fields]",
        "---", "", "- x", "",
    ]), encoding="utf-8")
    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    assert any("m1.md" in w and "projects" in w for w in result["warnings"])
    assert result["projectsNeedingUpdate"] == []


def test_executive_slug_is_validated(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(updatequeue.UpdateQueueError, match="person note"):
        updatequeue.run(root, today="2026-06-12", executive="ghost-exec")
    with pytest.raises(updatequeue.UpdateQueueError):
        updatequeue.run(root, today="2026-06-12", executive="Not A Slug")
    with pytest.raises(updatequeue.UpdateQueueError, match="--today"):
        updatequeue.run(root, today="12-06-2026", executive="exec-morgan")


def test_self_check_trips_on_a_silent_skip():
    confirmed = [{"file": "20-meetings/m.md", "date": date(2026, 6, 10),
                  "projects": ["alpha"], "attendees": []}]
    warnings = updatequeue.self_check(
        confirmed, queued_slugs=set(),
        active_last_updated={"alpha": date(2026, 6, 1)})
    assert len(warnings) == 1 and "SELF-CHECK" in warnings[0]
    # Queued or up-to-date projects never trip it.
    assert updatequeue.self_check(confirmed, {"alpha"},
                                  {"alpha": date(2026, 6, 1)}) == []
    assert updatequeue.self_check(confirmed, set(),
                                  {"alpha": date(2026, 6, 12)}) == []


def test_cli_update_queue_envelope(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    proc = subprocess.run(
        [sys.executable, str(CLI), "sync", "update-queue",
         "--vault", str(root), "--today", "2026-06-12",
         "--executive", "exec-morgan"],
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
    """The demo vault is a converged evening-run snapshot at 2026-06-12: the
    checked-in metric stamps ARE update-queue's output, so a run changes
    nothing. This pins metric arithmetic against real fixture data AND keeps
    the stamps honest (P2a lesson: fixture stamps must survive scrutiny)."""
    root = copy_fixture_vault(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    result = updatequeue.run(root, today="2026-06-12",
                             executive="morgan-ellery")
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    assert after == before
    assert result["meetingsIndexed"] == 9
    assert result["confirmedMeetings"] == 3
    assert result["projectsNeedingUpdate"] == []
    assert result["warnings"] == []
    assert result["metricsWritten"] == {"projects": 4, "people": 10}
