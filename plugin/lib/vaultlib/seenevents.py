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

from . import dates, syncjob, vault
from .m365 import (_parse_graph_dt, _resolve_zone, event_uri, graph_dt_utc,
                   M365Error)

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


def _normalize_event_id(event_id) -> str:
    """The one normalization every `event_id`-keyed cache lookup or write
    must agree on: stripped of incidental surrounding whitespace.

    `--event-id` crosses the CLI boundary verbatim (`cli.py` applies no
    `type=` stripping), so a value like `"AAMkAGId1 "` is entirely
    plausible. `_validate_outcome` (and so `record`, and so
    `settle_duplicate`), `forget_event`, and `unsettle_duplicate`'s own
    guard lookup all build a cache key from this value — if any one of
    them normalized differently (or not at all) the keys would diverge
    and a lookup would silently miss the entry a sibling call just wrote.
    """
    return str(event_id or "").strip()


def _occurrence_dt(event: dict, field: str) -> Optional[datetime]:
    """The UTC datetime of one listing field, or None when absent/unusable."""
    node = event.get(field)
    if isinstance(node, dict):
        if not node.get("dateTime"):
            return None
        # The zone label is resolved (or the whole listing refused) before
        # the datetime's own parse gets to fail open below: an unreadable
        # zone is a listing-wide fact, not one bad entry.
        if node.get("timeZone") is not None:
            try:
                _resolve_zone(node.get("timeZone"), f"event {field}.timeZone")
            except M365Error as exc:
                raise SeenEventsError(str(exc)) from exc
        try:
            return graph_dt_utc(node, f"event {field}")
        except M365Error:
            return None
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


def _collide_duplicate(root: Path, candidate: dict, start: datetime,
                       end: datetime, *, timezone=None, utc_offset=None,
                       notes=None) -> Optional[dict]:
    """None, or the `duplicate`-bucket entry for a **strong**, precise,
    cross-namespace match — the triage-time half of the plan's three
    collision nets (A2).

    Computed straight from the listing, since `m365 ids` cannot be used here
    at all: the listing carries no `meetingTranscriptUrl` (only a full event
    read does), so there is nothing to derive an m365 id from yet. The owner-
    local start and the occurrence's own duration (`dates.minutes_between` —
    the same round()-semantics helper `m365 ids`' `event_duration_min` uses,
    so the two never disagree at the boundary) are enough for
    `syncjob.collide`, which does not need an id, only a time window. `notes`
    is `syncjob.load_collide_notes(root)["notes"]`, preloaded once by
    `triage` and reused for every candidate in this run instead of
    re-reading `20-meetings/` per candidate.

    A match at a namespace other than `m365` — this whole function only ever
    runs on m365 candidates — means another adapter already captured this
    conversation, but only when `collide` also flags it `strong`: its
    15-minute grace makes two merely-adjacent meetings a *match* with
    essentially no real overlap, and auto-settling on that would silently
    lose a genuine back-to-back meeting. An imprecise (date-only) match, or
    a precise-but-not-strong one, is never a duplicate here either, same as
    the write-time check: it stays in `fetch` for the worker or a human to
    look at.

    A listing entry with no `end` falls back to `end == start` at the call
    site (occurrence duration 0) — that is a missing fact, not a real
    zero-length meeting, but `collide` floors any duration to a 1-minute
    window, and a 1-minute window's own strong-match threshold is
    `ceil(1/2) == 1`, so a single overlapping minute would trivially count
    as strong. Rather than let a fabricated window drive an auto-skip, skip
    the collide call entirely when there is no real duration to query with:
    the candidate stays in `fetch`, and the write-time net (which sees the
    payload's own real duration once the worker derives one) still applies.
    """
    duration_min = dates.minutes_between(start, end)
    if duration_min <= 0:
        return None
    local_start, _ = dates.utc_to_local(start, timezone, utc_offset)
    result = syncjob.collide(
        root, local_start.strftime("%Y-%m-%dT%H:%M"), duration_min,
        notes=notes)
    for match in result["matches"]:
        if match["imprecise"] or not match["strong"]:
            continue
        existing_id = match.get("source-recording-id")
        namespace = str(existing_id or "").split(":", 1)[0]
        if namespace and namespace != "m365":
            return {
                "id": candidate["id"], "start_utc": candidate["start_utc"],
                "subject": candidate["subject"],
                "event_uri": candidate["event_uri"],
                "existing_stem": match["stem"],
                "existing_id": existing_id,
            }
    return None


def triage(root: Path, events, now_utc: datetime, home_domains=None, *,
          collide: bool = False, timezone=None, utc_offset=None) -> dict:
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

    `collide` (default False) adds the triage-time half of the cross-adapter
    duplicate check (A2): for every candidate that would otherwise land in
    `fetch`, run `syncjob.collide` against the listing's own start/end. A
    precise match from another adapter's namespace moves the candidate into
    the new top-level `duplicate` bucket instead — `{id, start_utc, subject,
    event_uri, existing_stem, existing_id}` — never into `fetch`. This has
    no m365 id yet (that needs the full event), so the caller banks it as a
    plain `{"id", "start_utc", "outcome": "skipped"}` seen-events entry, the
    same shape `sync m365-record` already accepts with no `recording_id`.
    Imprecise (date-only) matches never move anything — they stay in
    `fetch`, same as the write-time check's "look at it" warning. `timezone`/
    `utc_offset` are required together with `collide` (the "exactly one" rule
    every owner-local conversion in this CLI uses) — `collide=False`, the
    default, never touches them and needs neither.
    """
    if not isinstance(events, list):
        raise SeenEventsError(
            "--events must be a JSON array of calendar-search event objects")
    home_domain_set = ({d.casefold() for d in home_domains}
                       if home_domains is not None else None)
    cache = load(root)
    entries = cache["events"]
    fetch: List[dict] = []
    duplicate: List[dict] = []
    deferred: List[dict] = []
    external: List[dict] = []
    warnings: List[str] = []
    # Loaded once for the whole run, never per candidate: `syncjob.collide`
    # otherwise re-globs and re-parses 20-meetings/ once per fetch survivor.
    if collide:
        _preload = syncjob.load_collide_notes(root)
        collide_notes = _preload["notes"]
        # An unparseable 20-meetings/*.md file is a property of the vault,
        # not of any one candidate — surfaced once here, since collide()
        # itself starts from warnings=[] whenever notes is pre-injected
        # (it never re-reads the folder to discover them) and
        # _collide_duplicate never reads a per-call result["warnings"].
        warnings.extend(_preload["warnings"])
    else:
        collide_notes = None
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
                          "subject": subject,
                          "event_uri": event_uri(event_id),
                          "reason": "unkeyed"})
            continue
        start_utc = start.strftime(_KEY_FMT)
        candidate = {"id": event_id, "start_utc": start_utc,
                     "subject": subject,
                     "event_uri": event_uri(event_id)}
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
                    dup = (_collide_duplicate(
                               root, candidate, start, end,
                               timezone=timezone, utc_offset=utc_offset,
                               notes=collide_notes)
                           if collide else None)
                    if dup is not None:
                        duplicate.append(dup)
                    else:
                        fetch.append(
                            {**candidate, "reason": "recheck-no-transcript"})
        else:
            # Unseen — or an outcome value this version does not know, which
            # re-checks rather than trusts (fail open).
            dup = (_collide_duplicate(root, candidate, start, end,
                                      timezone=timezone, utc_offset=utc_offset,
                                      notes=collide_notes)
                   if collide else None)
            if dup is not None:
                duplicate.append(dup)
            else:
                fetch.append({**candidate, "reason": "unseen"})
    return {"fetch": fetch, "duplicate": duplicate, "deferred": deferred,
            "external": external, "filtered": filtered, "warnings": warnings}


def _validate_outcome(entry) -> Tuple[str, dict]:
    if not isinstance(entry, dict):
        raise SeenEventsError(
            f"--outcomes entries must be objects, got {type(entry).__name__}")
    if not isinstance(entry.get("id"), str) or not str(entry.get("id")).strip():
        raise SeenEventsError("each outcome needs the event id")
    event_id = _normalize_event_id(entry.get("id"))
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
    # Triage sends an occurrence with no parseable start as `unkeyed`, with
    # `start_utc: null`. The cache cannot key it (and prune would drop it),
    # so it is left out — failing the call lost every other outcome in the
    # batch (review 2026-10-12).
    def is_unkeyed(entry) -> bool:
        # Only triage's own shape: an explicit null start on an entry that
        # otherwise has its id and outcome. Anything else malformed still
        # fails loudly, as before.
        return (isinstance(entry, dict) and "start_utc" in entry
                and entry["start_utc"] is None and bool(entry.get("id"))
                and entry.get("outcome") in OUTCOMES)

    unkeyed = [e for e in outcomes if is_unkeyed(e)]
    validated = [_validate_outcome(entry) for entry in outcomes if not is_unkeyed(entry)]
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
    return {"recorded": len(validated), "skipped_unkeyed": len(unkeyed),
            "pruned": pruned, "cached_total": len(cache["events"])}


def settle_duplicate(root: Path, recording_id: str, existing_id: str,
                     stem: str, *, event_id: Optional[str] = None,
                     start_utc: Optional[str] = None,
                     now_utc: Optional[datetime] = None) -> dict:
    """Settle an unattended cross-adapter duplicate — `sync settle-duplicate`,
    A4's one CLI verb for the "drop it" path.

    Validates first, then writes in order: the skip-list line
    (`syncjob.skip`, reason "same meeting already synced as <existing_id>
    (<stem>)") and, when the underlying m365 occurrence is known, the
    seen-events `skipped` entry — the same validate-before-writing shape
    `syncjob.park` uses for an inbox item, adapted here to two writes: both
    name the same reason, so the two ledgers never tell a different story
    about why this id never synced. `event_id` and `start_utc` travel
    together (a triage-caught duplicate always has both; a worker-time one
    derived after a full event fetch does too) — passing exactly one is
    refused. Omitted entirely, only the skip-list line is written (a
    plaud/inbox duplicate has no seen-events entry to bank in the first
    place).

    The seen-events entry is validated (`_validate_outcome`, the same check
    `record` applies) *before* the skip-list line is written, not after — a
    malformed `event_id`/`start_utc` refuses the whole call with neither
    ledger touched, never leaving the skip-list line written and the
    seen-events entry silently missing. This is validation-order safety,
    not a transactional guarantee: see `unsettle_duplicate` below for the
    undo, which a crash between the two writes would otherwise make
    necessary to reach for by hand.
    """
    if (event_id is None) != (start_utc is None):
        raise SeenEventsError(
            "--event-id and --start-utc travel together — pass both or "
            "neither"
        )
    outcome_entry = None
    if event_id is not None:
        # Normalized here too (not just inside _validate_outcome/record),
        # so the id this function's own return value and log lines carry
        # is already the same spelling unsettle_duplicate's guard will
        # look up later.
        outcome_entry = {"id": _normalize_event_id(event_id),
                         "start_utc": start_utc, "outcome": "skipped"}
        _validate_outcome(outcome_entry)  # raises before anything is written
    reason = f"same meeting already synced as {existing_id} ({stem})"
    recorded = syncjob.skip(root, recording_id, reason=reason)
    seen_events_recorded = False
    if outcome_entry is not None:
        if now_utc is None:
            now_utc = datetime.now(_timezone.utc).replace(
                tzinfo=None, microsecond=0)
        record(root, [outcome_entry], now_utc)
        seen_events_recorded = True
    return {"recording_id": recorded["recording_id"], "reason": reason,
            "already_present": recorded["already_present"],
            "seen_events_recorded": seen_events_recorded}


def unsettle_duplicate(root: Path, recording_id: str, *,
                       event_id: Optional[str] = None,
                       start_utc: Optional[str] = None) -> dict:
    """Reverse a `settle_duplicate` call — `sync unsettle-duplicate`, the
    undo a worker-settled cross-adapter duplicate needs.

    `sync unskip` alone is not enough for an M365 recording:
    `settle_duplicate` also wrote a seen-events `skipped` entry when
    `event_id`/`start_utc` were given, and that entry alone is what
    permanently filters the occurrence out of every future `sync
    m365-triage` — removing only the skip-list line would leave it
    unrecoverable. This removes the skip-list line (`syncjob.unskip`,
    which refuses an id not on the list) and, when `event_id`/`start_utc`
    are given, the seen-events entry too — tolerating a missing one (the
    occurrence may already have aged out of the cache's own 30-day
    retention) rather than raising, reported honestly as `forgot: false`.
    `event_id` and `start_utc` travel together, same as `settle_duplicate`.
    A plaud/inbox recording never carries them, on either side of the
    settle/unsettle pair.

    Unlike the generic `forget_event` (which deletes whatever is at that
    key regardless of outcome — its whole point, for the bulk operator
    workflow it serves), this function checks the cached entry's own
    `outcome` first and refuses to touch anything that is not `skipped`:
    mismatched `event_id`/`start_utc` (a typo, or an id belonging to a
    different occurrence than the one `settle_duplicate` actually cached)
    would otherwise silently drop some unrelated occurrence's `written`,
    `no-transcript`, or other settled entry. That case reports `forgot:
    false` with `reason: "outcome is <x>, not skipped"` — the skip-list
    line still comes off either way, since that part is unambiguous.
    """
    if (event_id is None) != (start_utc is None):
        raise SeenEventsError(
            "--event-id and --start-utc travel together — pass both or "
            "neither"
        )
    unskipped = syncjob.unskip(root, recording_id)
    forgot = False
    reason = None
    if event_id is not None:
        # Normalized the same way forget_event normalizes its own key —
        # otherwise an event_id with incidental whitespace would make this
        # guard look up (and find nothing at) a key forget_event would not
        # use, falling through to the unsafe default below.
        event_id_text = _normalize_event_id(event_id)
        try:
            key_start = _normalize_start(start_utc, "--start-utc")
        except M365Error as exc:
            raise SeenEventsError(str(exc)) from exc
        cache = load(root)
        cached = cache["events"].get(f"{event_id_text}|{key_start}")
        outcome = cached.get("outcome") if isinstance(cached, dict) else None
        if outcome is not None and outcome != "skipped":
            reason = f"outcome is {outcome}, not skipped"
        else:
            try:
                forget_event(root, event_id_text, start_utc)
                forgot = True
            except SeenEventsError:
                forgot = False
    return {"recording_id": unskipped["recording_id"], "removed": True,
            "forgot": forgot, "reason": reason}


FORGET_ALLOWED_OUTCOMES = ("no-access", "forbidden", "no-transcript")


def forget_event(root: Path, event_id: str, start_utc: str) -> dict:
    """Drop exactly one cached occurrence, regardless of its outcome — the
    targeted counterpart to the bulk `forget(outcome)` below.

    The undo for a triage-caught cross-adapter duplicate: `sync
    settle-duplicate` banks it as a plain `skipped` seen-events entry, which
    the bulk form refuses to touch (that refusal exists so a whole class of
    deliberate skips can't be undone by accident). This form names one
    occurrence, not a class, so it has no closed-vocabulary restriction —
    the caller already knows exactly what it is undoing. Refuses an
    id/start_utc pair not on the cache: an undo of something never recorded
    is far more likely a typo than a deliberate no-op.
    """
    event_id_text = _normalize_event_id(event_id)
    if not event_id_text:
        raise SeenEventsError("--event-id must not be empty")
    try:
        key_start = _normalize_start(start_utc, "--start-utc")
    except M365Error as exc:
        raise SeenEventsError(str(exc)) from exc
    cache = load(root)
    key = f"{event_id_text}|{key_start}"
    if key not in cache["events"]:
        raise SeenEventsError(
            f"no seen-events entry for event {event_id_text!r} at "
            f"{key_start!r} — nothing to forget"
        )
    del cache["events"][key]
    save(root, cache)
    return {"forgotten": 1, "remaining": len(cache["events"])}


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
