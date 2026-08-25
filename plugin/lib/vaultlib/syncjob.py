"""Inbox scan, dedup, the skip list, and the sweep: the deterministic ledger
under /sync-recordings.

The vault itself is the ledger — a recording is synced iff its namespaced
source-recording-id appears in some 20-meetings/*.md. There is no second
ledger to reconcile, so a failed item (which wrote nothing) retries
naturally on the next run. The skip list exists for the one case the ledger
cannot express: a human said "never propose this one again".

scan-cache.json is a cache, not a ledger: it remembers what the vault
already said, keyed on (mtime_ns, size), and is rebuilt in silence whenever
it is missing or does not match. Deleting it is always safe and changes no
answer — see scancache.py.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

from . import markdown, scancache, vault

INBOX_DIR = vault.INBOX_DIR
MEETINGS_DIR = vault.MEETINGS_DIR
NAMESPACES = ("inbox", "plaud", "m365")
SKIP_FILE_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"
ARCHIVE_DIR = vault.ARCHIVE_DIR
ARCHIVE_INBOX_SUBDIR = "inbox"
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


def _validate_id(recording_id: str) -> str:
    text = str(recording_id or "").strip()
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
            ids[entry["recording_id"]] = rel
    scancache.prune(cache, "ledger", live)
    if owns_cache:
        scancache.save(root, cache)
    return ids, warnings


def read_skip_list(root: Path) -> Set[str]:
    skip_file = root / SKIP_FILE_RELPATH
    if not skip_file.is_file():
        return set()
    return {line.strip() for line in
            skip_file.read_text(encoding="utf-8").splitlines() if line.strip()}


def skip(root: Path, recording_id: str) -> dict:
    """Append one id to the skip list (idempotent)."""
    rid = _validate_id(recording_id)
    existing = read_skip_list(root)
    if rid in existing:
        return {"recording_id": rid, "already_present": True}
    skip_file = root / SKIP_FILE_RELPATH
    skip_file.parent.mkdir(parents=True, exist_ok=True)
    with open(skip_file, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(rid + "\n")
    return {"recording_id": rid, "already_present": False}


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
    """Filter an adapter's discovery list against the ledger and skip list."""
    validated = [_validate_id(rid) for rid in ids]
    known, warnings = known_recording_ids(root)
    skipped_ids = read_skip_list(root)
    return {
        "new": [rid for rid in validated
                if rid not in known and rid not in skipped_ids],
        "synced": {rid: known[rid] for rid in validated if rid in known},
        "skipped": [rid for rid in validated if rid in skipped_ids],
        "warnings": warnings,
    }


def reconcile_reviews(root: Path) -> dict:
    """Fold triage ticks back into review_status: reviewed true flips
    needs-review -> confirmed. One-way and narrow: a tick on a note that still
    carries a `conflicts-with` edge is surfaced for a human, never
    auto-confirmed — that edge means the note is a duplicate the CLI kept
    rather than overwrite a confirmed meeting, and confirming it silently would
    bless two notes for one meeting. Clearing the edge is how a human says the
    duplicate is resolved; the next run folds the tick. `archived` is never
    read by any pipeline.
    """
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
        except ValueError as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        vault.atomic_write(path, updated)
        flipped.append(rel)
    return {"flipped": flipped, "conflict_ticks": conflict_ticks,
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
