"""Triage in the chat (#271): list the meetings waiting for review, and apply
the owner's answers to them.

The same three moves as Meetings.base — Keep, Dismiss, edit the row — written
by the CLI, so an answer typed in the chat never becomes a hand edit of
frontmatter. Confirming is still `sync reconcile-reviews`' job: this module
only sets the tick, exactly as Obsidian would, so there is one confirm path.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from . import markdown, naming, vault

MEETINGS_DIR = vault.MEETINGS_DIR
ACTIONS = ("accept", "dismiss", "change")


class TriageError(Exception):
    """An argument the caller must fix (not a per-item refusal)."""


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _title(data: dict, body: str, stem: str) -> str:
    for line in body.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return str(data.get("calendar-subject") or stem)


def _when(value) -> str:
    """'Mon 12 Oct 09:00' (or 'Mon 12 Oct' for a date-only meeting), built
    here so the model never works out a weekday itself."""
    text = str(value or "")
    if len(text) >= 16 and text[10] == " ":
        text = text[:10] + "T" + text[11:]
    try:
        if "T" in text:
            moment = datetime.fromisoformat(text[:16])
            return f"{moment:%a} {moment.day} {moment:%b %H:%M}"
        day = date.fromisoformat(text[:10])
    except ValueError:
        return text
    return f"{day:%a} {day.day} {day:%b}"


def _project_index(root: Path, slug: str) -> Path:
    return root / vault.PROJECTS_DIR / slug / "index.md"


def _person_note(root: Path, slug: str) -> Path:
    return root / vault.PEOPLE_DIR / f"{slug}.md"


def _entity_dossier(root: Path, slug: str) -> Path:
    return root / vault.ENTITIES_DIR / slug / "dossier.md"


def _name(path: Path, key: str, slug: str) -> str:
    try:
        data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return slug
    return str(data.get(key) or slug)


def list_queue(root: Path) -> dict:
    items: List[dict] = []
    warnings: List[str] = []
    folder = root / MEETINGS_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        if data.get("review_status") != "needs-review" or data.get("archived") is True:
            continue
        projects = _as_list(data.get("projects"))
        attendees = _as_list(data.get("attendees"))
        entities = _as_list(data.get("entities"))
        items.append({
            "path": rel,
            "title": _title(data, body, path.stem),
            "date": str(data.get("date") or ""),
            "when": _when(data.get("date")),
            "type": data.get("type"),
            "projects": projects,
            "project_names": [_name(_project_index(root, s), "project-name", s)
                              for s in projects],
            "attendees": attendees,
            "attendee_names": [_name(_person_note(root, s), "person-name", s)
                               for s in attendees],
            "entities": entities,
            "entity_names": [_name(_entity_dossier(root, s), "entity-name", s)
                             for s in entities],
            "confidence": data.get("confidence"),
            "conflicts_with": data.get("conflicts-with") or None,
        })
    items.sort(key=lambda item: (item["date"], item["path"]))
    return {"items": items, "warnings": warnings}


def _flow_list(values: List[str]) -> str:
    return "[" + ", ".join(values) + "]"


def _check_slugs(root: Path, values, key: str, exists) -> Optional[str]:
    if not isinstance(values, list):
        return f"{key} must be a list of slugs"
    for value in values:
        try:
            naming.validate_slug(str(value))
        except ValueError as exc:
            return f"{key} entry {value!r}: {exc}"
        if not exists(root, str(value)).is_file():
            return f"{key} entry {value!r} matches no note — check the spelling"
    return None


def _apply_one(root: Path, item) -> Optional[str]:
    """Returns a refusal reason, or None once the item is written."""
    if not isinstance(item, dict):
        return "each item must be an object"
    action = item.get("action")
    if action not in ACTIONS:
        return f"action {action!r} is not one of {list(ACTIONS)}"
    raw = str(item.get("path") or "")
    target = (root / raw).resolve()
    meetings = (root / MEETINGS_DIR).resolve()
    if target.parent != meetings or target.suffix != ".md":
        return f"{raw!r} is not a meeting note in {MEETINGS_DIR}/"
    if not target.is_file():
        return f"{raw!r} does not exist"
    text = target.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    if data.get("review_status") != "needs-review":
        return f"{raw!r} is not waiting for review"
    flag = item.get("accept", True)
    if not isinstance(flag, bool):
        return "accept must be true or false"
    accept = action == "accept" or (action == "change" and flag)
    if accept and data.get("archived") is True:
        return f"{raw!r} is already dismissed"
    if accept and data.get("conflicts-with"):
        return (f"possible Duplicate of {data.get('conflicts-with')} — dismiss "
                "one of the two here, or merge them, clear '⚠ Duplicate of' "
                "in Obsidian, then accept")
    updated = text
    if action == "change":
        if not any(key in item for key in ("projects", "attendees", "entities")):
            return "change needs projects, attendees and/or entities"
        if "projects" in item:
            problem = _check_slugs(root, item["projects"], "projects", _project_index)
            if problem:
                return problem
            updated = markdown.upsert_scalar_field(
                updated, "projects", _flow_list(item["projects"]))
        if "attendees" in item:
            problem = _check_slugs(root, item["attendees"], "attendees", _person_note)
            if problem:
                return problem
            updated = markdown.upsert_scalar_field(
                updated, "attendees", _flow_list(item["attendees"]))
        if "entities" in item:
            # Only when the owner said so: changing a meeting to no project
            # asks whether it should also leave its entity's page (owner's
            # call, 2026-10-12) — an entity can be right without a project.
            problem = _check_slugs(root, item["entities"], "entities", _entity_dossier)
            if problem:
                return problem
            updated = markdown.upsert_scalar_field(
                updated, "entities", _flow_list(item["entities"]))
    if accept:
        updated = markdown.upsert_scalar_field(updated, "reviewed", "true")
    if action == "dismiss":
        updated = markdown.upsert_scalar_field(updated, "archived", "true")
    if updated != text:
        vault.atomic_write(target, updated)
    return None


def apply(root: Path, items) -> dict:
    if not isinstance(items, list):
        raise TriageError("--items must be a JSON array of {path, action, ...}")
    applied: List[dict] = []
    refused: List[dict] = []
    for item in items:
        try:
            reason = _apply_one(root, item)
        except (ValueError, OSError) as exc:
            reason = str(exc)
        path = item.get("path") if isinstance(item, dict) else None
        if reason is None:
            applied.append({"path": path, "action": item["action"]})
        else:
            refused.append({"path": path, "reason": reason})
    return {"applied": applied, "refused": refused}
