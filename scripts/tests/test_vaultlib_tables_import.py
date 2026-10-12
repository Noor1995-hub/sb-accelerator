"""Import plan of a filled-in table (#272)."""
from pathlib import Path

import pytest

from vaultlib import tables, xlsx
from test_vaultlib_tables_export import make_vault


def exported(root, table="people"):
    rel = tables.export(root, table, today="2026-10-12")["path"]
    book = xlsx.read(root / rel)
    width = len(book[table.title()][0])
    book[table.title()] = [r + [""] * (width - len(r)) for r in book[table.title()]]
    return rel, book


def save(root, rel, book):
    """Rewrite the workbook with the owner's edits, keeping the hidden sheets."""
    states = {"_lists": "hidden", "_original": "veryHidden", "_meta": "veryHidden"}
    sheets = [{"name": name, "rows": rows, "state": states.get(name, "visible"),
               "hidden_cols": {0} if name not in states else set(),
               "highlight_empty": False, "validations": []}
              for name, rows in book.items()]
    xlsx.write(root / rel, sheets)


def col(book, title, header):
    return book[title][0].index(header)


def test_untouched_export_plans_nothing(tmp_path):
    root = make_vault(tmp_path)
    rel, _ = exported(root)
    assert tables.plan(root, rel)["counts"] == {"updates": 0, "new": 0, "conflicts": 0,
                                                "refused": 0, "unknown": 0}


def test_a_filled_cell_is_an_update(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["updates"] == [{"key": "50-people/jan-peeters.md", "prop": "role", "header": "Role",
                             "from": "", "to": "CEO", "value": "CEO"}]


def test_vault_changed_too_is_a_conflict(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    note = root / "50-people/jan-peeters.md"
    note.write_text(note.read_text(encoding="utf-8").replace("role:", 'role: "CFO"'), encoding="utf-8")
    p = tables.plan(root, rel)
    assert p["updates"] == [] and p["conflicts"][0]["vault"] == "CFO"


def test_vault_already_equal_is_nothing(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CFO"
    save(root, rel, book)
    note = root / "50-people/jan-peeters.md"
    note.write_text(note.read_text(encoding="utf-8").replace("role:", 'role: "CFO"'), encoding="utf-8")
    assert tables.plan(root, rel)["counts"]["updates"] == 0


def test_bad_choice_unknown_and_ambiguous_names_are_refused(tmp_path):
    root = make_vault(tmp_path)
    (root / "50-people/jan-de-wit.md").write_text(
        '---\nperson-name: "Jan Peeters"\nslug: jan-de-wit\n---\n', encoding="utf-8")
    rel, book = exported(root, "projects")
    row = book["Projects"][1]
    row[col(book, "Projects", "Status")] = "busy"
    row[col(book, "Projects", "Owner")] = "jan peeters"          # two people carry this name
    save(root, rel, book)
    reasons = " | ".join(r["reason"] for r in tables.plan(root, rel)["refused"])
    assert "busy" in reasons and "several" in reasons


def test_an_entity_that_does_not_exist_is_refused_and_listed(tmp_path):
    """#273: a person's entity is a real link now, not text."""
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Entity")] = "LLBG"
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["updates"] == 0 and p["counts"]["refused"] == 1
    assert p["unknown"] == [{"header": "Entity", "value": "LLBG", "kind": "entity"}]


def test_stance_and_role_in_decision_are_choices(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Stance")] = "Champion"
    book["People"][1][col(book, "People", "Role in decision")] = "sponsor"
    save(root, rel, book)
    values = {u["prop"]: u["value"] for u in tables.plan(root, rel)["updates"]}
    assert values == {"stance": "champion", "decision-role": "sponsor"}


def test_clearing_a_required_field_and_moving_a_project_are_refused(tmp_path):
    root = make_vault(tmp_path)
    (root / "40-entities/beta").mkdir()
    (root / "40-entities/beta/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Beta"\nslug: beta\nstatus: active\n---\n', encoding="utf-8")
    rel, book = exported(root, "projects")
    row = book["Projects"][1]
    row[col(book, "Projects", "Project")] = ""
    row[col(book, "Projects", "Entity")] = "Beta"
    save(root, rel, book)
    reasons = " | ".join(r["reason"] for r in tables.plan(root, rel)["refused"])
    assert "required" in reasons and "another entity" in reasons


def test_new_rows_need_their_required_fields(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    width = len(book["Projects"][0])
    good = [""] * width
    good[col(book, "Projects", "Project")] = "CRM pilot"
    good[col(book, "Projects", "Entity")] = "Acme"
    good[col(book, "Projects", "Owner")] = "Jan Peeters"
    good[col(book, "Projects", "Status")] = "active"
    good[col(book, "Projects", "Type")] = "initiative"
    bad = [""] * width
    bad[col(book, "Projects", "Project")] = "No entity"
    book["Projects"] += [good, bad]
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert [n["values"]["project-name"] for n in p["new"]] == ["CRM pilot"]
    assert any("Entity" in r["reason"] for r in p["refused"])


def test_a_numeric_cell_in_a_link_column_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    book["Projects"][1][col(book, "Projects", "Owner")] = "45943"
    save(root, rel, book)
    assert tables.plan(root, rel)["counts"]["refused"] == 1


def test_moved_columns_refuse_the_whole_import(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    for row in book["People"]:
        row[1], row[2] = row[2], row[1]
    save(root, rel, book)
    with pytest.raises(tables.TablesError, match="columns were changed"):
        tables.plan(root, rel)


def test_a_deleted_row_deletes_nothing_and_a_stale_key_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"] = book["People"][:1] + [["50-people/gone.md", "Gone"]]
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["updates"] == 0 and "no longer in the vault" in p["refused"][0]["reason"]


# --- review 2026-10-12: owner words and per-entity project names ------------

def _second_entity_with_same_project_name(root):
    (root / "40-entities/beta").mkdir(parents=True)
    (root / "40-entities/beta/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Beta"\nslug: beta\nstatus: active\n---\n# Beta\n',
        encoding="utf-8")
    (root / "30-projects/beta-erp").mkdir(parents=True)
    (root / "30-projects/beta-erp/index.md").write_text(
        '---\ntype: project\nproject-name: "ERP rollout"\nslug: beta-erp\nstatus: active\n'
        'project-type: initiative\nentity: beta\nowner: jan-peeters\nstakeholders: []\n---\n',
        encoding="utf-8")


def test_project_type_and_status_show_the_tables_words(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    row = book["Projects"][1]
    assert row[col(book, "Projects", "Type")] == "Project"
    assert row[col(book, "Projects", "Status")] == "Active"
    assert any("Responsibility" in r for r in book["_lists"])
    row[col(book, "Projects", "Type")] = "Responsibility"
    save(root, rel, book)
    [update] = tables.plan(root, rel)["updates"]
    assert (update["prop"], update["value"]) == ("project-type", "area-of-responsibility")


def test_the_raw_value_is_still_accepted(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    book["Projects"][1][col(book, "Projects", "Status")] = "paused"
    save(root, rel, book)
    [update] = tables.plan(root, rel)["updates"]
    assert update["value"] == "paused"


def test_the_same_project_name_under_another_entity_is_allowed(tmp_path):
    root = make_vault(tmp_path)
    (root / "40-entities/beta").mkdir(parents=True)
    (root / "40-entities/beta/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Beta"\nslug: beta\nstatus: active\n---\n# Beta\n',
        encoding="utf-8")
    rel, book = exported(root, "projects")
    new = [""] * len(book["Projects"][0])
    for header, value in (("Project", "ERP rollout"), ("Status", "Active"), ("Type", "Project"),
                          ("Entity", "Beta"), ("Owner", "Jan Peeters")):
        new[col(book, "Projects", header)] = value
    book["Projects"].append(new)
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["refused"] == 0 and len(p["new"]) == 1
    # ...but not twice under the same entity.
    book["Projects"][-1][col(book, "Projects", "Entity")] = "Acme"
    save(root, rel, book)
    assert tables.plan(root, rel)["counts"]["refused"] == 1


def test_shared_project_names_are_told_apart_by_entity(tmp_path):
    root = make_vault(tmp_path)
    _second_entity_with_same_project_name(root)
    shown = tables.names(root)["project"]
    assert shown == {"acme-erp": "ERP rollout (Acme)", "beta-erp": "ERP rollout (Beta)"}
    rel, book = exported(root, "people")
    book["People"][1][col(book, "People", "Projects")] = "ERP rollout (Beta)"
    save(root, rel, book)
    [update] = tables.plan(root, rel)["updates"]
    assert update["value"] == ["beta-erp"]
