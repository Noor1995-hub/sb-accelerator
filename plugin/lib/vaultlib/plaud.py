"""Plaud MCP adapter: reassemble raw tool JSON into one capture-bundle blob.

Transcript-first: the summary note is optional enrichment and its absence or
breakage never fails the bundle. Shapes are the lab-verified Plaud MCP
responses; anything else raises rather than guessing.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from . import dates

ENRICHMENT_HEADER = "## Enrichment (recorder summary)"


class PlaudError(Exception):
    """A malformed or failed Plaud payload the caller must handle."""


def _render_transcript(payload) -> Tuple[str, int]:
    """(speaker-labeled body, max end_time ms) from either response shape."""
    if isinstance(payload, dict):
        utterances = payload.get("segments") or []
        if not utterances:
            raise PlaudError("empty transcript (no segments)")
    elif isinstance(payload, list):
        txn = next((e for e in payload
                    if e.get("data_type") == "transaction"), None)
        if txn is None:
            raise PlaudError("no 'transaction' entry in transcript response")
        code = txn.get("data_error_code")
        if code is not None and code != 10:
            raise PlaudError(f"transcript data_error_code={code}")
        try:
            utterances = (json.loads(txn["data_content"])
                          if txn.get("data_content") else [])
        except json.JSONDecodeError as exc:
            raise PlaudError(
                f"transcript data_content is not valid JSON: {exc}"
            ) from exc
        if not utterances:
            raise PlaudError("empty transcript")
    else:
        raise PlaudError(
            f"unrecognized transcript shape ({type(payload).__name__})"
        )
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


def reassemble(meta_path: str, transcript_path: str, note_path: Optional[str],
               out_dir: str, *, timezone: Optional[str] = None,
               utc_offset: Optional[str] = None) -> dict:
    meta = _load(meta_path, "meta")
    if not isinstance(meta, dict) or not meta.get("id") or not meta.get("start_at"):
        raise PlaudError("meta must be the list_files entry: id, name, start_at, duration")
    rec_id = str(meta["id"])
    if "/" in rec_id or "\\" in rec_id or ".." in rec_id:
        raise PlaudError(f"meta id {rec_id!r} is not usable as a filename")
    transcript = _load(transcript_path, "transcript")
    note = _load(note_path, "note")

    try:
        start_utc = datetime.fromisoformat(str(meta["start_at"]))
    except ValueError as exc:
        raise PlaudError(f"meta start_at {meta['start_at']!r} is not ISO") from exc
    if start_utc.tzinfo is not None:
        from datetime import timezone as _timezone
        start_utc = start_utc.astimezone(_timezone.utc).replace(tzinfo=None)
    local, _ = dates.utc_to_local(start_utc, timezone, utc_offset)
    recorded_local = local.strftime("%Y-%m-%d %H:%M:%S")

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
