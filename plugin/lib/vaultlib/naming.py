"""Slug derivation and validation. Pure string logic — no filesystem access."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

MAX_SLUG_LENGTH = 60

# Windows refuses these stems whatever the extension. The vault syncs to
# Windows machines even when written from the Cowork Linux VM, so a slug that
# is legal where it is created can be illegal where it lands.
RESERVED_STEMS = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)]
)

_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Lowercase, hyphen-joined, ASCII-only slug.

    Truncation drops a trailing partial segment rather than cutting a word in
    half, and the result is length-capped because a vault synced to Windows
    inherits its 260-character path limit.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG_CHARS.sub("-", ascii_only.lower()).strip("-")
    if not slug:
        raise ValueError(f"{text!r} produced an empty slug")
    if len(slug) <= max_length:
        return slug
    cut = slug[:max_length]
    # If the character just past the cut is neither the end nor a hyphen, the
    # cut landed inside a segment — drop that partial segment.
    if slug[max_length : max_length + 1] not in ("", "-"):
        head = cut.rpartition("-")[0]
        cut = head or cut
    result = cut.strip("-")
    if not result:
        raise ValueError(f"{text!r} produced an empty slug at max_length={max_length}")
    return result


def validate_slug(slug: str) -> None:
    """Raise ValueError if the slug is unusable as a folder or file stem."""
    if not slug:
        raise ValueError("slug is empty")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"slug {slug!r} must be lowercase alphanumeric segments joined by "
            "single hyphens, with no leading or trailing hyphen"
        )
    if len(slug) > MAX_SLUG_LENGTH:
        raise ValueError(f"slug {slug!r} exceeds {MAX_SLUG_LENGTH} characters")
    if slug in RESERVED_STEMS:
        raise ValueError(f"slug {slug!r} is a reserved filename on Windows")


def find_collision(slug: str, existing: Iterable[str]) -> Optional[str]:
    """Return the colliding existing name, or None.

    Case-insensitive: the Cowork VM is Linux and will create both `Foo` and
    `foo`, but the APFS or NTFS host underneath collapses them into one.
    """
    lowered = slug.lower()
    for name in existing:
        if name.lower() == lowered:
            return name
    return None
