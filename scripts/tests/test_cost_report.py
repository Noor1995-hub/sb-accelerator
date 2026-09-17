"""cost_report.py: sums a session export's message.usage (max per
message.id, since a message repeats once per content-block line) and
prices it at list rate per model family.

Fixture is synthetic (built in tmp_path, never real session data — see
CLAUDE.md's clean-room rule): one main transcript.jsonl with two lines
sharing a message id (each line carries a different partial usage — the
max across keys must win, not the max of any single line), and one
subagent with its meta.json.
"""
import json
import zipfile
from pathlib import Path

import pytest

import cost_report


def _write_jsonl(path: Path, records: list) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8", newline="\n"
    )


def make_export(root: Path) -> None:
    """A tiny synthetic session export: main transcript + one subagent."""
    _write_jsonl(
        root / "transcript.jsonl",
        [
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "model": "claude-sonnet-4-5-20250929",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "model": "claude-sonnet-4-5-20250929",
                    "usage": {
                        "input_tokens": 60,
                        "output_tokens": 80,
                        "cache_read_input_tokens": 20,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ],
    )
    (root / "metadata.json").write_text(
        json.dumps({"sessionId": "sess-fixture"}), encoding="utf-8", newline="\n"
    )
    subagents_dir = root / "sess-fixture" / "subagents"
    subagents_dir.mkdir(parents=True)
    _write_jsonl(
        subagents_dir / "agent-abc123.jsonl",
        [
            {
                "type": "assistant",
                "message": {
                    "id": "msg_2",
                    "model": "claude-haiku-4-5-20250929",
                    "usage": {
                        "input_tokens": 50,
                        "output_tokens": 30,
                        "cache_read_input_tokens": 10,
                        "cache_creation_input_tokens": 5,
                    },
                },
            }
        ],
    )
    (subagents_dir / "agent-abc123.meta.json").write_text(
        json.dumps(
            {
                "agentType": "second-brain:sync-worker",
                "description": "Sync worker: fixture recording",
            }
        ),
        encoding="utf-8",
        newline="\n",
    )


# Expected costs at default list prices, computed by hand from the fixture
# above so the test is an independent check on cost_report's arithmetic.
MAIN_COST = (100 * 3 + 80 * 15 + 20 * 0.30 + 0 * 3.75) / 1_000_000  # 0.001506
SUB_COST = (50 * 1 + 30 * 5 + 10 * 0.10 + 5 * 1.25) / 1_000_000  # 0.00020725


def test_max_per_message_id_wins_independently_per_key(tmp_path):
    make_export(tmp_path)
    pricing = cost_report.load_pricing(None)
    report = cost_report.build_report(tmp_path, pricing)

    assert len(report["rows"]) == 2
    main_row, sub_row = report["rows"]

    assert main_row["agent_type"] == "main"
    assert main_row["requests"] == 1
    assert main_row["input_tokens"] == 100  # max(100, 60)
    assert main_row["output_tokens"] == 80  # max(50, 80)
    assert main_row["cache_read_input_tokens"] == 20  # max(0, 20)
    assert main_row["cache_creation_input_tokens"] == 0
    assert main_row["cost"] == pytest.approx(MAIN_COST)

    assert sub_row["agent_type"] == "second-brain:sync-worker"
    assert sub_row["description"] == "Sync worker: fixture recording"
    assert sub_row["requests"] == 1
    assert sub_row["output_tokens"] == 30
    assert sub_row["cache_read_input_tokens"] == 10
    assert sub_row["cache_creation_input_tokens"] == 5
    assert sub_row["cost"] == pytest.approx(SUB_COST)

    assert report["warnings"] == []


def test_totals_by_type_and_grand_total(tmp_path):
    make_export(tmp_path)
    pricing = cost_report.load_pricing(None)
    report = cost_report.build_report(tmp_path, pricing)

    totals = report["totals_by_type"]
    assert set(totals) == {"main", "second-brain:sync-worker"}
    assert totals["main"]["cost"] == pytest.approx(MAIN_COST)
    assert totals["second-brain:sync-worker"]["cost"] == pytest.approx(SUB_COST)

    grand = report["grand_total"]
    assert grand["requests"] == 2
    assert grand["output_tokens"] == 110
    assert grand["cache_read_input_tokens"] == 30
    assert grand["cache_creation_input_tokens"] == 5
    assert grand["cost"] == pytest.approx(MAIN_COST + SUB_COST)


def test_unknown_model_falls_back_to_sonnet_with_warning(tmp_path):
    _write_jsonl(
        tmp_path / "transcript.jsonl",
        [
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "model": "claude-mystery-9000",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 10,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        ],
    )
    pricing = cost_report.load_pricing(None)
    report = cost_report.build_report(tmp_path, pricing)

    expected_cost = (10 * 3 + 10 * 15) / 1_000_000  # priced as sonnet
    assert report["rows"][0]["cost"] == pytest.approx(expected_cost)
    assert len(report["warnings"]) == 1
    assert "claude-mystery-9000" in report["warnings"][0]


def test_pricing_override_changes_cost(tmp_path):
    make_export(tmp_path)
    override = tmp_path / "prices.json"
    override.write_text(json.dumps({"sonnet": {"out": 30.0}}), encoding="utf-8")

    pricing = cost_report.load_pricing(override)
    report = cost_report.build_report(tmp_path, pricing)

    new_main_cost = (100 * 3 + 80 * 30 + 20 * 0.30 + 0 * 3.75) / 1_000_000
    assert report["rows"][0]["cost"] == pytest.approx(new_main_cost)
    # haiku pricing untouched
    assert report["rows"][1]["cost"] == pytest.approx(SUB_COST)


def test_export_root_accepts_a_zip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_export(src)

    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src))

    pricing = cost_report.load_pricing(None)
    with cost_report.export_root(zip_path) as root:
        report = cost_report.build_report(root, pricing)

    assert len(report["rows"]) == 2
    assert report["grand_total"]["cost"] == pytest.approx(MAIN_COST + SUB_COST)


def test_is_safe_zip_member_rejects_traversal_and_absolute_paths(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    assert cost_report._is_safe_zip_member("transcript.jsonl", dest) is True
    assert cost_report._is_safe_zip_member("sub/dir/file.json", dest) is True
    assert cost_report._is_safe_zip_member("../evil.txt", dest) is False
    assert cost_report._is_safe_zip_member("../../evil.txt", dest) is False
    assert cost_report._is_safe_zip_member("/etc/passwd", dest) is False


def test_export_root_rejects_a_zip_slip_member(tmp_path, monkeypatch, capsys):
    """A crafted export.zip carrying a `../evil.txt` member must not write
    outside the extraction directory — extraction skips it (with a
    warning) rather than raising, so a poisoned member doesn't block
    reading the rest of a legitimate export."""
    # Redirect tempfile's default directory into tmp_path: if the zip-slip
    # guard ever regresses, the escape lands inside pytest's own tmp_path
    # instead of the real system temp directory.
    sandbox = tmp_path / "tmproot"
    sandbox.mkdir()
    monkeypatch.setattr(cost_report.tempfile, "tempdir", str(sandbox))

    zip_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("transcript.jsonl", "")
        zf.writestr("../evil.txt", "pwned")

    with cost_report.export_root(zip_path) as root:
        assert (root / "transcript.jsonl").exists()

    assert list(sandbox.rglob("evil.txt")) == []
    assert "evil.txt" in capsys.readouterr().err


def test_missing_transcript_raises(tmp_path):
    pricing = cost_report.load_pricing(None)
    with pytest.raises(FileNotFoundError):
        with cost_report.export_root(tmp_path) as root:
            cost_report.build_report(root, pricing)


def test_cli_prints_table_and_json(tmp_path, capsys):
    make_export(tmp_path)
    exit_code = cost_report.main([str(tmp_path), "--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "second-brain:sync-worker" in out
    assert "GRAND TOTAL" in out

    # The JSON blob is the last thing printed; parse from its opening brace.
    json_start = out.index("{")
    payload = json.loads(out[json_start:])
    assert payload["grand_total"]["requests"] == 2
    assert payload["grand_total"]["cost"] == pytest.approx(MAIN_COST + SUB_COST)


def test_format_table_contains_no_input_tokens_column_but_costs_use_it(tmp_path):
    """The brief's table spec omits an input-tokens column (agentType,
    description, requests, out, cache-read, cache-write, $) even though
    input tokens feed the cost math — this pins that column set."""
    make_export(tmp_path)
    pricing = cost_report.load_pricing(None)
    report = cost_report.build_report(tmp_path, pricing)
    table = cost_report.format_table(report)
    header_line = table.splitlines()[0]
    assert "input" not in header_line.lower()
    for column in ("agentType", "description", "reqs", "out", "cache_read", "cache_write"):
        assert column in header_line


def test_format_table_renders_correct_cell_values_for_main_row(tmp_path):
    """format_table() isn't just a header pin — the numbers in a rendered
    row must match build_report()'s numbers for the fixture. The main
    row's description is empty, so whitespace-splitting the line is
    unambiguous (agentType, reqs, out, cache_read, cache_write, cost)."""
    make_export(tmp_path)
    pricing = cost_report.load_pricing(None)
    report = cost_report.build_report(tmp_path, pricing)
    table = cost_report.format_table(report)

    lines = table.splitlines()
    main_line = lines[2]  # 0: header, 1: separator, 2: main row
    tokens = main_line.split()

    assert tokens[0] == "main"
    assert tokens[1] == "1"  # requests
    assert tokens[2] == "80"  # output_tokens
    assert tokens[3] == "20"  # cache_read_input_tokens
    assert tokens[4] == "0"  # cache_creation_input_tokens
    assert float(tokens[5]) == pytest.approx(MAIN_COST, abs=1e-4)
