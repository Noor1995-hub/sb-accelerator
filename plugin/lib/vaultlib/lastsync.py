"""Per-adapter last-successful-sync watermark: a cache, not a ledger.

Each adapter (`m365`, `plaud`) remembers the UTC instant its last clean sync
run covered through, so the next discovery window can start from that mark
instead of always re-covering the full trailing window a sync's cost
controls allow. A later task (`dates window`) reads this mark to narrow that
window's floor; this module knows nothing about window arithmetic — it only
remembers one instant per adapter and lets it move forward.

Doctrine, same as scan-cache.json and seen-events.json: **a cache, not a
ledger.** A missing, unreadable, malformed, or version-mismatched file is a
normal cold state, answered as `None` rather than raised — the caller falls
back to its own discovery cap, nothing is lost. Deleting this file is always
safe: it only widens the next window back out to that cap, it never drops or
duplicates a sync, because the vault's own ledgers (source-recording-id,
seen-events) still dedup every write regardless of what this file says.

`set_mark` is monotonic on purpose (design-review finding: a stale replay —
a retried worker, a resumed batch, a clock that jumped backward — must never
move the mark earlier than what is already stored). Accepting an earlier
value would pull the next window's floor backward and widen it, but it would
also *discard* the guarantee the later mark already made: the gap between
the two marks would never be re-covered, because the caller trusts the mark
to mean "already covered through here." So an earlier (or equal) `utc_to`
is a no-op — the file is not rewritten, and the result reports
`{"advanced": False, ...}` with the stored mark unchanged.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import vault
from .m365 import _parse_graph_dt, M365Error

STATE_RELPATH = Path("99-workflow-config") / "sync-state" / "last-sync.json"
STATE_VERSION = 1
ADAPTERS = ("m365", "plaud")

_KEY_FMT = "%Y-%m-%dT%H:%M:%S"


class LastSyncError(Exception):
    """An unknown adapter name or an unparseable datetime the caller must fix."""


def _check_adapter(adapter: str) -> None:
    if adapter not in ADAPTERS:
        raise LastSyncError(
            f"unknown adapter {adapter!r}; must be one of {list(ADAPTERS)}")


def _parse_utc(value, label: str) -> datetime:
    """Graph-form ('...Z', 7-digit fractions) or plain ISO -> naive UTC,
    the same parser seenevents.parse_now uses, so a caller that echoes a
    Graph timestamp verbatim (Python 3.10's fromisoformat rejects it) still
    lands on one spelling."""
    try:
        return _parse_graph_dt(value, label)
    except M365Error as exc:
        raise LastSyncError(str(exc)) from exc


def _empty() -> dict:
    return {"version": STATE_VERSION, "adapters": {}}


def _load(root: Path) -> dict:
    """The state as a plain dict, or a fresh empty one. Never raises for a
    missing, unreadable, malformed, or version-mismatched file — cache
    doctrine."""
    try:
        data = json.loads((root / STATE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION \
            or not isinstance(data.get("adapters"), dict):
        return _empty()
    return data


def _save(root: Path, state: dict) -> None:
    vault.atomic_write(root / STATE_RELPATH,
                       json.dumps(state, indent=2, sort_keys=True) + "\n")


def _stored_mark(state: dict, adapter: str):
    """(entry dict or None, parsed datetime or None) for one adapter. A
    malformed stored entry answers None rather than raising — it never
    blocks a fresh advance, same fail-open the cache doctrine uses
    elsewhere."""
    entry = state["adapters"].get(adapter)
    if not isinstance(entry, dict):
        return None, None
    raw = entry.get("last_utc_to")
    if not isinstance(raw, str):
        return entry, None
    try:
        return entry, datetime.strptime(raw, _KEY_FMT)
    except ValueError:
        return entry, None


def read(root: Path, adapter: str) -> Optional[datetime]:
    """The stored watermark as a naive-UTC datetime, or None on any cold or
    malformed state — missing file, unreadable JSON, wrong version, or an
    entry that will not parse. Only an unknown adapter name is the caller's
    mistake, and that raises rather than answering None."""
    _check_adapter(adapter)
    _, mark = _stored_mark(_load(root), adapter)
    return mark


def set_mark(root: Path, adapter: str, utc_to, now_utc: datetime) -> dict:
    """Advance one adapter's watermark to `utc_to`, stamped with `now_utc`.

    Monotonic: a `utc_to` at or before the stored mark is a no-op — the
    file is left untouched and the result reports `advanced: False` with
    the mark and stamp exactly as already stored.
    """
    _check_adapter(adapter)
    new_mark = _parse_utc(utc_to, "--utc-to")
    state = _load(root)
    entry, previous = _stored_mark(state, adapter)
    if previous is not None and new_mark <= previous:
        return {"adapter": adapter, "advanced": False,
                "last_utc_to": entry.get("last_utc_to"),
                "set_at": entry.get("set_at")}
    new_raw = new_mark.strftime(_KEY_FMT)
    stamp = now_utc.strftime(_KEY_FMT)
    state["adapters"][adapter] = {"last_utc_to": new_raw, "set_at": stamp}
    _save(root, state)
    return {"adapter": adapter, "advanced": True,
            "last_utc_to": new_raw, "set_at": stamp}
