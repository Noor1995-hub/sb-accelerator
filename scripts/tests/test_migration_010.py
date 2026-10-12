"""Migration 010: Inbox becomes Input, the menu takes its new order, and
Inbox.base is removed when unmodified. Made-up vaults only."""
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
OLD = Path("99-workflow-config/views/Inbox.base")


def load(slug="010-structure-version-11"):
    spec = importlib.util.spec_from_file_location(slug, MIGRATIONS / slug / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shipped_inbox_base() -> bytes:
    """Inbox.base exactly as 0.13.7 shipped it (checked-in fixture; CI clones shallowly)."""
    return (Path(__file__).parent / "data" / "inbox-base-0.13.7.base").read_bytes()


def vault_v10(tmp_path: Path, inbox_base: bytes = None) -> Path:
    root = tmp_path / "vault"
    (root / "99-workflow-config" / "views").mkdir(parents=True)
    (root / "structure-version").write_text("10\n", encoding="utf-8")
    (root / OLD).write_bytes(shipped_inbox_base() if inbox_base is None else inbox_base)
    items = load("009-structure-version-10").shipped_menu() + [
        {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}]
    (root / OBS).mkdir()
    (root / OBS / "bookmarks.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return root


def read_items(root):
    return json.loads((root / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 11 and module.LOSSY
    assert [t for t, _ in module.MENU] == [
        "Start here", "Daily notes", "Thoughts & ideas", "Meetings", "Projects",
        "People", "Entities", "Decisions", "Input"]
    assert [t for t, _ in module.LIBRARY] == [
        "Recent", "Resources", "Heavy assets", "Private", "Archive"]


def test_shipped_menu_is_the_template_menu_before_actions():
    """011 (#257) added To Do's to the template menu and 012 renamed two of
    its files; everything else is 010's."""
    shipped = json.loads((TEMPLATE / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]
    renamed = load("012-structure-version-13").rename_paths(load().shipped_menu())
    assert renamed == [i for i in shipped if i.get("title") != "To Do's"]


def test_apply_lands_the_new_menu_keeps_the_owners_own_and_removes_inbox_base(tmp_path):
    root = vault_v10(tmp_path)
    module = load()
    assert module.apply(root) == {"bookmarks": "merged", "inbox_base": "removed"}
    items = read_items(root)
    assert items[:len(module.shipped_menu())] == module.shipped_menu()
    assert items[len(module.shipped_menu()):] == [
        {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}]
    assert all(i.get("path") != OLD.as_posix() for i in items)
    assert not (root / OLD).exists()


def test_the_owners_own_library_entries_survive_in_my_library(tmp_path):
    root = vault_v10(tmp_path)
    items = read_items(root)
    items[-2]["items"].append({"type": "file", "ctime": 7, "path": "70-resources/x.md", "title": "X"})
    (root / OBS / "bookmarks.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    load().apply(root)
    mine = [i for i in read_items(root) if i.get("title") == "My library"]
    assert mine and mine[0]["items"] == [
        {"type": "file", "ctime": 7, "path": "70-resources/x.md", "title": "X"}]


def test_a_modified_inbox_base_is_kept_and_reported(tmp_path):
    root = vault_v10(tmp_path, inbox_base=shipped_inbox_base() + b"# my tweak\n")
    result = load().apply(root)
    assert result["inbox_base"].startswith("kept")
    assert (root / OLD).is_file()


def test_crlf_copy_of_the_shipped_inbox_base_still_counts_as_unmodified(tmp_path):
    root = vault_v10(tmp_path, inbox_base=shipped_inbox_base().replace(b"\n", b"\r\n"))
    assert load().apply(root)["inbox_base"] == "removed"


def test_apply_is_idempotent(tmp_path):
    root = vault_v10(tmp_path)
    module = load()
    module.apply(root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert module.apply(root) == {"bookmarks": "unchanged", "inbox_base": "absent"}
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_unreadable_bookmarks_stop_the_migration(tmp_path):
    root = vault_v10(tmp_path)
    (root / OBS / "bookmarks.json").write_text("{not json", encoding="utf-8")
    module = load()
    with pytest.raises(module.MigrationError):
        module.apply(root)


def test_the_whole_chain_lands_on_the_shipped_template(tmp_path):
    root = tmp_path / "fresh"
    shutil.copytree(TEMPLATE / ".obsidian", root / ".obsidian")
    (root / "60-daily-notes").mkdir()
    shipped = read_items(root)
    load("009-structure-version-10").apply(root)
    load().apply(root)
    load("011-structure-version-12").apply(root)
    load("012-structure-version-13").apply(root)
    assert read_items(root) == shipped


def test_run_through_the_framework_bumps_to_12(tmp_path):
    root = vault_v10(tmp_path)
    result = migrate.run(root, "2026-10-06", stamp="2026-10-06-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-11", "structure-version-12", "structure-version-13", "structure-version-14"]
    assert result["structure_version"] == 14
