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

A page whose frontmatter will not parse is left byte-identical and named in
`needs_human`. Running it twice changes nothing. Not lossy: every line is
kept; only the `Notes from` headings go.

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
PREFIX = "Notes from "


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
        if title == HEADING:
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
        moved: List[str] = []
        kept = []
        for title, content in sections:
            if title.startswith(PREFIX):
                lines = _trim(content)
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
        if any(t.startswith(PREFIX) for t, _ in markdown.split_sections(body)):
            problems.append(f"{rel}: still has a '## Notes from' heading")
        if data.get("person-updated") in (None, ""):
            problems.append(f"{rel}: no person-updated")
    if problems:
        raise MigrationError("; ".join(problems))
    return {"people": checked}
