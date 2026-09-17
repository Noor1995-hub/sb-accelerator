"""Per-recording fetch-error counter: a cache, not a ledger.

There is no per-recording retry state anywhere else in this plugin —
`scancache`, `seenevents`, and `lastsync` all answer "have we seen this
before", never "how many times in a row has this one failed". A recording
whose fetch fails forever (an oversized transcript, a Plaud id the connector
now returns `[]` for) retries at every run, at full dispatch cost, with no
way to stop.

This module counts three distinct UTC days per recording id, each within
14 days of the previous failure, and at the third suppresses the recording
the same way a human would: `syncjob.skip`, with a reason that says why.
"Day" here is always a UTC calendar day — `parse_now` is naive UTC, the
same clock every other cache in this plugin uses, never the vault owner's
local timezone. Three runs in one UTC day must never park an id on their
own — a park means "failed on three different days", not "failed three
times this morning" — so `record` increments a recording's count at most
once per UTC day, no matter how many times that id appears in one call or
across several calls the same day. Pruning (below) runs after counting, so
the 14 days is a gap the *next* failure must land inside, not a fixed
window from the first one: three failures 13 days apart each still park,
even though the whole span is 26 days.

Doctrine, same as scan-cache.json, seen-events.json, and last-sync.json: **a
cache, not a ledger.** A missing, unreadable, malformed, or version-mismatched
file is a normal cold state, rebuilt in silence — deleting it is always safe,
it only resets every recording's counter back to zero, which delays a park by
up to `PARK_AFTER` more failing days. It can never cause an unwanted park (the
skip list is the only thing that suppresses a recording) and can never lose a
recording that already synced (the vault's own ledger still dedups every
write, regardless of what this file says).

Once parked, a recording is the skip list's problem, not this module's:
`syncjob.skip` is idempotent on the id, so a stale fetch-errors entry
surviving alongside an already-parked id costs nothing beyond one wasted
counter. `record` still drops its own entry the moment it parks one, and
refuses to re-track an id that some later call resubmits after it is
already on the skip list — that id comes back under `already_parked`
instead of being counted from zero again.

`clear` — for an id that later succeeds — is also called from inside
`record` itself, not only by hand: `record` runs after a batch's outcomes are
already banked (SKILL.md's step 6 says so), so by the time it runs, any id
in this file that the run just wrote a meeting note for is already visible in
the vault's own ledger. Cross-checking against that ledger and dropping those
ids automatically means a recording that fails once, then succeeds on a
retry, never needs a human or an extra CLI call to un-count it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as _timezone
from pathlib import Path
from typing import List, Tuple

from . import syncjob, vault
from .m365 import M365Error, _parse_graph_dt

STATE_RELPATH = Path("99-workflow-config") / "sync-state" / "fetch-errors.json"
STATE_VERSION = 1
# Three distinct UTC days, not three attempts — see the module docstring.
PARK_AFTER = 3
# Deployed vaults keep this file indefinitely otherwise; a recording whose
# last failure is this stale is either already fixed or already parked by
# some other route, so the entry is dead weight either way.
PRUNE_AFTER_DAYS = 14

_KEY_FMT = "%Y-%m-%dT%H:%M:%S"
_DAY_FMT = "%Y-%m-%d"


class FetchErrorsError(Exception):
    """A malformed outcomes payload or id the caller must fix."""


def _empty() -> dict:
    return {"version": STATE_VERSION, "recordings": {}}


def load(root: Path) -> dict:
    """The state as a plain dict, or a fresh empty one. Never raises for a
    missing, unreadable, malformed, or version-mismatched file — cache
    doctrine, same as scancache/seenevents/lastsync."""
    try:
        data = json.loads((root / STATE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION \
            or not isinstance(data.get("recordings"), dict):
        return _empty()
    return data


def save(root: Path, state: dict) -> None:
    vault.atomic_write(
        root / STATE_RELPATH, json.dumps(state, indent=2, sort_keys=True) + "\n")


def parse_now(text) -> datetime:
    """A naive-UTC datetime: the caller's override, or the clock.

    Same parser every other cache in this plugin uses (`seenevents.parse_now`,
    `lastsync.set_mark`), so a caller that echoes a Graph-form timestamp
    (7-digit fractions, a trailing `Z`) lands on the same stored key a plain
    ISO string would.
    """
    if text is None:
        return datetime.now(_timezone.utc).replace(tzinfo=None, microsecond=0)
    try:
        return _parse_graph_dt(text, "--now")
    except M365Error as exc:
        raise FetchErrorsError(str(exc)) from exc


def _validate_entry(entry) -> Tuple[str, str]:
    """(canonical namespaced id, cleaned reason), or FetchErrorsError.

    Namespace validation happens here, up front — `record` validates every
    entry before it loads or mutates any state, so a malformed id fails the
    whole call immediately with a plain message. Without this, a
    non-namespaced id was silently accepted and counted for two days, then
    blew up *inside* `syncjob.skip` on the third (deep in the park branch,
    after other entries in the same call had already been counted) —
    aborting the whole batch on the day it should have parked instead.
    """
    if not isinstance(entry, dict):
        raise FetchErrorsError(
            f"--outcomes entries must be objects, got {type(entry).__name__}")
    recording_id = entry.get("id")
    if not isinstance(recording_id, str) or not recording_id.strip():
        raise FetchErrorsError("each fetch-error entry needs a non-empty id")
    try:
        canonical = syncjob._validate_id(recording_id)
    except syncjob.SyncError as exc:
        raise FetchErrorsError(str(exc)) from exc
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise FetchErrorsError(
            f"fetch-error entry for {recording_id!r} needs a non-empty reason")
    return canonical, " ".join(reason.split())


def _clear(state: dict, ids) -> List[str]:
    cleared = []
    for rid in ids:
        if rid in state["recordings"]:
            del state["recordings"][rid]
            cleared.append(rid)
    return cleared


def _is_stale(entry: dict, horizon: datetime) -> bool:
    """True when `entry`'s own `last_seen` already predates `horizon`.

    A malformed or missing `last_seen` counts as stale too, not kept
    forever — losing it only resets a counter, never a real answer. Shared
    by `_prune` (other ids' entries, checked at the end of `record`) and
    `record` itself (one id's own prior entry, checked before this call's
    failure would otherwise overwrite `last_seen` and hide the gap from
    ever being noticed again).
    """
    raw = entry.get("last_seen")
    try:
        last_seen = datetime.strptime(raw, _KEY_FMT) if isinstance(raw, str) else None
    except ValueError:
        last_seen = None
    return last_seen is None or last_seen < horizon


def _prune(state: dict, now: datetime) -> int:
    horizon = now - timedelta(days=PRUNE_AFTER_DAYS)
    pruned = 0
    for rid in list(state["recordings"]):
        if _is_stale(state["recordings"][rid], horizon):
            del state["recordings"][rid]
            pruned += 1
    return pruned


def record(root: Path, entries, now: datetime) -> dict:
    """Bank one fetch-error per failed recording; park at the third
    distinct UTC day.

    `entries` is a JSON array of `{"id", "reason"}` objects — the recordings
    that failed to fetch *this run*. Every entry is namespace-validated
    before anything is loaded or mutated (`_validate_entry`), so a malformed
    id fails the call up front rather than aborting mid-batch days later.

    An id already on the skip list (a previous call already parked it, or
    this batch resubmits a just-parked id) is never re-tracked from zero —
    it comes back under `already_parked` instead of `recorded`, and any
    stale entry this file still held for it is dropped.

    A recording already counted today (UTC) has its `last_reason`/
    `last_seen` refreshed but its `count` left alone: three runs in one UTC
    day must not park an id that only ever failed once, today. An id whose
    existing entry's `last_seen` already predates the 14-day horizon is
    treated as a fresh failure instead — its stale count is discarded before
    counting this one, never combined with it — because `_prune` (below)
    only ever drops *other* ids' stale entries in this same call; it can
    never catch this id's own entry, since this call is about to overwrite
    that very `last_seen` with `now`. Without this check, three failures
    months apart would still combine into a park, contradicting the
    documented "each within 14 days of the previous failure" contract. Once
    a recording's count reaches `PARK_AFTER`, it is suppressed via
    `syncjob.skip` with a reason that names the count and the failure, and
    dropped from this file — the skip list is now the authority on it.
    """
    if not isinstance(entries, list):
        raise FetchErrorsError(
            "--outcomes must be a JSON array of {id, reason} objects")
    validated = [_validate_entry(entry) for entry in entries]
    state = load(root)
    skip_list = syncjob.read_skip_list(root)
    today = now.strftime(_DAY_FMT)
    stamp = now.strftime(_KEY_FMT)
    horizon = now - timedelta(days=PRUNE_AFTER_DAYS)
    recorded: List[str] = []
    parked: List[dict] = []
    already_parked: List[str] = []
    failing_ids = set()
    for recording_id, reason in validated:
        failing_ids.add(recording_id)
        if recording_id in skip_list:
            already_parked.append(recording_id)
            state["recordings"].pop(recording_id, None)
            continue
        entry = state["recordings"].get(recording_id)
        if isinstance(entry, dict) and _is_stale(entry, horizon):
            # The gap since this id's own previous failure already exceeds
            # the window a park may span — start counting fresh rather than
            # let last_seen's imminent overwrite (below) hide the gap from
            # every future _prune call.
            entry = None
        if not isinstance(entry, dict):
            entry = {"count": 0, "first_seen": stamp, "last_seen": None,
                     "last_reason": None}
        already_today = (entry.get("last_seen") or "")[:10] == today
        if not already_today:
            entry["count"] = int(entry.get("count") or 0) + 1
        entry["last_seen"] = stamp
        entry["last_reason"] = reason
        state["recordings"][recording_id] = entry
        recorded.append(recording_id)
        if entry["count"] >= PARK_AFTER:
            syncjob.skip(
                root, recording_id,
                reason=f"parked after {entry['count']} fetch-errors: {reason}")
            parked.append({"id": recording_id, "reason": reason})
            del state["recordings"][recording_id]
    # Self-heal: an id tracked here that the vault's own ledger now carries
    # succeeded on some later attempt this run or a previous one — see the
    # module docstring for why this is safe to do automatically.
    tracked_other = [rid for rid in state["recordings"] if rid not in failing_ids]
    cleared: List[str] = []
    if tracked_other:
        synced_ids, _warnings = syncjob.known_recording_ids(root)
        cleared = _clear(state, [rid for rid in tracked_other if rid in synced_ids])
    _prune(state, now)
    save(root, state)
    return {"recorded": recorded, "parked": parked, "cleared": cleared,
            "already_parked": already_parked}


def clear(root: Path, ids) -> dict:
    """Drop tracked ids by hand — the counter no longer applies.

    A library helper only — there is no `sync fetch-error-clear` or similar
    CLI verb for this. `record` already calls it itself for the one case
    that needs no human involved (an id whose meeting note now exists on
    disk, cross-checked against the vault's own ledger); anything else that
    wants an id's counter dropped by hand does so today by editing or
    deleting fetch-errors.json directly — safe under this module's own
    cache doctrine — not through a dedicated command.

    Idempotent: an id this file is not tracking is silently skipped rather
    than raising, since a caller clearing "whatever succeeded" cannot always
    know in advance which ids this file actually holds.
    """
    if not isinstance(ids, list):
        raise FetchErrorsError("ids must be a JSON array of id strings")
    state = load(root)
    cleared = _clear(state, [syncjob.canonical_id(rid) for rid in ids])
    if cleared:
        save(root, state)
    return {"cleared": cleared}
