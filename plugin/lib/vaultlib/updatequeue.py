"""Project/person meeting metrics and the project-state update queue.

Port of the lab's build_update_queue.py, minus --auto-fix (decision-graph
drift repair is parked toward /health-check; v1 surfaces drift as warnings
only) and minus allowedTags (decision tags were dropped in P1a).

Only review_status: confirmed meetings count — triage is the quality gate.
Attendees are person slugs here, so metrics join on slug, and the executive
is excluded from key-people by slug — never by display name, which is why the
lab's name-prefix filter could not have ported.

The reverse self-check re-derives the queue by iterating meetings -> projects
(the opposite direction from the queue's per-project scan) so a silent skip
in either pass shows up as a warning instead of staying invisible — the bug
class that once cost the lab nine unqueued projects.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import decision, markdown, naming, vault

MEETINGS_DIR = vault.MEETINGS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
PEOPLE_DIR = vault.PEOPLE_DIR
KEY_PEOPLE_WINDOW_DAYS = 90
TOP_KEY_PEOPLE = 3


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
               active_last_updated: Dict[str, Optional[date]]) -> List[str]:
    """Independent reverse-direction verification of the queue."""
    warnings: List[str] = []
    flagged: Set[str] = set()
    for meeting in confirmed:
        for slug in meeting["projects"]:
            if slug in queued_slugs or slug in flagged:
                continue
            last_updated = active_last_updated.get(slug)
            if last_updated is None:
                continue
            if meeting["date"] > last_updated:
                warnings.append(
                    f"SELF-CHECK: confirmed meeting '{meeting['file']}' "
                    f"({meeting['date'].isoformat()}) references active project "
                    f"'{slug}' (last-updated {last_updated.isoformat()}) but the "
                    "project was not queued — possible silent skip, investigate."
                )
                flagged.add(slug)
    return warnings


def run(root: Path, today: str, executive: str) -> dict:
    exec_slug = str(executive or "").strip()
    try:
        naming.validate_slug(exec_slug)
    except ValueError as exc:
        raise UpdateQueueError(f"--executive {executive!r}: {exc}") from exc
    if not (root / PEOPLE_DIR / f"{exec_slug}.md").is_file():
        raise UpdateQueueError(
            f"--executive {exec_slug!r} has no person note at "
            f"{PEOPLE_DIR}/{exec_slug}.md — the executive is excluded from "
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

    queue: List[dict] = []
    active_last_updated: Dict[str, Optional[date]] = {}
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
        m7 = sum(1 for m in for_project if m["date"] > d7)
        m30 = sum(1 for m in for_project if m["date"] > d30)
        counts: Dict[str, int] = {}
        for meeting in for_project:
            if meeting["date"] > d90:
                for attendee in meeting["attendees"]:
                    if attendee != exec_slug:
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
        active_last_updated[slug] = last_updated
        if last_updated is None:
            warnings.append(
                f"{rel}: unparseable last-updated "
                f"{data.get('last-updated')!r} — project cannot be queued"
            )
            continue
        new_meetings = [m for m in for_project if m["date"] > last_updated]
        if new_meetings:
            queue.append({
                "slug": slug,
                "indexPath": rel,
                "decisionsDir": f"{PROJECTS_DIR}/{slug}/decisions/",
                "lastUpdated": last_updated.isoformat(),
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
        m7 = sum(1 for m in confirmed
                 if slug in m["attendees"] and m["date"] > d7)
        m30 = sum(1 for m in confirmed
                  if slug in m["attendees"] and m["date"] > d30)
        updated = _upsert_all(text, {"meetings-7d": str(m7),
                                     "meetings-30d": str(m30)})
        if updated != text:
            vault.atomic_write(path, updated)
        people_written += 1

    warnings.extend(self_check(confirmed, {entry["slug"] for entry in queue},
                               active_last_updated))
    return {
        "today": today_date.isoformat(),
        "executive": exec_slug,
        "meetingsIndexed": len(meetings),
        "confirmedMeetings": len(confirmed),
        "projectsNeedingUpdate": queue,
        "metricsWritten": {"projects": projects_written,
                           "people": people_written},
        "warnings": warnings,
    }
