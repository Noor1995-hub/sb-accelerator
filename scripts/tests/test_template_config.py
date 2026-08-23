"""Guards for shipped .obsidian configuration in the template.

The Notebook Navigator settings file references template paths (shortcuts)
— these tests keep it honest when folders or .base files get renamed."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template"
NN_DATA = TEMPLATE / ".obsidian" / "plugins" / "notebook-navigator" / "data.json"

EXPECTED_SHORTCUTS = [
    ("note", "20-meetings/Meetings.base"),
    ("note", "30-projects/Projects.base"),
    ("note", "40-entities/Entities.base"),
    ("note", "50-people/People.base"),
    ("note", "30-projects/Decisions.base"),
    ("folder", "60-daily-notes"),
]


def load_profile() -> dict:
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    profiles = data["vaultProfiles"]
    assert len(profiles) == 1, "template ships exactly one NN profile"
    return profiles[0]


def test_nn_data_json_parses_and_profile_selected():
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    assert data["vaultProfile"] == data["vaultProfiles"][0]["id"]


def test_nn_shortcuts_exact_order_and_paths_exist():
    profile = load_profile()
    got = [(s["type"], s["path"]) for s in profile["shortcuts"]]
    assert got == EXPECTED_SHORTCUTS, f"shortcut list drifted: {got}"
    for kind, path in got:
        target = TEMPLATE / path
        if kind == "folder":
            assert target.is_dir(), f"shortcut folder missing in template: {path}"
        else:
            assert target.is_file(), f"shortcut file missing in template: {path}"


def test_nn_file_visibility_is_all():
    """.base files show even under "documents"; "all" is a deliberate choice so attachments and generated deliverables are browsable too."""
    assert load_profile()["fileVisibility"] == "all"


def test_nn_folder_appearances_claude_skills_path_exists():
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    assert "claude/skills" in data["folderAppearances"]
    assert (TEMPLATE / "claude" / "skills").is_dir()


def test_nn_rainbow_enabled_for_folders_shortcuts_recents():
    rainbow = load_profile()["navRainbow"]
    for section in ("folders", "shortcuts", "recent"):
        assert rainbow[section]["enabled"] is True, f"navRainbow.{section} must be enabled"
