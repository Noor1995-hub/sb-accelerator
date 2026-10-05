"""Structure-version 8: names, not codes, in project and entity pages (#259).

The page bodies carry their own copies of a few Dataview queries, written when
the page was (last) rendered, so a fresh query in the writer reaches an
existing page only through this migration:

- **Project pages** (`30-projects/*/index.md`): *Recent meetings → With*
  shows attendee names, not slugs; *Recent decisions → Status* reads Active,
  Replaced or Withdrawn. A *Defining decision* written as a bare `[[stem]]`
  link gains the decision's own sentence as its text, `[[stem|summary]]` —
  what the writer has produced since #238.
- **Entity pages** (`40-entities/*/dossier.md`): *Meeting Log → Projects*
  shows linked project names; the *Teams* tables show a capitalised status.

Each change is one line, matched exactly and only inside a ```` ```dataview ````
block (or, for the defining decision, on the card's own line); nothing else
in a page moves, so hand edits survive. The lines are frozen literals, not
imports of the writer's constants: this migration's output must not change
when the writer's does. A project page the evening run rewrites later gets the
same lines from the writer anyway.

A slug with no note behind it still shows, as itself. Lossless: every
rewritten line computes from the same fields as before.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, vault  # noqa: E402

TARGET_VERSION = 8
LOSSY = None

PROJECT_GLOB = "30-projects/*/index.md"
DOSSIER_GLOB = "40-entities/*/dossier.md"
FENCE = "```dataview"

PROJECT_LINES = {
    '  slice(attendees, 0, 3) AS "With"':
        '  map(slice(attendees, 0, 3), (a) => default(link("50-people/" + a).person-name, a)) AS "With"',
    '  status AS "Status"':
        '  choice(status = "superseded", "Replaced", choice(status = "withdrawn", "Withdrawn", '
        'choice(status = "active", "Active", status))) AS "Status"',
}
DOSSIER_LINES = {
    '  projects AS "Projects"':
        '  map(projects, (p) => link("30-projects/" + p + "/index", '
        'default(link("30-projects/" + p + "/index").project-name, p))) AS "Projects"',
    '  status AS "Status"':
        '  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status"',
}
# `> - **Defining decision** — [[stem]]` with nothing after the link but an
# optional date in brackets; a link that already carries `|text` is left alone.
DEFINING_RE = re.compile(r"^(> - \*\*Defining decision\*\* — )\[\[([^\]|]+)\]\](.*)$")


class MigrationError(Exception):
    """A page still carries an old line after apply."""


def _swap_in_dataview(lines: list, table: dict) -> int:
    changed, inside = 0, False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            inside = line.strip() == FENCE if not inside else False
            continue
        if inside and line in table:
            lines[i] = table[line]
            changed += 1
    return changed


def _summary(project_dir: Path, stem: str):
    path = project_dir / "decisions" / f"{stem}.md"
    if not path.is_file():
        return None
    fm, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    text = str(fm.get("summary") or "").strip()
    return text or None


def _defining(lines: list, project_dir: Path) -> int:
    changed = 0
    for i, line in enumerate(lines):
        m = DEFINING_RE.match(line)
        if not m:
            continue
        summary = _summary(project_dir, m.group(2))
        if summary:
            lines[i] = f"{m.group(1)}[[{m.group(2)}|{summary}]]{m.group(3)}"
            changed += 1
    return changed


def _rewrite(path: Path, fix) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not fix(lines):
        return False
    vault.atomic_write(path, "\n".join(lines))
    return True


def apply(root: Path) -> dict:
    root = Path(root)
    projects = sum(_rewrite(p, lambda ls, d=p.parent: _swap_in_dataview(ls, PROJECT_LINES) + _defining(ls, d))
                   for p in sorted(root.glob(PROJECT_GLOB)))
    dossiers = sum(_rewrite(p, lambda ls: _swap_in_dataview(ls, DOSSIER_LINES))
                   for p in sorted(root.glob(DOSSIER_GLOB)))
    return {"projects": projects, "dossiers": dossiers}


def _stale(path: Path, table: dict) -> bool:
    lines = path.read_text(encoding="utf-8").split("\n")
    return _swap_in_dataview(list(lines), table) > 0


def verify(root: Path) -> dict:
    root = Path(root)
    checked = 0
    for glob, table in ((PROJECT_GLOB, PROJECT_LINES), (DOSSIER_GLOB, DOSSIER_LINES)):
        for path in sorted(root.glob(glob)):
            if _stale(path, table):
                raise MigrationError(f"{path.relative_to(root).as_posix()}: a query still shows codes")
            checked += 1
    return {"checked": checked}
