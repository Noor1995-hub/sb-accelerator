"""Migration 003 (#239): the sidebar menu and a quiet ribbon, merged into an
existing vault's Notebook Navigator settings and workspace — never a file
replacement, because both files carry the owner's own state."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from vaultlib import migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
M003 = REPO_ROOT / "plugin" / "migrations" / "003-structure-version-4" / "migrate.py"
NN = Path(".obsidian/plugins/notebook-navigator/data.json")
WS = Path(".obsidian/workspace.json")


def load():
    spec = importlib.util.spec_from_file_location("m003", M003)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lived_in_vault(tmp_path: Path) -> Path:
    """A structure-version-3 vault whose Navigator has been used: the 0.12
    shortcuts, a shortcut the owner added, tags switched on, Navigator's own
    UI state and per-device sync modes, and a workspace with open tabs."""
    root = tmp_path / "vault"
    (root / ".obsidian/plugins/notebook-navigator").mkdir(parents=True)
    (root / "structure-version").write_text("3\n", encoding="utf-8")
    (root / NN).write_text(json.dumps({
        "vaultProfiles": [{
            "id": "default", "name": "Default",
            "hiddenFolders": ["old-stuff"], "hiddenFileNames": [],
            "shortcuts": [
                {"type": "note", "path": "Start here.md"},
                {"type": "note", "path": "20-meetings/Meetings.base"},
                {"type": "note", "path": "40-entities/Entities.base"},
                {"type": "folder", "path": "60-daily-notes"},
                {"type": "note", "path": "80-thoughts-ideas/board-prep.md"},
            ],
        }],
        "vaultProfile": "default",
        "showTags": True,
        "lastShownVersion": "3.3.4",
        "rootFolderOrder": ["my-clients", "10-inbox"],
        "syncModes": {"vaultProfile": "local", "dualPane": "local",
                      "dualPaneOrientation": "local", "uiScale": "local"},
    }), encoding="utf-8")
    (root / WS).write_text(json.dumps({
        "main": {"id": "m", "type": "split", "children": []},
        "left": {"id": "l", "type": "split", "children": [], "width": 400},
        "left-ribbon": {"hiddenItems": {"graph:Open graph view": False,
                                        "my-plugin:Something": True}},
        "active": "m",
        "lastOpenFiles": ["20-meetings/x.md"],
    }), encoding="utf-8")
    return root


def nn(root):
    return json.loads((root / NN).read_text(encoding="utf-8"))


def test_metadata():
    module = load()
    assert module.TARGET_VERSION == 4
    assert module.LOSSY and "Start here shortcut" in module.LOSSY


def test_merge_writes_the_menu_and_keeps_the_owners_state(tmp_path):
    module = load()
    root = lived_in_vault(tmp_path)
    result = module.apply(root)
    assert result == {"navigator": "merged", "workspace": "merged"}
    data = nn(root)
    shortcuts = data["vaultProfiles"][0]["shortcuts"]
    assert [s.get("alias") for s in shortcuts] == [
        "Daily notes", "Meetings", "Projects", "People", "Entities", "Decisions", None]
    # the owner's own shortcut survives, after the menu
    assert shortcuts[-1] == {"type": "note", "path": "80-thoughts-ideas/board-prep.md"}
    assert not any(s["path"] == "Start here.md" for s in shortcuts)
    profile = data["vaultProfiles"][0]
    assert profile["hiddenFolders"] == ["old-stuff", "claude", "99-workflow-config"]
    assert profile["hiddenFileNames"] == ["CLAUDE.md"]
    assert data["showTags"] is False and data["checkForUpdatesOnStart"] is False
    assert data["dualPaneOrientation"] == "vertical" and data["narrowSidebarLayout"] == "none"
    # the pane layout now reads from the vault; other per-device modes untouched
    assert data["syncModes"] == {"vaultProfile": "local", "dualPane": "synced",
                                 "dualPaneOrientation": "synced", "uiScale": "local"}
    # Navigator's own state is left alone
    assert data["lastShownVersion"] == "3.3.4"
    # the owner's own root folder keeps a place, above the archive block
    assert data["rootFolderOrder"][-4:] == ["my-clients", "90-archive", "95-private", "_heavy-assets"]

    ws = json.loads((root / WS).read_text(encoding="utf-8"))
    hidden = ws["left-ribbon"]["hiddenItems"]
    assert hidden["graph:Open graph view"] is True
    assert hidden["daily-notes:Open today's daily note"] is False
    assert hidden["my-plugin:Something"] is True     # the owner's own choice
    assert ws["left"]["width"] == 290
    assert ws["lastOpenFiles"] == ["20-meetings/x.md"] and ws["active"] == "m"
    assert module.verify(root)["checked"] == [NN.as_posix(), WS.as_posix()]


def test_running_twice_changes_nothing_the_second_time(tmp_path):
    module = load()
    root = lived_in_vault(tmp_path)
    module.apply(root)
    before = {p: (root / p).read_bytes() for p in (NN, WS)}
    assert module.apply(root) == {"navigator": "unchanged", "workspace": "unchanged"}
    assert {p: (root / p).read_bytes() for p in (NN, WS)} == before


def test_a_vault_without_the_files_skips_cleanly(tmp_path):
    module = load()
    root = tmp_path / "bare"
    root.mkdir()
    result = module.apply(root)
    assert result["navigator"].startswith("skipped") and result["workspace"].startswith("skipped")
    assert module.verify(root) == {"checked": []}


def test_broken_json_is_refused_without_writing(tmp_path):
    module = load()
    root = lived_in_vault(tmp_path)
    (root / NN).write_text("{not json", encoding="utf-8")
    with pytest.raises(module.MigrationError, match="not readable JSON"):
        module.apply(root)
    assert (root / NN).read_text(encoding="utf-8") == "{not json"


# Convergence with the shipped template is checked for the whole chain at once in test_migration_009 (#263): the template no longer ships Navigator's settings.
def test_run_through_the_framework_bumps_to_4(tmp_path):
    # 003 applies first; 004 (#238) and 005 (#249) then carry the chain on to 10
    root = lived_in_vault(tmp_path)
    (root / "99-workflow-config").mkdir()
    (root / "20-meetings").mkdir()
    result = migrate.run(root, "2026-10-01", stamp="2026-10-01-120000")
    assert [a["slug"] for a in result["applied"]][:1] == ["structure-version-4"]
    assert result["structure_version"] == 10
    assert (root / "structure-version").read_text(encoding="utf-8").strip() == "10"
