"""The runtime schema is compiled from the ontology, so these tests assert the
contract the CLI relies on rather than restating the ontology."""
import pytest

from vaultlib import schema


def test_all_six_objects_are_present():
    assert set(schema.load()["objects"]) == {
        "meeting", "project", "person", "decision", "entity", "daily-note",
    }


def test_for_object_raises_on_unknown():
    with pytest.raises(KeyError, match="unknown object type"):
        schema.for_object("nonsense")


def test_enum_values_reads_the_two_value_axis():
    assert schema.enum_values("project", "project-type") == [
        "initiative", "area-of-responsibility",
    ]


def test_body_sections_for_entity():
    assert schema.body_sections("entity") == [
        "Context", "Stakeholders", "Relationship History",
        "Meeting Log", "Sensitivities", "Engagements",
    ]


def test_body_sections_empty_for_objects_without_one():
    assert schema.body_sections("meeting") == []


def test_validate_accepts_a_complete_project():
    problems = schema.validate("project", {
        "project-name": "Yard Program", "slug": "yard-program",
        "status": "active", "project-type": "initiative",
        "entity": "meridian-freight-holdings", "owner": "morgan-ellery",
        "created": "2026-08-23", "last-updated": "2026-08-23",
    })
    assert problems == []


def test_validate_reports_every_missing_required_field():
    problems = schema.validate("project", {"slug": "x"})
    joined = " ".join(problems)
    for field in ("project-name", "status", "project-type", "entity", "owner"):
        assert field in joined


def test_validate_rejects_an_empty_required_value():
    problems = schema.validate("entity", {
        "type": "entity", "entity-name": "", "slug": "x", "status": "active",
    })
    assert any("entity-name" in p for p in problems)


def test_validate_rejects_an_off_enum_value():
    problems = schema.validate("project", {
        "project-name": "X", "slug": "x", "status": "active",
        "project-type": "presales", "entity": "e", "owner": "o",
        "created": "2026-08-23", "last-updated": "2026-08-23",
    })
    assert any("presales" in p for p in problems)


def test_validate_ignores_absent_optional_fields():
    assert schema.validate("person", {"person-name": "A", "slug": "a",
                                      "relationship": None}) == []


def test_validate_requires_keys_present_even_when_null():
    problems = schema.validate("person", {"person-name": "A", "slug": "a"})
    assert any("relationship" in p for p in problems)


def test_validate_flags_unknown_fields():
    problems = schema.validate("person", {
        "person-name": "A", "slug": "a", "relationship": None, "invented": 1,
    })
    assert any("invented" in p for p in problems)


def test_meeting_type_admits_the_non_meeting_capture():
    """A forwarded email is a dated capture, not a meeting. It lives in
    20-meetings/ because that folder is the vault's capture ledger — the
    honest label is what keeps that from being a lie."""
    values = schema.enum_values("meeting", "type")
    assert "note" in values
    assert values[:6] == ["meeting", "1:1", "steerco", "workshop",
                          "brainstorm", "status-update"]


def test_calendar_reasons_distinguish_not_applicable_from_not_found():
    """Three different facts that must never collapse: searched and found
    nothing, could not search, and never searched because it is not a
    meeting."""
    calendar = schema.for_object("meeting")["confidence_reasons"]["calendar"]
    assert "no-calendar-match" in calendar
    assert "calendar-tool-unavailable" in calendar
    assert "calendar-not-applicable" in calendar


def test_a_note_still_needs_a_real_calendar_subject():
    """calendar-subject is required, and validate() rejects "" for any
    required field — so a capture is filed under its own subject line, not
    under nothing. attendees: [] is the one genuinely empty field."""
    frontmatter = {
        "date": "2026-08-21", "type": "note", "calendar_match": False,
        "attendees": [], "projects": [], "review_status": "needs-review",
        "recording-duration": 0, "source": "email", "processed": True,
    }
    assert schema.validate(
        "meeting", {**frontmatter, "calendar-subject": ""}
    ) == ["required field 'calendar-subject' is empty"]
    assert schema.validate(
        "meeting",
        {**frontmatter,
         "calendar-subject": "Renewal terms — heads up before next steerco"},
    ) == []
