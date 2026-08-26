"""Plaud MCP adapter: reassemble raw tool JSON into one capture-bundle blob.

Transcript-first: the summary note is optional enrichment and its absence or
breakage never fails the bundle. Shapes are the verified Plaud MCP responses;
anything else raises rather than guessing.

`get_transcript` is paginated, so a transcript arrives as a set of pages and
`reassemble` takes one path per page. It checks them against the `total` the
pages themselves report: a caller that fetched only the first page gets an
error, not a note written from a third of the meeting.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone as _timezone
from pathlib import Path
from typing import Optional, Tuple

from . import dates

ENRICHMENT_HEADER = "## Enrichment (recorder summary)"


class PlaudError(Exception):
    """A malformed or failed Plaud payload the caller must handle."""


def _legacy_utterances(payload: list) -> list:
    """The pre-pagination response: one `transaction` entry holding the whole
    transcript as a JSON string."""
    txn = next((e for e in payload
                if isinstance(e, dict)
                and e.get("data_type") == "transaction"), None)
    if txn is None:
        raise PlaudError("no 'transaction' entry in transcript response")
    code = txn.get("data_error_code")
    if code is not None and code != 10:
        raise PlaudError(f"transcript data_error_code={code}")
    try:
        return (json.loads(txn["data_content"])
                if txn.get("data_content") else [])
    except json.JSONDecodeError as exc:
        raise PlaudError(
            f"transcript data_content is not valid JSON: {exc}"
        ) from exc


def _paged_utterances(pages: list) -> list:
    """Every utterance across the pages, in transcript order.

    `get_transcript` answers one page at a time — 50 utterances by default —
    with `total`, `offset` and a `next_cursor`. A caller that takes the first
    page and stops loses the rest of the conversation *and* the duration with
    it, silently: the segments it did get are well-formed, so nothing
    downstream can tell. So completeness is checked here rather than trusted,
    and the pages are ordered by their own `offset` — scratch filenames are
    the caller's business, not an ordering contract.
    """
    ordered = sorted(pages, key=lambda page: int(page.get("offset") or 0))
    total = next((int(page["total"]) for page in ordered
                  if page.get("total") is not None), None)
    utterances: list = []
    expected = 0
    for page in ordered:
        segments = page.get("segments") or []
        if total is not None:
            offset = int(page.get("offset") or 0)
            if offset != expected:
                raise PlaudError(
                    f"transcript pages do not tile: expected offset "
                    f"{expected}, got {offset} — pass each page of the "
                    "paginated transcript exactly once"
                )
            expected = offset + len(segments)
        utterances.extend(segments)
    if total is not None and len(utterances) != total:
        raise PlaudError(
            f"transcript is incomplete: {len(utterances)} of {total} "
            "utterances — follow next_cursor and pass every page"
        )
    return utterances


def _render_transcript(payloads: list) -> Tuple[str, int]:
    """(speaker-labeled body, max end_time ms) from one or more pages."""
    unknown = next((p for p in payloads if not isinstance(p, (dict, list))),
                   None)
    if unknown is not None:
        raise PlaudError(
            f"unrecognized transcript shape ({type(unknown).__name__})"
        )
    legacy = [p for p in payloads if isinstance(p, list)]
    pages = [p for p in payloads if isinstance(p, dict)]
    if legacy and pages:
        raise PlaudError(
            "transcript payloads mix response shapes — pass either one "
            "legacy transaction payload or the pages of one paginated "
            "transcript"
        )
    if legacy:
        if len(legacy) > 1:
            raise PlaudError(
                "a legacy transaction payload is not paginated — pass "
                "exactly one"
            )
        utterances = _legacy_utterances(legacy[0])
        if not utterances:
            raise PlaudError("empty transcript")
    else:
        utterances = _paged_utterances(pages)
        if not utterances:
            raise PlaudError("empty transcript (no segments)")
    utterances = [u for u in utterances if isinstance(u, dict)]
    if not utterances:
        raise PlaudError("empty transcript")
    lines = [f'{u.get("speaker", "Speaker ?")}: {(u.get("content") or "").strip()}'
             for u in utterances]
    max_end = max((u.get("end_time") or 0) for u in utterances)
    return "\n".join(lines), int(max_end)


def _extract_summary(note) -> Optional[str]:
    """The recorder's own summary, or None. Never raises — optional means
    optional."""
    if not note or not isinstance(note, list):
        return None
    entry = next((e for e in note
                  if isinstance(e, dict)
                  and e.get("data_type") == "auto_sum_note"), None)
    if entry is None:
        return None
    code = entry.get("data_error_code")
    if code is not None and code != 10:
        return None
    content = entry.get("data_content")
    return content if content and str(content).strip() else None


def _load(path: Optional[str], label: str):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlaudError(f"{label} file {path!r} is unreadable: {exc}") from exc


def _load_all(paths, label: str) -> list:
    """One path or many — a paginated transcript arrives as a set of files."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    loaded = [_load(str(path), label) for path in paths or []]
    if not loaded:
        raise PlaudError(f"no {label} file given")
    return loaded


def reassemble(meta_path: str, transcript_paths, note_path: Optional[str],
               out_dir: str, *, timezone: Optional[str] = None,
               utc_offset: Optional[str] = None) -> dict:
    meta = _load(meta_path, "meta")
    if not isinstance(meta, dict) or not meta.get("id") or not meta.get("start_at"):
        raise PlaudError("meta must be the list_files entry: id, name, start_at, duration")
    rec_id = str(meta["id"])
    if "/" in rec_id or "\\" in rec_id or ".." in rec_id:
        raise PlaudError(f"meta id {rec_id!r} is not usable as a filename")
    transcript = _load_all(transcript_paths, "transcript")
    note = _load(note_path, "note")

    try:
        start_utc = datetime.fromisoformat(str(meta["start_at"]))
    except ValueError as exc:
        raise PlaudError(f"meta start_at {meta['start_at']!r} is not ISO") from exc
    if start_utc.tzinfo is not None:
        start_utc = start_utc.astimezone(_timezone.utc).replace(tzinfo=None)
    local, _ = dates.utc_to_local(start_utc, timezone, utc_offset)
    # Both consumers of this value parse it verbatim — `meeting write`
    # (date) and `sync collide` (--start) — and neither accepts seconds
    # or a space separator. Widening the format here costs every
    # recording a rejection round trip.
    recorded_local = local.strftime("%Y-%m-%dT%H:%M")

    body, max_end_ms = _render_transcript(transcript)
    title = meta.get("name") or "Untitled recording"
    parts = [title, "", f"> Recorded: {recorded_local}", "", "#Transcript", body]
    summary = _extract_summary(note)
    if summary:
        parts += ["", ENRICHMENT_HEADER, str(summary).rstrip()]
    blob = "\n".join(parts) + "\n"

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    blob_path = out / f"{rec_id}.blob.md"
    blob_path.write_text(blob, encoding="utf-8", newline="\n")

    duration_ms = max_end_ms or int(meta.get("duration") or 0)
    return {
        "recording_id": f"plaud:{rec_id}",
        "duration_min": round(duration_ms / 60000),
        "recorded_local": recorded_local,
        "has_enrichment": summary is not None,
        "blob_path": str(blob_path),
    }
