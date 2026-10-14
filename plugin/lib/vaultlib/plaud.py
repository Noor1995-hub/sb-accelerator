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
import re
import time
from datetime import datetime, timezone as _timezone
from pathlib import Path
from typing import List, Optional, Tuple

from . import dates, syncjob
from .m365 import M365Error, _resolve_spill, spill_roots

ENRICHMENT_HEADER = "## Enrichment (recorder summary)"

# The floor is an order-of-magnitude tripwire, not a completeness proof:
# genuine transcripts end within ~2% of the recording's length; the live
# forged-counts incident sat at ~25%. Half tolerates a recording that is
# largely trailing silence.
DURATION_COVERAGE_FLOOR = 0.5


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
    the caller's business, not an ordering contract. Each page is also
    checked against itself — `returned` against its own segment count, and
    `limit`/`next_cursor` against the shape a short final page must have —
    because a page can pass every cross-page check and still be forged.
    """
    ordered = sorted(pages, key=lambda page: int(page.get("offset") or 0))
    totals = {int(page["total"]) for page in ordered
              if page.get("total") is not None}
    if len(totals) > 1:
        raise PlaudError(
            f"transcript pages disagree about total ({sorted(totals)}) — "
            "the page files do not match what the connector sent; re-fetch "
            "the transcript rather than editing pages")
    total = totals.pop() if totals else None
    utterances: list = []
    expected = 0
    for page in ordered:
        segments = page.get("segments") or []
        returned = page.get("returned")
        if returned is not None and int(returned) != len(segments):
            raise PlaudError(
                f"page at offset {int(page.get('offset') or 0)} says "
                f"returned={int(returned)} but carries {len(segments)} "
                "segments — the page file does not match what the "
                "connector sent; re-fetch it rather than editing it")
        limit = page.get("limit")
        if (limit is not None and page.get("next_cursor") is not None
                and len(segments) < int(limit)):
            raise PlaudError(
                f"page at offset {int(page.get('offset') or 0)} is shorter "
                f"than its limit ({len(segments)} < {int(limit)}) yet "
                "carries a next_cursor — a short page is the final page; "
                "re-fetch the transcript")
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
    if ordered and ordered[-1].get("next_cursor") is not None:
        raise PlaudError(
            "the last page carries a non-null next_cursor — the transcript "
            "has more pages; follow the cursor and pass every page")
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
    # The ledger key: the connector's id with Plaud's `of_` object prefix
    # stripped (syncjob.canonical_id). The blob keeps the connector's own id
    # in its filename — that is scratch, not ledger.
    recording_id = syncjob.canonical_id(f"plaud:{rec_id}")
    transcript = _load_all(transcript_paths, "transcript")
    for page in transcript:
        # Meta and page may spell one recording differently (the listing and
        # the transcript endpoint changed spelling on different days).
        if isinstance(page, dict) and page.get("file_id") \
                and syncjob.canonical_id(f"plaud:{page['file_id']}") \
                != recording_id:
            raise PlaudError(
                f"transcript page carries file_id {page['file_id']!r} but "
                f"the meta is recording {rec_id!r} — wrong meta/transcript "
                "pairing")
    # The note is optional enrichment (worker contract: "on failure proceed
    # without"), and the reassemble command always names its file — a fetch
    # that failed leaves no file, which must not fail the recording.
    if note_path is not None and not Path(note_path).is_file():
        note_path = None
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
    meta_ms = int(meta.get("duration") or 0)
    warnings: list = []
    coverage = None
    if meta_ms > 0 and max_end_ms > 0:
        coverage = round(100 * max_end_ms / meta_ms)
        if max_end_ms < DURATION_COVERAGE_FLOOR * meta_ms:
            raise PlaudError(
                f"transcript timeline ends at "
                f"{round(max_end_ms / 60000)} of "
                f"{round(meta_ms / 60000)} recorded minutes — pages are "
                "missing or not verbatim; re-fetch every page via "
                "next_cursor, never edit page files to pass this check")
        if max_end_ms > meta_ms + max(5000, meta_ms // 50):
            warnings.append(
                f"transcript timestamps run {round((max_end_ms - meta_ms) / 60000)} "
                "minutes beyond the recording's own duration — check the "
                "meta/transcript pairing")
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
        "recording_id": recording_id,
        "duration_min": round(duration_ms / 60000),
        "recorded_local": recorded_local,
        "has_enrichment": summary is not None,
        "blob_path": str(blob_path),
        "warnings": warnings,
        "coverage_pct": coverage,
        # Same paging signal as m365 reassemble: the worker reads a long
        # blob in windows instead of drafting from the first one alone.
        "blob_lines": blob.count("\n"),
        "blob_chars": len(blob),
    }


# --- capture: a get_transcript / get_note result, copied to scratch by the CLI
#
# The worker used to persist every page by re-typing it as Write input. That
# copy was never verbatim (models re-indent JSON and drop the connector's
# wrapper), it cost ~250k output tokens for a two-hour meeting, and from
# claude-sonnet-5-5 on the API's output classifier stops long re-typed
# copies partway (stop_reason "refusal") — every recording past ~45 minutes
# failed, every run. So the model never writes a result; the CLI copies the
# bytes from where the host already put them:
#
#   * a result over the tool-result cap is spilled to a tool-results file,
#     and the notice names it (`--from`, resolved as for `m365 capture`);
#   * a result under the cap is in the session's own log the moment it
#     arrives. The connector wraps every result in a block named
#     `untrusted-user-data-<16 hex>`, random per call, so that name finds
#     exactly one result (`--tag`).
#
# Either way the page written is the JSON inside the wrapper, byte for byte.

TAG_RE = re.compile(r"untrusted-user-data-[0-9a-f]{16}\Z")
_WRAPPED = r"<({tag})[^>\n]*>\n(.*)\n</\1>"
# The session log being searched is the worker's own, written seconds ago.
# A window keeps the scan off months of old sessions (gigabytes on a
# long-lived host) without any risk to the live one.
LOG_WINDOW_S = 12 * 3600


def _unwrap(text: str, tag: Optional[str] = None) -> Tuple[str, str]:
    """(tag, inner JSON text) from one wrapped connector result."""
    pattern = _WRAPPED.format(
        tag=re.escape(tag) if tag else r"untrusted-user-data-[0-9a-f]{16}")
    found = re.findall(pattern, text, re.S)
    if len(found) != 1:
        raise PlaudError(
            "not one wrapped Plaud result (expected exactly one "
            "untrusted-user-data block) — capture only copies a "
            "get_transcript or get_note result")
    return found[0]


def _log_results(text) -> List[str]:
    """The text parts of every tool result in one session-log line."""
    out: List[str] = []
    try:
        entry = json.loads(text)
    except json.JSONDecodeError:
        return out
    message = entry.get("message") if isinstance(entry, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else []:
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            continue
        parts = block.get("content")
        if isinstance(parts, str):
            out.append(parts)
        elif isinstance(parts, list):
            out.extend(p["text"] for p in parts
                       if isinstance(p, dict) and isinstance(p.get("text"), str))
    return out


def _from_log(tag: str, roots: List[Path], now: float) -> Tuple[str, Path]:
    logs = [f for root in roots if root.is_dir() for f in root.rglob("*.jsonl")
            if now - f.stat().st_mtime <= LOG_WINDOW_S]
    # Newest first: the worker's own log was written to a moment ago.
    for log in sorted(set(logs), key=lambda f: f.stat().st_mtime, reverse=True):
        bodies = set()
        with open(log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if tag not in line:
                    continue
                for result in _log_results(line):
                    if f"<{tag}" in result:
                        bodies.add(_unwrap(result, tag)[1])
        if len(bodies) > 1:
            raise PlaudError(f"{tag} names {len(bodies)} different results "
                             "in one session log")
        if bodies:
            return bodies.pop(), log
    raise PlaudError(
        f"no tool result tagged {tag} in a session log of the last "
        f"{LOG_WINDOW_S // 3600} hours (looked under: "
        f"{', '.join(str(r) for r in roots) or 'no roots'}) — pass the tag "
        "exactly as the result's first line names it")


def _check_page(page: dict) -> None:
    for key in ("total", "offset", "returned"):
        if not isinstance(page.get(key), int):
            raise PlaudError(f"transcript page has no integer {key!r}")
    if "next_cursor" not in page:
        raise PlaudError("transcript page has no next_cursor key")
    segments = page.get("segments")
    if not isinstance(segments, list) or len(segments) != page["returned"]:
        raise PlaudError(
            "transcript page's segments do not match its own 'returned' — "
            "not a complete get_transcript result")


def capture(out_path: str, *, source: Optional[str] = None,
            tag: Optional[str] = None, roots: Optional[List[Path]] = None,
            now: Optional[float] = None) -> dict:
    """Copy one Plaud result to scratch, verbatim. Exactly one of `source`
    (the spill path the host's notice named) or `tag` (the result's
    untrusted-user-data block name). Returns counts — never content."""
    if (source is None) == (tag is None):
        raise PlaudError("capture takes exactly one of --from or --tag")
    roots = spill_roots() if roots is None else list(roots)
    if source is not None:
        try:
            path = _resolve_spill(source, roots)
        except M365Error as exc:
            raise PlaudError(str(exc)) from exc
        tag, body = _unwrap(path.read_text(encoding="utf-8-sig"))
        found_in = "spill"
    else:
        if not TAG_RE.match(tag):
            raise PlaudError(
                f"{tag!r} is not a result tag — expected "
                "untrusted-user-data- and 16 hex digits")
        body, _log = _from_log(tag, roots, time.time() if now is None else now)
        found_in = "session-log"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PlaudError(f"captured result is not valid JSON: {exc}") from exc

    result = {"captured_from": found_in, "path": str(out_path)}
    if isinstance(payload, dict) and "segments" in payload:
        _check_page(payload)
        result.update(kind="transcript-page", file_id=payload.get("file_id"),
                      total=payload["total"], offset=payload["offset"],
                      returned=payload["returned"],
                      next_cursor=payload["next_cursor"])
    elif isinstance(payload, list):
        result.update(kind="note", entries=len(payload))
    else:
        raise PlaudError("captured result is neither a transcript page nor a "
                         "note — capture only copies get_transcript and "
                         "get_note results")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8", newline="")
    result["bytes"] = len(body.encode("utf-8"))
    return result
