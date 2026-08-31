"""Project/person meeting metrics and the project-state update queue.

Port of the lab's build_update_queue.py, minus --auto-fix (decision-graph
drift repair is parked toward /health-check; v1 surfaces drift as warnings
only) and minus allowedTags (decision tags were dropped in P1a).

Only review_status: confirmed meetings count — triage is the quality gate.
Attendees are person slugs here, so metrics join on slug, and the vault owner
is excluded from key-people by slug — never by display name, which is why the
lab's name-prefix filter could not have ported.

The reverse self-check re-derives the queue by iterating meetings -> projects
(the opposite direction from the queue's per-project scan) so a silent skip
in either pass shows up as a warning instead of staying invisible — the bug
class that once cost the lab nine unqueued projects. It is deliberately not
the queue's predicate re-spelled: it sweeps at day granularity with `>=` and
suppresses a flag only on positive evidence — a `state-updated` timestamp
later than the meeting. A queue predicate that drops a meeting therefore
trips the sweep instead of agreeing with it (issue #98: the two passes shared
a strict day-granularity `>`, so the self-check was blind by construction).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import decision, markdown, naming, vault

MEETINGS_DIR = vault.MEETINGS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
PEOPLE_DIR = vault.PEOPLE_DIR
KEY_PEOPLE_WINDOW_DAYS = 90
TOP_KEY_PEOPLE = 3

# A type: note is a capture, not a meeting. It feeds project-state synthesis
# and decision capture — that is why captures route into 20-meetings/ at all
# — but it must never move a meeting count. meetings-7d feeds Projects.base;
# counting an email as a meeting is a quiet lie in a number a human reads.
NOT_A_MEETING = "note"


class UpdateQueueError(Exception):
    """An argument the caller must fix."""


def _parse_first_iso_date(value) -> Optional[date]:
    """First 10 chars as YYYY-MM-DD, or None. Meeting dates are ISO datetimes;
    last-updated is an ISO date; both reduce to the day."""
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_iso_datetime(value) -> Optional[datetime]:
    """A frontmatter date field as a full datetime, or None.

    A bare `YYYY-MM-DD` carries no time, so it reads as the *end* of that day
    (23:59:59): an untimed meeting must err toward queuing rather than sort
    itself before a timestamp written that afternoon and vanish. Anything
    fromisoformat accepts keeps its own time. A value that parses only as far
    as a leading day falls back to end-of-day for the same reason.
    """
    text = str(value or "").strip()
    if not text:
        return None
    end_of_day = time(23, 59, 59)
    if vault.ISO_DATE_RE.match(text):
        day = _parse_first_iso_date(text)
        return datetime.combine(day, end_of_day) if day else None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    day = _parse_first_iso_date(text)
    return datetime.combine(day, end_of_day) if day else None


def _slug_list(value, field: str, rel: str, warnings: List[str]) -> List[str]:
    """A frontmatter list field, with the scalar case named rather than split.

    `projects: alpha` parses as a string, and iterating a string yields its
    characters — the meeting would then join to no project at all, silently.
    One item is the obvious reading, so take it and say so.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        warnings.append(
            f"{rel}: frontmatter '{field}' is a scalar ({value!r}), not a "
            "list — read as a single item; write it as [a, b] or '- a' lines")
        return [value.strip()] if value.strip() else []
    warnings.append(
        f"{rel}: frontmatter '{field}' is {type(value).__name__}, not a list "
        f"({value!r}) — ignored; write it as [a, b] or '- a' lines")
    return []


def _index_meetings(root: Path) -> Tuple[List[dict], List[str]]:
    meetings: List[dict] = []
    warnings: List[str] = []
    folder = root / MEETINGS_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        meetings.append({
            "file": rel,
            "date": _parse_first_iso_date(data.get("date")),
            "datetime": _parse_iso_datetime(data.get("date")),
            "type": data.get("type"),
            "review_status": data.get("review_status"),
            "projects": _slug_list(data.get("projects"), "projects", rel,
                                   warnings),
            "attendees": _slug_list(data.get("attendees"), "attendees", rel,
                                    warnings),
        })
    return meetings, warnings


def _upsert_all(text: str, fields: Dict[str, str]) -> str:
    for field, value in fields.items():
        text = markdown.upsert_scalar_field(text, field, value)
    return text


def self_check(confirmed: List[dict], queued_slugs: Set[str],
               active_stamps: Dict[str, Optional[Tuple[
                   date, Optional[datetime]]]]) -> List[str]:
    """Independent reverse-direction verification of the queue.

    `active_stamps` maps every active project's slug to
    `(last-updated day, state-updated datetime or None)`, or to None when
    last-updated does not parse at all — such a project can never be queued,
    which is the loudest silent skip there is.

    The sweep is deliberately looser than the queue: day granularity, `>=`,
    and only one suppression — a `state-updated` timestamp strictly later
    than the meeting, which is positive evidence that the state was written
    after that meeting landed. Absent that evidence a same-day pair is
    flagged, so a queue predicate that drops it disagrees with this pass
    instead of matching it.
    """
    warnings: List[str] = []
    flagged: Set[str] = set()
    for meeting in confirmed:
        for slug in meeting["projects"]:
            if slug not in active_stamps:
                continue
            if slug in queued_slugs or slug in flagged:
                continue
            stamp = active_stamps[slug]
            if stamp is None:
                warnings.append(
                    f"SELF-CHECK: confirmed meeting '{meeting['file']}' "
                    f"references active project '{slug}' whose last-updated is "
                    "unparseable — it can never be queued; fix the field."
                )
                flagged.add(slug)
                continue
            last_day, state_dt = stamp
            if meeting["date"] < last_day:
                continue
            if state_dt is not None and meeting["datetime"] < state_dt:
                continue
            state_note = (f", state-updated {state_dt.isoformat(timespec='minutes')}"
                          if state_dt is not None else "")
            warnings.append(
                f"SELF-CHECK: confirmed meeting '{meeting['file']}' "
                f"({meeting['date'].isoformat()}) references active project "
                f"'{slug}' (last-updated {last_day.isoformat()}{state_note}) but "
                "the project was not queued — possible silent skip, investigate."
            )
            flagged.add(slug)
    return warnings


def run(root: Path, today: str, owner: str) -> dict:
    owner_slug = str(owner or "").strip()
    try:
        naming.validate_slug(owner_slug)
    except ValueError as exc:
        raise UpdateQueueError(f"--owner {owner!r}: {exc}") from exc
    if not (root / PEOPLE_DIR / f"{owner_slug}.md").is_file():
        raise UpdateQueueError(
            f"--owner {owner_slug!r} has no person note at "
            f"{PEOPLE_DIR}/{owner_slug}.md — the vault owner is excluded from "
            "key-people by slug, so a mistyped slug silently poisons the metric"
        )
    if not vault.ISO_DATE_RE.match(str(today or "").strip()):
        raise UpdateQueueError(f"--today {today!r} must be ISO YYYY-MM-DD")
    today_date = _parse_first_iso_date(today)
    if today_date is None:
        raise UpdateQueueError(f"--today {today!r} is not a real date")
    d7 = today_date - timedelta(days=7)
    d30 = today_date - timedelta(days=30)
    d90 = today_date - timedelta(days=KEY_PEOPLE_WINDOW_DAYS)

    meetings, warnings = _index_meetings(root)
    confirmed = [m for m in meetings
                 if m["review_status"] == "confirmed" and m["date"]]
    # confirmed drives the queue and the self-check; countable drives every
    # number written into a note. The two lists are deliberately different.
    countable = [m for m in confirmed if m["type"] != NOT_A_MEETING]

    queue: List[dict] = []
    active_stamps: Dict[str, Optional[Tuple[date, Optional[datetime]]]] = {}
    projects_written = 0
    projects_dir = root / PROJECTS_DIR
    for index_path in (sorted(projects_dir.glob("*/index.md"))
                       if projects_dir.is_dir() else []):
        rel = index_path.relative_to(root).as_posix()
        try:
            text = index_path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        slug = data.get("slug")
        if data.get("status") != "active" or not slug:
            continue
        slug = str(slug)

        for_project = [m for m in confirmed if slug in m["projects"]]
        countable_for_project = [m for m in countable
                                 if slug in m["projects"]]
        m7 = sum(1 for m in countable_for_project if m["date"] > d7)
        m30 = sum(1 for m in countable_for_project if m["date"] > d30)
        counts: Dict[str, int] = {}
        for meeting in countable_for_project:
            if meeting["date"] > d90:
                for attendee in meeting["attendees"]:
                    if attendee != owner_slug:
                        counts[attendee] = counts.get(attendee, 0) + 1
        key_people = [s for s, _ in sorted(counts.items(),
                                           key=lambda kv: (-kv[1], kv[0]))
                      ][:TOP_KEY_PEOPLE]
        updated = _upsert_all(text, {
            "meetings-7d": str(m7),
            "meetings-30d": str(m30),
            "key-people": "[{}]".format(", ".join(key_people)),
        })
        if updated != text:
            vault.atomic_write(index_path, updated)
        projects_written += 1

        last_updated = _parse_first_iso_date(data.get("last-updated"))
        if last_updated is None:
            active_stamps[slug] = None
            warnings.append(
                f"{rel}: unparseable last-updated "
                f"{data.get('last-updated')!r} — project cannot be queued"
            )
            continue

        # The threshold is a moment, not a day. `state-updated` is the minute
        # `project touch` wrote the state; without it the day at 00:00 is the
        # floor, which makes the comparison day-granularity `>=` — erring
        # toward one extra queue cycle rather than dropping a same-day meeting
        # forever (issue #98).
        raw_state = data.get("state-updated")
        state_updated = _parse_iso_datetime(raw_state)
        if raw_state is not None and state_updated is None:
            warnings.append(
                f"{rel}: unparseable state-updated {raw_state!r} for project "
                f"'{slug}' — falling back to the last-updated day; rewrite it "
                "as YYYY-MM-DDTHH:MM or delete it"
            )
        active_stamps[slug] = (last_updated, state_updated)
        threshold = (state_updated if state_updated is not None
                     else datetime.combine(last_updated, time.min))
        new_meetings = [m for m in for_project if m["datetime"] >= threshold]
        if new_meetings:
            queue.append({
                "slug": slug,
                "indexPath": rel,
                "decisionsDir": f"{PROJECTS_DIR}/{slug}/decisions/",
                "lastUpdated": last_updated.isoformat(),
                "stateUpdated": (state_updated.isoformat(timespec="minutes")
                                 if state_updated is not None else None),
                "newCount": len(new_meetings),
                "newFiles": [m["file"] for m in new_meetings],
                "existingDecisions":
                    decision.list_decisions(root, slug)["decisions"],
            })
    queue.sort(key=lambda entry: (-entry["newCount"], entry["slug"]))

    people_written = 0
    people_dir = root / PEOPLE_DIR
    for path in sorted(people_dir.glob("*.md")) if people_dir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        slug = data.get("slug")
        if not slug:
            warnings.append(f"{rel}: no slug — metrics skipped")
            continue
        slug = str(slug)
        m7 = sum(1 for m in countable
                 if slug in m["attendees"] and m["date"] > d7)
        m30 = sum(1 for m in countable
                  if slug in m["attendees"] and m["date"] > d30)
        updated = _upsert_all(text, {"meetings-7d": str(m7),
                                     "meetings-30d": str(m30)})
        if updated != text:
            vault.atomic_write(path, updated)
        people_written += 1

    warnings.extend(self_check(confirmed, {entry["slug"] for entry in queue},
                               active_stamps))
    return {
        "today": today_date.isoformat(),
        "owner": owner_slug,
        "meetingsIndexed": len(meetings),
        "confirmedMeetings": len(confirmed),
        "projectsNeedingUpdate": queue,
        "metricsWritten": {"projects": projects_written,
                           "people": people_written},
        "warnings": warnings,
    }
