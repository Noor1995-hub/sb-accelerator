"""Entity dossiers: creation and section merges.

One hard rule runs through every merge: never remove existing content. Add or
update only, and report contradictions to the caller rather than resolving
them silently.

Two sources of malformed input meet in this module, and they get opposite
treatment (#40, #41):

- **Hand-edited FILE content is repaired.** A human editing a dossier in
  Obsidian is not writing our storage format. None of that is lost and none of
  it blocks a write: it is reinterpreted the way the human meant it, tidied
  into a self-consistent file on the next write, and every repair comes back
  in the result's `repairs` list so the skill can say what changed. (Since
  #273 no merge parses a table, so `repairs` is currently always empty; the
  key stays so callers' envelopes do not change shape.) Refusing here would
  strand the user with a note they consider fine and a CLI that will not
  touch it.
- **Off-shape model PAYLOADS are refused, loudly.** A misspelled field, a list
  where prose belongs, a date that is not `YYYY-MM-DD` — nothing is written and
  the EntityError names the field, the index, and what to send instead. The
  caller is a model that can retry; writing a plausible-looking wrong file and
  reporting ok is the worse outcome.

The per-section field tables below are write()'s API contract, not vault
ontology: they describe the JSON a caller may send, which is why they live
here rather than in schema.json.

Section shapes and merge rules are the contract in ontology.md §Entity. Two
skills write dossiers — /new-project creates a baseline, /update-entity
maintains one — so the rules live here rather than in either SKILL.md.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from . import markdown, naming, schema, vault

ENTITIES_DIR = vault.ENTITIES_DIR
ENTITY_QUOTE_KEYS = frozenset({"entity-name", "industry"})

PLACEHOLDER = "*No entries yet.*"
UNVALIDATED = "<!-- unvalidated -->"
BANNER = ("> [!unvalidated] Generated context — verify before relying on "
          "details.")

MAX_CONTEXT_BULLETS = 8

# Context and Sensitivities render as callouts so a dossier carries the same
# visual weight as a project index, which opens with
# `> [!summary] Where it stands` and `> [!info]- **Context**`. That is a
# contract, not styling: it puts a
# `> ` in front of every bullet those two sections hold, and every matcher in
# this module has to look past it.
CONTEXT_CALLOUT = "> [!info]+ **Standing context**"
SENSITIVITIES_CALLOUT = "> [!warning]+ **Handle with care**"

DYNAMICS_HEADING = "### Dynamics"
# The Meeting Log's index. Slug-free by construction — `this.slug` resolves
# from the dossier's own frontmatter at render time — so every dossier carries
# the same bytes. Joins on the meeting's `entities[]` field: Dataview sees only
# what the notes it filters say, and a meeting note names its projects, not the
# organization behind them (ontology.md §Meeting).
MEETING_LOG_QUERY = """```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  calendar-subject AS "Subject",
  map(projects, (p) => link("30-projects/" + p + "/index", default(link("30-projects/" + p + "/index").project-name, p))) AS "Projects"
FROM "20-meetings"
WHERE econtains(entities, this.slug)
SORT date DESC
LIMIT 20
```"""

# Teams (#253): an entity with `parent:` is a team or department of that
# entity. The parent's dossier gets this section the first time a team is
# attached — two live queries, slug-free like the Meeting Log, so nothing has
# to be rewritten when a team is added later. It is not one of the six managed
# sections; read() returns it under extra_sections and writes preserve it.
TEAMS_HEADING = "## Teams"
TEAMS_SECTION = TEAMS_HEADING + """

```dataview
TABLE WITHOUT ID
  link(file.path, entity-name) AS "Team",
  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status"
FROM "40-entities"
WHERE parent = this.slug
SORT entity-name ASC
```

"""
# The teams' projects used to be listed here too; Engagements lists them now,
# together with the entity's own (#273).
PART_OF_PREFIX = "**Part of** "

# Stakeholders and Engagements (#273): live lists, slug-free like the Meeting
# Log, so every dossier carries the same bytes. A person belongs to an entity
# through their own `entity` field; a team's people and projects show on the
# parent too. Nothing writes these sections — the people and projects do.
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
_LIVE_EDIT_KEYS = {
    "stakeholders": ("stakeholders live on the person now — use: person set --slug <person> "
                     "--entity <this entity> [--role …] [--decision-role …] [--stance …]"),
    "engagements": ("Engagements is a live list of this entity's projects — nothing to write; "
                    "create the project with /new-project"),
}

_EDIT_KEYS = ("context", "relationship_history", "meeting_log",
              "sensitivities")
_REQUIRED_EDIT_FIELDS = {
    "context": ("label", "fact", "why"),
    "relationship_history": ("date", "what", "significance"),
    "meeting_log": ("date", "topic", "dynamics"),
    "sensitivities": ("topic", "detail", "implications"),
}
# Every field a section entry may carry, required ones included. An unknown key
# used to be dropped silently and reported ok, so a model that misspelled
# `title` learned nothing and the note was quietly missing a column.
_KNOWN_EDIT_FIELDS = {
    "context": ("label", "fact", "why"),
    "relationship_history": ("date", "what", "significance"),
    "meeting_log": ("date", "topic", "dynamics"),
    "sensitivities": ("topic", "detail", "implications"),
}
# Sections whose entries are sorted on the ISO date they render with, via
# _date_key's fixed slice. Validated at the boundary so that slice never sees
# anything but YYYY-MM-DD.
_DATED_EDIT_KEYS = ("relationship_history", "meeting_log")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
# Fields the Meeting Log used to carry as hand-written bullets and no longer
# does. Rejected rather than ignored: dropping them silently would return an
# ok envelope to a caller that believes the content was written.
_RETIRED_EDIT_FIELDS = {
    "meeting_log": {
        "attendees": "the meeting note's own `attendees` frontmatter",
        "outcomes": "the meeting note's `## Notes`",
        "followups": "the meeting note's `## Action items`",
    },
}
_SECTION_FOR_EDIT = {
    "context": "Context",
    "relationship_history": "Relationship History",
    "meeting_log": "Meeting Log",
    "sensitivities": "Sensitivities",
}


class EntityError(Exception):
    """An entity argument or dossier state the caller must fix."""


_WS_RUN_RE = re.compile(r"\s+")


def _text(value) -> str:
    """Collapse a caller-supplied value to a single line.

    Bullet and heading sections render free text directly into markdown, so an
    embedded newline could fabricate a section header — and read() keeps only
    the last section of a given title, which would make a real section's
    content invisible.
    """
    return _WS_RUN_RE.sub(" ", "" if value is None else str(value)).strip()


def _dossier_path(root: Path, slug: str) -> Path:
    return root / ENTITIES_DIR / slug / "dossier.md"


# --- creation -------------------------------------------------------------

def _empty_body(name: str, part_of: Optional[str] = None) -> str:
    parts = []
    for title in schema.body_sections("entity"):
        if title == "Context":
            # The marker stays outside the callout: it is a comment about the
            # section, and inside it would render as a line of the box.
            parts.append(f"## Context\n{UNVALIDATED}\n\n{CONTEXT_CALLOUT}\n"
                         f"> {PLACEHOLDER}\n")
        elif title == "Stakeholders":
            parts.append(f"## Stakeholders\n\n{STAKEHOLDERS_QUERY}\n")
        elif title == "Meeting Log":
            parts.append(f"## Meeting Log\n\n{MEETING_LOG_QUERY}\n\n"
                         f"{DYNAMICS_HEADING}\n\n{PLACEHOLDER}\n")
        elif title == "Sensitivities":
            parts.append(f"## Sensitivities\n\n{SENSITIVITIES_CALLOUT}\n"
                         f"> {PLACEHOLDER}\n")
        elif title == "Engagements":
            parts.append(f"## Engagements\n\n{ENGAGEMENTS_QUERY}\n")
        else:
            parts.append(f"## {title}\n\n{PLACEHOLDER}\n")
    # `# {name}` because every dossier file is called dossier.md: without it
    # the only title Obsidian shows for the note is the word "dossier".
    head = f"\n# {name}\n\n" + (f"{part_of}\n\n" if part_of else "")
    return head + BANNER + "\n\n" + "\n".join(parts)


# --- teams (#253) ---------------------------------------------------------

def _children(root: Path, slug: str) -> List[str]:
    """Slugs of the entities whose `parent` is `slug`."""
    found = []
    for path in sorted((root / ENTITIES_DIR).glob("*/dossier.md")):
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if data.get("parent") == slug:
            found.append(path.parent.name)
    return found


def _validate_parent(root: Path, slug: str, parent: str) -> dict:
    """At most two levels, like projects. Returns the parent's frontmatter."""
    try:
        naming.validate_slug(parent)
    except ValueError as exc:
        raise EntityError(f"parent {parent!r} is not an entity slug: {exc}") from exc
    if parent == slug:
        raise EntityError(f"entity {slug!r} cannot be its own parent")
    path = _dossier_path(root, parent)
    if not path.is_file():
        raise EntityError(
            f"no dossier for parent {parent!r} at {ENTITIES_DIR}/{parent}/"
            f"dossier.md — create it first with: entity ensure --slug {parent} "
            "--name <name>")
    data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    if data.get("parent"):
        raise EntityError(
            f"{parent!r} is itself a team of {data['parent']!r} — teams go at "
            f"most one level deep; attach to {data['parent']!r} instead")
    children = _children(root, slug)
    if children:
        raise EntityError(
            f"{slug!r} has teams of its own ({', '.join(children)}) — an entity "
            "with teams cannot become a team; teams go at most one level deep")
    return data


def _part_of_line(parent: str, parent_fm: dict) -> str:
    shown = str(parent_fm.get("entity-name") or parent).replace("|", "-")
    return f"{PART_OF_PREFIX}[[{ENTITIES_DIR}/{parent}/dossier|{shown}]]"


def _with_part_of(text: str, line: str) -> str:
    """Put the Part of line right under the dossier's `# title` (replacing a
    previous one), leaving every other byte alone."""
    lines = text.split("\n")
    for index, current in enumerate(lines):
        if current.startswith(PART_OF_PREFIX):
            lines[index] = line
            return "\n".join(lines)
    fm_end = next((i for i, l in enumerate(lines) if i > 0 and l.strip() == "---"), -1)
    for index in range(fm_end + 1, len(lines)):
        if lines[index].startswith("# "):
            lines[index + 1:index + 1] = ["", line]
            return "\n".join(lines)
    raise EntityError("dossier has no `# title` line to put the Part of link under")


def _ensure_teams_section(root: Path, parent: str) -> bool:
    path = _dossier_path(root, parent)
    text = path.read_text(encoding="utf-8")
    if f"\n{TEAMS_HEADING}\n" in text.replace("\r\n", "\n"):
        return False
    vault.atomic_write(path, text.rstrip("\n") + "\n\n" + TEAMS_SECTION)
    return True


def _apply_existing_fields(root: Path, path: Path, slug: str, *,
                           name: str, entity_type: Optional[str],
                           status: Optional[str],
                           owner: Optional[str], today: str,
                           parent: Optional[str] = None,
                           part_of: Optional[str] = None) -> dict:
    """Apply explicitly provided fields to an already-existing dossier.

    Only fields the caller actually passed are candidates for an update — an
    absent flag must never read as "clear this field". This is the honest
    half of the fix for #97: the previous early return dropped every provided
    field (owner, name, entity-type, status) and still reported created:
    false with no other signal, which is indistinguishable from an ordinary,
    harmless no-op.
    """
    text = path.read_text(encoding="utf-8")
    frontmatter, _ = markdown.split_frontmatter(text)

    provided = {"entity-name": name}
    if entity_type is not None:
        provided["entity-type"] = entity_type
    if status is not None:
        provided["status"] = status
    if owner is not None:
        provided["owner"] = owner
    if parent is not None:
        provided["parent"] = parent

    updated_fields = sorted(
        field for field, value in provided.items()
        if frontmatter.get(field) != value
    )
    rel_path = path.relative_to(root).as_posix()
    part_of_missing = part_of is not None and part_of not in text
    if not updated_fields and not part_of_missing:
        return {"slug": slug, "path": rel_path, "created": False,
                "changed": False, "updated": []}

    merged = dict(frontmatter)
    merged.update(provided)
    problems = schema.validate("entity", merged)
    if problems:
        raise EntityError(
            "refusing to update entity frontmatter to a non-conformant "
            "state: " + "; ".join(problems)
        )

    rewritten = text
    for field in updated_fields:
        quoted = field in ENTITY_QUOTE_KEYS
        rendered = markdown.emit_scalar(merged[field], quoted=quoted)
        rewritten = markdown.upsert_scalar_field(rewritten, field, rendered)
    if part_of is not None:
        rewritten = _with_part_of(rewritten, part_of)
    rewritten = markdown.upsert_scalar_field(rewritten, "last-updated", today)
    vault.atomic_write(path, rewritten)
    return {"slug": slug, "path": rel_path, "created": False,
            "changed": True, "updated": updated_fields}


def ensure(root: Path, *, slug: str, name: str, today: str,
           entity_type: Optional[str] = None, status: Optional[str] = None,
           owner: Optional[str] = None,
           parent: Optional[str] = None) -> dict:
    """Create 40-entities/{slug}/dossier.md if it does not exist.

    On an existing dossier, apply whichever of name / entity_type / status /
    owner / parent the caller explicitly passed as an update instead of
    silently dropping them — see _apply_existing_fields.

    `parent` makes this entity a team of another (#253): validated to two
    levels, written to frontmatter, linked as **Part of** under the title, and
    the parent's dossier gains its `## Teams` section on the first team.
    """
    naming.validate_slug(slug)
    if owner:
        # owner is a join key to 50-people/{slug}.md, so it gets the same
        # validation as slug. Unvalidated, a display name like "jordan: reyes"
        # emits frontmatter that no YAML parser accepts.
        try:
            naming.validate_slug(str(owner).strip())
        except ValueError as exc:
            raise EntityError(
                f"owner {owner!r} is not a person slug: {exc}. "
                "owner joins to 50-people/<slug>.md"
            ) from exc
    part_of = None
    if parent is not None:
        parent = str(parent).strip()
        part_of = _part_of_line(parent, _validate_parent(root, slug, parent))
    path = _dossier_path(root, slug)
    if path.is_file():
        result = _apply_existing_fields(
            root, path, slug, name=name, entity_type=entity_type,
            status=status, owner=owner, today=today,
            parent=parent, part_of=part_of,
        )
        if parent is not None and _ensure_teams_section(root, parent):
            result["parent_teams_section"] = "added"
        return result

    frontmatter = {
        "type": "entity",
        "entity-name": name,
        "slug": slug,
        "entity-type": entity_type,
        "status": status if status is not None else "prospect",
        "industry": None,
        "owner": owner,
        "created": today,
        "last-updated": today,
    }
    if parent is not None:
        frontmatter = {**{k: v for k, v in frontmatter.items()
                          if k not in ("created", "last-updated")},
                       "parent": parent, "created": today, "last-updated": today}
    problems = schema.validate("entity", frontmatter)
    if problems:
        raise EntityError(
            "refusing to write non-conformant entity frontmatter: "
            + "; ".join(problems)
        )
    text = (markdown.emit_frontmatter(frontmatter, ENTITY_QUOTE_KEYS)
            + _empty_body(name, part_of))
    vault.atomic_write(path, text)
    result = {"slug": slug, "path": path.relative_to(root).as_posix(),
              "created": True}
    if parent is not None and _ensure_teams_section(root, parent):
        result["parent_teams_section"] = "added"
    return result


# --- reading --------------------------------------------------------------

def read(root: Path, slug: str) -> dict:
    """Parse a dossier into frontmatter, the six managed sections, and any
    section a human added.

    `extra_sections` is a separate key rather than more entries in `sections`
    because `sections` is a fixed six-key contract the callers index by name —
    and because write() has no edit key for a human's own section, so the two
    are not interchangeable. Both skills read before writing, and a section
    read() could not see made the model plan against a partial dossier (#41).
    """
    path = _dossier_path(root, slug)
    if not path.is_file():
        raise EntityError(
            f"no dossier at {ENTITIES_DIR}/{slug}/dossier.md — "
            f"create it first with: entity ensure --slug {slug} --name <name>"
        )
    text = path.read_text(encoding="utf-8")
    frontmatter, body = markdown.split_frontmatter(text)
    raw_sections = markdown.split_sections(body)
    preamble = ""
    seen: Dict[str, str] = {}
    for title, content in raw_sections:
        if title == "":
            preamble = content
            continue
        if title in seen:
            raise EntityError(
                f"dossier {slug!r} has more than one '## {title}' section — "
                "content under the earlier one is unreachable. Repair the file "
                "by hand (merge the duplicate headers) before editing it here."
            )
        seen[title] = content
    managed = schema.body_sections("entity")
    return {
        "slug": slug,
        "path": path.relative_to(root).as_posix(),
        "frontmatter": frontmatter,
        "sections": {title: seen.get(title, "") for title in managed},
        # File order, because that is where the human put them.
        "extra_sections": {title: content for title, content in seen.items()
                           if title not in managed},
        "unvalidated": [title for title, content in seen.items()
                        if UNVALIDATED in content],
        "banner": BANNER in preamble,
    }


# --- merge helpers --------------------------------------------------------

def _lines(content: str) -> List[str]:
    return [line for line in content.split("\n")]


_CALLOUT_PREFIX_RE = re.compile(r"\A[ \t]*(?:>[ \t]*)+")


def _split_prefix(line: str) -> Tuple[str, str]:
    """Split a line into its callout prefix and the markdown underneath.

    Context and Sensitivities are callouts, so every bullet in them arrives
    prefixed `> `. Every matcher here keys on `- **{Label}:**`, which that
    prefix hides — and each failure is silent rather than loud: the placeholder
    is never stripped, no label ever matches so every write appends a
    duplicate, and the Context bullet ceiling counts zero and stops enforcing.
    Strip the prefix to compare, re-attach it to render.
    """
    match = _CALLOUT_PREFIX_RE.match(line)
    return (match.group(0), line[match.end():]) if match else ("", line)


def _body(line: str) -> str:
    """A line with its callout prefix and indentation removed."""
    return _split_prefix(line)[1].strip()


def _strip_placeholder(lines: List[str]) -> List[str]:
    return [line for line in lines if _body(line) != PLACEHOLDER]


def _append_point(lines: List[str]) -> Tuple[int, str]:
    """Where a new bullet goes, and the callout prefix it needs there.

    Inside a callout the section does not end where the last bullet does — the
    callout ends at the first line without a `>`. A bullet appended past that
    point renders as loose text below the box instead of inside it, which
    reads as a rendering bug and is really a write-path bug. So append after
    the last prefixed line and carry its prefix; with no callout in the
    section, fall back to appending above any trailing blank lines.
    """
    for index in range(len(lines) - 1, -1, -1):
        prefix, rest = _split_prefix(lines[index])
        if prefix and rest.strip():
            return index + 1, prefix
    insert_at = len(lines)
    while insert_at > 0 and not lines[insert_at - 1].strip():
        insert_at -= 1
    return insert_at, ""


def _merge_labelled_bullets(content: str, items, label_key: str,
                            render) -> Tuple[str, int]:
    """Update a bullet whose bold label matches, else append. Returns
    (content, touched-count)."""
    lines = _strip_placeholder(_lines(content))
    touched = 0
    for item in items:
        label = _text(item[label_key])
        rendered = render(item)
        marker = f"- **{label}:**"
        for index, line in enumerate(lines):
            prefix, rest = _split_prefix(line)
            if rest.strip().startswith(marker):
                lines[index] = prefix + rendered
                break
        else:
            insert_at, prefix = _append_point(lines)
            lines.insert(insert_at, prefix + rendered)
        touched += 1
    return "\n".join(lines), touched


# --- per-section merges ---------------------------------------------------

def _merge_context(content: str, items) -> Tuple[str, int, List[str]]:
    merged, touched = _merge_labelled_bullets(
        content, items, "label",
        lambda item: (f"- **{_text(item['label'])}:** {_text(item['fact'])} "
                      f"— {_text(item['why'])}"),
    )
    count = len([line for line in merged.split("\n")
                if _body(line).startswith("- **")])
    if count > MAX_CONTEXT_BULLETS:
        raise EntityError(
            f"Context would hold {count} bullets, exceeding the maximum of "
            f"{MAX_CONTEXT_BULLETS}. Consolidate instead: update an existing "
            "bullet's label rather than adding a new one, or merge two related "
            "bullets before writing."
        )
    return merged, touched, []


def _merge_sensitivities(content: str, items) -> Tuple[str, int, List[str]]:
    merged, touched = _merge_labelled_bullets(
        content, items, "topic",
        lambda item: (f"- **{_text(item['topic'])}:** {_text(item['detail'])} "
                      f"— {_text(item['implications'])}"),
    )
    return merged, touched, []


def _date_key(block: List[str]) -> str:
    """The ISO date a dated bullet leads with: `- **2026-03-10 …`."""
    return _split_prefix(block[0])[1][4:14]


def _merge_dated_bullets(content: str, items, render, *,
                         newest_first: bool) -> Tuple[str, int]:
    """Add dated entries in date order, keeping every line that is not one.

    Only the top-level `- **date:**` bullets are sorted. Anything else a human
    put here survives: a lead-in paragraph stays above the entries, an indented
    continuation line stays attached to the entry it sits under, and any other
    trailing content (a stray comment, a note) stays below them. Filtering the
    section down to its bold bullets used to delete all of it.

    Content is never deleted, but it may be **regrouped**: a lead-in a human
    wrote *between* two entries comes back below all of them, because the
    entries are re-sorted as a block and an interleaved line has no stable
    place in that order.

    Once the walk has left the entries — the first non-blank line that is
    neither a dated bullet nor a continuation — later indented lines belong to
    the trailing content, not to the last dated entry. Sending them to
    `blocks[-1]` regardless was the reattribution defect in #41. A fresh dated
    bullet reopens a block, so a sub-bullet under it still attaches. Blank
    lines keep their old routing and do not close the entries, which is what
    keeps blank-line-separated sub-bullets with the entry they annotate.
    """
    lead: List[str] = []
    blocks: List[List[str]] = []
    tail: List[str] = []
    in_tail = False
    for line in _strip_placeholder(_lines(content)):
        if _body(line).startswith("- **"):
            blocks.append([line])
            in_tail = False
        elif not blocks:
            lead.append(line)
        elif line[:1] in (" ", "\t") and line.strip() and not in_tail:
            blocks[-1].append(line)
        else:
            tail.append(line)
            if line.strip():
                in_tail = True
    for item in items:
        blocks.append([render(item)])
    # Stable, so two entries sharing a date keep the order they arrived in
    # under both directions.
    blocks.sort(key=_date_key, reverse=newest_first)

    body: List[str] = []
    if any(line.strip() for line in lead):
        body.extend(lead)
        if body[-1].strip():
            body.append("")
    for block in blocks:
        body.extend(block)
    if any(line.strip() for line in tail):
        # tail comes back from the file with the blank line that already
        # separates it, so adding one unconditionally grew the gap by one
        # line on every write. Same guard as the lead branch above: only
        # add the separator when the adjacent line is not already blank.
        if tail[0].strip():
            body.append("")
        body.extend(tail)
    return "\n" + "\n".join(body).strip("\n") + "\n", len(items)


def _merge_relationship_history(content: str,
                                items) -> Tuple[str, int, List[str]]:
    merged, touched = _merge_dated_bullets(
        content, items,
        lambda item: (f"- **{_text(item['date'])}:** {_text(item['what'])} "
                      f"— {_text(item['significance'])}"),
        newest_first=False)
    return merged, touched, []


def _merge_meeting_log(content: str, items) -> Tuple[str, int, List[str]]:
    """Add Dynamics bullets under the section's `### Dynamics` heading.

    Everything above that heading is the Dataview index — a query, not
    content — and comes back byte for byte. Attendees, outcomes and follow-ups
    are deliberately not written here: they live in the meeting note's own
    frontmatter, `## Notes` and `## Action items`, and a copy in the dossier
    goes stale the moment the note is corrected. What the meeting note cannot
    hold is the read of the room, so that is all this section keeps.
    """
    lines = _lines(content)
    for position, line in enumerate(lines):
        if line.strip() == DYNAMICS_HEADING:
            break
    else:
        raise EntityError(
            f"the Meeting Log section has no '{DYNAMICS_HEADING}' heading, so "
            "there is nowhere to record the read of the room. Restore the "
            "heading (whatever sits above it is a Dataview query and writes "
            "nothing) and retry."
        )
    merged, touched = _merge_dated_bullets(
        "\n".join(lines[position + 1:]), items,
        lambda item: (f"- **{_text(item['date'])} — {_text(item['topic'])}:** "
                      f"{_text(item['dynamics'])}"),
        newest_first=True)
    return "\n".join(lines[:position + 1]) + "\n" + merged, touched, []


_MERGERS = {
    "context": _merge_context,
    "relationship_history": _merge_relationship_history,
    "meeting_log": _merge_meeting_log,
    "sensitivities": _merge_sensitivities,
}


# --- payload validation ---------------------------------------------------

def _is_iso_date(value: str) -> bool:
    """Is this exactly a YYYY-MM-DD calendar date?

    The regex is not redundant with fromisoformat: from 3.11 the latter also
    accepts `20260823` and full timestamps, and this module's floor is 3.10.
    fromisoformat is not redundant with the regex either — it is what rejects
    2026-13-40.
    """
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_items(edit_key: str, items: list) -> None:
    """Reject malformed entries before any merge runs.

    The merge functions index required keys directly, so a missing key would
    otherwise surface as a KeyError traceback with no JSON envelope — and the
    caller reading stdout is a model that has been told to read `ok`.

    This is the refusal half of the module's policy pair: a payload is the
    model's own output and it can retry, so every off-shape entry fails loudly
    and names the field. (Hand-edited file content gets the opposite
    treatment — see the module docstring.) The check order matters: the retired-field
    guidance is more specific than "unknown field", and both are more useful
    than a type or date complaint about a key that should not be there at all.
    """
    required = _REQUIRED_EDIT_FIELDS[edit_key]
    known = _KNOWN_EDIT_FIELDS[edit_key]
    retired = _RETIRED_EDIT_FIELDS.get(edit_key, {})
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise EntityError(
                f"{edit_key}[{index}] must be an object with "
                f"{list(required)}, got {type(item).__name__}"
            )
        gone = sorted(key for key in retired if item.get(key))
        if gone:
            raise EntityError(
                f"{edit_key}[{index}] carries retired field(s) {gone}, which "
                f"this section no longer holds — "
                + "; ".join(f"{key} belongs in {retired[key]}"
                            for key in gone)
                + f". Pass only {list(required)}."
            )
        unknown = sorted(key for key in item if key not in known)
        if unknown:
            raise EntityError(
                f"{edit_key}[{index}] has unknown field(s) {unknown}; "
                f"{edit_key} entries take {list(known)}"
            )
        for key in known:
            value = item.get(key)
            # None stays "no update": every fill-only merge reads an absent or
            # null optional field as "leave the stored value alone".
            if value is not None and not isinstance(value, str):
                raise EntityError(
                    f"{edit_key}[{index}].{key} must be a string, got "
                    f"{type(value).__name__}; render it as prose before "
                    "sending"
                )
        missing = [key for key in required
                   if not str(item.get(key) or "").strip()]
        if missing:
            raise EntityError(
                f"{edit_key}[{index}] is missing required field(s) {missing}; "
                f"every {edit_key} entry needs {list(required)}"
            )
        if edit_key in _DATED_EDIT_KEYS:
            # `date` is required and non-blank by here, and _date_key sorts on
            # a fixed slice of the rendered bullet — so anything else sorted
            # into an arbitrary position and stayed there.
            value = item["date"].strip()
            if not _is_iso_date(value):
                raise EntityError(
                    f"{edit_key}[{index}].date {value!r} is not a calendar "
                    "date in YYYY-MM-DD form; pass an ISO date like 2026-08-23"
                )


# --- writing --------------------------------------------------------------

# The source marker an automatic line ends with (#273): `(meeting · …)`,
# `(mail · …)`, `(chat · …)`, `(session · …)`, `(note · …)`. A labelled
# bullet without one was written by the owner (or by /update-entity with the
# owner in the loop), and an unattended run must never overwrite it.
_SOURCE_MARKER_RE = re.compile(r"\((?:meeting|mail|chat|session|note) · .*\)\s*\Z")
_BULLET_LABEL_RE = re.compile(r"- \*\*(.+?):\*\*")
_LABEL_KEYS = {"context": "label", "sensitivities": "topic"}
# The field each section renders last — where an automatic line's source
# marker sits (#273).
_MARKER_FIELD = {"context": "why", "sensitivities": "implications",
                 "relationship_history": "significance", "meeting_log": "dynamics"}


def _owner_bullet_labels(content: str) -> List[str]:
    """Labels of the bullets in a labelled section that carry no source
    marker — the owner's own points."""
    labels = []
    for line in _lines(content):
        body = _body(line)
        match = _BULLET_LABEL_RE.match(body)
        if match and not _SOURCE_MARKER_RE.search(body):
            labels.append(match.group(1))
    return labels


def write(root: Path, slug: str, edits: Mapping, today: str, *,
          automatic: bool = False) -> dict:
    """Apply section edits to an existing dossier.

    `automatic` is the unattended update (#273 section D): a Context or
    Sensitivities item whose label matches a bullet with no source marker is
    the owner's point and is skipped, never replaced — it is listed in
    `skipped` and the rest is written. An automatic write also leaves each
    section's `<!-- unvalidated -->` marker in place: nobody reviewed it.

    Returns `{"path", "changes", "repairs", "skipped"}`. `repairs` is always present and
    empty for a clean file; each entry names the section and what was tidied up
    in the human's own content. The skill surfaces it, because a repair the
    user is not told about is indistinguishable from a bug they will find
    later (#40).
    """
    for key, why in _LIVE_EDIT_KEYS.items():
        if edits.get(key):
            raise EntityError(why)
    unknown = [key for key in edits if key not in _EDIT_KEYS]
    if unknown:
        raise EntityError(
            f"unknown edit key(s) {unknown}; expected any of {list(_EDIT_KEYS)}")
    active = {}
    for key in _EDIT_KEYS:
        value = edits.get(key)
        if not value:
            continue
        if not isinstance(value, (list, tuple)):
            # A dict here would otherwise be list()-ed into its own keys and
            # then indexed as if each key were an entry.
            raise EntityError(
                f"{key} must be a list of entries, got "
                f"{type(value).__name__}; wrap a single entry in a list"
            )
        active[key] = list(value)
    if not active:
        raise EntityError(
            f"no edits supplied; expected at least one of {list(_EDIT_KEYS)}")
    for key, items in active.items():
        _validate_items(key, items)

    path = _dossier_path(root, slug)
    read(root, slug)  # raises EntityError if the dossier does not exist
    text = path.read_text(encoding="utf-8")
    _, body = markdown.split_frontmatter(text)
    sections = markdown.split_sections(body)

    # The merge loop below walks the sections the FILE has, so an edit whose
    # heading is absent — deleted or renamed by hand in Obsidian — would never
    # be visited: no merge, no changes entry, and an ok envelope over a write
    # that did not happen. Refuse the whole payload rather than apply part of
    # it; a half-applied write reads like an ordinary success.
    present = {title for title, _ in sections}
    missing = [key for key in active if _SECTION_FOR_EDIT[key] not in present]
    if missing:
        headings = ", ".join(f"## {_SECTION_FOR_EDIT[key]}" for key in missing)
        raise EntityError(
            f"the dossier for {slug} has no {headings} heading, so nothing "
            f"was written for {sorted(missing)}. Restore the heading (a "
            "deleted or renamed section is the usual cause) and retry."
        )

    skipped: List[str] = []
    if automatic:
        # Every automatic line names its source (owner, #273): enforced here,
        # so an unattended run cannot write an unsourced claim.
        for key in list(active):
            field = _MARKER_FIELD.get(key)
            if field is None:
                continue
            kept = []
            for item in active[key]:
                if _SOURCE_MARKER_RE.search(_text(item.get(field)) or ""):
                    kept.append(item)
                else:
                    skipped.append(
                        f"{key}: no source marker at the end of '{field}' — an "
                        "automatic line must say where it came from; not written")
            if kept:
                active[key] = kept
            else:
                del active[key]
        if not active:
            return {"path": path.relative_to(root).as_posix(), "changes": [],
                    "repairs": [], "skipped": skipped}
        contents = dict(sections)
        for key, label_key in _LABEL_KEYS.items():
            if key not in active:
                continue
            owners = set(_owner_bullet_labels(contents[_SECTION_FOR_EDIT[key]]))
            kept = []
            for item in active[key]:
                label = _text(item[label_key])
                if label in owners:
                    skipped.append(
                        f"{key} '{label}': the owner's point (no source "
                        "marker) — not replaced; use a new label")
                else:
                    kept.append(item)
            if kept:
                active[key] = kept
            else:
                del active[key]
        if not active:
            return {"path": path.relative_to(root).as_posix(), "changes": [],
                    "repairs": [], "skipped": skipped}

    changes: List[str] = []
    repairs: List[str] = []
    updated: List[Tuple[str, str]] = []
    for title, content in sections:
        edit_key = next((key for key, name in _SECTION_FOR_EDIT.items()
                         if name == title), None)
        if edit_key is None or edit_key not in active:
            updated.append((title, content))
            continue
        merged, touched, notes = _MERGERS[edit_key](content, active[edit_key])
        repairs.extend(f"{title}: {note}" for note in notes)
        # A human supplied this content, so the section is no longer
        # unvalidated — unless the write was automatic: nobody reviewed it.
        if not automatic:
            merged = "\n".join(line for line in merged.split("\n")
                               if _body(line) != UNVALIDATED)
        updated.append((title, merged))
        changes.append(f"{title}: {touched} entr{'y' if touched == 1 else 'ies'}")

    # The whole-document [!unvalidated] banner is preamble (title ""), which
    # the loop above always carries into `updated` byte for byte — it is
    # never a target of any edit key, so it survives unconditionally here.
    # (#97) It used to be stripped as a side effect whenever the last
    # per-section marker was consumed, silently upgrading the dossier's trust
    # status with no review having happened. Clearing it is now the separate,
    # explicit act in validate() below.
    new_body = markdown.render_sections(updated)

    head = text[: text.index("\n---", 4) + len("\n---") + 1]
    rewritten = markdown.replace_scalar_field(head + new_body,
                                              "last-updated", today)
    vault.atomic_write(path, rewritten)
    return {"path": path.relative_to(root).as_posix(), "changes": changes,
            "repairs": repairs, "skipped": skipped}


def validate(root: Path, slug: str, today: str) -> dict:
    """Clear the dossier's [!unvalidated] banner — the explicit review act.

    write() never removes the banner as a side effect of merging section
    content (#97): the only way to record that the dossier as a whole has
    been reviewed by a human is this call. Idempotent — calling it again once
    the banner is already gone is a silent no-op, not an error, matching
    ensure()'s and project.touch()'s "changed" precedent.
    """
    path = _dossier_path(root, slug)
    parsed = read(root, slug)  # raises EntityError if the dossier is missing
    if not parsed["banner"]:
        return {"slug": slug, "path": parsed["path"], "changed": False}

    text = path.read_text(encoding="utf-8")
    # The banner owns its own line and render_sections puts a blank one after
    # it, so removing only the text leaves a widening gap under the H1. The
    # narrower replacements stay as a fallback for a hand-edited file whose
    # spacing is not ours.
    updated = (text.replace(BANNER + "\n\n", "")
               .replace(BANNER + "\n", "").replace(BANNER, ""))
    updated = markdown.upsert_scalar_field(updated, "last-updated", today)
    vault.atomic_write(path, updated)
    return {"slug": slug, "path": parsed["path"], "changed": True}


_STAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")


def touch(root: Path, slug: str, *, timestamp: Optional[str] = None) -> dict:
    """Stamp `entity-updated`: the automatic update has read every piece of
    new material up to this minute (#273). The update queue compares new
    meetings, logs and sessions against it, as it does a project's
    `state-updated`. Nothing else in the dossier changes."""
    if timestamp is None:
        timestamp = datetime.datetime.now().isoformat(timespec="minutes")
    try:
        valid = bool(_STAMP_RE.match(str(timestamp))) and bool(
            datetime.datetime.strptime(str(timestamp), "%Y-%m-%dT%H:%M"))
    except ValueError:
        valid = False
    if not valid:
        # The stamp is the queue's start point: a month 13 or a 99:99 reads as
        # no stamp, and the same material is appended again every night — the
        # check person.touch already has (review 2026-10-12).
        raise EntityError(f"timestamp {timestamp!r} must be a real YYYY-MM-DDTHH:MM")
    read(root, slug)  # raises EntityError if the dossier does not exist
    path = _dossier_path(root, slug)
    text = path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "entity-updated", timestamp)
    if updated != text:
        vault.atomic_write(path, updated)
    return {"slug": slug, "path": path.relative_to(root).as_posix(),
            "entity-updated": timestamp, "changed": updated != text}
