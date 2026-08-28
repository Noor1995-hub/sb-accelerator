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

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dates, markdown, meeting, naming, vault

DAILY_NOTES_DIR = vault.DAILY_NOTES_DIR
NO_MEETINGS_LINE = "*No meetings scheduled.*"

_MARKER_RE = re.compile(
    r"\A<!-- evening-sync:([a-z-]+):(begin|end)"
    r"((?: [a-z][a-z0-9-]*=[A-Za-z0-9._-]+)*) -->\s*\Z")
_ATTR_RE = re.compile(r"([a-z][a-z0-9-]*)=([A-Za-z0-9._-]+)")
# Region metadata the CLI owns. Only the recap's begin marker carries any:
# `inputs` is the fingerprint of what the recap was composed from. Anything
# else means a version this plugin does not understand, and guessing at a
# marker is how a note gets silently mis-merged.
_ALLOWED_ATTRS = {("recap", "begin"): frozenset({"inputs"})}
_KNOWN_REGIONS = ("recap", "prep")
_TIME_RE = re.compile(r"\A([01]\d|2[0-3]):[0-5]\d\Z")
_HEADING_RE = re.compile(
    r"\A(\d{2}:\d{2}) — (.*?)(?: · \[\[([a-z0-9-]+)\]\])?\Z")
_ALLOWED_KEYS = ("date", "recap", "meetings", "meetings_note", "recap_window")
_ALLOWED_MEETING_KEYS = ("time", "subject", "entity", "prep")
_ALLOWED_WINDOW_KEYS = ("from", "to", "detailed_from")
_DIGEST_LENGTH = 16

# `#heading` is stripped before resolution; `|alias` is the display-name
# claim. `!?` catches embeds, which make the same claim as a plain link.
_WIKILINK_RE = re.compile(
    r"!?\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")


class DailyNoteError(Exception):
    """A payload field or note state the caller must fix."""


def _require_date(raw, label: str = "date") -> str:
    text = str(raw or "").strip()
    if not vault.ISO_DATE_RE.match(text):
        raise DailyNoteError(f"{label} {raw!r} must be ISO YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise DailyNoteError(f"{label} {raw!r} is not a real date") from exc
    return text


def _require_date_obj(raw, label: str) -> date:
    return datetime.strptime(_require_date(raw, label), "%Y-%m-%d").date()


def _validate_window(payload: dict, note_date: str) -> Optional[dict]:
    """The recap window: what the recap covers, and what it was built from.

    Optional so existing callers keep working — but a caller that omits it
    forgoes both the catch-up banner and the idempotence guard, which is
    why a skill-contract test pins it into the SKILL.md payload example.
    """
    raw = payload.get("recap_window")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DailyNoteError("recap_window must be a JSON object")
    unknown = sorted(set(raw) - set(_ALLOWED_WINDOW_KEYS))
    if unknown:
        raise DailyNoteError(f"recap_window: unknown key(s) {unknown}")
    for key in ("from", "to"):
        if key not in raw:
            raise DailyNoteError(
                f"recap_window: {key} is required — pass recap_from and "
                "recap_to from `dates plan` verbatim")
    start = _require_date_obj(raw["from"], "recap_window.from")
    end = _require_date_obj(raw["to"], "recap_window.to")
    if start > end:
        raise DailyNoteError(
            f"recap_window: from {start.isoformat()} is after to "
            f"{end.isoformat()}")
    if end >= datetime.strptime(note_date, "%Y-%m-%d").date():
        raise DailyNoteError(
            f"recap_window.to ({end.isoformat()}) must be before the note's "
            f"own date ({note_date}) — the window is what the note recaps, "
            "not the note itself")
    detailed = raw.get("detailed_from")
    if detailed is not None:
        detailed = _require_date_obj(detailed, "recap_window.detailed_from")
        if not start <= detailed <= end:
            raise DailyNoteError(
                f"recap_window.detailed_from ({detailed.isoformat()}) must "
                f"fall within {start.isoformat()}..{end.isoformat()}")
    return {"from": start, "to": end, "detailed_from": detailed}


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


def _resolve_link(root: Path, target: str):
    """(kind, path, display-name key) for a wikilink target, or three Nones.

    Identity objects come first: they are the ones whose *name* an alias
    claims, and a slug that is both a person note and a project folder is a
    collision the vault should not have. Event objects resolve but make no
    name claim — "Friday's Acme sync" is a reference, not a name.
    """
    candidates = (
        ("entity", root / vault.ENTITIES_DIR / target / "dossier.md",
         "entity-name"),
        ("person", root / vault.PEOPLE_DIR / f"{target}.md", "person-name"),
        ("project", root / vault.PROJECTS_DIR / target / "index.md",
         "project-name"),
        ("meeting", root / vault.MEETINGS_DIR / f"{target}.md", None),
        ("daily note", root / DAILY_NOTES_DIR / f"{target}.md", None),
    )
    for kind, path, name_key in candidates:
        if path.is_file():
            return kind, path, name_key
    projects = root / vault.PROJECTS_DIR
    for folder in sorted(projects.glob("*/decisions")) if projects.is_dir() else []:
        path = folder / f"{target}.md"
        if path.is_file():
            return "decision", path, None
    return None, None, None


def _check_links(root: Path, text: str, label: str,
                 warnings: List[str]) -> None:
    """Every wikilink resolves; every identity alias matches the vault.

    Decision 19. A plain-prose name cannot be checked by anything, which is
    why the skill mandates the wikilink form — this is the half that a
    machine can hold.
    """
    for match in _WIKILINK_RE.finditer(text):
        target = match.group(1).strip()
        alias = match.group(2)
        kind, path, name_key = _resolve_link(root, target)
        if kind is None:
            raise DailyNoteError(
                f"{label}: [[{target}]] resolves to no vault object — link "
                "only to objects that exist (create one with /update-entity "
                "or /new-project first), or leave the name out. Never write "
                "a name you have not looked up.")
        if alias is None or name_key is None:
            continue
        try:
            frontmatter, _ = markdown.split_frontmatter(
                path.read_text(encoding="utf-8"))
        except ValueError as exc:
            warnings.append(
                f"{label}: [[{target}]] resolves but its frontmatter could "
                f"not be read ({exc}) — display name not verified")
            continue
        actual = str(frontmatter.get(name_key) or "").strip()
        if not actual:
            warnings.append(
                f"{label}: [[{target}]] carries no {name_key} — display name "
                "not verified")
            continue
        if alias.strip() != actual:
            raise DailyNoteError(
                f"{label}: [[{target}|{alias}]] — that {kind} is called "
                f"{actual!r}. Display names come from the vault, never from "
                "the model.")


def _validate(root: Path, payload) -> Tuple[dict, List[str]]:
    if not isinstance(payload, dict):
        raise DailyNoteError("the payload must be a JSON object")
    warnings: List[str] = []
    unknown = sorted(set(payload) - set(_ALLOWED_KEYS))
    if unknown:
        raise DailyNoteError(f"unknown payload key(s) {unknown}")
    date_iso = _require_date(payload.get("date"))
    window = _validate_window(payload, date_iso)
    recap = _clean_region_text(payload.get("recap"), "recap")
    _check_links(root, recap, "recap", warnings)
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
        _check_links(root, prep, f"meeting {position} prep", warnings)
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
        _check_links(root, meetings_note, "meetings_note", warnings)
    return ({"date": date_iso, "recap": recap, "meetings": meetings,
             "meetings_note": meetings_note, "recap_window": window},
            warnings)


def _iso_prefix_date(stem: str) -> Optional[date]:
    head = str(stem)[:10]
    if not vault.ISO_DATE_RE.match(head):
        return None
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fingerprint_inputs(root: Path, start: date, end: date) -> List[Tuple[str, Path]]:
    """Every file whose content the recap for [start, end] was built from.

    Meetings and jottings are the recap's stated inputs; decisions are here
    so a stage-4 retry that finally wrote one is not read as "unchanged".
    """
    found: List[Tuple[str, Path]] = []
    meetings = root / vault.MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        noted = meeting.date_from_stem(path.stem)
        if noted is not None and start <= noted <= end:
            found.append((f"{vault.MEETINGS_DIR}/{path.name}", path))
    notes = root / DAILY_NOTES_DIR
    for path in sorted(notes.glob("*.md")) if notes.is_dir() else []:
        noted = _iso_prefix_date(path.stem)
        # The stem must be the date and nothing else: an editor's
        # `2026-06-12-backup.md` is not that day's note, and hashing it would
        # invalidate every recap fingerprint for the window.
        if noted is not None and path.stem == noted.isoformat() and start <= noted <= end:
            found.append((f"{DAILY_NOTES_DIR}/{path.name}", path))
    projects = root / vault.PROJECTS_DIR
    for folder in sorted(projects.glob("*/decisions")) if projects.is_dir() else []:
        for path in sorted(folder.glob("*.md")):
            noted = _iso_prefix_date(path.stem)
            if noted is not None and start <= noted <= end:
                found.append((
                    f"{vault.PROJECTS_DIR}/{folder.parent.name}/decisions/"
                    f"{path.name}", path))
    return found


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _catchup_banner(root: Path, window: Optional[dict]) -> Optional[str]:
    """The owner-facing statement of decisions 15-17, or None on a normal run.

    Rendered here rather than composed by the caller: the count is
    arithmetic and the no-back-fill rule is a promise the CLI keeps, so
    neither is left to a model to remember.

    The count comes from `dates.missed_runs`, which asks the vault whether
    each run left a note behind, not from the window's width — a Saturday
    run on a healthy vault has a two-day window and zero missed runs, and
    this banner is the artifact that would otherwise state the opposite to
    the vault owner.
    """
    if window is None:
        return None
    missed = dates.missed_runs(root, window["from"], window["to"])
    if missed <= 0:
        return None
    lines = [
        "> [!warning] Catch-up note",
        f"> Covers {window['from'].isoformat()} → {window['to'].isoformat()} "
        f"— {_plural(missed, 'business day')} without an evening run. "
        "Skipped days are not back-filled: this is the only note for that "
        "window.",
    ]
    detailed = window.get("detailed_from")
    if detailed is not None and detailed > window["from"]:
        earlier = dates.business_days(window["from"], detailed)
        verb = "is" if earlier == 1 else "are"
        lines.append(
            f"> Detailed from {detailed.isoformat()}; the "
            f"{_plural(earlier, 'earlier business day')} {verb} counted, "
            "not recapped in detail.")
    return "\n".join(lines)


def recap_fingerprint(root: Path, window: dict) -> str:
    """A content hash of the recap's inputs — 16 hex, as `syncjob.content_id`.

    Computed here, never accepted from a caller: a caller-supplied hash is
    a caller-supplied fact, and the whole point is that this one is not.

    The first line is the *rendered banner*, hashed — not the raw window
    bounds. The digest has to cover exactly what determines the region's
    machine-generated content, which is the banner plus the input files.
    Hashing the bounds instead made a Saturday re-run over an untouched
    vault look changed (`08-21..08-21` vs `08-21..08-22`) and regenerate a
    recap the vault owner had already read, and it left `detailed_from` — which
    does change the rendered banner — out of the digest entirely.

    Dropping the bounds is safe: if they move enough to change what the
    recap is built from, the input *file set* moves with them. If they move
    without changing either the banner or the file set, the rendered region
    is byte-identical and skipping it is the right answer.
    """
    start, end = window["from"], window["to"]
    banner = _catchup_banner(root, window) or ""
    lines = [f"banner\t{hashlib.sha256(banner.encode('utf-8')).hexdigest()}"]
    for relpath, path in sorted(_fingerprint_inputs(root, start, end)):
        lines.append(f"{relpath}\t{hashlib.sha256(path.read_bytes()).hexdigest()}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest[:_DIGEST_LENGTH]


def _recap_body(root: Path, data: dict) -> str:
    banner = _catchup_banner(root, data["recap_window"])
    return f"{banner}\n\n{data['recap']}" if banner else data["recap"]


def _marker_line(name: str, kind: str,
                 attrs: Optional[dict] = None) -> str:
    suffix = "".join(f" {key}={value}"
                     for key, value in sorted((attrs or {}).items()))
    return f"<!-- evening-sync:{name}:{kind}{suffix} -->"


def _region(name: str, content: str, attrs: Optional[dict] = None) -> str:
    return (f"{_marker_line(name, 'begin', attrs)}\n{content}\n"
            f"{_marker_line(name, 'end')}")


def _heading(meeting: dict) -> str:
    heading = f"{meeting['time']} — {meeting['subject']}"
    if meeting["entity"]:
        heading += f" · [[{meeting['entity']}]]"
    return heading


def _render(root: Path, data: dict, fingerprint: Optional[str]) -> str:
    date_iso = data["date"]
    attrs = {"inputs": fingerprint} if fingerprint else None
    parts = ["---", f"date: {date_iso}", "type: daily-note", "---", "",
             f"# {date_iso} · {_day_name(date_iso)}", "",
             "## Recap", _region("recap", _recap_body(root, data), attrs), "",
             "## Meetings", ""]
    if data["meetings"]:
        chunks = []
        for meeting in data["meetings"]:
            heading = f"### {_heading(meeting)}"
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
    open_marker: Optional[Tuple[str, int, dict]] = None
    for index, line in enumerate(lines):
        match = _MARKER_RE.match(line)
        if not match:
            continue
        name, kind = match.group(1), match.group(2)
        if name not in _KNOWN_REGIONS:
            raise DailyNoteError(
                f"unknown region {name!r} at line {index + 1}; "
                f"known regions: {_KNOWN_REGIONS}")
        attrs = dict(_ATTR_RE.findall(match.group(3)))
        stray = sorted(set(attrs) - _ALLOWED_ATTRS.get((name, kind), frozenset()))
        if stray:
            raise DailyNoteError(
                f"unknown region attribute(s) {stray} on {name}:{kind} at "
                f"line {index + 1} — this note may have been written by a "
                "newer plugin version; upgrade the plugin rather than "
                "editing the marker")
        if kind == "begin":
            if open_marker is not None:
                raise DailyNoteError(
                    f"nested region marker at line {index + 1}")
            open_marker = (name, index, attrs)
        else:
            if open_marker is None or open_marker[0] != name:
                raise DailyNoteError(
                    f"unmatched end marker for {name!r} at line {index + 1}")
            regions.append({"name": name, "begin": open_marker[1],
                            "end": index, "attrs": open_marker[2]})
            open_marker = None
    if open_marker is not None:
        raise DailyNoteError(f"region {open_marker[0]!r} is never closed")
    return regions


_STRUCTURAL_HINT = (
    "Only region interiors are replaced and bytes outside markers are "
    "never touched, so a structural change needs a human (or a fresh note)."
)


def _heading_above(lines: List[str], begin: int, floor: int) -> Optional[str]:
    """The '### ...' heading a prep region belongs to, searching upward.

    Not just the line directly above: the gap between a heading and its marker
    is outside the markers, so it is the user's. A blank line inserted by an
    Obsidian formatter, or a note they typed under the heading, must not read
    as "this region has no heading" and refuse every run from then on. The
    search stops at the previous region (so a missing heading never borrows
    the one above it, and a `### ` inside recap content stays content) and at
    any `#`/`##` line, which ends the meeting a heading would have introduced.
    """
    for index in range(begin - 1, floor - 1, -1):
        line = lines[index].rstrip()
        if line.startswith("### "):
            return line[len("### "):].strip()
        if line.startswith(("# ", "## ")):
            return None
    return None


def _prep_headings(lines: List[str], regions: List[dict]) -> List[Optional[str]]:
    """Each prep region's heading, in document order — None where it has none."""
    headings: List[Optional[str]] = []
    floor = 0
    for region in regions:
        if region["name"] == "prep":
            headings.append(_heading_above(lines, region["begin"], floor))
        floor = region["end"] + 1
    return headings


def _merge(root: Path, text: str, data: dict,
           fingerprint: Optional[str]) -> Tuple[str, int, bool]:
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
            f"this note was written. {_STRUCTURAL_HINT}"
        )
    prep_headings = _prep_headings(lines, regions)
    if data["meetings"]:
        if any(heading is None for heading in prep_headings):
            raise DailyNoteError(
                "a prep region in the note has no meeting heading above it "
                "but the payload carries meetings — the meeting structure "
                f"changed since this note was written. {_STRUCTURAL_HINT}"
            )
        expected_headings = [_heading(m) for m in data["meetings"]]
        if prep_headings != expected_headings:
            raise DailyNoteError(
                "the note's meeting headings don't match the payload — the "
                f"meeting structure changed since this note was written. "
                f"{_STRUCTURAL_HINT}"
            )
    else:
        if prep_headings[0] is not None:
            raise DailyNoteError(
                "the note's prep region is headed by a meeting but the "
                "payload carries no meetings — the meeting structure "
                f"changed since this note was written. {_STRUCTURAL_HINT}"
            )
    prep_contents = ([m["prep"] for m in data["meetings"]]
                     if data["meetings"]
                     else [data["meetings_note"] or NO_MEETINGS_LINE])
    # Each entry: begin index -> (region, content, marker line or None).
    # None means "re-emit the line that is already there"; only the recap's
    # begin marker is ever rewritten, and only to restamp `inputs`.
    replacements: Dict[int, Tuple[dict, str, Optional[str]]] = {}
    recap = recaps[0]
    recap_skipped = (fingerprint is not None
                     and recap["attrs"].get("inputs") == fingerprint)
    if not recap_skipped:
        attrs = {"inputs": fingerprint} if fingerprint else None
        replacements[recap["begin"]] = (
            recap, _recap_body(root, data),
            _marker_line("recap", "begin", attrs))
    for region, content in zip(preps, prep_contents):
        replacements[region["begin"]] = (region, content, None)
    out: List[str] = []
    index = 0
    while index < len(lines):
        if index in replacements:
            region, content, marker = replacements[index]
            out.append(marker if marker is not None else lines[region["begin"]])
            out.extend(content.split("\n"))
            out.append(lines[region["end"]])
            index = region["end"] + 1
        else:
            out.append(lines[index])
            index += 1
    return "\n".join(out), len(replacements), recap_skipped


def write(root: Path, payload) -> dict:
    data, warnings = _validate(root, payload)
    window = data["recap_window"]
    fingerprint = recap_fingerprint(root, window) if window else None
    path = root / DAILY_NOTES_DIR / f"{data['date']}.md"
    if path.is_file():
        original = path.read_text(encoding="utf-8")
        merged, replaced, recap_skipped = _merge(
            root, original, data, fingerprint)
        changed = merged != original
        if changed:
            vault.atomic_write(path, merged)
        created = False
    else:
        merged = _render(root, data, fingerprint)
        replaced = 1 + (len(data["meetings"]) or 1)
        changed, created, recap_skipped = True, True, False
        vault.atomic_write(path, merged)
    return {
        "path": f"{DAILY_NOTES_DIR}/{data['date']}.md",
        "date": data["date"],
        "day_name": _day_name(data["date"]),
        "created": created,
        "regions_replaced": replaced,
        "changed": changed,
        "recap_skipped": recap_skipped,
        "recap_inputs": fingerprint,
        "warnings": warnings,
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
    recap_inputs = None
    recap_regions = [r for r in regions if r["name"] == "recap"]
    if recap_regions:
        region = recap_regions[0]
        recap = "\n".join(lines[region["begin"] + 1:region["end"]])
        recap_inputs = region["attrs"].get("inputs")
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
        "frontmatter": frontmatter, "recap": recap,
        "recap_inputs": recap_inputs, "meetings": meetings,
        "meetings_note": meetings_note,
        "end_of_day": end_of_day, "other_lines": other_lines,
        "warnings": warnings,
    }
