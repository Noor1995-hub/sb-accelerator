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
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import markdown, naming, schema, vault

ENTITIES_DIR = vault.ENTITIES_DIR
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
_REQUIRED_EDIT_FIELDS = {
    "context": ("label", "fact", "why"),
    "stakeholders": ("name",),
    "relationship_history": ("date", "what", "significance"),
    "meeting_log": ("date", "topic"),
    "sensitivities": ("topic", "detail", "implications"),
    "engagements": ("project",),
}
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


_WS_RUN_RE = re.compile(r"\s+")


def _text(value) -> str:
    """Collapse a caller-supplied value to a single line.

    Bullet and heading sections render free text directly into markdown, so an
    embedded newline could fabricate a section header — and read() keeps only
    the last section of a given title, which would make a real section's
    content invisible. _cell() does the same job for table sections.
    """
    return _WS_RUN_RE.sub(" ", "" if value is None else str(value)).strip()


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
    return {
        "slug": slug,
        "path": path.relative_to(root).as_posix(),
        "frontmatter": frontmatter,
        "sections": {title: seen.get(title, "")
                     for title in schema.body_sections("entity")},
        "unvalidated": [title for title, content in seen.items()
                        if UNVALIDATED in content],
        "banner": BANNER in preamble,
    }


# --- merge helpers --------------------------------------------------------

def _lines(content: str) -> List[str]:
    return [line for line in content.split("\n")]


def _strip_placeholder(lines: List[str]) -> List[str]:
    return [line for line in lines if line.strip() != PLACEHOLDER]


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
            if line.strip().startswith(marker):
                lines[index] = rendered
                break
        else:
            insert_at = len(lines)
            while insert_at > 0 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, rendered)
        touched += 1
    return "\n".join(lines), touched


_ROW_SPLIT_RE = re.compile(r'(?<!\\)\|')


def _split_row(line: str) -> list:
    """Split a table row on unescaped delimiters only.

    _cell() escapes pipes inside free text, so a naive split on "|" would
    corrupt any cell carrying one — and re-parsing happens on every later
    write to the same dossier.
    """
    parts = _ROW_SPLIT_RE.split(line.strip())
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [part.strip() for part in parts]


def _parse_table(content: str,
                 columns: int) -> Tuple[List[str], List[List[str]], List[str]]:
    """Return (lines before the table, data rows as cell lists, lines after).

    Both the preamble and the postamble are a human's own annotation — a note
    under the Stakeholders table naming someone's assistant, say — and the hard
    rule is that a merge never removes existing content. Trailing lines used to
    match neither branch here and were silently dropped on the next write.
    """
    preamble: List[str] = []
    rows: List[List[str]] = []
    postamble: List[str] = []
    seen_header = 0
    for line in _lines(content):
        stripped = line.strip()
        if stripped.startswith("|"):
            seen_header += 1
            if seen_header <= 2:
                continue  # header row and separator
            cells = _split_row(stripped)
            cells += [""] * (columns - len(cells))
            rows.append(cells[:columns])
        elif seen_header == 0:
            preamble.append(line)
        else:
            postamble.append(line)
    return preamble, rows, postamble


def _render_table(preamble: List[str], header: str, rows: List[List[str]],
                  postamble: Sequence[str] = ()) -> str:
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    lead = "\n".join(_strip_placeholder(preamble)).rstrip("\n")
    chunk = header + ("\n" + body if body else "")
    rendered = (lead + "\n\n" if lead.strip() else "\n") + chunk + "\n"
    tail = "\n".join(_strip_placeholder(list(postamble))).strip("\n")
    if tail:
        rendered += "\n" + tail + "\n"
    return rendered


# --- per-section merges ---------------------------------------------------

def _merge_context(content: str, items) -> Tuple[str, int]:
    merged, touched = _merge_labelled_bullets(
        content, items, "label",
        lambda item: (f"- **{_text(item['label'])}:** {_text(item['fact'])} "
                      f"— {_text(item['why'])}"),
    )
    count = len([line for line in merged.split("\n")
                if line.strip().startswith("- **")])
    if count > MAX_CONTEXT_BULLETS:
        raise EntityError(
            f"Context would hold {count} bullets, exceeding the maximum of "
            f"{MAX_CONTEXT_BULLETS}. Consolidate instead: update an existing "
            "bullet's label rather than adding a new one, or merge two related "
            "bullets before writing."
        )
    return merged, touched


def _merge_sensitivities(content: str, items) -> Tuple[str, int]:
    return _merge_labelled_bullets(
        content, items, "topic",
        lambda item: (f"- **{_text(item['topic'])}:** {_text(item['detail'])} "
                      f"— {_text(item['implications'])}"),
    )


_WIKILINK_RE = re.compile(r"\A\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\Z")


def _name_key(cell: str) -> str:
    """Comparison key for a stakeholder Name cell.

    A dossier may carry a plain display name, an Obsidian wikilink to the
    person note, or an aliased link — and a hand-edited file may mix them.
    Normalising to a slug means `[[leo-marchetti]]` and "Leo Marchetti" are the
    same person, so a caller passing a display name updates the existing row
    instead of appending a duplicate.
    """
    # _cell() escapes pipes, so an aliased wikilink arrives as
    # `[[slug\|Alias]]`. Unescape first, or the alias separator is invisible to
    # the pattern below and the slug captures a stray backslash.
    text = cell.strip().replace(r"\|", "|")
    match = _WIKILINK_RE.match(text)
    if match:
        text = match.group(1).strip()
    if not text:
        return ""
    try:
        return naming.slugify(text)
    except ValueError:
        return text.lower()


def _merge_stakeholders(content: str, items) -> Tuple[str, int]:
    preamble, rows, postamble = _parse_table(content, 5)
    touched = 0
    for item in items:
        # str()-wrapped like every other caller value in this module:
        # `"role": ["sponsor"]` is a routine LLM JSON slip, and .strip()
        # on a list raises AttributeError — straight past the envelope.
        role = str(item.get("role") or "").strip()
        stance = str(item.get("stance") or "").strip()
        if role and role not in ROLE_VOCABULARY:
            raise EntityError(
                f"role {role!r} is not one of {list(ROLE_VOCABULARY)}")
        if stance and stance not in STANCE_VOCABULARY:
            raise EntityError(
                f"stance {stance!r} is not one of {list(STANCE_VOCABULARY)}")
        incoming = [_cell(item.get("name")), _cell(item.get("title")),
                    _cell(role), _cell(stance), _cell(item.get("notes"))]
        if not incoming[0]:
            raise EntityError(
                "stakeholder name is missing or blank; every stakeholder "
                "needs a name"
            )
        name_key = _name_key(incoming[0])
        for row in rows:
            if _name_key(row[0]) == name_key:
                was_flagged = NEEDS_REVIEW in row[4]
                # Only fill; never replace a filled cell with an empty one.
                # row[0] is deliberately left alone: the dossier's own Name
                # format (plain, linked, or aliased) is the human's choice.
                for index in range(1, 5):
                    if incoming[index]:
                        row[index] = incoming[index]
                if was_flagged and NEEDS_REVIEW not in row[4]:
                    # /update-entity Rule 4: only a human clears the marker.
                    # A later Notes update must not carry it away with the text
                    # it replaced.
                    row[4] = f"{row[4]} {NEEDS_REVIEW}".strip()
                break
        else:
            if NEEDS_REVIEW not in incoming[4]:
                incoming[4] = f"{incoming[4]} {NEEDS_REVIEW}".strip()
            rows.append(incoming)
        touched += 1
    return _render_table(preamble, STAKEHOLDER_HEADER, rows, postamble), touched


_LINK_TEXT_RE = re.compile(r"\A\[([^\]]+)\]")


def _row_project_slug(cell: str) -> str:
    """The engagement row's project slug, taken from the link text.

    Safe to match without unescaping: _merge_engagements validates the project
    value as a slug, so no `\\|` escape can ever reach this cell.
    """
    match = _LINK_TEXT_RE.match(cell.strip())
    return match.group(1).strip() if match else cell.strip()


def _merge_engagements(content: str, items) -> Tuple[str, int]:
    preamble, rows, postamble = _parse_table(content, 3)
    touched = 0
    for item in items:
        slug = str(item["project"]).strip()
        # The Project cell is a markdown link built from this value and is the
        # one cell _cell() never sees, so an unescaped pipe would break the row
        # and a display name would link at a folder that cannot exist.
        try:
            naming.validate_slug(slug)
        except ValueError as exc:
            raise EntityError(
                f"engagement project {slug!r} is not a project slug: {exc}. "
                "Pass the project's slug — the row links to "
                "30-projects/<slug>/index.md"
            ) from exc
        link = f"[{slug}](../../30-projects/{slug}/index.md)"
        incoming = [link, _cell(item.get("status")),
                    _cell(item.get("one_liner"))]
        for row in rows:
            if _row_project_slug(row[0]) == slug:
                for index in (1, 2):
                    if incoming[index]:
                        row[index] = incoming[index]
                break
        else:
            # The default belongs on a NEW row only. On the merge input it
            # made the Status cell unconditionally truthy, so the fill-only
            # guard above could never protect a stored value: a follow-up
            # note carrying no status reset Completed to Active. `status` is
            # not a required field, so that payload is entirely valid.
            if not incoming[1]:
                incoming[1] = "Active"
            rows.append(incoming)
        touched += 1
    return _render_table(preamble, ENGAGEMENT_HEADER, rows, postamble), touched


def _merge_relationship_history(content: str, items) -> Tuple[str, int]:
    """Add dated entries, keeping every line that is not one.

    Only the top-level `- **date:**` bullets are sorted. Anything else a human
    put here survives: a lead-in paragraph stays above the entries, an indented
    continuation line stays attached to the entry it sits under, and any other
    trailing content (a stray comment, a note) stays below them. Filtering the
    section down to its bold bullets used to delete all of it.
    """
    lead: List[str] = []
    blocks: List[List[str]] = []
    tail: List[str] = []
    for line in _strip_placeholder(_lines(content)):
        if line.strip().startswith("- **"):
            blocks.append([line])
        elif not blocks:
            lead.append(line)
        elif line[:1] in (" ", "\t") and line.strip():
            blocks[-1].append(line)
        else:
            tail.append(line)
    for item in items:
        blocks.append([
            f"- **{_text(item['date'])}:** {_text(item['what'])} "
            f"— {_text(item['significance'])}"])
    blocks.sort(key=lambda block: block[0][4:14])

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
        detail = "\n".join(f"- **{label}:** {_text(value)}"
                           for label, value in rows if value)
        blocks.append(
            f"### {_text(item['date'])} — {_text(item['topic'])}\n\n{detail}")
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


# --- payload validation ---------------------------------------------------

def _validate_items(edit_key: str, items: list) -> None:
    """Reject malformed entries before any merge runs.

    The merge functions index required keys directly, so a missing key would
    otherwise surface as a KeyError traceback with no JSON envelope — and the
    caller reading stdout is a model that has been told to read `ok`.
    """
    required = _REQUIRED_EDIT_FIELDS[edit_key]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise EntityError(
                f"{edit_key}[{index}] must be an object with "
                f"{list(required)}, got {type(item).__name__}"
            )
        missing = [key for key in required
                   if not str(item.get(key) or "").strip()]
        if missing:
            raise EntityError(
                f"{edit_key}[{index}] is missing required field(s) {missing}; "
                f"every {edit_key} entry needs {list(required)}"
            )


# --- writing --------------------------------------------------------------

def write(root: Path, slug: str, edits: Mapping, today: str) -> dict:
    """Apply section edits to an existing dossier."""
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
    parsed = read(root, slug)
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
