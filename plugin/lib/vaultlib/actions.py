"""Actions (#257): the owner's `- [ ]` lines, followed up as notes.

The daily note is where an action is written and the archive of the day, so
it is only ever read. Each new line becomes a note in 65-actions/, which is
what Actions.base lists, groups by project and sorts by deadline. `harvest`
says which lines are new (with the meeting they sit under, as evidence for
the project) and closes a note whose line was ticked since. `create` writes
the notes: the deadline arrives as the owner's phrase and is resolved here
against the daily note's date, so no model ever does date arithmetic.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dailynote, dates, markdown, naming, schema, vault

ACTIONS_DIR = vault.ACTIONS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
QUOTE_KEYS = frozenset({"action", "source"})
# A recap window is days, a catch-up a few weeks; anything longer is a typo.
MAX_WINDOW_DAYS = 62
_WS_RE = re.compile(r"\s+")
_SOURCE_RE = re.compile(r"\A\[\[(?:60-daily-notes/)?(\d{4}-\d{2}-\d{2})(?:\.md)?(?:\|[^\]]*)?\]\]\Z")


class ActionsError(Exception):
    """An actions argument or item the caller must fix."""


def _key(source: Optional[str], text: str) -> Tuple[Optional[str], str]:
    """Identity of a line: its daily note and its words, case and spacing aside."""
    return source, _WS_RE.sub(" ", text).strip().casefold()


def _date(raw, label: str) -> date:
    text = str(raw or "")
    if not vault.ISO_DATE_RE.match(text):
        raise ActionsError(f"{label} {raw!r} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ActionsError(f"{label} {raw!r} is not a real date") from exc


def _projects(root: Path) -> Dict[str, dict]:
    """Active projects: slug -> {name, entity}."""
    found: Dict[str, dict] = {}
    folder = root / PROJECTS_DIR
    for index in sorted(folder.glob("*/index.md")) if folder.is_dir() else []:
        try:
            data, _ = markdown.split_frontmatter(index.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        slug = data.get("slug")
        if data.get("status") == "active" and slug:
            found[str(slug)] = {"name": str(data.get("project-name") or slug),
                                "entity": str(data.get("entity") or "")}
    return found


def _recorded(root: Path) -> List[dict]:
    """Every action note: path, frontmatter, text, source date, identity."""
    found: List[dict] = []
    folder = root / ACTIONS_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError):
            continue
        if data.get("type") != "action":
            continue
        match = _SOURCE_RE.match(str(data.get("source") or ""))
        source = match.group(1) if match else None
        words = str(data.get("action") or "")
        found.append({"path": path, "text": text, "data": data, "source": source,
                      "key": _key(source, words) if words else None})
    return found


def _lines(root: Path, date_iso: str) -> List[dict]:
    """The action lines in one daily note, each with its meeting, if any."""
    note = dailynote.read(root, date_iso)
    if not note.get("exists"):
        return []
    lines = []
    for meeting in note["meetings"]:
        for action in meeting["actions"]:
            lines.append({**action, "meeting": meeting["subject"],
                          "entity": meeting["entity"]})
    for action in note["loose_actions"]:
        lines.append({**action, "meeting": None, "entity": None})
    return lines


def harvest(root: Path, from_iso: str, to_iso: str) -> dict:
    start, end = _date(from_iso, "--from"), _date(to_iso, "--to")
    if end < start:
        raise ActionsError(f"--from {from_iso} is after --to {to_iso}")
    if (end - start).days > MAX_WINDOW_DAYS:
        raise ActionsError(f"--from {from_iso} to --to {to_iso} spans more than "
                           f"{MAX_WINDOW_DAYS} days")
    projects = _projects(root)
    recorded = _recorded(root)
    known = {r["key"] for r in recorded if r["key"]}

    new: List[dict] = []
    seen = set(known)
    day = start
    while day <= end:
        source = day.isoformat()
        for line in _lines(root, source):
            key = _key(source, line["text"])
            if line["done"] or key in seen:
                continue
            seen.add(key)
            entity = line["entity"]
            new.append({
                "source": source, "text": line["text"], "meeting": line["meeting"],
                "entity": entity,
                "entity_projects": [{"slug": slug, "name": info["name"]}
                                    for slug, info in sorted(projects.items())
                                    if entity and info["entity"] == entity],
            })
        day += timedelta(days=1)

    # A tick in the daily note closes the note, on whatever day it was given.
    closed: List[str] = []
    ticked_by_day: Dict[str, set] = {}
    for item in recorded:
        if item["data"].get("done") is True or not item["source"] or not item["key"]:
            continue
        if item["source"] not in ticked_by_day:
            ticked_by_day[item["source"]] = {
                _key(item["source"], line["text"])
                for line in _lines(root, item["source"]) if line["done"]}
        if item["key"] in ticked_by_day[item["source"]]:
            vault.atomic_write(item["path"],
                               markdown.upsert_scalar_field(item["text"], "done", "true"))
            closed.append(item["path"].relative_to(root).as_posix())
    return {"new": new, "closed": closed, "warnings": []}


def _validated(item, index: int) -> dict:
    where = f"item {index}"
    if not isinstance(item, dict):
        raise ActionsError(f"{where} must be an object with at least 'text'")
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ActionsError(f"{where}: 'text' is required — the action as written")
    if "\n" in text or "\r" in text:
        raise ActionsError(f"{where}: 'text' must be one line")
    source = item.get("source")
    if source is not None:
        _date(source, f"{where}: 'source'")
    project = item.get("project")
    if project is not None:
        try:
            naming.validate_slug(str(project))
        except ValueError as exc:
            raise ActionsError(f"{where}: 'project' {project!r}: {exc}") from exc
    due = item.get("due")
    if due is not None and not isinstance(due, str):
        raise ActionsError(f"{where}: 'due' must be the deadline phrase as written")
    return {"text": _WS_RE.sub(" ", text).strip(), "source": source,
            "project": project, "due": due}


def _free_stem(folder: Path, stem: str) -> str:
    candidate, counter = stem, 2
    while (folder / f"{candidate}.md").exists():
        candidate, counter = f"{stem}-{counter}", counter + 1
    return candidate


def create(root: Path, items, today: Optional[str] = None) -> dict:
    if not isinstance(items, list):
        raise ActionsError("the items file must hold a JSON list of actions")
    checked = [_validated(item, i) for i, item in enumerate(items)]
    today_iso = vault.today_iso(today)
    projects = _projects(root)
    known = {r["key"]: r["path"] for r in _recorded(root) if r["key"]}
    folder = root / ACTIONS_DIR
    created: List[dict] = []
    skipped: List[dict] = []
    warnings: List[str] = []
    for item in checked:
        key = _key(item["source"], item["text"])
        if key in known:
            skipped.append({"text": item["text"], "source": item["source"],
                            "path": known[key].relative_to(root).as_posix()})
            continue
        project = item["project"]
        if project is not None and project not in projects:
            warnings.append(f"{item['text']!r}: {project!r} is not an active project "
                            "— left for the owner to fill in")
            project = None
        anchor_iso = item["source"] or today_iso
        due = None
        if item["due"]:
            resolved = dates.resolve_due(item["due"], date.fromisoformat(anchor_iso))
            if resolved is None:
                warnings.append(f"{item['text']!r}: deadline {item['due']!r} is not a "
                                "date the CLI can read — left open")
            else:
                due = resolved.isoformat()
        try:
            slug = naming.slugify(item["text"])
        except ValueError:
            slug = "action"
        stem = _free_stem(folder, f"{anchor_iso}-{slug}")
        frontmatter = {"type": "action", "action": item["text"], "project": project,
                       "due": due, "done": False}
        if item["source"]:
            frontmatter["source"] = f"[[{item['source']}]]"
        frontmatter["created"] = today_iso
        problems = schema.validate("action", frontmatter)
        if problems:
            raise ActionsError("refusing to write non-conformant action frontmatter: "
                               + "; ".join(problems))
        path = folder / f"{stem}.md"
        vault.atomic_create(path, markdown.emit_frontmatter(frontmatter, QUOTE_KEYS))
        known[key] = path
        created.append({"path": path.relative_to(root).as_posix(), "action": item["text"],
                        "project": project, "due": due})
    return {"created": created, "skipped": skipped, "warnings": warnings}
