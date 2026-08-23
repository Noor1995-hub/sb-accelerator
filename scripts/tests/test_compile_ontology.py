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


def test_all_five_objects_compile():
    objects = co.compile_schema()["objects"]
    assert set(objects) == {"meeting", "project", "person", "decision", "entity"}
    for name, block in objects.items():
        assert block["required"], f"{name}: empty required list"


def test_project_type_enum_is_the_two_value_axis():
    project = co.compile_schema()["objects"]["project"]
    assert project["enums"]["project-type"] == ["initiative", "area-of-responsibility"]


def test_body_sections_are_carried_for_project_and_entity():
    objects = co.compile_schema()["objects"]
    assert objects["project"]["body_sections"] == [
        "Decisions", "Open Items", "Related Meetings",
    ]
    assert objects["entity"]["body_sections"] == [
        "Context", "Stakeholders", "Relationship History",
        "Meeting Log", "Sensitivities", "Engagements",
    ]


@pytest.mark.parametrize("object_name", ["meeting", "person", "decision"])
def test_objects_without_body_schema_omit_the_key(object_name):
    assert "body_sections" not in co.compile_schema()["objects"][object_name]
