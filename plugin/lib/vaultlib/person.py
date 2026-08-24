"""Person notes.

Auto-created from a display name. The body stays empty on purpose: person
notes are curated through People.base, and an invented body would be noise
the assistant has to clear.
"""
from __future__ import annotations

from pathlib import Path

from . import markdown, naming, vault

PEOPLE_DIR = vault.PEOPLE_DIR
PERSON_QUOTE_KEYS = frozenset({"person-name", "company", "role"})


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


def ensure(root: Path, name: str, today: str) -> dict:
    """Create 50-people/{slug}.md if no note for this person exists yet.

    Never rewrites an existing note — curation added through People.base must
    survive every later call.
    """
    slug = naming.slugify(name)
    naming.validate_slug(slug)

    found = _existing_note(root, slug)
    if found is not None:
        return {
            "slug": slug,
            "path": found.relative_to(root).as_posix(),
            "created": False,
        }

    frontmatter = {
        "person-name": name,
        "slug": slug,
        "email": None,
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
    )
    return {"slug": slug, "path": target.relative_to(root).as_posix(), "created": True}
