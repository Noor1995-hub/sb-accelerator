"""Microsoft 365 adapter: derive dedup ids from calendar event reads and
reassemble raw connector JSON into one capture-bundle blob.

Ids are computable from the event read alone, before the expensive
transcript fetch — so `sync dedup` gates that fetch exactly as it does for
Plaud. The event read itself is gated one stage earlier: seenevents.triage
answers, from the cheap calendar-search listing, which occurrences still
need it at all. Shapes are the lab-verified M365 connector responses;
anything else raises rather than guessing.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone as _timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from . import dates, winzones

URL_PREFIX = "meeting-transcript:///events/"
EVENT_URI_PREFIX = "calendar:///events/"
# A transcript on a recurring series' unscoped URL may belong to another
# occurrence; anything created outside the event window plus this pad is
# filtered out rather than filed under the wrong meeting.
OCCURRENCE_PAD_HOURS = 2

_CUE_RE = re.compile(
    r"\A(\d+):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})\.(\d{3})")
_VOICE_RE = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.DOTALL)
_TAG_RE = re.compile(r"</?[^>]+>")


class M365Error(Exception):
    """A malformed or failed M365 payload the caller must fix."""


def _load(path: Optional[str], label: str):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M365Error(f"{label} file {path!r} is unreadable: {exc}") from exc


def _parse_graph_dt(value, label: str) -> datetime:
    """Graph ISO datetime -> naive UTC. Graph emits 7-digit fractional
    seconds, which fromisoformat rejects; truncate to 6 before parsing."""
    parsed = _parse_graph_wall(value, label)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_graph_wall(value, label: str) -> datetime:
    """`_parse_graph_dt` without the UTC normalisation: naive when the text
    carries no offset, aware when it does (`Z` counts as one)."""
    text = str(value or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, _, frac = text.partition(".")
        tail = ""
        for i, ch in enumerate(frac):
            if not ch.isdigit():
                tail = frac[i:]
                frac = frac[:i]
                break
        text = f"{head}.{frac[:6]}{tail}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise M365Error(f"{label} {value!r} is not an ISO datetime") from exc
    return parsed


_UTC_NAMES = frozenset({"utc", "etc/utc", "gmt", "etc/gmt", "z"})
_WINDOWS_ZONES = {name.casefold(): iana
                  for name, iana in winzones.WINDOWS_TO_IANA.items()}


def _resolve_zone(name, label: str):
    """The tzinfo a Graph `timeZone` label names, or None for UTC itself.

    The calendar connector answers in the *mailbox's* own zone and only
    falls back to UTC when the mailbox has none — so a mailbox set to
    Brussels time answers `"Romance Standard Time"`, a Windows name
    zoneinfo cannot read, and every such event used to be refused. A
    Windows name goes through CLDR's mapping (`winzones`), anything else is
    tried as an IANA name. A label that resolves to neither is still
    refused: converting through a named zone is arithmetic, inventing one
    is a guess."""
    text = str(name).strip()
    if text.casefold() in _UTC_NAMES:
        return None
    iana = _WINDOWS_ZONES.get(text.casefold(), text)
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(iana)
    except Exception as exc:
        raise M365Error(
            f"{label} {name!r} is neither UTC, a Windows time zone name nor "
            f"an IANA name this host can resolve ({exc.__class__.__name__}) "
            "— refusing to guess the offset; a Windows host without a tz "
            "database needs `pip install tzdata`") from exc


def graph_dt_utc(node, label: str) -> datetime:
    """One Graph `{dateTime, timeZone}` pair -> naive UTC.

    The wall clock is read in the named zone and converted. A wall clock
    that occurs twice (the autumn DST hour) is read as its first
    occurrence (`fold=0`); only a meeting starting inside that one hour can
    land an hour off, and only in its local rendering's offset, never its
    date. A `dateTime` that already carries an offset wins over the label.
    """
    wall = _parse_graph_wall(node.get("dateTime"), f"{label}.dateTime")
    if wall.tzinfo is None:
        zone = _resolve_zone(node.get("timeZone") or "UTC", f"{label}.timeZone")
        if zone is None:
            return wall
        wall = wall.replace(tzinfo=zone)
    return wall.astimezone(_timezone.utc).replace(tzinfo=None)


def _event_start(event: dict) -> datetime:
    start = event.get("start") or {}
    if not start.get("dateTime"):
        raise M365Error("event is missing start.dateTime")
    return graph_dt_utc(start, "event start")


def _event_end(event: dict) -> Optional[datetime]:
    """Event end as a UTC datetime, or None with no end at all — the
    calendar-event span is optional throughout this module. When an end IS
    present, its timeZone is resolved exactly as `_event_start` resolves
    start's: an end in an unresolvable zone must be refused, not silently
    read as UTC, or a recurring series' window (`_transcript_window`) and
    duration fallbacks (`_event_span_ms`, `_event_duration_min`) would
    mis-scope by the offset."""
    end = event.get("end") or {}
    if not end.get("dateTime"):
        return None
    return graph_dt_utc(end, "event end")


def _canonical(event: dict) -> Tuple[str, str, str]:
    """(token, start-utc string, verbatim url) for one trimmed event read."""
    url = event.get("meetingTranscriptUrl")
    if not isinstance(url, str) or not url.startswith(URL_PREFIX):
        raise M365Error(
            f"meetingTranscriptUrl {url!r} does not start with {URL_PREFIX!r}")
    token = url[len(URL_PREFIX):].split("?", 1)[0].rstrip("/")
    if not token:
        raise M365Error(f"meetingTranscriptUrl {url!r} carries no token")
    start = _event_start(event)
    return token, start.strftime("%Y-%m-%dT%H:%M:%S"), url


def event_uri(event_id) -> str:
    """The `calendar:///events/<id>` URI for one listing entry's event id.

    This exists so that nothing above it ever *transforms* an event id.

    The calendar-search listing returns ids in Outlook's URL-safe base64
    variant, which is **not** RFC 4648 §5 base64url: measured against paired
    `uri`/`webLink` values from one mailbox, `-` stands in for `/` and `_`
    for `+` — the inverse of base64url's substitution. Do not "correct" that
    to the RFC's mapping; the substitution below is what the wire actually
    carries, and `webLink`'s `itemid` is where the un-substituted spelling
    (`%2F`, `%2B`) shows up.

    A caller that reverses that substitution and percent-encodes the result
    by hand turns every `-` into `%2F`. The connector then decodes it back
    to a raw `/` and splices it into the Graph request path unencoded, so
    Graph reads the tail as unknown path segments and answers 400
    `RequestBroker--ParseUri`. That cost two meetings a transcript on every
    run until someone read the run log.

    Percent-encoding with an empty safe set is the whole job: `-` and `_`
    are unreserved, so the substituted alphabet passes through untouched,
    while the padding `=` — plus a literal `/` or `+`, should an id ever
    arrive un-substituted — comes out encoded exactly once. `unquote` on the
    result returns the id byte for byte, which is the only property the
    connector cares about.
    """
    if not isinstance(event_id, str) or not event_id.strip():
        raise M365Error(
            f"event id {event_id!r} is empty or not a string — a URI cannot "
            "be derived from it")
    return f"{EVENT_URI_PREFIX}{quote(event_id, safe='')}"


def derive_id(event: dict) -> dict:
    """The m365: dedup id for one event occurrence.

    Hashes the transcript-URL token (query stripped — the connector may add
    or drop ?start/&end) plus the occurrence start, so the id is stable
    across runs and distinct per occurrence of a recurring series.
    """
    token, start_utc, url = _canonical(event)
    # A malformed `end` must never pass silently just because the caller
    # omitted --timezone/--utc-offset: `_event_end` is otherwise only
    # reached through `_event_duration_min`/`_event_span_ms`, both gated
    # behind those flags in `ids()` below — the probe's own `m365 ids`
    # call never passes either one. Called here, unconditionally, for
    # every id derivation regardless of the flags; the return value is
    # only useful for the duration fallbacks, which stay flag-gated.
    _event_end(event)
    digest = hashlib.sha256(f"{token}|{start_utc}".encode("utf-8")).hexdigest()
    return {
        "recording_id": f"m365:{digest[:16]}",
        "transcript_url": url,
        "start_utc": start_utc,
        "subject": event.get("subject") or None,
    }


def _recorded_local(event: dict, *, timezone: Optional[str] = None,
                    utc_offset: Optional[str] = None) -> str:
    """The owner-local recorded timestamp — factored out of `reassemble`,
    which both `meeting write` (`date`) and `sync collide` (`--start`) take
    verbatim (minute precision, no seconds — neither accepts more)."""
    start_utc = _event_start(event)
    local, _ = dates.utc_to_local(start_utc, timezone, utc_offset)
    return local.strftime("%Y-%m-%dT%H:%M")


def _event_span_ms(event: dict) -> Optional[float]:
    """The calendar event's own start/end span, in milliseconds, or None
    with no `end`. This is `reassemble`'s event-span fallback, factored out
    so `ids` can offer the same number before any transcript exists — at
    that stage there is no cue-derived duration to prefer over it."""
    end_dt = _event_end(event)
    if end_dt is None:
        return None
    start_utc = _event_start(event)
    return (end_dt - start_utc).total_seconds() * 1000


def _event_duration_min(event: dict) -> Optional[int]:
    """The calendar event's own start/end span, in whole minutes, or None
    with no `end` — via `dates.minutes_between`, the same round()-semantics
    helper `sync collide`'s occurrence duration uses, so the two never
    silently disagree by a minute at the boundary (both now feed the same
    `strong`-match threshold)."""
    end_dt = _event_end(event)
    if end_dt is None:
        return None
    start_utc = _event_start(event)
    return dates.minutes_between(start_utc, end_dt)


def load_listing(text: str) -> list:
    """The calendar-search listing as a flat list of objects, however the
    orchestrator wrote it to scratch.

    The connector answers a page as JSON objects back to back — not an
    array — with paging markers (`nextOffset`, `totalResultCount`) among
    them, and the skill says "write every page to one file". So this accepts
    a JSON array, an object wrapping one under `value`/`events`, or any
    concatenation of arrays and objects separated by nothing or whitespace.
    Markers pass through; `agenda` counts and drops them, so the caller sees
    that they were there rather than wondering whether an event vanished.
    """
    decoder = json.JSONDecoder()
    items: list = []
    pos = 0
    length = len(text)
    while True:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            break
        try:
            chunk, pos = decoder.raw_decode(text, pos)
        except json.JSONDecodeError as exc:
            raise M365Error(
                f"calendar listing is not JSON at offset {exc.pos}: {exc.msg}") from exc
        if isinstance(chunk, list):
            items.extend(chunk)
        elif isinstance(chunk, dict):
            wrapped = chunk.get("value", chunk.get("events"))
            if isinstance(wrapped, list) and "start" not in chunk:
                items.extend(wrapped)
            else:
                items.append(chunk)
        else:
            raise M365Error(
                f"calendar listing must hold event objects, got {type(chunk).__name__}")
    if not items and not text.strip():
        raise M365Error("calendar listing is empty — write the raw search results first")
    return items


_AGENDA_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def agenda(events, *, timezone: Optional[str] = None,
           utc_offset: Optional[str] = None, date: Optional[str] = None) -> dict:
    """The day's meetings from a calendar-search listing, filtered, sorted
    and rendered in the vault owner's local time — the deterministic half of
    /evening-sync Stage 5.

    The connector returns every `start`/`end` as a wall clock in the
    mailbox's own zone (`timeZone: "UTC"` on some mailboxes, a Windows name
    such as "Romance Standard Time" on others). When the heading time was
    left to the orchestrator to "render locally", one run copied the UTC
    clock straight into the daily note and every meeting showed two hours
    early. So `time` (owner-local `HH:MM`) is computed here: `graph_dt_utc`
    to UTC, then the same `dates.utc_to_local` the meeting notes use, and
    the skill carries it into the payload verbatim.

    All-day and cancelled entries are dropped and counted; so are paging
    markers (`load_listing` passes them through). With `date` (local
    `YYYY-MM-DD`) an event whose *local* start falls on another day is
    dropped too — the query window is built in UTC and can graze a
    neighbouring day at the edges. A listing in a zone that cannot be
    resolved is refused, exactly as `ids` refuses it: guessing an offset is
    how this bug happened.
    """
    if not isinstance(events, list):
        raise M365Error("--events must hold a JSON array of calendar-search results")
    if date is not None and not _AGENDA_DATE_RE.match(date):
        raise M365Error(f"--date {date!r} must be YYYY-MM-DD (the owner-local day)")
    dropped = {"all_day": 0, "cancelled": 0, "other_day": 0, "not_events": 0}
    keyed: List[Tuple[str, str, dict]] = []
    for event in events:
        if not isinstance(event, dict):
            raise M365Error(
                f"--events entries must be objects, got {type(event).__name__}")
        if not (event.get("start") or {}).get("dateTime"):
            dropped["not_events"] += 1
            continue
        if event.get("isCancelled"):
            dropped["cancelled"] += 1
            continue
        if event.get("isAllDay"):
            dropped["all_day"] += 1
            continue
        start_utc = _event_start(event)
        local, _ = dates.utc_to_local(start_utc, timezone, utc_offset)
        if date is not None and local.strftime("%Y-%m-%d") != date:
            dropped["other_day"] += 1
            continue
        end_utc = _event_end(event)
        end_local = None
        if end_utc is not None:
            end_local = dates.utc_to_local(end_utc, timezone, utc_offset)[0].strftime("%H:%M")
        attendees = event.get("attendees")
        subject = str(event.get("subject") or "").strip()
        entry = {
            "time": local.strftime("%H:%M"),
            "end": end_local,
            "subject": subject,
            "start_utc": start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
            "start_local": local.strftime("%Y-%m-%dT%H:%M"),
            "organizer": event.get("organizer"),
            "attendees": list(attendees) if isinstance(attendees, list) else [],
            "location": event.get("location"),
            "show_as": event.get("showAs"),
            "is_organizer": event.get("isOrganizer"),
            "id": event.get("id"),
            "uri": event.get("uri"),
        }
        keyed.append((entry["start_utc"], subject.casefold(), entry))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return {"date": date, "meetings": [item[2] for item in keyed], "dropped": dropped}


# A recording's start and its calendar event's start agree to within this many
# minutes when the owner pressed record at the top of the meeting. Plaud and
# a human both run a few minutes either side of the scheduled clock.
START_MATCH_MINUTES = 5


def calendar_match(events, *, start_local: str, duration_min: int = 0,
                   timezone: Optional[str] = None,
                   utc_offset: Optional[str] = None,
                   address_book: Optional[dict] = None) -> dict:
    """The time-only calendar match for one recording: the deterministic
    half of /sync-recordings step 2.

    Title keywords and attendee names are the model's judgment, and a
    recording whose auto-title shares no word with its event and whose
    speakers are `Speaker 2` / `Speaker 4` gives that judgment nothing to
    hold (2026-10-09: an 11:01 call against an 11:00 weekly was stamped
    `no-calendar-match`). When the clock alone is unambiguous it is enough.

    The slot is every live event (not cancelled, not all-day) that overlaps
    the recording's own span. Exactly one, starting within
    `START_MATCH_MINUTES` of the recording start (either side), is a
    `single` match. Two or more is `ambiguous` — never auto-matched on time,
    the caller keeps its keyword/attendee scoring. None is `none`. A single
    overlapping event that starts further away than the tolerance is also
    `none`: a bare overlap says someone was in a meeting, not which one.

    The listing carries attendees as bare addresses, so a match also returns
    `known_attendees` — the person slugs whose note already holds one of
    those addresses (`address_book`: lowercased email -> slug) — and
    `unknown_attendee_emails` for the rest, which the caller cannot turn
    into a person note without a name it does not have.
    """
    if not isinstance(events, list):
        raise M365Error("--events must hold a JSON array of calendar-search results")
    if duration_min < 0:
        raise M365Error("--duration-min must be >= 0")
    try:
        local, had_time = dates._parse_local(start_local)
        offset_minutes, _ = dates.resolve_offset_minutes(local, timezone, utc_offset)
    except dates.DatesError as exc:
        raise M365Error(str(exc)) from exc
    if not had_time:
        raise M365Error("--start must carry a time (YYYY-MM-DDTHH:MM)")
    rec_start = local - timedelta(minutes=offset_minutes)
    rec_end = rec_start + timedelta(minutes=duration_min)
    tolerance = timedelta(minutes=START_MATCH_MINUTES)
    slot = []
    for event in events:
        if not isinstance(event, dict):
            raise M365Error(
                f"--events entries must be objects, got {type(event).__name__}")
        if not (event.get("start") or {}).get("dateTime"):
            continue
        if event.get("isCancelled") or event.get("isAllDay"):
            continue
        ev_start = _event_start(event)
        ev_end = _event_end(event) or ev_start
        # Overlap, with the tolerance letting a recording that began a hair
        # before a meeting (or after it ended) still count as in its slot.
        if ev_start < rec_end + tolerance and ev_end > rec_start - tolerance:
            slot.append((ev_start, event))
    slot.sort(key=lambda item: item[0])
    result = {"slot_size": len(slot), "tolerance_min": START_MATCH_MINUTES}
    if len(slot) == 1 and abs(slot[0][0] - rec_start) <= tolerance:
        ev_start, event = slot[0]
        local_ev, _ = dates.utc_to_local(ev_start, timezone, utc_offset)
        book = address_book or {}
        known, unknown = [], []
        for attendee in event.get("attendees") or []:
            address = str(attendee.get("address") if isinstance(attendee, dict)
                          else attendee or "").strip().casefold()
            if "@" not in address:
                continue
            slug = book.get(address)
            if slug and slug not in known:
                known.append(slug)
            elif not slug and address not in unknown:
                unknown.append(address)
        result.update(match="single", known_attendees=known,
                      unknown_attendee_emails=unknown, event={
            "subject": str(event.get("subject") or "").strip(),
            "organizer": event.get("organizer"),
            "location": event.get("location"),
            "attendees": (list(event["attendees"])
                          if isinstance(event.get("attendees"), list) else []),
            "recurring": bool(event.get("recurrence")),
            "start_local": local_ev.strftime("%Y-%m-%dT%H:%M"),
            "start_offset_min": round((ev_start - rec_start).total_seconds() / 60),
            "id": event.get("id"),
            "uri": event.get("uri"),
        })
        return result
    result["match"] = "ambiguous" if len(slot) > 1 else "none"
    return result


def ids(events, *, timezone: Optional[str] = None,
       utc_offset: Optional[str] = None) -> dict:
    """Batch id derivation over event reads (the trimmed event file — id,
    subject, start, end, meetingTranscriptUrl, organizer, attendees —
    verbatim), before any transcript fetch. No transcript URL is the
    normal case, never an error.

    `timezone`/`utc_offset` are optional and travel together with the same
    "exactly one" rule as everywhere else in this CLI; omitted entirely, a
    derived entry carries only what it always has (id-only callers, and the
    worker contract's pre-#213 invocation, see no shape change at all).
    Supplied, each transcript-bearing entry also gains `recorded_local` (for
    `sync collide --start` and `meeting write`'s `date`) and
    `event_duration_min` (for `sync collide --duration-min`) — the latter
    only when the event carries an `end`. An unresolvable `end.timeZone` is
    refused unconditionally, via `derive_id`, whether or not `timezone`/
    `utc_offset` are supplied — validation must not depend on an optional
    flag a caller (the probe, in particular) may never pass.
    """
    if not isinstance(events, list):
        raise M365Error("--events must be a JSON array of event reads")
    derived: List[dict] = []
    skipped: List[dict] = []
    for event in events:
        if not isinstance(event, dict):
            raise M365Error(
                f"--events entries must be event objects, got {type(event).__name__}")
        if not event.get("meetingTranscriptUrl"):
            skipped.append({"subject": event.get("subject") or None,
                            "reason": "no-transcript-url"})
            continue
        entry = derive_id(event)
        if timezone is not None or utc_offset is not None:
            entry["recorded_local"] = _recorded_local(
                event, timezone=timezone, utc_offset=utc_offset)
            duration_min = _event_duration_min(event)
            if duration_min is not None:
                entry["event_duration_min"] = duration_min
        derived.append(entry)
    return {"ids": derived, "skipped": skipped}


def _cue_end_ms(match: "re.Match") -> int:
    h, m, s, ms = (int(match.group(i)) for i in (5, 6, 7, 8))
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def _parse_vtt(content: str, transcript_id: str) -> Tuple[List[Tuple[Optional[str], str]], int]:
    """[(speaker-or-None, text)] in file order, plus max cue end in ms.

    Handles both formats the connector can return: unattributed cue text
    (today's tenant reality) and attributed `<v Name>` cues (once the tenant
    enables speaker attribution). Rolling-caption repeats collapse; order is
    never sorted — Teams cue windows overlap legitimately.
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    cues: List[Tuple[Optional[str], str]] = []
    max_end_ms = 0
    for block in re.split(r"\n\s*\n", text):
        lines = [line for line in block.split("\n") if line.strip()]
        timing_at = next((i for i, line in enumerate(lines)
                          if _CUE_RE.match(line.strip())), None)
        if timing_at is None:
            continue  # WEBVTT header, NOTE blocks, stray prose
        match = _CUE_RE.match(lines[timing_at].strip())
        max_end_ms = max(max_end_ms, _cue_end_ms(match))
        payload = " ".join(line.strip() for line in lines[timing_at + 1:])
        if not payload:
            continue
        voiced = _VOICE_RE.findall(payload)
        parts = ([(speaker.strip(), part.strip()) for speaker, part in voiced]
                 if voiced else [(None, _TAG_RE.sub("", payload).strip())])
        for speaker, part in parts:
            if not part:
                continue
            if cues and cues[-1] == (speaker, part):
                continue
            cues.append((speaker, part))
    if not cues:
        raise M365Error(f"transcript {transcript_id} content has no VTT cues")
    return cues, max_end_ms


def _transcript_window(event: dict) -> Optional[Tuple[datetime, datetime]]:
    end_dt = _event_end(event)
    if end_dt is None:
        return None
    pad = timedelta(hours=OCCURRENCE_PAD_HOURS)
    start = _event_start(event)
    return start - pad, end_dt + pad


def reassemble(event_path: str, transcript_path: str, out_dir: str, *,
               timezone: Optional[str] = None,
               utc_offset: Optional[str] = None) -> dict:
    event = _load(event_path, "event")
    if not isinstance(event, dict):
        raise M365Error("event must be a JSON object")
    if not event.get("meetingTranscriptUrl"):
        raise M365Error(
            "event is missing meetingTranscriptUrl — reassemble needs the "
            "event's kept keys (id, subject, start, end, "
            "meetingTranscriptUrl, organizer, attendees), not a bare "
            "listing entry")
    if not (event.get("start") or {}).get("dateTime"):
        raise M365Error("event is missing start.dateTime")
    payload = _load(transcript_path, "transcript")
    transcripts = payload.get("transcripts") if isinstance(payload, dict) else None
    if not isinstance(transcripts, list) or not transcripts:
        raise M365Error("transcript payload has no transcripts — a "
                        "transcripts_empty result is a skip line, not a "
                        "reassemble input")

    derived = derive_id(event)
    # Both consumers of this value parse it verbatim — `meeting write`
    # (date) and `sync collide` (--start) — and neither accepts seconds
    # or a space separator. Widening the format here costs every
    # recording a rejection round trip.
    recorded_local = _recorded_local(event, timezone=timezone,
                                     utc_offset=utc_offset)

    entries = []
    for entry in transcripts:
        if not isinstance(entry, dict) or not entry.get("content"):
            raise M365Error("each transcript entry needs id and content")
        entries.append((_parse_graph_dt(entry.get("createdDateTime"),
                                        "transcript createdDateTime"), entry))
    entries.sort(key=lambda pair: pair[0])
    window = _transcript_window(event)
    if window is not None and len(entries) > 1:
        lo, hi = window
        entries = [pair for pair in entries if lo <= pair[0] <= hi]
        if not entries:
            raise M365Error("no transcript overlaps this event occurrence — "
                            "the URL likely covers other occurrences of the "
                            "series")

    bodies = []
    max_end_ms = 0
    for _, entry in entries:
        cues, end_ms = _parse_vtt(str(entry["content"]),
                                  str(entry.get("id") or "?"))
        max_end_ms += end_ms
        bodies.append("\n".join(
            f"{speaker}: {text}" if speaker else text for speaker, text in cues))

    duration_ms = max_end_ms
    if not duration_ms:
        spans = []
        for created, entry in entries:
            end = entry.get("endDateTime")
            if end:
                spans.append((_parse_graph_dt(end, "transcript endDateTime")
                              - created).total_seconds() * 1000)
        duration_ms = int(sum(spans))
    if not duration_ms:
        span_ms = _event_span_ms(event)
        if span_ms is not None:
            duration_ms = int(span_ms)

    title = event.get("subject") or "Untitled meeting"
    parts = [title, "", f"> Recorded: {recorded_local}", "", "#Transcript",
             "\n\n".join(bodies)]
    blob = "\n".join(parts) + "\n"

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = derived["recording_id"].split(":", 1)[1]
    blob_path = out / f"{stem}.blob.md"
    blob_path.write_text(blob, encoding="utf-8", newline="\n")

    return {
        "recording_id": derived["recording_id"],
        "duration_min": round(max(duration_ms, 0) / 60000),
        "recorded_local": recorded_local,
        "has_enrichment": False,
        "blob_path": str(blob_path),
        # A long meeting's blob outgrows one Read call; the worker pages
        # through it by line count instead of guessing where it ends.
        "blob_lines": blob.count("\n"),
        "blob_chars": len(blob),
    }


# --- capture: a transcript read the host spilled to a tool-results file -----
#
# A transcript read over the host's tool-result cap comes back as an error
# notice naming the file the host saved it to, not as content (live
# reproduction 2026-10-01: a 104,221-character, 72-minute transcript; the
# cap sits somewhere below that). Re-typing ~100k characters through a
# model's output is neither verbatim nor possible within one reply, so the
# CLI copies the bytes instead. Cowork names the file by its Windows host
# path; the sandbox's Bash sees the same file under
# /sessions/<name>/mnt/.claude/projects/..., one session-id level below
# projects/ — so the path in the notice is a hint, resolved here.

SPILL_DIR = "tool-results"
# Cues ending before this share of the event span are worth a look: a
# meeting that ended early is normal (72 of 90 minutes, live), a transcript
# covering under half its slot is rare enough to say so.
COVERAGE_WARN_RATIO = 0.5


def spill_roots() -> List[Path]:
    """Where a host keeps tool-results files, most specific first."""
    roots = []
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        roots.append(Path(config_dir) / "projects")
    roots.append(Path.home() / ".claude" / "projects")
    roots.extend(Path(p) for p in sorted(glob.glob("/sessions/*/mnt/.claude/projects")))
    return roots


def _resolve_spill(source: str, roots: List[Path]) -> Path:
    parts = [p for p in re.split(r"[\\/]+", source) if p]
    if not parts:
        raise M365Error("capture needs the path the host's notice named")
    name = parts[-1]
    literal = Path(source)
    found: List[Path] = []
    if literal.is_file():
        found.append(literal)
    else:
        # The notice's path below projects/ survives the host-to-sandbox
        # mapping; only the prefix differs.
        if "projects" in parts:
            at = len(parts) - 1 - parts[::-1].index("projects")
            for root in roots:
                candidate = root.joinpath(*parts[at + 1:])
                if candidate.is_file():
                    found.append(candidate)
        if not found:
            for root in roots:
                if root.is_dir():
                    found.extend(p for p in root.rglob(name)
                                 if p.parent.name == SPILL_DIR and p.is_file())
    unique = sorted({p.resolve() for p in found})
    if not unique:
        raise M365Error(
            f"spilled transcript {name!r} is not reachable from this shell "
            f"(looked under: {', '.join(str(r) for r in roots) or 'no roots'})")
    if len(unique) > 1:
        raise M365Error(f"spilled transcript {name!r} matches {len(unique)} files")
    path = unique[0]
    if path.parent.name != SPILL_DIR:
        raise M365Error(
            f"{str(path)!r} is not a host {SPILL_DIR} file — capture only "
            f"copies a spilled tool result")
    return path


def _fmt_ms(ms: int) -> str:
    s = max(int(ms), 0) // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def capture(source: str, out_path: str, *, event_path: Optional[str] = None,
            roots: Optional[List[Path]] = None) -> dict:
    """Copy a spilled transcript read to scratch, byte for byte (a leading
    BOM aside), after proving it is one complete transcript read. Returns
    counts only — never content."""
    path = _resolve_spill(source, spill_roots() if roots is None else list(roots))
    raw = path.read_bytes()
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M365Error(
            f"spilled file is not a complete transcript read (invalid JSON: "
            f"{exc}) — a cut-off read must not become a meeting note") from exc
    transcripts = payload.get("transcripts") if isinstance(payload, dict) else None
    if not isinstance(transcripts, list) or not transcripts:
        raise M365Error("spilled file carries no transcripts — not a "
                        "transcript read")
    cues = 0
    last_ms = 0
    for entry in transcripts:
        if not isinstance(entry, dict) or not entry.get("content"):
            raise M365Error("each transcript entry needs id and content")
        content = str(entry["content"])
        _, end_ms = _parse_vtt(content, str(entry.get("id") or "?"))
        cues += sum(1 for line in content.splitlines()
                    if _CUE_RE.match(line.strip()))
        last_ms = max(last_ms, end_ms)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)

    result = {
        "source_path": str(path),
        "transcript_path": str(out),
        "bytes": len(raw),
        "transcripts": len(transcripts),
        "cues": cues,
        "last_cue": _fmt_ms(last_ms),
    }
    if event_path is not None:
        event = _load(event_path, "event")
        span_ms = _event_span_ms(event) if isinstance(event, dict) else None
        # A recurring series' read can carry several occurrences; coverage
        # of one event is only meaningful for a single transcript.
        if span_ms and len(transcripts) == 1 and last_ms < span_ms * COVERAGE_WARN_RATIO:
            result["warnings"] = [
                f"transcript cues end at {_fmt_ms(last_ms)} of a "
                f"{round(span_ms / 60000)}-minute event — check the "
                f"transcript is complete"]
    return result
