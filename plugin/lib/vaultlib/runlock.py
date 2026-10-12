"""One run at a time (#271).

The owner's on-demand processing and the evening run both rewrite project
pages. Nothing stopped them overlapping before; this lock does, for runs that
see the same vault folder. Two OneDrive copies on two machines each have their
own lock — that case is out of reach of a file lock and is accepted.

A lock older than MAX_AGE is stale (a run that crashed), and a routine may
always take over its own lock (a crashed interactive call must not lock the
owner out for two hours).
"""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from . import vault

LOCK_RELPATH = Path("99-workflow-config") / "sync-state" / "run.lock.json"
MAX_AGE = timedelta(hours=2)
_ROUTINE_RE = re.compile(r"\A[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")


class RunLockError(Exception):
    """An argument the caller must fix."""


def _check(routine: str) -> None:
    if not _ROUTINE_RE.match(routine or ""):
        raise RunLockError(f"routine {routine!r} must be a lowercase slug")


def _read(root: Path) -> Optional[dict]:
    path = root / LOCK_RELPATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        datetime.fromisoformat(data["started_at"])
        return data
    except (ValueError, KeyError, TypeError, OSError):
        return {"routine": None, "started_at": None, "host": None}


def acquire(root: Path, routine: str, *, now: Optional[datetime] = None) -> dict:
    _check(routine)
    now = now or datetime.now()
    holder = _read(root)
    stale = False
    if holder is not None:
        started = holder.get("started_at")
        stale = started is None or now - datetime.fromisoformat(started) > MAX_AGE
        if not stale and holder.get("routine") != routine:
            return {"acquired": False, "took_over": False, "stale": False,
                    "holder": holder}
    mine = {"routine": routine, "started_at": now.isoformat(timespec="minutes"),
            "host": socket.gethostname()}
    path = root / LOCK_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    vault.atomic_write(path, json.dumps(mine, indent=2) + "\n")
    return {"acquired": True, "took_over": holder is not None, "stale": stale,
            "holder": mine}


def release(root: Path, routine: str) -> dict:
    _check(routine)
    holder = _read(root)
    if holder is None or holder.get("routine") != routine:
        return {"released": False, "holder": holder}
    (root / LOCK_RELPATH).unlink()
    return {"released": True, "holder": holder}
