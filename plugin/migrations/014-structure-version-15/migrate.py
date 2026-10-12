"""Structure-version 15: `## Notes from <entity>` becomes `## What I know` (#273 piece 4).

Person pages now carry one section of facts about the person, `## What I
know`, placed right after the `# Name` heading; the evening run appends to
it. The structure-14 upgrade and /update-entity wrote such notes under
`## Notes from <entity>`, one heading per entity. This migration, for every
person page:

- moves everything under each `## Notes from …` heading — bullets, prose,
  code blocks, in page order, each line verbatim — to the end of `## What I
  know` (created after the H1 when missing), and drops the emptied headings;
- stamps `person-updated` with the upgrade moment when the page has none, so
  the first evening reads nothing older than the upgrade (the owner chose no
  look-back).

A heading matches in any case, with or without an entity name (`## Notes
From Acme`, `## Notes from`), and an existing `## What I Know` in any case is
reused. A moved bullet that does not already name its entity (the
/update-entity lines said only "(from /update-entity, <date>)") gets
` (Notes from <entity>)` appended, so dropping the heading loses nothing.

A page whose frontmatter will not parse is left byte-identical and named in
`needs_human`. So is the body of a page where a `Notes from` section leaves a
code block (```) open: moving it would reorder the sections that follow
(only the stamp is added). Running it twice changes nothing. Not lossy:
every line is kept; only the `Notes from` headings go. Pages that change are
written with LF line endings, like every vault writer.

The section placement is frozen here (a copy of person.py's at ship time): a
migration must keep producing what it produced when it shipped.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, vault  # noqa: E402

TARGET_VERSION = 15
LOSSY = None

HEADING = "What I know"
PREFIX = "notes from"


def _entity_of(title: str):
    """The entity name of a `Notes from <entity>` heading ("" when bare), in
    any case; None for any other heading."""
    t = title.strip()
    if t.lower() == PREFIX:
        return ""
    if t.lower().startswith(PREFIX + " "):
        return t[len(PREFIX):].strip()
    return None


def _open_fence(text: str) -> bool:
    fence = None
    for line in text.split("\n"):
        match = markdown._FENCE_RE.match(line)
        if match:
            token = match.group(1)
            fence = None if fence == token else (fence or token)
    return fence is not None


class MigrationError(Exception):
    """A readable person page still has a Notes from heading or no stamp."""


def _split_head(text: str) -> Tuple[str, str]:
    _, body = markdown.split_frontmatter(text)
    return text[:len(text) - len(body)], body


def _trim(content: str) -> List[str]:
    lines = content.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _insert(body: str, lines: List[str]) -> str:
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title.strip().lower() == HEADING.lower():
            kept = content.rstrip("\n")
            last = kept.split("\n")[-1].strip() if kept.strip() else ""
            gap = "\n" if (not last or last.startswith("- ")) else "\n\n"
            if not kept.strip():
                kept, gap = "", "\n"
            first = lines[0].strip() if lines else ""
            if not first.startswith("- "):
                gap = "\n\n" if kept else "\n"
            sections[i] = (title, kept + gap + "\n".join(lines) + "\n")
            return markdown.render_sections(sections)
    preamble = sections[0][1]
    if not preamble.endswith("\n"):
        preamble += "\n"
    sections[0] = ("", preamble)
    sections.insert(1, (HEADING, "\n" + "\n".join(lines) + "\n"))
    return markdown.render_sections(sections)


def _people(root: Path):
    folder = root / vault.PEOPLE_DIR
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def apply(root: Path) -> dict:
    root = Path(root)
    stamp = datetime.now().isoformat(timespec="minutes")
    result = {"people": 0, "notes_moved": 0, "stamped": 0, "needs_human": []}
    for path in _people(root):
        rel = path.relative_to(root).as_posix()
        try:
            original = path.read_text(encoding="utf-8")
            text = original.replace("\r\n", "\n")
            data, _ = markdown.split_frontmatter(text)
            head, body = _split_head(text)
        except (ValueError, OSError) as exc:
            result["needs_human"].append(
                f"{rel}: not readable ({exc}) — left as it is; move any "
                f"'## Notes from' text under '## {HEADING}' by hand")
            continue
        result["people"] += 1
        sections = markdown.split_sections(body)
        if any(_entity_of(t) is not None and _open_fence(c) for t, c in sections):
            result["needs_human"].append(
                f"{rel}: a '## Notes from' section leaves a code block (```) open — "
                f"its text was not moved; close the block and move it under "
                f"'## {HEADING}' by hand")
            sections = [("", body)]          # nothing in the body moves
        moved: List[str] = []
        kept = []
        for title, content in sections:
            entity = _entity_of(title) if title else None
            if entity is not None:
                lines = _trim(content)
                if entity:
                    # Outside code blocks only: a suffix inside a query
                    # would break it.
                    tagged, fence = [], None
                    for line in lines:
                        match = markdown._FENCE_RE.match(line)
                        if match:
                            token = match.group(1)
                            fence = None if fence == token else (fence or token)
                        elif (fence is None and line.startswith("- ")
                              and f"the {entity} page" not in line):
                            line += f" (Notes from {entity})"
                        tagged.append(line)
                    lines = tagged
                if moved and lines:
                    if not (moved[-1].startswith("- ") and lines[0].startswith("- ")):
                        moved.append("")
                moved.extend(lines)
                result["notes_moved"] += sum(1 for l in lines if l.startswith("- "))
            else:
                kept.append((title, content))
        if len(kept) != len(sections):
            body = markdown.render_sections(kept)
            if moved:
                body = _insert(body, moved)
        text = head + body
        if data.get("person-updated") in (None, ""):
            text = markdown.upsert_scalar_field(text, "person-updated", stamp)
            result["stamped"] += 1
        # Compared against the LF text: a CRLF page with nothing to do stays
        # byte-identical, as in migration 013.
        if text != original.replace("\r\n", "\n"):
            vault.atomic_write(path, text)
    return result


def verify(root: Path) -> dict:
    problems, checked = [], 0
    for path in _people(Path(root)):
        rel = path.relative_to(root).as_posix()
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue          # reported by apply; the owner's to fix
        checked += 1
        # A section left open by a code block was reported by apply and is
        # the owner's to move, like an unreadable page.
        if any(_entity_of(t) is not None and not _open_fence(c)
               for t, c in markdown.split_sections(body) if t):
            problems.append(f"{rel}: still has a '## Notes from' heading")
        if data.get("person-updated") in (None, ""):
            problems.append(f"{rel}: no person-updated")
    if problems:
        raise MigrationError("; ".join(problems))
    return {"people": checked}
