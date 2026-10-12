"""Migration 012: To Do's.base and Thoughts & ideas.base get filenames a
plugin zip upload accepts, and everything that pointed at them follows.
Made-up vaults only."""
import importlib.util
import json
from pathlib import Path

import pytest

from vaultlib import migrate, provenance

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
MIGRATIONS = REPO_ROOT / "plugin" / "migrations"
OBS = Path(".obsidian")
OLD_TODOS, NEW_TODOS = "65-to-dos/To Do's.base", "65-to-dos/To Dos.base"
OLD_IDEAS, NEW_IDEAS = ("80-thoughts-ideas/Thoughts & ideas.base",
                        "80-thoughts-ideas/Thoughts and ideas.base")
MINE = {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}


def load(slug="012-structure-version-13"):
    spec = importlib.util.spec_from_file_location(slug, MIGRATIONS / slug / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vault_v12(tmp_path: Path, items=None) -> Path:
    root = tmp_path / "vault"
    (root / OBS).mkdir(parents=True)
    (root / "structure-version").write_text("12\n", encoding="utf-8")
    for rel in (OLD_TODOS, OLD_IDEAS):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"# {rel}, as the owner left it\n", encoding="utf-8")
    if items is None:
        items = load("011-structure-version-12").shipped_menu() + [MINE]
    (root / OBS / "bookmarks.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return root


def read_items(root):
    return json.loads((root / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 13 and module.LOSSY is None
    assert set(module.RENAMES.items()) == {(OLD_TODOS, NEW_TODOS), (OLD_IDEAS, NEW_IDEAS)}


def test_the_new_names_are_what_the_template_ships():
    for old, new in load().RENAMES.items():
        assert (TEMPLATE / new).is_file() and not (TEMPLATE / old).exists()


def test_files_are_renamed_with_the_owners_content(tmp_path):
    root = vault_v12(tmp_path)
    result = load().apply(root)
    assert result["files"] == {OLD_TODOS: "renamed", OLD_IDEAS: "renamed"}
    assert "needs_human" not in result
    for old, new in ((OLD_TODOS, NEW_TODOS), (OLD_IDEAS, NEW_IDEAS)):
        assert not (root / old).exists()
        assert (root / new).read_text(encoding="utf-8") == f"# {old}, as the owner left it\n"
    load().verify(root)


def test_menu_entries_follow_in_place_and_keep_their_titles(tmp_path):
    root = vault_v12(tmp_path)
    before = read_items(root)
    assert load().apply(root)["bookmarks"] == "renamed"
    after = read_items(root)
    assert [i.get("title") for i in after] == [i.get("title") for i in before]
    paths = {i.get("title"): i.get("path") for i in after}
    assert paths["To Do's"] == NEW_TODOS and paths["Thoughts & ideas"] == NEW_IDEAS
    assert after[-1] == MINE


def test_an_entry_in_the_owners_own_group_follows_too(tmp_path):
    grouped = [{"type": "group", "ctime": 2, "title": "Mine",
                "items": [{"type": "file", "ctime": 3, "path": OLD_TODOS, "title": "To do"}]}]
    root = vault_v12(tmp_path, items=grouped)
    load().apply(root)
    assert read_items(root)[0]["items"][0] == {
        "type": "file", "ctime": 3, "path": NEW_TODOS, "title": "To do"}


def test_a_duplicate_left_by_an_early_template_refresh_is_dropped():
    old = {"type": "file", "ctime": 9, "path": OLD_TODOS, "title": "To Do's"}
    new = dict(old, path=NEW_TODOS)
    owners = dict(old, title="Mine to do")
    assert load().rename_paths([old, MINE, new, owners]) == [
        new, MINE, dict(owners, path=NEW_TODOS)]


def test_both_names_present_keeps_both_and_reports_it(tmp_path):
    root = vault_v12(tmp_path)
    (root / NEW_TODOS).write_text("shipped\n", encoding="utf-8")
    result = load().apply(root)
    assert result["files"][OLD_TODOS].startswith("kept")
    assert (root / OLD_TODOS).is_file() and (root / NEW_TODOS).read_text(encoding="utf-8") == "shipped\n"
    assert any(OLD_TODOS in line for line in result["needs_human"])
    load().verify(root)


def test_workspace_tabs_and_recent_files_follow(tmp_path):
    root = vault_v12(tmp_path)
    workspace = {"main": {"children": [{"state": {"type": "bases", "state": {"file": OLD_IDEAS}}}]},
                 "lastOpenFiles": [OLD_TODOS, "Start here.md"]}
    (root / OBS / "workspace.json").write_text(json.dumps(workspace), encoding="utf-8")
    assert load().apply(root)["workspace"] == "renamed"
    after = json.loads((root / OBS / "workspace.json").read_text(encoding="utf-8"))
    assert after["main"]["children"][0]["state"]["state"]["file"] == NEW_IDEAS
    assert after["lastOpenFiles"] == [NEW_TODOS, "Start here.md"]


def test_provenance_baselines_move_to_the_new_names(tmp_path):
    root = vault_v12(tmp_path)
    provenance.record_event(root, "provision", at="2026-10-01T09:00:00Z")
    data = provenance.read(root)
    data["template_files"] = {OLD_TODOS: "a" * 64, OLD_IDEAS: "b" * 64, "Start here.md": "c" * 64}
    (root / provenance.PROVENANCE_RELPATH).write_text(json.dumps(data), encoding="utf-8")
    load().apply(root)
    assert provenance.read(root)["template_files"] == {
        NEW_TODOS: "a" * 64, NEW_IDEAS: "b" * 64, "Start here.md": "c" * 64}


def test_unreadable_provenance_is_reported_not_raised(tmp_path):
    root = vault_v12(tmp_path)
    (root / provenance.PROVENANCE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (root / provenance.PROVENANCE_RELPATH).write_text("{not json", encoding="utf-8")
    result = load().apply(root)
    assert result["provenance"].startswith("skipped")
    assert any("provenance.json" in line for line in result["needs_human"])


def test_apply_is_idempotent(tmp_path):
    root = vault_v12(tmp_path)
    module = load()
    module.apply(root)
    before = (root / OBS / "bookmarks.json").read_bytes()
    assert module.apply(root) == {
        "files": {OLD_TODOS: "absent", OLD_IDEAS: "absent"},
        "bookmarks": "unchanged", "workspace": "absent", "provenance": "unchanged"}
    assert (root / OBS / "bookmarks.json").read_bytes() == before


def test_a_vault_without_the_files_or_a_menu_is_fine(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    result = load().apply(root)
    assert result["bookmarks"] == "absent"
    load().verify(root)


def test_unreadable_bookmarks_stop_the_migration(tmp_path):
    root = vault_v12(tmp_path)
    (root / OBS / "bookmarks.json").write_text("{not json", encoding="utf-8")
    module = load()
    with pytest.raises(module.MigrationError):
        module.apply(root)


def test_verify_catches_a_file_not_renamed(tmp_path):
    root = vault_v12(tmp_path)
    module = load()
    with pytest.raises(module.MigrationError, match="not renamed"):
        module.verify(root)


def test_verify_catches_a_menu_still_on_an_old_name(tmp_path):
    root = vault_v12(tmp_path)
    for old, new in ((OLD_TODOS, NEW_TODOS), (OLD_IDEAS, NEW_IDEAS)):
        (root / old).rename(root / new)
    module = load()
    with pytest.raises(module.MigrationError, match="old name"):
        module.verify(root)


def test_run_through_the_framework_bumps_to_13(tmp_path):
    root = vault_v12(tmp_path)
    result = migrate.run(root, "2026-10-09", stamp="2026-10-09-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-13", "structure-version-14", "structure-version-15"]
    assert result["structure_version"] == 15
