"""meeting write: schema-validated emission of meeting notes.

review_status is not a payload field — every synced meeting lands
needs-review (the auto-confirm gate deliberately did not ship; a fresh vault
has no calibration data)."""
from pathlib import Path

import pytest
import yaml

from vaultlib import meeting, syncjob


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "10-inbox").mkdir()
    (tmp_path / "20-meetings").mkdir()
    (tmp_path / "30-projects" / "yard-automation").mkdir(parents=True)
    (tmp_path / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nslug: yard-automation\n---\n", encoding="utf-8")
    (tmp_path / "50-people").mkdir()
    for slug in ("priya-nathan", "morgan-ellery"):
        (tmp_path / "50-people" / f"{slug}.md").write_text(
            f"---\nperson-name: X\nslug: {slug}\nrelationship:\n---\n",
            encoding="utf-8")
    return tmp_path


def payload(**overrides) -> dict:
    base = {
        "title": "vendor strategy brainstorm",
        "date": "2026-05-20T11:00",
        "type": "brainstorm",
        "calendar-subject": "Vendor strategy: working session",
        "calendar_match": False,
        "attendees": ["priya-nathan", "morgan-ellery"],
        "projects": ["yard-automation"],
        "recording-duration": 41,
        "source": "recorder",
        "source-recording-id": "inbox:3f9c2a41d8e07b56",
        "source-filename": "REC-2026-0520-1103.m4a",
        "confidence": "low",
        "confidence-reasons": ["calendar-tool-unavailable",
                               "content-keyword-match", "new-attendees:1"],
        "takeaways": ["Single-vendor consolidation preferred.",
                      "Yard 2 timeline at risk."],
        "debrief": "### Vendor strategy\nDiscussion of consolidation.",
        "action-items": ["**Priya Nathan** — circulate revised schedule"],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_write_happy_path_is_conformant_yaml(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload())
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm"
    assert result["review_status"] == "needs-review"
    assert result["conflict"] is None

    text = (root / result["path"]).read_text(encoding="utf-8")
    # PyYAML is the second parser CI trusts; the emitted block must satisfy it.
    block = text.split("---\n")[1]
    data = yaml.safe_load(block)
    assert data["calendar-subject"] == "Vendor strategy: working session"
    assert data["review_status"] == "needs-review"
    assert data["reviewed"] is False and data["archived"] is False
    assert data["processed"] is True
    assert data["confidence-reasons"] == ["calendar-tool-unavailable",
                                          "content-keyword-match",
                                          "new-attendees:1"]
    assert "## Key Takeaways" in text and "## Debrief" in text
    assert "## Action Items" in text


def test_one_to_one_type_survives_pyyaml(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(type="1:1",
                                         title="priya check in"))
    block = (root / result["path"]).read_text(encoding="utf-8").split("---\n")[1]
    assert yaml.safe_load(block)["type"] == "1:1"   # not the integer 61


def test_action_items_section_omitted_when_absent(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(**{"action-items": None}))
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "## Action Items" not in text


def test_rejects_unknown_project_and_unknown_attendee(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="no-such-project"):
        meeting.write(root, payload(projects=["no-such-project"]))
    with pytest.raises(meeting.MeetingError, match="person ensure"):
        meeting.write(root, payload(attendees=["ghost-attendee"]))


def test_rejects_incomplete_confidence_stamp(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="travel together"):
        meeting.write(root, payload(**{"confidence-reasons": None}))
    bad = payload(**{"confidence-reasons":
                     ["calendar-match-high", "calendar-match-low",
                      "all-attendees-known"]})
    with pytest.raises(meeting.MeetingError, match="project-link"):
        meeting.write(root, bad)
    bad2 = payload(**{"confidence-reasons":
                      ["calendar-match-high", "no-project-match",
                       "new-attendees:0"]})
    with pytest.raises(meeting.MeetingError, match="new-attendees"):
        meeting.write(root, bad2)


def test_rejects_unknown_payload_key_and_bad_enum(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="unknown payload key"):
        meeting.write(root, payload(review_status="confirmed"))
    with pytest.raises(meeting.MeetingError, match="source"):
        meeting.write(root, payload(source="carrier-pigeon"))


def test_rejects_zero_takeaways_and_too_many(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="takeaways"):
        meeting.write(root, payload(takeaways=[]))
    with pytest.raises(meeting.MeetingError, match="takeaways"):
        meeting.write(root, payload(takeaways=["a", "b", "c", "d", "e", "f"]))


def test_rejects_missing_recording_id(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="source-recording-id"):
        meeting.write(root, payload(**{"source-recording-id": None}))


def test_refuses_when_recording_id_already_in_ledger(tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload())
    with pytest.raises(meeting.MeetingError, match="already synced"):
        meeting.write(root, payload(title="different title entirely"))


def test_confirmed_target_gets_needs_attention_sibling(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    # A human confirms it via triage.
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")

    dup = payload(**{"source-recording-id": "inbox:ffff2a41d8e07b56"})
    result = meeting.write(root, dup)
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-v2"
    assert result["review_status"] == "needs-attention"
    assert result["conflict"] == {
        "kind": "confirmed-target",
        "conflicts_with": "20-05-26-vendor-strategy-brainstorm",
    }
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'conflicts-with: "[[20-05-26-vendor-strategy-brainstorm]]"' in text
    # The confirmed note was not touched.
    assert "review_status: confirmed" in p.read_text(encoding="utf-8")


def test_second_conflict_takes_v3(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")
    meeting.write(root, payload(**{"source-recording-id": "inbox:aaaa2a41d8e07b56"}))
    third = meeting.write(root, payload(**{"source-recording-id": "inbox:bbbb2a41d8e07b56"}))
    assert third["stem"] == "20-05-26-vendor-strategy-brainstorm-v3"


def test_unconfirmed_stem_collision_suffixes_instead_of_overwriting(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    result = meeting.write(
        root, payload(**{"source-recording-id": "inbox:cccc2a41d8e07b56"}))
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-2"
    assert result["review_status"] == "needs-review"
    assert result["conflict"]["kind"] == "stem-collision"
    # Both notes exist; nothing was overwritten.
    assert (root / first["path"]).is_file() and (root / result["path"]).is_file()
