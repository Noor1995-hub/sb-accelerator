"""Daily notes: render the contract, merge the marker-fenced machine regions.

One daily artifact (design decision 1): the evening run writes tomorrow's
note. Machine content lives between <!-- evening-sync:{region}:begin/end -->
markers; this module regenerates region interiors wholesale and is forbidden
from touching a byte outside them (decision 10). One writer class per region.
A structural change (the meeting set differs from the note's prep regions) is
refused rather than guessed at — by then the note may hold human jottings,
and those outrank the calendar.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dates, markdown, naming, vault

DAILY_NOTES_DIR = vault.DAILY_NOTES_DIR
NO_MEETINGS_LINE = "*No meetings scheduled.*"

_MARKER_RE = re.compile(r"\A<!-- evening-sync:([a-z-]+):(begin|end) -->\s*\Z")
_KNOWN_REGIONS = ("recap", "prep")
_TIME_RE = re.compile(r"\A([01]\d|2[0-3]):[0-5]\d\Z")
_HEADING_RE = re.compile(
    r"\A(\d{2}:\d{2}) — (.*?)(?: · \[\[([a-z0-9-]+)\]\])?\Z")
_ALLOWED_KEYS = ("date", "recap", "meetings", "meetings_note")
_ALLOWED_MEETING_KEYS = ("time", "subject", "entity", "prep")

_STRUCTURE_HINT = (
    "the meeting structure changed since this note was written. Only region "
    "interiors are replaced and bytes outside markers are never touched, so a "
    "structural change needs a human (or a fresh note)."
)


class DailyNoteError(Exception):
    """A payload field or note state the caller must fix."""


def _require_date(raw) -> str:
    text = str(raw or "").strip()
    if not vault.ISO_DATE_RE.match(text):
        raise DailyNoteError(f"date {raw!r} must be ISO YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise DailyNoteError(f"date {raw!r} is not a real date") from exc
    return text


def _day_name(date_iso: str) -> str:
    return dates.DAY_NAMES[datetime.strptime(date_iso, "%Y-%m-%d").weekday()]


def _clean_region_text(value, label: str) -> str:
    text = str(value or "").rstrip()
    if not text.strip():
        raise DailyNoteError(f"{label} must be a non-empty string")
    if "evening-sync:" in text:
        raise DailyNoteError(
            f"{label} must not contain region markers — the CLI writes those"
        )
    return text


def _validate(root: Path, payload) -> dict:
    if not isinstance(payload, dict):
        raise DailyNoteError("the payload must be a JSON object")
    unknown = sorted(set(payload) - set(_ALLOWED_KEYS))
    if unknown:
        raise DailyNoteError(f"unknown payload key(s) {unknown}")
    date_iso = _require_date(payload.get("date"))
    recap = _clean_region_text(payload.get("recap"), "recap")
    raw_meetings = payload.get("meetings")
    if not isinstance(raw_meetings, list):
        raise DailyNoteError("meetings must be a list (possibly empty)")
    meetings: List[dict] = []
    for position, entry in enumerate(raw_meetings, 1):
        if not isinstance(entry, dict):
            raise DailyNoteError(f"meeting {position}: must be an object")
        unknown_keys = sorted(set(entry) - set(_ALLOWED_MEETING_KEYS))
        if unknown_keys:
            raise DailyNoteError(
                f"meeting {position}: unknown key(s) {unknown_keys}")
        time_text = str(entry.get("time") or "").strip()
        if not _TIME_RE.match(time_text):
            raise DailyNoteError(
                f"meeting {position}: time {entry.get('time')!r} must be "
                "HH:MM (24h, local)")
        subject = str(entry.get("subject") or "").strip()
        if not subject or "\n" in subject or "evening-sync:" in subject:
            raise DailyNoteError(
                f"meeting {position}: subject must be one non-empty line "
                "without markers")
        entity = entry.get("entity")
        if entity is not None:
            entity = str(entity)
            try:
                naming.validate_slug(entity)
            except ValueError as exc:
                raise DailyNoteError(
                    f"meeting {position}: entity {entity!r}: {exc}") from exc
            dossier = root / vault.ENTITIES_DIR / entity / "dossier.md"
            if not dossier.is_file():
                raise DailyNoteError(
                    f"meeting {position}: entity {entity!r} has no dossier at "
                    f"{vault.ENTITIES_DIR}/{entity}/dossier.md — pass null "
                    "rather than guessing")
        prep = _clean_region_text(entry.get("prep"),
                                  f"meeting {position} prep")
        meetings.append({"time": time_text, "subject": subject,
                         "entity": entity, "prep": prep})
    meetings_note = payload.get("meetings_note")
    if meetings_note is not None:
        if meetings:
            raise DailyNoteError(
                "meetings_note only applies when meetings is empty")
        meetings_note = _clean_region_text(meetings_note, "meetings_note")
        if "\n" in meetings_note:
            raise DailyNoteError("meetings_note must be a single line")
    return {"date": date_iso, "recap": recap, "meetings": meetings,
            "meetings_note": meetings_note}


def _region(name: str, content: str) -> str:
    return (f"<!-- evening-sync:{name}:begin -->\n{content}\n"
            f"<!-- evening-sync:{name}:end -->")


def _meeting_heading(meeting: dict) -> str:
    """The heading text (no `### `) a meeting renders to — and the form the
    merge guard compares an existing note's heading against."""
    heading = f"{meeting['time']} — {meeting['subject']}"
    if meeting["entity"]:
        heading += f" · [[{meeting['entity']}]]"
    return heading


def _render(data: dict) -> str:
    date_iso = data["date"]
    parts = ["---", f"date: {date_iso}", "type: daily-note", "---", "",
             f"# {date_iso} · {_day_name(date_iso)}", "",
             "## Recap", _region("recap", data["recap"]), "",
             "## Meetings", ""]
    if data["meetings"]:
        chunks = []
        for meeting in data["meetings"]:
            chunks.append("\n".join([f"### {_meeting_heading(meeting)}",
                                     _region("prep", meeting["prep"]), "- "]))
        parts.append("\n\n".join(chunks))
    else:
        parts.append(_region("prep",
                             data["meetings_note"] or NO_MEETINGS_LINE))
    parts += ["", "## End of day", "- ", ""]
    return "\n".join(parts)


def _find_regions(lines: List[str]) -> List[dict]:
    regions: List[dict] = []
    open_marker: Optional[Tuple[str, int]] = None
    for index, line in enumerate(lines):
        match = _MARKER_RE.match(line)
        if not match:
            continue
        name, kind = match.group(1), match.group(2)
        if name not in _KNOWN_REGIONS:
            raise DailyNoteError(
                f"unknown region {name!r} at line {index + 1}; "
                f"known regions: {_KNOWN_REGIONS}")
        if kind == "begin":
            if open_marker is not None:
                raise DailyNoteError(
                    f"nested region marker at line {index + 1}")
            open_marker = (name, index)
        else:
            if open_marker is None or open_marker[0] != name:
                raise DailyNoteError(
                    f"unmatched end marker for {name!r} at line {index + 1}")
            regions.append({"name": name, "begin": open_marker[1],
                            "end": index})
            open_marker = None
    if open_marker is not None:
        raise DailyNoteError(f"region {open_marker[0]!r} is never closed")
    return regions


def _heading_above(lines: List[str], begin: int, floor: int) -> Optional[str]:
    """The `### ` heading a prep region belongs to, or None.

    Searches upward from the region's begin marker, stopping at the previous
    region (so a missing heading never borrows the one above it, and a `###`
    line inside recap content is never read as a meeting) and at any `#`/`##`
    line, which ends the meeting a heading would have introduced.
    """
    for index in range(begin - 1, floor - 1, -1):
        line = lines[index].rstrip()
        if line.startswith("### "):
            return line[4:].strip()
        if line.startswith(("# ", "## ")):
            return None
    return None


def _heading_key(text: str) -> Tuple[str, str, Optional[str]]:
    """(time, subject, entity) — an unparseable heading compares as a whole so
    a hand-retyped one is a mismatch rather than a partial match."""
    match = _HEADING_RE.match(text)
    if not match:
        return ("", text, None)
    return (match.group(1), match.group(2), match.group(3))


def _check_headings(lines: List[str], regions: List[dict],
                    meetings: List[dict]) -> None:
    """Refuse a merge whose prep regions sit under the wrong meetings.

    Equal counts are not equal structure: headings live outside the markers,
    so nothing regenerates them, and a calendar that swapped one meeting for
    another between runs would file fresh prep under a stale heading.
    """
    preps, floors, previous_end = [], [], 0
    for region in regions:
        if region["name"] == "prep":
            preps.append(region)
            floors.append(previous_end)
        previous_end = region["end"] + 1
    for position, (region, floor) in enumerate(zip(preps, floors)):
        found = _heading_above(lines, region["begin"], floor)
        if not meetings:
            if found is not None:
                raise DailyNoteError(
                    f"the note's prep region sits under meeting heading "
                    f"{found!r} but the payload carries no meetings — "
                    f"{_STRUCTURE_HINT}")
            continue
        expected = _meeting_heading(meetings[position])
        if found is None:
            raise DailyNoteError(
                f"meeting {position + 1}: the note has no '### ' heading above "
                f"the matching prep region, but the payload carries "
                f"{expected!r} — {_STRUCTURE_HINT}")
        if _heading_key(found) != _heading_key(expected):
            raise DailyNoteError(
                f"meeting {position + 1}: the note's heading is {found!r} but "
                f"the payload carries {expected!r} — {_STRUCTURE_HINT}")


def _merge(text: str, data: dict) -> Tuple[str, int]:
    lines = text.split("\n")
    regions = _find_regions(lines)
    recaps = [r for r in regions if r["name"] == "recap"]
    preps = [r for r in regions if r["name"] == "prep"]
    if len(recaps) != 1:
        raise DailyNoteError(
            f"expected exactly one recap region, found {len(recaps)}")
    expected_preps = len(data["meetings"]) if data["meetings"] else 1
    if len(preps) != expected_preps:
        raise DailyNoteError(
            f"the note has {len(preps)} prep region(s) but the payload "
            f"carries {expected_preps} — {_STRUCTURE_HINT}"
        )
    _check_headings(lines, regions, data["meetings"])
    prep_contents = ([m["prep"] for m in data["meetings"]]
                     if data["meetings"]
                     else [data["meetings_note"] or NO_MEETINGS_LINE])
    replacements: Dict[int, Tuple[dict, str]] = {
        recaps[0]["begin"]: (recaps[0], data["recap"])}
    for region, content in zip(preps, prep_contents):
        replacements[region["begin"]] = (region, content)
    out: List[str] = []
    index = 0
    while index < len(lines):
        if index in replacements:
            region, content = replacements[index]
            out.append(lines[region["begin"]])
            out.extend(content.split("\n"))
            out.append(lines[region["end"]])
            index = region["end"] + 1
        else:
            out.append(lines[index])
            index += 1
    return "\n".join(out), len(replacements)


def write(root: Path, payload) -> dict:
    data = _validate(root, payload)
    path = root / DAILY_NOTES_DIR / f"{data['date']}.md"
    if path.is_file():
        original = path.read_text(encoding="utf-8")
        merged, replaced = _merge(original, data)
        changed = merged != original
        if changed:
            vault.atomic_write(path, merged)
        created = False
    else:
        merged = _render(data)
        replaced = 1 + (len(data["meetings"]) or 1)
        changed, created = True, True
        vault.atomic_write(path, merged)
    return {
        "path": f"{DAILY_NOTES_DIR}/{data['date']}.md",
        "date": data["date"],
        "day_name": _day_name(data["date"]),
        "created": created,
        "regions_replaced": replaced,
        "changed": changed,
    }


def _frontmatter_end_line(lines: List[str]) -> int:
    """Index of the closing '---' fence line, or -1 if none."""
    if not lines or lines[0].strip() != "---":
        return -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index
    return -1


def read(root: Path, date_iso_raw) -> dict:
    """Parse a daily note into machine regions and human jottings.

    Read-only by design (decision 8): the note is the archive of the day.
    A missing note is a normal state — the first run of a fresh vault — not
    an error. A hand-written note without markers is tolerated: everything
    is human text then, and recap comes back null.
    """
    date_iso = _require_date(date_iso_raw)
    rel = f"{DAILY_NOTES_DIR}/{date_iso}.md"
    path = root / DAILY_NOTES_DIR / f"{date_iso}.md"
    if not path.is_file():
        return {"exists": False, "path": rel}
    text = path.read_text(encoding="utf-8")
    warnings: List[str] = []
    try:
        frontmatter, _ = markdown.split_frontmatter(text)
    except ValueError as exc:
        frontmatter = {}
        warnings.append(f"{rel}: {exc}")

    lines = text.split("\n")
    regions = _find_regions(lines)
    region_lines = set()
    for region in regions:
        region_lines.update(range(region["begin"], region["end"] + 1))
    recap = None
    recap_regions = [r for r in regions if r["name"] == "recap"]
    if recap_regions:
        region = recap_regions[0]
        recap = "\n".join(lines[region["begin"] + 1:region["end"]])
    prep_by_begin = {r["begin"]: "\n".join(lines[r["begin"] + 1:r["end"]])
                     for r in regions if r["name"] == "prep"}

    meetings: List[dict] = []
    meetings_note = None
    end_of_day: List[str] = []
    other_lines: List[str] = []
    current: Optional[dict] = None
    section = ""
    fm_end = _frontmatter_end_line(lines)
    for index, line in enumerate(lines):
        if index <= fm_end:
            continue
        if index in region_lines:
            if index in prep_by_begin:
                # A prep region under no meeting heading is the no-meetings
                # line the write path renders (or the payload's meetings_note).
                if current is not None:
                    current["prep"] = prep_by_begin[index]
                elif meetings_note is None:
                    meetings_note = prep_by_begin[index]
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        if line.startswith("# "):
            continue
        if section == "Meetings" and line.startswith("### "):
            heading = line[4:].strip()
            match = _HEADING_RE.match(heading)
            current = {
                "heading": heading,
                "time": match.group(1) if match else None,
                "subject": match.group(2) if match else heading,
                "entity": match.group(3) if match else None,
                "prep": None,
                "jottings": [],
            }
            meetings.append(current)
            continue
        stripped = line.strip()
        if not stripped:
            continue
        content = stripped[2:].strip() if stripped.startswith("- ") else (
            "" if stripped == "-" else stripped)
        if not content:
            continue   # the empty '- ' jot affordance
        if section == "End of day":
            end_of_day.append(content)
        elif section == "Meetings" and current is not None:
            current["jottings"].append(content)
        else:
            other_lines.append(content)
    return {
        "exists": True, "path": rel, "date": date_iso,
        "frontmatter": frontmatter, "recap": recap, "meetings": meetings,
        "meetings_note": meetings_note,
        "end_of_day": end_of_day, "other_lines": other_lines,
        "warnings": warnings,
    }
