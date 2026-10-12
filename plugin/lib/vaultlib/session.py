"""Session records (#267): what a conversation with Claude added to the brain.

A conversation is not a meeting and gets no visible note. Its summary is kept
here, in the hidden `_messages/sessions/`, so project pages and decisions can
cite where a line came from and the evening run's queue can tell it has been
read. Every mail and Teams reader globs `_messages/*-messages.md` in the folder
itself, so nothing there ever sees these files.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from . import markdown, naming, vault

SESSIONS_DIR = Path(vault.MESSAGES_DIR) / "sessions"
REQUIRED = ("title", "date", "projects", "people", "summary", "scope")
OPTIONAL = ("decisions",)
QUOTE_KEYS = frozenset({"title", "scope"})
_NEWLINE_RE = re.compile(r"[\r\n]")


class SessionError(Exception):
    """A payload field or vault state the caller must fix."""


def _line(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SessionError(f"{field} must not be empty")
    if _NEWLINE_RE.search(text):
        raise SessionError(f"{field} must be one line")
    return text


def _lines(value, field: str, *, allow_empty: bool) -> List[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise SessionError(f"{field} must be a {'' if allow_empty else 'non-empty '}list")
    return [_line(item, f"{field} entry") for item in value]


def _slugs(root: Path, value, field: str, exists) -> List[str]:
    if not isinstance(value, list):
        raise SessionError(f"{field} must be a list of slugs")
    for slug in value:
        try:
            naming.validate_slug(str(slug))
        except ValueError as exc:
            raise SessionError(f"{field} entry {slug!r}: {exc}") from exc
        if not exists(str(slug)).is_file():
            raise SessionError(f"{field} entry {slug!r} matches no note — "
                               "check the spelling")
    return [str(slug) for slug in value]


def write(root: Path, payload: dict, *, now: Optional[datetime] = None) -> dict:
    if not isinstance(payload, dict):
        raise SessionError("the payload must be a JSON object")
    unknown = sorted(set(payload) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise SessionError(f"unknown payload key(s) {unknown}")
    missing = [key for key in REQUIRED if key not in payload]
    if missing:
        raise SessionError(f"missing payload key(s) {missing}")
    title = _line(payload["title"], "title")
    if any(ch in title for ch in "[]|"):
        raise SessionError("title must not contain [, ] or | — it becomes a "
                           "link alias on the project page")
    try:
        title_slug = naming.slugify(title)
    except ValueError as exc:
        raise SessionError(f"title {title!r} gives no file name: {exc}") from exc
    try:
        day = date.fromisoformat(str(payload["date"])).isoformat()
    except ValueError as exc:
        raise SessionError(f"date {payload['date']!r} is not YYYY-MM-DD") from exc
    projects = _slugs(root, payload["projects"], "projects",
                      lambda s: root / vault.PROJECTS_DIR / s / "index.md")
    if not projects:
        # A session with no project is never queued and never shown: it would
        # sit hidden forever (final review, #267).
        raise SessionError("a session needs at least one active project — name "
                           "one, or create it with /new-project first")
    for slug in projects:
        data, _ = markdown.split_frontmatter(
            (root / vault.PROJECTS_DIR / slug / "index.md").read_text(encoding="utf-8"))
        status = data.get("status")
        if status not in (None, "active"):
            raise SessionError(f"project {slug!r} is not active (status "
                               f"{status!r}) — nothing would read this session")
    people = _slugs(root, payload["people"], "people",
                    lambda s: root / vault.PEOPLE_DIR / f"{s}.md")
    summary = _lines(payload["summary"], "summary", allow_empty=False)
    decisions = _lines(payload.get("decisions", []), "decisions", allow_empty=True)
    scope = _line(payload["scope"], "scope")
    stamp = (now or datetime.now()).isoformat(timespec="minutes")

    folder = root / SESSIONS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    # "session" keeps the stem out of decision notes' `<date>-<title>` space:
    # links resolve sessions before decisions, so a shared stem would make a
    # same-titled decision unresolvable (final review, #267).
    base = f"{day}-session-{title_slug}"
    stem, n = base, 1
    while (folder / f"{stem}.md").exists():
        n += 1
        stem = f"{base}-{n}"

    frontmatter = {"type": "session", "date": day, "updated-at": stamp,
                   "projects": projects, "people": people, "scope": scope}
    lines = [markdown.title_heading(title), "", "## Summary"]
    lines += [f"- {item}" for item in summary]
    if decisions:
        lines += ["", "## Decisions"] + [f"- {item}" for item in decisions]
    text = markdown.emit_frontmatter(frontmatter, QUOTE_KEYS) + "\n".join(lines) + "\n"
    target = folder / f"{stem}.md"
    vault.atomic_create(target, text)
    return {"path": target.relative_to(root).as_posix(), "stem": stem}
