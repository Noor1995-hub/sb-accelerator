"""Structure-version 9: meeting, person and decision notes open with their name (#258).

Project, entity and daily notes already open with an H1; these three did not,
so the only title Obsidian showed for them was the file name — `jordan-vance`,
`12-06-26-jordan-1on1`, `2026-06-01-vendor-shortlist-approved`. The writers
now emit the heading; this gives existing notes the same:

- a meeting (`20-meetings/*.md`) gets `# {calendar-subject}`
- a person (`50-people/*.md`) gets `# {person-name}`
- a decision (`30-projects/*/decisions/*.md`) gets `# {summary}`

The heading goes directly under the frontmatter, followed by a blank line.
A note whose body already opens with an H1, or whose property is empty, is
left alone; nothing else in any note changes. The CSS snippet (template
refresh) hides the repeated file-name title on these notes, as it does for
the other three.

Lossless; `verify` only reads. The heading rule is a frozen literal, not an
import of the writer: this migration's output must not change when the
writer's does.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, vault  # noqa: E402

TARGET_VERSION = 9
LOSSY = None

KINDS = (
    ("meetings", "20-meetings/*.md", "calendar-subject"),
    ("people", "50-people/*.md", "person-name"),
    ("decisions", "30-projects/*/decisions/*.md", "summary"),
)


class MigrationError(Exception):
    """A note that should open with its name still does not."""


def _heading(value) -> str:
    return "# " + " ".join(str(value).split())


def _needs(text: str, key: str):
    """The heading this note should gain, or None."""
    if not text.startswith("---"):
        return None
    try:
        fm, body = markdown.split_frontmatter(text)
    except ValueError:
        # Hand-edited frontmatter the vault's parser cannot read: not this
        # migration's to repair, and no reason to stop the upgrade over.
        return None
    value = fm.get(key)
    if value is None or not str(value).strip():
        return None
    first = next((line for line in body.split("\n") if line.strip()), "")
    if first.startswith("# "):
        return None
    return _heading(value)


def _insert(text: str, heading: str) -> str:
    # The frontmatter ends at the second `---` line; the body follows it.
    lines = text.split("\n")
    end = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---")
    head, body = lines[:end + 1], lines[end + 1:]
    while body and not body[0].strip():
        body.pop(0)
    return "\n".join(head + ["", heading, ""] + body)


def apply(root: Path) -> dict:
    root = Path(root)
    result = {}
    for name, glob, key in KINDS:
        count = 0
        for path in sorted(root.glob(glob)):
            text = path.read_text(encoding="utf-8")
            heading = _needs(text, key)
            if heading:
                vault.atomic_write(path, _insert(text, heading))
                count += 1
        result[name] = count
    return result


def verify(root: Path) -> dict:
    root = Path(root)
    checked = 0
    for _, glob, key in KINDS:
        for path in sorted(root.glob(glob)):
            if _needs(path.read_text(encoding="utf-8"), key):
                raise MigrationError(f"{path.relative_to(root).as_posix()}: does not open with its name")
            checked += 1
    return {"checked": checked}
