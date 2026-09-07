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
OUTCOMES = ("written", "no-transcript", "skipped", "forbidden", "no-access")
# Teams transcripts trail the meeting; the lab saw them minutes-to-hours
# late. Two days is the horizon after which "no transcript" stops being
# "not yet" and becomes the answer.
NO_TRANSCRIPT_FINAL_AFTER_HOURS = 48
# A recheck costs a dispatch — the full event fetch, transcript fetch, and a
# worker to process it. Three /sync-recordings runs a day must not pay for
# the same still-transcript-less occurrence three times, so a provisional
# no-transcript answer holds for this long before it is worth re-checking.
RECHECK_MIN_INTERVAL_HOURS = 6
# "no-access" is a 403 on the transcript fetch whose body carries Graph
# error code 3003 ("does not have access to lookup meeting"), or one whose
# body could not be read at all — the transcript is not reachable from this
# account. Two known causes, neither "organised by someone else" (that
# framing was withdrawn — live reproduction 2026-08-31 showed attendee
# access to an intra-tenant transcript works once the tenant enables it):
# the meeting is hosted in another organisation's tenant (the home_domains
# filter in triage() is meant to catch these before dispatch, so one
# reaching a worker means the organizer's domain is missing from
# adapters.m365.home_domains, or the list is unset); or the organisation's
# own tenant has the "Transcript API access — Microsoft Graph access"
# setting off (Microsoft switched it off by default in late July 2026; IT
# turns it back on, then `sync m365-forget --outcome no-access` forces a
# re-check). It is terminal the moment it is recorded (no per-run retry —
# the condition heals only through a home_domains edit, a tenant setting
# change, or a forget), same as "skipped". "forbidden" is a 403 that
# positively names a different cause, counted and reported separately.
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


def _organizer_domain(event: dict):
    """(domain, raw_address) from a calendar-search listing's organizer
    field, or (None, address_or_None) when no usable address is present.

    Three shapes are accepted: a bare string (the calendar-search listing),
    a dict with `address` (a full event read), or a dict with
    `emailAddress.address` (Graph's own event shape) — this module does not
    own either connector's payload shape, so it stays permissive rather than
    asserting one.
    """
    node = event.get("organizer")
    if isinstance(node, str):
        addr = node
    elif isinstance(node, dict):
        addr = node.get("address")
        if not isinstance(addr, str):
            email_addr = node.get("emailAddress")
            addr = email_addr.get("address") if isinstance(email_addr, dict) else None
    else:
        addr = None
    if not isinstance(addr, str) or "@" not in addr:
        return None, (addr if isinstance(addr, str) and addr.strip() else None)
    return addr.rsplit("@", 1)[-1].strip().casefold(), addr.strip()


def triage(root: Path, events, now_utc: datetime, home_domains=None) -> dict:
    """Which occurrences in a raw calendar-search listing still need the
    full event fetch. Everything else is answered from the cache.

    Fail-open on a per-entry basis: an entry that cannot be keyed (its start
    will not parse) is warned about and sent to fetch anyway — losing an
    event is the one wrong answer a cache is never allowed to give. An entry
    with no id at all cannot even be fetched, so it is warned about and
    surfaced, never silently dropped.

    `home_domains`, when not None, is the vault owner's own organisation's
    email domains (`config.m365_home_domains`). An occurrence whose
    organizer's domain falls outside that list is hosted in another
    organisation's tenant — this account can never read its transcript, no
    matter how the earlier 403 framing put it — so it is filtered into
    `external` before either of the other two checks below, never fetched
    and never cached: a future external meeting is still external, and an
    occurrence an earlier run cached as forbidden/no-access must now show up
    here instead, because home_domains may have just been set. An organizer
    this module cannot read a domain from (missing, or no "@") fails open —
    proceeds to the normal path — rather than guess, with one warning.
    `home_domains is None` disables the filter entirely: the caller (the
    CLI) surfaces the config warning for that case, this function adds none.

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
    home_domain_set = ({d.casefold() for d in home_domains}
                       if home_domains is not None else None)
    cache = load(root)
    entries = cache["events"]
    fetch: List[dict] = []
    deferred: List[dict] = []
    external: List[dict] = []
    warnings: List[str] = []
    filtered = {"written": 0, "no_transcript_final": 0,
                "no_transcript_waiting": 0, "skipped": 0, "forbidden": 0,
                "no_access": 0, "external": 0}
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
        # The external-organizer filter outranks both the not-ended
        # deferral and the cache lookup below it: a future external meeting
        # is still external, and an occurrence cached as forbidden/no-access
        # by an earlier run must now surface as external if home_domains was
        # only just configured.
        if home_domain_set is not None:
            domain, organizer_addr = _organizer_domain(event)
            if domain is None:
                warnings.append(
                    f"event {event_id} ({subject!r}) carries no usable "
                    "organizer address — cannot apply the home-domain "
                    "filter; fetching normally")
            elif domain not in home_domain_set:
                external.append({**candidate, "organizer": organizer_addr})
                filtered["external"] += 1
                continue
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
        elif outcome == "no-access":
            filtered["no_access"] += 1
        elif outcome == "no-transcript":
            end = _occurrence_dt(event, "end") or start
            if now_utc - end >= timedelta(
                    hours=NO_TRANSCRIPT_FINAL_AFTER_HOURS):
                filtered["no_transcript_final"] += 1
            else:
                checked = None
                raw = seen.get("checked_at") if isinstance(seen, dict) \
                    else None
                if isinstance(raw, str):
                    try:
                        checked = datetime.strptime(raw, _KEY_FMT)
                    except ValueError:
                        checked = None  # fail open: an unreadable stamp
                                         # never blocks a fetch
                if checked is not None and now_utc - checked < timedelta(
                        hours=RECHECK_MIN_INTERVAL_HOURS):
                    filtered["no_transcript_waiting"] += 1
                else:
                    fetch.append(
                        {**candidate, "reason": "recheck-no-transcript"})
        else:
            # Unseen — or an outcome value this version does not know, which
            # re-checks rather than trusts (fail open).
            fetch.append({**candidate, "reason": "unseen"})
    return {"fetch": fetch, "deferred": deferred, "external": external,
            "filtered": filtered, "warnings": warnings}


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


FORGET_ALLOWED_OUTCOMES = ("no-access", "forbidden", "no-transcript")


def forget(root: Path, outcome: str) -> dict:
    """Drop every cached entry with one outcome, so triage re-checks those
    occurrences on the next run.

    The hand-editable-cache fallback made deterministic: `no-access` and
    `forbidden` never heal on their own, so the only way a consultant forces
    a re-check after client IT changes a permission is to make the cache
    forget what it settled — one outcome at a time, never the whole cache,
    which would also cost a re-check on every unrelated occurrence.

    `written` and `skipped` are refused outright, not just left undocumented:
    forgetting `written` would silently drop up to 30 days of write history
    and re-trigger a paid dispatch wave for meetings already synced, and
    `skipped` is a deliberate human decision the skip list already recorded
    a reason for — forgetting it would undo that decision by side effect.
    """
    if outcome not in OUTCOMES:
        raise SeenEventsError(
            f"outcome {outcome!r} must be one of {list(OUTCOMES)}")
    if outcome not in FORGET_ALLOWED_OUTCOMES:
        raise SeenEventsError(
            f"outcome {outcome!r} cannot be forgotten — forgetting "
            f"{outcome!r} would re-trigger a paid dispatch wave or undo a "
            "deliberate decision, not force a re-check of a stale denial; "
            f"forgettable outcomes are {list(FORGET_ALLOWED_OUTCOMES)}")
    cache = load(root)
    forgotten = 0
    for key in list(cache["events"]):
        entry = cache["events"][key]
        if isinstance(entry, dict) and entry.get("outcome") == outcome:
            del cache["events"][key]
            forgotten += 1
    if forgotten:
        save(root, cache)
    return {"forgotten": forgotten, "remaining": len(cache["events"])}
