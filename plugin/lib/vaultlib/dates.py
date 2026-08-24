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
         utc_offset: Optional[str] = None) -> dict:
    """The authoritative date block for the evening run.

    Everything downstream consumes these values verbatim — the model never
    derives day-of-week or offsets from an ISO date. The recap window is
    design decision 9: everything since the last daily note on disk
    (inclusive), through today. A note dated in the future (tomorrow's,
    written by an earlier run today) is not "the last daily note".
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
    return {
        "today": today_date.isoformat(),
        "today_day_name": DAY_NAMES[today_date.weekday()],
        "next_business_day": nxt.isoformat(),
        "next_day_name": DAY_NAMES[nxt.weekday()],
        "note_to_write": f"{DAILY_NOTES_DIR}/{nxt.isoformat()}.md",
        "last_daily_note": (f"{DAILY_NOTES_DIR}/{last.isoformat()}.md"
                            if last else None),
        "recap_from": (last or today_date).isoformat(),
        "recap_to": today_date.isoformat(),
    }
