"""Project scaffolding: index.md plus an empty decisions/ folder.

Validation lives here rather than in the skill because these are exactly the
rules a model relaxes under pressure — a colliding slug, a third nesting
level, an area given a parent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import markdown, naming, schema, vault

PROJECTS_DIR = "30-projects"
ENTITIES_DIR = "40-entities"
PROJECT_QUOTE_KEYS = frozenset({"project-name", "next-milestone"})

_PLACEHOLDER = "_none yet_"


class ProjectError(Exception):
    """A project argument the caller must fix."""


def _load_project(root: Path, slug: str) -> Optional[dict]:
    index = root / PROJECTS_DIR / slug / "index.md"
    if not index.is_file():
        return None
    data, _ = markdown.split_frontmatter(index.read_text(encoding="utf-8"))
    return data


def _validate_inputs(root: Path, slug: str, project_type: str,
                     entity: str, parent: Optional[str]) -> None:
    allowed_types = schema.enum_values("project", "project-type")
    if project_type not in allowed_types:
        raise ProjectError(
            f"project-type {project_type!r} is not one of {allowed_types}"
        )

    existing = vault.list_dir_names(root / PROJECTS_DIR)
    clash = naming.find_collision(slug, existing)
    if clash is not None:
        raise ProjectError(
            f"a project folder already exists at {PROJECTS_DIR}/{clash} — "
            "pick a different name or work in the existing project"
        )

    if not (root / ENTITIES_DIR / entity / "dossier.md").is_file():
        raise ProjectError(
            f"no entity {entity!r} at {ENTITIES_DIR}/{entity}/dossier.md — "
            f"create it first with: entity ensure --slug {entity}"
        )

    if parent is None:
        return

    if project_type == "area-of-responsibility":
        raise ProjectError(
            "areas of responsibility are always top-level and cannot have a parent"
        )
    parent_data = _load_project(root, parent)
    if parent_data is None:
        raise ProjectError(
            f"parent project {parent!r} does not exist at "
            f"{PROJECTS_DIR}/{parent}/index.md"
        )
    if parent_data.get("parent") not in (None, ""):
        raise ProjectError(
            f"maximum two levels of nesting: {parent!r} already has a parent "
            f"({parent_data['parent']!r})"
        )


def _render_body(slug: str, name: str, today_display: str, stage: Optional[str],
                 contacts: Optional[str], source: Optional[str]) -> str:
    return f"""
# {name}

> [!summary]+ **Now** — as of {today_display}
> - **Stage** — {stage or "_newly created; awaiting first meeting or intake_"}
> - **Defining decision** — {_PLACEHOLDER}
> - **Next event** — _none scheduled_
> - **Owe** — {_PLACEHOLDER}
> - **Watch** — {_PLACEHOLDER}

> [!info]- **Context**
> - **Contacts** — {contacts or _PLACEHOLDER}
> - **Source** — {source or _PLACEHOLDER}

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "{PROJECTS_DIR}/{slug}/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — {_PLACEHOLDER}
- **Awaiting** — {_PLACEHOLDER}
- **Question** — {_PLACEHOLDER}
- **Pending** — {_PLACEHOLDER}

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date",
  slice(attendees, 0, 3) AS "Attendees",
  recording-duration AS "Min",
  calendar-subject AS "Subject"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
SORT date DESC
LIMIT 15
```
"""


def _display_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}-{month}-{year[2:]}"


def scaffold(root: Path, *, name: str, project_type: str, entity: str,
             owner: str, today: str, parent: Optional[str] = None,
             stage: Optional[str] = None, contacts: Optional[str] = None,
             source: Optional[str] = None) -> dict:
    """Create 30-projects/{slug}/index.md and its decisions/ folder."""
    slug = naming.slugify(name)
    naming.validate_slug(slug)
    # owner is a join key to 50-people/{slug}.md, so it gets the same
    # validation as slug. Unvalidated, a display name like "Jordan Reyes,
    # VP: Ops" emits frontmatter that no YAML parser accepts.
    try:
        naming.validate_slug(str(owner or "").strip())
    except ValueError as exc:
        raise ProjectError(
            f"owner {owner!r} is not a person slug: {exc}. "
            "owner joins to 50-people/<slug>.md"
        ) from exc
    _validate_inputs(root, slug, project_type, entity, parent)

    frontmatter = {
        "type": "project",
        "project-name": name,
        "slug": slug,
        "status": "active",
        "project-type": project_type,
        "entity": entity,
        "owner": owner,
        "parent": parent,
        "stakeholders": [],
        "created": today,
        "last-updated": today,
        "meetings-7d": 0,
        "meetings-30d": 0,
        "key-people": [],
        "next-milestone": None,
        "next-milestone-date": None,
    }
    problems = schema.validate("project", frontmatter)
    if problems:
        raise ProjectError(
            "refusing to write non-conformant project frontmatter: "
            + "; ".join(problems)
        )

    body = _render_body(slug, name, _display_date(today), stage, contacts, source)
    text = markdown.emit_frontmatter(frontmatter, PROJECT_QUOTE_KEYS) + body

    folder = root / PROJECTS_DIR / slug
    index = folder / "index.md"
    decisions = folder / "decisions"
    vault.atomic_write(index, text)
    decisions.mkdir(parents=True, exist_ok=True)

    return {
        "slug": slug,
        "path": index.relative_to(root).as_posix(),
        "decisions_dir": decisions.relative_to(root).as_posix(),
        "created": [
            index.relative_to(root).as_posix(),
            decisions.relative_to(root).as_posix() + "/",
        ],
    }


_ISO_DATE_ONLY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _require_iso_date(value, label: str) -> str:
    text = str(value or "").strip()
    if not _ISO_DATE_ONLY_RE.match(text):
        raise ProjectError(f"{label} {value!r} must be ISO YYYY-MM-DD")
    return text


def touch(root, *, slug: str, date_iso: str,
          next_milestone=None, next_milestone_date=None) -> dict:
    """Bump the auto-maintained frontmatter of a project-state update.

    Stage-5 subagents own the Now callout and Open Items as body prose; the
    frontmatter half comes through here so no model ever authors it. Only
    last-updated (and, together, the milestone pair) can change; every other
    byte of index.md stays put.
    """
    try:
        naming.validate_slug(str(slug or "").strip())
    except ValueError as exc:
        raise ProjectError(f"slug {slug!r}: {exc}") from exc
    index_path = root / "30-projects" / slug / "index.md"
    if not index_path.is_file():
        raise ProjectError(
            f"no project {slug!r} at 30-projects/{slug}/index.md — "
            "create it first with /new-project"
        )
    stamped = _require_iso_date(date_iso, "date")
    if (next_milestone is None) != (next_milestone_date is None):
        raise ProjectError(
            "next-milestone and next-milestone-date travel together — "
            "pass both or neither"
        )
    text = index_path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "last-updated", stamped)
    milestone = None
    milestone_date = None
    if next_milestone is not None:
        milestone = str(next_milestone).strip()
        if not milestone or "\n" in milestone:
            raise ProjectError("next-milestone must be a single line of text")
        milestone_date = _require_iso_date(next_milestone_date,
                                           "next-milestone-date")
        quoted = '"{}"'.format(milestone.replace('"', '\\"'))
        updated = markdown.upsert_scalar_field(updated, "next-milestone", quoted)
        updated = markdown.upsert_scalar_field(updated, "next-milestone-date",
                                               milestone_date)
    changed = updated != text
    if changed:
        vault.atomic_write(index_path, updated)
    return {
        "slug": slug,
        "path": f"30-projects/{slug}/index.md",
        "last-updated": stamped,
        "next-milestone": milestone,
        "next-milestone-date": milestone_date,
        "changed": changed,
    }
