"""A disposable index of what the vault already says.

The vault is still the ledger. This module never answers a question the
vault cannot — it only remembers the answer so the next run does not
re-parse 2,000 notes and re-hash every recorder export. Every entry is
keyed on (mtime_ns, size); anything that does not match is re-read, so the
cache cannot go stale behind an edit.

A missing, unreadable, malformed, or version-mismatched cache is a normal
cold state and is rebuilt in silence. Deleting this file is always safe.
That property is what makes it a cache and not a second ledger to
reconcile.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Set, Tuple

from . import vault

CACHE_RELPATH = Path("99-workflow-config") / "sync-state" / "scan-cache.json"
CACHE_VERSION = 1
SECTIONS = ("ledger", "inbox")

StatKey = Optional[Tuple[int, int]]


def _empty() -> dict:
    return {"version": CACHE_VERSION, "ledger": {}, "inbox": {}}


def load(root: Path) -> dict:
    """The cache as a plain dict, or a fresh empty one. Never raises."""
    try:
        data = json.loads((root / CACHE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return _empty()
    if any(not isinstance(data.get(section), dict) for section in SECTIONS):
        return _empty()
    return data


def save(root: Path, cache: dict) -> bool:
    """Persist the cache; return False when nothing was written.

    A quiet run leaves the cache byte-identical, and writing it anyway would
    put a side effect on meeting.write's hot path — known_recording_ids is a
    pure read whenever the vault has not changed, and must stay one.
    """
    path = root / CACHE_RELPATH
    text = json.dumps(cache, indent=2, sort_keys=True) + "\n"
    # Same tuple as load(): a torn or non-UTF-8 cache is a cold cache, not a
    # fault. UnicodeDecodeError is a ValueError, so OSError alone would let a
    # corrupt file crash every scan.
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, ValueError):
        pass
    vault.atomic_write(path, text)
    return True


def stat_key(path: Path) -> StatKey:
    """(mtime_ns, size), or None when the file cannot be stat'd — in which
    case nothing is cached for it and it is read every time."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def lookup(cache: dict, section: str, rel: str, key: StatKey) -> Optional[dict]:
    if key is None:
        return None
    entry = cache.get(section, {}).get(rel)
    if not isinstance(entry, dict):
        return None
    if entry.get("mtime_ns") != key[0] or entry.get("size") != key[1]:
        return None
    return entry


def store(cache: dict, section: str, rel: str, key: StatKey,
          payload: dict) -> None:
    if key is None:
        return
    cache.setdefault(section, {})[rel] = {
        "mtime_ns": key[0], "size": key[1], **payload}


def prune(cache: dict, section: str, live: Set[str]) -> None:
    """Drop entries for files that no longer exist."""
    entries = cache.get(section, {})
    for rel in [rel for rel in entries if rel not in live]:
        del entries[rel]
