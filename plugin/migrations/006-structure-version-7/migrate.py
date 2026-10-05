"""Structure-version 7: names over codes in the sidebar (#240).

Brings an existing vault's Notebook Navigator, sidebar width and daily notes
to what a fresh vault ships:

- The Entities shortcut is labelled **Entities** again (#239 shipped it as
  "Organisations"; the owner kept the word Entities).
- The file list shows a note's name from its frontmatter — `project-name`,
  `entity-name` or `person-name` — instead of the file name, so project
  pages stop reading "index" and entity pages "dossier".
- The two panes sit side by side (navigation left, file list right) and the
  left sidebar is 400px wide to hold them. Marked `synced`, as in 003, so the
  vault's value wins over Navigator's per-device default.
- The Meetings review view is now named **To review**, like the Decisions
  one. Each daily note's *Waiting for you* block embeds it by name, so the
  old `Meetings.base#Triage` embed line is rewritten in place — that exact
  line only; nothing else in the note is touched.

The Bases, the CSS snippet (which hides the repeated title on pages that
open with their own heading) and Start here arrive with the template
refresh; they need no migration.

Navigator's `data.json` and `workspace.json` are merged key by key, never
replaced, for the reasons 003 gives. A vault without either file skips that
half. `LOSSY` is set because the pane layout, the sidebar width and the name
fields are reset to the shipped values even where the owner had changed
them. Obsidian must be closed while this runs: it rewrites `workspace.json`
on quit and would undo the width.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 7
LOSSY = (
    "resets the sidebar layout: Notebook Navigator's panes go side by side "
    "with the left sidebar 400px wide, its file list shows names from the "
    "notes' frontmatter, and the Entities shortcut is labelled Entities — "
    "even where the owner had changed them"
)

NN_RELPATH = Path(".obsidian") / "plugins" / "notebook-navigator" / "data.json"
WORKSPACE_RELPATH = Path(".obsidian") / "workspace.json"
ENTITIES_SHORTCUT = "40-entities/Entities.base"
ENTITIES_ALIAS = "Entities"
NN_SETTINGS = {
    "dualPane": True,
    "dualPaneOrientation": "horizontal",
    "useFrontmatterMetadata": True,
    "frontmatterNameField": "project-name, entity-name, person-name",
}
NN_SYNCED = ("dualPane", "dualPaneOrientation")
SIDEBAR_WIDTH = 400
OLD_EMBED = "> ![[20-meetings/Meetings.base#Triage]]"
NEW_EMBED = "> ![[20-meetings/Meetings.base#To review]]"


class MigrationError(Exception):
    """A file this migration must merge into does not parse."""


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{path.as_posix()} is not readable JSON ({exc}) — fix or delete "
            "it (the template refresh restores the Navigator settings; "
            "Obsidian rewrites workspace.json) and re-run") from exc
    if not isinstance(data, dict):
        raise MigrationError(f"{path.as_posix()} is not a JSON object")
    return data


def _write(path: Path, data: dict) -> None:
    vault.atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _profiles(data: dict) -> list:
    profiles = data.get("vaultProfiles")
    return [p for p in profiles if isinstance(p, dict)] if isinstance(profiles, list) else []


def _merge_nn(data: dict) -> dict:
    data.update(NN_SETTINGS)
    modes = data.get("syncModes")
    modes = dict(modes) if isinstance(modes, dict) else {}
    for key in NN_SYNCED:
        modes[key] = "synced"
    data["syncModes"] = modes
    for profile in _profiles(data):
        for shortcut in profile.get("shortcuts") or []:
            if isinstance(shortcut, dict) and shortcut.get("path") == ENTITIES_SHORTCUT:
                shortcut["alias"] = ENTITIES_ALIAS
    return data


def _daily_notes(root: Path) -> list:
    folder = root / vault.DAILY_NOTES_DIR
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def _rewrite_embed(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not any(line.rstrip("\r") == OLD_EMBED for line in lines):
        return False
    # read_text has already turned CRLF into LF; atomic_write keeps it LF.
    out = [NEW_EMBED if line.rstrip("\r") == OLD_EMBED else line for line in lines]
    vault.atomic_write(path, "\n".join(out))
    return True


def apply(root: Path) -> dict:
    root = Path(root)
    result = {"navigator": "skipped: no data.json",
              "workspace": "skipped: no workspace.json", "daily_notes": 0}
    nn = root / NN_RELPATH
    if nn.is_file():
        before = nn.read_text(encoding="utf-8")
        _write(nn, _merge_nn(_load(nn)))
        result["navigator"] = "unchanged" if nn.read_text(encoding="utf-8") == before else "merged"
    ws = root / WORKSPACE_RELPATH
    if ws.is_file():
        data = _load(ws)
        if isinstance(data.get("left"), dict) and data["left"].get("width") != SIDEBAR_WIDTH:
            data["left"]["width"] = SIDEBAR_WIDTH
            _write(ws, data)
            result["workspace"] = "merged"
        else:
            result["workspace"] = "unchanged"
    result["daily_notes"] = sum(_rewrite_embed(p) for p in _daily_notes(root))
    return result


def verify(root: Path) -> dict:
    root = Path(root)
    checked = []
    nn = root / NN_RELPATH
    if nn.is_file():
        data = _load(nn)
        for key, value in NN_SETTINGS.items():
            if data.get(key) != value:
                raise MigrationError(f"{NN_RELPATH.as_posix()}: {key} is {data.get(key)!r}, expected {value!r}")
        for key in NN_SYNCED:
            if (data.get("syncModes") or {}).get(key) != "synced":
                raise MigrationError(f"{NN_RELPATH.as_posix()}: syncModes.{key} is not 'synced'")
        for profile in _profiles(data):
            for shortcut in profile.get("shortcuts") or []:
                if (isinstance(shortcut, dict) and shortcut.get("path") == ENTITIES_SHORTCUT
                        and shortcut.get("alias") != ENTITIES_ALIAS):
                    raise MigrationError(f"{NN_RELPATH.as_posix()}: the Entities shortcut "
                                         f"is labelled {shortcut.get('alias')!r}")
        checked.append(NN_RELPATH.as_posix())
    ws = root / WORKSPACE_RELPATH
    if ws.is_file():
        left = _load(ws).get("left")
        if isinstance(left, dict) and left.get("width") != SIDEBAR_WIDTH:
            raise MigrationError(f"{WORKSPACE_RELPATH.as_posix()}: left sidebar is "
                                 f"{left.get('width')!r}px, expected {SIDEBAR_WIDTH}")
        checked.append(WORKSPACE_RELPATH.as_posix())
    for path in _daily_notes(root):
        if OLD_EMBED in (line.rstrip("\r") for line in path.read_text(encoding="utf-8").split("\n")):
            raise MigrationError(f"{path.relative_to(root).as_posix()}: still embeds the Triage view")
    checked.append(vault.DAILY_NOTES_DIR)
    return {"checked": checked}
