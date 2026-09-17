"""Inbox scan, dedup, the skip list, and the sweep: the deterministic ledger
under /sync-recordings.

The vault itself is the ledger — a recording is synced iff its namespaced
source-recording-id appears in some 20-meetings/*.md, compared in canonical
form (canonical_id: one recording, one key, whichever spelling the connector
used). There is no second ledger to reconcile, so a failed item (which wrote nothing) retries
naturally on the next run. The skip list exists for the one case the ledger
cannot express: a human said "never propose this one again". It carries the
reason alongside the id, because a permanent suppression no one can explain
is indistinguishable from a mistake.

scan-cache.json is a cache, not a ledger: it remembers what the vault
already said, keyed on (mtime_ns, size), and is rebuilt in silence whenever
it is missing or does not match. Deleting it is always safe and changes no
answer — see scancache.py.
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

from . import markdown, project, scancache, vault

INBOX_DIR = vault.INBOX_DIR
MEETINGS_DIR = vault.MEETINGS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
ENTITIES_DIR = vault.ENTITIES_DIR
PEOPLE_DIR = vault.PEOPLE_DIR
NAMESPACES = ("inbox", "plaud", "m365")
SKIP_FILE_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"
ARCHIVE_DIR = vault.ARCHIVE_DIR
ARCHIVE_INBOX_SUBDIR = "inbox"
PARKED_SIDECAR_SUFFIX = ".parked.md"
MAX_REASON_CHARS = 300
_IGNORED_NAMES = {"README.md"}


class SyncError(Exception):
    """A sync argument or id the caller must fix."""


def content_id(path: Path) -> str:
    """inbox:{16 hex} — content-addressed, so a renamed drop stays deduped.

    Chunked read: the inbox legitimately holds large recorder exports. scan()
    reaches this through _cached_content_id and only calls it when a file's
    (mtime_ns, size) has changed, so a large export sitting pending across
    several runs is hashed once."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"inbox:{digest.hexdigest()[:16]}"


def _cached_content_id(root: Path, path: Path, cache: dict) -> str:
    """content_id, but only for files whose (mtime_ns, size) changed.

    The inbox legitimately holds large recorder exports, and a file can sit
    pending across several runs before it is classified.
    """
    rel = path.relative_to(root).as_posix()
    key = scancache.stat_key(path)
    entry = scancache.lookup(cache, "inbox", rel, key)
    if entry is not None and entry.get("content_id"):
        return str(entry["content_id"])
    recording_id = content_id(path)
    scancache.store(cache, "inbox", rel, key, {"content_id": recording_id})
    return recording_id


def canonical_id(recording_id) -> str:
    """One recording, one ledger key, whichever spelling the connector used.

    Plaud listed a recording as its bare 32-hex storage hash until
    2026-09-15 and as `of_<hex>` from then on — the hash under Plaud's
    object-type prefix (its own storage paths hold the audio at
    `of_<hex>/oc_at_<hex>.mp3`). Both spellings name one recording, and a
    ledger that compared the literal strings wrote one recording twice, once
    per spelling. The hash is the identity, so the prefix is stripped: every
    deployed vault already holds the bare form on months of notes, and
    stripping a tag is safe where inventing one would not be.

    Every comparison and every write goes through here. `of_` means nothing
    in the other namespaces and is left exactly as given there.
    """
    text = str(recording_id or "").strip()
    namespace, sep, rest = text.partition(":")
    if sep and namespace == "plaud" and rest.startswith(_PLAUD_OBJECT_PREFIX):
        return f"{namespace}:{rest[len(_PLAUD_OBJECT_PREFIX):]}"
    return text


_PLAUD_OBJECT_PREFIX = "of_"


def _validate_id(recording_id: str) -> str:
    """The canonical form of a well-namespaced id, or SyncError."""
    text = canonical_id(recording_id)
    prefix = text.split(":", 1)[0] if ":" in text else ""
    if prefix not in NAMESPACES or not text.split(":", 1)[1]:
        raise SyncError(
            f"recording id {recording_id!r} must carry a namespace prefix, "
            f"one of {[n + ':' for n in NAMESPACES]}"
        )
    return text


def known_recording_ids(root: Path, cache: Optional[dict] = None
                        ) -> Tuple[Dict[str, str], List[str]]:
    """{source-recording-id: meeting relpath} across 20-meetings/, plus
    warnings for unparseable notes (reported, never fatal — one mangled file
    must not stop the sync).

    Only notes whose (mtime_ns, size) changed since the last run are read;
    the rest come from the scan cache, warnings included — a mangled note
    must not be re-read every run, and its warning must not disappear just
    because the read was skipped. Pass `cache` to share one load/save across
    several calls in the same run.
    """
    owns_cache = cache is None
    cache = scancache.load(root) if owns_cache else cache
    ids: Dict[str, str] = {}
    warnings: List[str] = []
    live: Set[str] = set()
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        live.add(rel)
        key = scancache.stat_key(path)
        entry = scancache.lookup(cache, "ledger", rel, key)
        if entry is None:
            try:
                data, _ = markdown.split_frontmatter(
                    path.read_text(encoding="utf-8"))
                rid = data.get("source-recording-id")
                entry = {"recording_id": str(rid) if rid else None,
                         "warning": None}
                scancache.store(cache, "ledger", rel, key, entry)
            except ValueError as exc:
                # Deterministic, and self-healing: unparseable bytes cannot
                # become parseable without changing (mtime_ns, size), which
                # misses the cache and forces a re-read. Safe to remember, so
                # a mangled note is not re-parsed on every run.
                entry = {"recording_id": None, "warning": f"{rel}: {exc}"}
                scancache.store(cache, "ledger", rel, key, entry)
            except OSError as exc:
                # Transient, and NOT self-healing: a sync-client lock, EIO,
                # ESTALE, EMFILE. Restoring readability changes neither mtime
                # nor size, so a cached "no id" here would answer for this
                # note forever — its source-recording-id would vanish from the
                # ledger and its recording would sync a second time. Warn for
                # this run only; the next run reads the file again.
                entry = {"recording_id": None, "warning": f"{rel}: {exc}"}
        if entry.get("warning"):
            warnings.append(entry["warning"])
        if entry.get("recording_id"):
            # The cache holds the id as the note spells it; the key is the
            # canonical form, so a note written under either Plaud spelling
            # answers for the recording without a cache rebuild.
            ids[canonical_id(entry["recording_id"])] = rel
    scancache.prune(cache, "ledger", live)
    if owns_cache:
        scancache.save(root, cache)
    return ids, warnings


def _flatten(text: Optional[str]) -> Optional[str]:
    """Collapse all whitespace to single spaces, or None if nothing is left.

    One record is one line: a tab would invent a field and a newline would
    invent a record. A model writes these reasons, so neither can be assumed
    absent.
    """
    collapsed = " ".join(str(text or "").split())
    return collapsed or None


def _clean_reason(reason: Optional[str]) -> Optional[str]:
    """A reason short enough to stay readable in a list of them."""
    text = _flatten(reason)
    if text is not None and len(text) > MAX_REASON_CHARS:
        text = text[:MAX_REASON_CHARS - 1].rstrip() + "…"
    return text


def _format_skip_line(record: dict) -> str:
    r"""`id[\treason[\tfilename]]`, one line, LF-terminated.

    Trailing empty fields are omitted rather than written as bare tabs, so an
    id with nothing to say produces exactly the line this format started as —
    what every deployed vault already holds.
    """
    fields = [record["recording_id"],
              _clean_reason(record.get("reason")) or "",
              _flatten(record.get("source_name")) or ""]
    while len(fields) > 1 and not fields[-1]:
        fields.pop()
    return "\t".join(fields) + "\n"


def _parse_skip_line(line: str) -> dict:
    fields = [field.strip() for field in line.split("\t")]
    fields += [""] * (3 - len(fields))
    # Canonical on read: a line written in the other Plaud spelling still
    # suppresses, and skip() finds it rather than appending a twin.
    return {"recording_id": canonical_id(fields[0]),
            "reason": fields[1] or None, "source_name": fields[2] or None}


def read_skip_records(root: Path) -> List[dict]:
    """Every suppressed id in file order, with what it was and why.

    A bare id line — all this format held before reasons were recorded, and
    what deployed vaults still hold — parses as a complete record whose
    reason is None. That is the honest rendering: no reason was ever captured,
    and none is invented here.
    """
    skip_file = root / SKIP_FILE_RELPATH
    if not skip_file.is_file():
        return []
    return [_parse_skip_line(line) for line
            in skip_file.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def read_skip_list(root: Path) -> Set[str]:
    """Just the suppressed ids — what scan() and dedup() filter against.

    Deliberately unchanged by the annotated format: every caller that asks
    "is this id suppressed?" gets the same answer from either line shape.
    """
    return {record["recording_id"] for record in read_skip_records(root)}


def skip(root: Path, recording_id: str, reason: Optional[str] = None,
         source_name: Optional[str] = None) -> dict:
    """Record one id as never-propose-again (idempotent on the id).

    `reason` and `source_name` are what make this list legible a quarter
    later; both are optional because an adapter id skipped by hand has no
    inbox file and may have nothing to say. Inbox files come through park(),
    which requires a reason.
    """
    rid = _validate_id(recording_id)
    cleaned = _clean_reason(reason)
    records = read_skip_records(root)
    present = next((r for r in records if r["recording_id"] == rid), None)
    if present is not None:
        # An id suppressed before reasons were recorded, whose file was
        # dropped back in and parked again: annotate the line already there
        # rather than duplicate the id. A reason already on record is the one
        # a human would have read, so a re-park never revises it.
        if cleaned and not present["reason"]:
            present["reason"] = cleaned
            present["source_name"] = _flatten(source_name) \
                or present["source_name"]
            vault.atomic_write(root / SKIP_FILE_RELPATH,
                               "".join(_format_skip_line(r) for r in records))
            return {"recording_id": rid, "already_present": True,
                    "reason_added": True, "reason": cleaned}
        return {"recording_id": rid, "already_present": True,
                "reason_added": False, "reason": present["reason"]}
    skip_file = root / SKIP_FILE_RELPATH
    skip_file.parent.mkdir(parents=True, exist_ok=True)
    with open(skip_file, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(_format_skip_line(
            {"recording_id": rid, "reason": cleaned,
             "source_name": source_name}))
    return {"recording_id": rid, "already_present": False,
            "reason_added": bool(cleaned), "reason": cleaned}


def unskip(root: Path, recording_id: str) -> dict:
    """Remove one id from the never-propose-again list — the undo half of
    `sync settle-duplicate` (and of a bare `sync skip`).

    Refuses an id that is not on the list, rather than silently doing
    nothing: a caller unskipping an id it does not actually suppress is far
    more likely a typo'd id than a deliberate no-op, and a silent success
    here would look identical to the one that actually removed something.
    """
    rid = _validate_id(recording_id)
    records = read_skip_records(root)
    remaining = [r for r in records if r["recording_id"] != rid]
    if len(remaining) == len(records):
        raise SyncError(
            f"recording id {rid!r} is not on the skip list — nothing to "
            "remove; check the id, or read the list to find the one "
            "actually suppressing it"
        )
    vault.atomic_write(root / SKIP_FILE_RELPATH,
                       "".join(_format_skip_line(r) for r in remaining))
    return {"recording_id": rid, "removed": True}


def scan(root: Path) -> dict:
    """Partition inbox files into candidates / already synced / skipped.

    Which candidates are captures, and which of those are meetings, is
    judgment and stays with the model; this returns every regular file with
    enough metadata to decide.
    """
    cache = scancache.load(root)
    known, warnings = known_recording_ids(root, cache)
    skipped_ids = read_skip_list(root)
    candidates, synced, skipped = [], [], []
    live: Set[str] = set()
    inbox = root / INBOX_DIR
    for path in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if path.is_symlink():
            # archive() refuses to move a symlink — moving one relocates the
            # link, not the file. Offering it as a candidate would mean
            # processing a file that can then never leave the inbox.
            warnings.append(
                f"{path.relative_to(root).as_posix()} is a symlink and is not "
                "a sync candidate — replace it with the real file"
            )
            continue
        if not path.is_file() or path.name in _IGNORED_NAMES \
                or path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        live.add(rel)
        rid = _cached_content_id(root, path, cache)
        entry = {
            "name": path.name,
            "path": rel,
            "size": path.stat().st_size,
            "recording_id": rid,
        }
        if rid in known:
            synced.append({**entry, "synced_as": known[rid]})
        elif rid in skipped_ids:
            skipped.append(entry)
        else:
            candidates.append(entry)
    scancache.prune(cache, "inbox", live)
    scancache.save(root, cache)
    return {"candidates": candidates, "already_synced": synced,
            "skipped": skipped, "known_ids_count": len(known),
            "warnings": warnings}


def dedup(root: Path, ids: List[str]) -> dict:
    """Filter an adapter's discovery list against the ledger and skip list.

    Compares in canonical form but answers in the caller's own spelling: the
    orchestrator matches `new` back to the connector's listing entries by
    id, so what went in is what comes out.
    """
    given = [str(rid or "").strip() for rid in ids]
    keys = [_validate_id(rid) for rid in given]
    known, warnings = known_recording_ids(root)
    skipped_ids = read_skip_list(root)
    return {
        "new": [rid for rid, key in zip(given, keys)
                if key not in known and key not in skipped_ids],
        "synced": {rid: known[key] for rid, key in zip(given, keys)
                   if key in known},
        "skipped": [rid for rid, key in zip(given, keys)
                    if key in skipped_ids],
        "warnings": warnings,
    }


_COLLIDE_START_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")
# A recorder is pressed a few minutes after the calendar start; the grace
# absorbs that skew without matching a back-to-back meeting in the next slot.
OVERLAP_GRACE_MIN = 15


def _read_meeting_notes(root: Path) -> Tuple[List[dict], List[str]]:
    """(notes, warnings) — every `20-meetings/*.md`'s rel path, stem, and
    parsed frontmatter, read once. An unreadable note is a warning, never
    fatal — one mangled file must not blind `collide` to every other note."""
    notes: List[dict] = []
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        notes.append({"rel": rel, "stem": path.stem, "data": data})
    return notes, warnings


def load_collide_notes(root: Path) -> dict:
    """Preload `{"notes": [...], "warnings": [...]}` for a caller that runs
    many `collide` queries in one pass — `sync m365-triage --collide`, one
    per fetch survivor. Without this, `collide` re-globbed and re-parsed
    every meeting note once per candidate; loading once and passing `notes`
    through to every `collide` call turns an O(candidates × notes) re-read
    into one O(notes) read plus O(candidates × notes) in-memory comparisons.
    Surface `warnings` once for the whole run — `collide` itself produces no
    read-warnings when `notes` is supplied, only date-format ones.
    """
    notes, warnings = _read_meeting_notes(root)
    return {"notes": notes, "warnings": warnings}


def collide(root: Path, start_local: str, duration_min: int, *,
           notes: Optional[List[dict]] = None) -> dict:
    """Meeting notes whose time window overlaps a candidate recording.

    The exact-id ledger cannot see that plaud:X and m365:Y are the same
    conversation captured twice; this can. Fresh, uncached scan by default —
    it runs a handful of times per sync over one folder, and the ledger
    cache's entry shape only holds ids. Pass `notes` (from
    `load_collide_notes`) to skip the read/glob entirely when a caller
    (`sync m365-triage --collide`) runs many queries in one pass.

    A date-only note (legal per the meeting payload) has no window; it
    matches by calendar day and is flagged imprecise — a "look at it", never
    a "duplicate".

    Every match also carries `overlap_min` (the real intersection of the two
    windows, no grace, floored at 0) and `strong` (`overlap_min >= 1` and
    `overlap_min` at least half — rounded up — of the shorter of the two
    windows; always `False` for an imprecise match). The 15-minute grace
    above makes two merely-adjacent meetings (14:00-15:00 and 15:00-16:00)
    a *match* — real overlap is 0 — so a caller that acts automatically on a
    match (never just reports it) must additionally require `strong`, or it
    silently drops a genuine back-to-back meeting as a duplicate.

    `strong` is also always `False` when the *existing note*'s own
    `recording-duration` is falsy (0, missing, or unparseable) — a capture
    with `recording-duration: 0` legitimately means "nothing was recorded"
    (SKILL.md's own contract for a `type: note` capture), and treating that
    as a real 1-minute window would make its own strong-match threshold
    `ceil(1/2) == 1`, so any single overlapping minute against an unrelated
    real meeting would trivially count as strong. `overlap_min` is still
    reported for such a match — only `strong` is forced false, same
    treatment as an imprecise match gets.
    """
    start_text = str(start_local or "").strip()
    if not _COLLIDE_START_RE.match(start_text):
        raise SyncError(
            "--start must be YYYY-MM-DDTHH:MM in the vault owner's local time")
    if not isinstance(duration_min, int) or isinstance(duration_min, bool) \
            or duration_min < 0:
        raise SyncError(f"--duration-min {duration_min!r} must be an int >= 0")
    q_start = datetime.fromisoformat(start_text)
    q_minutes = max(duration_min, 1)
    q_end = q_start + timedelta(minutes=q_minutes)
    grace = timedelta(minutes=OVERLAP_GRACE_MIN)

    if notes is None:
        note_entries, warnings = _read_meeting_notes(root)
    else:
        note_entries, warnings = notes, []

    matches: List[dict] = []
    checked = 0
    for entry in note_entries:
        rel = entry["rel"]
        data = entry["data"]
        checked += 1
        date_text = str(data.get("date") or "").strip()
        imprecise = False
        overlap_min = 0
        strong = False
        if _COLLIDE_START_RE.match(date_text):
            n_start = datetime.fromisoformat(date_text)
            try:
                note_duration = int(data.get("recording-duration") or 0)
            except (TypeError, ValueError):
                note_duration = 0
            note_min = max(note_duration, 1)
            n_end = n_start + timedelta(minutes=note_min)
            hit = n_start <= q_end + grace and q_start <= n_end + grace
            if hit:
                overlap_start = max(q_start, n_start)
                overlap_end = min(q_end, n_end)
                overlap_min = max(
                    int((overlap_end - overlap_start).total_seconds() // 60),
                    0)
                # A falsy recording-duration (0, missing, unparseable) has no
                # real window — note_min above is a fabricated 1-minute
                # placeholder, and its own threshold would be ceil(1/2) == 1,
                # trivially satisfied by any single overlapping minute.
                if note_duration > 0:
                    threshold = math.ceil(min(q_minutes, note_min) / 2)
                    strong = overlap_min >= 1 and overlap_min >= threshold
        elif re.match(r"\A\d{4}-\d{2}-\d{2}\Z", date_text):
            imprecise = True
            hit = date_text in {q_start.date().isoformat(),
                                q_end.date().isoformat()}
        elif date_text:
            warnings.append(f"{rel}: date {date_text!r} is not ISO — skipped")
            continue
        else:
            warnings.append(f"{rel}: no date in frontmatter — skipped")
            continue
        if hit:
            matches.append({
                "path": rel,
                "stem": entry["stem"],
                "date": date_text,
                "recording-duration": data.get("recording-duration"),
                "source": data.get("source"),
                "source-recording-id": data.get("source-recording-id"),
                "calendar-subject": data.get("calendar-subject"),
                "imprecise": imprecise,
                "overlap_min": overlap_min,
                "strong": strong,
            })
    return {"matches": matches, "checked": checked, "warnings": warnings}


def reconcile_reviews(root: Path, *, timestamp: Optional[str] = None) -> dict:
    """Fold triage ticks back into review_status: reviewed true flips
    needs-review -> confirmed. One-way and narrow: a tick on a note that still
    carries a `conflicts-with` edge is surfaced for a human, never
    auto-confirmed — that edge means the note is a duplicate the CLI kept
    rather than overwrite a confirmed meeting, and confirming it silently would
    bless two notes for one meeting. Clearing the edge is how a human says the
    duplicate is resolved; the next run folds the tick. `archived` is never
    read by any pipeline.

    Every flip also stamps `confirmed-at` (ISO to the minute, `timestamp` or
    now). The update queue compares a project's `state-updated` against the
    *later* of a meeting's datetime and this stamp: a meeting that happened
    before the project's last state update but was confirmed after it used
    to fall out of the queue permanently, because meeting time alone said it
    had already been seen. Notes confirmed before the stamp existed carry no
    field and keep comparing on datetime alone — nothing is reprocessed.
    """
    if timestamp is None:
        stamp = datetime.now().isoformat(timespec="minutes")
    else:
        try:
            stamp = project._require_iso_datetime(timestamp, "--timestamp")
        except project.ProjectError as exc:
            raise SyncError(str(exc)) from exc
    flipped: List[str] = []
    conflict_ticks: List[str] = []
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        if data.get("reviewed") is not True:
            continue
        status = data.get("review_status")
        if status != "needs-review":
            if status != "confirmed":
                warnings.append(
                    f"{rel}: review_status {status!r} is not a current value "
                    "— this note predates the needs-attention retirement and "
                    "needs the pending migration before its review tick can fold"
                )
            continue
        if data.get("conflicts-with"):
            conflict_ticks.append(rel)
            continue
        try:
            updated = markdown.replace_scalar_field(
                text, "review_status", "confirmed")
            updated = markdown.upsert_scalar_field(updated, "confirmed-at", stamp)
        except ValueError as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        vault.atomic_write(path, updated)
        flipped.append(rel)
    return {"flipped": flipped, "conflict_ticks": conflict_ticks,
            "confirmed_at": stamp,
            "warnings": warnings}


def _entities_list(value) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


# `projects[]` holds bare slugs — but a hand edit during triage occasionally
# writes a wikilink instead (`[[colruyt-ai-transformation]]`), which resolves
# to nothing: the project is a *folder*, so the link dangles (clicking it
# creates a stray note in the vault root) and `derive_entities` can't follow
# it, leaving the meeting invisible to its entity's dossier. Shipped as a real
# bug 2026-09-02.
_PROJECT_WIKILINK_RE = re.compile(r"\A\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\Z")


def _normalize_project_entry(entry: str) -> str:
    """Bare slug from a projects[] entry: strip `[[...]]` (alias form takes
    the target), then whitespace. Anything else passes through untouched —
    an entry this can't fix is `derive_entities`'s to refuse."""
    text = str(entry).strip()
    match = _PROJECT_WIKILINK_RE.match(text)
    if match:
        text = match.group(1).strip()
    return text


def rederive_entities(root: Path) -> dict:
    """Fold pass: re-derive `entities` from `projects` on every meeting note.

    `entities` is machine-owned once a meeting has a project (see
    `meeting.write`, which derives it at creation), but nothing keeps the two
    in sync afterward — a project re-triaged by hand after the note was
    written leaves the old `entities` stale. This is the repair: for every
    meeting with a non-empty `projects[]`, recompute
    `entities := project.derive_entities(projects)` and rewrite only when the
    stored value differs. A meeting whose projects[] does not fully resolve
    (missing project index, or a project missing its `entity:` field) is
    reported under `unresolved` and left byte-identical — the same
    all-or-nothing refusal `derive_entities` and migration 001 both use, so a
    partial list is never written over a stale-but-honest one.

    Hand edits also drift in *form*, not just assignment: a wikilink written
    where a bare slug belongs (see `_normalize_project_entry`). Entries are
    normalized before deriving, and when normalization changed anything *and*
    the normalized list fully resolves, `projects` is rewritten alongside
    `entities` and the file reported under `normalized_files`. A wikilink
    that still doesn't resolve after unwrapping stays byte-identical and is
    reported under `unresolved`, like any other bad entry.
    """
    checked = 0
    changed: List[str] = []
    normalized_files: List[str] = []
    unresolved: List[dict] = []
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        projects = _entities_list(data.get("projects"))
        if not projects:
            continue
        checked += 1
        normalized = [_normalize_project_entry(entry) for entry in projects]
        try:
            derived = project.derive_entities(root, normalized)
        except project.ProjectError as exc:
            unresolved.append({"file": rel, "reason": str(exc)})
            continue
        projects_drifted = normalized != projects
        entities_stale = _entities_list(data.get("entities")) != derived
        if not projects_drifted and not entities_stale:
            continue
        try:
            updated = text
            if projects_drifted:
                updated = markdown.upsert_scalar_field(
                    updated, "projects", "[" + ", ".join(normalized) + "]")
            updated = markdown.upsert_scalar_field(
                updated, "entities", "[" + ", ".join(derived) + "]")
        except ValueError as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        vault.atomic_write(path, updated)
        changed.append(rel)
        if projects_drifted:
            normalized_files.append(rel)
    return {
        "checked": checked,
        "changed": len(changed),
        "changed_files": changed,
        "normalized_files": normalized_files,
        "unresolved": unresolved,
        "warnings": warnings,
    }


def routing_signals(root: Path) -> dict:
    """Compact digest of what exists, for a model deciding where a new
    recording routes — values only, never note bodies or free text, so the
    digest stays small.

    Projects come from `30-projects/*/index.md` frontmatter
    (`project-name`, `entity`, `status`); a folder with no index.md is not a
    project and is skipped. Malformed frontmatter is reported as a warning
    and the project comes back with null fields rather than dropping it or
    failing the whole call — one mangled index.md must not blind routing to
    every other project. Entities are `40-entities/*/` directory names;
    people are `50-people/*.md` stems.
    """
    projects: List[dict] = []
    warnings: List[str] = []
    projects_dir = root / PROJECTS_DIR
    if projects_dir.is_dir():
        for folder in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            index = folder / "index.md"
            if not index.is_file():
                continue
            slug = folder.name
            try:
                data, _ = markdown.split_frontmatter(
                    index.read_text(encoding="utf-8"))
                projects.append({
                    "slug": slug,
                    "name": data.get("project-name"),
                    "entity": data.get("entity"),
                    "status": data.get("status"),
                })
            except (ValueError, OSError):
                projects.append({"slug": slug, "name": None, "entity": None,
                                 "status": None})
                warnings.append(f"{slug}: unparseable frontmatter")
    entities = vault.list_dir_names(root / ENTITIES_DIR)
    people_dir = root / PEOPLE_DIR
    people = sorted(p.stem for p in people_dir.glob("*.md")) \
        if people_dir.is_dir() else []
    return {"projects": projects, "entities": entities, "people": people,
            "warnings": warnings}


def _free_target(folder: Path, name: str) -> Path:
    """First unused name in folder, suffixing -2, -3, ... on collision.

    Two different files can legitimately arrive with the same name in the
    same month; neither may overwrite the other. Bounded the same way as
    meeting._first_free, so the two collision loops — in modules that call
    into each other — give one answer to the same problem instead of two.
    """
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    for counter in range(2, 100):
        candidate = folder / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise SyncError(
        f"more than 98 archived files named {name!r} in {folder.name} — "
        "clean up first"
    )


def archive(root: Path, relpath: str, today: str) -> dict:
    """Move a processed or parked inbox file to 90-archive/inbox/{YYYY-MM}/.

    The inbox is the pending set: a file that produced a note, or that a
    human parked, has left the queue and leaves the folder. What remains in
    10-inbox/ is what still needs processing — that is the whole of the
    processed-state story, and why no index note or state file is needed.

    Safe by construction: ids are content hashes, so an archived file keeps
    its id and stays deduped. A symlink is refused outright: moving one
    relocates the link, not the file, and scan() does not offer symlinks as
    candidates for the same reason. The month bucket comes from the run date
    and is deliberately not timezone-aware — an archive folder is a filing
    convenience, not a fact anything joins on.
    """
    day = vault.today_iso(today)
    rel = PurePosixPath(str(relpath or "").strip())
    if len(rel.parts) != 2 or rel.parts[0] != INBOX_DIR:
        raise SyncError(
            f"--path {relpath!r} must name a file directly inside {INBOX_DIR}/, "
            f"for example {INBOX_DIR}/2026-08-21-forwarded-email.txt"
        )
    name = rel.parts[1]
    if name in _IGNORED_NAMES or name.startswith("."):
        raise SyncError(
            f"{name!r} is not a sync candidate and is never archived — "
            "scan() ignores it too"
        )
    source = root / INBOX_DIR / name
    if source.is_symlink():
        raise SyncError(
            f"{rel.as_posix()} is a symlink — refusing to archive it. Moving a "
            "symlink relocates the link, not the file it points at, so the "
            "archive would hold a pointer to something outside the vault. "
            "Replace it with the real file, or remove it from the inbox."
        )
    if not source.is_file():
        raise SyncError(
            f"{rel.as_posix()} does not exist or is not a regular file"
        )
    target_dir = root / ARCHIVE_DIR / ARCHIVE_INBOX_SUBDIR / day[:7]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _free_target(target_dir, name)
    shutil.move(str(source), str(target))
    return {"from": rel.as_posix(),
            "to": target.relative_to(root).as_posix()}


def _sidecar_text(name: str, source_relpath: str, recording_id: str,
                  reason: str, day: str, prior: Optional[dict] = None) -> str:
    """Prose for whoever opens the archive a quarter later.

    Deliberately without frontmatter: this explains a file, it is not a vault
    object, and nothing should ever try to validate it as one.

    `prior` is the skip record this id already had, if any. The three cases
    read differently and must not be flattened: a first park, a re-park whose
    reason was already on record, and a re-park of an id suppressed back when
    the list held ids alone — where the reason below is new, and saying
    otherwise would backdate it.
    """
    again = ""
    if prior is not None:
        again = (" This item was parked on an earlier run too; the reason "
                 "below is the one recorded then."
                 if prior.get("reason") else
                 " This item was parked on an earlier run too, but no reason "
                 "was recorded at the time — the one below was written now.")
    return (
        f"# Parked: {name}\n"
        "\n"
        f"Parked by `/sync-recordings` on {day} — not a capture, so no note "
        f"was written for it.{again}\n"
        "\n"
        f"- **Why:** {reason}\n"
        f"- **Came from:** `{source_relpath}`\n"
        f"- **Recording id:** `{recording_id}`, now on the never-propose-again "
        f"list in `{SKIP_FILE_RELPATH.as_posix()}`\n"
        "\n"
        "Nothing reads this file. To have the item processed after all, delete "
        f"that id's line from the skip list and drop the file back into "
        f"`{INBOX_DIR}/`.\n"
    )


def park(root: Path, relpath: str, recording_id: str, reason: str,
         today: str) -> dict:
    """Archive a non-capture, suppress its id, and record why — in one call.

    Parking is two writes that must not come apart: the file leaves the inbox
    and its id joins the never-propose-again list. Neither is legible without
    the reason, and a reason threaded through two separate calls can be
    omitted from one or drift between them. So this is the only entry point
    that parks an inbox file, and it refuses to run without a reason.

    The reason is written twice on purpose, because the two readers are
    different people at different times: the skip list answers "what has this
    vault suppressed, and why?", and the sidecar answers "why is this file
    sitting in my archive?" for someone browsing the folder who will never
    open a config directory.

    Order is deliberate. The id is validated and the reason required before
    anything moves; the suppression is recorded only after the move. A move
    that failed suppresses nothing, whereas recording first would leave an id
    suppressed while its file sat in the inbox — offered by scan() as skipped
    and unable ever to leave.
    """
    rid = _validate_id(recording_id)
    cleaned = _clean_reason(reason)
    if cleaned is None:
        raise SyncError(
            "a reason is required to park an item: it is the only record of "
            "why this was not a capture. Say what the file is and what it is "
            "not — for example 'vendor whitepaper, no capture content'."
        )
    # An id already suppressed with a reason keeps that reason — including in
    # this run's sidecar. The alternative is a vault telling two stories about
    # one decision: the skip list saying why the item was parked in August,
    # and a September sidecar for the same id asserting something else.
    prior = next((r for r in read_skip_records(root)
                  if r["recording_id"] == rid), None)
    effective = prior["reason"] if prior and prior["reason"] else cleaned
    moved = archive(root, relpath, today)
    landed = PurePosixPath(moved["to"]).name
    sidecar = root / PurePosixPath(moved["to"]).parent \
        / (landed + PARKED_SIDECAR_SUFFIX)
    vault.atomic_write(sidecar, _sidecar_text(
        landed, moved["from"], rid, effective, vault.today_iso(today),
        prior=prior))
    recorded = skip(root, rid, reason=effective,
                    source_name=PurePosixPath(moved["from"]).name)
    return {**moved, "sidecar": sidecar.relative_to(root).as_posix(),
            "recording_id": rid, "reason": effective,
            "already_present": recorded["already_present"]}
