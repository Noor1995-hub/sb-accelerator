"""meeting write: schema-validated emission of meeting notes.

review_status is not a payload field — every synced meeting lands
needs-review (the auto-confirm gate deliberately did not ship; a fresh vault
has no calibration data)."""
from pathlib import Path
from typing import Optional

import pytest
import yaml

from vaultlib import meeting, syncjob


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "10-inbox").mkdir()
    (tmp_path / "20-meetings").mkdir()
    (tmp_path / "30-projects" / "yard-automation").mkdir(parents=True)
    (tmp_path / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nslug: yard-automation\n"
        "entity: meridian-freight-holdings\n---\n", encoding="utf-8")
    (tmp_path / "40-entities" / "meridian-freight-holdings").mkdir(parents=True)
    (tmp_path / "40-entities" / "meridian-freight-holdings"
     / "dossier.md").write_text(
        "---\ntype: entity\nslug: meridian-freight-holdings\n---\n",
        encoding="utf-8")
    (tmp_path / "50-people").mkdir()
    for slug in ("priya-nathan", "morgan-ellery"):
        (tmp_path / "50-people" / f"{slug}.md").write_text(
            f"---\nperson-name: X\nslug: {slug}\nrelationship:\n---\n",
            encoding="utf-8")
    return tmp_path


def _add_project(root: Path, slug: str, entity: Optional[str] = None) -> None:
    body = f"---\ntype: project\nslug: {slug}\n"
    if entity is not None:
        body += f"entity: {entity}\n"
    body += "---\n"
    (root / "30-projects" / slug).mkdir(parents=True, exist_ok=True)
    (root / "30-projects" / slug / "index.md").write_text(body, encoding="utf-8")


def _add_entity_dossier(root: Path, slug: str) -> None:
    folder = root / "40-entities" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dossier.md").write_text(
        f"---\ntype: entity\nslug: {slug}\n---\n", encoding="utf-8")


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


def test_entities_is_derived_from_a_single_project(tmp_path):
    # projects[] is non-empty (yard-automation, entity: meridian-freight-
    # holdings), so entities is machine-derived rather than taken from the
    # payload.
    root = make_vault(tmp_path)
    result = meeting.write(root, payload())
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    assert data["entities"] == ["meridian-freight-holdings"]


def test_entities_is_derived_from_multiple_projects_and_deduped(tmp_path):
    root = make_vault(tmp_path)
    _add_project(root, "yard-automation-2", "meridian-freight-holdings")
    result = meeting.write(
        root, payload(projects=["yard-automation", "yard-automation-2"]))
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    # Both projects map to the same entity: one slug, not two.
    assert data["entities"] == ["meridian-freight-holdings"]


def test_entities_derived_from_projects_mapping_to_different_entities(tmp_path):
    root = make_vault(tmp_path)
    _add_entity_dossier(root, "northwind-holdings")
    _add_project(root, "northwind-rollout", "northwind-holdings")
    result = meeting.write(
        root, payload(projects=["yard-automation", "northwind-rollout"]))
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    assert data["entities"] == ["meridian-freight-holdings", "northwind-holdings"]


def test_refuses_payload_entities_when_projects_non_empty(tmp_path):
    # The skill layer must stop hand-passing entities once a project is
    # assigned — write() derives it, and a payload that tries anyway is
    # refused rather than silently overridden.
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="derived from projects"):
        meeting.write(root, payload(entities=["meridian-freight-holdings"]))


def test_allows_payload_entities_when_projects_empty(tmp_path):
    # A project-less meeting may still concern an entity by hand.
    root = make_vault(tmp_path)
    result = meeting.write(
        root, payload(projects=[], entities=["meridian-freight-holdings"]))
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    assert data["entities"] == ["meridian-freight-holdings"]


def test_entities_is_omitted_rather_than_written_empty(tmp_path):
    # An entity dossier is the only reader of this field, so `entities: []` on
    # every meeting without one is noise in the properties panel.
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(projects=[]))
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "entities:" not in text.split("---")[1]


def test_rejects_an_entity_slug_with_no_dossier(tmp_path):
    # The dossier's Meeting Log is a Dataview query over this field: a slug
    # that joins to nothing empties the table with no error anywhere. Only
    # reachable on a project-less meeting now (a project-carrying meeting's
    # entities come from derivation, never the payload).
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="40-entities/typo-co"):
        meeting.write(root, payload(projects=[], entities=["typo-co"]))


def test_all_or_nothing_when_a_project_entity_is_unresolvable(tmp_path):
    # yard-automation resolves fine; the second project has no `entity:`
    # field at all — derivation must refuse the whole note rather than write
    # a partial entities list (migration 001's contract, shared here).
    root = make_vault(tmp_path)
    _add_project(root, "fieldless-project", entity=None)
    with pytest.raises(meeting.MeetingError, match="fieldless-project"):
        meeting.write(
            root, payload(projects=["yard-automation", "fieldless-project"]))
    # Nothing was written — a refused derivation leaves no note behind.
    assert list((root / "20-meetings").glob("*.md")) == []


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


def test_confirmed_target_gets_a_flagged_sibling(tmp_path):
    """The sibling is an ordinary needs-review note; the conflicts-with edge
    is what marks it as a duplicate that must not be auto-confirmed."""
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
    assert result["review_status"] == "needs-review"
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


def note_payload(**overrides) -> dict:
    """A forwarded email: a capture, not a meeting. No calendar was ever
    consulted and nothing was recorded — but it is still filed under its
    own subject line, because a required field may not be empty."""
    base = payload(
        title="meridian renewal terms heads up",
        type="note",
        **{"calendar-subject": "Renewal terms — heads up before next steerco"},
    )
    base["calendar_match"] = False
    base["recording-duration"] = 0
    base["source"] = "email"
    base["confidence-reasons"] = ["calendar-not-applicable",
                                  "content-keyword-match",
                                  "all-attendees-known"]
    base.pop("source-filename", None)
    base.update(overrides)
    return base


def test_note_type_is_written_like_any_other_capture(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, note_payload())
    assert result["stem"] == "20-05-26-meridian-renewal-terms-heads-up"
    assert result["review_status"] == "needs-review"
    written = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(written.split("---")[1])
    assert data["type"] == "note"
    assert data["calendar-subject"] == "Renewal terms — heads up before next steerco"
    assert data["recording-duration"] == 0
    assert data["source"] == "email"


def test_note_may_carry_no_attendees(tmp_path):
    """A voice memo musing names nobody. Every other type still must."""
    root = make_vault(tmp_path)
    result = meeting.write(root, note_payload(attendees=[]))
    written = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(written.split("---")[1])
    assert data["attendees"] == []


def test_empty_attendees_still_refused_for_every_other_type(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="non-empty"):
        meeting.write(root, payload(attendees=[]))


def test_date_from_stem_is_the_inverse_of_the_date_prefix():
    from datetime import date
    # meeting._date_prefix renders 2026-06-01 as 01-06-26; this reads it back.
    assert meeting.date_from_stem(
        "01-06-26-commercial-ops-status-update") == date(2026, 6, 1)
    # A conflict variant keeps its prefix.
    assert meeting.date_from_stem("12-06-26-jordan-1on1-v2") == date(2026, 6, 12)


def test_date_from_stem_returns_none_for_a_non_conforming_stem():
    # An ISO-prefixed stem is a decision note, not a meeting note.
    assert meeting.date_from_stem("2026-06-12-phase-1-deferred") is None
    assert meeting.date_from_stem("notes-from-the-call") is None
    assert meeting.date_from_stem("") is None
    # A real-looking but impossible date.
    assert meeting.date_from_stem("32-06-26-nope") is None


def test_date_prefix_round_trips_through_date_from_stem():
    stem = f"{meeting._date_prefix('2026-05-20T11:00')}-vendor-strategy"
    assert meeting.date_from_stem(stem).isoformat() == "2026-05-20"
