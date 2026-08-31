"""Entity dossiers: creation and section merges.

One hard rule runs through every merge: never remove existing content. Add or
update only, and report contradictions to the caller rather than resolving
them silently.

Two sources of malformed input meet in this module, and they get opposite
treatment (#40, #41):

- **Hand-edited FILE content is repaired.** A human editing a dossier in
  Obsidian is not writing our storage format — a raw `|` inside a cell, a
  deleted separator row, a note that happens to start with a pipe. None of
  that is lost and none of it blocks a write: it is reinterpreted the way the
  human meant it, tidied into a self-consistent file on the next write, and
  every repair comes back in the result's `repairs` list so the skill can say
  what changed. Refusing here would strand the user with a note they consider
  fine and a CLI that will not touch it.
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

# Context and Sensitivities render as callouts so a dossier carries the same
# visual weight as a project index, which opens with `> [!summary]+ **Now**`
# and `> [!info]- **Context**`. That is a contract, not styling: it puts a
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
  projects AS "Projects"
FROM "20-meetings"
WHERE econtains(entities, this.slug)
SORT date DESC
LIMIT 20
```"""

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
    "meeting_log": ("date", "topic", "dynamics"),
    "sensitivities": ("topic", "detail", "implications"),
    "engagements": ("project",),
}
# Every field a section entry may carry, required ones included. An unknown key
# used to be dropped silently and reported ok, so a model that misspelled
# `title` learned nothing and the note was quietly missing a column.
_KNOWN_EDIT_FIELDS = {
    "context": ("label", "fact", "why"),
    "stakeholders": ("name", "title", "role", "stance", "notes"),
    "relationship_history": ("date", "what", "significance"),
    "meeting_log": ("date", "topic", "dynamics"),
    "sensitivities": ("topic", "detail", "implications"),
    "engagements": ("project", "status", "one_liner"),
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

def _empty_body(name: str) -> str:
    parts = []
    for title in schema.body_sections("entity"):
        if title == "Context":
            # The marker stays outside the callout: it is a comment about the
            # section, and inside it would render as a line of the box.
            parts.append(f"## Context\n{UNVALIDATED}\n\n{CONTEXT_CALLOUT}\n"
                         f"> {PLACEHOLDER}\n")
        elif title == "Stakeholders":
            parts.append(f"## Stakeholders\n\n{STAKEHOLDER_HEADER}\n")
        elif title == "Meeting Log":
            parts.append(f"## Meeting Log\n\n{MEETING_LOG_QUERY}\n\n"
                         f"{DYNAMICS_HEADING}\n\n{PLACEHOLDER}\n")
        elif title == "Sensitivities":
            parts.append(f"## Sensitivities\n\n{SENSITIVITIES_CALLOUT}\n"
                         f"> {PLACEHOLDER}\n")
        elif title == "Engagements":
            parts.append(f"## Engagements\n\n{ENGAGEMENT_HEADER}\n")
        else:
            parts.append(f"## {title}\n\n{PLACEHOLDER}\n")
    # `# {name}` because every dossier file is called dossier.md: without it
    # the only title Obsidian shows for the note is the word "dossier".
    return f"\n# {name}\n\n" + BANNER + "\n\n" + "\n".join(parts)


def _apply_existing_fields(root: Path, path: Path, slug: str, *,
                           name: str, entity_type: Optional[str],
                           status: Optional[str],
                           owner: Optional[str], today: str) -> dict:
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

    updated_fields = sorted(
        field for field, value in provided.items()
        if frontmatter.get(field) != value
    )
    rel_path = path.relative_to(root).as_posix()
    if not updated_fields:
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
    rewritten = markdown.upsert_scalar_field(rewritten, "last-updated", today)
    vault.atomic_write(path, rewritten)
    return {"slug": slug, "path": rel_path, "created": False,
            "changed": True, "updated": updated_fields}


def ensure(root: Path, *, slug: str, name: str, today: str,
           entity_type: Optional[str] = None, status: Optional[str] = None,
           owner: Optional[str] = None) -> dict:
    """Create 40-entities/{slug}/dossier.md if it does not exist.

    On an existing dossier, apply whichever of name / entity_type / status /
    owner the caller explicitly passed as an update instead of silently
    dropping them — see _apply_existing_fields.
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
    path = _dossier_path(root, slug)
    if path.is_file():
        return _apply_existing_fields(
            root, path, slug, name=name, entity_type=entity_type,
            status=status, owner=owner, today=today,
        )

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
    problems = schema.validate("entity", frontmatter)
    if problems:
        raise EntityError(
            "refusing to write non-conformant entity frontmatter: "
            + "; ".join(problems)
        )
    text = (markdown.emit_frontmatter(frontmatter, ENTITY_QUOTE_KEYS)
            + _empty_body(name))
    vault.atomic_write(path, text)
    return {"slug": slug, "path": path.relative_to(root).as_posix(),
            "created": True}


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


_SEPARATOR_CELL_RE = re.compile(r"\A:?-+:?\Z")
# The header rows this module writes, as cells, for recognising a table whose
# separator a human deleted.
_STAKEHOLDER_HEADER_CELLS = _split_row(STAKEHOLDER_HEADER.split("\n")[0])
_ENGAGEMENT_HEADER_CELLS = _split_row(ENGAGEMENT_HEADER.split("\n")[0])


def _is_separator(stripped: str) -> bool:
    """Is this row the `|---|---|` rule under a header?"""
    cells = _split_row(stripped)
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell) for cell in cells)


def _header_key(cells: Sequence[str]) -> List[str]:
    """Comparison key for a header row: spacing and case carry no meaning."""
    return [_WS_RUN_RE.sub(" ", cell).strip().lower() for cell in cells]


def _find_header(lines: Sequence[str], header_cells: Sequence[str]) -> int:
    """Index of the table's header row, or -1 when there is no table.

    Finding the header explicitly is the whole ballgame. Treating the *first*
    pipe-prefixed line as the header regardless of what follows it meant a
    human's note above the table was consumed as the header and deleted, the
    real header and every row were demoted to prose, and the payload — with no
    row left to match — appended a duplicate person. A never-delete *and*
    never-duplicate violation from one wrong assumption.

    A line opens the table when either holds:

    1. **The next non-blank line is a separator.** This is the renderer's own
       rule (GFM opens a table at a header followed by a delimiter row), so on
       any well-formed file this parser and Obsidian cannot disagree. It is
       also what keeps a hand-renamed header working.
    2. **The line is this section's canonical header.** Rule 1 alone cannot
       carry the deleted-separator repair: with the separator gone there is no
       delimiter row to find, the table would never open, and the rows we are
       trying to rescue would strand as prose. Every header in a dossier was
       written by this module, so matching it — modulo spacing and case — is a
       reliable second opening, and it is the one place we deliberately part
       company with the renderer: Obsidian shows that file as plain text, and
       repairing it into a table is the point.

    Anything before the opening line is the human's own text.
    """
    canonical = _header_key(header_cells)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if canonical and _header_key(_split_row(stripped)) == canonical:
            return index
        for later in lines[index + 1:]:
            if not later.strip():
                continue
            if _is_separator(later.strip()):
                return index
            break
    return -1


def _parse_table(
    content: str, columns: int, header_cells: Sequence[str] = ()
) -> Tuple[List[str], List[List[str]], List[str], List[str]]:
    """Return (lines before the table, data rows, lines after, repairs).

    Both the preamble and the postamble are a human's own annotation — a note
    under the Stakeholders table naming someone's assistant, say — and the hard
    rule is that a merge never removes existing content. Trailing lines used to
    match neither branch here and were silently dropped on the next write.

    The table starts where `_find_header` says it does, and **a blank line ends
    it** — the renderer's rule again. So a pipe-prefixed line outside that span
    stays the paragraph Obsidian renders it as, while one inside it is a row,
    with its trailing `|` optional as GFM allows. Deciding row-ness on the
    line's own shape instead (trailing pipe, pipe count) misclassifies a row
    whose ` |` a human deleted while clearing the `needs-review` marker.

    Two hand-edit shapes are repaired, each with a note in `repairs`
    (#40, #41): a raw `|` a human typed into a cell is text, not a column
    break, so surplus cells are re-joined into the last column; and a deleted
    separator row no longer costs the first data row. Both change bytes and
    both converge — the file is canonical after one write, so neither note
    fires again. Nothing else is reported, because a note that repeats on
    every write of a healthy dossier is noise.

    Existing content is never deleted, but it may be **regrouped**: an
    annotation between two rows comes back below the table rather than in
    place. Keeping it exactly where it sat needs positional bookkeeping the
    merge does not carry. One shape is preserved rather than repaired — a table
    whose *header* is gone has no recognisable opening, so its rows come back
    as the preamble's prose and a fresh header is written above them. Nothing
    is lost; guessing which loose pipe-prefixed lines used to be rows is how
    prose gets eaten.
    """
    lines = _lines(content)
    repairs: List[str] = []
    header_index = _find_header(lines, header_cells)
    if header_index < 0:
        return lines, [], [], repairs

    rest = lines[header_index + 1:]
    cursor = 0
    while cursor < len(rest) and not rest[cursor].strip():
        cursor += 1
    if cursor < len(rest) and _is_separator(rest[cursor].strip()):
        cursor += 1
    else:
        # Only reachable through _find_header's rule 2 — the canonical header
        # with its separator deleted by hand. Obsidian renders the whole thing
        # as plain text; the rows are rescued and the separator comes back.
        cursor = 0
        repairs.append(
            "separator row was missing; the rows under the header were read as "
            "data — this write restores it"
        )

    rows: List[List[str]] = []
    postamble: List[str] = []
    closed = False
    for line in rest[cursor:]:
        stripped = line.strip()
        if not closed and stripped.startswith("|"):
            cells = _split_row(stripped)
            if len(cells) > columns:
                surplus = len(cells) - columns
                # Escaped, because rows live in stored form in memory:
                # _render_table writes them out verbatim, so the file becomes
                # self-consistent on this write and parses cleanly on the next.
                cells = cells[: columns - 1] + [r" \| ".join(cells[columns - 1:])]
                repairs.append(
                    f"re-joined {surplus} extra cell(s) into the last column; "
                    "an unescaped `|` in a cell is text, not a column break"
                )
            # A short row keeps the silent right-pad: a human who deleted a
            # trailing empty cell changed nothing a reader can see.
            cells += [""] * (columns - len(cells))
            rows.append(cells)
            continue
        closed = closed or not stripped
        postamble.append(line)
    return lines[:header_index], rows, postamble, repairs


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


def _merge_stakeholders(content: str, items) -> Tuple[str, int, List[str]]:
    preamble, rows, postamble, repairs = _parse_table(
        content, 5, _STAKEHOLDER_HEADER_CELLS)
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
    rendered = _render_table(preamble, STAKEHOLDER_HEADER, rows, postamble)
    return rendered, touched, repairs


_LINK_TEXT_RE = re.compile(r"\A\[([^\]]+)\]")


def _row_project_slug(cell: str) -> str:
    """The engagement row's project slug, taken from the link text.

    Safe to match without unescaping: _merge_engagements validates the project
    value as a slug, so no `\\|` escape can ever reach this cell.
    """
    match = _LINK_TEXT_RE.match(cell.strip())
    return match.group(1).strip() if match else cell.strip()


def _merge_engagements(content: str, items) -> Tuple[str, int, List[str]]:
    preamble, rows, postamble, repairs = _parse_table(
        content, 3, _ENGAGEMENT_HEADER_CELLS)
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
    rendered = _render_table(preamble, ENGAGEMENT_HEADER, rows, postamble)
    return rendered, touched, repairs


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
    "stakeholders": _merge_stakeholders,
    "relationship_history": _merge_relationship_history,
    "meeting_log": _merge_meeting_log,
    "sensitivities": _merge_sensitivities,
    "engagements": _merge_engagements,
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
    treatment — see _parse_table.) The check order matters: the retired-field
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

def write(root: Path, slug: str, edits: Mapping, today: str) -> dict:
    """Apply section edits to an existing dossier.

    Returns `{"path", "changes", "repairs"}`. `repairs` is always present and
    empty for a clean file; each entry names the section and what was tidied up
    in the human's own content. The skill surfaces it, because a repair the
    user is not told about is indistinguishable from a bug they will find
    later (#40).
    """
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
        # unvalidated.
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
            "repairs": repairs}


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
