"""UTC window computation for calendar queries.

The executive's timezone is prose in the context portfolio; the model reads
it and passes an IANA name (or, where the host has no tz database, an
explicit offset). Nothing here hardcodes a region — the lab's CET/CEST
arithmetic deliberately did not port.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone as _timezone
from pathlib import Path
from typing import Optional, Tuple

from . import vault

_OFFSET_RE = re.compile(r"\A([+-])(\d{2}):(\d{2})\Z")
_DATETIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?\Z")
_UTC_FMT = "%Y-%m-%dT%H:%M:%S"


class DatesError(Exception):
    """A date, timezone, or offset argument the caller must fix."""


def _parse_offset_minutes(text: str) -> int:
    match = _OFFSET_RE.match(text.strip())
    if not match:
        raise DatesError(
            f"utc-offset {text!r} must look like +02:00 or -05:30"
        )
    sign = 1 if match.group(1) == "+" else -1
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59:
        raise DatesError(f"utc-offset {text!r} is out of range")
    return sign * (hours * 60 + minutes)


def _parse_local(start_local: str) -> Tuple[datetime, bool]:
    """Return (datetime, had_time). Date-only input means a whole-day window."""
    text = str(start_local).strip()
    if not _DATETIME_RE.match(text):
        raise DatesError(
            f"start {start_local!r} must be ISO YYYY-MM-DD or YYYY-MM-DDTHH:MM"
        )
    if "T" in text:
        fmt = _UTC_FMT if text.count(":") == 2 else "%Y-%m-%dT%H:%M"
        return datetime.strptime(text, fmt), True
    return datetime.strptime(text, "%Y-%m-%d"), False


def resolve_offset_minutes(local_dt: datetime, timezone: Optional[str],
                           utc_offset: Optional[str]) -> Tuple[int, str]:
    """The UTC offset in force at local_dt, and where it came from.

    zoneinfo handles DST correctly but needs a tz database, which a Windows
    host may not have — hence the explicit-offset escape hatch.
    """
    if (timezone is None) == (utc_offset is None):
        raise DatesError(
            "pass exactly one of --timezone (IANA name, e.g. America/Chicago) "
            "or --utc-offset (e.g. -05:00)"
        )
    if utc_offset is not None:
        return _parse_offset_minutes(utc_offset), "explicit"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
    except Exception as exc:
        raise DatesError(
            f"timezone {timezone!r} could not be resolved on this host "
            f"({exc.__class__.__name__}) — check the IANA name, or pass "
            "--utc-offset (e.g. -05:00) instead"
        ) from exc
    delta = local_dt.replace(tzinfo=tz).utcoffset()
    return int(delta.total_seconds() // 60), "zoneinfo"


def _format_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def window(start_local: str, *, timezone: Optional[str] = None,
           utc_offset: Optional[str] = None, hours: float = 2.0) -> dict:
    """A UTC [from, to] window around a local timestamp.

    With a time component: ±hours around it. Date-only: that whole local day
    (00:00:00–23:59:59), still widened by ±hours.
    """
    if hours < 0:
        raise DatesError(f"hours {hours!r} must be >= 0")
    local, had_time = _parse_local(start_local)
    offset_minutes, source = resolve_offset_minutes(local, timezone, utc_offset)
    pad = timedelta(hours=float(hours))
    if had_time:
        lo, hi = local - pad, local + pad
    else:
        lo = local - pad
        hi = local + timedelta(hours=23, minutes=59, seconds=59) + pad
    shift = timedelta(minutes=offset_minutes)
    return {
        "start_local": str(start_local).strip(),
        "utc_from": (lo - shift).strftime(_UTC_FMT),
        "utc_to": (hi - shift).strftime(_UTC_FMT),
        "offset": _format_offset(offset_minutes),
        "offset_source": source,
    }


DAILY_NOTES_DIR = vault.DAILY_NOTES_DIR

# Explicit and English on purpose: %A is locale-dependent, and the whole point
# of this module is that the model never derives day-of-week itself.
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")

# weekday(): Mon=0 … Sun=6. Fri -> Mon (+3), Sat -> Mon (+2), Sun -> Mon (+1).
_NEXT_BUSINESS_DAYS = {4: 3, 5: 2, 6: 1}


def business_days(start: date, end: date) -> int:
    """Mon-Fri days in the half-open interval [start, end).

    Half-open on purpose: with start = the last daily note's date and
    end = today, the count is exactly the number of evening runs that did
    not happen. A note dated `start` on disk proves the run on the evening
    before it completed, so `start` itself is not a missed day.

    No holiday calendar: a public holiday counts as missed, which is
    literally true ("no run happened") and is the honest reading rather
    than a silent one.
    """
    if end <= start:
        return 0
    # Whole weeks contribute 5 each; walk only the remainder. A 6-month gap
    # must not become a 180-iteration loop on the client's machine.
    whole_weeks, remainder = divmod((end - start).days, 7)
    count = whole_weeks * 5
    for offset in range(remainder):
        if (start + timedelta(days=offset)).weekday() < 5:
            count += 1
    return count


def _walk_back_business_days(end: date, count: int) -> date:
    """The date `count` business days back from `end`, counting `end` itself.

    A weekend `end` contributes nothing, so the walk simply continues into
    the previous week.
    """
    remaining = max(count, 1)
    cursor = end
    while True:
        if cursor.weekday() < 5:
            remaining -= 1
            if remaining == 0:
                return cursor
        cursor -= timedelta(days=1)


def _parse_date(text, label: str) -> date:
    raw = str(text).strip()
    if not vault.ISO_DATE_RE.match(raw):
        raise DatesError(f"{label} {text!r} must be ISO YYYY-MM-DD")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise DatesError(f"{label} {text!r} is not a real date") from exc


def utc_to_local(utc_dt: datetime, timezone: Optional[str],
                 utc_offset: Optional[str]) -> Tuple[datetime, str]:
    """A naive UTC datetime rendered in the executive's local time.

    The zoneinfo path converts properly (attach UTC, astimezone) rather than
    asking what offset is in force at the UTC value read as wall time — those
    differ inside the DST transition window, which is exactly the recorded_local
    bug this fixes.
    """
    if (timezone is None) == (utc_offset is None):
        raise DatesError(
            "pass exactly one of --timezone (IANA name, e.g. Europe/Brussels) "
            "or --utc-offset (e.g. +02:00)"
        )
    if utc_offset is not None:
        return utc_dt + timedelta(minutes=_parse_offset_minutes(utc_offset)), "explicit"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
    except Exception as exc:
        raise DatesError(
            f"timezone {timezone!r} could not be resolved on this host "
            f"({exc.__class__.__name__}) — check the IANA name, or pass "
            "--utc-offset (e.g. +02:00) instead"
        ) from exc
    local = utc_dt.replace(tzinfo=_timezone.utc).astimezone(tz)
    return local.replace(tzinfo=None), "zoneinfo"


def plan(root: Path, today: Optional[str] = None, *,
         timezone: Optional[str] = None,
         utc_offset: Optional[str] = None,
         catchup_threshold: int = 5) -> dict:
    """The authoritative date block for the evening run.

    Everything downstream consumes these values verbatim — the model never
    derives day-of-week or offsets from an ISO date. The recap window is
    design decision 9: everything since the last daily note on disk
    (inclusive), through today. A note dated in the future (tomorrow's,
    written by an earlier run today) is not "the last daily note".

    A gap is reported, not inferred (decision 15): business_days_missed is
    the count of business days in [recap_from, recap_to), which is exactly
    the set of evening runs that did not happen. Above catchup_threshold,
    recap_detail_from bounds how far back the caller should recap in detail
    (decision 17) — the caller does no arithmetic, only prose.
    """
    if today is not None:
        today_date = _parse_date(today, "today")
    else:
        if timezone is None and utc_offset is None:
            raise DatesError(
                "pass --today, or --timezone/--utc-offset so today can be "
                "derived from the clock"
            )
        now_utc = datetime.now(_timezone.utc).replace(tzinfo=None, microsecond=0)
        local_now, _ = utc_to_local(now_utc, timezone, utc_offset)
        today_date = local_now.date()

    if not isinstance(catchup_threshold, int) or isinstance(catchup_threshold, bool):
        raise DatesError("catchup-threshold must be an integer")
    if catchup_threshold < 0:
        raise DatesError(
            f"catchup-threshold {catchup_threshold} must be >= 0")

    notes_dir = root / DAILY_NOTES_DIR
    existing = []
    for path in sorted(notes_dir.glob("*.md")) if notes_dir.is_dir() else []:
        if not vault.ISO_DATE_RE.match(path.stem):
            continue
        try:
            noted = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if noted <= today_date:
            existing.append(noted)
    last = max(existing) if existing else None

    nxt = today_date + timedelta(
        days=_NEXT_BUSINESS_DAYS.get(today_date.weekday(), 1))
    recap_from = last or today_date
    missed = business_days(recap_from, today_date)
    over_threshold = missed > catchup_threshold
    detail_from = (max(recap_from,
                       _walk_back_business_days(today_date, catchup_threshold))
                   if over_threshold else recap_from)
    return {
        "today": today_date.isoformat(),
        "today_day_name": DAY_NAMES[today_date.weekday()],
        "next_business_day": nxt.isoformat(),
        "next_day_name": DAY_NAMES[nxt.weekday()],
        "note_to_write": f"{DAILY_NOTES_DIR}/{nxt.isoformat()}.md",
        "last_daily_note": (f"{DAILY_NOTES_DIR}/{last.isoformat()}.md"
                            if last else None),
        "recap_from": recap_from.isoformat(),
        "recap_to": today_date.isoformat(),
        "business_days_missed": missed,
        "is_catchup": missed > 0,
        "catchup_threshold": catchup_threshold,
        "over_threshold": over_threshold,
        "recap_detail_from": detail_from.isoformat(),
        "business_days_not_detailed": business_days(recap_from, detail_from),
    }
