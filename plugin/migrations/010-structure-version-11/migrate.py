"""Structure-version 11: Inbox becomes Input, and the menu takes its new order.

The owner approved this menu on 2026-10-06: the places you write sit at the
top (Daily notes, then Thoughts & ideas), the tables you browse follow, and
Input — what tonight's run picks up — closes the main list. The Library
leads with Recent and ends with Archive. In an existing vault this migration:

- writes that menu into `.obsidian/bookmarks.json`, exactly as 009 did: the
  shipped entries first, every bookmark the owner made kept after them, and
  the owner's own entries in the Library group kept in a "My library" group;
- removes `99-workflow-config/views/Inbox.base` when it is identical to what
  0.13.7 shipped (line endings ignored). A copy the owner changed is kept
  and reported — it is theirs.

`Input.base`, the new Thoughts & ideas views, the menu colours, and the
wording in Start here, How it works, the inbox README, CLAUDE.md and the
ontology arrive with the template refresh, like every other managed file.
No note is touched: daily notes keep their `## End of day` heading, which
the reader still accepts. `LOSSY` because a menu order the owner chose
themselves is reset.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 11
LOSSY = ("resets the sidebar menu to its new order (Input last, Thoughts & "
         "ideas under Daily notes); the owner's own bookmarks are kept, after the menu")

BOOKMARKS = Path(".obsidian") / "bookmarks.json"
CTIME = 1759000000000
VIEWS = "99-workflow-config/views"
OLD_INBOX = f"{VIEWS}/Inbox.base"
MENU = [
    ("Start here", "Start here.md"),
    ("Daily notes", "60-daily-notes/Daily notes.base"),
    ("Thoughts & ideas", "80-thoughts-ideas/Thoughts & ideas.base"),
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
# sha256 of Inbox.base as shipped in 0.13.7–0.13.8, LF line endings.
SHIPPED_INBOX_SHA256 = "36d6ea25994b87d932aaf7e1e286313ef27b662a5073c72d6f0c986ffa3eb161"


class MigrationError(Exception):
    """bookmarks.json exists but does not parse."""


def shipped_menu() -> list:
    """The menu exactly as the template's bookmarks.json carries it."""
    items = [{"type": "file", "ctime": CTIME + i, "path": p, "title": t}
             for i, (t, p) in enumerate(MENU)]
    items.append({"type": "group", "ctime": CTIME + 50, "title": LIBRARY_TITLE,
                  "items": [{"type": "file", "ctime": CTIME + 60 + i, "path": p, "title": t}
                            for i, (t, p) in enumerate(LIBRARY)]})
    return items


def _shipped_paths() -> set:
    # The old Inbox entry counts as shipped, so it is replaced, never kept.
    return {p for _, p in MENU} | {p for _, p in LIBRARY} | {OLD_INBOX}


def _merge(data) -> dict:
    existing = data.get("items") if isinstance(data, dict) else None
    existing = existing if isinstance(existing, list) else []
    shipped = _shipped_paths()
    kept = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "group" and item.get("title") == LIBRARY_TITLE:
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


def apply(root: Path) -> dict:
    root = Path(root)
    result = {}
    text = json.dumps(_merge(_load_bookmarks(root)), indent=2, ensure_ascii=False) + "\n"
    path = root / BOOKMARKS
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        result["bookmarks"] = "unchanged"
    else:
        vault.atomic_write(path, text)
        result["bookmarks"] = "merged"

    old = root / OLD_INBOX
    if not old.is_file():
        result["inbox_base"] = "absent"
    elif hashlib.sha256(old.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == SHIPPED_INBOX_SHA256:
        old.unlink()
        result["inbox_base"] = "removed"
    else:
        result["inbox_base"] = (f"kept: {OLD_INBOX} was changed by hand — "
                                "Input.base replaces it in the menu")
    return result


def verify(root: Path) -> dict:
    items = (_load_bookmarks(Path(root)) or {}).get("items") or []
    if items[:len(shipped_menu())] != shipped_menu():
        raise MigrationError(f"{BOOKMARKS.as_posix()}: the new menu did not land")
    return {"checked": ["bookmarks"]}
