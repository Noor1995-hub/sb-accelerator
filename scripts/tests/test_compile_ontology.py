"""The checked-in schema.json must be exactly what the ontology compiles to."""
from pathlib import Path

import pytest

import compile_ontology as co

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_schema_json_is_not_stale():
    assert co.SCHEMA_JSON.is_file(), (
        "plugin/lib/vaultlib/schema.json is missing — "
        "run: python3 scripts/compile_ontology.py"
    )
    expected = co.render(co.compile_schema())
    actual = co.SCHEMA_JSON.read_text(encoding="utf-8")
    assert actual == expected, (
        "schema.json does not match ontology.md — "
        "run: python3 scripts/compile_ontology.py"
    )


def test_check_mode_agrees_with_the_file_on_disk():
    assert co.main(["--check"]) == 0


def test_all_six_objects_compile():
    objects = co.compile_schema()["objects"]
    assert set(objects) == {"meeting", "project", "person", "decision",
                            "entity", "daily-note"}
    for name, block in objects.items():
        assert block["required"], f"{name}: empty required list"


def test_daily_note_block_is_deliberately_thin():
    block = co.compile_schema()["objects"]["daily-note"]
    assert block["required"] == ["date", "type"]
    assert block["enums"]["type"] == ["daily-note"]
    assert block["body_sections"] == ["Recap", "Meetings", "End of day"]


def test_project_type_enum_is_the_two_value_axis():
    project = co.compile_schema()["objects"]["project"]
    assert project["enums"]["project-type"] == ["initiative", "area-of-responsibility"]


def test_body_sections_are_carried_for_project_and_entity():
    objects = co.compile_schema()["objects"]
    assert objects["project"]["body_sections"] == [
        "Coming up", "Recent meetings", "Recent decisions", "Background",
    ]
    assert objects["entity"]["body_sections"] == [
        "Context", "Stakeholders", "Relationship History",
        "Meeting Log", "Sensitivities", "Engagements",
    ]


@pytest.mark.parametrize("object_name", ["meeting", "person", "decision"])
def test_objects_without_body_schema_omit_the_key(object_name):
    assert "body_sections" not in co.compile_schema()["objects"][object_name]


def test_decision_carries_reviewed_and_no_tags_vocabulary():
    decision = co.compile_schema()["objects"]["decision"]
    assert decision["optional"] == ["supersedes", "source", "archived"]
    assert decision["keys_present"] == ["reviewed"]
    assert "tags" not in decision, (
        "decision tags were dropped in P1a decision 6 — a compiled key nothing "
        "validates is the silent-divergence shape the compiler exists to prevent"
    )


def test_carried_keys_are_exactly_what_the_runtime_validator_reads():
    # schema.validate() reads required / optional / keys_present / enums;
    # body_sections is read by schema.body_sections(); confidence_reasons is
    # read by the confidence stamp validation logic. Anything else compiled
    # into schema.json affects nothing and will drift.
    assert set(co.CARRIED_KEYS) == {
        "required", "optional", "enums", "keys_present", "body_sections",
        "confidence_reasons",
    }


def test_review_status_retired_needs_attention():
    """#58: `needs-attention` was a busdev-era status. The clobber-risk signal
    it used to carry now lives on the `conflicts-with` edge, which is a field
    rather than a status — so the enum is two values, and stays two."""
    meeting = co.compile_schema()["objects"]["meeting"]
    assert meeting["enums"]["review_status"] == ["needs-review", "confirmed"]


def test_entity_and_project_type_are_pinned_discriminators():
    """#44: `type` on entity/project is the object discriminator and was
    unconstrained — a hand-edited dossier carrying `type: sprocket` passed
    conformance silently. Pinned to a single-value enum so validation catches
    it. (`meeting.type` is a different axis — the meeting *kind* — and stays
    its own multi-value enum; `person` has no `type` field at all.)"""
    objects = co.compile_schema()["objects"]
    assert objects["entity"]["enums"]["type"] == ["entity"]
    assert objects["project"]["enums"]["type"] == ["project"]
