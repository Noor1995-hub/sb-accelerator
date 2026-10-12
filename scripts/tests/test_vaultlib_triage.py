"""Triage in the chat (#271): the CLI half of accept / dismiss / change."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import triage

CLI = Path(__file__).resolve().parents[2] / "plugin" / "lib" / "vaultlib" / "cli.py"


def make_vault(tmp_path: Path) -> Path:
    for folder in ("20-meetings", "50-people", "99-workflow-config"):
        (tmp_path / folder).mkdir()
    for slug, name in (("acme-erp", "Acme ERP rollout"),
                       ("acme-finance-close", "Finance close")):
        (tmp_path / "30-projects" / slug).mkdir(parents=True)
        (tmp_path / "30-projects" / slug / "index.md").write_text(
            f'---\ntype: project\nproject-name: "{name}"\nslug: {slug}\n---\n',
            encoding="utf-8")
    for slug, name in (("jan-peeters", "Jan Peeters"), ("sofie-maes", "Sofie Maes")):
        (tmp_path / "50-people" / f"{slug}.md").write_text(
            f'---\nperson-name: "{name}"\nslug: {slug}\n---\n', encoding="utf-8")
    return tmp_path


def write_meeting(root, stem, *, status="needs-review", archived=False,
                  projects="[acme-erp]", conflicts=None, h1="Weekly with Acme"):
    lines = ["---", "date: 2026-10-12T09:00", "type: meeting",
             'calendar-subject: "Weekly"', "attendees: [jan-peeters, sofie-maes]",
             f"projects: {projects}", f"review_status: {status}",
             "reviewed: false", f"archived: {'true' if archived else 'false'}",
             "confidence: medium"]
    if conflicts:
        lines.append(f'conflicts-with: "[[{conflicts}]]"')
    lines += ["---", f"# {h1}" if h1 else "", "", "## Key Takeaways", "- x", ""]
    path = root / "20-meetings" / f"{stem}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_list_shows_only_open_triage_with_names(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a-open")
    write_meeting(root, "b-confirmed", status="confirmed")
    write_meeting(root, "c-dismissed", archived=True)
    result = triage.list_queue(root)
    assert [i["path"] for i in result["items"]] == ["20-meetings/a-open.md"]
    item = result["items"][0]
    assert item["title"] == "Weekly with Acme"
    assert item["project_names"] == ["Acme ERP rollout"]
    assert item["attendee_names"] == ["Jan Peeters", "Sofie Maes"]
    assert item["conflicts_with"] is None


def test_list_falls_back_to_calendar_subject_and_reports_conflicts(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a-dup", conflicts="b-other", h1="")
    item = triage.list_queue(root)["items"][0]
    assert item["title"] == "Weekly"
    assert item["conflicts_with"] == "[[b-other]]"


def test_accept_and_dismiss_set_the_same_ticks_as_obsidian(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    b = write_meeting(root, "b")
    result = triage.apply(root, [
        {"path": "20-meetings/a.md", "action": "accept"},
        {"path": "20-meetings/b.md", "action": "dismiss"},
    ])
    assert result["refused"] == []
    assert "reviewed: true" in a.read_text(encoding="utf-8")
    assert "archived: true" in b.read_text(encoding="utf-8")
    assert "reviewed: false" in b.read_text(encoding="utf-8")


def test_change_rewrites_projects_and_accepts_by_default(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "change",
                         "projects": ["acme-finance-close"]}])
    text = a.read_text(encoding="utf-8")
    assert "projects: [acme-finance-close]" in text
    assert "reviewed: true" in text


def test_change_without_accept_leaves_it_in_triage(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "change",
                         "attendees": ["jan-peeters"], "accept": False}])
    text = a.read_text(encoding="utf-8")
    assert "attendees: [jan-peeters]" in text
    assert "reviewed: false" in text


def test_unknown_slug_refuses_that_item_only(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    write_meeting(root, "b")
    before = a.read_text(encoding="utf-8")
    result = triage.apply(root, [
        {"path": "20-meetings/a.md", "action": "change", "projects": ["acme-finanse"]},
        {"path": "20-meetings/b.md", "action": "accept"},
    ])
    assert result["refused"][0]["path"] == "20-meetings/a.md"
    assert "acme-finanse" in result["refused"][0]["reason"]
    assert a.read_text(encoding="utf-8") == before
    assert result["applied"] == [{"path": "20-meetings/b.md", "action": "accept"}]


def test_conflicted_note_cannot_be_accepted(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a", conflicts="b-other")
    result = triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    assert "Duplicate" in result["refused"][0]["reason"]
    assert "reviewed: false" in a.read_text(encoding="utf-8")


def test_refuses_paths_outside_meetings_and_bad_actions(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a")
    result = triage.apply(root, [
        {"path": "../outside.md", "action": "accept"},
        {"path": "20-meetings/missing.md", "action": "accept"},
        {"path": "20-meetings/a.md", "action": "approve"},
    ])
    assert len(result["refused"]) == 3
    assert result["applied"] == []


def test_apply_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    once = a.read_text(encoding="utf-8")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    assert a.read_text(encoding="utf-8") == once


def test_items_must_be_a_list(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(triage.TriageError):
        triage.apply(root, {"path": "x"})


def test_cli_round_trip(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a")
    listed = json.loads(subprocess.run(
        [sys.executable, str(CLI), "meeting", "triage-list", "--vault", str(root)],
        capture_output=True, text=True, check=True).stdout)
    assert listed["ok"] and listed["result"]["items"][0]["path"] == "20-meetings/a.md"
    payload = tmp_path / "triage.payload.json"
    payload.write_text(json.dumps([{"path": "20-meetings/a.md", "action": "accept"}]))
    applied = json.loads(subprocess.run(
        [sys.executable, str(CLI), "meeting", "triage-apply", "--vault", str(root),
         "--items", str(payload)], capture_output=True, text=True, check=True).stdout)
    assert applied["result"]["applied"] == [{"path": "20-meetings/a.md", "action": "accept"}]


def test_list_gives_a_ready_made_when_label(tmp_path):
    """#271: the model never works out a weekday itself."""
    root = make_vault(tmp_path)
    write_meeting(root, "a")
    assert triage.list_queue(root)["items"][0]["when"] == "Mon 12 Oct 09:00"


def test_when_label_for_a_date_only_meeting(tmp_path):
    root = make_vault(tmp_path)
    path = write_meeting(root, "a")
    path.write_text(path.read_text(encoding="utf-8").replace(
        "date: 2026-10-12T09:00", "date: 2026-10-12"), encoding="utf-8")
    assert triage.list_queue(root)["items"][0]["when"] == "Mon 12 Oct"


def test_when_label_has_no_leading_zero(tmp_path):
    root = make_vault(tmp_path)
    path = write_meeting(root, "a")
    path.write_text(path.read_text(encoding="utf-8").replace(
        "date: 2026-10-12T09:00", "date: 2026-10-05T14:30"), encoding="utf-8")
    assert triage.list_queue(root)["items"][0]["when"] == "Mon 5 Oct 14:30"


def test_accept_must_be_a_real_boolean(tmp_path):
    """Final review: a string "false" is truthy — it must not accept."""
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    result = triage.apply(root, [{"path": "20-meetings/a.md", "action": "change",
                                  "attendees": ["jan-peeters"], "accept": "false"}])
    assert "true or false" in result["refused"][0]["reason"]
    assert "reviewed: false" in a.read_text(encoding="utf-8")


def test_a_dismissed_note_cannot_be_accepted(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a", archived=True)
    result = triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    assert "already dismissed" in result["refused"][0]["reason"]


def test_duplicate_refusal_names_the_other_note_and_the_chat_way_out(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a", conflicts="b-other")
    reason = triage.apply(root, [{"path": "20-meetings/a.md",
                                  "action": "accept"}])["refused"][0]["reason"]
    assert "b-other" in reason and "dismiss one of the two" in reason


def test_when_label_accepts_a_space_separator(tmp_path):
    root = make_vault(tmp_path)
    path = write_meeting(root, "a")
    path.write_text(path.read_text(encoding="utf-8").replace(
        "date: 2026-10-12T09:00", "date: 2026-10-12 09:00"), encoding="utf-8")
    assert triage.list_queue(root)["items"][0]["when"] == "Mon 12 Oct 09:00"


def test_change_to_no_project_can_also_clear_the_entity(tmp_path):
    # Owner's call 2026-10-12: "no project" asks whether the meeting should
    # also leave its entity's page; the answer arrives as `entities`.
    root = make_vault(tmp_path)
    (root / "40-entities" / "acme").mkdir(parents=True)
    (root / "40-entities" / "acme" / "dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Acme"\nslug: acme\n---\n', encoding="utf-8")
    a = write_meeting(root, "a")
    b = write_meeting(root, "b")
    result = triage.apply(root, [
        {"path": "20-meetings/a.md", "action": "change", "projects": [], "entities": []},
        {"path": "20-meetings/b.md", "action": "change", "projects": [], "entities": ["acme"]},
    ])
    assert result["refused"] == []
    assert "entities: []" in a.read_text(encoding="utf-8")
    assert "entities: [acme]" in b.read_text(encoding="utf-8")
    bad = triage.apply(root, [{"path": "20-meetings/a.md", "action": "change",
                               "entities": ["nope"]}])
    assert "matches no note" in bad["refused"][0]["reason"]
