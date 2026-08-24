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

DAILY_NOTES_DIR = "60-daily-notes"
NO_MEETINGS_LINE = "*No meetings scheduled.*"

_MARKER_RE = re.compile(r"\A<!-- evening-sync:([a-z-]+):(begin|end) -->\s*\Z")
_KNOWN_REGIONS = ("recap", "prep")
_ISO_DATE_ONLY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_TIME_RE = re.compile(r"\A([01]\d|2[0-3]):[0-5]\d\Z")
_HEADING_RE = re.compile(
    r"\A(\d{2}:\d{2}) — (.*?)(?: · \[\[([a-z0-9-]+)\]\])?\Z")
_ALLOWED_KEYS = ("date", "recap", "meetings", "meetings_note")
_ALLOWED_MEETING_KEYS = ("time", "subject", "entity", "prep")


class DailyNoteError(Exception):
    """A payload field or note state the caller must fix."""


def _require_date(raw) -> str:
    text = str(raw or "").strip()
    if not _ISO_DATE_ONLY_RE.match(text):
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
            if not (root / "40-entities" / entity / "dossier.md").is_file():
                raise DailyNoteError(
                    f"meeting {position}: entity {entity!r} has no dossier at "
                    f"40-entities/{entity}/dossier.md — pass null rather than "
                    "guessing")
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


def _render(data: dict) -> str:
    date_iso = data["date"]
    parts = ["---", f"date: {date_iso}", "type: daily-note", "---", "",
             f"# {date_iso} · {_day_name(date_iso)}", "",
             "## Recap", _region("recap", data["recap"]), "",
             "## Meetings", ""]
    if data["meetings"]:
        chunks = []
        for meeting in data["meetings"]:
            heading = f"### {meeting['time']} — {meeting['subject']}"
            if meeting["entity"]:
                heading += f" · [[{meeting['entity']}]]"
            chunks.append("\n".join([heading,
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
            f"carries {expected_preps} — the meeting structure changed since "
            "this note was written. Only region interiors are replaced and "
            "bytes outside markers are never touched, so a structural change "
            "needs a human (or a fresh note)."
        )
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
