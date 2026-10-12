"""Person notes.

Auto-created from a display name. The frontmatter is curated through
People.base. The body holds one machine-written part: `## What I know`
(#273 piece 4), dated facts the person said about themselves, each ending in
its source marker, appended by `write_facts` and never edited or removed by
it. Every other line on the page is the owner's.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import markdown, naming, vault

PEOPLE_DIR = vault.PEOPLE_DIR
ENTITIES_DIR = vault.ENTITIES_DIR
PERSON_QUOTE_KEYS = frozenset({"person-name", "company", "role"})
# One address, nothing YAML could read as structure: no whitespace (which
# also rules out newlines), no quotes, brackets, commas or `#`.
EMAIL_RE = re.compile(r"\A[^\s@\"'\[\]{},#]+@[^\s@\"'\[\]{},#]+\.[^\s@\"'\[\]{},#]+\Z")


def _existing_note(root: Path, slug: str):
    """Return an existing note path matching slug case-insensitively."""
    people = root / PEOPLE_DIR
    if not people.is_dir():
        return None
    lowered = slug.lower()
    for candidate in sorted(people.glob("*.md")):
        if candidate.stem.lower() == lowered:
            return candidate
    return None


def _require_email(value) -> str:
    text = str(value).strip()
    if not EMAIL_RE.match(text):
        raise ValueError(f"email {value!r} is not a single email address")
    # Casefolded so the message feed's address book (#249) matches it.
    return text.casefold()


def _require_entity(root: Path, value: str) -> str:
    value = str(value).strip()
    naming.validate_slug(value)
    if not (root / ENTITIES_DIR / value / "dossier.md").is_file():
        raise ValueError(f"entity {value!r} has no dossier at {ENTITIES_DIR}/{value}/dossier.md")
    return value


def ensure(root: Path, name: str, today: str,
           email: Optional[str] = None, entity: Optional[str] = None) -> dict:
    """Create 50-people/{slug}.md if no note for this person exists yet.

    Never rewrites an existing note — curation added through People.base must
    survive every later call. But (#97) a caller-supplied name that differs
    from the note's own is reported, not silently dropped: an envelope with
    no signal at all reads as an ordinary success.

    The one exception is an empty `email`: the M365 sync knows each
    attendee's address, and a note created before it passed one (#242) gets
    it filled the next time that person is seen. A set email is never
    overwritten — a differing one is reported as ignored, like the name.
    """
    slug = naming.slugify(name)
    naming.validate_slug(slug)
    if email is not None:
        email = _require_email(email)
    if entity is not None:
        entity = _require_entity(root, entity)

    found = _existing_note(root, slug)
    if found is not None:
        result = {
            "slug": slug,
            "path": found.relative_to(root).as_posix(),
            "created": False,
        }
        text = found.read_text(encoding="utf-8")
        existing, _ = markdown.split_frontmatter(text)
        ignored = []
        if existing.get("person-name") != name:
            ignored.append("name")
        if email is not None:
            current = str(existing.get("email") or "").strip()
            if not current:
                vault.atomic_write(found, markdown.upsert_scalar_field(
                    text, "email", markdown.emit_scalar(email, quoted=False)))
                result["updated"] = ["email"]
            elif current.casefold() != email.casefold():
                ignored.append("email")
        if entity is not None:
            # Same fill-if-empty rule as email (#273): routing only knows an
            # entity for certain, and a set link is the owner's.
            linked = str(existing.get("entity") or "").strip()
            if not linked:
                # `entity` replaces the legacy free-text `company` (#273).
                text = found.read_text(encoding="utf-8")
                vault.atomic_write(found, markdown.remove_field(
                    markdown.upsert_scalar_field(text, "entity", entity), "company"))
                result.setdefault("updated", []).append("entity")
            elif linked != entity:
                ignored.append("entity")
        if ignored:
            result["ignored"] = ignored
            result["reason"] = (
                "person notes are curated through People.base and are never "
                "rewritten by ensure (only an empty email is filled); edit "
                "the note directly to change " + " or ".join(ignored)
            )
        return result

    frontmatter = {
        "person-name": name,
        "slug": slug,
        "email": email,
        # Key present with an empty value = uncurated. People.base's
        # "Uncurated" view filters on exactly this.
        "relationship": None,
        "entity": entity,
        "role": None,
        "projects": [],
        "created": today,
        "last-updated": today,
        "meetings-7d": 0,
        "meetings-30d": 0,
    }
    target = root / PEOPLE_DIR / f"{slug}.md"
    vault.atomic_write(
        target, markdown.emit_frontmatter(frontmatter, PERSON_QUOTE_KEYS)
        # The name is the page's heading (#258), not the file's slug.
        + "\n" + markdown.title_heading(name) + "\n"
    )
    return {"slug": slug, "path": target.relative_to(root).as_posix(), "created": True}


def set_email_if_missing(root: Path, slug: str, email: str) -> bool:
    """Fill a person note's empty `email` (the message feed learns addresses
    from Teams chat members). Never overwrites one that is set."""
    found = _existing_note(root, slug)
    address = str(email or "").strip().casefold()
    if found is None or "@" not in address:
        return False
    try:
        text = found.read_text(encoding="utf-8")
        frontmatter, _ = markdown.split_frontmatter(text)
        if frontmatter.get("email"):
            return False
        updated = markdown.upsert_scalar_field(
            text, "email", markdown.emit_scalar(address, quoted=False))
    except (ValueError, OSError):
        return False
    vault.atomic_write(found, updated)
    return True


def address_book(root: Path) -> Dict[str, str]:
    """Map every person note's email to its slug."""
    book: Dict[str, str] = {}
    people = root / PEOPLE_DIR
    for path in sorted(people.glob("*.md")) if people.is_dir() else []:
        try:
            frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        address = str(frontmatter.get("email") or "").strip().casefold()
        if "@" in address and frontmatter.get("slug"):
            book.setdefault(address, str(frontmatter["slug"]))
    return book


_ENUMS = {"decision-role": ("sponsor", "champion", "evaluator", "influencer", "blocker"),
          "stance": ("champion", "neutral", "blocker")}


def set_fields(root: Path, slug: str, *, entity: Optional[str] = None,
               role: Optional[str] = None, decision_role: Optional[str] = None,
               stance: Optional[str] = None) -> dict:
    """Write a person's entity link and stakeholder fields (#273). `None`
    leaves a field alone; an empty string clears it. Vocabulary words are
    matched case-insensitively and stored lowercase. Setting an entity drops
    the legacy free-text `company` it replaces.

    The result's `was` maps each changed field to its previous value (""
    when it had none), so a caller can say "moved from acme-finance"."""
    found = _existing_note(root, slug)
    if found is None:
        raise ValueError(f"no person {slug!r} in {PEOPLE_DIR}/")
    text = found.read_text(encoding="utf-8")
    current, _ = markdown.split_frontmatter(text)
    wanted = {"entity": entity, "role": role, "decision-role": decision_role, "stance": stance}
    changed, was = [], {}
    for prop, value in wanted.items():
        if value is None:
            continue
        value = str(value).strip()
        if value and prop == "entity":
            value = _require_entity(root, value)
        if prop in _ENUMS:
            value = value.lower()
            if value and value not in _ENUMS[prop]:
                raise ValueError(f"{prop} {value!r} is not one of {list(_ENUMS[prop])}")
        previous = "" if current.get(prop) is None else str(current.get(prop)).strip()
        if previous == value:
            continue
        rendered = markdown.emit_scalar(value, prop in PERSON_QUOTE_KEYS) if value else ""
        text = markdown.upsert_scalar_field(text, prop, rendered)
        if prop == "entity" and value:
            text = markdown.remove_field(text, "company")
        changed.append(prop)
        was[prop] = previous
    if changed:
        vault.atomic_write(found, text)
    return {"slug": found.stem, "path": found.relative_to(root).as_posix(),
            "changed": changed, "was": was}


FACTS_HEADING = "What I know"
_STAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")


def _require_note(root: Path, slug: str) -> Path:
    found = _existing_note(root, slug)
    if found is None:
        raise ValueError(f"no person {slug!r} in {PEOPLE_DIR}/")
    return found


def _is_iso_date(value: str) -> bool:
    if not vault.ISO_DATE_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _ends_in_open_fence(text: str) -> bool:
    """True when `text` leaves a ``` / ~~~ block open, by split_sections'
    own fence rule."""
    fence = None
    for line in text.split("\n"):
        match = markdown._FENCE_RE.match(line)
        if match:
            token = match.group(1)
            fence = None if fence == token else (fence or token)
    return fence is not None


def insert_section_after_preamble(body: str, heading: str, lines: List[str]) -> str:
    """Append `lines` to `## heading`, creating the section right after the
    body's preamble (the `# Name` H1 and anything before the first `##`)
    when it is missing. Nothing else in the body changes."""
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title.strip().lower() == heading.lower():
            kept = content.rstrip("\n")
            last = kept.split("\n")[-1].strip() if kept.strip() else ""
            gap = "\n" if (not last or last.startswith("- ")) else "\n\n"
            if not kept.strip():
                kept, gap = "", "\n"
            sections[i] = (title, kept + gap + "\n".join(lines) + "\n")
            return markdown.render_sections(sections)
    preamble = sections[0][1]
    if not preamble.endswith("\n"):
        preamble += "\n"
    sections[0] = ("", preamble)
    sections.insert(1, (heading, "\n" + "\n".join(lines) + "\n"))
    return markdown.render_sections(sections)


def write_facts(root: Path, slug: str, facts, today: str) -> dict:
    """Append dated, sourced facts under `## What I know` (#273 piece 4).

    Only appends. An item that is not `{date, fact}` with a real ISO date and
    a one-line fact ending in a source marker is listed in `skipped`; a line
    already in the section is listed in `duplicates`. Nothing is written —
    not even `last-updated` — when no item survives."""
    from .entity import _SOURCE_MARKER_RE
    if not isinstance(facts, list):
        raise ValueError("facts must be a list of {date, fact} objects")
    path = _require_note(root, slug)
    text = path.read_text(encoding="utf-8")
    _, body = markdown.split_frontmatter(text)
    head = markdown._normalize(text)[: len(markdown._normalize(text)) - len(body)]
    existing = set()
    sections = markdown.split_sections(body)
    target = sections[0][1]          # the preamble, when the section is new
    for title, content in sections:
        if title.strip().lower() == FACTS_HEADING.lower():
            existing = {line.strip() for line in content.split("\n") if line.strip()}
            target = content
            break
    if _ends_in_open_fence(target):
        # A line appended here would be code, not a fact — and so would
        # every later night's (review I2). The owner closes the block first.
        return {"slug": path.stem, "path": path.relative_to(root).as_posix(),
                "written": 0, "duplicates": [],
                "skipped": [f"facts: '## {FACTS_HEADING}' ends inside an unclosed code "
                            "block (```); close it on the page and retry — nothing "
                            "was written"]}
    lines, skipped, duplicates = [], [], []
    for index, item in enumerate(facts):
        if not isinstance(item, dict):
            skipped.append(f"facts[{index}]: not an object with date and fact")
            continue
        day = str(item.get("date") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if not _is_iso_date(day):
            skipped.append(f"facts[{index}]: date {day!r} is not YYYY-MM-DD")
        elif not fact:
            skipped.append(f"facts[{index}]: empty fact")
        elif "\n" in fact or "\r" in fact:
            skipped.append(f"facts[{index}]: a fact must be one line")
        elif not _SOURCE_MARKER_RE.search(fact):
            skipped.append(f"facts[{index}]: no source marker at the end — an "
                           "automatic line must say where it came from; not written")
        else:
            line = f"- {day} — {fact}"
            if line in existing:
                duplicates.append(line)
            else:
                existing.add(line)
                lines.append(line)
    rel = path.relative_to(root).as_posix()
    if lines:
        new_body = insert_section_after_preamble(body, FACTS_HEADING, lines)
        updated = markdown.upsert_scalar_field(head + new_body, "last-updated", today)
        vault.atomic_write(path, updated)
    return {"slug": path.stem, "path": rel, "written": len(lines),
            "skipped": skipped, "duplicates": duplicates}


def touch(root: Path, slug: str, *, timestamp: Optional[str] = None) -> dict:
    """Stamp `person-updated`: the automatic update has read every piece of
    new material naming this person up to this minute (#273 piece 4)."""
    if timestamp is None:
        timestamp = datetime.datetime.now().isoformat(timespec="minutes")
    try:
        valid = bool(_STAMP_RE.match(str(timestamp))) and bool(
            datetime.datetime.strptime(str(timestamp), "%Y-%m-%dT%H:%M"))
    except ValueError:
        valid = False
    if not valid:
        # The stamp is the queue's start point: a month 13 or a 99:99 would
        # stop this person from ever being read again (review I1).
        raise ValueError(f"timestamp {timestamp!r} must be a real YYYY-MM-DDTHH:MM")
    path = _require_note(root, slug)
    text = path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "person-updated", timestamp)
    if updated != text:
        vault.atomic_write(path, updated)
    return {"slug": path.stem, "path": path.relative_to(root).as_posix(),
            "person-updated": timestamp, "changed": updated != text}
