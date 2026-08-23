"""Entity dossiers: creation and section merges.

One hard rule runs through every merge: never remove existing content. Add or
update only, and report contradictions to the caller rather than resolving
them silently.

Section shapes and merge rules are the contract in ontology.md §Entity. Two
skills write dossiers — /new-project creates a baseline, /update-entity
maintains one — so the rules live here rather than in either SKILL.md.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from . import markdown, naming, schema, vault

ENTITIES_DIR = "40-entities"
ENTITY_QUOTE_KEYS = frozenset({"entity-name", "industry"})

PLACEHOLDER = "*No entries yet.*"
UNVALIDATED = "<!-- unvalidated -->"
NEEDS_REVIEW = "<!-- needs-review -->"
BANNER = ("> [!unvalidated] Generated context — verify before relying on "
          "details.")

MAX_CONTEXT_BULLETS = 8
ROLE_VOCABULARY = ("sponsor", "champion", "evaluator", "influencer", "blocker")
STANCE_VOCABULARY = ("champion", "neutral", "blocker")

STAKEHOLDER_HEADER = (
    "| Name | Title | Role in Decision | Stance | Notes |\n"
    "|------|-------|------------------|--------|-------|"
)
ENGAGEMENT_HEADER = (
    "| Project | Status | One-liner |\n"
    "|---------|--------|-----------|"
)

_EDIT_KEYS = ("context", "stakeholders", "relationship_history",
              "meeting_log", "sensitivities", "engagements")
_SECTION_FOR_EDIT = {
    "context": "Context",
    "stakeholders": "Stakeholders",
    "relationship_history": "Relationship History",
    "meeting_log": "Meeting Log",
    "sensitivities": "Sensitivities",
    "engagements": "Engagements",
}


class EntityError(Exception):
    """An entity argument or dossier state the caller must fix."""


def _cell(value: Optional[str]) -> str:
    """Escape a value for a markdown table cell."""
    text = "" if value is None else str(value).strip()
    return text.replace("|", r"\|").replace("\n", " ")


def _dossier_path(root: Path, slug: str) -> Path:
    return root / ENTITIES_DIR / slug / "dossier.md"


# --- creation -------------------------------------------------------------

def _empty_body() -> str:
    parts = [""]
    for title in schema.body_sections("entity"):
        if title == "Context":
            parts.append(f"## Context\n{UNVALIDATED}\n\n{PLACEHOLDER}\n")
        elif title == "Stakeholders":
            parts.append(f"## Stakeholders\n\n{STAKEHOLDER_HEADER}\n")
        elif title == "Engagements":
            parts.append(f"## Engagements\n\n{ENGAGEMENT_HEADER}\n")
        else:
            parts.append(f"## {title}\n\n{PLACEHOLDER}\n")
    return "\n" + BANNER + "\n\n" + "\n".join(parts[1:])


def ensure(root: Path, *, slug: str, name: str, today: str,
           entity_type: Optional[str] = None, status: str = "prospect",
           owner: Optional[str] = None) -> dict:
    """Create 40-entities/{slug}/dossier.md if it does not exist."""
    naming.validate_slug(slug)
    path = _dossier_path(root, slug)
    if path.is_file():
        return {"slug": slug, "path": path.relative_to(root).as_posix(),
                "created": False}

    frontmatter = {
        "type": "entity",
        "entity-name": name,
        "slug": slug,
        "entity-type": entity_type,
        "status": status,
        "industry": None,
        "owner": owner,
        "created": today,
        "last-updated": today,
    }
    problems = schema.validate("entity", frontmatter)
    if problems:
        raise EntityError(
            "refusing to write non-conformant entity frontmatter: "
            + "; ".join(problems)
        )
    text = markdown.emit_frontmatter(frontmatter, ENTITY_QUOTE_KEYS) + _empty_body()
    vault.atomic_write(path, text)
    return {"slug": slug, "path": path.relative_to(root).as_posix(),
            "created": True}


# --- reading --------------------------------------------------------------

def read(root: Path, slug: str) -> dict:
    path = _dossier_path(root, slug)
    if not path.is_file():
        raise EntityError(
            f"no dossier at {ENTITIES_DIR}/{slug}/dossier.md — "
            f"create it first with: entity ensure --slug {slug} --name <name>"
        )
    text = path.read_text(encoding="utf-8")
    frontmatter, body = markdown.split_frontmatter(text)
    sections = dict(markdown.split_sections(body))
    preamble = sections.pop("", "")
    return {
        "slug": slug,
        "path": path.relative_to(root).as_posix(),
        "frontmatter": frontmatter,
        "sections": {title: sections.get(title, "")
                     for title in schema.body_sections("entity")},
        "unvalidated": [title for title, content in sections.items()
                        if UNVALIDATED in content],
        "banner": BANNER in preamble,
    }


# --- merge helpers --------------------------------------------------------

def _lines(content: str) -> List[str]:
    return [line for line in content.split("\n")]


def _strip_placeholder(lines: List[str]) -> List[str]:
    return [line for line in lines if line.strip() != PLACEHOLDER]


def _merge_labelled_bullets(content: str, items, label_key: str,
                            render, cap: Optional[int] = None) -> Tuple[str, int]:
    """Update a bullet whose bold label matches, else append. Returns
    (content, touched-count)."""
    lines = _strip_placeholder(_lines(content))
    touched = 0
    for item in items:
        label = str(item[label_key]).strip()
        rendered = render(item)
        marker = f"- **{label}:**"
        for index, line in enumerate(lines):
            if line.strip().startswith(marker):
                lines[index] = rendered
                break
        else:
            insert_at = len(lines)
            while insert_at > 0 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, rendered)
        touched += 1
    bullets = [line for line in lines if line.strip().startswith("- **")]
    if cap is not None and len(bullets) > cap:
        # Drop oldest bullets first: the newest carry the freshest facts.
        doomed = set(id(line) for line in bullets[: len(bullets) - cap])
        lines = [line for line in lines if id(line) not in doomed]
    return "\n".join(lines), touched


def _parse_table(content: str, columns: int) -> Tuple[List[str], List[List[str]]]:
    """Return (non-table lines before the table, data rows as cell lists)."""
    preamble, rows, seen_header = [], [], 0
    for line in _lines(content):
        stripped = line.strip()
        if stripped.startswith("|"):
            seen_header += 1
            if seen_header <= 2:
                continue  # header row and separator
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            cells += [""] * (columns - len(cells))
            rows.append(cells[:columns])
        elif seen_header == 0:
            preamble.append(line)
    return preamble, rows


def _render_table(preamble: List[str], header: str,
                  rows: List[List[str]]) -> str:
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    lead = "\n".join(_strip_placeholder(preamble)).rstrip("\n")
    chunk = header + ("\n" + body if body else "")
    return (lead + "\n\n" if lead.strip() else "\n") + chunk + "\n"


# --- per-section merges ---------------------------------------------------

def _merge_context(content: str, items) -> Tuple[str, int]:
    return _merge_labelled_bullets(
        content, items, "label",
        lambda item: f"- **{item['label']}:** {item['fact']} — {item['why']}",
        cap=MAX_CONTEXT_BULLETS,
    )


def _merge_sensitivities(content: str, items) -> Tuple[str, int]:
    return _merge_labelled_bullets(
        content, items, "topic",
        lambda item: f"- **{item['topic']}:** {item['detail']} — {item['implications']}",
    )


def _merge_stakeholders(content: str, items) -> Tuple[str, int]:
    preamble, rows = _parse_table(content, 5)
    touched = 0
    for item in items:
        role = (item.get("role") or "").strip()
        stance = (item.get("stance") or "").strip()
        if role and role not in ROLE_VOCABULARY:
            raise EntityError(
                f"role {role!r} is not one of {list(ROLE_VOCABULARY)}")
        if stance and stance not in STANCE_VOCABULARY:
            raise EntityError(
                f"stance {stance!r} is not one of {list(STANCE_VOCABULARY)}")
        incoming = [_cell(item.get("name")), _cell(item.get("title")),
                    _cell(role), _cell(stance), _cell(item.get("notes"))]
        name_key = incoming[0].lower()
        for row in rows:
            if row[0].lower() == name_key:
                # Only fill; never replace a filled cell with an empty one.
                for index in range(1, 5):
                    if incoming[index]:
                        row[index] = incoming[index]
                break
        else:
            if not incoming[4]:
                incoming[4] = NEEDS_REVIEW
            else:
                incoming[4] = f"{incoming[4]} {NEEDS_REVIEW}"
            rows.append(incoming)
        touched += 1
    return _render_table(preamble, STAKEHOLDER_HEADER, rows), touched


def _merge_engagements(content: str, items) -> Tuple[str, int]:
    preamble, rows = _parse_table(content, 3)
    touched = 0
    for item in items:
        slug = str(item["project"]).strip()
        link = f"[{slug}](../../30-projects/{slug}/index.md)"
        incoming = [link, _cell(item.get("status") or "Active"),
                    _cell(item.get("one_liner"))]
        for row in rows:
            if slug in row[0]:
                for index in (1, 2):
                    if incoming[index]:
                        row[index] = incoming[index]
                break
        else:
            rows.append(incoming)
        touched += 1
    return _render_table(preamble, ENGAGEMENT_HEADER, rows), touched


def _merge_relationship_history(content: str, items) -> Tuple[str, int]:
    lines = _strip_placeholder(_lines(content))
    entries = [line for line in lines if line.strip().startswith("- **")]
    for item in items:
        entries.append(
            f"- **{item['date']}:** {item['what']} — {item['significance']}")
    entries.sort(key=lambda line: line[4:14])
    return "\n" + "\n".join(entries) + "\n", len(items)


def _merge_meeting_log(content: str, items) -> Tuple[str, int]:
    existing = "\n".join(_strip_placeholder(_lines(content))).strip("\n")
    blocks = []
    for item in items:
        rows = [
            ("Attendees", item.get("attendees")),
            ("Key outcomes", item.get("outcomes")),
            ("Follow-ups", item.get("followups")),
            ("Dynamics", item.get("dynamics")),
        ]
        detail = "\n".join(f"- **{label}:** {value}"
                           for label, value in rows if value)
        blocks.append(f"### {item['date']} — {item['topic']}\n\n{detail}")
    fresh = "\n\n".join(blocks)
    combined = "\n\n".join(part for part in (fresh, existing) if part)
    return "\n" + combined + "\n", len(items)


_MERGERS = {
    "context": _merge_context,
    "stakeholders": _merge_stakeholders,
    "relationship_history": _merge_relationship_history,
    "meeting_log": _merge_meeting_log,
    "sensitivities": _merge_sensitivities,
    "engagements": _merge_engagements,
}


# --- writing --------------------------------------------------------------

def write(root: Path, slug: str, edits: Mapping, today: str) -> dict:
    """Apply section edits to an existing dossier."""
    unknown = [key for key in edits if key not in _EDIT_KEYS]
    if unknown:
        raise EntityError(
            f"unknown edit key(s) {unknown}; expected any of {list(_EDIT_KEYS)}")
    active = {key: list(edits[key]) for key in _EDIT_KEYS
              if edits.get(key)}
    if not active:
        raise EntityError(
            f"no edits supplied; expected at least one of {list(_EDIT_KEYS)}")

    path = _dossier_path(root, slug)
    parsed = read(root, slug)
    text = path.read_text(encoding="utf-8")
    _, body = markdown.split_frontmatter(text)
    sections = markdown.split_sections(body)

    changes: List[str] = []
    updated: List[Tuple[str, str]] = []
    for title, content in sections:
        edit_key = next((key for key, name in _SECTION_FOR_EDIT.items()
                         if name == title), None)
        if edit_key is None or edit_key not in active:
            updated.append((title, content))
            continue
        merged, touched = _MERGERS[edit_key](content, active[edit_key])
        # A human supplied this content, so the section is no longer
        # unvalidated.
        merged = "\n".join(line for line in merged.split("\n")
                           if line.strip() != UNVALIDATED)
        updated.append((title, merged))
        changes.append(f"{title}: {touched} entr{'y' if touched == 1 else 'ies'}")

    new_body = markdown.render_sections(updated)
    if UNVALIDATED not in new_body:
        new_body = new_body.replace(BANNER + "\n", "").replace(BANNER, "")
        if parsed["banner"]:
            changes.append("removed the unvalidated banner")

    head = text[: text.index("\n---", 4) + len("\n---") + 1]
    rewritten = markdown.replace_scalar_field(head + new_body,
                                              "last-updated", today)
    vault.atomic_write(path, rewritten)
    return {"path": path.relative_to(root).as_posix(), "changes": changes}
