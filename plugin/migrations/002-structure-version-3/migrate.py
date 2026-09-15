"""Structure-version 3: project index v2 (readability).

Reshapes each `30-projects/*/index.md` that still carries the v1 sections
(`## Decisions`, `## Open Items`, `## Related Meetings`) into the v2 body:
a `Where it stands` card, a `Coming up` table, `Recent meetings` and
`Recent decisions` Dataview blocks capped at 10 rows, and a folded
`Background` (Owe by owner, Awaiting, Open questions, Pending, Watch list,
Context). Text is moved and re-bulleted, never dropped: the `·`/`;`-joined
mega-lines become one bullet per item. The next evening run then rewrites
the prose through `project state write`, which is where it gets short.

`LOSSY = None` is lossless by construction, not by convention. Anything the
parser cannot classify — an `## Open Items` written as a prose paragraph
instead of the expected `- **Owe** —` bullets, a `Now`/`Context` callout
bullet under a label the parser does not map, stray preamble prose outside
the title and the two callouts, or an entire extra `## ` section the v1
format never defined — is carried verbatim into a `### Carried over by the
structure-version 3 upgrade` block under `## Notes` (appended to an
existing Notes tail, or a fresh one) rather than dropped on the floor. The
one exception: the Dataview fences inside `## Decisions` and
`## Related Meetings` are not carried — those two blocks are exactly what
this migration replaces with the `Recent decisions`/`Recent meetings`
queries, so carrying them forward would duplicate the query, not preserve a
human's words.

Touches no template-managed file. Frontmatter is untouched. A vault upgraded
1→2→3 keeps the structure-version-2 ontology (`body_sections: [Decisions,
Open Items, Related Meetings]`) that migration 001 wrote until the
consultant accepts the template refresh in `/upgrade-vault`'s consent step,
because the ontology is a template-managed file this migration deliberately
does not touch.
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
_QUOTE_PREFIX_RE = re.compile(r"\A[ \t]*>[ \t]?")

# The bullet labels each callout maps into `parse_v1_body`'s output. A
# callout bullet under any other label is unclassified and gets carried —
# see `_scan_preamble`.
_NOW_LABELS = {"Stage", "Defining decision", "Next event", "Owe", "Watch"}
_CONTEXT_LABELS = {"Contacts", "Source"}
# v1 H2 sections `parse_v1_body` already accounts for by name. `Notes` is
# excluded from carrying (not "unclassified") because it is the destination
# the carried content itself lands in — see `_carry_over_tail`.
_KNOWN_V1_SECTIONS = set(V1_SECTIONS) | {"Notes"}
_CARRY_HEADING = "### Carried over by the structure-version 3 upgrade"


def _unquote(line: str) -> str:
    """One level of `>` removed. Content carried out of a Now/Context
    callout into the flat `## Notes` tail should not keep the blockquote
    marker that only meant something inside the callout box."""
    return _QUOTE_PREFIX_RE.sub("", line, count=1)


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


def _scan_preamble(preamble: str):
    """`(now bullets, context bullets, carried lines)` from the preamble.

    Single pass, because "carried" is everything the other two do *not*
    claim: a Now/Context callout bullet under a label `_NOW_LABELS`/
    `_CONTEXT_LABELS` does not list, any other `>`-prefixed line inside
    those callouts that is not a bullet at all, and any non-blank preamble
    line outside the H1 title and the two callouts. Carried callout content
    is unquoted (`_unquote`) since it is leaving the callout box; carried
    lines from outside a callout keep whatever they looked like (a stray
    prose paragraph, or even some other callout the v1 format never
    defined) verbatim.
    """
    now: Dict[str, str] = {}
    context: Dict[str, str] = {}
    carried: List[str] = []
    inside = None  # None | "Now" | "Context"
    seen_title = False
    for line in preamble.split("\n"):
        header = _LEGACY_CALLOUT_RE.match(line)
        if header:
            inside = header.group(1)
            continue
        if inside and line.startswith(">"):
            stripped = line.strip()
            known = _NOW_LABELS if inside == "Now" else _CONTEXT_LABELS
            target = now if inside == "Now" else context
            bullet = _CALLOUT_BULLET_RE.match(stripped)
            if bullet:
                label, text = bullet.group(1).strip(), bullet.group(2).strip()
                if label in known:
                    target[label] = text
                else:
                    carried.append(_unquote(line).rstrip())
            elif stripped not in ("", ">"):
                carried.append(_unquote(line).rstrip())
            continue
        inside = None
        stripped = line.strip()
        if not stripped:
            continue
        if not seen_title and stripped.startswith("# ") and not stripped.startswith("## "):
            seen_title = True  # the H1 title — not carried
            continue
        carried.append(line.rstrip())
    return now, context, carried


def parse_v1_body(body: str) -> dict:
    sections = markdown.split_sections(body, level=2)
    preamble = sections[0][1]
    now, context, carry = _scan_preamble(preamble)
    open_items: Dict[str, str] = {}
    carry_open_items: List[str] = []
    other_sections: List[str] = []
    for title, content in sections[1:]:
        if title == "Open Items":
            for line in content.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                match = _OPEN_ITEM_RE.match(stripped)
                if match:
                    open_items[match.group(1)] = match.group(2).strip()
                else:
                    carry_open_items.append(line.rstrip())
        elif title not in _KNOWN_V1_SECTIONS:
            # Every other v1 H2 section is one the parser never defined —
            # e.g. a hand-added `## Links` — and its whole content is
            # carried, not just individual lines.
            trimmed = content.strip("\n")
            if trimmed:
                other_sections.append(f"#### {title}\n\n{trimmed}")
    carry_blocks: List[str] = []
    if carry:
        carry_blocks.append("\n".join(carry))
    if carry_open_items:
        carry_blocks.append("\n".join(carry_open_items))
    carry_blocks.extend(other_sections)

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
        # Not a `render_body` field — `_reshape` pops this to build the
        # Notes tail and never passes it through. `parse_v1_body` is tested
        # directly, so it stays part of this function's own contract.
        "carry": carry_blocks,
    }


def _is_v1(body: str) -> bool:
    titles = {title for title, _ in markdown.split_sections(body, level=2)}
    return bool(titles & set(V1_SECTIONS)) and not ({"Background"} <= titles)


def _carry_over_tail(existing_tail: str, carry: List[str]) -> str:
    """The `## Notes` tail `_reshape` should write: `existing_tail` with the
    carried content appended under `_CARRY_HEADING`, or a fresh `## Notes`
    section holding just that if there was no tail. No carry means no
    change — `render_body` gets back exactly the tail that was already
    there (including None), which is what keeps a fully-classifiable index
    (nothing carried) producing no `## Notes` section at all.
    """
    if not carry:
        return existing_tail
    block = _CARRY_HEADING + "\n\n" + "\n\n".join(carry) + "\n"
    if existing_tail:
        prefix = existing_tail if existing_tail.endswith("\n") else existing_tail + "\n"
        return prefix + "\n" + block
    return "\n## Notes\n\n" + block


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
    carry = state.pop("carry")
    state["as_of"] = as_of
    for row in state["coming_up"]:
        row["when"] = row["when"] or "—"
    _, existing_tail = projectstate.split_notes_tail(body)
    state["notes_tail"] = _carry_over_tail(existing_tail, carry)
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
