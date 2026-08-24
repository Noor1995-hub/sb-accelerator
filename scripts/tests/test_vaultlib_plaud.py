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
    assert result["recorded_local"] == "2026-05-20 11:03:00"
    assert result["has_enrichment"] is True
    blob = Path(result["blob_path"]).read_text(encoding="utf-8")
    assert blob.splitlines()[0] == "Vendor strategy walk-through"
    assert "> Recorded: 2026-05-20 11:03:00" in blob
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
    assert "> Recorded: 2026-05-20 09:03:00" in blob


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
