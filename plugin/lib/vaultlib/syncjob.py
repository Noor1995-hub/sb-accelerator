"""Inbox scan, dedup, and the skip list: the deterministic ledger under
/sync-recordings.

The vault itself is the ledger — a recording is synced iff its namespaced
source-recording-id appears in some 20-meetings/*.md. There is no second
state file to reconcile, so a failed item (which wrote nothing) retries
naturally on the next run. The skip list exists for the one case the ledger
cannot express: a human said "never propose this one again".
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Set, Tuple

from . import markdown, vault

INBOX_DIR = "10-inbox"
MEETINGS_DIR = "20-meetings"
NAMESPACES = ("inbox", "plaud", "m365")
SKIP_FILE_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"
_IGNORED_NAMES = {"README.md"}


class SyncError(Exception):
    """A sync argument or id the caller must fix."""


def content_id(path: Path) -> str:
    """inbox:{16 hex} — content-addressed, so a renamed drop stays deduped.

    Chunked read: the inbox legitimately holds large recorder exports, and
    scan hashes every file on every run."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"inbox:{digest.hexdigest()[:16]}"


def _validate_id(recording_id: str) -> str:
    text = str(recording_id or "").strip()
    prefix = text.split(":", 1)[0] if ":" in text else ""
    if prefix not in NAMESPACES or not text.split(":", 1)[1]:
        raise SyncError(
            f"recording id {recording_id!r} must carry a namespace prefix, "
            f"one of {[n + ':' for n in NAMESPACES]}"
        )
    return text


def known_recording_ids(root: Path) -> Tuple[Dict[str, str], List[str]]:
    """{source-recording-id: meeting relpath} across 20-meetings/, plus
    warnings for unparseable notes (reported, never fatal — one mangled file
    must not stop the sync)."""
    ids: Dict[str, str] = {}
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        rid = data.get("source-recording-id")
        if rid:
            ids[str(rid)] = path.relative_to(root).as_posix()
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

    Which candidates are transcript-shaped is judgment and stays with the
    model; this returns every regular file with enough metadata to decide.
    """
    known, warnings = known_recording_ids(root)
    skipped_ids = read_skip_list(root)
    candidates, synced, skipped = [], [], []
    inbox = root / INBOX_DIR
    for path in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if not path.is_file() or path.name in _IGNORED_NAMES \
                or path.name.startswith("."):
            continue
        rid = content_id(path)
        entry = {
            "name": path.name,
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "recording_id": rid,
        }
        if rid in known:
            synced.append({**entry, "synced_as": known[rid]})
        elif rid in skipped_ids:
            skipped.append(entry)
        else:
            candidates.append(entry)
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
    needs-review -> confirmed. One-way and narrow: a tick on a
    needs-attention note is surfaced for a human, never auto-confirmed, and
    `archived` is never read by any pipeline.
    """
    flipped: List[str] = []
    attention: List[str] = []
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
        if status == "needs-attention":
            attention.append(rel)
            continue
        if status != "needs-review":
            continue
        try:
            updated = markdown.replace_scalar_field(
                text, "review_status", "confirmed")
        except ValueError as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        vault.atomic_write(path, updated)
        flipped.append(rel)
    return {"flipped": flipped, "needs_attention_ticks": attention,
            "warnings": warnings}
