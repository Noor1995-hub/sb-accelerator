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

from . import dates, links, markdown, meeting, naming, provenance, recap, vault

DAILY_NOTES_DIR = vault.DAILY_NOTES_DIR
NO_MEETINGS_LINE = "*No meetings scheduled.*"

PREP_HEADING = "#### Prep"
# "Your" says whose they are (#238); the reader finds them by position under
# the meeting heading, so notes written with the old "#### Notes" still read.
NOTES_BLOCK = "#### Your notes\n- "
ACTIONS_BLOCK = "#### Your to do's\n- [ ] "
# The live review queues, at the top of every note the evening run writes
# (#238). Embedded Bases views, so ticking Keep or Dismiss here works and the
# rows leave at once; the CSS snippet collapses an empty table, and the whole
# callout when both are empty, so a clear day shows nothing. Written once at
# creation and never merged: it holds no machine state.
REVIEW_BLOCK = ("> [!review] Waiting for you\n"
                "> ![[20-meetings/Meetings.base#To review]]\n"
                ">\n"
                "> ![[30-projects/Decisions.base#To review]]")
# The Meetings view was named Triage until #240. A note that migration 006
# has not rewritten still carries this line, and it is not a jotting.
LEGACY_TRIAGE_EMBED = "> ![[20-meetings/Meetings.base#Triage]]"
# The Decisions view was named Needs review until #244 — the name a 0.12.x
# vault still carries until its tables are refreshed.
LEGACY_DECISIONS_EMBED = "> ![[30-projects/Decisions.base#Needs review]]"
_REVIEW_LINES = (frozenset(REVIEW_BLOCK.split("\n"))
                 | {LEGACY_TRIAGE_EMBED, LEGACY_DECISIONS_EMBED})
MEETINGS_BASE = Path(vault.MEETINGS_DIR) / "Meetings.base"
DECISIONS_BASE = Path(vault.PROJECTS_DIR) / "Decisions.base"
_TRIAGE_VIEW_RE = re.compile(r"^\s*-?\s*name:\s*[\"']?Triage[\"']?\s*$", re.MULTILINE)
_NEEDS_REVIEW_VIEW_RE = re.compile(r"^\s*-?\s*name:\s*[\"']?Needs review[\"']?\s*$", re.MULTILINE)
_TO_REVIEW_VIEW_RE = re.compile(r"^\s*-?\s*name:\s*[\"']?To review[\"']?\s*$", re.MULTILINE)


def _review_block(root: Path) -> str:
    """The review block, embedding the Meetings view this vault actually has.

    The plugin updates on its own; the vault's tables change only at the next
    `/upgrade-vault`. Until then a vault's Meetings table may still call its
    queue Triage, and an embed of "To review" would show an error where the
    queue belongs. So the note embeds whichever name the vault's own table
    carries (#263); a vault without the table gets the shipped name. The
    same holds for Decisions, whose queue was Needs review until #244.
    """
    block = REVIEW_BLOCK
    for base, legacy_re, legacy_line, shipped_line in (
            (MEETINGS_BASE, _TRIAGE_VIEW_RE, LEGACY_TRIAGE_EMBED,
             "> ![[20-meetings/Meetings.base#To review]]"),
            (DECISIONS_BASE, _NEEDS_REVIEW_VIEW_RE, LEGACY_DECISIONS_EMBED,
             "> ![[30-projects/Decisions.base#To review]]")):
        try:
            text = (root / base).read_text(encoding="utf-8")
        except OSError:
            continue
        if legacy_re.search(text) and not _TO_REVIEW_VIEW_RE.search(text):
            block = block.replace(shipped_line, legacy_line)
    return block
_PREP_KEYS = ("attendees", "last_meeting", "context")
_PREP_LABELS = (("attendees", "Attendees"), ("last_meeting", "Last meeting"),
                ("context", "Context"))
_BANNER_FIRST_LINE = "> [!warning] Catch-up note"

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
    r"\A(\d{2}:\d{2}) — (.*?)"
    r"(?: · \[\[(?:40-entities/)?([a-z0-9-]+)(?:/dossier)?(?:\|[^\]]*)?\]\])?\Z")
_TASK_RE = re.compile(r"\A- \[( |x|X)\]\s*(.*)\Z")
_ALLOWED_KEYS = ("date", "recap", "meetings", "meetings_note", "recap_window")
_ALLOWED_MEETING_KEYS = ("time", "subject", "entity", "prep")
_ALLOWED_WINDOW_KEYS = ("from", "to", "detailed_from", "plan_for")
_DIGEST_LENGTH = 16


def parse_heading(text: str):
    """(time, subject, entity slug) for a v1 `· [[slug]]` or v2
    `· [[40-entities/slug/dossier|Name]]` heading; None when not a meeting heading."""
    match = _HEADING_RE.match(str(text).strip())
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


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
    plan_for = raw.get("plan_for", "next-business-day")
    if plan_for not in ("today", "next-business-day"):
        raise DailyNoteError(
            f"recap_window.plan_for {plan_for!r} must be `dates plan`'s "
            "plan_for: 'today' or 'next-business-day'")
    # Which evening runs the banner counts as missed: up to the run now
    # writing, which in the --for-today frame is a late one standing in for
    # the evening before the note's date — `dates plan` counts it, and so
    # must the banner (review 2026-10-12: plan said 3, the note said 2).
    count_to = (datetime.strptime(note_date, "%Y-%m-%d").date()
                if plan_for == "today" else end)
    return {"from": start, "to": end, "detailed_from": detailed,
            "count_to": count_to}


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


def _check_links(root: Path, text: str, label: str,
                 warnings: List[str]) -> List[str]:
    """Every wikilink resolves; every identity alias matches the vault.

    v1 payloads are *checked* here and left as written (byte-identical
    rendering is pinned); v2 payloads are normalised by `recap.py` and the
    prep renderer, which call `links.normalise` and pass its offenders
    through the same single-raise path.
    """
    _, offenders, new_warnings = links.normalise(root, text, label)
    warnings.extend(new_warnings)
    return offenders


def _strip_model_banner(text: str) -> Tuple[str, bool]:
    """Drop a model-written catch-up callout from a v1 recap string."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != _BANNER_FIRST_LINE:
        return text, False
    index = 1
    while index < len(lines) and lines[index].startswith(">"):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    rest = "\n".join(lines[index:]).rstrip()
    if not rest.strip():
        raise DailyNoteError(
            "recap held only a Catch-up note callout — the CLI writes that "
            "banner itself; the payload must carry the recap content")
    return rest, True


def _validate(root: Path, payload) -> Tuple[dict, List[str]]:
    if not isinstance(payload, dict):
        raise DailyNoteError("the payload must be a JSON object")
    warnings: List[str] = []
    link_offenders: List[str] = []
    unknown = sorted(set(payload) - set(_ALLOWED_KEYS))
    if unknown:
        raise DailyNoteError(f"unknown payload key(s) {unknown}")
    date_iso = _require_date(payload.get("date"))
    window = _validate_window(payload, date_iso)
    raw_meetings = payload.get("meetings")
    if not isinstance(raw_meetings, list):
        raise DailyNoteError("meetings must be a list (possibly empty)")
    meetings: List[dict] = []
    prep_forms: set = set()
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
        raw_prep = entry.get("prep")
        if isinstance(raw_prep, dict):
            unknown_prep = sorted(set(raw_prep) - set(_PREP_KEYS))
            missing_prep = [k for k in _PREP_KEYS if not str(raw_prep.get(k) or "").strip()]
            if unknown_prep or missing_prep:
                raise DailyNoteError(
                    f"meeting {position} prep: needs exactly attendees, last_meeting, "
                    f"context (missing {missing_prep}, unknown {unknown_prep})")
            fields = {}
            for key in _PREP_KEYS:
                text = str(raw_prep[key]).strip()
                if "\n" in text or "evening-sync:" in text:
                    raise DailyNoteError(f"meeting {position} prep.{key} must be one line without markers")
                text, bad, warn = links.normalise(root, text, f"meeting {position} prep.{key}")
                link_offenders.extend(bad)
                warnings.extend(warn)
                fields[key] = text
            prep = "\n".join(f"**{label}** — {fields[key]}" for key, label in _PREP_LABELS)
            prep_forms.add("v2")
        else:
            prep = _clean_region_text(raw_prep, f"meeting {position} prep")
            link_offenders.extend(
                _check_links(root, prep, f"meeting {position} prep", warnings))
            prep_forms.add("v1")
        meetings.append({"time": time_text, "subject": subject,
                         "entity": entity, "prep": prep})
    if len(prep_forms) > 1:
        raise DailyNoteError(
            "meetings: every prep must use the same form — all strings (v1) "
            "or all {attendees, last_meeting, context} objects (v2)")
    v2_prep = prep_forms == {"v2"}
    raw_recap = payload.get("recap")
    recap_clean = None
    recap_text = None
    if isinstance(raw_recap, dict):
        if window is None:
            raise DailyNoteError(
                "recap_window is required with a structured (v2) recap — the "
                "CLI computes the glance's meeting count and window label from it")
        try:
            recap_clean, bad, warn = recap.validate(root, raw_recap)
        except recap.RecapError as exc:
            raise DailyNoteError(str(exc)) from exc
        link_offenders.extend(bad)
        warnings.extend(warn)
    else:
        recap_text = _clean_region_text(raw_recap, "recap")
        recap_text, stripped = _strip_model_banner(recap_text)
        if stripped:
            warnings.append(
                "recap: a Catch-up note callout in the payload was stripped — "
                "the CLI writes the banner itself")
        link_offenders.extend(_check_links(root, recap_text, "recap", warnings))
    meetings_note = payload.get("meetings_note")
    if meetings_note is not None:
        if meetings:
            raise DailyNoteError(
                "meetings_note only applies when meetings is empty")
        meetings_note = _clean_region_text(meetings_note, "meetings_note")
        if "\n" in meetings_note:
            raise DailyNoteError("meetings_note must be a single line")
        link_offenders.extend(
            _check_links(root, meetings_note, "meetings_note", warnings))
    if link_offenders:
        raise DailyNoteError("\n".join(link_offenders))
    contract = "v2" if recap_clean is not None or v2_prep else "v1"
    return ({"date": date_iso, "recap_clean": recap_clean,
             "recap_text": recap_text, "v2_prep": v2_prep,
             "contract": contract, "meetings": meetings,
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
    logs = root / vault.MESSAGES_DIR
    for path in sorted(logs.glob("*-messages.md")) if logs.is_dir() else []:
        noted = _iso_prefix_date(path.stem)
        if (noted is not None and path.stem == f"{noted.isoformat()}-messages"
                and start <= noted <= end):
            found.append((f"{vault.MESSAGES_DIR}/{path.name}", path))
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
    missed = dates.missed_runs(root, window["from"], window.get("count_to", window["to"]))
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

    Input files are hashed through `provenance.digest`, which normalises
    CRLF to LF first — the convention that module already states for exactly
    this reason. Hashing raw bytes made the stamp fork on line endings, so a
    Windows host (or a Mac<->Windows synced vault) recomputed a different
    digest for byte-identical content and regenerated a recap the vault
    owner had already read, on every run. Caught by the Windows CI job the
    first time a fixture carried a stamp at all. LF content hashes the same
    either way, so no already-stamped vault sees a change.
    """
    start, end = window["from"], window["to"]
    banner = _catchup_banner(root, window) or ""
    lines = [f"banner\t{hashlib.sha256(banner.encode('utf-8')).hexdigest()}"]
    for relpath, path in sorted(_fingerprint_inputs(root, start, end)):
        lines.append(f"{relpath}\t{provenance.digest(path.read_bytes())}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest[:_DIGEST_LENGTH]


def meetings_in_window(root: Path, start: date, end: date) -> int:
    """Meeting notes dated inside [start, end] — the same set the recap
    fingerprint hashes, so the glance never disagrees with the digest."""
    return sum(1 for relpath, _ in _fingerprint_inputs(root, start, end)
               if relpath.startswith(f"{vault.MEETINGS_DIR}/"))


def _window_label(window: dict) -> str:
    start, end = window["from"], window["to"]
    first = dates.DAY_NAMES[start.weekday()]
    last = dates.DAY_NAMES[end.weekday()]
    return first if start == end else f"{first}–{last}"


def _recap_body(root: Path, data: dict) -> str:
    banner = _catchup_banner(root, data["recap_window"])
    if data["recap_clean"] is not None:
        window = data["recap_window"]
        body = recap.render(
            root, data["recap_clean"],
            meetings=meetings_in_window(root, window["from"], window["to"]),
            window_label=_window_label(window))
    else:
        body = data["recap_text"]
    return f"{banner}\n\n{body}" if banner else body


def _marker_line(name: str, kind: str,
                 attrs: Optional[dict] = None) -> str:
    suffix = "".join(f" {key}={value}"
                     for key, value in sorted((attrs or {}).items()))
    return f"<!-- evening-sync:{name}:{kind}{suffix} -->"


def _region(name: str, content: str, attrs: Optional[dict] = None) -> str:
    return (f"{_marker_line(name, 'begin', attrs)}\n{content}\n"
            f"{_marker_line(name, 'end')}")


def _heading(meeting: dict, root: Optional[Path] = None, v2: bool = False) -> str:
    heading = f"{meeting['time']} — {meeting['subject']}"
    if meeting["entity"]:
        if v2 and root is not None:
            path = root / vault.ENTITIES_DIR / meeting["entity"] / "dossier.md"
            shown = links.display_name(path, "entity-name") or meeting["entity"]
            heading += f" · [[{links.path_target(root, path)}|{shown}]]"
        else:
            heading += f" · [[{meeting['entity']}]]"
    return heading


def _render(root: Path, data: dict, fingerprint: Optional[str]) -> str:
    date_iso = data["date"]
    attrs = {"inputs": fingerprint} if fingerprint else None
    parts = ["---", f"date: {date_iso}", "type: daily-note", "---", "",
             f"# {date_iso} · {_day_name(date_iso)}", "",
             _review_block(root), "",
             "## Recap", _region("recap", _recap_body(root, data), attrs), "",
             "## Meetings", ""]
    if data["meetings"]:
        chunks = []
        for meeting in data["meetings"]:
            heading = f"### {_heading(meeting, root, data['v2_prep'])}"
            if data["v2_prep"]:
                chunks.append("\n".join([
                    heading, PREP_HEADING, _region("prep", meeting["prep"]), "",
                    NOTES_BLOCK, "", ACTIONS_BLOCK]))
            else:
                chunks.append("\n".join([heading,
                                         _region("prep", meeting["prep"]), "- "]))
        parts.append("\n\n".join(chunks))
    else:
        parts.append(_region("prep",
                             data["meetings_note"] or NO_MEETINGS_LINE))
    parts += ["", "## Notes", "- ", ""]
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
        expected = [(m["time"], m["subject"], m["entity"]) for m in data["meetings"]]
        actual = [parse_heading(h) for h in prep_headings]
        if actual != expected:
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
    # A blank note is the one Obsidian creates on opening today (#263): write
    # the real note over it, as if it were not there.
    if path.is_file() and not vault.is_blank_note(path):
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
        "contract": data["contract"],
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
    if not path.is_file() or vault.is_blank_note(path):
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
    day_notes: List[str] = []
    other_lines: List[str] = []
    loose_actions: List[dict] = []
    current: Optional[dict] = None
    section = ""
    sub = ""
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
            sub = ""
            continue
        if line.startswith("# "):
            continue
        if line in _REVIEW_LINES:
            continue            # the embedded queues, not the owner's words
        if section == "Meetings" and line.startswith("### "):
            heading = line[4:].strip()
            parsed = parse_heading(heading)
            current = {
                "heading": heading,
                "time": parsed[0] if parsed else None,
                "subject": parsed[1] if parsed else heading,
                "entity": parsed[2] if parsed else None,
                "prep": None, "notes": [], "actions": [], "jottings": [],
            }
            meetings.append(current)
            sub = ""
            continue
        if section == "Meetings" and line.startswith("#### ") and current is not None:
            sub = line[5:].strip().lower()      # "prep" | "notes" | "actions" | anything
            continue
        stripped = line.strip()
        if not stripped:
            continue
        task = _TASK_RE.match(stripped)
        if task and section == "Meetings" and current is not None:
            text_value = task.group(2).strip()
            if text_value:
                current["actions"].append({"text": text_value, "done": task.group(1) != " "})
                current["jottings"].append(text_value)
            continue
        if task and task.group(2).strip():
            # An action outside any meeting block (#257). The line still
            # falls through, so the notes it was part of read as before.
            loose_actions.append({"text": task.group(2).strip(),
                                  "done": task.group(1) != " "})
        content = stripped[2:].strip() if stripped.startswith("- ") else (
            "" if stripped == "-" else stripped)
        if not content:
            continue   # the empty '- ' jot affordance
        if section in ("Notes", "End of day"):     # End of day: before structure 11
            day_notes.append(content)
        elif section == "Meetings" and current is not None:
            if sub == "prep":
                continue            # a prep line outside the markers is still prep
            current["notes"].append(content)
            current["jottings"].append(content)
        else:
            other_lines.append(content)
    return {
        "exists": True, "path": rel, "date": date_iso,
        "frontmatter": frontmatter, "recap": recap,
        "recap_inputs": recap_inputs, "meetings": meetings,
        "meetings_note": meetings_note,
        "notes": day_notes, "end_of_day": day_notes, "other_lines": other_lines,
        "loose_actions": loose_actions, "warnings": warnings,
    }
