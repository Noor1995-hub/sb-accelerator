"""sync scan/dedup/skip: the vault is the ledger, keyed on namespaced
source-recording-id. Errors are simply not recorded — a failed item has no id
in the vault and reappears next run."""
import json
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


def test_scan_skips_symlinks_and_says_why(tmp_path):
    """scan() and archive() must agree on what an inbox candidate is. If scan
    offered a symlink, it would be processed into a note and then refused by
    the sweep — fully handled, yet never able to leave the inbox."""
    root = make_vault(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("lives outside the vault", encoding="utf-8")
    (root / "10-inbox" / "linked.txt").symlink_to(outside)
    (root / "10-inbox" / "real.txt").write_text("a transcript", encoding="utf-8")

    result = syncjob.scan(root)

    assert {c["name"] for c in result["candidates"]} == {"real.txt"}
    assert any("linked.txt" in w and "symlink" in w for w in result["warnings"])


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


def test_archive_moves_an_inbox_file_into_the_run_month(tmp_path):
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "transcript.txt"
    src.write_text("a transcript", encoding="utf-8")

    result = syncjob.archive(root, "10-inbox/transcript.txt", "2026-08-25")

    assert result == {"from": "10-inbox/transcript.txt",
                      "to": "90-archive/inbox/2026-08/transcript.txt"}
    assert not src.exists()
    moved = root / "90-archive" / "inbox" / "2026-08" / "transcript.txt"
    assert moved.read_text(encoding="utf-8") == "a transcript"


def test_archive_suffixes_a_name_collision(tmp_path):
    """Two runs, two different files, same name. Neither is lost."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "notes.txt").write_text("first", encoding="utf-8")
    syncjob.archive(root, "10-inbox/notes.txt", "2026-08-25")
    (root / "10-inbox" / "notes.txt").write_text("second", encoding="utf-8")

    result = syncjob.archive(root, "10-inbox/notes.txt", "2026-08-25")

    assert result["to"] == "90-archive/inbox/2026-08/notes-2.txt"
    folder = root / "90-archive" / "inbox" / "2026-08"
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "first"
    assert (folder / "notes-2.txt").read_text(encoding="utf-8") == "second"


def test_archive_refuses_the_readme_and_dotfiles(tmp_path):
    root = make_vault(tmp_path)
    (root / "10-inbox" / "README.md").write_text("# Inbox", encoding="utf-8")
    (root / "10-inbox" / ".DS_Store").write_bytes(b"\x00")
    for name in ("README.md", ".DS_Store"):
        with pytest.raises(syncjob.SyncError, match="never archived"):
            syncjob.archive(root, f"10-inbox/{name}", "2026-08-25")
    assert (root / "10-inbox" / "README.md").is_file()


def test_archive_refuses_a_path_outside_the_inbox(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "20-08-26-real", "plaud:abc")
    for bad in ("20-meetings/20-08-26-real.md", "10-inbox/sub/x.txt",
                "x.txt", "../escape.txt"):
        with pytest.raises(syncjob.SyncError, match="directly inside"):
            syncjob.archive(root, bad, "2026-08-25")
    assert (root / "20-meetings" / "20-08-26-real.md").is_file()


def test_archive_reports_a_missing_file_clearly(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(syncjob.SyncError, match="does not exist"):
        syncjob.archive(root, "10-inbox/ghost.txt", "2026-08-25")


def test_archive_refuses_a_symlink(tmp_path):
    """Moving a symlink relocates the link, not the file — the archive would
    hold a pointer to something outside the vault, and the real file would
    never leave the queue."""
    root = make_vault(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("lives outside the vault", encoding="utf-8")
    link = root / "10-inbox" / "linked.txt"
    link.symlink_to(outside)

    with pytest.raises(syncjob.SyncError, match="symlink"):
        syncjob.archive(root, "10-inbox/linked.txt", "2026-08-25")

    assert link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "lives outside the vault"


def test_archived_file_stays_deduped(tmp_path):
    """Ids are content hashes, so archiving never re-opens the ledger: drop
    the same content back into the inbox after the original was swept and it
    is still recognised as synced, not offered as new work. This is the
    property the whole sweep depends on."""
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "done.txt"
    src.write_text("already processed", encoding="utf-8")
    rid = syncjob.content_id(src)
    write_meeting(root, "20-08-26-done", rid)

    syncjob.archive(root, "10-inbox/done.txt", "2026-08-25")

    moved = root / "90-archive" / "inbox" / "2026-08" / "done.txt"
    assert moved.read_text(encoding="utf-8") == "already processed"
    assert not src.exists()

    # The re-delivery: same bytes, different name, after the sweep.
    redropped = root / "10-inbox" / "done-again.txt"
    redropped.write_text("already processed", encoding="utf-8")

    result = syncjob.scan(root)
    assert result["candidates"] == []
    assert [entry["name"] for entry in result["already_synced"]] == ["done-again.txt"]
    assert result["already_synced"][0]["synced_as"] == "20-meetings/20-08-26-done.md"


def test_second_scan_reparses_no_meeting(tmp_path, monkeypatch):
    """The acceptance criterion, measured: at 2,000 meetings a warm run must
    not re-read the world. Counted in file reads, not wall clock — timing
    assertions are flaky in CI."""
    root = make_vault(tmp_path)
    for n in range(2000):
        write_meeting(root, f"m{n:04d}", f"plaud:rec{n}")
    (root / "10-inbox" / "fresh.txt").write_text("t", encoding="utf-8")
    syncjob.scan(root)                       # cold run builds the cache

    reads = []
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        reads.append(self.as_posix())
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    syncjob.scan(root)

    assert [r for r in reads if "/20-meetings/" in r] == []


def test_second_scan_rehashes_no_inbox_file(tmp_path, monkeypatch):
    """A 500 MB recorder export sitting pending across runs is hashed once."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "big.txt").write_text("pretend this is huge",
                                               encoding="utf-8")
    syncjob.scan(root)

    hashed = []
    real_content_id = syncjob.content_id
    monkeypatch.setattr(syncjob, "content_id",
                        lambda path: hashed.append(path.name) or real_content_id(path))
    result = syncjob.scan(root)

    assert hashed == []
    assert {c["name"] for c in result["candidates"]} == {"big.txt"}


def test_edited_meeting_is_reparsed(tmp_path):
    """The cache is keyed on (mtime_ns, size): a changed file is re-read, so
    the ledger cannot go stale."""
    root = make_vault(tmp_path)
    done = root / "10-inbox" / "done.txt"
    done.write_text("processed transcript", encoding="utf-8")
    rid = syncjob.content_id(done)
    write_meeting(root, "20-08-26-note", rid)
    assert syncjob.scan(root)["candidates"] == []

    write_meeting(root, "20-08-26-note", None)   # id removed by hand
    result = syncjob.scan(root)

    assert {c["name"] for c in result["candidates"]} == {"done.txt"}


def test_deleted_meeting_drops_out_of_the_cache(tmp_path):
    root = make_vault(tmp_path)
    done = root / "10-inbox" / "done.txt"
    done.write_text("processed transcript", encoding="utf-8")
    write_meeting(root, "20-08-26-note", syncjob.content_id(done))
    syncjob.scan(root)

    (root / "20-meetings" / "20-08-26-note.md").unlink()
    result = syncjob.scan(root)

    assert {c["name"] for c in result["candidates"]} == {"done.txt"}
    cache = json.loads(
        (root / "99-workflow-config" / "sync-state" / "scan-cache.json")
        .read_text(encoding="utf-8"))
    assert cache["ledger"] == {}


def test_a_corrupt_or_stale_cache_is_rebuilt_in_silence(tmp_path):
    """A cold cache is a normal state, not a fault. Deleting or corrupting
    this file is always safe — that is what makes it a cache and not a second
    ledger. The non-UTF-8 case is separate on purpose: it raises
    UnicodeDecodeError (a ValueError, not an OSError) on the read, so a
    narrower except would let a torn write crash every scan."""
    root = make_vault(tmp_path)
    done = root / "10-inbox" / "done.txt"
    done.write_text("processed transcript", encoding="utf-8")
    write_meeting(root, "20-08-26-note", syncjob.content_id(done))
    cache_path = root / "99-workflow-config" / "sync-state" / "scan-cache.json"

    garbage_text = ("not json at all", '{"version": 99, "ledger": {}}',
                    '{"version": 1, "ledger": "wrong type", "inbox": {}}')
    for garbage in garbage_text:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(garbage, encoding="utf-8")
        result = syncjob.scan(root)
        assert result["candidates"] == [], garbage
        assert result["warnings"] == [], garbage

    cache_path.write_bytes(b"\xff\xfe\x00torn write \x80\x81")
    result = syncjob.scan(root)
    assert result["candidates"] == []
    assert result["warnings"] == []
    assert json.loads(cache_path.read_text(encoding="utf-8"))["version"] == 1


def test_unparseable_meeting_warning_is_replayed_from_cache(tmp_path,
                                                            monkeypatch):
    """A mangled note must not be re-read every run, and its warning must
    not vanish on the second run just because the read was skipped."""
    root = make_vault(tmp_path)
    (root / "20-meetings" / "broken.md").write_text("no frontmatter here",
                                                    encoding="utf-8")
    (root / "10-inbox" / "a.txt").write_text("t", encoding="utf-8")
    first = syncjob.scan(root)
    assert any("broken.md" in w for w in first["warnings"])

    reads = []
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        reads.append(self.as_posix())
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    second = syncjob.scan(root)

    assert any("broken.md" in w for w in second["warnings"])
    assert [r for r in reads if "broken.md" in r] == []


def test_a_quiet_run_does_not_rewrite_the_cache(tmp_path):
    """known_recording_ids is a pure read when nothing changed. meeting.write
    calls it on every write, and /sync-recordings fans out four of those in
    parallel — a needless write there is a side effect on a hot path."""
    root = make_vault(tmp_path)
    write_meeting(root, "20-08-26-one", "plaud:abc123")
    (root / "10-inbox" / "fresh.txt").write_text("t", encoding="utf-8")
    syncjob.scan(root)

    cache_path = root / "99-workflow-config" / "sync-state" / "scan-cache.json"
    before = cache_path.stat().st_mtime_ns
    syncjob.scan(root)
    assert cache_path.stat().st_mtime_ns == before

    # ...and it still writes when something actually changed.
    write_meeting(root, "20-08-26-two", "plaud:def456")
    syncjob.scan(root)
    assert cache_path.stat().st_mtime_ns != before


def test_a_meeting_with_no_recording_id_is_still_cached(tmp_path, monkeypatch):
    """The commonest note in a real vault: hand-written, no source-recording-id.
    "cached, and the answer is no id" must not collapse into "not cached", or
    the cache silently does nothing for most of the vault."""
    root = make_vault(tmp_path)
    write_meeting(root, "20-08-26-hand-written", None)
    (root / "10-inbox" / "fresh.txt").write_text("t", encoding="utf-8")
    syncjob.scan(root)

    reads = []
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        reads.append(self.as_posix())
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    result = syncjob.scan(root)

    assert [r for r in reads if "/20-meetings/" in r] == []
    assert result["known_ids_count"] == 0


def test_a_transient_read_failure_is_not_cached(tmp_path, monkeypatch):
    """The two failure modes differ, and only one may be remembered.

    Unparseable bytes self-heal: repairing the note changes (mtime_ns, size),
    so the cache misses and the note is re-read. A read *error* does not —
    restoring readability changes neither, so caching "no id" would answer for
    that note forever. Its source-recording-id would vanish from the ledger,
    its inbox file would move from already_synced back to candidates, and
    meeting._resolve_target's guard would stop firing: a second note written
    for a recording that was already synced.

    The failure has to happen on the cold read. A warm cache never opens the
    file, so it cannot be poisoned by one.
    """
    root = make_vault(tmp_path)
    done = root / "10-inbox" / "done.txt"
    done.write_text("already processed", encoding="utf-8")
    rid = syncjob.content_id(done)
    write_meeting(root, "20-08-26-locked", rid)

    real_read_text = Path.read_text

    def failing_read_text(self, *args, **kwargs):
        if self.name == "20-08-26-locked.md":
            raise OSError(13, "Permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read_text)
    during = syncjob.scan(root)
    assert any("20-08-26-locked.md" in w for w in during["warnings"])
    assert {c["name"] for c in during["candidates"]} == {"done.txt"}

    monkeypatch.undo()
    after = syncjob.scan(root)

    # The note's bytes, mtime and size never changed, so only "do not cache a
    # read error" can bring its id back.
    assert after["candidates"] == []
    assert after["warnings"] == []
    assert after["already_synced"][0]["synced_as"] == "20-meetings/20-08-26-locked.md"
# --- the skip list carries why, and park is the one call that writes it ------
#
# A bare id line records that something is suppressed forever without saying
# what it was or why. These cover the extended format (id, reason, original
# filename), the bare lines already sitting in deployed vaults, and park() —
# the single call that moves a non-capture out of the inbox and explains it in
# both places.

SKIP_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"


def write_skip_file(root: Path, *lines: str) -> Path:
    path = root / SKIP_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_skip_lines(root: Path) -> list:
    return [line for line in
            (root / SKIP_RELPATH).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_read_skip_list_returns_ids_only_from_both_line_formats(tmp_path):
    """Deployed vaults hold bare ids; new runs write three fields. Every reader
    of the id set — scan(), dedup() — must see exactly the ids either way."""
    root = make_vault(tmp_path)
    write_skip_file(root,
                    "plaud:legacy01",
                    "inbox:deadbeefcafe0000\tvendor whitepaper\treport.pdf")

    assert syncjob.read_skip_list(root) == {"plaud:legacy01",
                                            "inbox:deadbeefcafe0000"}


def test_read_skip_records_reports_an_unannotated_line_as_unknown(tmp_path):
    """A bare line is a complete record with no reason — never a parse error,
    and never invented prose."""
    root = make_vault(tmp_path)
    write_skip_file(root,
                    "plaud:legacy01",
                    "inbox:deadbeefcafe0000\tvendor whitepaper\treport.pdf")

    records = syncjob.read_skip_records(root)

    assert records == [
        {"recording_id": "plaud:legacy01", "reason": None, "source_name": None},
        {"recording_id": "inbox:deadbeefcafe0000",
         "reason": "vendor whitepaper", "source_name": "report.pdf"},
    ]


def test_skip_without_a_reason_still_writes_a_bare_line(tmp_path):
    """An adapter id with nothing to say stays one field wide, so the file a
    deployed vault already has keeps the shape it already had."""
    root = make_vault(tmp_path)
    syncjob.skip(root, "plaud:x1")
    assert read_skip_lines(root) == ["plaud:x1"]


def test_skip_records_the_reason_and_the_original_filename(tmp_path):
    root = make_vault(tmp_path)
    result = syncjob.skip(root, "inbox:abc0000000000000",
                          reason="vendor whitepaper, no capture content",
                          source_name="yard-automation.pdf")

    assert result["reason"] == "vendor whitepaper, no capture content"
    assert read_skip_lines(root) == [
        "inbox:abc0000000000000\tvendor whitepaper, no capture content"
        "\tyard-automation.pdf"]


def test_skip_flattens_whitespace_so_one_record_is_one_line(tmp_path):
    """A tab would invent a field and a newline would invent a record. A model
    writes these reasons, so neither can be assumed absent."""
    root = make_vault(tmp_path)
    syncjob.skip(root, "inbox:abc0000000000000",
                 reason="deck\tabout\nyard   automation", source_name="d.pptx")

    assert read_skip_lines(root) == [
        "inbox:abc0000000000000\tdeck about yard automation\td.pptx"]


def test_skip_truncates_an_overlong_reason(tmp_path):
    root = make_vault(tmp_path)
    syncjob.skip(root, "inbox:abc0000000000000", reason="x" * 500,
                 source_name="d.pptx")

    stored = read_skip_lines(root)[0].split("\t")[1]
    assert len(stored) == syncjob.MAX_REASON_CHARS
    assert stored.endswith("…")


def test_skip_annotates_an_existing_bare_record_in_place(tmp_path):
    """The deployed-vault case: an id parked before reasons existed, whose file
    is dropped back in and parked again. The reason lands on the line that is
    already there rather than duplicating the id."""
    root = make_vault(tmp_path)
    write_skip_file(root, "plaud:keep01", "inbox:abc0000000000000", "plaud:keep02")

    result = syncjob.skip(root, "inbox:abc0000000000000",
                          reason="a spreadsheet", source_name="q3.xlsx")

    assert result["already_present"] is True
    assert result["reason_added"] is True
    assert read_skip_lines(root) == [
        "plaud:keep01",
        "inbox:abc0000000000000\ta spreadsheet\tq3.xlsx",
        "plaud:keep02",
    ]


def test_skip_never_overwrites_a_reason_already_recorded(tmp_path):
    """The first explanation is the one a human would have read. A re-park does
    not get to revise history."""
    root = make_vault(tmp_path)
    syncjob.skip(root, "inbox:abc0000000000000", reason="first call",
                 source_name="a.pdf")

    result = syncjob.skip(root, "inbox:abc0000000000000", reason="second call",
                          source_name="b.pdf")

    assert result["already_present"] is True
    assert result["reason_added"] is False
    assert read_skip_lines(root) == [
        "inbox:abc0000000000000\tfirst call\ta.pdf"]


def test_scan_partitions_an_annotated_skip_record(tmp_path):
    """The format change must not resurrect a parked file as a candidate."""
    root = make_vault(tmp_path)
    parked = root / "10-inbox" / "noise.txt"
    parked.write_text("pocket recording", encoding="utf-8")
    syncjob.skip(root, syncjob.content_id(parked), reason="stray binary",
                 source_name="noise.txt")

    result = syncjob.scan(root)

    assert result["candidates"] == []
    assert [s["name"] for s in result["skipped"]] == ["noise.txt"]


def test_park_moves_records_and_explains_in_one_call(tmp_path):
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "yard-automation.pdf"
    src.write_bytes(b"%PDF-1.7 whitepaper")
    rid = syncjob.content_id(src)

    result = syncjob.park(root, "10-inbox/yard-automation.pdf", rid,
                          "vendor whitepaper, no capture content", "2026-08-25")

    assert result["from"] == "10-inbox/yard-automation.pdf"
    assert result["to"] == "90-archive/inbox/2026-08/yard-automation.pdf"
    assert result["sidecar"] == (
        "90-archive/inbox/2026-08/yard-automation.pdf.parked.md")
    assert result["recording_id"] == rid
    assert not src.exists()
    assert (root / result["to"]).read_bytes() == b"%PDF-1.7 whitepaper"
    assert rid in syncjob.read_skip_list(root)
    assert syncjob.read_skip_records(root) == [
        {"recording_id": rid, "reason": "vendor whitepaper, no capture content",
         "source_name": "yard-automation.pdf"}]


def test_park_sidecar_says_what_why_and_how_to_undo_it(tmp_path):
    """The whole point: the folder explains itself a quarter later."""
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "yard-automation.pdf"
    src.write_bytes(b"%PDF")
    rid = syncjob.content_id(src)

    result = syncjob.park(root, "10-inbox/yard-automation.pdf", rid,
                          "vendor whitepaper, no capture content", "2026-08-25")
    sidecar = (root / result["sidecar"]).read_text(encoding="utf-8")

    assert "yard-automation.pdf" in sidecar
    assert "vendor whitepaper, no capture content" in sidecar
    assert "10-inbox/yard-automation.pdf" in sidecar
    assert rid in sidecar
    assert "skipped-recordings.txt" in sidecar
    assert "2026-08-25" in sidecar
    # No frontmatter: this is prose for a human, not a vault object, and no
    # ontology check may ever try to validate it.
    assert not sidecar.startswith("---")


def test_park_sidecar_follows_a_collision_suffixed_name(tmp_path):
    """archive() renames on collision; the explanation must name the file that
    actually landed, not the one that was asked for."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "notes.txt").write_text("first", encoding="utf-8")
    syncjob.archive(root, "10-inbox/notes.txt", "2026-08-25")
    (root / "10-inbox" / "notes.txt").write_text("second", encoding="utf-8")
    rid = syncjob.content_id(root / "10-inbox" / "notes.txt")

    result = syncjob.park(root, "10-inbox/notes.txt", rid, "a stray file",
                          "2026-08-25")

    assert result["to"] == "90-archive/inbox/2026-08/notes-2.txt"
    assert result["sidecar"] == "90-archive/inbox/2026-08/notes-2.txt.parked.md"
    assert (root / result["sidecar"]).is_file()


def test_park_refuses_an_empty_reason_and_moves_nothing(tmp_path):
    """A park with no reason is the defect being fixed. It cannot be reachable
    by omission."""
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "a.pdf"
    src.write_bytes(b"x")

    with pytest.raises(syncjob.SyncError, match="reason"):
        syncjob.park(root, "10-inbox/a.pdf", "inbox:abc0000000000000", "   ",
                     "2026-08-25")

    assert src.exists()
    assert syncjob.read_skip_list(root) == set()


def test_park_validates_the_id_before_touching_the_file(tmp_path):
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "a.pdf"
    src.write_bytes(b"x")

    with pytest.raises(syncjob.SyncError, match="namespace"):
        syncjob.park(root, "10-inbox/a.pdf", "abc123", "a deck", "2026-08-25")

    assert src.exists()


def test_park_inherits_the_archive_guards(tmp_path):
    """park() suppresses an id forever, so it must refuse everything archive()
    refuses — and suppress nothing when it does."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "README.md").write_text("# Inbox", encoding="utf-8")
    (root / "20-meetings" / "note.md").write_text("x", encoding="utf-8")

    with pytest.raises(syncjob.SyncError):
        syncjob.park(root, "10-inbox/README.md", "inbox:abc0000000000000",
                     "the folder readme", "2026-08-25")
    with pytest.raises(syncjob.SyncError):
        syncjob.park(root, "20-meetings/note.md", "inbox:abc0000000000000",
                     "not in the inbox", "2026-08-25")

    assert (root / "10-inbox" / "README.md").is_file()
    assert syncjob.read_skip_list(root) == set()


def test_re_parking_an_id_explains_it_the_way_it_was_first_explained(tmp_path):
    """The same non-capture dropped back in and parked again. The skip list
    keeps the first reason, so a second sidecar asserting a different one
    would leave the vault telling two stories about one decision."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "report.pdf").write_bytes(b"%PDF")
    rid = syncjob.content_id(root / "10-inbox" / "report.pdf")
    syncjob.park(root, "10-inbox/report.pdf", rid, "vendor whitepaper",
                 "2026-08-25")

    (root / "10-inbox" / "report.pdf").write_bytes(b"%PDF")
    result = syncjob.park(root, "10-inbox/report.pdf", rid,
                          "a wholly different explanation", "2026-09-02")

    assert result["already_present"] is True
    assert result["reason"] == "vendor whitepaper"
    sidecar = (root / result["sidecar"]).read_text(encoding="utf-8")
    assert "vendor whitepaper" in sidecar
    assert "a wholly different explanation" not in sidecar
    assert "earlier run" in sidecar


def test_re_parking_a_legacy_bare_id_does_not_backdate_its_reason(tmp_path):
    """The deployed-vault case. The id was suppressed before reasons existed,
    so the reason written now is new — the sidecar must not claim it was on
    record all along."""
    root = make_vault(tmp_path)
    (root / "10-inbox" / "report.pdf").write_bytes(b"%PDF")
    rid = syncjob.content_id(root / "10-inbox" / "report.pdf")
    write_skip_file(root, rid)

    result = syncjob.park(root, "10-inbox/report.pdf", rid,
                          "vendor whitepaper", "2026-08-25")
    sidecar = (root / result["sidecar"]).read_text(encoding="utf-8")

    assert result["reason"] == "vendor whitepaper"
    assert "vendor whitepaper" in sidecar
    assert "recorded then" not in sidecar
    assert "no reason was recorded" in sidecar
    # ...and the bare line gains the reason rather than gaining a twin.
    assert syncjob.read_skip_records(root) == [
        {"recording_id": rid, "reason": "vendor whitepaper",
         "source_name": "report.pdf"}]


def write_timed_meeting(root: Path, stem: str, *, date: str, duration: int,
                        source: str, recording_id: str,
                        subject: str = "A meeting") -> None:
    lines = ["---", f"date: {date}", "type: meeting",
             f'calendar-subject: "{subject}"',
             f"recording-duration: {duration}", f"source: {source}",
             f"source-recording-id: {recording_id}", "---", "", "body"]
    (root / "20-meetings" / f"{stem}.md").write_text(
        "\n".join(lines), encoding="utf-8")


def test_collide_finds_a_window_overlapping_meeting_from_another_adapter(tmp_path):
    """The exact-id ledger cannot see that plaud:X and m365:Y are one
    conversation; the window check can."""
    root = make_vault(tmp_path)
    write_timed_meeting(root, "25-08-26-darta-sync", date="2026-08-25T16:01",
                        duration=63, source="recorder",
                        recording_id="plaud:abc123", subject="Darta sync")
    result = syncjob.collide(root, "2026-08-25T16:00", 64)
    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["source-recording-id"] == "plaud:abc123"
    assert match["imprecise"] is False
    assert result["checked"] == 1


def test_collide_grace_absorbs_a_late_recorder_start(tmp_path):
    root = make_vault(tmp_path)
    write_timed_meeting(root, "25-08-26-late-start", date="2026-08-25T16:12",
                        duration=45, source="recorder",
                        recording_id="plaud:late1")
    result = syncjob.collide(root, "2026-08-25T16:00", 60)
    assert len(result["matches"]) == 1


def test_collide_excludes_a_back_to_back_meeting_outside_the_grace(tmp_path):
    root = make_vault(tmp_path)
    write_timed_meeting(root, "25-08-26-next-slot", date="2026-08-25T17:30",
                        duration=30, source="recorder",
                        recording_id="plaud:next1")
    result = syncjob.collide(root, "2026-08-25T16:00", 60)
    assert result["matches"] == []
    assert result["checked"] == 1


def test_collide_reports_a_date_only_note_as_imprecise(tmp_path):
    root = make_vault(tmp_path)
    write_timed_meeting(root, "25-08-26-dateless", date="2026-08-25",
                        duration=0, source="manual",
                        recording_id="inbox:aaaa000011112222")
    result = syncjob.collide(root, "2026-08-25T16:00", 60)
    assert len(result["matches"]) == 1
    assert result["matches"][0]["imprecise"] is True


def test_collide_warns_on_an_unparseable_note_and_continues(tmp_path):
    root = make_vault(tmp_path)
    (root / "20-meetings" / "broken.md").write_text("---\n: not yaml\n",
                                                    encoding="utf-8")
    write_timed_meeting(root, "25-08-26-fine", date="2026-08-25T16:00",
                        duration=30, source="teams",
                        recording_id="m365:0123456789abcdef")
    result = syncjob.collide(root, "2026-08-25T16:00", 30)
    assert len(result["matches"]) == 1
    assert result["warnings"]


def test_collide_rejects_a_date_only_start_argument(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(syncjob.SyncError, match="YYYY-MM-DDTHH:MM"):
        syncjob.collide(root, "2026-08-25", 30)


def test_collide_rejects_a_negative_duration(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(syncjob.SyncError, match="duration-min"):
        syncjob.collide(root, "2026-08-25T16:00", -5)
