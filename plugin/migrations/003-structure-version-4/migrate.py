"""Structure-version 4: one sidebar menu, a quiet window (#239).

Brings an existing vault's Notebook Navigator settings and ribbon to what a
fresh vault ships:

- Shortcuts become the menu — Daily notes, Meetings, Projects, People,
  Organisations, Decisions — each with its own label (`alias`), no position
  numbers. The old shortcut to `Start here.md` is dropped. Any shortcut the
  owner added themselves is kept, after the menu.
- `claude` and `99-workflow-config` are hidden folders and `CLAUDE.md` a
  hidden file (Navigator's show-hidden toggle still reaches them); archive,
  private and heavy assets sort to the bottom of the folder tree.
- Recent files, Tags and Properties sections off; no update notice on start.
- One pane layout that never switches on its own: the navigation pane above
  the file list, marked `synced` so the vault's value wins over the per-device
  default Navigator otherwise keeps in local storage.
- The ribbon keeps today's daily note and the quick switcher; graph view,
  command palette and "Create new base" leave it (still reachable through the
  command palette shortcut, Ctrl/Cmd+P).

Merged key by key, never overwritten: Navigator writes its own UI state into
the same `data.json` constantly, and `workspace.json` is the owner's open
tabs and layout — replacing either file would throw that away. Only the keys
named in `NN_SETTINGS`, the profile's `shortcuts`, `hiddenFolders`,
`hiddenFileNames` and `rootFolderOrder`, and the ribbon's `hiddenItems` and
the left sidebar's width are written. A vault without the Navigator settings
or a workspace file skips that half (the template refresh restores a missing
`data.json`; Obsidian writes a fresh `workspace.json`).

`LOSSY` is set because the keys above are reset to the shipped values even
where the owner had changed them. Obsidian must be closed while this runs:
it rewrites `workspace.json` on quit and would undo the ribbon change.

`data.json` is a template-managed file. The template ships the same values
this migration writes, so a later template refresh converges on them rather
than reverting it — but because Navigator's own UI state differs from the
shipped bytes, `template status` will report the file as `locally-edited`, as
it already did before this migration.
"""
from __future__ import annotations

import json
from pathlib import Path

TARGET_VERSION = 4
LOSSY = (
    "resets the sidebar to the shipped menu: Notebook Navigator's shortcuts to "
    "the shipped tables (the Start here shortcut goes; shortcuts the owner "
    "added stay), the Recent files / Tags / Properties sections, the pane "
    "layout, shortcut numbers and the update check; hides claude, "
    "99-workflow-config and CLAUDE.md in the sidebar; and hides graph view, "
    "command palette and Create new base from the ribbon — even where the "
    "owner had changed them"
)

NN_RELPATH = Path(".obsidian") / "plugins" / "notebook-navigator" / "data.json"
WORKSPACE_RELPATH = Path(".obsidian") / "workspace.json"

MENU = [
    {"type": "folder", "path": "60-daily-notes", "alias": "Daily notes"},
    {"type": "note", "path": "20-meetings/Meetings.base", "alias": "Meetings"},
    {"type": "note", "path": "30-projects/Projects.base", "alias": "Projects"},
    {"type": "note", "path": "50-people/People.base", "alias": "People"},
    {"type": "note", "path": "40-entities/Entities.base", "alias": "Organisations"},
    {"type": "note", "path": "30-projects/Decisions.base", "alias": "Decisions"},
]
# Paths whose old, unlabelled shortcuts the menu replaces.
SHIPPED_SHORTCUT_PATHS = {s["path"] for s in MENU} | {"Start here.md"}
HIDDEN_FOLDERS = ["claude", "99-workflow-config"]
HIDDEN_FILE_NAMES = ["CLAUDE.md"]
ROOT_ORDER_TOP = ["10-inbox", "20-meetings", "30-projects", "40-entities",
                  "50-people", "60-daily-notes", "70-resources",
                  "80-thoughts-ideas"]
ROOT_ORDER_BOTTOM = ["90-archive", "95-private", "_heavy-assets"]
NN_SETTINGS = {
    "checkForUpdatesOnStart": False,
    "shortcutBadgeDisplay": "none",
    "showRecentNotes": False,
    "showTags": False,
    "showProperties": False,
    "dualPane": True,
    "dualPaneOrientation": "vertical",
    "narrowSidebarLayout": "none",
}
NN_SYNCED = ("dualPane", "dualPaneOrientation")
RIBBON_HIDDEN = {
    "switcher:Open quick switcher": False,
    "graph:Open graph view": True,
    "daily-notes:Open today's daily note": False,
    "command-palette:Open command palette": True,
    "bases:Create new base": True,
    "notebook-navigator:Notebook Navigator": True,
}
SIDEBAR_WIDTH = 290


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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _active_profile(data: dict) -> dict:
    profiles = data.get("vaultProfiles")
    if not isinstance(profiles, list) or not profiles:
        profiles = [{"id": "default", "name": "Default"}]
        data["vaultProfiles"] = profiles
        data["vaultProfile"] = "default"
    wanted = data.get("vaultProfile")
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("id") == wanted:
            return profile
    return profiles[0]


def _union(existing, extra):
    current = [x for x in existing if isinstance(x, str)] if isinstance(existing, list) else []
    return current + [x for x in extra if x not in current]


def _merge_nn(data: dict) -> dict:
    data.update(NN_SETTINGS)
    modes = data.get("syncModes")
    modes = dict(modes) if isinstance(modes, dict) else {}
    for key in NN_SYNCED:
        modes[key] = "synced"
    data["syncModes"] = modes

    profile = _active_profile(data)
    existing = profile.get("shortcuts") if isinstance(profile.get("shortcuts"), list) else []
    kept = [s for s in existing
            if isinstance(s, dict) and s.get("path") not in SHIPPED_SHORTCUT_PATHS]
    profile["shortcuts"] = [dict(s) for s in MENU] + kept
    profile["hiddenFolders"] = _union(profile.get("hiddenFolders"), HIDDEN_FOLDERS)
    profile["hiddenFileNames"] = _union(profile.get("hiddenFileNames"), HIDDEN_FILE_NAMES)

    order = data.get("rootFolderOrder")
    order = [x for x in order if isinstance(x, str)] if isinstance(order, list) else []
    own = [x for x in order if x not in ROOT_ORDER_TOP and x not in ROOT_ORDER_BOTTOM]
    data["rootFolderOrder"] = ROOT_ORDER_TOP + own + ROOT_ORDER_BOTTOM
    return data


def _merge_workspace(data: dict) -> dict:
    ribbon = data.get("left-ribbon")
    ribbon = dict(ribbon) if isinstance(ribbon, dict) else {}
    hidden = ribbon.get("hiddenItems")
    hidden = dict(hidden) if isinstance(hidden, dict) else {}
    hidden.update(RIBBON_HIDDEN)
    ribbon["hiddenItems"] = hidden
    data["left-ribbon"] = ribbon
    if isinstance(data.get("left"), dict):
        data["left"]["width"] = SIDEBAR_WIDTH
    return data


def apply(root: Path) -> dict:
    root = Path(root)
    result = {"navigator": "skipped: no data.json", "workspace": "skipped: no workspace.json"}
    nn = root / NN_RELPATH
    if nn.is_file():
        before = nn.read_text(encoding="utf-8")
        data = _merge_nn(_load(nn))
        _write(nn, data)
        result["navigator"] = "unchanged" if nn.read_text(encoding="utf-8") == before else "merged"
    ws = root / WORKSPACE_RELPATH
    if ws.is_file():
        before = ws.read_text(encoding="utf-8")
        data = _merge_workspace(_load(ws))
        _write(ws, data)
        result["workspace"] = "unchanged" if ws.read_text(encoding="utf-8") == before else "merged"
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
        profile = _active_profile(data)
        if profile.get("shortcuts", [])[:len(MENU)] != MENU:
            raise MigrationError(f"{NN_RELPATH.as_posix()}: the menu shortcuts did not land")
        for folder in HIDDEN_FOLDERS:
            if folder not in profile.get("hiddenFolders", []):
                raise MigrationError(f"{NN_RELPATH.as_posix()}: {folder} is not hidden")
        if data.get("rootFolderOrder", [])[-len(ROOT_ORDER_BOTTOM):] != ROOT_ORDER_BOTTOM:
            raise MigrationError(f"{NN_RELPATH.as_posix()}: archive folders are not last")
        checked.append(NN_RELPATH.as_posix())
    ws = root / WORKSPACE_RELPATH
    if ws.is_file():
        hidden = (_load(ws).get("left-ribbon") or {}).get("hiddenItems") or {}
        for key, value in RIBBON_HIDDEN.items():
            if hidden.get(key) is not value:
                raise MigrationError(f"{WORKSPACE_RELPATH.as_posix()}: ribbon {key!r} is not {value}")
        checked.append(WORKSPACE_RELPATH.as_posix())
    return {"checked": checked}
