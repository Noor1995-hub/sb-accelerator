"""Vault health metrics: content-free by construction.

report() answers "is the machinery running" — meeting cadence, review
backlog, daily-note coverage, inbox pressure, staleness — without ever
touching a note's title, name, or filename. Every value it produces is a
count, a rate, an age, a date, or a version string. render() interpolates
only those values into markdown, so the two functions together have no code
path that can leak vault content into a report a consultant might paste
into a client channel.

The two free-text-shaped fields this module reads — a meeting's
`source-recording-id` prefix and a decision's `status` — are only
enum-checked on the CLI write path; an Obsidian property edit bypasses that
and can put anything in either field. So this module never trusts either
value as a dict key on faith: `_by_source` keeps only prefixes in
`syncjob.NAMESPACES`, and `_decisions` keeps only statuses in
`schema.enum_values("decision", "status")`, folding everything else into
`"unknown"` before it can become a key that render() would print. That fold
is what makes the content-free claim true of the code, not of an assumption
about how the field got written.

This is a read-only accounting pass: unlike `sync update-queue`, which
writes meetings-7d/30d and key-people into project and person notes, health
never writes into a note. Its own "update-queue warning count" stand-in
(`meetings.without_projects`) is derived the same way but never persisted —
running `sync update-queue` is what actually clears that queue.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import markdown, provenance, schema, syncjob, template, vault

MEETINGS_DIR = vault.MEETINGS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
ENTITIES_DIR = vault.ENTITIES_DIR
INBOX_DIR = vault.INBOX_DIR
DAILY_NOTES_DIR = vault.DAILY_NOTES_DIR

# Reuse syncjob's skip-list location rather than re-deriving it: it is the
# one path that names the file, and a future rename of it should not need a
# second edit here.
SKIP_FILE_RELPATH = syncjob.SKIP_FILE_RELPATH

HEALTH_REPORTS_DIR = Path("99-workflow-config") / "health-reports"

MACHINE_REGION_MARKER = "<!-- evening-sync:"
# Excluded the same way syncjob's inbox scan excludes it: a placeholder file,
# never a capture candidate.
_IGNORED_INBOX_NAMES = {"README.md"}
STALE_WINDOW_DAYS = 30
DEFAULT_WINDOW_DAYS = 28


class HealthError(Exception):
    """A `report()` argument the caller must fix."""


def _parse_date(value) -> Optional[date]:
    """First 10 chars as YYYY-MM-DD, or None. Meeting dates are ISO
    datetimes; this reduces them to the day, same as updatequeue."""
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_list(value) -> List[str]:
    """A frontmatter list field, tolerant of the scalar case.

    Health only counts membership, so a mis-typed scalar (`projects: alpha`
    instead of `[alpha]`) is read as one item rather than iterated into
    characters — the same rule updatequeue applies, minus the warning
    (health has no channel to carry one back through).
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


class _Counter:
    """A running total, not a list — nothing here to surface a path from.

    The frontmatter readers below only ever need "how many", so this counts
    rather than collecting the relpaths that failed; that also forecloses a
    future `render()` change that might have been tempted to print the list.
    """

    def __init__(self) -> None:
        self.value = 0

    def bump(self) -> None:
        self.value += 1


def _read_frontmatter(path: Path, unparsed: _Counter) -> Optional[dict]:
    try:
        data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        unparsed.bump()
        return None
    return data


def _index_meetings(root: Path, unparsed: _Counter) -> List[dict]:
    meetings: List[dict] = []
    folder = root / MEETINGS_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        data = _read_frontmatter(path, unparsed)
        if data is None:
            continue
        source_id = data.get("source-recording-id")
        meetings.append({
            "date": _parse_date(data.get("date")),
            "review_status": data.get("review_status"),
            "projects": _as_list(data.get("projects")),
            "entities": _as_list(data.get("entities")),
            "source_prefix": (str(source_id).split(":", 1)[0]
                              if source_id else None),
        })
    return meetings


def _per_week(in_window: List[dict]) -> List[Dict[str, object]]:
    """ISO (Monday-start) week buckets, oldest first. Only weeks that carry
    at least one meeting are listed — there is no fixed calendar to pad
    against, unlike by_source's fixed namespace set."""
    weeks: Dict[date, int] = {}
    for meeting in in_window:
        day = meeting["date"]
        monday = day - timedelta(days=day.weekday())
        weeks[monday] = weeks.get(monday, 0) + 1
    return [{"week_start": monday.isoformat(), "count": count}
            for monday, count in sorted(weeks.items())]


def _by_source(in_window: List[dict]) -> Dict[str, int]:
    """Bucket by source-recording-id prefix, allow-listed against
    syncjob.NAMESPACES.

    The enum is only enforced on the CLI write path; a hand-edited property
    in Obsidian can put anything before the `:`. Any prefix outside the
    known namespaces — like an absent one — folds into "unknown" rather
    than becoming a dict key render() would print verbatim.
    """
    counts = {name: 0 for name in (*syncjob.NAMESPACES, "unknown")}
    for meeting in in_window:
        prefix = meeting["source_prefix"]
        key = prefix if prefix in syncjob.NAMESPACES else "unknown"
        counts[key] += 1
    return counts


def _daily_notes(root: Path, window_start: date, window_end: date) -> dict:
    working_days = sum(
        1 for offset in range((window_end - window_start).days + 1)
        if (window_start + timedelta(days=offset)).weekday() < 5
    )
    with_machine_regions = 0
    folder = root / DAILY_NOTES_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if not vault.ISO_DATE_RE.match(path.stem):
            continue
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not (window_start <= day <= window_end and day.weekday() < 5):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if MACHINE_REGION_MARKER in text:
            with_machine_regions += 1
    coverage_pct = (round(with_machine_regions / working_days * 100)
                    if working_days else 0)
    return {"working_days": working_days,
            "with_machine_regions": with_machine_regions,
            "coverage_pct": coverage_pct}


def _inbox_pending(root: Path) -> int:
    folder = root / INBOX_DIR
    if not folder.is_dir():
        return 0
    count = 0
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in _IGNORED_INBOX_NAMES or path.name.startswith("."):
            continue
        count += 1
    return count


def _projects(root: Path, meetings: List[dict], cutoff: date,
              unparsed: _Counter) -> dict:
    folder = root / PROJECTS_DIR
    total = 0
    stale = 0
    for project_dir in sorted(p for p in folder.iterdir() if p.is_dir()) \
            if folder.is_dir() else []:
        index_path = project_dir / "index.md"
        if not index_path.is_file():
            continue
        data = _read_frontmatter(index_path, unparsed)
        if data is None:
            continue
        slug = str(data.get("slug") or project_dir.name)
        total += 1
        last_ref = max(
            (m["date"] for m in meetings
             if m["date"] is not None and slug in m["projects"]),
            default=None,
        )
        # Inclusive like the rest of this module's windows: a meeting
        # exactly `cutoff` days old is still recent, so only a last
        # reference strictly older than the cutoff counts as stale.
        if last_ref is None or last_ref < cutoff:
            stale += 1
    return {"total": total, "stale_30d": stale}


def _entities(root: Path, meetings: List[dict], cutoff: date,
              unparsed: _Counter) -> dict:
    folder = root / ENTITIES_DIR
    total = 0
    no_recent = 0
    for entity_dir in sorted(p for p in folder.iterdir() if p.is_dir()) \
            if folder.is_dir() else []:
        dossier_path = entity_dir / "dossier.md"
        if not dossier_path.is_file():
            continue
        data = _read_frontmatter(dossier_path, unparsed)
        if data is None:
            continue
        slug = str(data.get("slug") or entity_dir.name)
        total += 1
        last_ref = max(
            (m["date"] for m in meetings
             if m["date"] is not None and slug in m["entities"]),
            default=None,
        )
        # Same inclusive boundary as _projects: exactly-30-days-old is recent.
        if last_ref is None or last_ref < cutoff:
            no_recent += 1
    return {"total": total, "no_meeting_30d": no_recent}


def _decisions(root: Path, unparsed: _Counter) -> Dict[str, int]:
    """Count decisions by `status`, allow-listed against the ontology.

    `schema.enum_values("decision", "status")` is the same allow-list the
    write path enforces; a hand-edited status outside it (or missing
    entirely) folds into "unknown" rather than becoming a dict key
    render() would print verbatim. The allow-list keys are zero-filled so
    the rendered table has a stable shape regardless of which statuses are
    actually present.
    """
    allowed = schema.enum_values("decision", "status")
    counts: Dict[str, int] = {name: 0 for name in allowed}
    counts["unknown"] = 0
    folder = root / PROJECTS_DIR
    for path in sorted(folder.glob("*/decisions/*.md")) if folder.is_dir() else []:
        data = _read_frontmatter(path, unparsed)
        if data is None:
            continue
        status = data.get("status")
        key = status if status in allowed else "unknown"
        counts[key] += 1
    return counts


_EMPTY_PROVENANCE_BLOCK = {
    "recorded": False, "malformed": False,
    "provisioned_at": None, "provisioned_plugin_version": None,
    "last_event": None, "last_event_at": None,
    "recorded_plugin_version": None, "plugin_drift": "unknown",
}


def _provenance_block(root: Path) -> dict:
    """provenance.json folded to counts/strings only — never raises, and a
    malformed file folds to `recorded: false, malformed: true` rather than
    surfacing whatever ProvenanceError says (that message could quote the
    file's own bytes back)."""
    try:
        data = provenance.read(root)
    except provenance.ProvenanceError:
        return {**_EMPTY_PROVENANCE_BLOCK, "malformed": True}
    if data is None:
        return dict(_EMPTY_PROVENANCE_BLOCK)
    events = data.get("events") or []
    provision_event = next(
        (e for e in events if e.get("event") == "provision"), None)
    last_event = events[-1] if events else None
    recorded_version = last_event.get("plugin_version") if last_event else None
    return {
        "recorded": True,
        "malformed": False,
        "provisioned_at": provision_event.get("at") if provision_event else None,
        "provisioned_plugin_version": (provision_event.get("plugin_version")
                                       if provision_event else None),
        "last_event": last_event.get("event") if last_event else None,
        "last_event_at": last_event.get("at") if last_event else None,
        "recorded_plugin_version": recorded_version,
        "plugin_drift": provenance.drift(data),
    }


_EMPTY_TEMPLATE_BLOCK = {
    "managed": 0, "current": 0, "refresh": 0, "needs_consent": 0,
    "missing": 0, "blocked": 0, "baseline": "unknown",
}


def _template_block(root: Path) -> dict:
    """template.status() folded to counts only — no relpaths, per the
    content-free contract this module keeps for every block. A malformed
    provenance.json (template.status reads it via provenance.read) or a
    managed relpath missing from the shipped template both fold to the
    empty block rather than raising: health must never fail because the
    provenance or template state underneath it is broken."""
    try:
        result = template.status(root)
    except (provenance.ProvenanceError, template.TemplateError):
        return dict(_EMPTY_TEMPLATE_BLOCK)
    counts = result["counts"]
    return {
        "managed": len(result["files"]),
        "current": counts.get("current", 0),
        "refresh": counts.get("refresh", 0),
        "needs_consent": counts.get("needs-consent", 0),
        "missing": counts.get("missing", 0),
        "blocked": counts.get("blocked", 0),
        "baseline": result["baseline"],
    }


def _resolve_window(window) -> int:
    try:
        window_days = int(window)
    except (TypeError, ValueError) as exc:
        raise HealthError(
            f"--window {window!r} must be a positive integer") from exc
    if window_days <= 0:
        raise HealthError(
            f"--window {window!r} must be a positive integer")
    return window_days


def report(root: Path, today: str, window: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Content-free vault health metrics for the window ending on `today`.

    Every value is a count, a rate, an age, a date, or a version string —
    never a title, name, or filename. Unreadable frontmatter anywhere is
    counted under `"unparsed"`, never raised.
    """
    if not vault.ISO_DATE_RE.match(str(today or "").strip()):
        raise HealthError(f"today {today!r} must be ISO YYYY-MM-DD")
    try:
        today_date = date.fromisoformat(today)
    except ValueError as exc:
        raise HealthError(f"today {today!r} is not a real date") from exc
    window_days = _resolve_window(window)

    window_start = today_date - timedelta(days=window_days)
    cutoff_30d = today_date - timedelta(days=STALE_WINDOW_DAYS)

    unparsed = _Counter()
    meetings = _index_meetings(root, unparsed)
    in_window = [m for m in meetings
                 if m["date"] is not None
                 and window_start <= m["date"] <= today_date]

    result = {
        "generated": today_date.isoformat(),
        "window_days": window_days,
        "plugin_version": vault.plugin_version(),
        "structure_version": vault.structure_version(root),
        "meetings": {
            "in_window": len(in_window),
            "per_week": _per_week(in_window),
            "by_source": _by_source(in_window),
            "without_projects": sum(1 for m in in_window if not m["projects"]),
            "needs_review": sum(1 for m in in_window
                                if m["review_status"] == "needs-review"),
        },
        "daily_notes": _daily_notes(root, window_start, today_date),
        "inbox_pending": _inbox_pending(root),
        "skip_list_size": len(syncjob.read_skip_records(root)),
        "projects": _projects(root, meetings, cutoff_30d, unparsed),
        "entities": _entities(root, meetings, cutoff_30d, unparsed),
        "decisions": _decisions(root, unparsed),
        "unparsed": unparsed.value,
        "provenance": _provenance_block(root),
        "claude_link": provenance.claude_link_state(root),
        "template": _template_block(root),
    }
    return result


def _table(rows: List[Tuple[str, object]]) -> List[str]:
    lines = ["| metric | value |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return lines


def render(data: dict) -> str:
    """Fixed markdown template. Interpolates only numbers/versions/dates —
    never a filename or note field, by construction of what `report()`
    hands it."""
    lines: List[str] = [
        f"# Health Report — {data['generated']}",
        "",
        f"Window: {data['window_days']} days · "
        f"plugin {data['plugin_version']} · "
        f"structure {data['structure_version']}",
        "",
        "## Meetings",
    ]
    lines += _table([
        ("in_window", data["meetings"]["in_window"]),
        ("without_projects", data["meetings"]["without_projects"]),
        ("needs_review", data["meetings"]["needs_review"]),
    ])
    lines += ["", "### Meetings per week", "| week_start | count |", "|---|---|"]
    lines += [f"| {entry['week_start']} | {entry['count']} |"
              for entry in data["meetings"]["per_week"]]
    lines += ["", "### Meetings by source", "| source | count |", "|---|---|"]
    lines += [f"| {source} | {count} |"
              for source, count in sorted(data["meetings"]["by_source"].items())]
    lines += ["", "## Daily notes"]
    lines += _table([
        ("working_days", data["daily_notes"]["working_days"]),
        ("with_machine_regions", data["daily_notes"]["with_machine_regions"]),
        ("coverage_pct", data["daily_notes"]["coverage_pct"]),
    ])
    lines += ["", "## Inbox & sync"]
    lines += _table([
        ("inbox_pending", data["inbox_pending"]),
        ("skip_list_size", data["skip_list_size"]),
    ])
    lines += ["", "## Projects"]
    lines += _table([
        ("total", data["projects"]["total"]),
        ("stale_30d", data["projects"]["stale_30d"]),
    ])
    lines += ["", "## Entities"]
    lines += _table([
        ("total", data["entities"]["total"]),
        ("no_meeting_30d", data["entities"]["no_meeting_30d"]),
    ])
    lines += ["", "## Decisions", "| status | count |", "|---|---|"]
    lines += [f"| {status} | {count} |"
              for status, count in sorted(data["decisions"].items())]
    lines += ["", "## Unparsed"]
    lines += _table([("unparsed", data["unparsed"])])
    lines += ["", "## Provenance"]
    lines += _table([
        ("recorded", data["provenance"]["recorded"]),
        ("malformed", data["provenance"]["malformed"]),
        ("provisioned_at", data["provenance"]["provisioned_at"]),
        ("provisioned_plugin_version", data["provenance"]["provisioned_plugin_version"]),
        ("last_event", data["provenance"]["last_event"]),
        ("last_event_at", data["provenance"]["last_event_at"]),
        ("recorded_plugin_version", data["provenance"]["recorded_plugin_version"]),
        ("plugin_drift", data["provenance"]["plugin_drift"]),
        ("claude_link_is_symlink", data["claude_link"]["is_symlink"]),
        ("claude_link_state", data["claude_link"]["state"]),
    ])
    lines += ["", "## Template files"]
    lines += _table([
        ("managed", data["template"]["managed"]),
        ("current", data["template"]["current"]),
        ("refresh", data["template"]["refresh"]),
        ("needs_consent", data["template"]["needs_consent"]),
        ("missing", data["template"]["missing"]),
        ("blocked", data["template"]["blocked"]),
        ("baseline", data["template"]["baseline"]),
    ])
    lines.append("")
    return "\n".join(lines) + "\n"


def write_report(root: Path, data: dict) -> str:
    """Render and atomic-write to 99-workflow-config/health-reports/{today}.md.

    Returns the vault-relative path, so the caller can add it to the result
    without re-deriving the naming rule.
    """
    relpath = HEALTH_REPORTS_DIR / f"{data['generated']}.md"
    vault.atomic_write(root / relpath, render(data))
    return relpath.as_posix()
