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

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone as _timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from . import dates

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
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M365Error(f"{label} file {path!r} is unreadable: {exc}") from exc


def _parse_graph_dt(value, label: str) -> datetime:
    """Graph ISO datetime -> naive UTC. Graph emits 7-digit fractional
    seconds, which fromisoformat rejects; truncate to 6 before parsing."""
    text = str(value or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1]
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
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_timezone.utc).replace(tzinfo=None)
    return parsed


def _event_start(event: dict) -> datetime:
    start = event.get("start") or {}
    tz = start.get("timeZone")
    if tz is not None and str(tz).casefold() != "utc":
        raise M365Error(
            f"event start.timeZone {tz!r} is not UTC — refusing to guess the offset")
    return _parse_graph_dt(start.get("dateTime"), "event start.dateTime")


def _canonical(event: dict) -> Tuple[str, str, str]:
    """(token, start-utc string, verbatim url) for one full event read."""
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
    end = (event.get("end") or {}).get("dateTime")
    if not end:
        return None
    start_utc = _event_start(event)
    return (_parse_graph_dt(end, "event end.dateTime")
            - start_utc).total_seconds() * 1000


def _event_duration_min(event: dict) -> Optional[int]:
    """The calendar event's own start/end span, in whole minutes, or None
    with no `end` — via `dates.minutes_between`, the same round()-semantics
    helper `sync collide`'s occurrence duration uses, so the two never
    silently disagree by a minute at the boundary (both now feed the same
    `strong`-match threshold)."""
    end = (event.get("end") or {}).get("dateTime")
    if not end:
        return None
    start_utc = _event_start(event)
    return dates.minutes_between(
        start_utc, _parse_graph_dt(end, "event end.dateTime"))


def ids(events, *, timezone: Optional[str] = None,
       utc_offset: Optional[str] = None) -> dict:
    """Batch id derivation over full event reads, before any transcript
    fetch. No transcript URL is the normal case, never an error.

    `timezone`/`utc_offset` are optional and travel together with the same
    "exactly one" rule as everywhere else in this CLI; omitted entirely, a
    derived entry carries only what it always has (id-only callers, and the
    worker contract's pre-#213 invocation, see no shape change at all).
    Supplied, each transcript-bearing entry also gains `recorded_local` (for
    `sync collide --start` and `meeting write`'s `date`) and
    `event_duration_min` (for `sync collide --duration-min`) — the latter
    only when the event carries an `end`.
    """
    if not isinstance(events, list):
        raise M365Error("--events must be a JSON array of full event reads")
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
    end = (event.get("end") or {}).get("dateTime")
    if not end:
        return None
    pad = timedelta(hours=OCCURRENCE_PAD_HOURS)
    start = _event_start(event)
    return start - pad, _parse_graph_dt(end, "event end.dateTime") + pad


def reassemble(event_path: str, transcript_path: str, out_dir: str, *,
               timezone: Optional[str] = None,
               utc_offset: Optional[str] = None) -> dict:
    event = _load(event_path, "event")
    if not isinstance(event, dict) or not (event.get("start") or {}).get("dateTime") \
            or not event.get("meetingTranscriptUrl"):
        raise M365Error("event must be the full calendar event read: "
                        "start.dateTime and meetingTranscriptUrl are required")
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
    }
