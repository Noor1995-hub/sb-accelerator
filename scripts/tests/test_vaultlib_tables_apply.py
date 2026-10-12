"""Apply a filled-in table (#272)."""
from vaultlib import markdown, tables
from test_vaultlib_tables_export import make_vault
from test_vaultlib_tables_import import col, exported, save


def fm(root, rel):
    return markdown.split_frontmatter((root / rel).read_text(encoding="utf-8"))


def test_updates_are_written_and_nothing_else_moves(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    before = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    result = tables.apply(root, rel, today="2026-10-12")
    after = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    assert result["written"] == [{"key": "50-people/jan-peeters.md", "prop": "role"}]
    assert after == before.replace("role:", 'role: "CEO"')


def test_a_rename_updates_the_heading(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Name")] = "Jan Peeters-Maes"
    save(root, rel, book)
    tables.apply(root, rel, today="2026-10-12")
    data, body = fm(root, "50-people/jan-peeters.md")
    assert data["person-name"] == "Jan Peeters-Maes" and "# Jan Peeters-Maes" in body


def test_new_people_entities_and_projects_go_through_their_creators(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    row = [""] * len(book["People"][0])
    row[col(book, "People", "Name")] = "Piet Janssens"
    row[col(book, "People", "Relationship")] = "external"
    book["People"].append(row)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    assert result["created"][0]["key"] == "50-people/piet-janssens.md"
    assert fm(root, "50-people/piet-janssens.md")[0]["relationship"] == "external"

    rel, book = exported(root, "projects")
    row = [""] * len(book["Projects"][0])
    for header, value in (("Project", "CRM pilot"), ("Entity", "Acme"), ("Owner", "Jan Peeters"),
                          ("Status", "paused"), ("Type", "initiative")):
        row[col(book, "Projects", header)] = value
    book["Projects"].append(row)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    key = result["created"][0]["key"]
    assert (root / key).parent.joinpath("decisions").is_dir()
    assert fm(root, key)[0]["status"] == "paused"


def test_an_unknown_entity_on_a_new_project_fails_that_row_only(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "projects")
    good = list(book["Projects"][1])
    good[col(book, "Projects", "Status")] = "paused"
    book["Projects"][1] = good
    bad = [""] * len(book["Projects"][0])
    for header, value in (("Project", "Ghost"), ("Entity", "Nobody"), ("Owner", "Jan Peeters"),
                          ("Status", "active"), ("Type", "initiative")):
        bad[col(book, "Projects", header)] = value
    book["Projects"].append(bad)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    assert result["written"] and not result["created"]
    assert any("Nobody" in r["reason"] for r in result["plan"]["refused"])


def test_dry_run_writes_nothing(tmp_path, mark_stale):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Role")] = "CEO"
    save(root, rel, book)
    stamp = mark_stale(root / "50-people/jan-peeters.md")
    tables.plan(root, rel)
    assert (root / "50-people/jan-peeters.md").stat().st_mtime_ns == stamp


def test_a_new_entity_row_never_updates_an_existing_entity(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root, "entities")
    row = [""] * len(book["Entities"][0])
    row[col(book, "Entities", "Entity")] = "Acme"
    row[col(book, "Entities", "Status")] = "dormant"
    book["Entities"].append(row)
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    # Final review: refused in the plan itself now, before anything is written.
    assert "already exists" in result["plan"]["refused"][0]["reason"]
    assert result["created"] == [] and result["failed"] == []
    assert fm(root, "40-entities/acme/dossier.md")[0]["status"] == "active"


def _legacy(root):
    (root / "50-people/sofie-maes.md").write_text(
        '---\nperson-name: "Sofie Maes"\nslug: sofie-maes\nrelationship: external\n'
        'company: "LLBG"\nrole:\n---\n# Sofie Maes\n', encoding="utf-8")


def _row(book, key):
    return next(r for r in book["People"] if r[0] == key)


def test_the_entity_cell_shows_a_legacy_company_and_an_unchanged_one_is_skipped(tmp_path):
    root = make_vault(tmp_path)
    _legacy(root)
    rel, book = exported(root)
    assert _row(book, "50-people/sofie-maes.md")[col(book, "People", "Entity")] == "LLBG"
    assert tables.plan(root, rel)["counts"]["updates"] == 0
    assert tables.plan(root, rel)["counts"]["conflicts"] == 0


def test_resolving_a_legacy_company_sets_the_entity_and_drops_company(tmp_path):
    root = make_vault(tmp_path)
    _legacy(root)
    rel, book = exported(root)
    _row(book, "50-people/sofie-maes.md")[col(book, "People", "Entity")] = "Acme"
    save(root, rel, book)
    result = tables.apply(root, rel, today="2026-10-12")
    assert result["written"] == [{"key": "50-people/sofie-maes.md", "prop": "entity"}]
    data, _ = fm(root, "50-people/sofie-maes.md")
    assert data["entity"] == "acme" and "company" not in data
