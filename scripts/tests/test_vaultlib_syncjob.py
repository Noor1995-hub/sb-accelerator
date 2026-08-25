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


def write_triaged_meeting(root, stem, review_status, reviewed,
                          conflicts_with=None):
    """`conflicts_with=None` omits the key; a stem writes the quoted wikilink;
    `""` writes the key with no value — the shape Obsidian leaves behind when
    a human clears the field to say the duplicate is resolved."""
    lines = [
        "---", "date: 2026-08-20T10:00", "type: meeting",
        'calendar-subject: "X"', f"review_status: {review_status}",
        f"reviewed: {'true' if reviewed else 'false'}", "archived: false",
    ]
    if conflicts_with is not None:
        value = f'"[[{conflicts_with}]]"' if conflicts_with else ""
        lines.append(f"conflicts-with: {value}".rstrip())
    lines += ["---", "", "## Key Takeaways", "- x", ""]
    (root / "20-meetings" / f"{stem}.md").write_text(
        "\n".join(lines), encoding="utf-8")


def test_reconcile_flips_only_reviewed_needs_review(tmp_path):
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "a-ticked", "needs-review", True)
    write_triaged_meeting(root, "b-unticked", "needs-review", False)
    write_triaged_meeting(root, "c-confirmed", "confirmed", True)
    # The clobber-risk case: a -v2 sibling the CLI wrote rather than overwrite
    # a confirmed note. Ticked, but the duplicate is unresolved.
    write_triaged_meeting(root, "d-duplicate", "needs-review", True,
                          conflicts_with="c-confirmed")

    result = syncjob.reconcile_reviews(root)
    assert result["flipped"] == ["20-meetings/a-ticked.md"]
    assert result["conflict_ticks"] == ["20-meetings/d-duplicate.md"]

    text = (root / "20-meetings" / "a-ticked.md").read_text(encoding="utf-8")
    assert "review_status: confirmed" in text
    assert "reviewed: true" in text          # the tick itself is never touched
    untouched = (root / "20-meetings" / "b-unticked.md").read_text(encoding="utf-8")
    assert "review_status: needs-review" in untouched
    still_flagged = (root / "20-meetings" / "d-duplicate.md").read_text(encoding="utf-8")
    assert "review_status: needs-review" in still_flagged


def test_clearing_the_conflict_edge_lets_the_tick_fold(tmp_path):
    """The escape hatch: emptying conflicts-with is how a human says the
    duplicate is merged or deleted, and the next run confirms normally."""
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "resolved", "needs-review", True,
                          conflicts_with="")

    result = syncjob.reconcile_reviews(root)
    assert result["flipped"] == ["20-meetings/resolved.md"]
    assert result["conflict_ticks"] == []


def test_reconcile_preserves_every_other_byte(tmp_path):
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "a-ticked", "needs-review", True)
    before = (root / "20-meetings" / "a-ticked.md").read_text(encoding="utf-8")
    syncjob.reconcile_reviews(root)
    after = (root / "20-meetings" / "a-ticked.md").read_text(encoding="utf-8")
    assert after == before.replace("review_status: needs-review",
                                   "review_status: confirmed")


def test_reconcile_is_idempotent_and_tolerates_broken_files(tmp_path):
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "a-ticked", "needs-review", True)
    (root / "20-meetings" / "broken.md").write_text("not a note", encoding="utf-8")
    syncjob.reconcile_reviews(root)
    second = syncjob.reconcile_reviews(root)
    assert second["flipped"] == []
    assert any("broken.md" in w for w in second["warnings"])


def test_ticked_legacy_status_warns_instead_of_falling_out_silently(tmp_path):
    """A vault from before the needs-attention retirement may still hold a
    ticked note carrying the retired status plus its conflicts-with edge. It
    must not be flipped, must not be reported as a conflict tick (it was never
    in that queue), and must produce exactly one warning naming the file."""
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "legacy-duplicate", "needs-attention", True,
                          conflicts_with="c-confirmed")

    result = syncjob.reconcile_reviews(root)

    assert result["flipped"] == []
    assert result["conflict_ticks"] == []
    matching = [w for w in result["warnings"] if "legacy-duplicate.md" in w]
    assert len(matching) == 1
    assert "needs-attention" in matching[0]


def test_ticked_confirmed_note_never_warns(tmp_path):
    """The cry-wolf guard: a ticked confirmed note is the normal steady state
    and must stay silent, not warn on every run."""
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "c-confirmed", "confirmed", True)

    result = syncjob.reconcile_reviews(root)

    assert result["warnings"] == []
