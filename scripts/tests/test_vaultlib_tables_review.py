"""Final-review fixes for the Excel round trip (#272)."""
import re
import shutil
import zipfile

import pytest

from vaultlib import markdown, tables, xlsx
from test_vaultlib_tables_export import make_vault
from test_vaultlib_tables_import import col, exported, save


def fm(root, rel):
    return markdown.split_frontmatter((root / rel).read_text(encoding="utf-8"))


def add_entity(root, slug, name, parent=None):
    (root / "40-entities" / slug).mkdir(parents=True)
    extra = f"parent: {parent}\n" if parent else ""
    (root / "40-entities" / slug / "dossier.md").write_text(
        f'---\ntype: entity\nentity-name: "{name}"\nslug: {slug}\nstatus: active\n{extra}---\n'
        f"# {name}\n", encoding="utf-8")


def row_of(book, title, key):
    return next(r for r in book[title][1:] if r and r[0] == key)


# I1 — updates keep the creators' rules
def test_an_entity_cannot_become_its_own_parent(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "entities")
    row_of(book, "Entities", "40-entities/acme/dossier.md")[col(book, "Entities", "Part of")] = "Acme"
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["updates"] == 0 and "own parent" in p["refused"][0]["reason"]


def test_a_team_cannot_become_a_parent(tmp_path):
    root = make_vault(tmp_path)
    add_entity(root, "acme-finance", "Acme Finance", parent="acme")
    add_entity(root, "beta", "Beta")
    rel, book = exported(root, "entities")
    row_of(book, "Entities", "40-entities/beta/dossier.md")[col(book, "Entities", "Part of")] = "Acme Finance"
    save(root, rel, book)
    assert "one level" in tables.plan(root, rel)["refused"][0]["reason"]


def test_setting_a_parent_writes_the_part_of_line(tmp_path):
    root = make_vault(tmp_path)
    add_entity(root, "beta", "Beta")
    rel, book = exported(root, "entities")
    row_of(book, "Entities", "40-entities/beta/dossier.md")[col(book, "Entities", "Part of")] = "Acme"
    save(root, rel, book)
    tables.apply(root, rel, today="2026-10-12")
    data, body = fm(root, "40-entities/beta/dossier.md")
    assert data["parent"] == "acme" and "Part of" in body


def test_a_project_cannot_be_its_own_parent(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    book["Projects"][1][col(book, "Projects", "Parent")] = "ERP rollout"
    save(root, rel, book)
    assert "own parent" in tables.plan(root, rel)["refused"][0]["reason"]


def test_an_email_is_checked_and_casefolded(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Email")] = "Jan.Peeters@ACME.example"
    save(root, rel, book)
    assert tables.plan(root, rel)["updates"][0]["value"] == "jan.peeters@acme.example"
    book["People"][1][col(book, "People", "Email")] = "not an email"
    save(root, rel, book)
    assert tables.plan(root, rel)["counts"]["refused"] == 1


# I2 — a copied row never renames someone
def test_a_copied_row_with_its_key_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    copy = list(book["People"][1])
    copy[col(book, "People", "Name")] = "Piet Janssens"
    book["People"].append(copy)
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["updates"] == 0 and p["counts"]["refused"] == 2
    assert "appears 2 times" in p["refused"][0]["reason"]


def test_a_rename_to_another_objects_name_is_refused(tmp_path):
    root = make_vault(tmp_path)
    (root / "50-people/an-de-smet.md").write_text(
        '---\nperson-name: "An De Smet"\nslug: an-de-smet\n---\n# An De Smet\n', encoding="utf-8")
    rel, book = exported(root)
    row_of(book, "People", "50-people/jan-peeters.md")[col(book, "People", "Name")] = "An De Smet"
    save(root, rel, book)
    assert "already has this name" in tables.plan(root, rel)["refused"][0]["reason"]


# I3 — the dry run predicts what apply would refuse
def test_a_line_break_in_a_cell_is_refused_in_the_dry_run(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO\nand founder"
    save(root, rel, book)
    assert "one line" in tables.plan(root, rel)["refused"][0]["reason"]


def test_an_existing_name_on_a_new_row_is_refused_in_the_dry_run(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    row = [""] * len(book["People"][0])
    row[col(book, "People", "Name")] = "jan peeters"
    book["People"].append(row)
    save(root, rel, book)
    p = tables.plan(root, rel)
    assert p["counts"]["new"] == 0 and "already" in p["refused"][0]["reason"]


# I4 — a refused new row writes nothing
def test_a_refused_duplicate_person_leaves_the_existing_note_untouched(tmp_path):
    root = make_vault(tmp_path)
    before = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    rel, book = exported(root)
    row = [""] * len(book["People"][0])
    row[col(book, "People", "Name")] = "Jan Peeters"
    row[col(book, "People", "Email")] = "other@x.be"
    book["People"].append(row)
    save(root, rel, book)
    tables.apply(root, rel, today="2026-10-12")
    assert (root / "50-people/jan-peeters.md").read_text(encoding="utf-8") == before


# Minors
def test_cells_without_a_reference_are_read_in_order(tmp_path):
    path = tmp_path / "t.xlsx"
    xlsx.write(path, [{"name": "S", "rows": [["a", "b"], ["c", "d"]], "state": "visible",
                       "hidden_cols": set(), "highlight_empty": False, "validations": []}])
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["xl/worksheets/sheet1.xml"] = re.sub(rb' r="[A-Z]+\d+"', b"", parts["xl/worksheets/sheet1.xml"])
    with zipfile.ZipFile(path, "w") as z:
        for n, b in parts.items():
            z.writestr(n, b)
    assert xlsx.read(path)["S"] == [["a", "b"], ["c", "d"]]


def test_an_excel_error_value_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "#N/A"
    save(root, rel, book)
    assert tables.plan(root, rel)["counts"]["refused"] == 1


def test_an_empty_list_gets_no_dropdown(tmp_path):
    root = make_vault(tmp_path)
    shutil.rmtree(root / "40-entities")
    (root / "40-entities").mkdir()
    rel = tables.export(root, "people", today="2026-10-12")["path"]
    with zipfile.ZipFile(root / rel) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert not re.search(r"\$2:\$[A-Z]+\$1<", sheet)


def test_clearing_a_list_writes_an_empty_list(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Projects")] = ""
    save(root, rel, book)
    tables.apply(root, rel, today="2026-10-12")
    assert "projects: []" in (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")


def test_a_workbook_without_its_hidden_sheets_asks_to_export_again(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    del book["_original"]
    save(root, rel, book)
    with pytest.raises(tables.TablesError, match="export again"):
        tables.plan(root, rel)
