"""Structure-version 2: the accumulated v0.2.0 → v0.6.2 vault changes.

This module is loaded standalone (spec_from_file_location) by
vaultlib.migrate.discover, not imported as a package member, so it puts
plugin/lib on sys.path itself rather than using a package-relative import.

The transformation list, quoted from the repo's `migrations/README.md`:

    Pending migration (structure-version 2 candidate): decision notes — drop
    `tags`, add `reviewed: true` to existing notes (v0.2.0 removed tags and
    made the reviewed key mandatory). Also: add
    `99-workflow-config/config.json` (template default, then fill
    timezone/executive/adapters from the vault's prose context — #54 moved
    machine decisions out of prose). Also: rewrite
    `review_status: needs-attention` → `needs-review` on existing meeting
    notes (v0.5.1 retired the status; those notes already carry the
    `conflicts-with` edge that now carries the clobber-risk signal, so
    nothing else has to be written). Until it runs, those notes are absent
    from the Triage view and a review tick on one cannot fold, so they stay
    invisible to the queue.

    Also, for #55 (inbox lifecycle): refresh `10-inbox/README.md` — its
    semantics changed, the folder is now the pending set rather than a
    staleness signal — add `90-archive/README.md`, and refresh
    `template/CLAUDE.md`'s Inbox Discipline section. **Most important:
    refresh `99-workflow-config/reference/ontology.md`.** The plugin's skills
    read the *vault's* copy for the confidence vocabulary, so a vault
    provisioned before #55 has a skill mandating `calendar-not-applicable`
    and a `note` type that its own ontology does not list — the skill and the
    vault contradict each other, and an agent resolving toward the vault
    writes a wrong confidence reason.

    Pending migration (entity dossier contract, v0.6.2 — #60). Two changes,
    and the first one is the only migration in the list so far that a vault
    silently *needs*: without it a shipped view goes from wrong-but-populated
    to empty.

    1. **Meeting notes need `entities: [<slug>]`.** The dossier's Meeting Log
       is now a Dataview query joining on that field, and no existing note
       has it, so every dossier shows an empty table until it is backfilled.
       Derive it: for each note in `20-meetings/`, map each `projects[]` slug
       to that project's `entity:` field, dedupe, write the list. A note with
       an empty `projects[]` cannot be derived and needs a human read (or is
       legitimately entity-less). The field means the entities a meeting was
       *about*, so an internal 1:1 reviewing a client account carries that
       client — derivation from `projects[]` already gets that right.
    2. **Dossier bodies need restructuring** in `40-entities/*/dossier.md`:
       add `# {entity-name}` above the first section; wrap the `## Context`
       and `## Sensitivities` bullets in their callouts (`> [!info]+
       **Standing context**`, `> [!warning]+ **Handle with care**`) — every
       bullet gains a `> ` prefix, and the write path matches on the label
       *after* stripping it, so a half-converted section still merges; and
       replace the `## Meeting Log` body with the Dataview block plus a
       `### Dynamics` list, carrying each old `### {date} — {Topic}` block's
       **Dynamics** line across as `- **{date} — {Topic}:** {dynamics}`,
       newest first. The Attendees, Key outcomes and Follow-ups lines are
       dropped — that content is in the meeting note. Dropping them is the
       one lossy step here, so snapshot before running and say so in the log.

    This one also needs the vault's own
    `99-workflow-config/reference/ontology.md` refreshed, for the reason the
    #55 entry above gives: `entities` is a new Meeting field, so a vault
    provisioned before this release has `/sync-recordings` telling an agent
    to write a field the vault's ontology does not list.

    Idempotency for both: skip a meeting note that already has `entities`,
    and a dossier whose Meeting Log already contains the Dataview block.

`apply` is an ordered list of step functions, so a step's report and the
quotation above stay put as the chain grows.

Assets are canonical copies of the template files, read from this
migration's own `assets/` directory so `apply` never needs the template at
runtime; `scripts/tests/test_migration_001.py` pins each one byte-equal to
its counterpart, so they cannot drift.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import config, markdown, vault  # noqa: E402

TARGET_VERSION = 2
# Declares what a snapshot is the only way back from. The honest scope is the
# whole old `## Meeting Log` body, not the three named fields: the section is
# *rebuilt* from its `**Dynamics:**` lines, so anything else it held — a
# preamble paragraph, a bullet nobody standardised — goes with them. The three
# named fields are what is expected to be there, not the limit of what is lost.
LOSSY = ("dossier `## Meeting Log` sections are rebuilt from their "
         "`**Dynamics:**` lines alone: everything else the old section body "
         "held is dropped. Expected there are the Attendees, Key outcomes and "
         "Follow-ups lines, whose content lives in the meeting notes — but "
         "any preamble prose or non-standard bullet in that section is "
         "dropped too, so read a dossier you have hand-edited before running")

ASSETS = Path(__file__).resolve().parent / "assets"

CONFIG_RELPATH = Path("99-workflow-config") / "config.json"
ONTOLOGY_RELPATH = Path("99-workflow-config") / "reference" / "ontology.md"
INBOX_README_RELPATH = Path("10-inbox") / "README.md"
ARCHIVE_README_RELPATH = Path("90-archive") / "README.md"
CLAUDE_RELPATH = Path("CLAUDE.md")

DECISION_GLOB = "30-projects/*/decisions/*.md"
MEETING_GLOB = "20-meetings/*.md"
PROJECT_GLOB = "30-projects/*/index.md"
DOSSIER_GLOB = "40-entities/*/dossier.md"

# The dossier body contract, frozen. These are literals rather than imports of
# vaultlib.entity's constants on purpose: a migration's output is a fixed point
# in the vault's history, and it must not change the day the writer's rendering
# changes. `scripts/tests/test_migration_001.py` pins MEETING_LOG_QUERY against
# every shipped fixture dossier, which is what keeps this honest today.
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
DATAVIEW_FENCE = "```dataview"
CONTEXT_CALLOUT = "> [!info]+ **Standing context**"
SENSITIVITIES_CALLOUT = "> [!warning]+ **Handle with care**"
DYNAMICS_TITLE = "Dynamics"
DYNAMICS_HEADING = f"### {DYNAMICS_TITLE}"
PLACEHOLDER = "*No entries yet.*"

INBOX_HEADING = "## Inbox Discipline"
CLAUDE_NEEDS_HUMAN = ("CLAUDE.md had no Inbox Discipline section — appended; "
                      "review placement")

# The frontmatter delimiters, matched the way vaultlib.markdown matches them.
# Duplicated rather than imported because it is a private name there and this
# module edits the raw block (the tags node) instead of a parsed field.
_FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"\A---[ \t]*(?:\n|\Z)")
_TAGS_NODE_RE = re.compile(r"(?m)^tags:.*\n(?:[ \t]+-.*\n)*")


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read(path: Path) -> str:
    return _normalize(path.read_text(encoding="utf-8"))


def _write_if_changed(path: Path, text: str, original: str) -> bool:
    """Write only when the bytes would differ — idempotency is a property of
    the filesystem here, not just of the report."""
    if text == original:
        return False
    vault.atomic_write(path, text)
    return True


def _frontmatter(text: str):
    """Classify a note's frontmatter: `(data, status)`.

    Three outcomes, not two, because they call for different handling:

    - `"ok"` — parsed; `data` is the mapping.
    - `"absent"` — no opening fence on line 1. Not a vault object: it cannot
      carry `tags` or a `review_status`, so there is nothing here to migrate
      and nothing to verify. A scratch file the exec dropped in a content
      folder must not block the chain.
    - `"broken"` — an opening fence is there but no frontmatter block can be
      read from it: the closing fence is missing, or the block will not
      parse. That *is* a vault object, and a broken one; it is named for a
      human and it fails `verify`.

    The opening fence, not the whole block, is what separates absent from
    broken. A truncated note — `---` and keys but no closing fence — plainly
    means to be an object and can visibly carry `tags`, so calling it absent
    would skip it in both phases and leave the consultant no signal at all.
    The cost of guessing wrong the other way is a stopped chain naming a file
    the consultant then looks at, which is recoverable; silence is not.

    Both phases classify through this one function, so `verify` cannot
    disagree with `apply` about which files are broken.
    """
    match = _FM_RE.match(text)
    if not match:
        return None, ("broken" if _OPEN_FENCE_RE.match(text) else "absent")
    try:
        return markdown.parse_frontmatter_block(match.group(1)), "ok"
    except ValueError:
        return None, "broken"


_REMOVED = object()


def _delta_is(before: dict, edited: str, changes: dict) -> bool:
    """Does `edited` parse to `before` with exactly `changes` applied?

    The guard on every edit, and it has to be semantic rather than a
    parseability check. Deleting the `tags:` key line hands its orphaned
    items to whichever key above accepts a block list — the
    ontology-canonical empty `supersedes:` does — and the result parses
    cleanly with `tags` gone. "It still parses" passes that; "every other
    key still holds exactly what it held" does not.

    A value of `_REMOVED` requires the key to be gone.
    """
    data, status = _frontmatter(edited)
    if status != "ok":
        return False
    expected = dict(before)
    for key, value in changes.items():
        if value is _REMOVED:
            expected.pop(key, None)
        else:
            expected[key] = value
    return data == expected


def _flag(needs_human: list, root: Path, path: Path, problem: str) -> str:
    relpath = path.relative_to(root).as_posix()
    needs_human.append(f"{relpath}: {problem}")
    return relpath


BROKEN_HINT = ("frontmatter will not parse — left untouched, repair it by "
               "hand and re-run")
TAGS_HINT = ("tags list shape not handled deterministically — remove tags by "
             "hand")


# --- step 1: config.json --------------------------------------------------

def _step_config(root: Path, needs_human: list) -> dict:
    """Missing → write the template default verbatim. Present → untouched:
    a deployed vault's config carries the engagement's own timezone,
    executive slug and account hints, and overwriting it would unbind the
    connectors."""
    path = root / CONFIG_RELPATH
    if path.is_file():
        return {"action": "existed", "path": CONFIG_RELPATH.as_posix()}
    vault.atomic_write(path, _asset("config.json"))
    return {"action": "written", "path": CONFIG_RELPATH.as_posix()}


# --- step 2: decision notes ----------------------------------------------

def _drop_tags_node(text: str) -> str:
    """Delete a `tags:` node — the key line plus its block-list items — from
    the raw frontmatter block, leaving every other byte alone."""
    match = _FM_RE.match(text)
    if not match:
        return text
    block = match.group(1)
    stripped = _TAGS_NODE_RE.sub("", block + "\n")
    if stripped == block + "\n":
        return text
    if stripped.endswith("\n"):
        stripped = stripped[:-1]
    return text[:match.start(1)] + stripped + text[match.end(1):]


def _step_decisions(root: Path, needs_human: list) -> dict:
    """v0.2.0 removed `tags` from decision notes and made `reviewed`
    mandatory. Pre-existing notes were all written in the foreground by a
    human, so the honest backfill is `reviewed: true` — but only where the
    key is absent: a note already carrying `false` is queued for review and
    must stay queued.

    The tags deletion edits the raw block, so it is the one edit here that
    can change more than it means to: the regex handles indented items under
    a flush-left `tags:` key, and a canonical zero-indent list, a comment or
    blank line inside the node, or an indented key all fall outside it. The
    failure is not always a parse error — orphaned items reattach to
    whichever key above accepts a block list, so `supersedes:` silently
    acquires tag values and the note still reads. Every edit is therefore
    checked semantically against the parse it started from (`_delta_is`), and
    a note whose shape the regex cannot handle is left byte-identical and
    named for a human. Broadening the regex was the alternative and it is the
    worse one — the shapes shade into "parse YAML", and a wrong guess here
    rewrites a note and reports success.
    """
    scanned = changed = tags_dropped = reviewed_added = 0
    unparseable, no_frontmatter, tags_unhandled, edit_failed = [], [], [], []
    for path in sorted(root.glob(DECISION_GLOB)):
        scanned += 1
        original = _read(path)
        data, status = _frontmatter(original)
        if status == "absent":
            no_frontmatter.append(path.relative_to(root).as_posix())
            continue
        if status == "broken":
            unparseable.append(_flag(needs_human, root, path, BROKEN_HINT))
            continue
        text = original
        current = data  # the parsed state `text` currently corresponds to
        if "tags" in current:
            edited = _drop_tags_node(text)
            # A no-op edit means the regex never matched the node the parser
            # can see (an indented key), so the note keeps its tags either
            # way: both cases are refusals, not successes.
            if edited == text or not _delta_is(current, edited,
                                               {"tags": _REMOVED}):
                tags_unhandled.append(_flag(needs_human, root, path,
                                            TAGS_HINT))
                continue
            text = edited
            current = {k: v for k, v in current.items() if k != "tags"}
            tags_dropped += 1
        if "reviewed" not in current:
            try:
                edited = markdown.upsert_scalar_field(text, "reviewed", "true")
            except ValueError as exc:
                # Defensive: the insert path cannot raise on a block that
                # just parsed. If it ever does, one odd note must not abort
                # the run and leave the vault half-migrated.
                edit_failed.append(_flag(needs_human, root, path, str(exc)))
                continue
            if not _delta_is(current, edited, {"reviewed": True}):
                edit_failed.append(_flag(
                    needs_human, root, path,
                    "adding reviewed would change other frontmatter — add "
                    "`reviewed: true` by hand"))
                continue
            text = edited
            reviewed_added += 1
        if _write_if_changed(path, text, original):
            changed += 1
    return {"scanned": scanned, "changed": changed,
            "tags_dropped": tags_dropped, "reviewed_added": reviewed_added,
            "unparseable": unparseable, "no_frontmatter": no_frontmatter,
            "tags_unhandled": tags_unhandled, "edit_failed": edit_failed}


# --- step 3: review_status ------------------------------------------------

def _step_review_status(root: Path, needs_human: list) -> dict:
    """v0.5.1 retired `needs-attention`. The clobber-risk signal it carried
    now rides the note's `conflicts-with` edge, which those notes already
    have, so the status is all that changes — and until it does, the note is
    absent from the Triage view entirely.

    `replace_scalar_field` matches the field at the start of a line while the
    parser strips each line first, so an indented `review_status:` is visible
    to one and not the other and the replace raises. Caught per note: an
    escaping ValueError would abort `apply` partway through, leaving the
    vault half-migrated with no report of how far it got.
    """
    scanned = changed = 0
    unparseable, no_frontmatter, edit_failed = [], [], []
    for path in sorted(root.glob(MEETING_GLOB)):
        scanned += 1
        original = _read(path)
        data, status = _frontmatter(original)
        if status == "absent":
            no_frontmatter.append(path.relative_to(root).as_posix())
            continue
        if status == "broken":
            unparseable.append(_flag(needs_human, root, path, BROKEN_HINT))
            continue
        if data.get("review_status") != "needs-attention":
            continue
        try:
            text = markdown.replace_scalar_field(
                original, "review_status", "needs-review")
        except ValueError as exc:
            edit_failed.append(_flag(
                needs_human, root, path,
                f"review_status could not be rewritten ({exc}) — set it to "
                "needs-review by hand"))
            continue
        if not _delta_is(data, text, {"review_status": "needs-review"}):
            edit_failed.append(_flag(
                needs_human, root, path,
                "rewriting review_status would change other frontmatter — "
                "set it to needs-review by hand"))
            continue
        if _write_if_changed(path, text, original):
            changed += 1
    return {"scanned": scanned, "changed": changed,
            "unparseable": unparseable, "no_frontmatter": no_frontmatter,
            "edit_failed": edit_failed}


# --- step 4: folder READMEs ----------------------------------------------

def _step_readmes(root: Path, needs_human: list) -> dict:
    """`10-inbox/README.md` describes semantics that changed — the folder is
    the pending set now, not a staleness signal — and `90-archive/README.md`
    did not exist before the sync started moving files there. Both are
    plugin-authored prose with nothing of the exec's in them, so an
    unconditional overwrite is both correct and the idempotent form."""
    written = []
    for relpath, asset in ((INBOX_README_RELPATH, "10-inbox-README.md"),
                           (ARCHIVE_README_RELPATH, "90-archive-README.md")):
        path = root / relpath
        text = _asset(asset)
        original = _read(path) if path.is_file() else None
        if original is None or original != text:
            vault.atomic_write(path, text)
        written.append(relpath.as_posix())
    return {"written": written}


# --- step 5: CLAUDE.md's Inbox Discipline section -------------------------

def _step_claude_md(root: Path, needs_human: list) -> dict:
    """Replace the section in place, between its own heading and the next
    `## ` — the rest of the file may hold the exec's own edits. No section
    means the file's shape is not the one this rule was written against, so
    it is appended rather than guessed at, and a human is asked to place it."""
    path = root / CLAUDE_RELPATH
    asset = _asset("claude-inbox-discipline.md")
    existed = path.is_file()
    original = _read(path) if existed else ""
    start = original.find(INBOX_HEADING)
    # Only a heading at the start of a line is the section heading.
    while start > 0 and original[start - 1] != "\n":
        start = original.find(INBOX_HEADING, start + 1)
    if start < 0:
        prefix = original
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
        text = prefix + asset
        action = "created" if not existed else "appended"
        needs_human.append(CLAUDE_NEEDS_HUMAN)
    else:
        end = original.find("\n## ", start + 1)
        tail = original[end:] if end >= 0 else ""
        text = original[:start] + asset + tail
        action = "replaced"
    _write_if_changed(path, text, original if existed else None)
    return {"action": action, "path": CLAUDE_RELPATH.as_posix()}


# --- step 6: the vault's ontology ----------------------------------------

def _step_ontology(root: Path, needs_human: list) -> dict:
    """The skills read the *vault's* ontology for the confidence vocabulary
    and the object types, so a stale copy makes the plugin and the vault
    contradict each other. It is generated reference, never hand-edited, so
    the unconditional overwrite is the idempotent form."""
    path = root / ONTOLOGY_RELPATH
    text = _asset("ontology.md")
    original = _read(path) if path.is_file() else None
    if original is None or original != text:
        vault.atomic_write(path, text)
    return {"action": "written", "path": ONTOLOGY_RELPATH.as_posix()}


# --- step 7: the entities backfill ---------------------------------------

def _node_end(lines: list, key_index: int) -> int:
    """Index one past the last line of the frontmatter node at `key_index`.

    A mirror of markdown._node_end, duplicated for the same reason _FM_RE is:
    it is private there, and this module walks the raw block rather than a
    parsed field. Block-list items keep accumulating under a key across blank
    and comment lines; trailing blanks with no item after them are layout, not
    node, so a new line inserted at this index lands under the key's own items
    and above whatever blank line separates it from the next key.
    """
    end = scan = key_index + 1
    while scan < len(lines):
        stripped = lines[scan].strip()
        if stripped.startswith("- ") or stripped == "-":
            scan += 1
            end = scan
        elif not stripped or stripped.startswith("#"):
            scan += 1
        else:
            break
    return end


def _insert_after_node(text: str, anchor: str, new_line: str):
    """Insert `new_line` into the frontmatter block right after the `anchor:`
    node. Returns None when the anchor's key line is not visible at the start
    of a line — an indented key parses (the parser strips each line) but
    cannot be located here, and guessing a position is how a note gets
    mis-edited."""
    match = _FM_RE.match(text)
    if not match:
        return None
    lines = match.group(1).split("\n")
    for index, line in enumerate(lines):
        if not line.startswith(f"{anchor}:"):
            continue
        end = _node_end(lines, index)
        block = "\n".join(lines[:end] + [new_line] + lines[end:])
        return text[:match.start(1)] + block + text[match.end(1):]
    return None


def _project_entities(root: Path, needs_human: list) -> tuple:
    """`(project_slug -> entity_slug, every project slug seen, unparseable)`.

    The folder name is the slug the meeting notes actually reference, so it is
    the key; a stale `slug:` field inside the index cannot break the join.
    An index whose frontmatter will not parse is named for a human, because
    every meeting that references it silently loses its entity otherwise.

    The second return value is every project that *has* an index, mapped or
    not. It is what separates "this index needs an `entity:` field" from
    "there is no such project" — two different repairs, and the second is
    usually a typo in the meeting's own `projects[]`.
    """
    mapping, known, unparseable = {}, set(), []
    for path in sorted(root.glob(PROJECT_GLOB)):
        known.add(path.parent.name)
        data, status = _frontmatter(_read(path))
        if status == "broken":
            unparseable.append(_flag(
                needs_human, root, path,
                "project index frontmatter will not parse, so no meeting can "
                "derive an entity from it — repair it by hand and re-run"))
            continue
        if status != "ok":
            continue
        entity = data.get("entity")
        if isinstance(entity, str) and entity.strip():
            mapping[path.parent.name] = entity.strip()
    return mapping, known, unparseable


EMPTY_PROJECTS_HINT = ("empty projects[] — entities cannot be derived; needs "
                       "a human read (or is legitimately entity-less)")


def _unmapped_hint(unresolved: list, known: set, derived: list) -> str:
    """The repair for a note whose `projects[]` does not fully map.

    Two different repairs, so two different sentences: a slug with no index is
    a missing project folder or a typo in this note; a slug with an index is
    one `entity:` field away. Both can appear at once.
    """
    absent = [slug for slug in unresolved if slug not in known]
    fieldless = [slug for slug in unresolved if slug in known]
    reasons = []
    if absent:
        reasons.append(
            "no project index at "
            + ", ".join(f"30-projects/{slug}/index.md" for slug in absent)
            + " — the project folder or its index is missing, or projects[] "
              "carries a typo")
    if fieldless:
        reasons.append(
            "no `entity:` field in "
            + ", ".join(f"30-projects/{slug}/index.md" for slug in fieldless)
            + " — add it and re-run")
    hint = "; ".join(reasons)
    if derived:
        # Say why the derivable half was not written anyway: a partial list
        # passes verify and leaves the missing entity's Meeting Log short a
        # meeting, with nothing on the page to say so.
        hint += (f" (the rest of projects[] does map, to {derived}, but a "
                 "partial entities list would pass verify and leave the "
                 "unmapped project's dossier short this meeting — nothing "
                 "was written, so a re-run after the fix derives the "
                 "complete list)")
    return hint


def _step_entities_backfill(root: Path, needs_human: list) -> dict:
    """v0.6.2 made the dossier Meeting Log a Dataview query joining on a
    meeting's `entities[]`. No note written before it has the field, so every
    dossier renders an empty table until this runs — the one change in this
    chain a vault silently needs rather than merely benefits from.

    `entities` is derived, never guessed: each `projects[]` slug maps through
    the project indexes to that project's `entity:`. A meeting any part of
    which cannot be derived is left byte-identical and named for a human, with
    the hint saying which repair it needs — an empty `projects[]` is a note
    nobody can classify from metadata; a project index missing its `entity:`
    is one field away from mapping; a slug with no index at all is usually a
    typo in the meeting's own `projects[]`.

    **All-or-nothing per note, deliberately.** When one slug of two maps, the
    partial list is not written. A partial write is the worst outcome
    available: the note looks migrated, `verify` passes it, and the unmapped
    project's entity is short one meeting in a Dataview table that offers no
    hint anything is missing. Refusing leaves the note keyless, so once the
    consultant adds the missing `entity:` a re-run derives the *complete*
    list — a note already carrying a partial one would be skipped forever.
    `entities: []` is never written for the same reason: it would look
    migrated and join on nothing.
    """
    mapping, known, bad_projects = _project_entities(root, needs_human)
    scanned = backfilled = skipped_existing = 0
    unparseable, no_frontmatter = [], []
    empty_projects, unmapped, edit_failed = [], [], []
    for path in sorted(root.glob(MEETING_GLOB)):
        scanned += 1
        original = _read(path)
        data, status = _frontmatter(original)
        if status == "absent":
            no_frontmatter.append(path.relative_to(root).as_posix())
            continue
        if status == "broken":
            unparseable.append(_flag(needs_human, root, path, BROKEN_HINT))
            continue
        if "entities" in data:
            skipped_existing += 1
            continue
        projects = data.get("projects")
        if isinstance(projects, str):
            projects = [projects]
        if not projects:
            empty_projects.append(_flag(needs_human, root, path,
                                        EMPTY_PROJECTS_HINT))
            continue
        derived, unresolved = [], []
        for raw in projects:
            slug = str(raw).strip()
            entity = mapping.get(slug)
            if not entity:
                if slug not in unresolved:
                    unresolved.append(slug)
            elif entity not in derived:
                derived.append(entity)
        if unresolved:
            unmapped.append(_flag(needs_human, root, path,
                                  _unmapped_hint(unresolved, known, derived)))
            continue
        line = "entities: [" + ", ".join(derived) + "]"
        edited = _insert_after_node(original, "projects", line)
        if edited is None or not _delta_is(data, edited, {"entities": derived}):
            edit_failed.append(_flag(
                needs_human, root, path,
                f"inserting `{line}` would change other frontmatter (or the "
                "projects key is indented and cannot be located) — add the "
                "line by hand after projects"))
            continue
        if _write_if_changed(path, edited, original):
            backfilled += 1
    return {"scanned": scanned, "backfilled": backfilled,
            "skipped_existing": skipped_existing,
            "projects_mapped": len(mapping),
            "unparseable": unparseable, "no_frontmatter": no_frontmatter,
            "empty_projects": empty_projects, "unmapped": unmapped,
            "unparseable_projects": bad_projects, "edit_failed": edit_failed}


# --- step 8: dossier bodies ----------------------------------------------

_QUOTE_PREFIX_RE = re.compile(r"\A[ \t]*>[ \t]?")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# The old bullet: `- **Dynamics:** {text}`. The optional trailing colon covers
# a hand-typed `**Dynamics**:`, which reads identically and would otherwise
# drop the one line this section keeps.
_DYNAMICS_RE = re.compile(r"\A(?:-[ \t]+)?\*\*Dynamics:?\*\*:?[ \t]*(.*)\Z")


def _unquote(line: str) -> str:
    """One level of callout prefix removed. Only one: the matchers below key on
    text a half-converted section already carries a single `> ` in front of,
    and stripping every level would also eat the indentation of a nested
    bullet."""
    return _QUOTE_PREFIX_RE.sub("", line, count=1)


def _body_start(text: str) -> int:
    match = _FM_RE.match(text)
    return match.end() if match else 0


def _title_line(body: str) -> str:
    for line in body.split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _ensure_title(preamble: str, name: str) -> str:
    """`# {entity-name}` as the first body line. Every dossier file is called
    dossier.md, so without it the only title Obsidian shows for the note is
    the word "dossier"."""
    if _title_line(preamble).startswith("# "):
        return preamble
    kept = preamble.strip("\n")
    head = f"\n# {name}\n"
    return head + "\n" + kept + "\n" if kept else head


def _to_callout(content: str, callout: str) -> str:
    """Wrap a section's lines in its callout.

    Matching happens after stripping any existing `> `, so a section a hand
    edit already quoted converts once and does not end up doubly prefixed with
    two callout lines. A blank line inside the box is rendered as a bare `>`:
    an unprefixed blank ends the callout in Obsidian, and everything below it
    would render as loose text outside the box.

    A line that is nothing but an HTML comment is hoisted above the callout
    instead of quoted. `<!-- unvalidated -->` is a comment *about* the section
    and vaultlib.entity keeps it outside deliberately — inside it renders as a
    line of the box. An inline marker at the end of a bullet stays with its
    bullet, which is where entity.py puts those too.
    """
    label = _unquote(callout).strip()
    markers, inner = [], []
    for line in content.split("\n"):
        bare = _unquote(line)
        stripped = bare.strip()
        if stripped == label:
            continue  # the callout line itself — re-emitted below, once
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            markers.append(stripped)
            continue
        inner.append(bare)
    while inner and not inner[0].strip():
        inner.pop(0)
    while inner and not inner[-1].strip():
        inner.pop()
    if not inner:
        inner = [PLACEHOLDER]
    quoted = [f"> {line}" if line.strip() else ">" for line in inner]
    lead = "\n".join(markers) + "\n\n" if markers else "\n"
    return lead + callout + "\n" + "\n".join(quoted) + "\n"


def _dynamics_bullets(content: str) -> list:
    """One `- **{date} — {Topic}:** {dynamics}` per old dated block, newest
    first. Attendees, key outcomes and follow-ups are dropped (see LOSSY):
    they are in the meeting note, and a copy here goes stale the moment the
    note is corrected. What the meeting note cannot hold is the read of the
    room, so that is all this carries across.
    """
    entries = []
    for title, block in markdown.split_sections(content, 3):
        heading = title.strip()
        if not heading:
            continue
        if heading == DYNAMICS_TITLE:
            # A partly-converted section already has bullets in the new shape.
            # They are content, and the rule is that nothing is removed.
            for line in block.split("\n"):
                bare = _unquote(line).strip()
                if bare.startswith("- ") and bare != PLACEHOLDER:
                    entries.append((_date_key(bare), bare))
            continue
        for line in block.split("\n"):
            match = _DYNAMICS_RE.match(_unquote(line).strip())
            if match and match.group(1).strip():
                entries.append((_date_key(heading),
                                f"- **{heading}:** {match.group(1).strip()}"))
                break
    # A stable sort keeps two blocks sharing a date in the order the file had.
    entries.sort(key=lambda entry: entry[0], reverse=True)
    return [bullet for _, bullet in entries]


def _date_key(text: str) -> str:
    match = _DATE_RE.search(text)
    return match.group(1) if match else ""


def _meeting_log_section(content: str) -> str:
    bullets = _dynamics_bullets(content) or [PLACEHOLDER]
    return ("\n" + MEETING_LOG_QUERY + "\n\n" + DYNAMICS_HEADING + "\n\n"
            + "\n".join(bullets) + "\n")


def _restructure_body(body: str, name: str) -> str:
    rebuilt = []
    for title, content in markdown.split_sections(body, 2):
        if not title:
            rebuilt.append((title, _ensure_title(content, name)))
        elif title == "Context":
            rebuilt.append((title, _to_callout(content, CONTEXT_CALLOUT)))
        elif title == "Sensitivities":
            rebuilt.append((title,
                            _to_callout(content, SENSITIVITIES_CALLOUT)))
        elif title == "Meeting Log":
            rebuilt.append((title, _meeting_log_section(content)))
        else:
            rebuilt.append((title, content))
    return markdown.render_sections(rebuilt, 2)


def _step_dossiers(root: Path, needs_human: list) -> dict:
    """Restructure `40-entities/*/dossier.md` bodies to the v0.6.2 contract.

    Body-only, and that is checked rather than intended: the parsed
    frontmatter before and after must be identical, because a dossier's
    frontmatter carries the `slug` the new Dataview query joins on and this
    step has no business near it.

    The Dataview fence is the idempotency test. It is a better one than a
    version stamp would be: it is the thing the migration exists to add, so a
    dossier that has it is done by definition, and a dossier a consultant
    half-repaired by hand still converts.
    """
    scanned = restructured = skipped_existing = 0
    unparseable, no_frontmatter, edit_failed, unnamed = [], [], [], []
    for path in sorted(root.glob(DOSSIER_GLOB)):
        scanned += 1
        original = _read(path)
        data, status = _frontmatter(original)
        if status == "absent":
            no_frontmatter.append(path.relative_to(root).as_posix())
            continue
        if status == "broken":
            unparseable.append(_flag(needs_human, root, path, BROKEN_HINT))
            continue
        split = _body_start(original)
        body = original[split:]
        if DATAVIEW_FENCE in body:
            skipped_existing += 1
            continue
        name = data.get("entity-name")
        if not isinstance(name, str) or not name.strip():
            name = path.parent.name
            unnamed.append(_flag(
                needs_human, root, path,
                f"no entity-name in frontmatter — titled the dossier "
                f"{name!r} from its folder; set entity-name and fix the "
                "heading by hand"))
        edited = original[:split] + _restructure_body(body, str(name).strip())
        after, after_status = _frontmatter(edited)
        if after_status != "ok" or after != data:
            edit_failed.append(_flag(
                needs_human, root, path,
                "restructuring the body would have changed the frontmatter — "
                "left untouched; restructure this dossier by hand"))
            continue
        if _write_if_changed(path, edited, original):
            restructured += 1
    return {"scanned": scanned, "restructured": restructured,
            "skipped_existing": skipped_existing,
            "unparseable": unparseable, "no_frontmatter": no_frontmatter,
            "unnamed": unnamed, "edit_failed": edit_failed}


_STEPS = (
    ("config", _step_config),
    ("decisions", _step_decisions),
    ("review_status", _step_review_status),
    ("readmes", _step_readmes),
    ("claude_md", _step_claude_md),
    ("ontology", _step_ontology),
    ("entities", _step_entities_backfill),
    ("dossiers", _step_dossiers),
)


def apply(root: Path) -> dict:
    needs_human: list = []
    steps = {}
    for name, step in _STEPS:
        steps[name] = step(root, needs_human)
    return {"steps": steps, "needs_human": needs_human}


def _scan(root: Path, pattern: str, offends) -> tuple:
    """(offending paths, unparseable paths) over one glob.

    Unparseable notes are counted, never skipped: they are exactly the files
    a botched edit produces, so silently passing over them would let `verify`
    bless the damage it exists to catch.
    """
    offending, unparseable = [], []
    for path in sorted(root.glob(pattern)):
        data, status = _frontmatter(_read(path))
        if status == "absent":
            continue  # not a vault object — nothing to assert about it
        if status == "broken":
            unparseable.append(path.relative_to(root).as_posix())
        elif offends(data):
            offending.append(path.relative_to(root).as_posix())
    return offending, unparseable


def verify(root: Path) -> dict:
    """Raises on any violation; the framework treats that as a failed
    migration and leaves structure-version where it was.

    Strict on purpose, including about notes `apply` refused to touch. A
    refusal means the migration did not fully land, and this is a
    consultant-attended run: stopping the chain with the file named beats
    bumping structure-version over a note the new code will misread. The
    consultant fixes what `needs_human` listed and re-runs.
    """
    config.read(root)  # raises ConfigError if absent or malformed

    with_tags, bad_decisions = _scan(
        root, DECISION_GLOB, lambda data: "tags" in data)
    needing_attention, bad_meetings = _scan(
        root, MEETING_GLOB,
        lambda data: data.get("review_status") == "needs-attention")
    missing_entities, _ = _scan(
        root, MEETING_GLOB,
        lambda data: bool(data.get("projects")) and "entities" not in data)
    _, bad_projects = _scan(root, PROJECT_GLOB, lambda data: False)
    _, bad_dossiers = _scan(root, DOSSIER_GLOB, lambda data: False)

    unparseable = bad_decisions + bad_meetings + bad_projects + bad_dossiers
    if unparseable:
        raise ValueError(
            "frontmatter will not parse in: " + ", ".join(unparseable)
            + " — repair these notes by hand and re-run")
    # These messages repeat apply's needs_human hints. MigrateError carries
    # the apply report's list too, but the log line and the error text are
    # what a consultant reads first, so they say what to do rather than only
    # what is wrong.
    if with_tags:
        raise ValueError(
            "decision notes still carry tags: " + ", ".join(with_tags)
            + " — remove the tags node by hand and re-run")
    if needing_attention:
        raise ValueError(
            "meeting notes still carry review_status: needs-attention: "
            + ", ".join(needing_attention)
            + " — set them to needs-review by hand and re-run")
    if missing_entities:
        raise ValueError(
            "meeting notes name projects but carry no entities, so every "
            "dossier Meeting Log they belong in renders empty: "
            + ", ".join(missing_entities)
            + " — give each project index an `entity:` field and re-run, or "
            "set entities by hand")

    # Every offender at once, like the checks above. Raising on the first one
    # turns a ten-dossier vault into ten snapshot-migrate-fail cycles, each
    # revealing exactly one more file — and apply's needs_human is empty for a
    # dossier missing its `## Meeting Log` entirely, so this message is the
    # consultant's only list.
    dossiers = sorted(root.glob(DOSSIER_GLOB))
    dossier_problems = []
    for path in dossiers:
        text = _read(path)
        body = text[_body_start(text):]
        relpath = path.relative_to(root).as_posix()
        if DATAVIEW_FENCE not in body:
            dossier_problems.append(
                f"{relpath} (no Dataview Meeting Log — the `## Meeting Log` "
                "section is missing, or still holds the old hand-written "
                "entries)")
        elif not _title_line(body).startswith("# "):
            dossier_problems.append(
                f"{relpath} (does not open with a `# ` heading, so Obsidian "
                'shows the note as "dossier" — add `# <entity name>` above '
                "the first section)")
    if dossier_problems:
        raise ValueError(
            "dossier bodies are not on the v0.6.2 contract: "
            + ", ".join(dossier_problems)
            + " — restructure them by hand and re-run")

    for relpath in (INBOX_README_RELPATH, ARCHIVE_README_RELPATH):
        if not (root / relpath).is_file():
            raise ValueError(f"{relpath.as_posix()} is missing")

    ontology = root / ONTOLOGY_RELPATH
    if not ontology.is_file() or _read(ontology) != _asset("ontology.md"):
        raise ValueError(f"{ONTOLOGY_RELPATH.as_posix()} does not match the shipped "
                         "ontology")

    claude = root / CLAUDE_RELPATH
    marker = _first_prose_line(_asset("claude-inbox-discipline.md"))
    if not claude.is_file() or marker not in _read(claude):
        raise ValueError("CLAUDE.md is missing the refreshed Inbox "
                         "Discipline section")

    return {
        "decision_notes_with_tags": 0,
        "meetings_needing_attention": 0,
        "meetings_missing_entities": 0,
        "unparseable": 0,
        "dossiers": len(dossiers),
        "readmes": [INBOX_README_RELPATH.as_posix(), ARCHIVE_README_RELPATH.as_posix()],
        "ontology": ONTOLOGY_RELPATH.as_posix(),
    }


def _first_prose_line(asset: str) -> str:
    """The asset's first non-heading, non-blank line — enough to tell the
    refreshed section from the one it replaced without pinning the whole
    body, which the exec may reasonably have edited around."""
    for line in asset.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    raise ValueError("claude-inbox-discipline.md has no prose line")
