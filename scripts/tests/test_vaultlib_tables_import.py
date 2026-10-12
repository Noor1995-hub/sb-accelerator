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


def test_company_not_an_entity_is_kept_as_text_and_listed(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Company")] = "LLBG"
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["updates"][0]["value"] == "LLBG"
    assert p["unknown"] == [{"header": "Company", "value": "LLBG", "kind": "entity"}]


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
