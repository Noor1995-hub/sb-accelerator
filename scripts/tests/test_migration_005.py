"""Migration 005: the hidden _messages/ folder. Made-up vaults only."""
import importlib.util, json
from pathlib import Path
import pytest
from vaultlib import migrate
from test_vaultlib_vault import make_vault
from test_migration_003 import lived_in_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
M005 = REPO_ROOT / "plugin" / "migrations" / "005-structure-version-6" / "migrate.py"
NAV = ".obsidian/plugins/notebook-navigator/data.json"
APP = ".obsidian/app.json"


def load():
    spec = importlib.util.spec_from_file_location("m005", M005)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def obsidian(root, nav_hidden, app_extra):
    nav = root / NAV
    nav.parent.mkdir(parents=True, exist_ok=True)
    nav.write_text(json.dumps({"vaultProfiles": [{"hiddenFolders": nav_hidden}]}), encoding="utf-8")
    (root / ".obsidian").mkdir(exist_ok=True)
    (root / APP).write_text(json.dumps({"alwaysUpdateLinks": True, **app_extra}), encoding="utf-8")


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 6 and module.LOSSY is None


def test_apply_merges_into_what_the_owner_already_hid_and_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    obsidian(root, ["95-private"], {"userIgnoreFilters": ["70-resources/old/"]})
    module = load()
    first = module.apply(root)
    second = module.apply(root)
    nav = json.loads((root / NAV).read_text(encoding="utf-8"))
    app = json.loads((root / APP).read_text(encoding="utf-8"))
    assert nav["vaultProfiles"][0]["hiddenFolders"] == ["95-private", "_messages"]
    assert app["userIgnoreFilters"] == ["70-resources/old/", "_messages/"]
    assert app["alwaysUpdateLinks"] is True
    assert (root / "_messages").is_dir()
    assert first == {"created": True, "nav": True, "app": True}
    assert second == {"created": False, "nav": False, "app": False}
    assert module.verify(root) == {"checked": 3}


def test_apply_creates_the_filter_list_when_app_json_has_none(tmp_path):
    root = make_vault(tmp_path)
    obsidian(root, [], {})
    module = load()
    module.apply(root)
    app = json.loads((root / APP).read_text(encoding="utf-8"))
    assert app["userIgnoreFilters"] == ["_messages/"]


def test_missing_files_and_empty_profiles_are_skipped(tmp_path):
    root = make_vault(tmp_path)
    (root / NAV).parent.mkdir(parents=True, exist_ok=True)
    (root / NAV).write_text(json.dumps({"vaultProfiles": []}), encoding="utf-8")
    (root / APP).unlink(missing_ok=True)
    module = load()
    assert module.apply(root) == {"created": True, "nav": False, "app": False}
    assert json.loads((root / NAV).read_text(encoding="utf-8")) == {"vaultProfiles": []}
    assert not (root / APP).exists()
    assert module.verify(root) == {"checked": 3}


def test_verify_fails_when_the_folder_is_missing(tmp_path):
    root = make_vault(tmp_path)
    obsidian(root, [], {})
    with pytest.raises(RuntimeError):
        load().verify(root)


def test_verify_fails_when_a_hide_entry_is_missing_and_modifies_nothing(tmp_path):
    root = make_vault(tmp_path)
    obsidian(root, [], {})
    (root / "_messages").mkdir()
    before = {p: (root / p).read_bytes() for p in (NAV, APP)}
    with pytest.raises(RuntimeError):
        load().verify(root)
    assert {p: (root / p).read_bytes() for p in (NAV, APP)} == before


def test_discover_chains_through_005():
    found = migrate.discover()
    assert [m["module"].TARGET_VERSION for m in found][:5] == [2, 3, 4, 5, 6]


def test_run_from_structure_3_keeps_003s_hidden_folders_and_adds_messages(tmp_path):
    """003 rewrites hiddenFolders and 004 rewrites data.json again; 005 runs
    last and must leave both the menu's hidden folders and _messages."""
    root = lived_in_vault(tmp_path)   # structure-version 3, hiddenFolders ["old-stuff"]
    (root / "99-workflow-config").mkdir()
    (root / "20-meetings").mkdir()
    (root / APP).write_text(json.dumps({"alwaysUpdateLinks": True}), encoding="utf-8")
    result = migrate.run(root, "2026-10-01", stamp="2026-10-01-120000")
    assert [a["slug"] for a in result["applied"]] == [
        "structure-version-4", "structure-version-5", "structure-version-6",
        "structure-version-7", "structure-version-8",
        "structure-version-9", "structure-version-10", "structure-version-11"]
    assert result["structure_version"] == 11
    nav = json.loads((root / NAV).read_text(encoding="utf-8"))
    hidden = nav["vaultProfiles"][0]["hiddenFolders"]
    assert hidden == ["old-stuff", "claude", "99-workflow-config", "_messages"]
    assert nav["homepage"]["source"] == "daily-note"
    app = json.loads((root / APP).read_text(encoding="utf-8"))
    assert app["userIgnoreFilters"] == ["_messages/"]
    assert (root / "_messages").is_dir()
