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


def ensure(root: Path, name: str, today: str,
           email: Optional[str] = None) -> dict:
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
        "company": None,
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
