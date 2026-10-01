"""Message feed state: the cursor, open gaps, the requeue list.

A cache, not a ledger (like last-sync and seen-events): a missing or broken
file loads as empty. The cursor is the newest message the last successful run
saw (from data, never from the clock), so a missed evening catches itself up.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from . import dates, seenevents, vault

STATE_RELPATH = Path("99-workflow-config") / "sync-state" / "messages.json"
GAP_HORIZON_DAYS = 7
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _empty() -> dict:
    return {"version": 1, "cursor": None, "gaps": [], "requeue": [], "proposed": [],
            "closed_unread": [], "last_run": None, "next_gap": 1}


def load(root: Path) -> dict:
    try:
        state = json.loads((root / STATE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(state, dict) or state.get("version") != 1:
        return _empty()
    state = {**_empty(), **state}
    return state if _well_formed(state) else _empty()


def _parses(text) -> bool:
    try:
        seenevents.parse_now(text)
    except Exception:
        return False
    return True


def _well_formed(state: dict) -> bool:
    if state["cursor"] is not None and not (isinstance(state["cursor"], str) and _parses(state["cursor"])):
        return False
    for key in ("gaps", "requeue", "proposed", "closed_unread"):
        if not isinstance(state[key], list):
            return False
    if not isinstance(state["next_gap"], int) or isinstance(state["next_gap"], bool):
        return False
    for gap in state["gaps"]:
        if not isinstance(gap, dict) or any(k not in gap for k in ("id", "source", "from", "to")):
            return False
        if not (_parses(gap["from"]) and _parses(gap["to"])):
            return False
    return True


def save(root: Path, state: dict) -> None:
    vault.atomic_write(root / STATE_RELPATH, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _parse(text: str) -> datetime:
    return seenevents.parse_now(text)


def cursor(root: Path, *, now: str, timezone, utc_offset, since: Optional[str] = None) -> dict:
    state = load(root)
    now_dt = _parse(now)
    first_run = state["cursor"] is None and not since
    dirty = False
    if since:
        start = _parse(since).strftime(_FMT)
    elif state["cursor"]:
        start = state["cursor"]
        clamp = (now_dt - timedelta(days=GAP_HORIZON_DAYS)).strftime(_FMT)
        if _parse(start) < _parse(clamp):
            state["closed_unread"] = state["closed_unread"] + [{"source": "all", "from": start, "to": clamp}]
            state["cursor"] = start = clamp
            dirty = True
    else:
        local_now, _ = dates.utc_to_local(now_dt, timezone, utc_offset)
        midnight = datetime.combine(local_now.date() - timedelta(days=1), datetime.min.time())
        offset, _ = dates.resolve_offset_minutes(midnight, timezone, utc_offset)
        start = (midnight - timedelta(minutes=offset)).strftime(_FMT)
    horizon = now_dt - timedelta(days=GAP_HORIZON_DAYS)
    open_, closed = [], []
    for gap in state["gaps"]:
        (open_ if _parse(gap["to"]) >= horizon else closed).append(gap)
    if closed:
        state["gaps"] = open_
        state["closed_unread"] = state["closed_unread"] + closed
        dirty = True
    if dirty:
        save(root, state)
    return {"since": start, "first_run": first_run,
            "gaps": open_, "closed": closed}


def advance(root: Path, *, newest: Optional[str], new_gaps: List[dict], filled: List[str], now: str) -> dict:
    state = load(root)
    if newest and (state["cursor"] is None or _parse(newest) > _parse(state["cursor"])):
        state["cursor"] = _parse(newest).strftime(_FMT)
    state["gaps"] = [g for g in state["gaps"] if g["id"] not in set(filled)]
    for gap in new_gaps:
        state["gaps"].append({"id": str(state["next_gap"]), **gap})
        state["next_gap"] += 1
    state["last_run"] = _parse(now).strftime(_FMT)
    save(root, state)
    return {"cursor": state["cursor"], "gaps": state["gaps"]}


def requeue_add(root: Path, slug: str, log: str) -> None:
    state = load(root)
    entry = {"slug": slug, "log": log}
    if entry not in state["requeue"]:
        state["requeue"].append(entry)
        save(root, state)


def requeue_take(root: Path) -> List[dict]:
    state = load(root)
    taken, state["requeue"] = state["requeue"], []
    if taken:
        save(root, state)
    return taken
