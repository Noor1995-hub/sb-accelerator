"""Structure-version 12: the To Do's table joins the menu (#257).

Every to do the owner writes in a daily note now becomes a note in
`65-to-dos/`, followed up in `To Do's.base`. In an existing vault this
migration adds the **To Do's** entry to `.obsidian/bookmarks.json`, directly
under Thoughts & ideas — or under Daily notes, or first, when the owner moved
or removed those. Every other entry stays exactly where it is, which is why
this is not lossy where 009 and 010 were.

A vault whose template refresh laid down the new menu before 009 or 010 ran
has the shipped To Do's entry pushed to the end by them (they keep entries
they do not know after the menu), so an entry identical to the shipped one
at the top level is moved back under its anchor. One the owner renamed or
put in a group of their own is theirs and stays.

It also tells Obsidian which properties are checkboxes and dates, in
`.obsidian/types.json`: Include, Done, Keep (`reviewed`) and Dismiss
(`archived`) are ticks, `due` and `absorbed` dates. Without it Obsidian
guesses each type from the values it has seen, so in a vault where no note
was ticked yet, Include on a new note came up as a text field. Only types the
vault does not have yet are added; one the owner set stays theirs.

`To Do's.base`, the menu colour and the wording in Start here, How it works,
CLAUDE.md and the ontology arrive with the template refresh, like every
other managed file. No note is touched; the folder appears with the first
action.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 12
LOSSY = None

BOOKMARKS = Path(".obsidian") / "bookmarks.json"
TYPES_FILE = Path(".obsidian") / "types.json"
# Kept equal to the template's types.json (a test pins it).
# `projects` is a list: a project typed into a new note in Thoughts and
# ideas would otherwise be stored as text, and the table's grouping formula
# maps over it as a list (review 2026-10-12).
TYPES = {"absorbed": "date", "archived": "checkbox", "done": "checkbox",
         "due": "date", "include": "checkbox", "projects": "multitext",
         "reviewed": "checkbox"}
CTIME = 1759000000000
VIEWS = "99-workflow-config/views"
ACTIONS = ("To Do's", "65-to-dos/To Do's.base")
ACTIONS_ENTRY = {"type": "file", "ctime": CTIME + 9, "path": ACTIONS[1], "title": ACTIONS[0]}
# Where To Do's goes, in order of preference: under the first of these found.
ANCHORS = ("80-thoughts-ideas/Thoughts & ideas.base", "60-daily-notes/Daily notes.base",
           "Start here.md")
MENU = [
    ("Start here", "Start here.md"),
    ("Daily notes", "60-daily-notes/Daily notes.base"),
    ("Thoughts & ideas", "80-thoughts-ideas/Thoughts & ideas.base"),
    ACTIONS,
    ("Meetings", "20-meetings/Meetings.base"),
    ("Projects", "30-projects/Projects.base"),
    ("People", "50-people/People.base"),
    ("Entities", "40-entities/Entities.base"),
    ("Decisions", "30-projects/Decisions.base"),
    ("Input", f"{VIEWS}/Input.base"),
]
LIBRARY_TITLE = "Library"
LIBRARY = [
    ("Recent", f"{VIEWS}/Recent.base"),
    ("Resources", f"{VIEWS}/Resources.base"),
    ("Heavy assets", f"{VIEWS}/Heavy assets.base"),
    ("Private", f"{VIEWS}/Private.base"),
    ("Archive", f"{VIEWS}/Archive.base"),
]


class MigrationError(Exception):
    """bookmarks.json exists but does not parse."""


def shipped_menu() -> list:
    """The menu exactly as the template's bookmarks.json carries it."""
    items = []
    for i, (title, path) in enumerate(m for m in MENU if m != ACTIONS):
        items.append({"type": "file", "ctime": CTIME + i, "path": path, "title": title})
    items.insert(3, dict(ACTIONS_ENTRY))
    items.append({"type": "group", "ctime": CTIME + 50, "title": LIBRARY_TITLE,
                  "items": [{"type": "file", "ctime": CTIME + 60 + i, "path": p, "title": t}
                            for i, (t, p) in enumerate(LIBRARY)]})
    return items


def _has_actions(items) -> bool:
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("path") == ACTIONS[1]:
            return True
        if item.get("type") == "group" and _has_actions(item.get("items") or []):
            return True
    return False


def _with_actions(data) -> dict:
    out = dict(data) if isinstance(data, dict) else {}
    items = out.get("items") if isinstance(out.get("items"), list) else []
    if ACTIONS_ENTRY in items:
        items = [i for i in items if i != ACTIONS_ENTRY]
    elif _has_actions(items):
        return out
    paths = [i.get("path") if isinstance(i, dict) else None for i in items]
    at = 0
    for anchor in ANCHORS:
        if anchor in paths:
            at = paths.index(anchor) + 1
            break
    out["items"] = items[:at] + [dict(ACTIONS_ENTRY)] + items[at:]
    return out


def _load_bookmarks(root: Path):
    path = root / BOOKMARKS
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{BOOKMARKS.as_posix()} is not readable JSON ({exc}) — fix or delete it "
            "(the template refresh writes a fresh one) and re-run") from exc


def _load_types(root: Path) -> dict:
    path = root / TYPES_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{TYPES_FILE.as_posix()} is not readable JSON ({exc}) — fix or delete it "
            "(Obsidian rebuilds it) and re-run") from exc
    return data if isinstance(data, dict) else {}


def _apply_types(root: Path) -> str:
    data = _load_types(root)
    types = data.get("types") if isinstance(data.get("types"), dict) else {}
    missing = {k: v for k, v in TYPES.items() if k not in types}
    if not missing:
        return "unchanged"
    data["types"] = {**types, **missing}
    vault.atomic_write(root / TYPES_FILE, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return "added " + ", ".join(sorted(missing))


def apply(root: Path) -> dict:
    root = Path(root)
    data = _load_bookmarks(root)
    before = (data or {}).get("items") or []
    after = _with_actions(data)
    if after.get("items") == before:
        result = {"bookmarks": "unchanged"}
    else:
        vault.atomic_write(root / BOOKMARKS, json.dumps(after, indent=2, ensure_ascii=False) + "\n")
        result = {"bookmarks": "moved" if _has_actions(before) else "added"}
    result["types"] = _apply_types(root)
    return result


def verify(root: Path) -> dict:
    root = Path(root)
    items = (_load_bookmarks(root) or {}).get("items") or []
    if not _has_actions(items):
        raise MigrationError(f"{BOOKMARKS.as_posix()}: the To Do's entry did not land")
    types = _load_types(root).get("types") or {}
    if any(k not in types for k in TYPES):
        raise MigrationError(f"{TYPES_FILE.as_posix()}: the property types did not land")
    return {"checked": ["bookmarks", "types"]}
