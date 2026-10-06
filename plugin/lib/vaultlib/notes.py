"""The owner's own notes in 80-thoughts-ideas: which are ticked Include, which
projects they belong to, and the stamp once the evening run has read them.

Only frontmatter is ever written, one field node at a time; the body is the
owner's own writing and stays byte-identical. A note is never moved or
deleted — absorbing it is a stamp, not a filing step.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Set

from . import markdown, naming, vault

THOUGHTS_DIR = vault.THOUGHTS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
# A note longer than this is listed but not handed to the run: one runaway
# paste must not blow a project subagent's context.
MAX_BODY_CHARS = 40_000


class NotesError(Exception):
    """A notes argument the caller must fix."""


def _active_projects(root: Path) -> Set[str]:
    active: Set[str] = set()
    folder = root / PROJECTS_DIR
    for index in sorted(folder.glob("*/index.md")) if folder.is_dir() else []:
        try:
            data, _ = markdown.split_frontmatter(index.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if data.get("status") == "active" and data.get("slug"):
            active.add(str(data["slug"]))
    return active


def _project_list(value) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if str(item or "").strip()]


def _note_path(root: Path, rel: str) -> Path:
    folder = (root / THOUGHTS_DIR).resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(folder)
    except ValueError as exc:
        raise NotesError(f"--path {rel!r} is not a note under {THOUGHTS_DIR}/") from exc
    if path.suffix != ".md":
        raise NotesError(f"--path {rel!r} is not a markdown note")
    return root / rel


def harvest(root: Path) -> dict:
    found: List[dict] = []
    warnings: List[str] = []
    folder = root / THOUGHTS_DIR
    active = _active_projects(root)
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc} — not read tonight")
            continue
        if data.get("include") is not True:
            continue
        projects = _project_list(data.get("projects"))
        unknown = [p for p in projects if p not in active]
        if unknown:
            warnings.append(f"{rel}: projects {unknown} name no active project — ignored")
        entry = {
            "path": rel,
            "title": path.stem,
            "projects": [p for p in projects if p in active],
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"),
            "body": body,
        }
        if len(body) > MAX_BODY_CHARS:
            entry["body"] = None
            warnings.append(f"{rel}: {len(body)} characters, over the {MAX_BODY_CHARS} "
                            "cap — not read tonight; split it into shorter notes")
        found.append(entry)
    return {"notes": found, "warnings": warnings}


def assign(root: Path, rel: str, projects: List[str]) -> dict:
    path = _note_path(root, rel)
    active = _active_projects(root)
    for slug in projects:
        try:
            naming.validate_slug(slug)
        except ValueError as exc:
            raise NotesError(f"project {slug!r}: {exc}") from exc
        if slug not in active:
            raise NotesError(f"project {slug!r} is not an active project")
    if not path.is_file():
        raise NotesError(f"--path {rel!r} does not exist")
    text = path.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    current = _project_list(data.get("projects"))
    if current or not projects:
        return {"path": rel, "projects": current, "written": False}
    vault.atomic_write(path, markdown.upsert_scalar_field(
        text, "projects", "[{}]".format(", ".join(projects))))
    return {"path": rel, "projects": list(projects), "written": True}


def mark_absorbed(root: Path, rel: str, date_iso: str) -> dict:
    if not vault.ISO_DATE_RE.match(str(date_iso or "")):
        raise NotesError(f"--date {date_iso!r} must be ISO YYYY-MM-DD")
    path = _note_path(root, rel)
    if not path.is_file():
        return {"path": rel, "status": "missing"}
    text = path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "include", "false")
    updated = markdown.upsert_scalar_field(updated, "absorbed", date_iso)
    if updated == text:
        return {"path": rel, "status": "unchanged"}
    vault.atomic_write(path, updated)
    return {"path": rel, "status": "marked"}
