"""Person notes.

Auto-created from a display name. The body stays empty on purpose: person
notes are curated through People.base, and an invented body would be noise
the vault owner has to clear.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

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
                text = found.read_text(encoding="utf-8")
                vault.atomic_write(found, markdown.upsert_scalar_field(text, "entity", entity))
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
    leaves a field alone; an empty string clears it."""
    found = _existing_note(root, slug)
    if found is None:
        raise ValueError(f"no person {slug!r} in {PEOPLE_DIR}/")
    text = found.read_text(encoding="utf-8")
    current, _ = markdown.split_frontmatter(text)
    wanted = {"entity": entity, "role": role, "decision-role": decision_role, "stance": stance}
    changed = []
    for prop, value in wanted.items():
        if value is None:
            continue
        value = str(value).strip()
        if value and prop == "entity":
            value = _require_entity(root, value)
        if value and prop in _ENUMS and value not in _ENUMS[prop]:
            raise ValueError(f"{prop} {value!r} is not one of {list(_ENUMS[prop])}")
        if str(current.get(prop) or "") == value:
            continue
        rendered = markdown.emit_scalar(value, prop in PERSON_QUOTE_KEYS) if value else ""
        text = markdown.upsert_scalar_field(text, prop, rendered)
        changed.append(prop)
    if changed:
        vault.atomic_write(found, text)
    return {"slug": found.stem, "path": found.relative_to(root).as_posix(), "changed": changed}
