"""Person notes.

Auto-created from a display name. The body stays empty on purpose: person
notes are curated through People.base, and an invented body would be noise
the vault owner has to clear.
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
    survive every later call. But (#97) a caller-supplied name that differs
    from the note's own is reported, not silently dropped: an envelope with
    no signal at all reads as an ordinary success.
    """
    slug = naming.slugify(name)
    naming.validate_slug(slug)

    found = _existing_note(root, slug)
    if found is not None:
        result = {
            "slug": slug,
            "path": found.relative_to(root).as_posix(),
            "created": False,
        }
        existing, _ = markdown.split_frontmatter(
            found.read_text(encoding="utf-8"))
        if existing.get("person-name") != name:
            result["ignored"] = ["name"]
            result["reason"] = (
                "person notes are curated through People.base and are never "
                "rewritten by ensure; edit the note directly to change the name"
            )
        return result

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
