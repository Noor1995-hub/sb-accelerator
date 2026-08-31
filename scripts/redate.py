"""Re-date the demo fixture overlay AFTER it's copied into a fresh test vault,
so vaultlib.dates.plan()'s recap window works regardless of what day
make_test_vault.py is run. Only ever touches the target vault passed in —
fixtures/demo-vault/ itself is never opened for writing.

Two clusters, two strategies:

Cluster A (everything except 10-inbox/) shifts by one uniform, weekday-
aligned delta — always a multiple of 7 days — so every weekday-name string
already baked into the fixture prose (`# 2026-06-15 · Monday`, "1 meeting
Friday", `as of 12-06-26`) stays correct with zero text regeneration.

Cluster B (the 5 inbox files) cannot use a single delta: the Wed..Mon span
of their original dates crosses a weekend past the recap window for some
demo days, so each file is placed individually (`plan_inbox_dates`). One of
the five — WEEKDAY_LOCKED_INBOX_SLUG — has dialogue that derives weekday
names from its own date ("I'll send an invite for Thursday or Friday",
"you're there Friday") and cannot be rewritten mechanically; it is kept on
its original weekday instead.

Accepted, documented trade-off: when demo_day is a Monday or Tuesday, the
recap window is too short to contain a Wednesday, so the weekday-locked file
lands 1-2 days *after* demo_day (one file, 2 of the 7 possible weekdays) —
the alternative is breaking its Thursday/Friday dialogue, which is worse.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple, Optional

_LIB_DIR = Path(__file__).resolve().parents[1] / "plugin" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from vaultlib import dates as vaultlib_dates          # noqa: E402
from vaultlib import vault                            # noqa: E402
from vaultlib.meeting import _date_prefix, date_from_stem  # noqa: E402


class RedateError(Exception):
    """A fixture-tree shape or self-check failure the caller must fix."""


# The one inbox file whose dialogue derives weekday names from its own date
# and so cannot be rewritten mechanically like the other four.
WEEKDAY_LOCKED_INBOX_SLUG = "teams-transcript-nordbridge-checkin"

INBOX_DIR = vault.INBOX_DIR
DAILY_NOTES_DIR = vault.DAILY_NOTES_DIR

_ISO_TOKEN_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})(T\d{2}:\d{2}(?::\d{2})?)?')
_DDMMYY_TOKEN_RE = re.compile(r'(?<!\d)(\d{2})-(\d{2})-(\d{2})(?!\d)')
_LABELED_DATE_LINE_RE = re.compile(
    r'^(?P<prefix>>?\s*(?:Date|Recorded):\s*)(?P<date>\d{4}-\d{2}-\d{2})', re.MULTILINE)
_RFC2822_RE = re.compile(
    r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} '
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}')

# Stem shapes that carry a rename-worthy date: meeting notes are
# DD-MM-YY-<slug> (meeting.py's _date_prefix); decision notes and daily
# notes are YYYY-MM-DD(-<slug>-<status>)? — an ISO prefix, bare or not.
_MEETING_STEM_RE = re.compile(r'\A\d{2}-\d{2}-\d{2}(?=-|\Z)')
_ISO_STEM_RE = re.compile(r'\A\d{4}-\d{2}-\d{2}(?=-|\Z)')
_INBOX_STEM_RE = re.compile(r'\A(\d{4})-(\d{2})-(\d{2})-(.+)\Z')

_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class RedatePlan(NamedTuple):
    anchor: date
    shift_a_days: int
    recap_from: date
    inbox_dates: dict  # old filename stem -> new date


# --------------------------------------------------------------------------
# Cluster A: discovery + the uniform weekday-aligned shift
# --------------------------------------------------------------------------

def discover_anchor(target: Path) -> date:
    """The latest ISO-named daily note on disk — never hardcoded.

    That note anchors the whole re-dating: cluster A's shift is chosen so
    this exact date lands on `recap_from_target` (see
    `weekday_aligned_shift`).
    """
    notes_dir = target / DAILY_NOTES_DIR
    found = []
    if notes_dir.is_dir():
        for path in sorted(notes_dir.glob("*.md")):
            if not vault.ISO_DATE_RE.match(path.stem):
                continue
            try:
                found.append(datetime.strptime(path.stem, "%Y-%m-%d").date())
            except ValueError:
                continue
    if not found:
        raise RedateError(
            f"no ISO-named daily notes found under {notes_dir} — nothing to anchor the re-date on"
        )
    return max(found)


def weekday_aligned_shift(anchor: date, demo_day: date) -> tuple:
    """The cluster-A shift (always a multiple of 7) and where it lands `anchor`.

    Choosing recap_from_target on the same weekday as anchor keeps every
    weekday-name string in the fixture prose correct without rewriting any
    of it, and keeps the shift a whole number of weeks so business-day
    structure (which day is a weekend) is preserved too.
    """
    delta_weekday = (demo_day.weekday() - anchor.weekday()) % 7
    recap_from_target = demo_day - timedelta(days=delta_weekday)
    shift_days = (recap_from_target - anchor).days
    return shift_days, recap_from_target


def _shift_iso_token(shift_days: int):
    def repl(match: re.Match) -> str:
        year, month, day, time_suffix = match.groups()
        try:
            original = date(int(year), int(month), int(day))
        except ValueError:
            return match.group(0)  # not a real date — leave it alone
        shifted = original + timedelta(days=shift_days)
        return f"{shifted.isoformat()}{time_suffix or ''}"
    return repl


def _shift_ddmmyy_token(shift_days: int):
    def repl(match: re.Match) -> str:
        try:
            original = datetime.strptime(match.group(0), "%d-%m-%y").date()
        except ValueError:
            return match.group(0)  # a token that only looks like DD-MM-YY
        shifted = original + timedelta(days=shift_days)
        return shifted.strftime("%d-%m-%y")
    return repl


def _shift_content_a(text: str, shift_days: int) -> str:
    text = _ISO_TOKEN_RE.sub(_shift_iso_token(shift_days), text)
    text = _DDMMYY_TOKEN_RE.sub(_shift_ddmmyy_token(shift_days), text)
    return text


def _apply_renames(renames: list) -> None:
    """Rename in two phases, via a unique temp name per file first.

    A one-phase rename risks a false collision: if file A's new name
    happens to equal file B's *old* name (both shift by the same amount,
    so this only takes two dates exactly `shift_days` apart), renaming A
    before B has moved out of the way trips `new_path.exists()` even
    though B is about to vacate it. Moving every source to a name nothing
    else in the batch can produce first removes that ordering dependency;
    only a genuine collision (two sources wanting the same final name)
    still raises.
    """
    temps = []
    for index, (old_path, new_path) in enumerate(renames):
        temp_path = old_path.with_name(f".redate-tmp-{index}-{old_path.name}")
        old_path.rename(temp_path)
        temps.append((temp_path, new_path))
    for temp_path, new_path in temps:
        if new_path.exists():
            raise RedateError(f"rename collision: {temp_path} -> {new_path} already exists")
        temp_path.rename(new_path)


def _cluster_a_md_files(target: Path):
    for path in sorted(target.rglob("*.md")):
        rel_parts = path.relative_to(target).parts
        if rel_parts and rel_parts[0] == INBOX_DIR:
            continue
        yield path


def _shifted_stem(stem: str, shift_days: int) -> Optional[str]:
    if _MEETING_STEM_RE.match(stem):
        old_date = date_from_stem(stem)
        if old_date is None:
            return None
        new_date = old_date + timedelta(days=shift_days)
        return _date_prefix(new_date.isoformat()) + stem[8:]
    if _ISO_STEM_RE.match(stem):
        try:
            old_date = datetime.strptime(stem[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
        new_date = old_date + timedelta(days=shift_days)
        return new_date.isoformat() + stem[10:]
    return None


def shift_cluster_a(target: Path, shift_days: int) -> None:
    """Shift every date in cluster A's content, then rename the files whose
    stem encodes one. Content first, always — a rename before the content
    pass would leave wikilinks (which are plain text) pointing at stems the
    content pass hasn't caught up to yet.
    """
    for path in _cluster_a_md_files(target):
        original = path.read_text(encoding="utf-8")
        updated = _shift_content_a(original, shift_days)
        if updated != original:
            vault.atomic_write(path, updated)

    renames = []
    for path in _cluster_a_md_files(target):
        new_stem = _shifted_stem(path.stem, shift_days)
        if new_stem is not None and new_stem != path.stem:
            renames.append((path, path.with_name(new_stem + path.suffix)))
    _apply_renames(renames)


# --------------------------------------------------------------------------
# Cluster B: the 5 inbox files
# --------------------------------------------------------------------------

def _inbox_files(target: Path):
    """(old_date, slug, path) for every inbox file, in filename order —
    which is original chronological order, since every stem starts with an
    ISO date."""
    folder = target / INBOX_DIR
    items = []
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            match = _INBOX_STEM_RE.match(path.stem)
            if not match:
                continue
            year, month, day, slug = match.groups()
            try:
                old_date = date(int(year), int(month), int(day))
            except ValueError:
                continue
            items.append((old_date, slug, path))
    return items


def _latest_on_or_before(end: date, weekday: int) -> date:
    return end - timedelta(days=(end.weekday() - weekday) % 7)


def _earliest_on_or_after(start: date, weekday: int) -> date:
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def plan_inbox_dates(target: Path, recap_from: date, demo_day: date) -> dict:
    """Where each inbox file lands: old filename stem -> new date.

    The weekday-locked file keeps its original weekday, placed as close to
    demo_day as the recap window allows (see the module docstring for the
    Mon/Tue trade-off). The other four are spread, in their original date
    order, evenly across the span from the locked file's new date through
    demo_day.
    """
    items = _inbox_files(target)
    if not items:
        return {}

    locked = [item for item in items if item[1] == WEEKDAY_LOCKED_INBOX_SLUG]
    if not locked:
        raise RedateError(
            f"expected an inbox file for {WEEKDAY_LOCKED_INBOX_SLUG!r} under "
            f"{target / INBOX_DIR}"
        )
    original_weekday = locked[0][0].weekday()

    checkin_date = _latest_on_or_before(demo_day, original_weekday)
    if checkin_date < recap_from:
        checkin_date = _earliest_on_or_after(recap_from, original_weekday)

    others = [item for item in items if item[1] != WEEKDAY_LOCKED_INBOX_SLUG]
    span_start = checkin_date
    span_end = max(demo_day, checkin_date)
    span_days = (span_end - span_start).days
    n_others = len(others)

    inbox_dates = {path.stem: checkin_date for _, slug, path in items
                   if slug == WEEKDAY_LOCKED_INBOX_SLUG}
    for index, (_, _, path) in enumerate(others):
        offset = (span_days * index) // (n_others - 1) if n_others > 1 else 0
        inbox_dates[path.stem] = span_start + timedelta(days=offset)
    return inbox_dates


def _rfc2822_span(new_date: date) -> str:
    return (f"{_DAY_ABBR[new_date.weekday()]}, {new_date.day} "
            f"{_MONTH_ABBR[new_date.month - 1]} {new_date.year}")


def _shift_content_b(text: str, new_date: date) -> str:
    text = _LABELED_DATE_LINE_RE.sub(
        lambda m: m.group("prefix") + new_date.isoformat(), text)
    text = _RFC2822_RE.sub(lambda m: _rfc2822_span(new_date), text)
    return text


def shift_cluster_b(target: Path, inbox_dates: dict) -> None:
    folder = target / INBOX_DIR
    if not folder.is_dir():
        return
    renames = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.stem not in inbox_dates:
            continue
        new_date = inbox_dates[path.stem]
        original = path.read_text(encoding="utf-8")
        updated = _shift_content_b(original, new_date)
        if updated != original:
            vault.atomic_write(path, updated)

        match = _INBOX_STEM_RE.match(path.stem)
        slug = match.group(4)
        new_path = path.with_name(f"{new_date.isoformat()}-{slug}{path.suffix}")
        if new_path != path:
            renames.append((path, new_path))
    _apply_renames(renames)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def redate_vault(target: Path, demo_day: date) -> RedatePlan:
    """Re-date the fixture overlay already copied into `target` so the
    recap window works as if today were `demo_day`. Raises RedateError
    (never ships a broken demo) if the self-check finds the recap gap over
    threshold anyway.
    """
    anchor = discover_anchor(target)
    shift_a_days, recap_from = weekday_aligned_shift(anchor, demo_day)
    inbox_dates = plan_inbox_dates(target, recap_from, demo_day)

    shift_cluster_a(target, shift_a_days)
    shift_cluster_b(target, inbox_dates)

    check = vaultlib_dates.plan(target, today=demo_day.isoformat())
    if check["over_threshold"]:
        raise RedateError(
            f"redate self-check failed for demo_day={demo_day.isoformat()}: "
            f"business_days_missed={check['business_days_missed']} exceeds "
            f"catchup_threshold={check['catchup_threshold']} "
            f"(recap_from={check['recap_from']})"
        )
    return RedatePlan(anchor=anchor, shift_a_days=shift_a_days,
                       recap_from=recap_from, inbox_dates=inbox_dates)
