"""Prompt-safe scratch-directory hygiene.

`rm -f "$SCRATCH"/rec_*.json ...` is a Bash builtin with a glob the
permission system can flag mid-run — issue #95 traced a 52-minute unattended
hang straight to that command. `scratch sweep` replaces it with a
stdlib-only, pattern-limited delete that lives behind the same `python3
"$VAULTLIB" ...` prefix every other unattended call already uses, so one
narrow pre-approval covers it too.
"""
from pathlib import Path

import pytest

from vaultlib import scratch


def test_sweep_deletes_only_known_patterns(tmp_path):
    (tmp_path / "plaud.whoami.json").write_text("{}", encoding="utf-8")
    (tmp_path / "m365.whoami.json").write_text("{}", encoding="utf-8")
    (tmp_path / "rec_42.meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "rec_42.transcript.01.json").write_text("{}", encoding="utf-8")
    (tmp_path / "plaud.list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "m365_events.json").write_text("[]", encoding="utf-8")
    (tmp_path / "rec_42.blob.md").write_text("# blob", encoding="utf-8")
    (tmp_path / "ids.json").write_text("[]", encoding="utf-8")
    (tmp_path / "rec_42.payload.json").write_text("{}", encoding="utf-8")
    (tmp_path / "daily-note.payload.json").write_text("{}", encoding="utf-8")
    (tmp_path / "decision.json").write_text("{}", encoding="utf-8")
    # Not a sweep pattern — must survive.
    keep = tmp_path / "notes.txt"
    keep.write_text("keep me", encoding="utf-8")

    result = scratch.sweep(str(tmp_path))

    assert keep.is_file()
    assert keep.name not in result["deleted"]
    for name in ("plaud.whoami.json", "m365.whoami.json", "rec_42.meta.json",
                 "rec_42.transcript.01.json", "plaud.list.json",
                 "m365_events.json", "rec_42.blob.md", "ids.json",
                 "rec_42.payload.json", "daily-note.payload.json",
                 "decision.json"):
        assert not (tmp_path / name).exists(), f"{name} should have been swept"
        assert name in result["deleted"]


def test_sweep_covers_project_qualified_decision_payloads(tmp_path):
    # /log-decision qualifies the payload filename with the project slug so
    # concurrent evening-sync subagents cannot race on one shared file. The
    # qualified names must still be swept — a decision payload can carry
    # confidential meeting content and must never outlive the run.
    for name in ("decision.json",
                 "decision-meridian-yard-automation-program.json",
                 "decision-atlas-vendor-consolidation.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    result = scratch.sweep(str(tmp_path))

    for name in ("decision.json",
                 "decision-meridian-yard-automation-program.json",
                 "decision-atlas-vendor-consolidation.json"):
        assert not (tmp_path / name).exists(), f"{name} should have been swept"
        assert name in result["deleted"]


def test_sweep_covers_worker_qualified_payload_names(tmp_path):
    # Workers key payload files by their briefing's scratch stem, never the
    # meeting-note stem (two workers syncing one meeting from two sources
    # derive the same note stem and would race on a shared file, per
    # worker-contract.md). The qualified names must still match the sweep.
    names = ("rec_3.payload.json", "m365_event_7.payload.json",
             "REC-2026-0520-1103.payload.json")
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")

    result = scratch.sweep(str(tmp_path))

    for name in names:
        assert not (tmp_path / name).exists(), f"{name} should have been swept"
        assert name in result["deleted"]


def test_sweep_covers_the_session_1_onboarding_files(tmp_path):
    # /setup-my-brain writes these during the live interview; its deletion
    # points are the same full sweep, so they must be in the pattern list.
    for name in ("sentmail.sample.json", "calendar.next-two-weeks.json",
                 "identity.block.md", "communication-style.block.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    result = scratch.sweep(str(tmp_path))

    for name in ("sentmail.sample.json", "calendar.next-two-weeks.json",
                 "identity.block.md", "communication-style.block.md"):
        assert not (tmp_path / name).exists(), f"{name} should have been swept"
        assert name in result["deleted"]


def test_sweep_is_idempotent_on_an_already_clean_directory(tmp_path):
    result = scratch.sweep(str(tmp_path))
    assert result["deleted"] == []
    assert result["skipped"] == []


def test_sweep_refuses_a_missing_directory(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(scratch.ScratchError, match="does not exist"):
        scratch.sweep(str(missing))


def test_sweep_refuses_a_file_given_as_dir(tmp_path):
    a_file = tmp_path / "not-a-dir.json"
    a_file.write_text("{}", encoding="utf-8")
    with pytest.raises(scratch.ScratchError, match="does not exist"):
        scratch.sweep(str(a_file))


def test_sweep_never_descends_into_subdirectories(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    trap = nested / "ids.json"
    trap.write_text("[]", encoding="utf-8")

    result = scratch.sweep(str(tmp_path))

    assert trap.is_file()
    assert result["deleted"] == []


def test_sweep_reports_a_directory_matching_a_pattern_as_skipped_not_deleted(tmp_path):
    # A directory happens to be named like a swept pattern — never rm -rf it.
    trap_dir = tmp_path / "ids.json"
    trap_dir.mkdir()

    result = scratch.sweep(str(tmp_path))

    assert trap_dir.is_dir()
    assert "ids.json" in result["skipped"]
    assert "ids.json" not in result["deleted"]


def test_sweep_expands_user_and_resolves(tmp_path):
    result = scratch.sweep(str(tmp_path) + "/")
    assert result["dir"] == str(tmp_path.resolve())


def test_sweep_covers_the_fetch_error_batch(tmp_path):
    # Review 2026-10-12: /sync-recordings names this file, and it matched no
    # pattern, so it outlived every run.
    (tmp_path / "fetch_errors_batch.json").write_text("[]", encoding="utf-8")
    result = scratch.sweep(str(tmp_path))
    assert "fetch_errors_batch.json" in result["deleted"]
