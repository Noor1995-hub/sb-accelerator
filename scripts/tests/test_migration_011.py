"""Migration 011: the To Do's entry joins the menu under Thoughts & ideas,
and nothing else moves. Made-up vaults only."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from vaultlib import migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
MIGRATIONS = REPO_ROOT / "plugin" / "migrations"
OBS = Path(".obsidian")
MINE = {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}


def load(slug="011-structure-version-12"):
    spec = importlib.util.spec_from_file_location(slug, MIGRATIONS / slug / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vault_v11(tmp_path: Path, items=None) -> Path:
    root = tmp_path / "vault"
    (root / OBS).mkdir(parents=True)
    (root / "60-daily-notes").mkdir()
    (root / "structure-version").write_text("11\n", encoding="utf-8")
    if items is None:
        items = load("010-structure-version-11").shipped_menu() + [MINE]
    (root / OBS / "bookmarks.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return root


def read_items(root):
    return json.loads((root / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 12 and module.LOSSY is None


def test_shipped_menu_is_the_template_menu():
    shipped = json.loads((TEMPLATE / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]
    assert load("012-structure-version-13").rename_paths(load().shipped_menu()) == shipped


def test_actions_lands_under_thoughts_and_nothing_else_moves(tmp_path):
    root = vault_v11(tmp_path)
    before = read_items(root)
    assert load().apply(root)["bookmarks"] == "added"
    items = read_items(root)
    assert [i["title"] for i in items][:5] == [
        "Start here", "Daily notes", "Thoughts & ideas", "To Do's", "Meetings"]
    assert [i for i in items if i.get("title") != "To Do's"] == before
    assert items[-1] == MINE


def test_an_upgraded_menu_equals_a_fresh_one(tmp_path):
    root = vault_v11(tmp_path, items=load("010-structure-version-11").shipped_menu())
    load().apply(root)
    assert read_items(root) == load().shipped_menu()


@pytest.mark.parametrize("titles,expected", [
    (["Daily notes", "Meetings"], ["Daily notes", "To Do's", "Meetings"]),
    (["Meetings", "Thoughts & ideas"], ["Meetings", "Thoughts & ideas", "To Do's"]),
    (["Meetings"], ["To Do's", "Meetings"]),
])
def test_a_reordered_menu_gets_actions_next_to_what_is_left(tmp_path, titles, expected):
    menu = {e["title"]: e for e in load("010-structure-version-11").shipped_menu()
            if e["type"] == "file"}
    root = vault_v11(tmp_path, items=[menu[t] for t in titles])
    load().apply(root)
    assert [i["title"] for i in read_items(root)] == expected


def test_apply_is_idempotent_and_respects_an_actions_entry_already_there(tmp_path):
    root = vault_v11(tmp_path)
    module = load()
    module.apply(root)
    before = (root / OBS / "bookmarks.json").read_bytes()
    assert module.apply(root) == {"bookmarks": "unchanged", "types": "unchanged"}
    assert (root / OBS / "bookmarks.json").read_bytes() == before
    # The owner filed it in a group of their own: it stays there.
    grouped = [{"type": "group", "ctime": 2, "title": "Mine",
                "items": [dict(module.ACTIONS_ENTRY, title="To do")]}]
    root2 = vault_v11(tmp_path / "two", items=grouped)
    assert module.apply(root2)["bookmarks"] == "unchanged"


def test_a_vault_without_bookmarks_gets_the_entry(tmp_path):
    root = tmp_path / "bare"
    (root / OBS).mkdir(parents=True)
    load().apply(root)
    assert read_items(root) == [load().ACTIONS_ENTRY]
    load().verify(root)


def test_unreadable_bookmarks_stop_the_migration(tmp_path):
    root = vault_v11(tmp_path)
    (root / OBS / "bookmarks.json").write_text("{not json", encoding="utf-8")
    module = load()
    with pytest.raises(module.MigrationError):
        module.apply(root)


def test_the_whole_chain_lands_on_the_shipped_template(tmp_path):
    root = tmp_path / "fresh"
    shutil.copytree(TEMPLATE / ".obsidian", root / ".obsidian")
    (root / "60-daily-notes").mkdir()
    shipped = read_items(root)
    for slug in ("009-structure-version-10", "010-structure-version-11"):
        load(slug).apply(root)
    load().apply(root)
    load("012-structure-version-13").apply(root)
    assert read_items(root) == shipped


def test_run_through_the_framework_bumps_to_12(tmp_path):
    root = vault_v11(tmp_path)
    result = migrate.run(root, "2026-10-08", stamp="2026-10-08-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-12", "structure-version-13", "structure-version-14", "structure-version-15"]
    assert result["structure_version"] == 15


def test_property_types_match_the_template():
    shipped = json.loads((TEMPLATE / OBS / "types.json").read_text(encoding="utf-8"))["types"]
    assert {k: shipped[k] for k in load().TYPES} == load().TYPES


def test_property_types_are_added_and_the_owners_own_kept(tmp_path):
    """Include came up as a text field on a new note in a vault where no note
    was ticked yet: Obsidian guesses a type from values it has seen."""
    root = vault_v11(tmp_path)
    (root / OBS / "types.json").write_text(json.dumps(
        {"types": {"tags": "tags", "due": "text", "mine": "number"}}), encoding="utf-8")
    result = load().apply(root)
    assert result["types"] == "added absorbed, archived, done, include, projects, reviewed"
    types = json.loads((root / OBS / "types.json").read_text(encoding="utf-8"))["types"]
    assert types["include"] == "checkbox" and types["done"] == "checkbox"
    assert types["due"] == "text" and types["mine"] == "number" and types["tags"] == "tags"
    load().verify(root)
    assert load().apply(root)["types"] == "unchanged"


def test_unreadable_types_stop_the_migration(tmp_path):
    root = vault_v11(tmp_path)
    (root / OBS / "types.json").write_text("{nope", encoding="utf-8")
    module = load()
    with pytest.raises(module.MigrationError):
        module.apply(root)
