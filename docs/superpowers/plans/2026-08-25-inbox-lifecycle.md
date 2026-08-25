# Inbox Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `10-inbox/` a lifecycle — non-meeting captures get an honest home, processed and parked files leave the folder, and the ledger check stops re-parsing every meeting on every run.

**Architecture:** Non-meeting inbox items become notes in `20-meetings/` under a new `type: note` (the dedup ledger only exists there), so one triage surface and one evening-sync consumer serve both. `/sync-recordings` moves every processed or parked file to `90-archive/inbox/{YYYY-MM}/`, which makes `10-inbox/` contain exactly the pending set — the folder becomes the "what is unprocessed?" view, replacing any need for an index note or state file. A disposable `(mtime_ns, size)`-keyed cache under `99-workflow-config/sync-state/` removes the full re-parse and re-hash.

**Tech Stack:** Python 3.10 (syntax floor), stdlib only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-25-inbox-lifecycle-design.md`

## Global Constraints

Copied verbatim from `plugin/CLAUDE.md` and the repo's root `CLAUDE.md`. Every task's requirements implicitly include this section.

- **Stdlib only** in `plugin/lib/`. PyYAML's presence in the Cowork VM is unverified. Never import a third-party package.
- **Python 3.10 is the syntax floor.** Cowork ships 3.10; repo CI runs 3.13. A 3.11+ construct fails only on the client machine.
- **The vault root is always a parameter.** Never infer a path shape.
- **Writes are UTF-8 with `newline="\n"`** — always via `vault.atomic_write`, never `Path.write_text` for vault content.
- **The CLI prints exactly one JSON object** and signals through its exit code: `{"ok": true, "result": {...}}` or `{"ok": false, "error": "...", "hint": "..."}`.
- **Clean-room rule:** nothing in `plugin/` or `template/` may name a delaware client, a real person, or busdev content. `scripts/lint_plugin.py` greps a denylist in CI.
- **Every commit message ends with the exact trailer:** `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Do not run `git checkout`, `git switch`, `git reset`, `git stash`, or `git rebase`** in this worktree. To read a file at a commit use `git show <sha>:<path>`. (See `docs/superpowers/lessons.md` — this has orphaned commits here twice.)
- **A fenced block containing another fenced block needs more backticks than its deepest child** — four outside, three inside. This repo embeds vault content constantly; see `docs/superpowers/lessons.md`.
- **Plugin version:** any PR touching `plugin/` (except `plugin/CLAUDE.md`) must bump `plugin/.claude-plugin/plugin.json`. This work ships **0.6.0** (current is `0.5.0`, taken by #54).

**The local gate, run before every commit that touches `plugin/`, `template/`, or `scripts/`:**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

**Test imports resolve via `scripts/tests/conftest.py`**, which puts `plugin/lib/` and `scripts/` on `sys.path`. Import as `from vaultlib import syncjob` — never a relative or absolute filesystem path.

---

### Task 1: Ontology — `type: note` and `calendar-not-applicable`

The compiled `schema.json` is generated from the ontology and is what the CLI validates against at runtime. Nothing in later tasks can accept a `note` until this lands.

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md` (Meeting block, ~lines 29-68)
- Regenerate: `plugin/lib/vaultlib/schema.json` (never hand-edited)
- Test: `scripts/tests/test_vaultlib_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `schema.enum_values("meeting", "type")` includes `"note"`; `schema.for_object("meeting")["confidence_reasons"]["calendar"]` includes `"calendar-not-applicable"`. Task 2, Task 5, and Task 6 all depend on these exact strings.

- [ ] **Step 1: Write the failing test**

Append to `scripts/tests/test_vaultlib_schema.py`:

```python
def test_meeting_type_admits_the_non_meeting_capture():
    """A forwarded email is a dated capture, not a meeting. It lives in
    20-meetings/ because that folder is the vault's capture ledger — the
    honest label is what keeps that from being a lie."""
    values = schema.enum_values("meeting", "type")
    assert "note" in values
    assert values[:6] == ["meeting", "1:1", "steerco", "workshop",
                          "brainstorm", "status-update"]


def test_calendar_reasons_distinguish_not_applicable_from_not_found():
    """Three different facts that must never collapse: searched and found
    nothing, could not search, and never searched because it is not a
    meeting."""
    calendar = schema.for_object("meeting")["confidence_reasons"]["calendar"]
    assert "no-calendar-match" in calendar
    assert "calendar-tool-unavailable" in calendar
    assert "calendar-not-applicable" in calendar
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_schema.py -q -k "non_meeting_capture or not_applicable"`
Expected: FAIL — `assert 'note' in ['meeting', '1:1', ...]`

- [ ] **Step 3: Edit the ontology's Meeting block**

In `template/99-workflow-config/reference/ontology.md`, find this exact fenced block under `### Meeting`:

```yaml
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update]
  review_status: [needs-review, confirmed, needs-attention]
  source: [teams, recorder, manual, email]
  confidence: [high, medium, low]
confidence_reasons:
  calendar: [calendar-match-high, calendar-match-medium, calendar-match-low,
             no-calendar-match, calendar-tool-unavailable]
```

Replace those seven lines with:

```yaml
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update, note]
  review_status: [needs-review, confirmed, needs-attention]
  source: [teams, recorder, manual, email]
  confidence: [high, medium, low]
confidence_reasons:
  calendar: [calendar-match-high, calendar-match-medium, calendar-match-low,
             no-calendar-match, calendar-tool-unavailable,
             calendar-not-applicable]
```

- [ ] **Step 4: Add the ontology prose**

In the same file, find this bullet (it ends the `source` explanation):

```
- `source` is the capture channel: `teams` (platform transcript), `recorder`
  (device capture), `manual` (typed notes), `email` (an emailed summary or
  transcript). `recording-duration` is `0` when nothing was recorded
  (`manual`, `email`).
```

Insert these bullets immediately **after** it:

```
- **`type: note` is a capture that is not a record of an interaction** —
  forwarded correspondence, a voice memo, pasted context. It lives here
  because `20-meetings/` is the vault's capture ledger, not because an email
  is a meeting. A `note` carries `calendar_match: false`,
  `recording-duration: 0`, and **may carry empty `attendees`** — it is the
  one type for which an empty attendee list is valid. Its
  `calendar-subject` is a descriptive subject drawn from the item itself —
  a forwarded email's own `Subject:` line, a voice memo's short title —
  and is never empty; `calendar_match: false` alone records that no
  calendar corroborated it. `type` and `source` are orthogonal: a forwarded email is
  `type: note` + `source: email`, while an emailed *meeting summary* is
  `type: meeting` + `source: email`.
- `calendar-not-applicable` means the calendar was never consulted **because
  the item is not a meeting**. It is a third distinct fact alongside
  `no-calendar-match` (searched, found nothing) and
  `calendar-tool-unavailable` (could not search). Never collapse the three.
  A `note` with empty `attendees` still carries `all-attendees-known`: the
  attendees vocabulary stays closed, and with nobody named there is nobody
  unknown.
```

- [ ] **Step 5: Regenerate the compiled schema**

```bash
python3 scripts/compile_ontology.py
```

Expected: writes `plugin/lib/vaultlib/schema.json`. Do not hand-edit that file.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_schema.py scripts/tests/test_compile_ontology.py -q`
Expected: PASS. `test_compile_ontology.py` is the staleness guard — if it fails, step 5 did not run.

- [ ] **Step 7: Run the full local gate**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

Expected: all pass. `test_fixtures_ontology.py` validates fixture frontmatter against the schema — widening an enum cannot break it, so a failure here means something else moved.

- [ ] **Step 8: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md plugin/lib/vaultlib/schema.json scripts/tests/test_vaultlib_schema.py
git commit -m "$(cat <<'EOF'
feat: ontology admits type: note and calendar-not-applicable (#55)

A forwarded email carrying project context is a dated capture, not a
meeting. It belongs in 20-meetings/ because that folder is the vault's
capture ledger and the dedup ledger only exists there — but calling it
type: status-update asserted a meeting that never happened.

calendar-not-applicable is the third calendar fact: never consulted
because the item is not a meeting. Distinct from searched-found-nothing
and could-not-search, which the pipeline already refuses to collapse.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `meeting write` accepts a `type: note` with no attendees

`meeting.py` currently refuses an empty `attendees` list for every type. An email always names people; a voice-memo musing may name nobody.

**Files:**
- Modify: `plugin/lib/vaultlib/meeting.py:202`
- Test: `scripts/tests/test_vaultlib_meeting.py`

**Interfaces:**
- Consumes: Task 1's schema (`"note"` in the type enum, `"calendar-not-applicable"` in the calendar reasons).
- Produces: `meeting.write(root, payload)` accepts `{"type": "note", "attendees": [], ...}` and writes `20-meetings/{DD-MM-YY}-{title-slug}.md` exactly as it does for any other type. Task 6's SKILL.md payload contract depends on this.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_meeting.py`. The module already defines `make_vault()` and `payload(**overrides)` — reuse them, do not redefine.

```python
def note_payload(**overrides) -> dict:
    """A forwarded email: a capture, not a meeting. No calendar was ever
    consulted and nothing was recorded — but it is still filed under its
    own subject line, because a required field may not be empty."""
    base = payload(
        title="meridian renewal terms heads up",
        type="note",
        **{"calendar-subject": "Renewal terms — heads up before next steerco"},
    )
    base["calendar_match"] = False
    base["recording-duration"] = 0
    base["source"] = "email"
    base["confidence-reasons"] = ["calendar-not-applicable",
                                  "content-keyword-match",
                                  "all-attendees-known"]
    base.pop("source-filename", None)
    base.update(overrides)
    return base


def test_note_type_is_written_like_any_other_capture(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, note_payload())
    assert result["stem"] == "20-05-26-meridian-renewal-terms-heads-up"
    assert result["review_status"] == "needs-review"
    written = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(written.split("---")[1])
    assert data["type"] == "note"
    assert data["calendar-subject"] == "Renewal terms — heads up before next steerco"
    assert data["recording-duration"] == 0
    assert data["source"] == "email"


def test_note_may_carry_no_attendees(tmp_path):
    """A voice memo musing names nobody. Every other type still must."""
    root = make_vault(tmp_path)
    result = meeting.write(root, note_payload(attendees=[]))
    written = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(written.split("---")[1])
    assert data["attendees"] == []


def test_empty_attendees_still_refused_for_every_other_type(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="non-empty"):
        meeting.write(root, payload(attendees=[]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py -q -k "note_type or no_attendees or every_other_type"`
Expected: `test_note_may_carry_no_attendees` FAILS with `MeetingError: attendees must be a non-empty list of slugs`. The other two should already pass once Task 1 landed — if `test_note_type_is_written_like_any_other_capture` fails on the schema, Task 1 is incomplete.

- [ ] **Step 3: Make the minimal change**

In `plugin/lib/vaultlib/meeting.py`, find line 202:

```python
    attendees = _require_slug_list(payload, "attendees", allow_empty=False)
```

Replace with:

```python
    # A note is the one capture that legitimately names nobody — a voice memo
    # musing, a pasted paragraph. Every meeting has attendees by definition.
    attendees = _require_slug_list(
        payload, "attendees", allow_empty=(payload["type"] == "note"))
```

Nothing else in the module changes. `_validate_confidence()` reads its vocabulary from the compiled schema, so `calendar-not-applicable` is already accepted. `recording-duration: 0` already validates (`isinstance(int) and >= 0`).

**Do not pass an empty `calendar-subject`.** `meeting.py` itself has no non-empty check on it, but `meeting.write` calls `schema.validate("meeting", frontmatter)`, and `schema.py:52-54` fails any *required* field whose value is `""`. `calendar-subject` is required. A capture is therefore filed under its own subject line — the email's `Subject:`, the memo's title. `attendees: []` is genuinely fine by contrast: `[] in (None, "")` is `False`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py -q`
Expected: PASS, whole file.

- [ ] **Step 5: Run the full local gate**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/meeting.py scripts/tests/test_vaultlib_meeting.py
git commit -m "$(cat <<'EOF'
feat: meeting write accepts a type: note with no attendees (#55)

A note is the one capture that legitimately names nobody — a voice memo
musing, a pasted paragraph. Every meeting has attendees by definition,
so the non-empty requirement stays for every other type.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The sweep — `syncjob.archive()` and `sync archive`

The inbox becomes the pending set. Once a file has produced a note or been parked, it leaves for `90-archive/inbox/{YYYY-MM}/`.

**Files:**
- Modify: `plugin/lib/vaultlib/vault.py:22-27` (folder constants)
- Modify: `plugin/lib/vaultlib/syncjob.py` (imports, constants, new functions)
- Modify: `plugin/lib/vaultlib/cli.py:191-220` (parser), `cli.py:315-327` (dispatch)
- Test: `scripts/tests/test_vaultlib_syncjob.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `vault.today_iso(explicit)`, `vault.ARCHIVE_DIR`, `syncjob.SyncError`.
- Produces:
  - `vault.ARCHIVE_DIR: str = "90-archive"`
  - `syncjob.archive(root: Path, relpath: str, today: str) -> dict` returning `{"from": "10-inbox/x.txt", "to": "90-archive/inbox/2026-08/x.txt"}`
  - CLI: `sync archive --vault <path> --path 10-inbox/<name> [--today <ISO>]`

  Task 6's SKILL.md calls the CLI form. Nothing else consumes the Python form.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_syncjob.py`. The module already defines `make_vault()` and `write_meeting()` — reuse them.

```python
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


def test_archived_file_stays_deduped(tmp_path):
    """Ids are content hashes, so moving a file never re-opens the ledger.
    This is the property the sweep depends on."""
    root = make_vault(tmp_path)
    src = root / "10-inbox" / "done.txt"
    src.write_text("already processed", encoding="utf-8")
    rid = syncjob.content_id(src)
    write_meeting(root, "20-08-26-done", rid)

    syncjob.archive(root, "10-inbox/done.txt", "2026-08-25")

    moved = root / "90-archive" / "inbox" / "2026-08" / "done.txt"
    assert syncjob.content_id(moved) == rid
    assert syncjob.scan(root)["candidates"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q -k archive`
Expected: FAIL — `AttributeError: module 'vaultlib.syncjob' has no attribute 'archive'`

- [ ] **Step 3: Add the archive folder constant**

In `plugin/lib/vaultlib/vault.py`, find:

```python
DAILY_NOTES_DIR = "60-daily-notes"
```

Insert immediately after it:

```python
ARCHIVE_DIR = "90-archive"
```

Do **not** add it to `_CONTENT_FOLDERS` — that tuple is the "does this look like a vault?" probe, and a vault is not identified by having an archive.

- [ ] **Step 4: Implement `archive()`**

In `plugin/lib/vaultlib/syncjob.py`, change the import block at the top from:

```python
import hashlib
from pathlib import Path
from typing import Dict, List, Set, Tuple
```

to:

```python
import hashlib
import shutil
from pathlib import Path, PurePosixPath
from typing import Dict, List, Set, Tuple
```

Then find the constants block and add two lines after `SKIP_FILE_RELPATH`:

```python
SKIP_FILE_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"
ARCHIVE_DIR = vault.ARCHIVE_DIR
ARCHIVE_INBOX_SUBDIR = "inbox"
_IGNORED_NAMES = {"README.md"}
```

Then append these two functions to the end of the module:

```python
def _free_target(folder: Path, name: str) -> Path:
    """First unused name in folder, suffixing -2, -3, ... on collision.

    Two different files can legitimately arrive with the same name in the
    same month; neither may overwrite the other.
    """
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def archive(root: Path, relpath: str, today: str) -> dict:
    """Move a processed or parked inbox file to 90-archive/inbox/{YYYY-MM}/.

    The inbox is the pending set: a file that produced a note, or that a
    human parked, has left the queue and leaves the folder. What remains in
    10-inbox/ is what still needs processing — that is the whole of the
    processed-state story, and why no index note or state file is needed.

    Safe by construction: ids are content hashes, so an archived file keeps
    its id and stays deduped. The month bucket comes from the run date and
    is deliberately not timezone-aware — an archive folder is a filing
    convenience, not a fact anything joins on.
    """
    day = vault.today_iso(today)
    rel = PurePosixPath(str(relpath or "").strip())
    if len(rel.parts) != 2 or rel.parts[0] != INBOX_DIR:
        raise SyncError(
            f"--path {relpath!r} must name a file directly inside {INBOX_DIR}/, "
            f"for example {INBOX_DIR}/2026-08-21-forwarded-email.txt"
        )
    name = rel.parts[1]
    if name in _IGNORED_NAMES or name.startswith("."):
        raise SyncError(
            f"{name!r} is not a sync candidate and is never archived — "
            "scan() ignores it too"
        )
    source = root / INBOX_DIR / name
    if not source.is_file():
        raise SyncError(
            f"{rel.as_posix()} does not exist or is not a regular file"
        )
    target_dir = root / ARCHIVE_DIR / ARCHIVE_INBOX_SUBDIR / day[:7]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _free_target(target_dir, name)
    shutil.move(str(source), str(target))
    return {"from": rel.as_posix(),
            "to": target.relative_to(root).as_posix()}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q`
Expected: PASS, whole file.

- [ ] **Step 6: Add the CLI surface**

In `plugin/lib/vaultlib/cli.py`, find this block (around line 209):

```python
    sync_rec = sync_sub.add_parser(
        "reconcile-reviews",
        help="flip review_status needs-review -> confirmed where reviewed is ticked")
    _add_vault_argument(sync_rec)
```

Insert immediately **after** it:

```python
    sync_archive = sync_sub.add_parser(
        "archive",
        help="move a processed or parked inbox file to 90-archive/inbox/")
    _add_vault_argument(sync_archive)
    sync_archive.add_argument(
        "--path", required=True,
        help="vault-relative path of the inbox file, e.g. 10-inbox/notes.txt")
    sync_archive.add_argument("--today", help="ISO date; defaults to today")
```

Then in `_dispatch`, find (around line 326):

```python
        if args.action == "reconcile-reviews":
            return _ok(syncjob.reconcile_reviews(root))
```

Insert immediately **after** it:

```python
        if args.action == "archive":
            return _ok(syncjob.archive(root, args.path,
                                       vault.today_iso(args.today)))
```

- [ ] **Step 7: Write the CLI test**

Append to `scripts/tests/test_vaultlib_cli.py`. That module already defines `run(capsys, argv) -> (code, payload)` and imports `make_vault` from `test_vaultlib_vault` — use both; do not add a helper.

`make_vault` creates `10-inbox/` but not `90-archive/`, which is correct: `archive()` creates the destination on demand, and these tests prove it.

```python
def test_sync_archive_moves_the_file_and_reports_both_paths(capsys, tmp_path):
    root = make_vault(tmp_path)
    (root / "10-inbox" / "notes.txt").write_text("x", encoding="utf-8")

    code, payload = run(capsys, [
        "sync", "archive", "--vault", str(root),
        "--path", "10-inbox/notes.txt", "--today", "2026-08-25",
    ])

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"] == {
        "from": "10-inbox/notes.txt",
        "to": "90-archive/inbox/2026-08/notes.txt",
    }
    assert not (root / "10-inbox" / "notes.txt").exists()
    assert (root / "90-archive" / "inbox" / "2026-08" / "notes.txt").is_file()


def test_sync_archive_surfaces_a_bad_path_as_a_failure_envelope(capsys, tmp_path):
    """A refusal is a well-formed envelope with a hint, not a traceback —
    skills read this output."""
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "sync", "archive", "--vault", str(root), "--path", "20-meetings/x.md",
    ])

    assert code == 1
    assert payload["ok"] is False
    assert "directly inside" in payload["error"]
    assert payload["hint"] == "Fix the named id or argument and retry."
```

`main()` already routes `syncjob.SyncError` to `_fail(str(exc), "Fix the named id or argument and retry.")`, so the failure envelope needs no new handler — the second test pins that it stays that way.

- [ ] **Step 8: Run the CLI tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS. If the helper names above do not exist in that file, adapt to whatever it does define — do not add a second helper.

- [ ] **Step 9: Run the full local gate**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

- [ ] **Step 10: Commit**

```bash
git add plugin/lib/vaultlib/vault.py plugin/lib/vaultlib/syncjob.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_syncjob.py scripts/tests/test_vaultlib_cli.py
git commit -m "$(cat <<'EOF'
feat: sync archive — the inbox sweep the README promised (#55)

10-inbox/README.md has always claimed the assistant sweeps the folder and
that nothing lives there. No code moved, archived, or deleted an inbox
file. This adds the move: a processed or parked file goes to
90-archive/inbox/{YYYY-MM}/, so what remains in the inbox is exactly what
still needs processing.

That is also the processed-state fix: the folder becomes the view, so no
index note and no sync-state file are needed. Ids are content hashes, so
an archived file keeps its id and stays deduped.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `scancache` — stop re-parsing and re-hashing the world

`known_recording_ids()` reads and frontmatter-parses every `20-meetings/*.md` on every run; `content_id()` SHA-256s every inbox file on every run. The cache is disposable and keyed on `(mtime_ns, size)`.

**Files:**
- Create: `plugin/lib/vaultlib/scancache.py`
- Modify: `plugin/lib/vaultlib/syncjob.py` (module docstring, imports, `known_recording_ids`, `scan`)
- Test: `scripts/tests/test_vaultlib_syncjob.py`

**Interfaces:**
- Consumes: `vault.atomic_write(path, text)`.
- Produces:
  - `scancache.CACHE_RELPATH: Path` = `99-workflow-config/sync-state/scan-cache.json`
  - `scancache.load(root) -> dict`, `scancache.save(root, cache) -> None`
  - `scancache.stat_key(path) -> Optional[Tuple[int, int]]`
  - `scancache.lookup(cache, section, rel, key) -> Optional[dict]`
  - `scancache.store(cache, section, rel, key, payload) -> None`
  - `scancache.prune(cache, section, live) -> None`
  - `syncjob.known_recording_ids(root, cache=None)` — the added parameter is optional, so `meeting.py:_resolve_target`'s existing `known_recording_ids(root)` call keeps working unchanged.

  `content_id(path)` keeps its exact current signature. Task 3's tests call it directly.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_syncjob.py`:

```python
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
    """A cold cache is a normal state, not a fault. Deleting this file is
    always safe — that is what makes it a cache and not a second ledger."""
    root = make_vault(tmp_path)
    done = root / "10-inbox" / "done.txt"
    done.write_text("processed transcript", encoding="utf-8")
    write_meeting(root, "20-08-26-note", syncjob.content_id(done))
    cache_path = root / "99-workflow-config" / "sync-state" / "scan-cache.json"

    for garbage in ("not json at all", '{"version": 99, "ledger": {}}',
                    '{"version": 1, "ledger": "wrong type", "inbox": {}}'):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(garbage, encoding="utf-8")
        result = syncjob.scan(root)
        assert result["candidates"] == []
        assert result["warnings"] == []


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
```

Add `import json` to the test module's imports if it is not already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q -k "reparse or rehash or cache or replayed or drops_out"`
Expected: FAIL — the cache file is never written, so the first assertion to blow up is `[r for r in reads if "/20-meetings/" in r] == []` with 2,000 entries.

- [ ] **Step 3: Create the cache module**

Create `plugin/lib/vaultlib/scancache.py`:

```python
"""A disposable index of what the vault already says.

The vault is still the ledger. This module never answers a question the
vault cannot — it only remembers the answer so the next run does not
re-parse 2,000 notes and re-hash every recorder export. Every entry is
keyed on (mtime_ns, size); anything that does not match is re-read, so the
cache cannot go stale behind an edit.

A missing, unreadable, malformed, or version-mismatched cache is a normal
cold state and is rebuilt in silence. Deleting this file is always safe.
That property is what makes it a cache and not a second ledger to
reconcile.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Set, Tuple

from . import vault

CACHE_RELPATH = Path("99-workflow-config") / "sync-state" / "scan-cache.json"
CACHE_VERSION = 1
SECTIONS = ("ledger", "inbox")

StatKey = Optional[Tuple[int, int]]


def _empty() -> dict:
    return {"version": CACHE_VERSION, "ledger": {}, "inbox": {}}


def load(root: Path) -> dict:
    """The cache as a plain dict, or a fresh empty one. Never raises."""
    try:
        data = json.loads((root / CACHE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return _empty()
    if any(not isinstance(data.get(section), dict) for section in SECTIONS):
        return _empty()
    return data


def save(root: Path, cache: dict) -> None:
    vault.atomic_write(
        root / CACHE_RELPATH,
        json.dumps(cache, indent=2, sort_keys=True) + "\n")


def stat_key(path: Path) -> StatKey:
    """(mtime_ns, size), or None when the file cannot be stat'd — in which
    case nothing is cached for it and it is read every time."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def lookup(cache: dict, section: str, rel: str, key: StatKey) -> Optional[dict]:
    if key is None:
        return None
    entry = cache.get(section, {}).get(rel)
    if not isinstance(entry, dict):
        return None
    if entry.get("mtime_ns") != key[0] or entry.get("size") != key[1]:
        return None
    return entry


def store(cache: dict, section: str, rel: str, key: StatKey,
          payload: dict) -> None:
    if key is None:
        return
    cache.setdefault(section, {})[rel] = {
        "mtime_ns": key[0], "size": key[1], **payload}


def prune(cache: dict, section: str, live: Set[str]) -> None:
    """Drop entries for files that no longer exist."""
    entries = cache.get(section, {})
    for rel in [rel for rel in entries if rel not in live]:
        del entries[rel]
```

- [ ] **Step 4: Amend the `syncjob` module docstring**

The current docstring promises there is no second state file. That is still true in spirit and must now say so precisely. Replace the docstring at `plugin/lib/vaultlib/syncjob.py:1-9` with:

```python
"""Inbox scan, dedup, the skip list, and the sweep: the deterministic ledger
under /sync-recordings.

The vault itself is the ledger — a recording is synced iff its namespaced
source-recording-id appears in some 20-meetings/*.md. There is no second
ledger to reconcile, so a failed item (which wrote nothing) retries
naturally on the next run. The skip list exists for the one case the ledger
cannot express: a human said "never propose this one again".

scan-cache.json is a cache, not a ledger: it remembers what the vault
already said, keyed on (mtime_ns, size), and is rebuilt in silence whenever
it is missing or does not match. Deleting it is always safe and changes no
answer — see scancache.py.
"""
```

- [ ] **Step 5: Wire the cache into `known_recording_ids` and `scan`**

In `plugin/lib/vaultlib/syncjob.py`, change the import line:

```python
from . import markdown, vault
```

to:

```python
from . import markdown, scancache, vault
```

and add `Optional` to the typing import:

```python
from typing import Dict, List, Optional, Set, Tuple
```

Replace the whole of `known_recording_ids` (currently lines 52-68) with:

```python
def known_recording_ids(root: Path, cache: Optional[dict] = None
                        ) -> Tuple[Dict[str, str], List[str]]:
    """{source-recording-id: meeting relpath} across 20-meetings/, plus
    warnings for unparseable notes (reported, never fatal — one mangled file
    must not stop the sync).

    Only notes whose (mtime_ns, size) changed since the last run are read;
    the rest come from the scan cache, warnings included — a mangled note
    must not be re-read every run, and its warning must not disappear just
    because the read was skipped. Pass `cache` to share one load/save across
    several calls in the same run.
    """
    owns_cache = cache is None
    cache = scancache.load(root) if owns_cache else cache
    ids: Dict[str, str] = {}
    warnings: List[str] = []
    live: Set[str] = set()
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        live.add(rel)
        key = scancache.stat_key(path)
        entry = scancache.lookup(cache, "ledger", rel, key)
        if entry is None:
            try:
                data, _ = markdown.split_frontmatter(
                    path.read_text(encoding="utf-8"))
                rid = data.get("source-recording-id")
                entry = {"recording_id": str(rid) if rid else None,
                         "warning": None}
            except (ValueError, OSError) as exc:
                entry = {"recording_id": None, "warning": f"{rel}: {exc}"}
            scancache.store(cache, "ledger", rel, key, entry)
        if entry.get("warning"):
            warnings.append(entry["warning"])
        if entry.get("recording_id"):
            ids[entry["recording_id"]] = rel
    scancache.prune(cache, "ledger", live)
    if owns_cache:
        scancache.save(root, cache)
    return ids, warnings
```

Add this helper immediately after `content_id` (leave `content_id` itself untouched — it is the hashing primitive and Task 3's tests call it directly):

```python
def _cached_content_id(root: Path, path: Path, cache: dict) -> str:
    """content_id, but only for files whose (mtime_ns, size) changed.

    The inbox legitimately holds large recorder exports, and a file can sit
    pending across several runs before it is classified.
    """
    rel = path.relative_to(root).as_posix()
    key = scancache.stat_key(path)
    entry = scancache.lookup(cache, "inbox", rel, key)
    if entry is not None and entry.get("content_id"):
        return str(entry["content_id"])
    recording_id = content_id(path)
    scancache.store(cache, "inbox", rel, key, {"content_id": recording_id})
    return recording_id
```

Then replace the body of `scan` (currently lines 92-121) with:

```python
def scan(root: Path) -> dict:
    """Partition inbox files into candidates / already synced / skipped.

    Which candidates are captures, and which of those are meetings, is
    judgment and stays with the model; this returns every regular file with
    enough metadata to decide.
    """
    cache = scancache.load(root)
    known, warnings = known_recording_ids(root, cache)
    skipped_ids = read_skip_list(root)
    candidates, synced, skipped = [], [], []
    live: Set[str] = set()
    inbox = root / INBOX_DIR
    for path in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if not path.is_file() or path.name in _IGNORED_NAMES \
                or path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        live.add(rel)
        rid = _cached_content_id(root, path, cache)
        entry = {
            "name": path.name,
            "path": rel,
            "size": path.stat().st_size,
            "recording_id": rid,
        }
        if rid in known:
            synced.append({**entry, "synced_as": known[rid]})
        elif rid in skipped_ids:
            skipped.append(entry)
        else:
            candidates.append(entry)
    scancache.prune(cache, "inbox", live)
    scancache.save(root, cache)
    return {"candidates": candidates, "already_synced": synced,
            "skipped": skipped, "known_ids_count": len(known),
            "warnings": warnings}
```

`dedup()` and `reconcile_reviews()` are unchanged. `dedup` calls `known_recording_ids(root)` with no cache argument, which loads and saves its own — correct, it is a standalone entry point.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q`
Expected: PASS, whole file — the ten pre-existing tests included. The 2,000-meeting test takes a few seconds; that is expected.

- [ ] **Step 7: Confirm the cache did not change any answer**

Run: `python3 -m pytest scripts/tests -q`
Expected: PASS. `test_vaultlib_meeting.py` exercises `known_recording_ids` indirectly through `meeting.write`'s write-time ledger re-check — if the optional `cache` parameter broke that call site, it fails here.

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/scancache.py plugin/lib/vaultlib/syncjob.py scripts/tests/test_vaultlib_syncjob.py
git commit -m "$(cat <<'EOF'
perf: scan cache — stop re-parsing and re-hashing the world (#55)

known_recording_ids parsed every 20-meetings/*.md and content_id SHA-256'd
every inbox file on every run. Fine at 9 meetings; real cost at 2,000 plus
large recorder exports.

The cache is keyed on (mtime_ns, size) and is rebuilt in silence when it
is missing, corrupt, or version-mismatched — deleting it is always safe
and changes no answer. The vault remains the ledger. Warnings for
unparseable notes are cached and replayed, so a mangled file is neither
re-read every run nor silently dropped from the report.

Measured by file-read count on a synthetic 2,000-meeting vault, not wall
clock.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `update-queue` — notes feed project state but never the meeting count

`_index_meetings()` feeds two consumers that must now diverge. This is the subtlest change in the batch and the one most likely to regress silently.

**Files:**
- Modify: `plugin/lib/vaultlib/updatequeue.py:70-90` (`_index_meetings`), `:143-145` and `:165-176` and `:222-228` (`run`)
- Test: `scripts/tests/test_vaultlib_updatequeue.py`

**Interfaces:**
- Consumes: Task 1's `type: note` enum member.
- Produces: no signature change. `updatequeue.run(root, today, executive)` keeps its exact shape; only which meetings feed which number changes.

- [ ] **Step 1: Write the failing test**

The module's `write_meeting()` helper hardcodes `type: meeting`. Give it a type parameter first — find this helper in `scripts/tests/test_vaultlib_updatequeue.py`:

```python
def write_meeting(root: Path, stem: str, *, date_value="2026-06-10T10:00",
                  review_status="confirmed", projects=(), attendees=()) -> None:
    proj = ", ".join(projects)
    att = ", ".join(attendees)
    (root / "20-meetings" / f"{stem}.md").write_text("\n".join([
        "---", f"date: {date_value}", "type: meeting",
        f"review_status: {review_status}",
        f"projects: [{proj}]", f"attendees: [{att}]", "---", "", "- x", "",
    ]), encoding="utf-8")
```

and replace it with:

```python
def write_meeting(root: Path, stem: str, *, date_value="2026-06-10T10:00",
                  review_status="confirmed", projects=(), attendees=(),
                  type_value="meeting") -> None:
    proj = ", ".join(projects)
    att = ", ".join(attendees)
    (root / "20-meetings" / f"{stem}.md").write_text("\n".join([
        "---", f"date: {date_value}", f"type: {type_value}",
        f"review_status: {review_status}",
        f"projects: [{proj}]", f"attendees: [{att}]", "---", "", "- x", "",
    ]), encoding="utf-8")
```

Then append this test to the same file:

```python
def test_a_note_updates_project_state_but_is_not_counted_as_a_meeting(tmp_path):
    """Both halves in one test on purpose: a refactor that satisfies one and
    drops the other is exactly the silent regression this guards.

    A forwarded email carrying project context must reach project-state
    synthesis and decision capture — that is why captures route here at all.
    It must not inflate meetings-7d, which feeds Projects.base: counting an
    email as a meeting is the quiet kind of falsehood the vault's third
    golden rule forbids.
    """
    root = make_vault(tmp_path)
    write_person(root, "priya-nathan")
    write_project(root, "yard-automation", last_updated="2026-06-01")
    write_meeting(root, "10-06-26-capture", type_value="note",
                  date_value="2026-06-10T09:00",
                  projects=["yard-automation"], attendees=["priya-nathan"])

    result = updatequeue.run(root, "2026-06-12", "exec-morgan")

    index = (root / "30-projects" / "yard-automation" / "index.md").read_text(
        encoding="utf-8")
    assert "meetings-7d: 0" in index
    assert "meetings-30d: 0" in index
    assert "key-people: []" in index

    person = (root / "50-people" / "priya-nathan.md").read_text(
        encoding="utf-8")
    assert "meetings-7d: 0" in person

    queued = [entry["slug"] for entry in result["projectsNeedingUpdate"]]
    assert queued == ["yard-automation"]
    assert result["projectsNeedingUpdate"][0]["newFiles"] == [
        "20-meetings/10-06-26-capture.md"]


def test_a_meeting_alongside_a_note_counts_once(tmp_path):
    """The filter must remove notes, not everything."""
    root = make_vault(tmp_path)
    write_person(root, "priya-nathan")
    write_project(root, "yard-automation", last_updated="2026-06-01")
    write_meeting(root, "10-06-26-capture", type_value="note",
                  date_value="2026-06-10T09:00",
                  projects=["yard-automation"], attendees=["priya-nathan"])
    write_meeting(root, "10-06-26-steerco", type_value="steerco",
                  date_value="2026-06-10T14:00",
                  projects=["yard-automation"], attendees=["priya-nathan"])

    updatequeue.run(root, "2026-06-12", "exec-morgan")

    index = (root / "30-projects" / "yard-automation" / "index.md").read_text(
        encoding="utf-8")
    assert "meetings-7d: 1" in index
    assert "key-people: [priya-nathan]" in index
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_updatequeue.py -q -k "note_updates or alongside"`
Expected: FAIL — `assert "meetings-7d: 0" in index` fails because the note was counted, so the index says `meetings-7d: 1`.

- [ ] **Step 3: Record the type on each indexed meeting**

In `plugin/lib/vaultlib/updatequeue.py`, find the dict appended inside `_index_meetings` (around line 80):

```python
        meetings.append({
            "file": rel,
            "date": _parse_first_iso_date(data.get("date")),
            "review_status": data.get("review_status"),
```

and insert one line so it reads:

```python
        meetings.append({
            "file": rel,
            "date": _parse_first_iso_date(data.get("date")),
            "type": data.get("type"),
            "review_status": data.get("review_status"),
```

- [ ] **Step 4: Split the two consumers**

Add this constant near the top of the module, beside the other module-level constants:

```python
# A type: note is a capture, not a meeting. It feeds project-state synthesis
# and decision capture — that is why captures route into 20-meetings/ at all
# — but it must never move a meeting count. meetings-7d feeds Projects.base;
# counting an email as a meeting is a quiet lie in a number a human reads.
NOT_A_MEETING = "note"
```

Then in `run()`, find (around line 143):

```python
    meetings, warnings = _index_meetings(root)
    confirmed = [m for m in meetings
                 if m["review_status"] == "confirmed" and m["date"]]
```

and replace with:

```python
    meetings, warnings = _index_meetings(root)
    confirmed = [m for m in meetings
                 if m["review_status"] == "confirmed" and m["date"]]
    # confirmed drives the queue and the self-check; countable drives every
    # number written into a note. The two lists are deliberately different.
    countable = [m for m in confirmed if m["type"] != NOT_A_MEETING]
```

Next, inside the projects loop, find:

```python
        for_project = [m for m in confirmed if slug in m["projects"]]
        m7 = sum(1 for m in for_project if m["date"] > d7)
        m30 = sum(1 for m in for_project if m["date"] > d30)
        counts: Dict[str, int] = {}
        for meeting in for_project:
```

and replace with:

```python
        for_project = [m for m in confirmed if slug in m["projects"]]
        countable_for_project = [m for m in for_project
                                 if m["type"] != NOT_A_MEETING]
        m7 = sum(1 for m in countable_for_project if m["date"] > d7)
        m30 = sum(1 for m in countable_for_project if m["date"] > d30)
        counts: Dict[str, int] = {}
        for meeting in countable_for_project:
```

Leave `new_meetings = [m for m in for_project if m["date"] > last_updated]` exactly as it is — the queue must see notes.

Finally, in the people loop, find:

```python
        m7 = sum(1 for m in confirmed
                 if slug in m["attendees"] and m["date"] > d7)
        m30 = sum(1 for m in confirmed
                  if slug in m["attendees"] and m["date"] > d30)
```

and replace `confirmed` with `countable` in both:

```python
        m7 = sum(1 for m in countable
                 if slug in m["attendees"] and m["date"] > d7)
        m30 = sum(1 for m in countable
                  if slug in m["attendees"] and m["date"] > d30)
```

Leave the `self_check(confirmed, ...)` call unchanged: a note referencing an active project that was not queued is still a silent skip worth flagging.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_updatequeue.py -q`
Expected: PASS, whole file. The pre-existing metrics tests all use `type: meeting`, so none of them should move.

Two tests in that file run against the real demo vault — `test_cli_update_queue_envelope` and `test_fixture_vault_is_a_fixed_point_of_update_queue`. Both are safe: `fixtures/demo-vault/20-meetings/` today holds only `1:1`, `brainstorm`, `meeting`, `status-update`, `steerco` and `workshop`, so the filter removes nothing and every count stays put. If either fails, the filter is matching more than `note` — check `NOT_A_MEETING` is compared with `!=` and not something looser.

- [ ] **Step 6: Run the full local gate**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

- [ ] **Step 7: Commit**

```bash
git add plugin/lib/vaultlib/updatequeue.py scripts/tests/test_vaultlib_updatequeue.py
git commit -m "$(cat <<'EOF'
fix: a type: note feeds project state but never a meeting count (#55)

_index_meetings feeds two consumers that must diverge now that captures
route into 20-meetings/. The project-state queue and its existingDecisions
projection must see notes — feeding a forwarded email into project state
and decision capture is why captures route there at all. meetings-7d,
meetings-30d and key-people must not: they feed Projects.base, and
counting an email as a meeting is a quiet lie in a number a human reads.

Both halves are asserted in one test, so a refactor cannot satisfy one and
drop the other.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `/sync-recordings` — classify, route, sweep, report

The skill is the only thing that decides what an inbox item becomes. Everything before this task is plumbing it can now call.

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` (Inbox paragraph at ~109-119; step 6; the summary block at ~290-300)
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: `sync archive --vault <path> --path <relpath> [--today <ISO>]` (Task 3); `meeting write` accepting `type: note` with optionally-empty `attendees` (Task 2); the `calendar-not-applicable` reason (Task 1).
- Produces: skill prose only. No later task depends on it.

**Read before editing:** this file was substantially rewritten by PR #62 (`ea1aac7`). Read it in full first.

**Fence warning, for every step below.** Several replacement blocks in this task are shown wrapped in **four** backticks. That is *this plan's* fencing, needed because the block being quoted itself contains three-backtick ```bash blocks. Copy the **contents** into `SKILL.md`, never the outer four-backtick wrapper — the inner three-backtick fences are part of the text you are inserting and must survive verbatim. Two of its rules constrain these edits: `test_skill_contracts.py::test_no_skill_reads_machine_decisions_from_prose` fails any SKILL.md containing the strings `identity.md` or `tools-and-systems`, and the adapter gate means everything below runs only when `adapters.inbox.enabled` is true.

- [ ] **Step 1: Write the failing contract tests**

Append to `scripts/tests/test_skill_contracts.py`. Reuse the module's existing helpers for locating and reading skill files — read its top first; the assertions below are what matters.

```python
def test_sync_recordings_routes_non_meetings_to_a_type_note():
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "type: note" in text, "no non-meeting destination documented"
    assert "calendar-not-applicable" in text
    # The ambiguity rule is the load-bearing sentence: a wrongly written note
    # sits in Triage, a wrongly parked file is invisible.
    assert "write the `note`" in text


def test_sync_recordings_sweeps_the_inbox():
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "sync archive" in text, "the sweep the README promises is missing"
    assert "90-archive/inbox/" in text


def test_sync_recordings_no_longer_asks_the_user_to_archive_by_hand():
    """F0: the skill used to tell the user to do the thing the plugin
    promised to do and never did."""
    text = (SKILLS_DIR / "sync-recordings" / "SKILL.md").read_text(encoding="utf-8")
    assert "so the user can archive them" not in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q -k "type_note or sweeps or by_hand"`
Expected: all three FAIL.

- [ ] **Step 3: Replace the Inbox paragraph with classification and the sweep**

In `plugin/skills/sync-recordings/SKILL.md`, find this exact paragraph in `### 1. Scan and dedup`:

```
`candidates` are files whose content hash is in no meeting note and not on
the skip list. Which candidates are actually transcripts is your judgment —
read the head of each file; a forwarded email that is meeting notes by
another name qualifies, a random PDF does not. Report `already_synced` files
so the user can archive them (inbox discipline: nothing lives there).
```

Replace it with:

````
`candidates` are files whose content hash is in no meeting note and not on
the skip list. Read the head of each and classify it — this is judgment, and
it has exactly three outcomes:

| Shape | Outcome |
|---|---|
| A record of an interaction — transcript, meeting recording, meeting notes | a meeting note, the normal path below |
| Carries context about people, projects or entities but is not a meeting — forwarded correspondence, a voice memo, pasted context | a capture: a note with `type: note` |
| Not a capture at all — a whitepaper, a deck, a spreadsheet, an image, a stray binary | **park** it |

**When you cannot decide between a capture and a park, write the `note`.**
A wrongly written note sits in Triage and is one click from `archived: true`;
a wrongly parked file is invisible and on a never-propose-again list. The
error direction matters more than the error rate. Both modes decide all
three outcomes — `--unattended` does not defer, because routing captures
into the pipeline is the point.

A capture's payload differs from a meeting's in five fields and nothing else:

- `type: note`
- `calendar_match: false` — no calendar is ever consulted for a capture.
  `calendar-subject` is still required and still non-empty: give it the
  item's own subject (a forwarded email's `Subject:` line) or a short
  descriptive title (a voice memo). It is the Subject column in
  `Meetings.base`, so this is the label a human triages by.
- `recording-duration: 0` — nothing was recorded
- `source` is still the arrival channel: `email` for forwarded mail,
  `recorder` for a voice memo, `manual` for pasted text
- `confidence` is `medium` or `low`, and the calendar reason is
  `calendar-not-applicable` — never `no-calendar-match` (that means you
  searched) and never `calendar-tool-unavailable` (that means you tried)

`attendees` are the people the item names, resolved through `person ensure`
as usual. A capture that names nobody may pass `attendees: []` — it is the
one type for which that is valid — and still carries `all-attendees-known`,
because with nobody named there is nobody unknown. `takeaways` and `debrief`
keep their meanings: what this says, and what it means.

To park an item, skip it and sweep it:

```bash
python3 "$VAULTLIB" sync skip --vault "$VAULT" --id "inbox:<hash>"
python3 "$VAULTLIB" sync archive --vault "$VAULT" --path "10-inbox/<name>"
```

Report every parked item in the summary **with why it was not a capture** —
a park is a decision, not a throughput number.

Every file `already_synced` reports is swept the same way (it was processed
by an earlier run, or dropped back in). Ids are content hashes, so an
archived file keeps its id and stays deduped.
````

- [ ] **Step 4: Add the sweep to the write step**

Find the end of `### 6. Extract and write` — the step that fans out subagents calling `meeting write`. Append this paragraph to it:

````
**Then sweep what you wrote.** For each recording whose `meeting write`
returned a `path` that exists on disk, move its inbox source out of the
queue:

```bash
python3 "$VAULTLIB" sync archive --vault "$VAULT" --path "10-inbox/<name>"
```

Only after the note is verified against disk — a file that produced nothing
stays in the inbox and retries next run, which is the same failure rule as
everywhere else here. This applies to inbox-sourced items only; Plaud and
M365 recordings have no inbox file to move.

`10-inbox/` is the pending set. What is left in it after a run is exactly
what still needs processing — that is what makes the folder answerable
without running anything, and why no index note or state file exists.
````

- [ ] **Step 5: Add the three summary lines**

Find the summary template in `### 7. Summarize` (SKILL.md:292) and add the three new lines shown below. Keep the `Adapters:` line exactly as PR #62 left it — it carries the refuse-and-alert vocabulary and must not be reverted.

**Fence warning.** In `SKILL.md` that block is fenced with **three plain backticks and no language tag**. Leave it that way. The four backticks and the `markdown` tag below are *this plan's* nesting, needed only because the plan quotes a block that quotes backticks — do not copy them into `SKILL.md`.

````markdown
## Sync Complete
**Processed:** {N} → `20-meetings/` ({list the stems})
**Captures:** {N} → `20-meetings/` as `type: note` ({list the stems})
**Parked:** {N} → `90-archive/inbox/` ({filenames, each with why it was not a capture})
**Inbox swept:** {N} files → `90-archive/inbox/{YYYY-MM}/` · {N} left pending in `10-inbox/`
**New people:** {N} created in `50-people/`
**Reviewed ticks folded:** {N} confirmed
**Needs attention:** {N} (would have overwritten confirmed notes)
**Skipped / errors:** {N} (will retry next run)
**Adapters:** inbox ok · plaud ok | REFUSED (account-mismatch | no-account-hint) | disabled | unavailable · m365 disabled | not yet supported
**Calendar enrichment:** ok | UNAVAILABLE
````

Add this sentence directly under the block:

```
`Inbox swept` counts every file moved this run, captures and parks together,
and reports the pending remainder — that remainder is the number the
executive actually cares about. Count it from disk like everything else in
this step.
```

- [ ] **Step 6: Verify the fences still balance**

Your Step 3 and Step 4 edits both add ```bash blocks inside prose. Confirm nothing left an unclosed fence — a truncated `SKILL.md` is read wrong by every renderer and by the agent loading the skill:

```bash
python3 - plugin/skills/sync-recordings/SKILL.md <<'PY'
import pathlib, re, sys
OPEN = re.compile(r'^(`{3,})([a-zA-Z][a-zA-Z0-9]*)\s*$')
CLOSE = re.compile(r'^(`{3,})\s*$')
for path in sys.argv[1:]:
    lines = pathlib.Path(path).read_text().split("\n")
    i, ok = 0, True
    while i < len(lines):
        m = OPEN.match(lines[i])
        if m:
            ticks = m.group(1)
            j = i + 1
            while j < len(lines):
                c = CLOSE.match(lines[j])
                if c and len(c.group(1)) == len(ticks):
                    break
                j += 1
            if j >= len(lines):
                print(f"UNCLOSED {m.group(2)} block opened line {i+1}")
                ok = False
                break
            i = j + 1
        else:
            i += 1
    print(f"{path}: {'fences OK' if ok else 'FENCE PROBLEM'}")
PY
```

Expected: `fences OK`.

- [ ] **Step 7: Run the contract tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS, whole file. `test_every_cli_invocation_named_by_a_skill_exists` now checks `sync archive` against the parser from Task 3, and `test_no_skill_reads_machine_decisions_from_prose` still passes because nothing added references `identity.md` or `tools-and-systems`.

- [ ] **Step 8: Run the full local gate**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

- [ ] **Step 9: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "$(cat <<'EOF'
feat: /sync-recordings classifies, routes and sweeps (#55)

The inbox had one consumer and one output type, so a forwarded email
carrying project context became a meeting note with type: status-update —
asserting a meeting that never happened.

Three outcomes now: a meeting, a capture (type: note), or a park. When the
call is close, write the note: a wrongly written note sits in Triage one
click from archived, while a wrongly parked file is invisible.

Every processed or parked file is then swept to 90-archive/inbox/, so what
remains in 10-inbox/ is exactly what still needs processing. The step that
told the user to archive already-synced files by hand is gone — that was
the skill asking a human to do what the README promised the plugin did.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Vault-facing surfaces and release

Everything a human sees: the README that has been lying, the Base column, the fixture that proves the capture branch, and the version.

**Files:**
- Rewrite: `template/10-inbox/README.md`
- Create: `template/90-archive/README.md`
- Modify: `template/20-meetings/Meetings.base` (Triage `order` only)
- Modify: `template/CLAUDE.md` (Inbox Discipline section)
- Modify: `migrations/README.md` (pending-migration note)
- Create: `fixtures/demo-vault/10-inbox/2026-08-22-industry-report-yard-automation.txt`
- Modify: `plugin/.claude-plugin/plugin.json` (version)
- Modify: `CHANGELOG.md` (one line under `Unreleased`)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Rewrite the inbox README**

Replace the whole of `template/10-inbox/README.md` with:

```markdown
# Inbox

The landing zone for anything not yet processed into a vault object: meeting
transcripts, voice memos, forwarded emails, recorder exports, documents to file.

Rules:

- **Everything unprocessed lands here first.** Drop files in; don't sort them.
- **What is in this folder is what still needs processing.** The sync moves
  every file it handles out to `90-archive/inbox/{YYYY-MM}/` — whether it
  became a note or was parked as not-a-capture. So the folder answers "what
  is still outstanding?" by itself, without running anything.
- **Processing produces notes in `20-meetings/`.** A recording of an
  interaction becomes a meeting note. Something that carries context but is
  not a meeting — a forwarded email, a voice memo — becomes a note with
  `type: note`. Both land in the same triage queue, `Meetings.base`.
- **Anything that is not a capture is parked**, not filed. A whitepaper or a
  deck goes to the archive, and the run that parked it says why in its
  summary; the sync does not decide where your reference material belongs.
- Skills never leave their outputs in this folder.
```

- [ ] **Step 2: Create the archive README**

Create `template/90-archive/README.md`, and **delete `template/90-archive/.gitkeep`** in the same step. The convention in this template is that a folder keeps a `.gitkeep` only while it has no real content — `10-inbox/` carries a README and no `.gitkeep`, while `60-daily-notes/` and `80-thoughts-ideas/` carry a `.gitkeep` and no README. The README keeps the folder in git on its own.

```bash
git rm template/90-archive/.gitkeep
```


```markdown
# Archive

Completed and historical items. Nothing reads from here — it exists so that
nothing has to be deleted.

`inbox/{YYYY-MM}/` is written by the sync: every file it processed into a
note, and every file it parked as not-a-capture, moved out of `10-inbox/` so
that folder holds only what is still pending. The original bytes are
untouched, so a file here can always be dropped back into `10-inbox/` if
something needs redoing — though a note that was already written will keep
it deduped, so delete that note first.
```

- [ ] **Step 3: Make `type` visible in Triage**

In `template/20-meetings/Meetings.base`, find the `Triage` view's `order` list:

```yaml
    order:
      - formula.open
      - date
      - calendar-subject
      - calendar_match
      - attendees
      - projects
      - reviewed
      - archived
      - recording-duration
      - source
      - type
```

and replace it with:

```yaml
    order:
      - formula.open
      - date
      - type
      - calendar-subject
      - calendar_match
      - attendees
      - projects
      - reviewed
      - archived
      - recording-duration
      - source
```

Only the position of `type` changes. Do not touch the view's `filters`, `sort`, or `rowHeight`, and do not add a view — `scripts/tests/test_bases_views.py` asserts filter behaviour and view coverage, and a new view needs a row in its `EXPECTED` table.

- [ ] **Step 4: Update the vault's Inbox Discipline rule**

In `template/CLAUDE.md`, find:

```
## Inbox Discipline

Unprocessed capture lands in `10-inbox/` and only there. Processing skills
consume from the inbox and write results to the proper object folders. Skill
outputs never land in the inbox.
```

and replace with:

```
## Inbox Discipline

Unprocessed capture lands in `10-inbox/` and only there. Processing skills
consume from the inbox and write results to the proper object folders. Skill
outputs never land in the inbox.

Processing also empties it: every file the sync handles moves to
`90-archive/inbox/{YYYY-MM}/`, so what remains in `10-inbox/` is exactly
what is still outstanding. A capture that is not a meeting — a forwarded
email, a voice memo — becomes a note with `type: note` in `20-meetings/`,
sharing the one triage queue rather than starting a second one.
```

- [ ] **Step 5: Note the pending migration**

In `migrations/README.md`, find the sentence ending the pending-migration paragraph:

```
Also: add `99-workflow-config/config.json`
(template default, then fill timezone/executive/adapters from the vault's
prose context — #54 moved machine decisions out of prose).
```

and append after it, in the same paragraph:

```
Also: refresh `10-inbox/README.md` and add `90-archive/README.md` — #55 made
the inbox self-emptying, and a vault provisioned before that keeps a README
promising a sweep that its copy of the plugin did not perform.
```

- [ ] **Step 6: Add the park-branch fixture**

Create `fixtures/demo-vault/10-inbox/2026-08-22-industry-report-yard-automation.txt`. It must exercise the third branch — something plainly not a capture.

**It must also carry at least 30 non-empty lines.** `scripts/tests/test_fixtures_ontology.py:669` (`test_inbox_transcripts_are_realistically_thick`) asserts that of *every* `.txt` in the demo inbox — the guard #59 added because thin fixtures capped what routing could be exercised against. The content below clears it at 37; if you shorten it, count with `grep -c '[^[:space:]]'` before committing.

Keep it clean-room (no real client, no real person; the demo vault's fictional entities are Meridian Freight Holdings, Nordbridge Components and Cascadia Intermodal):

```
YARD AUTOMATION IN EUROPEAN INTERMODAL LOGISTICS
Market Outlook 2026-2030 — Sample Chapter

Published by Harbourline Research (fictional). Distributed for evaluation.

CONTENTS

1. Executive summary .................................... 3
2. Market sizing and segmentation ....................... 11
3. Automation maturity by terminal class ................ 24
4. Vendor landscape ..................................... 38
5. Procurement patterns and contract structures ......... 52
6. Outlook and scenarios ................................ 67

1. EXECUTIVE SUMMARY

European intermodal terminals are entering the second wave of yard
automation. Where the first wave optimised crane scheduling in isolation,
the second integrates yard, gate and hinterland planning into a single
control layer. Terminals in the 200,000-800,000 TEU band show the widest
spread in automation maturity and therefore the largest addressable gap.

Adoption is gated less by technology than by contract structure. Multi-year
volume commitments remain the dominant financing mechanism, and terminals
without them consistently defer investment past the point where the
business case peaks.

Three findings frame the rest of this report.

First, the integration layer is where value concentrates. Terminals that
automated cranes alone recovered a fraction of the modelled benefit,
because gate congestion simply moved the queue rather than removing it.

Second, the vendor market is consolidating faster than buyers expect.
Single-vendor consolidation has become the default procurement posture in
the segment, which shortens evaluation cycles but raises switching costs
materially over a five-year horizon.

Third, workforce transition is the most consistently underestimated line
item. Programmes that budgeted for retraining at under eight percent of
capital cost reported schedule slippage at roughly twice the rate of those
that budgeted above twelve percent.

Method note: findings draw on 41 terminal operators surveyed between
January and May 2026, supplemented by 12 structured interviews with
operations directors. Terminal names are withheld under the survey's
confidentiality terms.

[Sample chapter ends. Full report available under evaluation licence.]
```

This is reference material: no interaction, no participants, nothing about the executive's own work. `/sync-recordings` must park it, not write a note.

- [ ] **Step 7: Verify the fixture parks rather than routes**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py scripts/tests/test_bases_views.py -q`
Expected: PASS.

The one test that *does* see this file is `test_inbox_transcripts_are_realistically_thick`, which requires ≥30 non-empty lines from every inbox `.txt`. Confirm before relying on the run:

```bash
grep -c '[^[:space:]]' fixtures/demo-vault/10-inbox/2026-08-22-industry-report-yard-automation.txt
```

Expected: 37. Nothing else in either file reads inbox fixtures — they validate note frontmatter and Base filters — so a failure elsewhere means the fixture landed in the wrong folder.

- [ ] **Step 8: Bump the version**

In `plugin/.claude-plugin/plugin.json`, change:

```json
  "version": "0.5.0",
```

to:

```json
  "version": "0.6.0",
```

`0.5.0` was taken by #54; CI's version guard rejects a version equal to the target branch's or already tagged.

- [ ] **Step 9: Add the changelog line**

In `CHANGELOG.md`, insert as the **first** bullet under `## Unreleased`:

```markdown
- **The inbox empties itself, and context that isn't a meeting is captured
  honestly.** Files you drop in `10-inbox/` now move to `90-archive/inbox/`
  once they've been handled, so what's left in the folder is exactly what's
  still outstanding — you can answer "what hasn't been processed?" by
  looking, without running anything. And an item that carries context but
  isn't a meeting — a forwarded email, a voice memo — is now written as a
  capture (`type: note`) instead of being filed as a meeting that never
  happened. It shows up in the same review queue, feeds the same project
  updates, and no longer inflates your meeting counts. Anything that isn't a
  capture at all, like a report or a deck, is parked with the reason given
  rather than forced into a note. (#55)
```

- [ ] **Step 10: Run the full local gate**

```bash
python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q
```

Expected: all pass. `lint_plugin.py` greps the clean-room denylist across `plugin/`, `template/` **and** `fixtures/` — if the new fixture trips it, a name in it collides with the denylist and must be changed.

- [ ] **Step 11: Verify against a real vault**

Build a throwaway vault and confirm the sweep actually moves files, rather than trusting the unit tests alone:

```bash
python3 scripts/make_test_vault.py test-vaults/inbox-lifecycle-$(date +%Y%m%d) && ls test-vaults/inbox-lifecycle-$(date +%Y%m%d)/10-inbox/
```

Expected: the demo inbox contains the four existing fixtures plus the new industry report. Then exercise the CLI directly:

```bash
V=test-vaults/inbox-lifecycle-$(date +%Y%m%d)
python3 plugin/lib/vaultlib/cli.py sync scan --vault "$V"
python3 plugin/lib/vaultlib/cli.py sync archive --vault "$V" --path 10-inbox/2026-08-22-industry-report-yard-automation.txt --today 2026-08-25
ls "$V"/10-inbox/ "$V"/90-archive/inbox/2026-08/
```

Expected: `sync scan` returns five candidates and writes `99-workflow-config/sync-state/scan-cache.json`; the archive call moves the report; the inbox is down to four files. Test vaults live in the main checkout's gitignored `test-vaults/`, never in a worktree and never in `/tmp`.

- [ ] **Step 12: Commit**

```bash
git add template/10-inbox/README.md template/90-archive/README.md template/20-meetings/Meetings.base template/CLAUDE.md migrations/README.md fixtures/demo-vault/10-inbox/ plugin/.claude-plugin/plugin.json CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs: inbox lifecycle — README, Base, fixture, 0.6.0 (#55)

10-inbox/README.md has shipped since the template extraction claiming the
assistant sweeps the folder and that nothing lives there. Neither was true.
It now describes what the code does, and 90-archive/ gets a README because
it is now a destination the plugin writes to.

type moves to the second column in Meetings.base's Triage view so a capture
reads at a glance against the meeting types. A non-capture fixture is added
so the park branch is demonstrable in the demo vault.

An already-provisioned vault keeps the old README, so the refresh is noted
on the structure-version 2 candidate list alongside config.json.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

Run against the spec after the last task, before opening the PR.

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 Ontology and schema | Task 1 |
| §2 `meeting.py` relaxation | Task 2 |
| §3 `syncjob.archive` + CLI | Task 3 |
| §4 `scancache.py` | Task 4 |
| §5 Classification, sweep calls, summary | Task 6 |
| §6 `updatequeue` metrics/queue divergence | Task 5 |
| §7 Template, Base, docs, version, changelog | Task 7 |
| Decision 8 (pending migration note) | Task 7 step 5 |
| Decision 9 (inbox stays behind the #54 adapter gate) | Task 6 — no code change needed; the gate already wraps step 1 |

**Acceptance criteria:**

| Issue criterion | Verified by |
|---|---|
| Answer "what in my inbox is not yet processed?" in Obsidian without running anything | Task 3 + Task 6 (the folder is the pending set); Task 7 step 11 confirms it on a real vault |
| Scan cost no longer re-hashes/re-parses the world (2k-meeting vault) | Task 4 step 1, `test_second_scan_reparses_no_meeting` and `test_second_scan_rehashes_no_inbox_file` |
| A non-meeting item ends up somewhere defensible, routing surfaced in the summary | Task 1 + 2 + 6; `test_sync_recordings_routes_non_meetings_to_a_type_note` |
| README describes only behavior that exists | Task 7 step 1; `test_sync_recordings_no_longer_asks_the_user_to_archive_by_hand` |

**Type consistency:** `NOT_A_MEETING = "note"` (Task 5) is the same string as the enum member added in Task 1 and the `type: note` written by Task 6. `vault.ARCHIVE_DIR` (Task 3) is consumed only by `syncjob.ARCHIVE_DIR`. `syncjob.archive(root, relpath, today)` is called by `cli.py` with `vault.today_iso(args.today)` already resolved, and re-validates internally. `known_recording_ids(root, cache=None)` (Task 4) keeps `meeting.py:_resolve_target`'s existing one-argument call working.

**Ordering:** Task 2 requires Task 1. Task 4 touches `syncjob.py` after Task 3, so run them in order. Task 6 requires 1, 2 and 3. Task 5 is independent of 3 and 4 but requires 1. Task 7 is last.

## Finishing

After Task 7, use `superpowers:requesting-code-review`, then `superpowers:finishing-a-development-branch`. The PR body needs the checklist from `CONTRIBUTING.md`, including the version bump (0.5.0 → 0.6.0), the changelog line, and `Closes #55`.
