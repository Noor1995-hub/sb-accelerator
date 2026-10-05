"""Migration 009 (#263): Obsidian's Bookmarks list is the sidebar menu and
Notebook Navigator is switched off. Made-up vaults only."""
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


def load(slug="009-structure-version-10"):
    spec = importlib.util.spec_from_file_location(slug, MIGRATIONS / slug / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root: Path, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read(root: Path, rel):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def vault_v9(tmp_path: Path) -> Path:
    """A structure-9 vault as #240 left it, lived in: Navigator on and in the
    sidebar, an owner's own bookmark and settings."""
    root = tmp_path / "vault"
    (root / "99-workflow-config").mkdir(parents=True)
    (root / "structure-version").write_text("9\n", encoding="utf-8")
    write(root, OBS / "community-plugins.json",
          ["dataview", "obsidian-minimal-settings", "obsidian-style-settings", "notebook-navigator"])
    write(root, OBS / "bookmarks.json", {"items": [
        {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"},
        {"type": "file", "ctime": 2, "path": "20-meetings/Meetings.base", "title": "Old meetings"}]})
    write(root, OBS / "daily-notes.json", {"folder": "60-daily-notes", "template": "tpl.md"})
    write(root, OBS / "app.json", {"alwaysUpdateLinks": True, "userIgnoreFilters": ["_messages/"]})
    write(root, OBS / "workspace.json", {
        "left": {"type": "split", "width": 400, "children": [{"type": "tabs", "currentTab": 1, "children": [
            {"id": "a", "type": "leaf", "state": {"type": "file-explorer", "state": {}}},
            {"id": "b", "type": "leaf", "state": {"type": "notebook-navigator", "state": {}}},
            {"id": "c", "type": "leaf", "state": {"type": "bookmarks", "state": {}}}]}]},
        "lastOpenFiles": ["x.md"]})
    return root


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 10 and module.LOSSY


def test_apply_lands_the_menu_and_keeps_the_owners_own(tmp_path):
    root = vault_v9(tmp_path)
    module = load()
    result = module.apply(root)
    assert result == {"navigator": "switched off", "bookmarks": "merged", "daily_notes": "merged",
                      "app": "merged", "workspace": "merged"}
    assert "notebook-navigator" not in read(root, OBS / "community-plugins.json")
    items = read(root, OBS / "bookmarks.json")["items"]
    assert items[:len(module.shipped_menu())] == module.shipped_menu()
    assert items[len(module.shipped_menu()):] == [
        {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}]
    daily = read(root, OBS / "daily-notes.json")
    assert daily["autorun"] is True and daily["template"] == "tpl.md"
    app = read(root, OBS / "app.json")
    assert app["newFileFolderPath"] == "80-thoughts-ideas" and app["userIgnoreFilters"] == ["_messages/"]
    ws = read(root, OBS / "workspace.json")
    tabs = ws["left"]["children"][0]
    assert [c["state"]["type"] for c in tabs["children"]] == ["bookmarks", "file-explorer"]
    assert tabs["currentTab"] == 0 and ws["left"]["width"] == 280 and ws["lastOpenFiles"] == ["x.md"]
    module.verify(root)


def test_a_vault_without_bookmarks_or_a_bookmarks_tab_gets_both(tmp_path):
    root = vault_v9(tmp_path)
    (root / OBS / "bookmarks.json").unlink()
    ws = read(root, OBS / "workspace.json")
    ws["left"]["children"][0]["children"].pop()        # no bookmarks leaf
    write(root, OBS / "workspace.json", ws)
    module = load()
    module.apply(root)
    assert read(root, OBS / "bookmarks.json")["items"] == module.shipped_menu()
    types = [c["state"]["type"] for c in read(root, OBS / "workspace.json")["left"]["children"][0]["children"]]
    assert types[0] == "bookmarks"


def test_apply_is_idempotent(tmp_path):
    root = vault_v9(tmp_path)
    module = load()
    module.apply(root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert set(module.apply(root).values()) == {"already off", "unchanged"}
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_unreadable_settings_stop_the_migration(tmp_path):
    root = vault_v9(tmp_path)
    (root / OBS / "bookmarks.json").write_text("{not json", encoding="utf-8")
    module = load()
    with pytest.raises(module.MigrationError):
        module.apply(root)


def test_the_whole_chain_lands_on_the_shipped_template(tmp_path):
    """A fresh vault and an upgraded one converge: running every sidebar
    migration (003-006, then 009) over the template's own settings changes
    none of them, so a template refresh cannot fight the migrations."""
    root = tmp_path / "fresh"
    shutil.copytree(TEMPLATE / ".obsidian", root / ".obsidian")
    files = ["community-plugins.json", "bookmarks.json", "daily-notes.json", "app.json", "workspace.json"]
    shipped = {f: read(root, OBS / f) for f in files}
    (root / "60-daily-notes").mkdir()
    for slug in ["003-structure-version-4", "004-structure-version-5", "005-structure-version-6",
                 "006-structure-version-7", "009-structure-version-10"]:
        load(slug).apply(root)
    assert not (root / OBS / "plugins" / "notebook-navigator").exists()
    for f in files:
        assert read(root, OBS / f) == shipped[f], f"{f} moved under the migration chain"


def test_run_through_the_framework_bumps_to_10(tmp_path):
    root = vault_v9(tmp_path)
    result = migrate.run(root, "2026-10-05", stamp="2026-10-05-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-10"]
    assert result["structure_version"] == 10
