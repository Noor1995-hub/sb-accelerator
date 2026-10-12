"""Export of People / Projects / Entities to Excel (#272)."""
import json
from pathlib import Path

import pytest

from vaultlib import tables, xlsx

TEMPLATE = Path(__file__).resolve().parents[2] / "plugin" / "template"


def make_vault(tmp_path):
    root = tmp_path / "vault"
    for d in ("10-inbox", "20-meetings", "99-workflow-config", "_heavy-assets",
              "50-people", "40-entities/acme", "30-projects/acme-erp"):
        (root / d).mkdir(parents=True)
    for rel in ("50-people/People.base", "30-projects/Projects.base", "40-entities/Entities.base"):
        (root / rel).write_text((TEMPLATE / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (root / "50-people/jan-peeters.md").write_text(
        '---\nperson-name: "Jan Peeters"\nslug: jan-peeters\nrelationship: external\n'
        'entity: acme\nrole:\nprojects: [acme-erp]\nmeetings-30d: 4\n---\n# Jan Peeters\n',
        encoding="utf-8")
    (root / "40-entities/acme/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Acme"\nslug: acme\nstatus: active\n'
        'entity-type: client\nowner: jan-peeters\n---\n# Acme\n', encoding="utf-8")
    (root / "30-projects/acme-erp/index.md").write_text(
        '---\ntype: project\nproject-name: "ERP rollout"\nslug: acme-erp\nstatus: active\n'
        'project-type: initiative\nentity: acme\nowner: jan-peeters\nstakeholders: []\n'
        'meetings-7d: 2\n---\n', encoding="utf-8")
    return root


def test_people_columns_follow_the_owners_view_and_skip_machine_fields():
    spec = tables.TABLES["people"]
    got = tables.columns(spec, (TEMPLATE / "50-people/People.base").read_text(encoding="utf-8"), None)
    props = [c["prop"] for c in got["columns"]]
    headers = [c["header"] for c in got["columns"]]
    assert props[:7] == ["person-name", "relationship", "entity", "role", "decision-role",
                         "stance", "projects"]
    assert headers[:7] == ["Name", "Relationship", "Entity", "Role", "Role in decision",
                           "Stance", "Projects"]
    assert "email" in props                       # editable, not in the view → appended
    assert "meetings-30d" not in props and "last-met" not in props


def test_formula_columns_map_to_their_one_property():
    spec = tables.TABLES["projects"]
    got = tables.columns(spec, (TEMPLATE / "30-projects/Projects.base").read_text(encoding="utf-8"), None)
    by_prop = {c["prop"]: c["header"] for c in got["columns"]}
    assert by_prop["status"] == "Status" and by_prop["project-type"] == "Type"
    assert by_prop["entity"] == "Entity" and by_prop["owner"] == "Owner"
    assert "next-milestone" not in by_prop and "meetings-30d" not in by_prop


def test_entities_part_of_maps_to_parent_and_name_takes_the_first_column():
    spec = tables.TABLES["entities"]
    got = tables.columns(spec, (TEMPLATE / "40-entities/Entities.base").read_text(encoding="utf-8"), None)
    props = [c["prop"] for c in got["columns"]]
    assert props.count("entity-name") == 1 and "parent" in props


def test_unreadable_base_falls_back_with_a_warning():
    got = tables.columns(tables.TABLES["people"], "garbage: [", None)
    assert [c["prop"] for c in got["columns"]][0] == "person-name"
    assert got["warnings"]


def test_export_writes_the_workbook(tmp_path):
    root = make_vault(tmp_path)
    result = tables.export(root, "people", today="2026-10-12")
    assert result["path"] == "_heavy-assets/people-update-2026-10-12.xlsx"
    book = xlsx.read(root / result["path"])
    header, row = book["People"][0], book["People"][1]
    assert header[0] == "_key" and row[0] == "50-people/jan-peeters.md"
    assert row[header.index("Projects")] == "ERP rollout"
    assert row[header.index("Entity")] == "Acme"
    assert book["_original"][0][:3] == ["_key", "person-name", "relationship"]
    meta = dict((r[0], r[1]) for r in book["_meta"])
    assert meta["table"] == "people" and json.loads(meta["headers"]) == header
    assert "Acme" in [c for r in book["_lists"] for c in r]


def test_a_second_export_on_the_same_day_gets_a_suffix(tmp_path):
    root = make_vault(tmp_path)
    tables.export(root, "people", today="2026-10-12")
    again = tables.export(root, "people", today="2026-10-12")
    assert again["path"].endswith("people-update-2026-10-12-2.xlsx")


def test_projects_export_shows_names_not_slugs(tmp_path):
    root = make_vault(tmp_path)
    book = xlsx.read(root / tables.export(root, "projects", today="2026-10-12")["path"])
    header, row = book["Projects"][0], book["Projects"][1]
    assert row[header.index("Entity")] == "Acme" and row[header.index("Owner")] == "Jan Peeters"


def test_unknown_table_is_refused(tmp_path):
    with pytest.raises(tables.TablesError):
        tables.export(make_vault(tmp_path), "meetings", today="2026-10-12")


def test_the_name_column_comes_first_when_the_view_lacks_it():
    """Entities' view shows the name through a formula over name and parent,
    which maps to no single property — the name still leads."""
    spec = tables.TABLES["entities"]
    got = tables.columns(spec, (TEMPLATE / "40-entities/Entities.base").read_text(encoding="utf-8"), None)
    assert got["columns"][0]["prop"] == "entity-name"


def test_columns_without_any_name_in_the_base_get_a_readable_header():
    got = tables.columns(tables.TABLES["people"], (TEMPLATE / "50-people/People.base").read_text(encoding="utf-8"), None)
    assert {c["prop"]: c["header"] for c in got["columns"]}["email"] == "Email"


def test_people_export_carries_no_page_text(tmp_path):
    root = make_vault(tmp_path)
    path = root / "50-people/jan-peeters.md"
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n## What I know\n\n- 2026-10-08 — Secret fact. (meeting · [[m]])\n",
                    encoding="utf-8")
    result = tables.export(root, "people", today="2026-10-12")
    book = xlsx.read(root / result["path"])
    cells = [str(c) for sheet in book.values() for row in sheet for c in row]
    assert not any("Secret fact" in c for c in cells)
