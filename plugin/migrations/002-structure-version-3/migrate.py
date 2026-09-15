"""Structure-version 3: project index v2 (readability).

Reshapes each `30-projects/*/index.md` that still carries the v1 sections
(`## Decisions`, `## Open Items`, `## Related Meetings`) into the v2 body:
a `Where it stands` card, a `Coming up` table, `Recent meetings` and
`Recent decisions` Dataview blocks capped at 10 rows, and a folded
`Background` (Owe by owner, Awaiting, Open questions, Pending, Watch list,
Context). Text is moved and re-bulleted, never dropped: the `·`/`;`-joined
mega-lines become one bullet per item. The next evening run then rewrites
the prose through `project state write`, which is where it gets short.

Touches no template-managed file. Frontmatter is untouched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, projectstate, vault  # noqa: E402

TARGET_VERSION = 3
LOSSY = None

V1_SECTIONS = ("Decisions", "Open Items", "Related Meetings")
V2_SECTIONS = ("Coming up", "Recent meetings", "Recent decisions", "Background")
_PLACEHOLDERS = {"_none yet_", "_none scheduled_", "none yet", ""}
_CALLOUT_BULLET_RE = re.compile(r"\A>\s*-\s*\*\*(.+?)\*\*\s*[—:-]\s*(.*)\Z")
_OPEN_ITEM_RE = re.compile(r"\A-\s*\*\*(?:[^\w\s]+\s*)?(Owe|Awaiting|Question|Pending)\*\*\s*[—:-]\s*(.*)\Z")
_OWNER_RE = re.compile(r"\A(?:📤\s*)?([A-Z][\w'’.\- ]{1,40}?)\s*:\s+(.*)\Z")
_LEGACY_CALLOUT_RE = re.compile(r"\A>\s*\[!\w+\][+-]?\s*\*\*(Now|Context)\*\*")
# A `;` immediately followed by another owner prefix always separates two
# owners' entries — Open Items writes `Priya: a; Jamie: b` with exactly one
# `;`, and it must split there regardless of the ≥2 rule below.
_OWNER_SPLIT_RE = re.compile(r";\s+(?=(?:📤\s*)?[A-Z][\w'’.\- ]{1,40}:\s)")


def _split_items(text: str) -> List[str]:
    """One bullet per item: split on ` · ` first; a chunk splits further on
    `; ` only when it holds two or more `;` — one `;` is prose, two or more
    is a chained list (the same threshold `projectstate.validate` refuses:
    ≥ 2 `;` in one rendered item means it chains several tasks in one
    bullet). A single `;` inside a chunk is left exactly as written."""
    items: List[str] = []
    for chunk in re.split(r"\s·\s", text):
        pieces = re.split(r";\s+", chunk) if chunk.count(";") >= 2 else [chunk]
        for piece in pieces:
            piece = piece.strip().rstrip(";").strip()
            if piece and piece not in _PLACEHOLDERS:
                items.append(piece)
    return items


def _collect_owe(text: str, groups: Dict[str, List[str]]) -> None:
    """Fold a v1 Owe line into `groups` (owner -> tasks), insertion-ordered.

    ` · ` separates owner chunks. Inside a chunk, a `;` immediately followed
    by another owner prefix (`Name:` or `📤 Name:`) always starts a new
    owner segment, regardless of how many `;` the chunk holds — Open Items
    writes `Priya: a; Jamie: b` with exactly one `;` and it must still split
    there, or Jamie's task would be swallowed into Priya's. Within each
    owner segment, a `;` splits further into separate tasks only when the
    segment holds two or more of them — one `;` is prose, two or more is a
    chained list (the same threshold `projectstate.validate` refuses: ≥ 2
    `;` in one rendered item means it chains several tasks in one bullet).
    A task that itself opens with `Name:` starts a new owner (Open Items
    wrote `Priya: a; Jamie: b`); one that does not inherits the segment's
    owner (the Now callout wrote `📤 Priya: a; b; c · 📤 Leo: c`, where
    `a; b; c` are Priya's own tasks, not new owners). A task with no owner
    anywhere lands under "Unassigned". A task phrased `Anthropic: push
    harder` reads as owner "Anthropic" — acceptable for a reshape the next
    evening run rewrites.
    """
    for chunk in re.split(r"\s·\s", text or ""):
        owner = "Unassigned"
        for segment in _OWNER_SPLIT_RE.split(chunk):
            pieces = re.split(r";\s+", segment) if segment.count(";") >= 2 else [segment]
            for piece in pieces:
                piece = piece.strip().rstrip(";").strip()
                if not piece or piece in _PLACEHOLDERS:
                    continue
                match = _OWNER_RE.match(piece)
                if match:
                    owner, piece = match.group(1).strip(), match.group(2).strip()
                    if not piece:
                        continue
                groups.setdefault(owner, [])
                if piece not in groups[owner]:
                    groups[owner].append(piece)


def _callout_bullets(preamble: str, title: str) -> Dict[str, str]:
    """`label -> text` for the bullets of the `**title**` callout in the preamble."""
    out: Dict[str, str] = {}
    inside = False
    for line in preamble.split("\n"):
        header = _LEGACY_CALLOUT_RE.match(line)
        if header:
            inside = header.group(1) == title
            continue
        if not line.startswith(">"):
            inside = False
            continue
        if inside:
            bullet = _CALLOUT_BULLET_RE.match(line.strip())
            if bullet:
                out[bullet.group(1).strip()] = bullet.group(2).strip()
    return out


def parse_v1_body(body: str) -> dict:
    sections = markdown.split_sections(body, level=2)
    preamble = sections[0][1]
    now = _callout_bullets(preamble, "Now")
    context = _callout_bullets(preamble, "Context")
    open_items: Dict[str, str] = {}
    for title, content in sections[1:]:
        if title == "Open Items":
            for line in content.split("\n"):
                match = _OPEN_ITEM_RE.match(line.strip())
                if match:
                    open_items[match.group(1)] = match.group(2).strip()
    stage = now.get("Stage", "").strip()
    decision = now.get("Defining decision", "").strip()
    owe_groups: Dict[str, List[str]] = {}
    _collect_owe(now.get("Owe", ""), owe_groups)
    _collect_owe(open_items.get("Owe", ""), owe_groups)
    return {
        "stage": stage if stage not in _PLACEHOLDERS else None,
        "defining_decision": decision if decision not in _PLACEHOLDERS else None,
        "coming_up": [{"when": "", "what": item} for item in _split_items(now.get("Next event", ""))],
        "owe": [{"owner": owner, "items": tasks} for owner, tasks in owe_groups.items()],
        "awaiting": _split_items(open_items.get("Awaiting", "")),
        "questions": _split_items(open_items.get("Question", "")),
        "pending": _split_items(open_items.get("Pending", "")),
        "watch": _split_items(now.get("Watch", "")),
        "context": {
            "contacts": (context.get("Contacts") or "").strip() or None,
            "source": (context.get("Source") or "").strip() or None,
        },
    }


def _is_v1(body: str) -> bool:
    titles = {title for title, _ in markdown.split_sections(body, level=2)}
    return bool(titles & set(V1_SECTIONS)) and not ({"Background"} <= titles)


def _reshape(path: Path, root: Path) -> None:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    frontmatter, body = markdown.split_frontmatter(text)
    head = text[:len(text) - len(body)]
    slug = path.parent.name
    name = str(frontmatter.get("project-name") or slug)
    as_of = str(frontmatter.get("last-updated") or frontmatter.get("created") or "1970-01-01")[:10]
    if not vault.ISO_DATE_RE.match(as_of):
        as_of = "1970-01-01"
    state = parse_v1_body(body)
    state["as_of"] = as_of
    for row in state["coming_up"]:
        row["when"] = row["when"] or "—"
    _, tail = projectstate.split_notes_tail(body)
    state["notes_tail"] = tail
    vault.atomic_write(path, head + projectstate.render_body(name, slug, state))


def apply(root: Path) -> dict:
    reshaped: List[str] = []
    skipped: List[str] = []
    unparsed: List[str] = []
    projects = root / vault.PROJECTS_DIR
    for path in sorted(projects.glob("*/index.md")) if projects.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            _, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            unparsed.append(rel)
            continue
        if not _is_v1(body):
            skipped.append(path.parent.name)
            continue
        try:
            _reshape(path, root)
        except (ValueError, KeyError) as exc:
            unparsed.append(f"{rel}: {exc}")
            continue
        reshaped.append(path.parent.name)
    return {"reshaped": reshaped, "skipped": skipped, "unparsed": unparsed}


def verify(root: Path) -> dict:
    checked = 0
    projects = root / vault.PROJECTS_DIR
    for path in sorted(projects.glob("*/index.md")) if projects.is_dir() else []:
        try:
            _, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue   # apply already reported it as unparsed; not this step's failure
        titles = [title for title, _ in markdown.split_sections(body, level=2)]
        stale = [t for t in titles if t in V1_SECTIONS]
        if stale:
            raise RuntimeError(
                f"{path.relative_to(root).as_posix()} still carries v1 section(s) {stale}")
        missing = [t for t in V2_SECTIONS if t not in titles]
        if missing:
            raise RuntimeError(
                f"{path.relative_to(root).as_posix()} lacks v2 section(s) {missing}")
        checked += 1
    return {"checked": checked}
