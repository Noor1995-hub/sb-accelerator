"""Seen-events cache: M365 dedup BEFORE the full event fetch.

`m365 ids` derives the dedup id from a FULL calendar event read, so on its
own the pipeline must fetch every candidate the cheap calendar search
returned before `sync dedup` can say most of them are already synced or
transcript-less — and, remembering nothing, re-fetch the same candidates on
every run. This module remembers the outcome per occurrence, keyed by what
the search listing already carries — (event id, occurrence start UTC) — so
triage() answers "which occurrences still need the fetch" from the listing
alone, and record() writes the outcomes back after processing.

Doctrine, same as scan-cache.json: **a cache, not a ledger.** The vault's
source-recording-id ledger still dedups every write, so a missing,
unreadable, malformed, or version-mismatched cache is a normal cold state —
everything re-checks, nothing double-writes. Deleting this file is always
safe.

One outcome is time-qualified: `no-transcript` is provisional while the
event ended less than NO_TRANSCRIPT_FINAL_AFTER_HOURS before now, because
Teams delivers transcripts with delay — those occurrences are re-fetched.
Once the window has passed, the outcome is final and the occurrence is never
fetched again.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as _timezone
from pathlib import Path
from typing import List, Optional, Tuple

from . import vault
from .m365 import _parse_graph_dt, M365Error

CACHE_RELPATH = Path("99-workflow-config") / "sync-state" / "seen-events.json"
CACHE_VERSION = 1
OUTCOMES = ("written", "no-transcript", "skipped", "forbidden")
# Teams transcripts trail the meeting; the lab saw them minutes-to-hours
# late. Two days is the horizon after which "no transcript" stops being
# "not yet" and becomes the answer.
NO_TRANSCRIPT_FINAL_AFTER_HOURS = 48
# "forbidden" is a cross-tenant 403 on the transcript fetch: the ACL never
# heals, so — unlike "no-transcript" — it is terminal the moment it is
# recorded, same as "skipped".
# Occurrences older than this fall out of every search window this plugin
# runs (7 trailing days), so their entries are dead weight; dropping them
# costs at most one re-check if a wider window ever asks again.
PRUNE_AFTER_DAYS = 30

_KEY_FMT = "%Y-%m-%dT%H:%M:%S"


class SeenEventsError(Exception):
    """A malformed listing or outcome payload the caller must fix."""


def parse_now(text: Optional[str]) -> datetime:
    """A naive-UTC datetime: the caller's override, or the clock.

    Overrides go through the Graph parser, not bare fromisoformat: a caller
    will echo Graph's own `...Z` form, which Python 3.10 — the Cowork
    floor — rejects there.
    """
    if text is None:
        return datetime.now(_timezone.utc).replace(tzinfo=None, microsecond=0)
    try:
        return _parse_graph_dt(text, "--now")
    except M365Error as exc:
        raise SeenEventsError(str(exc)) from exc


def _empty() -> dict:
    return {"version": CACHE_VERSION, "events": {}}


def load(root: Path) -> dict:
    """The cache as a plain dict, or a fresh empty one. Never raises."""
    try:
        data = json.loads((root / CACHE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION \
            or not isinstance(data.get("events"), dict):
        return _empty()
    return data


def save(root: Path, cache: dict) -> None:
    vault.atomic_write(root / CACHE_RELPATH,
                       json.dumps(cache, indent=2, sort_keys=True) + "\n")


def _normalize_start(value, label: str) -> str:
    """Graph datetimes come in several precisions (7-digit fractions, Z or
    not); the key must land on one spelling from every spelling."""
    return _parse_graph_dt(value, label).strftime(_KEY_FMT)


def _occurrence_dt(event: dict, field: str) -> Optional[datetime]:
    """The UTC datetime of one listing field, or None when absent/unusable."""
    node = event.get(field)
    if isinstance(node, dict):
        tz = node.get("timeZone")
        if tz is not None and str(tz).casefold() != "utc":
            raise SeenEventsError(
                f"event {field}.timeZone {tz!r} is not UTC — the listing "
                "must be queried with UTC bounds; refusing to guess")
        node = node.get("dateTime")
    if not node:
        return None
    try:
        return _parse_graph_dt(node, f"event {field}")
    except M365Error:
        return None


def triage(root: Path, events, now_utc: datetime) -> dict:
    """Which occurrences in a raw calendar-search listing still need the
    full event fetch. Everything else is answered from the cache.

    Fail-open on a per-entry basis: an entry that cannot be keyed (its start
    will not parse) is warned about and sent to fetch anyway — losing an
    event is the one wrong answer a cache is never allowed to give. An entry
    with no id at all cannot even be fetched, so it is warned about and
    surfaced, never silently dropped.

    One class is refused outright rather than fetched: an occurrence that
    has not ended yet comes back in `deferred` (reason `not-ended`), never
    in `fetch`. M365 synthesizes meetingTranscriptUrl for future occurrences
    too, and on a recurring series that URL can answer with *past*
    occurrences' transcripts — future-dated junk. Deferral is per-run and
    never recorded, so the occurrence syncs normally on the first run after
    the meeting ends.
    """
    if not isinstance(events, list):
        raise SeenEventsError(
            "--events must be a JSON array of calendar-search event objects")
    cache = load(root)
    entries = cache["events"]
    fetch: List[dict] = []
    deferred: List[dict] = []
    warnings: List[str] = []
    filtered = {"written": 0, "no_transcript_final": 0, "skipped": 0,
                "forbidden": 0}
    for event in events:
        if not isinstance(event, dict):
            raise SeenEventsError(
                f"--events entries must be event objects, got "
                f"{type(event).__name__}")
        subject = event.get("subject") or None
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            warnings.append(
                f"listing entry {subject!r} carries no event id — it cannot "
                "be fetched or cached; surface it to a human")
            continue
        start = _occurrence_dt(event, "start")
        if start is None:
            warnings.append(
                f"event {event_id} ({subject!r}) has no parseable start — "
                "uncacheable, fetching it every run")
            fetch.append({"id": event_id, "start_utc": None,
                          "subject": subject, "reason": "unkeyed"})
            continue
        start_utc = start.strftime(_KEY_FMT)
        candidate = {"id": event_id, "start_utc": start_utc,
                     "subject": subject}
        # A meeting that has not ended cannot have a transcript. Checked
        # before the cache so no recorded outcome (clock skew, an improvised
        # window) can resurrect the fetch; with no end field the start
        # decides, which still defers anything future.
        end = _occurrence_dt(event, "end") or start
        if end > now_utc:
            deferred.append({**candidate, "reason": "not-ended"})
            continue
        seen = entries.get(f"{event_id}|{start_utc}")
        outcome = seen.get("outcome") if isinstance(seen, dict) else None
        if outcome == "written":
            filtered["written"] += 1
        elif outcome == "skipped":
            filtered["skipped"] += 1
        elif outcome == "forbidden":
            filtered["forbidden"] += 1
        elif outcome == "no-transcript":
            end = _occurrence_dt(event, "end") or start
            if now_utc - end >= timedelta(
                    hours=NO_TRANSCRIPT_FINAL_AFTER_HOURS):
                filtered["no_transcript_final"] += 1
            else:
                fetch.append({**candidate, "reason": "recheck-no-transcript"})
        else:
            # Unseen — or an outcome value this version does not know, which
            # re-checks rather than trusts (fail open).
            fetch.append({**candidate, "reason": "unseen"})
    return {"fetch": fetch, "deferred": deferred, "filtered": filtered,
            "warnings": warnings}


def _validate_outcome(entry) -> Tuple[str, dict]:
    if not isinstance(entry, dict):
        raise SeenEventsError(
            f"--outcomes entries must be objects, got {type(entry).__name__}")
    event_id = entry.get("id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise SeenEventsError("each outcome needs the event id")
    try:
        start_utc = _normalize_start(entry.get("start_utc"),
                                     "outcome start_utc")
    except M365Error as exc:
        raise SeenEventsError(str(exc)) from exc
    outcome = entry.get("outcome")
    if outcome not in OUTCOMES:
        raise SeenEventsError(
            f"outcome {outcome!r} must be one of {list(OUTCOMES)}")
    recording_id = entry.get("recording_id")
    if outcome == "written":
        if not recording_id:
            raise SeenEventsError(
                'a "written" outcome requires its recording_id — it maps '
                "this occurrence onto the vault's ledger")
        if not str(recording_id).startswith("m365:"):
            raise SeenEventsError(
                f"recording_id {recording_id!r} must carry the m365: "
                "namespace")
    payload = {"outcome": outcome}
    if recording_id:
        payload["recording_id"] = str(recording_id)
    return f"{event_id}|{start_utc}", payload


def record(root: Path, outcomes, now_utc: datetime) -> dict:
    """Write processing outcomes back, and prune occurrences that have aged
    out of every window this plugin searches."""
    if not isinstance(outcomes, list):
        raise SeenEventsError(
            "--outcomes must be a JSON array of outcome objects")
    validated = [_validate_outcome(entry) for entry in outcomes]
    cache = load(root)
    checked_at = now_utc.strftime(_KEY_FMT)
    for key, payload in validated:
        cache["events"][key] = {**payload, "checked_at": checked_at}
    horizon = now_utc - timedelta(days=PRUNE_AFTER_DAYS)
    pruned = 0
    for key in list(cache["events"]):
        try:
            start = datetime.strptime(key.rsplit("|", 1)[1], _KEY_FMT)
        except (IndexError, ValueError):
            start = None
        if start is None or start < horizon:
            del cache["events"][key]
            pruned += 1
    save(root, cache)
    return {"recorded": len(validated), "pruned": pruned,
            "cached_total": len(cache["events"])}
