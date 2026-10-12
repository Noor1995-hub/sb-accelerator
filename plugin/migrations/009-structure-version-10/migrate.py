"""Structure-version 10: the sidebar is one menu, every entry a table (#263).

Obsidian's own Bookmarks list replaces Notebook Navigator as the sidebar. In
an existing vault this migration:

- switches Notebook Navigator off (`community-plugins.json`; its files stay on
  disk, untouched, so switching it back on in Settings restores it as it was);
- writes the menu into `.obsidian/bookmarks.json` — Start here, Daily notes,
  Inbox, Meetings, Projects, People, Entities, Decisions, Thoughts & ideas,
  and a Library group (Resources, Heavy assets, Archive, Private, Recent). A
  bookmark the owner made themselves is kept, after the menu;
- sets the Daily notes folder and format (`daily-notes.json`), with
  `autorun` off: opening today's note on startup created it, empty, on a
  morning after a missed run, and a line typed into it hid the missed day
  from the catch-up (review 2026-10-12, owner's call);
- files new notes in `80-thoughts-ideas` (`app.json`);
- makes the Bookmarks tab the open one in the left sidebar, drops the
  Navigator tab and narrows the sidebar to 280px (`workspace.json`).

The tables the menu opens (`Daily notes.base`, `Thoughts & ideas.base` and the
six under `99-workflow-config/views/`), the menu's colours (CSS snippet) and
the Entities table without group headings arrive with the template refresh:
they are template-managed files, offered as `missing` / `refresh` by
`/upgrade-vault`, exactly like the other tables.

Every file is merged key by key, never replaced: they hold the owner's own
settings and Obsidian's UI state. A file that is missing is created only for
`bookmarks.json` and `daily-notes.json`; `workspace.json` is skipped when
absent (Obsidian writes a fresh one). `LOSSY` is set because Navigator is
switched off and the startup note, new-note folder and sidebar tab are reset
even where the owner had chosen otherwise. Obsidian must be closed while
this runs: it rewrites `workspace.json` on quit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 10
LOSSY = (
    "switches Notebook Navigator off and makes Obsidian's Bookmarks list the "
    "sidebar menu; Obsidian opens today's daily note on startup and files new "
    "notes in 80-thoughts-ideas — even where the owner had chosen otherwise "
    "(their own bookmarks are kept, after the menu)"
)

OBS = Path(".obsidian")
PLUGINS = OBS / "community-plugins.json"
BOOKMARKS = OBS / "bookmarks.json"
DAILY = OBS / "daily-notes.json"
APP = OBS / "app.json"
WORKSPACE = OBS / "workspace.json"
NAVIGATOR = "notebook-navigator"
CTIME = 1759000000000
VIEWS = "99-workflow-config/views"
MENU = [
    ("Start here", "Start here.md"),
    ("Daily notes", "60-daily-notes/Daily notes.base"),
    ("Inbox", f"{VIEWS}/Inbox.base"),
    ("Meetings", "20-meetings/Meetings.base"),
    ("Projects", "30-projects/Projects.base"),
    ("People", "50-people/People.base"),
    ("Entities", "40-entities/Entities.base"),
    ("Decisions", "30-projects/Decisions.base"),
    ("Thoughts & ideas", "80-thoughts-ideas/Thoughts & ideas.base"),
]
LIBRARY_TITLE = "Library"
LIBRARY = [
    ("Resources", f"{VIEWS}/Resources.base"),
    ("Heavy assets", f"{VIEWS}/Heavy assets.base"),
    ("Archive", f"{VIEWS}/Archive.base"),
    ("Private", f"{VIEWS}/Private.base"),
    ("Recent", f"{VIEWS}/Recent.base"),
]
DAILY_SETTINGS = {"folder": "60-daily-notes", "format": "YYYY-MM-DD", "autorun": False}
APP_SETTINGS = {"newFileLocation": "folder", "newFileFolderPath": "80-thoughts-ideas"}
SIDEBAR_WIDTH = 280


class MigrationError(Exception):
    """A settings file this migration must merge into does not parse."""


def _load(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{path.as_posix()} is not readable JSON ({exc}) — fix or delete it "
            "(Obsidian or the template refresh writes a fresh one) and re-run") from exc


def _write(path: Path, data) -> bool:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    vault.atomic_write(path, text)
    return True


def shipped_menu() -> list:
    """The menu exactly as the template's bookmarks.json carries it."""
    items = [{"type": "file", "ctime": CTIME + i, "path": p, "title": t}
             for i, (t, p) in enumerate(MENU)]
    items.append({"type": "group", "ctime": CTIME + 50, "title": LIBRARY_TITLE,
                  "items": [{"type": "file", "ctime": CTIME + 60 + i, "path": p, "title": t}
                            for i, (t, p) in enumerate(LIBRARY)]})
    return items


def _shipped_paths() -> set:
    return {p for _, p in MENU} | {p for _, p in LIBRARY}


def _merge_bookmarks(data) -> dict:
    existing = data.get("items") if isinstance(data, dict) else None
    existing = existing if isinstance(existing, list) else []
    shipped = _shipped_paths()
    kept = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "group" and item.get("title") == LIBRARY_TITLE:
            # The owner's own entries in a group called Library survive inside
            # the shipped one.
            extra = [x for x in item.get("items") or []
                     if isinstance(x, dict) and x.get("path") not in shipped]
            if extra:
                kept.append({**item, "title": "My library", "items": extra})
            continue
        if item.get("path") in shipped:
            continue
        kept.append(item)
    out = dict(data) if isinstance(data, dict) else {}
    out["items"] = shipped_menu() + kept
    return out


def _merge_workspace(data: dict) -> dict:
    left = data.get("left")
    if not isinstance(left, dict):
        return data
    groups = [c for c in left.get("children") or [] if isinstance(c, dict) and c.get("type") == "tabs"]
    if groups:
        tabs = groups[0]
        leaves = [c for c in tabs.get("children") or [] if isinstance(c, dict)]
        leaves = [c for c in leaves if (c.get("state") or {}).get("type") != NAVIGATOR]
        bookmarks = [c for c in leaves if (c.get("state") or {}).get("type") == "bookmarks"]
        rest = [c for c in leaves if c not in bookmarks]
        if not bookmarks:
            bookmarks = [{"id": "sbmenu0bookmarks", "type": "leaf",
                          "state": {"type": "bookmarks", "state": {"showSearch": False, "searchQuery": ""},
                                    "icon": "lucide-bookmark", "title": "Bookmarks"}}]
        tabs["children"] = bookmarks[:1] + rest
        tabs["currentTab"] = 0
    left["width"] = SIDEBAR_WIDTH
    return data


def apply(root: Path) -> dict:
    root = Path(root)
    result = {}

    plugins = _load(root / PLUGINS, None)
    if isinstance(plugins, list):
        result["navigator"] = "switched off" if _write(
            root / PLUGINS, [p for p in plugins if p != NAVIGATOR]) else "already off"
    else:
        result["navigator"] = "skipped: no community-plugins.json"

    result["bookmarks"] = "merged" if _write(
        root / BOOKMARKS, _merge_bookmarks(_load(root / BOOKMARKS, {}))) else "unchanged"

    daily = _load(root / DAILY, {})
    daily = dict(daily) if isinstance(daily, dict) else {}
    daily.update(DAILY_SETTINGS)
    result["daily_notes"] = "merged" if _write(root / DAILY, daily) else "unchanged"

    app = _load(root / APP, None)
    if isinstance(app, dict):
        app.update(APP_SETTINGS)
        result["app"] = "merged" if _write(root / APP, app) else "unchanged"
    else:
        result["app"] = "skipped: no app.json"

    ws = _load(root / WORKSPACE, None)
    if isinstance(ws, dict):
        result["workspace"] = "merged" if _write(root / WORKSPACE, _merge_workspace(ws)) else "unchanged"
    else:
        result["workspace"] = "skipped: no workspace.json"
    return result


def verify(root: Path) -> dict:
    root = Path(root)
    plugins = _load(root / PLUGINS, None)
    if isinstance(plugins, list) and NAVIGATOR in plugins:
        raise MigrationError(f"{PLUGINS.as_posix()}: Notebook Navigator is still enabled")
    items = (_load(root / BOOKMARKS, {}) or {}).get("items") or []
    if items[:len(shipped_menu())] != shipped_menu():
        raise MigrationError(f"{BOOKMARKS.as_posix()}: the menu did not land")
    daily = _load(root / DAILY, {})
    if any(daily.get(k) != v for k, v in DAILY_SETTINGS.items()):
        raise MigrationError(f"{DAILY.as_posix()}: daily-note settings did not land")
    app = _load(root / APP, None)
    if isinstance(app, dict) and any(app.get(k) != v for k, v in APP_SETTINGS.items()):
        raise MigrationError(f"{APP.as_posix()}: new notes do not go to 80-thoughts-ideas")
    return {"checked": ["navigator", "bookmarks", "daily_notes", "app"]}
