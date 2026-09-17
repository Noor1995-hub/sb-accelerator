"""Project scaffolding: index.md plus an empty decisions/ folder.

Validation lives here rather than in the skill because these are exactly the
rules a model relaxes under pressure — a colliding slug, a third nesting
level, an area given a parent.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import markdown, naming, schema, vault

PROJECTS_DIR = vault.PROJECTS_DIR
ENTITIES_DIR = vault.ENTITIES_DIR
PROJECT_QUOTE_KEYS = frozenset({"project-name", "next-milestone"})
# Seconds are accepted on the way in (a caller may pass a fuller stamp) but
# never written — the field is minute-precision, like a meeting's `date`.
ISO_DATETIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?\Z")


class ProjectError(Exception):
    """A project argument the caller must fix."""


def _load_project(root: Path, slug: str) -> Optional[dict]:
    index = root / PROJECTS_DIR / slug / "index.md"
    if not index.is_file():
        return None
    data, _ = markdown.split_frontmatter(index.read_text(encoding="utf-8"))
    return data


def _compose_slug(entity: str, name: str) -> str:
    """Entity-prefixed slug: `{entity}-{name-slug}`.

    The slug is the triage typing surface — the vault owner typing `colr` in a
    meeting's `projects[]` must land on Colruyt's project — and the join namespace is one
    flat folder, so two clients' "AI Transformation" projects must not collide.
    The entity prefix buys both. The name itself stays entity-free (the
    Projects base shows `entity` as its own column); only the slug carries it.

    Truncation comes off the *name* half, never the entity: a slug whose
    entity got cut would break the very disambiguation it exists for.
    """
    try:
        naming.validate_slug(entity)
    except ValueError as exc:
        raise ProjectError(
            f"entity {entity!r} is not an entity slug: {exc}. "
            f"entity joins to {ENTITIES_DIR}/<slug>/dossier.md"
        ) from exc
    name_budget = naming.MAX_SLUG_LENGTH - len(entity) - 1
    if name_budget < 1:
        raise ProjectError(
            f"entity slug {entity!r} leaves no room for a project name within "
            f"{naming.MAX_SLUG_LENGTH} characters"
        )
    try:
        name_slug = naming.slugify(name, max_length=name_budget)
    except ValueError as exc:
        raise ProjectError(f"name {name!r} is unusable: {exc}") from exc
    # A name that already carries the entity ("Colruyt AI Transformation" for
    # entity `colruyt`) must not double up as colruyt-colruyt-ai-transformation.
    if name_slug == entity or name_slug.startswith(entity + "-"):
        return naming.slugify(name)
    return f"{entity}-{name_slug}"


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


def scaffold(root: Path, *, name: str, project_type: str, entity: str,
             owner: str, today: str, parent: Optional[str] = None,
             stage: Optional[str] = None, contacts: Optional[str] = None,
             source: Optional[str] = None,
             slug: Optional[str] = None) -> dict:
    """Create 30-projects/{slug}/index.md and its decisions/ folder.

    The slug defaults to `{entity}-{name-slug}` (see `_compose_slug`); an
    explicit `slug` overrides the composition for the rare case where the
    composed form is unwieldy, but is validated and collision-checked the
    same way.
    """
    if slug is not None:
        slug = str(slug).strip()
        try:
            naming.validate_slug(slug)
        except ValueError as exc:
            raise ProjectError(f"slug {slug!r} is not usable: {exc}") from exc
    else:
        slug = _compose_slug(entity, name)
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

    from . import projectstate   # local import: projectstate imports project for touch
    body = projectstate.render_body(name, slug, {
        "as_of": today, "stage": stage,
        "context": {"contacts": contacts, "source": source}})
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


def derive_entities(root: Path, projects: list) -> list:
    """Map each `projects[]` slug to its project's `entity:` field, in
    `projects` order, then dedupe while preserving that order.

    Shared by `meeting.write` (derive at creation) and the evening fold's
    `sync rederive-entities` (repair drift after retriage) — both need the
    same all-or-nothing contract migration 001 established for the same
    computation (`_project_entities`/`_step_entities_backfill` in
    `plugin/migrations/001-structure-version-2/migrate.py`): a note whose
    `projects[]` does not *fully* map is refused rather than given a partial
    `entities` list, because a partial list passes verification and quietly
    leaves the unmapped project's dossier short a meeting, with nothing on
    the page to say why. `entities: []` is never returned for an empty input
    either — the caller decides whether that means "omit the field".
    """
    unresolved_missing: list = []
    unresolved_fieldless: list = []
    entity_by_project: dict = {}
    for slug in dict.fromkeys(str(p) for p in projects):
        index = root / PROJECTS_DIR / slug / "index.md"
        if not index.is_file():
            unresolved_missing.append(slug)
            continue
        try:
            data, _ = markdown.split_frontmatter(
                index.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            unresolved_missing.append(slug)
            continue
        entity = data.get("entity")
        if isinstance(entity, str) and entity.strip():
            entity_by_project[slug] = entity.strip()
        else:
            unresolved_fieldless.append(slug)

    if unresolved_missing or unresolved_fieldless:
        reasons = []
        if unresolved_missing:
            reasons.append(
                "no project index (or it will not parse) at "
                + ", ".join(f"{PROJECTS_DIR}/{s}/index.md"
                           for s in unresolved_missing))
        if unresolved_fieldless:
            reasons.append(
                "no `entity:` field in "
                + ", ".join(f"{PROJECTS_DIR}/{s}/index.md"
                           for s in unresolved_fieldless))
        raise ProjectError(
            "cannot derive entities from projects[] — " + "; ".join(reasons)
            + " — add the missing field(s) and retry rather than write a "
              "partial entities list"
        )

    derived: list = []
    for slug in (str(p) for p in projects):
        entity = entity_by_project[slug]
        if entity not in derived:
            derived.append(entity)
    return derived


def _require_iso_date(value, label: str) -> str:
    text = str(value or "").strip()
    if not vault.ISO_DATE_RE.match(text):
        raise ProjectError(f"{label} {value!r} must be ISO YYYY-MM-DD")
    return text


def _require_iso_datetime(value, label: str) -> str:
    """A full ISO timestamp to the minute, or a refusal naming the flag.

    A bare date is rejected on purpose: it would stamp 00:00 and put the
    threshold *before* every meeting of that day, reintroducing the churn the
    timestamp exists to stop. The regex pins the shape and fromisoformat
    checks the value is a real moment (`2026-06-12T99:99` matches the shape).
    """
    text = str(value or "").strip()
    if not ISO_DATETIME_RE.match(text):
        raise ProjectError(
            f"{label} {value!r} must be an ISO datetime YYYY-MM-DDTHH:MM "
            "(a bare date is refused — the time is the point)")
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ProjectError(f"{label} {value!r} is not a real moment: {exc}") from exc
    return text


def touch(root, *, slug: str, date_iso: str, timestamp: Optional[str] = None,
          next_milestone=None, next_milestone_date=None) -> dict:
    """Bump the auto-maintained frontmatter of a project-state update.

    Stage-4 subagents send the project state as JSON and `project state
    write` renders the body; the frontmatter half comes through here (state
    write calls touch itself). Only last-updated, state-updated (and,
    together, the milestone pair) can change; every other byte of index.md
    stays put.

    `last-updated` stays the human-facing day. `state-updated` records the
    minute the state was actually synthesized, and that is what the evening
    run's update queue compares meeting datetimes against — a day was too
    coarse, so a meeting confirmed later the same day used to be dropped from
    the queue forever (issue #98). `timestamp` defaults to now.
    """
    try:
        naming.validate_slug(str(slug or "").strip())
    except ValueError as exc:
        raise ProjectError(f"slug {slug!r}: {exc}") from exc
    index_path = root / PROJECTS_DIR / slug / "index.md"
    if not index_path.is_file():
        raise ProjectError(
            f"no project {slug!r} at {PROJECTS_DIR}/{slug}/index.md — "
            "create it first with /new-project"
        )
    stamped = _require_iso_date(date_iso, "date")
    if timestamp is None:
        state_stamp = datetime.now().isoformat(timespec="minutes")
    else:
        state_stamp = _require_iso_datetime(timestamp, "--timestamp")
    if (next_milestone is None) != (next_milestone_date is None):
        raise ProjectError(
            "next-milestone and next-milestone-date travel together — "
            "pass both or neither"
        )
    text = index_path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "last-updated", stamped)
    updated = markdown.upsert_scalar_field(updated, "state-updated", state_stamp)
    milestone = None
    milestone_date = None
    if next_milestone is not None:
        milestone = str(next_milestone).strip()
        # emit_scalar refuses newlines too, but this check keeps the error a
        # ProjectError that names the flag, and also catches the empty string.
        # A lone \r counts because the frontmatter parser normalizes it to \n
        # on the way back in.
        if not milestone or "\n" in milestone or "\r" in milestone:
            raise ProjectError("next-milestone must be a single line of text")
        milestone_date = _require_iso_date(next_milestone_date,
                                           "next-milestone-date")
        quoted = markdown.emit_scalar(milestone, quoted=True)
        updated = markdown.upsert_scalar_field(updated, "next-milestone", quoted)
        updated = markdown.upsert_scalar_field(updated, "next-milestone-date",
                                               milestone_date)
    changed = updated != text
    if changed:
        vault.atomic_write(index_path, updated)
    return {
        "slug": slug,
        "path": f"{PROJECTS_DIR}/{slug}/index.md",
        "last-updated": stamped,
        "state-updated": state_stamp,
        "next-milestone": milestone,
        "next-milestone-date": milestone_date,
        "changed": changed,
    }
