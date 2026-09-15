"""Wikilink resolution and identity-link normalisation, shared by writers.

Obsidian resolves `[[name]]` by file name only. Entities and projects are
folders (`<slug>/dossier.md`, `<slug>/index.md`), so a bare `[[acme]]`
passes an existence check here and still dangles in the app — clicking it
spawns an empty note in the vault root. Every writer that emits prose
therefore routes it through `normalise`, which rewrites identity links to
`[[<vault path>|<display name>]]` and keeps decision 19's alias check.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from . import markdown, vault

# `#heading` is stripped before resolution; `|alias` is the display-name
# claim. `!?` catches embeds, which make the same claim as a plain link.
WIKILINK_RE = re.compile(
    r"(!?)\[\[([^\[\]|#]+)(#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")

_IDENTITY = ("entity", "person", "project")
_SAFE_TARGET_RE = re.compile(r"\A[A-Za-z0-9._ -]+(?:/[A-Za-z0-9._ -]+)*\Z")


def _classify(root: Path, path: Path) -> Tuple[Optional[str], Optional[str]]:
    """(kind, display-name key) for a vault file by where it sits."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None, None
    parts = rel.split("/")
    if parts[0] == vault.ENTITIES_DIR and len(parts) == 3 and parts[2] == "dossier.md":
        return "entity", "entity-name"
    if parts[0] == vault.PEOPLE_DIR and len(parts) == 2:
        return "person", "person-name"
    if parts[0] == vault.PROJECTS_DIR and len(parts) == 3 and parts[2] == "index.md":
        return "project", "project-name"
    if parts[0] == vault.PROJECTS_DIR and len(parts) == 4 and parts[2] == "decisions":
        return "decision", None
    if parts[0] == vault.MEETINGS_DIR and len(parts) == 2:
        return "meeting", None
    if parts[0] == vault.DAILY_NOTES_DIR and len(parts) == 2:
        return "daily note", None
    return None, None


def resolve(root: Path, target: str):
    """(kind, path, display-name key) for a wikilink target, or three Nones.

    A bare slug/stem is looked up in the layout order identity objects
    first (they are the ones whose *name* an alias claims). A target with a
    `/` is a vault path without `.md` and is classified by where it sits.
    """
    target = str(target or "").strip()
    if not target or not _SAFE_TARGET_RE.match(target):
        return None, None, None
    if any(segment in (".", "..") for segment in target.split("/")):
        return None, None, None
    if "/" in target:
        path = (root / f"{target}.md")
        if path.is_file():
            kind, key = _classify(root, path)
            if kind is not None:
                return kind, path, key
        return None, None, None
    candidates = (
        ("entity", root / vault.ENTITIES_DIR / target / "dossier.md", "entity-name"),
        ("person", root / vault.PEOPLE_DIR / f"{target}.md", "person-name"),
        ("project", root / vault.PROJECTS_DIR / target / "index.md", "project-name"),
        ("meeting", root / vault.MEETINGS_DIR / f"{target}.md", None),
        ("daily note", root / vault.DAILY_NOTES_DIR / f"{target}.md", None),
    )
    for kind, path, name_key in candidates:
        if path.is_file():
            return kind, path, name_key
    projects = root / vault.PROJECTS_DIR
    for folder in sorted(projects.glob("*/decisions")) if projects.is_dir() else []:
        path = folder / f"{target}.md"
        if path.is_file():
            return "decision", path, None
    return None, None, None


def path_target(root: Path, path: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return rel[:-3] if rel.endswith(".md") else rel


def display_name(path: Path, name_key: str) -> Optional[str]:
    """The object's display name, None when the frontmatter cannot say."""
    try:
        frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    value = str(frontmatter.get(name_key) or "").strip()
    return value or None


def normalise(root: Path, text: str, label: str) -> Tuple[str, List[str], List[str]]:
    """Rewrite identity links to path form; collect offenders and warnings.

    Offenders (the caller refuses the write): an unresolvable target, or an
    identity alias that is not the object's display name. Warnings (the
    write proceeds): an identity object whose display name cannot be read,
    in which case the slug stands in so the link still opens the object.
    """
    offenders: List[str] = []
    warnings: List[str] = []

    def replace(match: re.Match) -> str:
        bang, raw_target, anchor, alias = match.groups()
        target = raw_target.strip()
        kind, path, name_key = resolve(root, target)
        if kind is None:
            offenders.append(
                f"{label}: [[{target}]] resolves to no vault object — link "
                "only to objects that exist (create one with /update-entity "
                "or /new-project first), or leave the name out. Never write "
                "a name you have not looked up.")
            return match.group(0)
        if kind not in _IDENTITY:
            return match.group(0)
        actual = display_name(path, name_key)
        if actual is None:
            warnings.append(
                f"{label}: [[{target}]] carries no readable {name_key} — "
                "display name not verified; the slug stands in")
            shown = path.parent.name if kind != "person" else path.stem
        else:
            shown = actual
            if alias is not None and alias.strip() != actual:
                offenders.append(
                    f"{label}: [[{target}|{alias}]] — that {kind} is called "
                    f"{actual!r}. Display names come from the vault, never "
                    "from the model.")
                return match.group(0)
        return f"{bang}[[{path_target(root, path)}{anchor or ''}|{shown}]]"

    return WIKILINK_RE.sub(replace, text), offenders, warnings
