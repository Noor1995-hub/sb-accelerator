"""Migration 004 (#238): the vault opens on today's daily note — merged into
Notebook Navigator's settings, never a file replacement."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from vaultlib import migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
M004 = REPO_ROOT / "plugin" / "migrations" / "004-structure-version-5" / "migrate.py"
NN = Path(".obsidian/plugins/notebook-navigator/data.json")


def load():
    spec = importlib.util.spec_from_file_location("m004", M004)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vault_v4(tmp_path, nn_data=None):
    root = tmp_path / "vault"
    (root / NN.parent).mkdir(parents=True)
    for folder in ("99-workflow-config", "20-meetings"):
        (root / folder).mkdir()
    (root / "structure-version").write_text("4\n", encoding="utf-8")
    if nn_data is not None:
        (root / NN).write_text(json.dumps(nn_data), encoding="utf-8")
    return root


def test_metadata():
    module = load()
    assert module.TARGET_VERSION == 5
    assert module.LOSSY and "homepage" in module.LOSSY


def test_sets_the_daily_note_homepage_and_keeps_everything_else(tmp_path):
    module = load()
    root = vault_v4(tmp_path, {
        "homepage": {"source": "file", "file": "Dashboard.md", "createMissingPeriodicNote": True},
        "calendarIntegrationMode": "notebook-navigator",
        "showTags": False, "lastShownVersion": "3.3.4",
        "vaultProfiles": [{"id": "default", "shortcuts": [{"type": "note", "path": "x.md"}]}],
    })
    assert module.apply(root) == {"navigator": "merged"}
    data = json.loads((root / NN).read_text(encoding="utf-8"))
    assert data["homepage"] == {"source": "daily-note", "file": None,
                                "createMissingPeriodicNote": False}
    assert data["calendarIntegrationMode"] == "daily-notes"
    assert data["showTags"] is False and data["lastShownVersion"] == "3.3.4"
    assert data["vaultProfiles"][0]["shortcuts"] == [{"type": "note", "path": "x.md"}]
    assert module.verify(root) == {"checked": [NN.as_posix()]}
    assert module.apply(root) == {"navigator": "unchanged"}


def test_no_navigator_settings_skips(tmp_path):
    module = load()
    root = vault_v4(tmp_path)
    assert module.apply(root)["navigator"].startswith("skipped")
    assert module.verify(root) == {"checked": []}


def test_broken_json_is_refused_without_writing(tmp_path):
    module = load()
    root = vault_v4(tmp_path)
    (root / NN).write_text("{nope", encoding="utf-8")
    with pytest.raises(module.MigrationError, match="not readable JSON"):
        module.apply(root)
    assert (root / NN).read_text(encoding="utf-8") == "{nope"


def test_the_shipped_template_is_already_where_the_migration_lands(tmp_path):
    module = load()
    root = tmp_path / "fresh"
    shutil.copytree(TEMPLATE / ".obsidian", root / ".obsidian")
    shipped = json.loads((root / NN).read_text(encoding="utf-8"))
    module.apply(root)
    assert json.loads((root / NN).read_text(encoding="utf-8")) == shipped


def test_run_through_the_framework_bumps_to_5(tmp_path):
    root = vault_v4(tmp_path, {"vaultProfiles": [{"id": "default"}]})
    result = migrate.run(root, "2026-10-01", stamp="2026-10-01-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-5", "structure-version-6",
                                                        "structure-version-7", "structure-version-8"]
    assert (root / "structure-version").read_text(encoding="utf-8").strip() == "8"
