"""sync scan/dedup/skip: the vault is the ledger, keyed on namespaced
source-recording-id. Errors are simply not recorded — a failed item has no id
in the vault and reappears next run."""
from pathlib import Path

import pytest

from vaultlib import syncjob


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "10-inbox").mkdir()
    (tmp_path / "20-meetings").mkdir()
    return tmp_path


def write_meeting(root: Path, stem: str, recording_id: str | None) -> None:
    lines = ["---", "date: 2026-08-20T10:00", "type: meeting"]
    if recording_id:
        lines.append(f"source-recording-id: {recording_id}")
    lines += ["---", "", "## Key Takeaways", "- x"]
    (root / "20-meetings" / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")


def test_content_id_is_stable_and_namespaced(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello transcript", encoding="utf-8")
    first = syncjob.content_id(f)
    assert first.startswith("inbox:") and len(first) == len("inbox:") + 16
    assert syncjob.content_id(f) == first


def test_scan_partitions_new_synced_and_skipped(tmp_path):
    root = make_vault(tmp_path)
    new = root / "10-inbox" / "fresh.txt"
    new.write_text("brand new transcript", encoding="utf-8")
    done = root / "10-inbox" / "done.txt"
    done.write_text("already processed transcript", encoding="utf-8")
    write_meeting(root, "20-08-26-old-sync", syncjob.content_id(done))
    skipped = root / "10-inbox" / "noise.txt"
    skipped.write_text("pocket recording", encoding="utf-8")
    syncjob.skip(root, syncjob.content_id(skipped))

    result = syncjob.scan(root)
    names = {c["name"] for c in result["candidates"]}
    assert names == {"fresh.txt"}
    assert result["candidates"][0]["recording_id"] == syncjob.content_id(new)
    assert result["already_synced"][0]["name"] == "done.txt"
    assert result["already_synced"][0]["synced_as"] == "20-meetings/20-08-26-old-sync.md"
    assert result["skipped"][0]["name"] == "noise.txt"


def test_scan_ignores_readme_and_hidden_files(tmp_path):
    root = make_vault(tmp_path)
    (root / "10-inbox" / "README.md").write_text("# Inbox", encoding="utf-8")
    (root / "10-inbox" / ".DS_Store").write_bytes(b"\x00")
    result = syncjob.scan(root)
    assert result["candidates"] == []


def test_scan_reports_unparseable_meeting_and_continues(tmp_path):
    root = make_vault(tmp_path)
    (root / "20-meetings" / "broken.md").write_text("no frontmatter here",
                                                    encoding="utf-8")
    (root / "10-inbox" / "a.txt").write_text("t", encoding="utf-8")
    result = syncjob.scan(root)
    assert len(result["candidates"]) == 1
    assert any("broken.md" in w for w in result["warnings"])


def test_dedup_filters_against_ledger_and_skiplist(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "19-08-26-synced", "plaud:abc123")
    syncjob.skip(root, "plaud:noise99")
    result = syncjob.dedup(root, ["plaud:abc123", "plaud:noise99", "plaud:new77"])
    assert result["new"] == ["plaud:new77"]
    assert result["synced"] == {"plaud:abc123": "20-meetings/19-08-26-synced.md"}
    assert result["skipped"] == ["plaud:noise99"]


def test_dedup_rejects_unnamespaced_ids(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(syncjob.SyncError, match="namespace"):
        syncjob.dedup(root, ["abc123"])


def test_skip_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    syncjob.skip(root, "plaud:x1")
    result = syncjob.skip(root, "plaud:x1")
    assert result["already_present"] is True
    skip_file = root / "99-workflow-config" / "sync-state" / "skipped-recordings.txt"
    assert skip_file.read_text(encoding="utf-8").count("plaud:x1") == 1
