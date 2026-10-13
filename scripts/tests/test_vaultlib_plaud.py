"""plaud reassemble: raw MCP JSON -> one normalized capture-bundle blob.

Shapes are ported from the lab's proven sync-helper; the timezone is a
parameter (the lab hardcoded Brussels)."""
import json
from pathlib import Path

import pytest

from vaultlib import plaud

META = {"id": "rec_42", "name": "Vendor strategy walk-through",
        "start_at": "2026-05-20T09:03:00", "duration": 2460000}
SEGMENTS = {"block": "transaction", "segments": [
    {"speaker": "Speaker 1", "content": "Let's consolidate vendors.",
     "end_time": 60000},
    {"speaker": "Speaker 2", "content": "Agreed, single platform.",
     "end_time": 2400000},
]}
LEGACY = [{"data_type": "transaction", "data_error_code": 10,
           "data_content": json.dumps(SEGMENTS["segments"])}]
NOTE = [{"data_type": "auto_sum_note", "data_error_code": 10,
         "data_content": "## Summary\nVendor consolidation discussed."}]


def write_json(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_reassemble_new_shape_with_note(tmp_path):
    out = tmp_path / "scratch"
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),
        write_json(tmp_path, "n.json", NOTE),
        str(out), utc_offset="+02:00")
    assert result["recording_id"] == "plaud:rec_42"
    assert result["duration_min"] == 40           # from max end_time, not meta
    assert result["recorded_local"] == "2026-05-20T11:03"
    assert result["has_enrichment"] is True
    blob = Path(result["blob_path"]).read_text(encoding="utf-8")
    assert blob.splitlines()[0] == "Vendor strategy walk-through"
    assert "> Recorded: 2026-05-20T11:03" in blob
    assert "#Transcript" in blob
    assert "Speaker 1: Let's consolidate vendors." in blob
    assert "## Enrichment (recorder summary)" in blob


def test_reassemble_legacy_shape_without_note(tmp_path):
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", LEGACY),
        None, str(tmp_path / "scratch"), utc_offset="+00:00")
    assert result["has_enrichment"] is False
    blob = Path(result["blob_path"]).read_text(encoding="utf-8")
    assert "Enrichment" not in blob
    assert "> Recorded: 2026-05-20T09:03" in blob


def test_reassemble_empty_transcript_raises(tmp_path):
    empty = {"segments": []}
    with pytest.raises(plaud.PlaudError, match="empty transcript"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", empty),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_reassemble_transcript_error_code_raises(tmp_path):
    bad = [{"data_type": "transaction", "data_error_code": 40,
            "data_content": ""}]
    with pytest.raises(plaud.PlaudError, match="data_error_code=40"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", bad),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_broken_note_degrades_to_no_enrichment(tmp_path):
    bad_note = [{"data_type": "auto_sum_note", "data_error_code": 40}]
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),
        write_json(tmp_path, "n.json", bad_note),
        str(tmp_path / "s"), utc_offset="+00:00")
    assert result["has_enrichment"] is False


def test_a_note_file_that_was_never_written_degrades_to_no_enrichment(tmp_path):
    # The summary fetch failed, so the worker wrote no note file — but the
    # reassemble command still names it. The recording must not fail.
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),
        str(tmp_path / "rec_1.note.json"),
        str(tmp_path / "s"), utc_offset="+00:00")
    assert result["has_enrichment"] is False


def test_non_json_data_content_raises_plauderror(tmp_path):
    bad = [{"data_type": "transaction", "data_error_code": 10,
            "data_content": "not json at all"}]
    with pytest.raises(plaud.PlaudError, match="not valid JSON"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", bad),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_path_escaping_meta_id_raises(tmp_path):
    evil = dict(META, id="../escaped")
    with pytest.raises(plaud.PlaudError, match="not usable as a filename"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", evil),
            write_json(tmp_path, "t.json", SEGMENTS),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_tz_aware_start_at_is_normalized_to_utc_first(tmp_path):
    """Plaud sends naive UTC, but the field is ISO and an offset is legal in
    it — the offset has to come off before the local conversion, or it is
    applied twice."""
    aware = dict(META, start_at="2026-05-20T09:03:00+05:00")
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", aware),
        write_json(tmp_path, "t.json", SEGMENTS),
        None, str(tmp_path / "s"), utc_offset="+02:00")
    # 09:03+05:00 is 04:03 UTC, which is 06:03 at +02:00.
    assert result["recorded_local"] == "2026-05-20T06:03"


def test_reassemble_recorded_local_handles_the_dst_edge(tmp_path):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
    except Exception:
        import pytest
        pytest.skip("no tz database on host")
    meta = tmp_path / "m.json"
    meta.write_text(json.dumps({"id": "r1", "name": "T",
                                "start_at": "2026-03-29T01:30:00",
                                "duration": 60000}), encoding="utf-8")
    tr = tmp_path / "t.json"
    tr.write_text(json.dumps({"segments": [
        {"speaker": "A", "content": "hi", "end_time": 60000}]}),
        encoding="utf-8")
    result = plaud.reassemble(str(meta), str(tr), None, str(tmp_path / "out"),
                              timezone="Europe/Brussels")
    assert result["recorded_local"] == "2026-03-29T03:30"


# --- Paginated transcripts -------------------------------------------------
#
# `get_transcript` returns one page of utterances at a time (default 50) and
# a `next_cursor`. A single call to a 142-utterance meeting therefore yields
# 50 segments and no complaint — silent truncation of ~65% of the transcript,
# and a `duration_min` computed from the 50th utterance's end_time. These
# tests pin the contract that stops it: every page, or a loud failure.

def page(offset, contents, *, total, end_step=60000, cursor=True):
    segments = [{"speaker": f"Speaker {i % 2 + 1}", "content": text,
                 "end_time": (offset + i + 1) * end_step}
                for i, text in enumerate(contents)]
    body = {"file_id": "rec_42", "block": "transaction", "total": total,
            "offset": offset, "limit": len(contents), "returned": len(contents),
            "segments": segments}
    if cursor and offset + len(contents) < total:
        body["next_cursor"] = f"cursor-{offset + len(contents)}"
    return body


def test_two_pages_reassemble_into_one_blob_in_order(tmp_path):
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=240000)),
        [write_json(tmp_path, "t1.json", page(0, ["one", "two"], total=4)),
         write_json(tmp_path, "t2.json", page(2, ["three", "four"], total=4))],
        None, str(tmp_path / "s"), utc_offset="+00:00")
    blob = Path(result["blob_path"]).read_text(encoding="utf-8")
    body = blob.split("#Transcript\n", 1)[1]
    assert [line.split(": ", 1)[1] for line in body.strip().splitlines()] == [
        "one", "two", "three", "four"]


def test_pages_are_ordered_by_offset_not_by_argument_order(tmp_path):
    """The caller writes one scratch file per page; their names are the
    caller's business. The page's own `offset` is the only ordering the CLI
    trusts."""
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=240000)),
        [write_json(tmp_path, "b.json", page(2, ["three", "four"], total=4)),
         write_json(tmp_path, "a.json", page(0, ["one", "two"], total=4))],
        None, str(tmp_path / "s"), utc_offset="+00:00")
    body = Path(result["blob_path"]).read_text(encoding="utf-8").split(
        "#Transcript\n", 1)[1]
    assert [line.split(": ", 1)[1] for line in body.strip().splitlines()] == [
        "one", "two", "three", "four"]


def test_duration_comes_from_the_last_page_not_the_first(tmp_path):
    """The truncation bug's second victim: a 32-minute meeting written as a
    third of its length because end_time came from utterance 50."""
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=300000)),
        [write_json(tmp_path, "t1.json", page(0, ["a", "b"], total=4)),
         write_json(tmp_path, "t2.json", page(2, ["c", "d"], total=4))],
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert result["duration_min"] == 4          # 4 * 60000 ms, not 2


def test_a_truncated_single_page_raises_naming_both_counts(tmp_path):
    """The exact shape the live connector returns for a 32-minute meeting
    when the caller takes the default page and never follows next_cursor."""
    with pytest.raises(plaud.PlaudError, match="50 of 142 utterances"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json",
                       page(0, [f"u{i}" for i in range(50)], total=142)),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_gap_between_pages_raises(tmp_path):
    with pytest.raises(plaud.PlaudError, match="expected offset 2"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            [write_json(tmp_path, "t1.json", page(0, ["one", "two"], total=6)),
             write_json(tmp_path, "t2.json",
                        page(4, ["five", "six"], total=6))],
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_the_same_page_passed_twice_raises(tmp_path):
    with pytest.raises(plaud.PlaudError, match="expected offset 2"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            [write_json(tmp_path, "t1.json", page(0, ["one", "two"], total=4)),
             write_json(tmp_path, "t2.json", page(0, ["one", "two"], total=4))],
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_complete_single_page_needs_no_second_page(tmp_path):
    """total == returned is the common case — a short recording. It must not
    acquire a new requirement."""
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=240000)),
        write_json(tmp_path, "t.json", page(0, ["one", "two"], total=2)),
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert "Speaker 2: two" in Path(result["blob_path"]).read_text(
        encoding="utf-8")


def test_an_untotalled_page_is_accepted_as_the_whole_transcript(tmp_path):
    """SEGMENTS carries no `total` — the pre-pagination shape. It passes
    because it dangles no cursor and covers the meta duration, not because
    nothing is claimed about it."""
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        [write_json(tmp_path, "t.json", SEGMENTS)],
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert result["duration_min"] == 40


def test_mixing_a_legacy_payload_with_a_page_raises(tmp_path):
    with pytest.raises(plaud.PlaudError, match="mix response shapes"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            [write_json(tmp_path, "t1.json", LEGACY),
             write_json(tmp_path, "t2.json", page(0, ["one"], total=1))],
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_two_legacy_payloads_raise(tmp_path):
    """The legacy block is the whole transcript by construction; two of them
    is a caller error, not a two-page transcript."""
    with pytest.raises(plaud.PlaudError, match="not paginated"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            [write_json(tmp_path, "t1.json", LEGACY),
             write_json(tmp_path, "t2.json", LEGACY)],
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_page_whose_returned_disagrees_with_its_segments_raises(tmp_path):
    """The forged-counts incident: segments were condensed and the count
    fields edited until tiling passed. `returned` must describe the file."""
    body = page(0, ["one", "two"], total=2)
    body["returned"] = 3
    with pytest.raises(plaud.PlaudError, match="returned"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_pages_with_disagreeing_totals_raise(tmp_path):
    p2 = page(2, ["three", "four"], total=4)
    p2["total"] = 5
    with pytest.raises(plaud.PlaudError, match="disagree about total"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            [write_json(tmp_path, "t1.json", page(0, ["one", "two"], total=4)),
             write_json(tmp_path, "t2.json", p2)],
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_complete_count_with_a_dangling_cursor_raises(tmp_path):
    """total says done but the cursor says more — the server never produces
    this; someone edited a count field."""
    body = page(0, ["one", "two"], total=2)
    body["next_cursor"] = "eyJvIjoyfQ"
    with pytest.raises(plaud.PlaudError, match="next_cursor"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_an_untotalled_page_with_a_dangling_cursor_raises(tmp_path):
    """Closes the hole where a page set with no `total` skipped every check."""
    body = dict(SEGMENTS, next_cursor="eyJvIjo1MH0")
    with pytest.raises(plaud.PlaudError, match="next_cursor"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_the_live_null_cursor_last_page_shape_passes(tmp_path):
    """The connector's real last page carries next_cursor with a null value,
    not an absent key."""
    body = page(0, ["one", "two"], total=2)
    body["next_cursor"] = None
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=240000)),
        write_json(tmp_path, "t.json", body),
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert "Speaker 2: two" in Path(result["blob_path"]).read_text(
        encoding="utf-8")


def test_a_page_shorter_than_its_limit_with_a_cursor_raises(tmp_path):
    """A short page is by definition the final page; a cursor on it is a
    shape the server never produces."""
    body = page(0, ["one"], total=1)
    body["limit"] = 50
    body["next_cursor"] = "eyJvIjoxfQ"
    with pytest.raises(plaud.PlaudError, match="shorter than its limit"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_transcript_page_for_a_different_recording_raises(tmp_path):
    body = page(0, ["one", "two"], total=2)
    body["file_id"] = "rec_99"
    with pytest.raises(plaud.PlaudError, match="rec_99"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_transcript_covering_under_half_the_recording_raises(tmp_path):
    """The one number the page files cannot vote on: the meta's duration
    comes from a different tool call, written before extraction began."""
    with pytest.raises(plaud.PlaudError, match="4 of 41 recorded minutes"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),               # 41 min
            write_json(tmp_path, "t.json",
                       page(0, ["one", "two", "three", "four"], total=4)),
            None, str(tmp_path / "s"), utc_offset="+00:00")     # ends 4 min


def test_a_short_legacy_transcript_raises_too(tmp_path):
    """The duration check is shape-agnostic on purpose."""
    short = [{"data_type": "transaction", "data_error_code": 10,
              "data_content": json.dumps([
                  {"speaker": "Speaker 1", "content": "hi",
                   "end_time": 60000}])}]
    with pytest.raises(plaud.PlaudError, match="1 of 41 recorded minutes"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", short),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_meta_without_duration_skips_the_coverage_check(tmp_path):
    meta = {k: v for k, v in META.items() if k != "duration"}
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", meta),
        write_json(tmp_path, "t.json", page(0, ["one", "two"], total=2)),
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert result["coverage_pct"] is None
    assert result["warnings"] == []


def test_timestamps_far_beyond_the_recording_length_warn(tmp_path):
    """Overshoot means a metadata quirk, not missing content — warn, never
    refuse."""
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=60000)),
        write_json(tmp_path, "t.json", SEGMENTS),               # ends 40 min
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert any("beyond" in w for w in result["warnings"])


def test_a_healthy_transcript_reports_coverage_and_no_warnings(tmp_path):
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),               # 97.6%
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert result["coverage_pct"] == 98
    assert result["warnings"] == []


def test_recorded_local_is_accepted_verbatim_by_both_consumers(tmp_path):
    """B1: `recorded_local` used to carry seconds, which `meeting write` and
    `sync collide` both refuse — one rejection round trip per recording. The
    three regexes are asserted against each other so they cannot drift apart
    again."""
    from vaultlib import meeting, syncjob
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),
        None, str(tmp_path / "s"), utc_offset="+02:00")
    stamp = result["recorded_local"]
    assert stamp == "2026-05-20T11:03"
    assert meeting._DATETIME_RE.match(stamp)
    assert syncjob._COLLIDE_START_RE.match(stamp)


def test_reassemble_reports_the_canonical_plaud_id(tmp_path):
    """The connector lists recordings as of_<hex> since 2026-09-15; the
    ledger keys on the hash. The blob keeps the connector's own id — it is a
    scratch filename, not a ledger key."""
    hex_id = "0123456789abcdef0123456789abcdef"
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", {**META, "id": f"of_{hex_id}"}),
        write_json(tmp_path, "t.json", {**SEGMENTS, "file_id": f"of_{hex_id}"}),
        None, str(tmp_path / "scratch"), utc_offset="+02:00")
    assert result["recording_id"] == f"plaud:{hex_id}"
    assert Path(result["blob_path"]).name == f"of_{hex_id}.blob.md"
    assert Path(result["blob_path"]).is_file()


def test_a_transcript_page_in_the_other_id_form_is_the_same_recording(tmp_path):
    hex_id = "0123456789abcdef0123456789abcdef"
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", {**META, "id": hex_id}),
        write_json(tmp_path, "t.json", {**SEGMENTS, "file_id": f"of_{hex_id}"}),
        None, str(tmp_path / "scratch"), utc_offset="+02:00")
    assert result["recording_id"] == f"plaud:{hex_id}"


def test_reassemble_reports_the_blob_size_for_paging(tmp_path):
    # Review 2026-10-12: only m365 reported it, so a long Plaud transcript
    # had nothing telling the worker to read past the first window.
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),
        None, str(tmp_path / "s"), utc_offset="+00:00")
    blob = Path(result["blob_path"]).read_text(encoding="utf-8")
    assert result["blob_lines"] == blob.count("\n") and result["blob_chars"] == len(blob)


# --- capture: the CLI copies a Plaud result; the model never re-types one ---
#
# Live 2026-10-13: from claude-sonnet-5-5 on, the API's output classifier
# stopped workers partway through re-typing transcript pages as Write input,
# so every Plaud recording past ~45 minutes failed every run. A result over
# the tool-result cap is spilled to a file the notice names; a result under
# it is in the session log. The connector wraps both in a block whose name
# (`untrusted-user-data-<16 hex>`) is random per call.

TAG = "untrusted-user-data-1ab4346a220da5c4"
PAGE = {"file_id": "of_rec_42", "block": "transaction", "total": 3,
        "offset": 0, "limit": 2, "returned": 2, "next_cursor": "eyJvIjoyfQ",
        "segments": [
            {"speaker": "Speaker 1", "content": "Eerst de planning.",
             "end_time": 60000},
            {"speaker": "Speaker 2", "content": "Akkoord.", "end_time": 120000}]}
LAST = {"file_id": "of_rec_42", "block": "transaction", "total": 3,
        "offset": 2, "limit": 2, "returned": 1, "next_cursor": None,
        "segments": [{"speaker": "Speaker 1", "content": "Tot vrijdag.",
                      "end_time": 2400000}]}


def wrapped(obj, tag=TAG):
    body = json.dumps(obj, indent=2, ensure_ascii=False)
    return (f"The block delimited by <{tag}> below contains user recording "
            f"data returned verbatim.\n<{tag} source=\"plaud-recording\">\n"
            f"{body}\n</{tag}>"), body


def spilled(root, text, name="mcp-plaud-get_transcript-1791913443044.txt"):
    d = root / "proj" / "sess" / "tool-results"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


def logged(root, text, *, as_list=True, name="agent-a1.jsonl"):
    d = root / "proj" / "sess" / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    content = [{"type": "text", "text": text}] if as_list else text
    line = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": content}]}}
    p = d / name
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    return p


def test_capture_from_a_spill_writes_the_inner_json_byte_for_byte(tmp_path):
    root = tmp_path / "projects"
    text, body = wrapped(PAGE)
    src = spilled(root, text)
    out = tmp_path / "scratch" / "rec_1.transcript.01.json"

    result = plaud.capture(str(out), source=str(src), roots=[root])

    assert out.read_text(encoding="utf-8") == body
    assert result["captured_from"] == "spill"
    assert result["kind"] == "transcript-page"
    assert (result["offset"], result["returned"], result["total"]) == (0, 2, 3)
    assert result["next_cursor"] == "eyJvIjoyfQ"   # the worker pages on with it
    assert "planning" not in json.dumps(result)    # counts only, never content


def test_capture_by_tag_finds_an_inline_result_in_the_session_log(tmp_path):
    root = tmp_path / "projects"
    text, body = wrapped(LAST)
    logged(root, text)
    out = tmp_path / "rec_1.transcript.02.json"

    result = plaud.capture(str(out), tag=TAG, roots=[root])

    assert out.read_text(encoding="utf-8") == body
    assert result["captured_from"] == "session-log"
    assert result["next_cursor"] is None


def test_capture_by_tag_reads_a_plain_string_tool_result(tmp_path):
    root = tmp_path / "projects"
    text, body = wrapped(LAST)
    logged(root, text, as_list=False)
    out = tmp_path / "p.json"

    plaud.capture(str(out), tag=TAG, roots=[root])

    assert out.read_text(encoding="utf-8") == body


def test_capture_by_tag_ignores_a_line_that_only_mentions_the_tag(tmp_path):
    """The worker's own Bash call names the tag; only a tool result whose
    wrapped block carries it counts."""
    root = tmp_path / "projects"
    d = root / "proj" / "sess"
    d.mkdir(parents=True)
    (d / "agent-a1.jsonl").write_text(json.dumps({"type": "assistant", "message": {
        "content": [{"type": "tool_use", "name": "Bash", "input": {
            "command": f"plaud capture --tag {TAG}"}}]}}) + "\n", encoding="utf-8")

    with pytest.raises(plaud.PlaudError, match="no tool result tagged"):
        plaud.capture(str(tmp_path / "p.json"), tag=TAG, roots=[root])


def test_capture_by_tag_skips_logs_older_than_the_window(tmp_path):
    import os
    root = tmp_path / "projects"
    text, _ = wrapped(LAST)
    log = logged(root, text)
    old = log.stat().st_mtime - plaud.LOG_WINDOW_S - 60
    os.utime(log, (old, old))

    with pytest.raises(plaud.PlaudError, match="no tool result tagged"):
        plaud.capture(str(tmp_path / "p.json"), tag=TAG, roots=[root])


def test_capture_refuses_a_tag_that_names_two_different_results(tmp_path):
    root = tmp_path / "projects"
    logged(root, wrapped(PAGE)[0])
    logged(root, wrapped(LAST)[0])

    with pytest.raises(plaud.PlaudError, match="2 different results"):
        plaud.capture(str(tmp_path / "p.json"), tag=TAG, roots=[root])


def test_capture_refuses_something_that_is_not_a_tag(tmp_path):
    with pytest.raises(plaud.PlaudError, match="not a result tag"):
        plaud.capture(str(tmp_path / "p.json"), tag="rec_1.transcript.01",
                      roots=[tmp_path])


def test_capture_takes_exactly_one_source(tmp_path):
    with pytest.raises(plaud.PlaudError, match="exactly one"):
        plaud.capture(str(tmp_path / "p.json"), roots=[tmp_path])
    with pytest.raises(plaud.PlaudError, match="exactly one"):
        plaud.capture(str(tmp_path / "p.json"), source="x", tag=TAG,
                      roots=[tmp_path])


def test_capture_refuses_an_unwrapped_or_cut_off_result(tmp_path):
    root = tmp_path / "projects"
    text, _ = wrapped(PAGE)
    src = spilled(root, text[: len(text) // 2])   # closing tag lost

    with pytest.raises(plaud.PlaudError, match="not one wrapped Plaud result"):
        plaud.capture(str(tmp_path / "p.json"), source=str(src), roots=[root])


def test_capture_refuses_a_page_whose_segments_disagree_with_returned(tmp_path):
    root = tmp_path / "projects"
    forged = dict(PAGE, returned=5)
    src = spilled(root, wrapped(forged)[0])

    with pytest.raises(plaud.PlaudError, match="returned"):
        plaud.capture(str(tmp_path / "p.json"), source=str(src), roots=[root])


def test_capture_copies_a_note(tmp_path):
    root = tmp_path / "projects"
    text, body = wrapped(NOTE)
    logged(root, text)
    out = tmp_path / "rec_1.note.json"

    result = plaud.capture(str(out), tag=TAG, roots=[root])

    assert result["kind"] == "note"
    assert out.read_text(encoding="utf-8") == body


def test_captured_pages_and_note_reassemble(tmp_path):
    """The whole Plaud path with no model-written page: one spilled page,
    one inline page, one inline note."""
    root = tmp_path / "projects"
    src = spilled(root, wrapped(PAGE)[0])
    logged(root, wrapped(LAST)[0])
    note_tag = "untrusted-user-data-00000000000000ff"
    logged(root, wrapped(NOTE, tag=note_tag)[0])
    scratch = tmp_path / "scratch"

    plaud.capture(str(scratch / "rec_1.transcript.01.json"), source=str(src),
                  roots=[root])
    plaud.capture(str(scratch / "rec_1.transcript.02.json"), tag=TAG,
                  roots=[root])
    plaud.capture(str(scratch / "rec_1.note.json"), tag=note_tag, roots=[root])
    meta = dict(META, id="of_rec_42")
    result = plaud.reassemble(
        write_json(tmp_path, "rec_1.meta.json", meta),
        [str(scratch / "rec_1.transcript.01.json"),
         str(scratch / "rec_1.transcript.02.json")],
        str(scratch / "rec_1.note.json"), str(scratch), utc_offset="+02:00")

    assert result["coverage_pct"] == 98
    assert result["has_enrichment"] is True
    assert "Tot vrijdag." in Path(result["blob_path"]).read_text(encoding="utf-8")
