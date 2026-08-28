"""The append-only routine-run log.

An unattended run's only trace is its summary text, which nobody reads
unless something already looks wrong — and `--unattended` exiting 0 having
done nothing is silent by construction. `runlog append` gives every run,
including a no-op one, exactly one line where a human looks.
"""
from pathlib import Path

import pytest

from vaultlib import runlog

from test_vaultlib_vault import make_vault


def test_append_creates_the_log_dir_and_file(tmp_path):
    root = make_vault(tmp_path)
    log_path = root / "99-workflow-config" / "logs" / "routine-runs.log"
    assert not log_path.exists()

    result = runlog.append(root, "evening-sync", "wrote 60-daily-notes/2026-08-29.md")

    assert log_path.is_file()
    assert result["path"] == "99-workflow-config/logs/routine-runs.log"


def test_append_writes_one_line_with_timestamp_routine_and_outcome(tmp_path):
    root = make_vault(tmp_path)
    runlog.append(root, "evening-sync", "wrote 60-daily-notes/2026-08-29.md")
    log_path = root / "99-workflow-config" / "logs" / "routine-runs.log"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    stamp, routine, outcome = lines[0].split("\t", 2)
    assert stamp.endswith("Z")
    assert routine == "evening-sync"
    assert outcome == "wrote 60-daily-notes/2026-08-29.md"


def test_append_is_append_only_across_multiple_runs(tmp_path):
    root = make_vault(tmp_path)
    runlog.append(root, "evening-sync", "first run")
    runlog.append(root, "sync-recordings", "second run: nothing to do")
    log_path = root / "99-workflow-config" / "logs" / "routine-runs.log"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("first run")
    assert lines[1].endswith("second run: nothing to do")


def test_append_records_the_nothing_to_do_outcome(tmp_path):
    root = make_vault(tmp_path)
    runlog.append(root, "sync-recordings", "nothing to do: inbox empty, no new recordings")
    log_path = root / "99-workflow-config" / "logs" / "routine-runs.log"
    assert "nothing to do" in log_path.read_text(encoding="utf-8")


def test_append_collapses_embedded_newlines_to_keep_one_line_per_entry(tmp_path):
    root = make_vault(tmp_path)
    runlog.append(root, "evening-sync", "line one\nline two")
    log_path = root / "99-workflow-config" / "logs" / "routine-runs.log"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "line one line two" in lines[0]


def test_append_rejects_an_empty_outcome(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(runlog.RunLogError, match="outcome"):
        runlog.append(root, "evening-sync", "   ")


def test_append_rejects_a_non_kebab_routine_name(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(runlog.RunLogError, match="routine"):
        runlog.append(root, "Evening Sync!", "did a thing")
