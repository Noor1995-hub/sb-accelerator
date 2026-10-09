"""Structure-version 13: two tables get filenames a plugin upload accepts.

Cowork refuses a plugin zip that carries a path with an apostrophe or an
ampersand ("Zip file contains path with invalid characters"), and the
template shipped two: `65-to-dos/To Do's.base` and
`80-thoughts-ideas/Thoughts & ideas.base`. They are now `To Dos.base` and
`Thoughts and ideas.base`. The menu still says "To Do's" and "Thoughts &
ideas" — those are bookmark titles, not filenames, and the menu colours key
on the titles.

In an existing vault this migration:

- renames the vault's own copy of each file, so a column the owner resized
  or a sort they changed comes along. When the new name is already there
  (a template refresh laid it down first), both are kept and the old one is
  reported — it may hold the owner's changes;
- points every menu entry at the new name, wherever the owner put it, and
  keeps its title and its place. When that leaves two entries with the same
  name and title, the later one is a duplicate and is dropped;
- points open tabs and recent files in `.obsidian/workspace.json` at the new
  name, so Obsidian does not reopen a table that is gone;
- moves the files' template baselines in `provenance.json` to the new names,
  so the next template status sees the same file rather than one `missing`
  and one unknown.

No note is touched. Not lossy: nothing the owner made is removed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import provenance, vault  # noqa: E402

TARGET_VERSION = 13
LOSSY = None

BOOKMARKS = Path(".obsidian") / "bookmarks.json"
WORKSPACE = Path(".obsidian") / "workspace.json"
RENAMES = {
    "65-to-dos/To Do's.base": "65-to-dos/To Dos.base",
    "80-thoughts-ideas/Thoughts & ideas.base": "80-thoughts-ideas/Thoughts and ideas.base",
}


class MigrationError(Exception):
    """A settings file does not parse, or a rename did not land."""


def _load(root: Path, rel: Path, what: str):
    path = root / rel
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{rel.as_posix()} is not readable JSON ({exc}) — fix or delete it "
            f"({what} writes a fresh one) and re-run") from exc


def _dump(root: Path, rel: Path, data) -> None:
    vault.atomic_write(root / rel, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _paths(items) -> set:
    found = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("path"), str):
            found.add(item["path"])
        if isinstance(item.get("items"), list):
            found |= _paths(item["items"])
    return found


def _renamed_items(items) -> list:
    out = []
    for item in items:
        if isinstance(item, dict) and item.get("path") in RENAMES:
            item = dict(item, path=RENAMES[item["path"]])
        elif isinstance(item, dict) and isinstance(item.get("items"), list):
            item = dict(item, items=_renamed_items(item["items"]))
        out.append(item)
    return out


def _deduped(items, seen: set) -> list:
    out = []
    for item in items:
        if isinstance(item, dict) and item.get("path") in RENAMES.values():
            key = (item["path"], item.get("title"))
            if key in seen:
                continue
            seen.add(key)
        elif isinstance(item, dict) and isinstance(item.get("items"), list):
            item = dict(item, items=_deduped(item["items"], seen))
        out.append(item)
    return out


def rename_paths(items) -> list:
    """The menu `items` with every entry for an old name pointed at the new
    one where it stands. When that leaves two entries with the same name and
    title — a template refresh wrote the new menu before 009/010 put the old
    entries back in front — the first is kept and the later one dropped."""
    return _deduped(_renamed_items(items), set())


def _apply_bookmarks(root: Path) -> str:
    data = _load(root, BOOKMARKS, "the template refresh")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return "absent"
    items = data["items"]
    if not _paths(items) & set(RENAMES):
        return "unchanged"
    _dump(root, BOOKMARKS, dict(data, items=rename_paths(items)))
    return "renamed"


def _renamed_strings(value):
    if isinstance(value, str):
        return RENAMES.get(value, value)
    if isinstance(value, list):
        return [_renamed_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: _renamed_strings(v) for k, v in value.items()}
    return value


def _apply_workspace(root: Path) -> str:
    data = _load(root, WORKSPACE, "Obsidian")
    if data is None:
        return "absent"
    after = _renamed_strings(data)
    if after == data:
        return "unchanged"
    _dump(root, WORKSPACE, after)
    return "renamed"


def apply(root: Path) -> dict:
    root = Path(root)
    files, needs_human = {}, []
    for old, new in RENAMES.items():
        if not (root / old).is_file():
            files[old] = "absent"
        elif (root / new).exists():
            files[old] = "kept: the new name is already there"
            needs_human.append(
                f"{old}: kept next to {new}, which the menu now opens — compare "
                "them, keep any change you made, then delete the old one")
        else:
            os.replace(root / old, root / new)
            files[old] = "renamed"

    result = {"files": files,
              "bookmarks": _apply_bookmarks(root),
              "workspace": _apply_workspace(root)}
    try:
        moved = [old for old, new in RENAMES.items()
                 if provenance.rename_template_file(root, old, new)]
        result["provenance"] = "moved " + ", ".join(moved) if moved else "unchanged"
    except provenance.ProvenanceError as exc:
        result["provenance"] = f"skipped: {exc}"
        needs_human.append(f"provenance.json not read ({exc}); the template "
                           "refresh will offer the two renamed tables as missing")
    if needs_human:
        result["needs_human"] = needs_human
    return result


def verify(root: Path) -> dict:
    root = Path(root)
    for old, new in RENAMES.items():
        if (root / old).is_file() and not (root / new).exists():
            raise MigrationError(f"{old} was not renamed to {new}")
    data = _load(root, BOOKMARKS, "the template refresh")
    items = data.get("items") if isinstance(data, dict) else None
    if isinstance(items, list) and _paths(items) & set(RENAMES):
        raise MigrationError(f"{BOOKMARKS.as_posix()} still points at an old name")
    return {"checked": ["files", "bookmarks"]}
