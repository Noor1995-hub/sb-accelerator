"""Structure-version 14: entity pages fill themselves (#273).

An entity's dossier held two typed tables nothing kept current: Stakeholders
(Name · Title · Role in Decision · Stance · Notes) and Engagements
(Project · Status · One-liner). From this version both are live lists: a
person belongs to an entity through their own `entity` field and carries
their title (`role`), `decision-role` and `stance`; a project carries its
`stage`. The entity page shows its people and projects, current, however
they were added.

In an existing vault this migration:

- links people to their entity: a person's free-text `company` that matches
  exactly one entity (by name or slug, ignoring case) becomes `entity:` and
  the `company` line goes. Anything else keeps its `company` text and is
  listed for the owner to resolve (with /update-tables);
- moves every Stakeholders row onto the person (created when missing, since
  the owner named them): title, role in decision and stance only where the
  person has none — a different value is kept and listed, a word outside the
  vocabulary is listed, not written — and a non-empty Notes cell to the
  person's page under `## Notes from <Entity>`;
- moves every Engagements one-liner to its project's `## Notes`;
- replaces both tables with the live lists, keeping any text the owner wrote
  around them, and drops the Teams section's project list (Engagements shows
  those projects now).

The query text is frozen here: a migration must keep producing what it
produced when it shipped, whatever entity.py says later.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, naming, person, vault  # noqa: E402

TARGET_VERSION = 14
LOSSY = ("replaces each entity page's typed Stakeholders and Engagements tables with "
         "live lists; their titles, roles, stances and notes move to the people, their "
         "one-liners to the projects' Notes")

STAKEHOLDERS_QUERY = """```dataview
TABLE WITHOUT ID
  link(file.path, person-name) AS "Name",
  choice(entity = this.slug, "", link("40-entities/" + entity + "/dossier").entity-name) AS "Team",
  role AS "Title",
  decision-role AS "Role in decision",
  stance AS "Stance"
FROM "50-people"
WHERE entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug
SORT person-name ASC
```"""
ENGAGEMENTS_QUERY = """```dataview
TABLE WITHOUT ID
  link(file.path, project-name) AS "Project",
  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status",
  stage AS "Where it stands",
  next-milestone AS "Next milestone"
FROM "30-projects"
WHERE type = "project" AND (entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug)
SORT status ASC, project-name ASC
```"""

ENUMS = {"decision-role": ("sponsor", "champion", "evaluator", "influencer", "blocker"),
         "stance": ("champion", "neutral", "blocker")}
_ROW_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_RE = re.compile(r"\A:?-+:?\Z")
_WIKILINK_RE = re.compile(r"\A\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\Z")
_MD_LINK_RE = re.compile(r"\A\[[^\]]*\]\(([^)]+)\)\Z")
_PROJECT_PATH_RE = re.compile(r"30-projects/([^/]+)/index(?:\.md)?\Z")
_DATAVIEW_BLOCK_RE = re.compile(r"```dataview\n.*?```\n?", re.S)
NEEDS_REVIEW = "<!-- needs-review -->"


class MigrationError(Exception):
    """A dossier still holds a typed table after the migration."""


# --- small helpers ----------------------------------------------------------

def _split_row(line: str) -> List[str]:
    parts = _ROW_SPLIT_RE.split(line.strip())
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [part.strip().replace("\\|", "|") for part in parts]


def _table(content: str) -> Tuple[str, List[List[str]], str]:
    """(text before, data rows, text after) of the first table in a section."""
    lines = content.split("\n")
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("|")), None)
    if start is None:
        return content, [], ""
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    rows = [_split_row(line) for line in lines[start:end]]
    rows = rows[1:]  # the header
    rows = [r for r in rows if not (r and all(_SEPARATOR_RE.match(c) for c in r))]
    return "\n".join(lines[:start]), rows, "\n".join(lines[end:])


def _remove_field(text: str, field: str) -> str:
    """Drop one top-level frontmatter field (and its block-list items)."""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return text
    end = normalized.index("\n---", 4)
    lines = normalized[4:end].split("\n")
    out, skipping = [], False
    for line in lines:
        if line.startswith(f"{field}:"):
            skipping = True
            continue
        if skipping and (line.startswith(" ") or line.startswith("-")) and line.strip().startswith("-"):
            continue
        skipping = False
        out.append(line)
    return "---\n" + "\n".join(out) + normalized[end:]


def _set(text: str, field: str, value: str, quoted: bool) -> str:
    return markdown.upsert_scalar_field(text, field, markdown.emit_scalar(value, quoted))


def _append_under(body: str, heading: str, line: str, marker: str) -> Optional[str]:
    """Add a bullet under `## heading` (created at the end if missing).
    None when a line starting with `marker` is already there."""
    if marker in body:
        return None
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title == heading:
            sections[i] = (title, content.rstrip("\n") + "\n" + line + "\n")
            return markdown.render_sections(sections)
    return body.rstrip("\n") + f"\n\n## {heading}\n\n{line}\n"


def _write(path: Path, text: str) -> None:
    vault.atomic_write(path, text)


# --- the vault ----------------------------------------------------------------

def _people(root: Path) -> Dict[str, Path]:
    folder = root / vault.PEOPLE_DIR
    return {p.stem: p for p in sorted(folder.glob("*.md"))} if folder.is_dir() else {}


def _entities(root: Path) -> Dict[str, dict]:
    out = {}
    folder = root / vault.ENTITIES_DIR
    for path in sorted(folder.glob("*/dossier.md")) if folder.is_dir() else []:
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out[path.parent.name] = {"name": str(data.get("entity-name") or path.parent.name),
                                 "path": path}
    return out


def _match_entity(text: str, entities: Dict[str, dict]) -> Optional[str]:
    wanted = str(text or "").strip().lower()
    if not wanted:
        return None
    hits = [slug for slug, e in entities.items()
            if slug.lower() == wanted or e["name"].strip().lower() == wanted]
    return hits[0] if len(hits) == 1 else None


def _find_person(name_cell: str, people: Dict[str, Path]) -> Optional[str]:
    match = _WIKILINK_RE.match(name_cell.strip())
    if match:
        slug = match.group(1).strip().split("/")[-1]
        return slug if slug in people else None
    wanted = name_cell.strip().lower()
    for slug, path in people.items():
        data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        if str(data.get("person-name") or "").strip().lower() == wanted:
            return slug
    return None


def _project_slug(cell: str) -> Optional[str]:
    cell = cell.strip()
    link = _WIKILINK_RE.match(cell) or _MD_LINK_RE.match(cell)
    target = link.group(1) if link else cell
    match = _PROJECT_PATH_RE.search(target.replace("\\", "/"))
    if match:
        return match.group(1)
    return target if re.fullmatch(r"[a-z0-9-]+", target) else None


# --- steps ------------------------------------------------------------------

def _link_companies(root: Path, entities, result) -> None:
    for slug, path in _people(root).items():
        text = path.read_text(encoding="utf-8")
        data, _ = markdown.split_frontmatter(text)
        company = str(data.get("company") or "").strip()
        if not company or data.get("entity"):
            continue
        target = _match_entity(company, entities)
        if target is None:
            result["unmatched"].append({"person": slug, "company": company})
            continue
        _write(path, _remove_field(_set(text, "entity", target, False), "company"))
        result["linked"] += 1


def _stakeholder(root: Path, entity_slug: str, entity_name: str, row: List[str],
                 today: str, result) -> None:
    row = row + [""] * (5 - len(row))
    name, title, decision_role, stance, notes = row[:5]
    if not name:
        return
    people = _people(root)
    slug = _find_person(name, people)
    if slug is None:
        display = _WIKILINK_RE.match(name)
        display_name = display.group(1) if display else name
        made = person.ensure(root, display_name.strip(), today)
        slug = made["slug"]
        if made.get("created"):
            result["people_created"].append(slug)
        people = _people(root)
    path = people[slug]
    text = path.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    for prop, value, quoted in (("role", title, True), ("decision-role", decision_role, False),
                                ("stance", stance, False)):
        value = value.strip()
        if not value:
            continue
        if prop in ENUMS and value.lower() not in ENUMS[prop]:
            result["clashes"].append(f"{slug}: {prop} {value!r} is not in the vocabulary")
            continue
        value = value.lower() if prop in ENUMS else value
        have = str(data.get(prop) or "").strip()
        if not have:
            text = _set(text, prop, value, quoted)
        elif have != value:
            result["clashes"].append(f"{slug}: {prop} kept {have!r} (table said {value!r})")
    if not str(data.get("entity") or "").strip():
        text = _set(text, "entity", entity_slug, False)
    note = notes.replace(NEEDS_REVIEW, "").strip()
    if note:
        fm_end = len(text) - len(markdown.split_frontmatter(text)[1])
        head, body = text[:fm_end], text[fm_end:]
        marker = f"- {note} (moved from the {entity_name} page,"
        updated = _append_under(body, f"Notes from {entity_name}",
                                f"{marker} {today})", marker)
        if updated is not None:
            text = head + updated
            result["notes_moved"] += 1
    _write(path, text)
    result["stakeholders_moved"] += 1


def _engagement(root: Path, entity_name: str, row: List[str], today: str, result) -> None:
    row = row + [""] * (3 - len(row))
    project_cell, _, one_liner = row[:3]
    one_liner = one_liner.strip()
    if not project_cell or not one_liner:
        return
    slug = _project_slug(project_cell)
    index = root / vault.PROJECTS_DIR / slug / "index.md" if slug else None
    if index is None or not index.is_file():
        result["unresolved"].append(f"{entity_name}: engagement {project_cell} — no such project")
        return
    text = index.read_text(encoding="utf-8").replace("\r\n", "\n")
    fm_end = len(text) - len(markdown.split_frontmatter(text)[1])
    head, body = text[:fm_end], text[fm_end:]
    marker = f"): {one_liner}"
    updated = _append_under(body, "Notes",
                            f"- Engagement note (moved from the {entity_name} page, {today}): {one_liner}",
                            marker)
    if updated is not None:
        _write(index, head + updated)
        result["one_liners_moved"] += 1


def _dossier(root: Path, slug: str, info: dict, today: str, result) -> None:
    path = info["path"]
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    fm_end = len(text) - len(markdown.split_frontmatter(text)[1])
    head, body = text[:fm_end], text[fm_end:]
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title == "Stakeholders" and STAKEHOLDERS_QUERY not in content:
            before, rows, after = _table(content)
            for row in rows:
                _stakeholder(root, slug, info["name"], row, today, result)
            sections[i] = (title, _rebuild(before, STAKEHOLDERS_QUERY, after))
        elif title == "Engagements" and ENGAGEMENTS_QUERY not in content:
            before, rows, after = _table(content)
            for row in rows:
                _engagement(root, info["name"], row, today, result)
            sections[i] = (title, _rebuild(before, ENGAGEMENTS_QUERY, after))
        elif title == "Teams":
            kept = _DATAVIEW_BLOCK_RE.sub(
                lambda m: "" if 'FROM "30-projects"' in m.group(0) else m.group(0), content)
            sections[i] = (title, re.sub(r"\n{3,}", "\n\n", kept))
    new_text = head + markdown.render_sections(sections)
    if new_text != text:
        _write(path, new_text)


def _rebuild(before: str, query: str, after: str) -> str:
    parts = [before.rstrip("\n"), "", query]
    tail = after.strip("\n")
    if tail:
        parts += ["", tail]
    return "\n".join(parts) + "\n\n"


def apply(root: Path) -> dict:
    today = date.today().isoformat()
    result = {"linked": 0, "unmatched": [], "stakeholders_moved": 0, "people_created": [],
              "clashes": [], "notes_moved": 0, "one_liners_moved": 0, "unresolved": [],
              "dossiers": 0}
    entities = _entities(root)
    _link_companies(root, entities, result)
    for slug, info in entities.items():
        _dossier(root, slug, info, today, result)
        result["dossiers"] += 1
    return result


def verify(root: Path) -> dict:
    checked = 0
    for slug, info in _entities(root).items():
        _, body = markdown.split_frontmatter(info["path"].read_text(encoding="utf-8"))
        sections = dict(markdown.split_sections(body))
        if "| Name | Title |" in sections.get("Stakeholders", ""):
            raise MigrationError(f"{slug}: Stakeholders is still a typed table")
        if "| Project | Status | One-liner |" in sections.get("Engagements", ""):
            raise MigrationError(f"{slug}: Engagements is still a typed table")
        if 'FROM "30-projects"' in sections.get("Teams", ""):
            raise MigrationError(f"{slug}: Teams still lists projects")
        checked += 1
    return {"dossiers": checked}
