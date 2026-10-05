"""Migration 006 (#240): Entities label, names in the file list, side-by-side
panes, and the renamed Meetings review view in existing daily notes.
Made-up vaults only."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from vaultlib import migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
M006 = REPO_ROOT / "plugin" / "migrations" / "006-structure-version-7" / "migrate.py"
NN = Path(".obsidian/plugins/notebook-navigator/data.json")
WS = Path(".obsidian/workspace.json")
OLD = "> ![[20-meetings/Meetings.base#Triage]]"
NEW = "> ![[20-meetings/Meetings.base#To review]]"


def load():
    spec = importlib.util.spec_from_file_location("m006", M006)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def daily(review_line: str, newline: str = "\n") -> str:
    lines = ["---", "date: 2026-10-01", "type: daily-note", "---", "",
             "# 2026-10-01 · Thursday", "", "> [!review] Waiting for you",
             review_line, ">", "> ![[30-projects/Decisions.base#To review]]", "",
             "## End of day", f"- I wrote {OLD} in my own words", ""]
    return newline.join(lines)


def vault_v6(tmp_path: Path) -> Path:
    """A structure-6 vault as #239 left it: stacked panes, the Organisations
    label, Navigator UI state and an owner's own shortcut."""
    root = tmp_path / "vault"
    (root / ".obsidian/plugins/notebook-navigator").mkdir(parents=True)
    (root / "60-daily-notes").mkdir()
    (root / "structure-version").write_text("6\n", encoding="utf-8")
    (root / NN).write_text(json.dumps({
        "vaultProfiles": [{"id": "default", "shortcuts": [
            {"type": "note", "path": "40-entities/Entities.base", "alias": "Organisations"},
            {"type": "note", "path": "80-thoughts-ideas/mine.md", "alias": "Mine"}]}],
        "vaultProfile": "default", "dualPane": True, "dualPaneOrientation": "vertical",
        "syncModes": {"dualPane": "synced", "dualPaneOrientation": "synced", "uiScale": "local"},
        "lastSelectedFolder": "30-projects"}), encoding="utf-8")
    (root / WS).write_text(json.dumps({"left": {"width": 290, "children": []},
                                       "lastOpenFiles": ["a.md"]}), encoding="utf-8")
    (root / "60-daily-notes/2026-10-01.md").write_text(daily(OLD), encoding="utf-8", newline="")
    (root / "60-daily-notes/2026-10-02.md").write_bytes(daily(OLD, "\r\n").encode("utf-8"))
    (root / "60-daily-notes/2026-10-03.md").write_text(daily(NEW), encoding="utf-8", newline="")
    return root


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 7 and module.LOSSY


def test_apply_lands_the_layout_and_keeps_the_owners_state(tmp_path):
    root = vault_v6(tmp_path)
    module = load()
    result = module.apply(root)
    assert result == {"navigator": "merged", "workspace": "merged", "daily_notes": 2}
    data = json.loads((root / NN).read_text(encoding="utf-8"))
    assert [s.get("alias") for s in data["vaultProfiles"][0]["shortcuts"]] == ["Entities", "Mine"]
    assert data["dualPaneOrientation"] == "horizontal"
    assert data["useFrontmatterMetadata"] is True
    assert data["frontmatterNameField"] == "project-name, entity-name, person-name"
    assert data["syncModes"] == {"dualPane": "synced", "dualPaneOrientation": "synced",
                                 "uiScale": "local"}
    assert data["lastSelectedFolder"] == "30-projects"
    ws = json.loads((root / WS).read_text(encoding="utf-8"))
    assert ws["left"]["width"] == 400 and ws["lastOpenFiles"] == ["a.md"]
    module.verify(root)


def test_only_the_embed_line_changes_in_a_daily_note(tmp_path):
    root = vault_v6(tmp_path)
    load().apply(root)
    lf = (root / "60-daily-notes/2026-10-01.md").read_text(encoding="utf-8")
    assert lf == daily(NEW).replace(f"- I wrote {NEW}", f"- I wrote {OLD}")
    assert f"- I wrote {OLD} in my own words" in lf
    # A CRLF note is rewritten too, and comes out LF like every vault write.
    crlf = (root / "60-daily-notes/2026-10-02.md").read_bytes().decode("utf-8")
    assert crlf == lf


def test_apply_is_idempotent(tmp_path):
    root = vault_v6(tmp_path)
    module = load()
    module.apply(root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert module.apply(root) == {"navigator": "unchanged", "workspace": "unchanged",
                                  "daily_notes": 0}
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_a_vault_without_the_files_skips(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    module = load()
    assert module.apply(root) == {"navigator": "skipped: no data.json",
                                  "workspace": "skipped: no workspace.json", "daily_notes": 0}
    assert module.verify(root) == {"checked": ["60-daily-notes"]}


def test_unreadable_navigator_settings_stop_the_migration(tmp_path):
    root = vault_v6(tmp_path)
    (root / NN).write_text("{not json", encoding="utf-8")
    module = load()
    with pytest.raises(module.MigrationError):
        module.apply(root)


def test_verify_catches_a_daily_note_still_on_triage(tmp_path):
    root = vault_v6(tmp_path)
    module = load()
    module.apply(root)
    (root / "60-daily-notes/2026-10-04.md").write_text(daily(OLD), encoding="utf-8")
    with pytest.raises(module.MigrationError, match="Triage"):
        module.verify(root)


def test_the_shipped_template_is_already_where_the_migration_lands(tmp_path):
    root = tmp_path / "fresh"
    shutil.copytree(TEMPLATE / ".obsidian", root / ".obsidian")
    shipped_nn = json.loads((root / NN).read_text(encoding="utf-8"))
    shipped_ws = json.loads((root / WS).read_text(encoding="utf-8"))
    load().apply(root)
    assert json.loads((root / NN).read_text(encoding="utf-8")) == shipped_nn
    assert json.loads((root / WS).read_text(encoding="utf-8")) == shipped_ws


def test_run_through_the_framework_bumps_to_8(tmp_path):
    root = vault_v6(tmp_path)
    (root / "99-workflow-config").mkdir()
    result = migrate.run(root, "2026-10-02", stamp="2026-10-02-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-7", "structure-version-8",
        "structure-version-9"]
    assert result["structure_version"] == 9
    assert (root / "structure-version").read_text(encoding="utf-8").strip() == "9"
