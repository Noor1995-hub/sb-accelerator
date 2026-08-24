# P2a — `/sync-recordings` Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the recorder-transcript intake skill (#14): a three-adapter capture pipeline (`inbox` / `plaud` / `m365`) over new deterministic vaultlib subcommands, with the §Meeting ontology extension and meeting-fixture enrichment.

**Architecture:** Adapters do discovery + fetch into a normalized capture bundle; one source-agnostic pipeline (dedup → enrichment → confidence stamp → extraction → `meeting write`) handles everything after. All writes go through `plugin/lib/vaultlib/cli.py`; the model owns judgment (project linking, prose), the CLI owns mechanics (dedup, validation, collision guards, atomic writes).

**Tech Stack:** Python stdlib only in `plugin/lib/` (3.10 floor); PyYAML/pytest only in `scripts/` (dev side). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-23-daily-loop-port-design.md` (P2a row of "Scope: two PRs"). Conventions: `docs/superpowers/specs/2026-08-23-object-skills-port-design.md`, `plugin/CLAUDE.md`.

## Global Constraints

- **Stdlib only, Python 3.10 floor** for everything under `plugin/lib/` — no PyYAML, no `tomllib` patterns from 3.11+, no `match` statements you aren't sure about; CI has a `runtime floor (python 3.10)` job that will catch violations.
- **Vault root is always a parameter** (`--vault`), never derived. Writes go through `vault.atomic_write` (UTF-8, LF).
- **CLI envelope:** every run prints exactly one JSON object — `{"ok": true, "result": {...}}` exit 0, or `{"ok": false, "error": "...", "hint": "..."}` exit 1. New modules raise their own `XxxError`; `cli.main` catches and wraps.
- **Clean-room:** nothing under `plugin/`, `template/`, `fixtures/` may contain `michael`, `bulthe`, `busdev` (except `upstreamed-from: busdev@` provenance), or client names. "Plaud" (vendor) is allowed — it is not on `scripts/cleanroom-denylist.txt`. No Dutch strings (the lab's `> Datum:` becomes `> Recorded:`).
- **No hardcoded timezone.** Brussels/CET logic from the lab does NOT port; timezone or UTC offset is always a caller argument.
- **Ontology is machine truth:** after editing `template/99-workflow-config/reference/ontology.md`, run `python3 scripts/compile_ontology.py` and commit the regenerated `plugin/lib/vaultlib/schema.json` in the same commit — `test_compile_ontology.py` diffs it.
- **Every commit message ends with the exact trailer** (own line): `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Verification trio** must pass before claiming any task done: `python3 scripts/lint_plugin.py` · `python3 scripts/validate_template.py` · `python3 -m pytest scripts/tests -q` (baseline: 515 passed).
- Work on the current branch `claude/daily-loop-skill-ports-d83122` (it already carries the design doc). Never commit to `main`.

## File Structure

```
plugin/lib/vaultlib/
  dates.py        NEW — UTC window computation (timezone/offset resolution)
  syncjob.py      NEW — inbox scan, dedup, skip list, reconcile-reviews
  plaud.py        NEW — Plaud MCP capture-bundle reassembly (adapter-specific shapes)
  meeting.py      NEW — meeting-note validation + write with collision guards
  cli.py          MODIFY — wire 4 new groups/actions; make --vault per-subcommand
  schema.json     REGENERATED — carries §Meeting changes + confidence_reasons
plugin/skills/sync-recordings/SKILL.md   NEW — the skill (three adapters)
plugin/.claude-plugin/plugin.json        MODIFY — version 0.2.0 → 0.3.0
template/99-workflow-config/reference/ontology.md  MODIFY — §Meeting block + prose
scripts/compile_ontology.py              MODIFY — CARRIED_KEYS += confidence_reasons
scripts/tests/
  test_vaultlib_dates.py    NEW
  test_vaultlib_syncjob.py  NEW
  test_vaultlib_plaud.py    NEW
  test_vaultlib_meeting.py  NEW
  test_fixtures_ontology.py MODIFY — confidence vocabulary + coverage tests
  test_skill_contracts.py   MODIFY — add sync-recordings to expected set
fixtures/demo-vault/20-meetings/*.md     MODIFY — all 8 enriched
CHANGELOG.md                             MODIFY — Unreleased entry
```

Existing helpers tasks MUST reuse (do not reimplement): `vault.resolve`, `vault.atomic_write`, `vault.today_iso`, `markdown.split_frontmatter`, `markdown.emit_frontmatter`, `markdown.replace_scalar_field`, `naming.slugify`, `naming.validate_slug`, `naming.find_collision`, `schema.validate`, `schema.enum_values`, `schema.for_object`.

Test fixture convention: the vaultlib test files build a minimal vault in `tmp_path` (a `99-workflow-config/` dir plus the content folders each test needs — see `scripts/tests/test_vaultlib_decision.py` for the established pattern; `vault.resolve` requires `99-workflow-config/` and at least one of the numbered folders).

---

### Task 1: §Meeting ontology extension + compiled schema

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md` (§Meeting, lines ~27–51)
- Modify: `scripts/compile_ontology.py` (CARRIED_KEYS, line ~30)
- Regenerate: `plugin/lib/vaultlib/schema.json`
- Test: `scripts/tests/test_fixtures_ontology.py`

**Interfaces:**
- Consumes: existing ontology block format, `compile_ontology.compile_schema`.
- Produces: `schema.json` → `objects.meeting` gains `enums.source`, `enums.confidence`, `confidence_reasons` (dict of three groups), optional keys `source-recording-id`, `conflicts-with`, `confidence`, `confidence-reasons`; loses `source-drive-id`. Later tasks call `schema.for_object("meeting")["confidence_reasons"]` and `schema.enum_values("meeting", "source")`.

- [ ] **Step 1: Write the failing tests** — append to `scripts/tests/test_fixtures_ontology.py`:

```python
# --- Meeting confidence vocabulary (loaded from the ontology, not hand-encoded) ---

_MEETING_BLOCK = load_ontology_schemas()["meeting"]
CONFIDENCE_REASON_GROUPS = _MEETING_BLOCK["confidence_reasons"]
NEW_ATTENDEES_RE = re.compile(r"\Anew-attendees:[1-9]\d*\Z")


def test_meeting_block_carries_reason_groups():
    assert set(CONFIDENCE_REASON_GROUPS) == {"calendar", "project-link", "attendees"}
    assert "calendar-tool-unavailable" in CONFIDENCE_REASON_GROUPS["calendar"]
    assert "no-calendar-match" in CONFIDENCE_REASON_GROUPS["calendar"]
    assert "entity-domain-match" in CONFIDENCE_REASON_GROUPS["project-link"]
    assert CONFIDENCE_REASON_GROUPS["attendees"] == ["all-attendees-known"]


def _matches_attendees_group(reason):
    return reason in CONFIDENCE_REASON_GROUPS["attendees"] or NEW_ATTENDEES_RE.match(reason)


def test_meeting_confidence_reasons_conform():
    """Where a meeting carries a confidence stamp, it is complete and closed-
    vocabulary: exactly one reason per group, and rating and reasons travel
    together."""
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        fm = parse_frontmatter(path)
        has_rating = "confidence" in fm
        has_reasons = "confidence-reasons" in fm
        assert has_rating == has_reasons, (
            f"{path}: confidence and confidence-reasons must travel together"
        )
        if not has_reasons:
            continue
        reasons = fm["confidence-reasons"]
        assert isinstance(reasons, list) and len(reasons) == 3, (
            f"{path}: expected exactly 3 reasons (one per group), got {reasons!r}"
        )
        cal = [r for r in reasons if r in CONFIDENCE_REASON_GROUPS["calendar"]]
        proj = [r for r in reasons if r in CONFIDENCE_REASON_GROUPS["project-link"]]
        att = [r for r in reasons if _matches_attendees_group(r)]
        assert len(cal) == 1, f"{path}: need exactly one calendar reason, got {cal}"
        assert len(proj) == 1, f"{path}: need exactly one project-link reason, got {proj}"
        assert len(att) == 1, f"{path}: need exactly one attendees reason, got {att}"
```

Note: `re` is already imported at the top of the module; `load_ontology_schemas`, `iter_fixture_files`, `parse_frontmatter`, `SCHEMAS` already exist there.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py -q`
Expected: collection ERROR — `KeyError: 'confidence_reasons'` (the block doesn't carry the key yet).

- [ ] **Step 3: Edit the §Meeting block** in `template/99-workflow-config/reference/ontology.md` — replace the fenced yaml block under `### Meeting` with:

```yaml
object: meeting
required: [date, type, calendar-subject, calendar_match, attendees, projects,
           review_status, recording-duration, source, processed]
optional: [attendee-emails, organizer, location, recurring, start-time,
           source-recording-id, source-filename, conflicts-with,
           confidence, confidence-reasons, reviewed, archived]
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update]
  review_status: [needs-review, confirmed, needs-attention]
  source: [teams, recorder, manual, email]
  confidence: [high, medium, low]
confidence_reasons:
  calendar: [calendar-match-high, calendar-match-medium, calendar-match-low,
             no-calendar-match, calendar-tool-unavailable]
  project-link: [entity-domain-match, calendar-subject-match,
                 content-keyword-match, no-project-match]
  attendees: [all-attendees-known]
```

And update the prose bullets under the block: replace the `source-drive-id` mention with `source-recording-id` and append these bullets (keep the existing ones about triage checkboxes, write-once, and `1:1` quoting):

```markdown
- `source` is the capture channel: `teams` (platform transcript), `recorder`
  (device capture), `manual` (typed notes), `email` (an emailed summary or
  transcript). `recording-duration` is `0` when nothing was recorded
  (`manual`, `email`).
- `source-recording-id` is the sync ledger: a namespaced id
  (`plaud:{id}`, `m365:{id}`, `inbox:{content-hash}`) written by
  `/sync-recordings`. A recording whose id appears in any meeting note is
  never synced twice. Notes that predate the sync, or were written by hand,
  simply omit it.
- **Confidence stamp.** `confidence` and `confidence-reasons` travel
  together and record how sure the sync pipeline was about its routing:
  exactly one reason from each `confidence_reasons` group above — the
  `attendees` group also admits the parameterized form `new-attendees:{N}`
  (N ≥ 1). `calendar-tool-unavailable` means the calendar was never
  searched; `no-calendar-match` means it was searched and held nothing.
  These are different facts — never collapse them.
- `conflicts-with` (`[[meeting]]`, quoted) appears only on a
  `needs-attention` sibling written because its target would have
  overwritten a `confirmed` meeting.
```

- [ ] **Step 4: Carry the new key through compilation** — in `scripts/compile_ontology.py` change:

```python
CARRIED_KEYS = ("required", "optional", "enums", "keys_present", "body_sections")
```

to:

```python
CARRIED_KEYS = ("required", "optional", "enums", "keys_present", "body_sections",
                "confidence_reasons")
```

Then regenerate: `python3 scripts/compile_ontology.py`

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest scripts/tests -q`
Expected: all pass (new tests pass vacuously — no fixture carries `confidence` yet; `test_compile_ontology` passes because schema.json was regenerated; no fixture carries `source-drive-id` or a `source` value outside the new enum, so nothing else moves).

- [ ] **Step 6: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md scripts/compile_ontology.py plugin/lib/vaultlib/schema.json scripts/tests/test_fixtures_ontology.py
git commit -m "feat: extend §Meeting with confidence stamp, source enum, recording id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `dates window` — UTC query windows without a hardcoded timezone

**Files:**
- Create: `plugin/lib/vaultlib/dates.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_dates.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `dates.DatesError`; `dates.resolve_offset_minutes(local_dt: datetime, timezone: Optional[str], utc_offset: Optional[str]) -> tuple[int, str]` returning `(minutes_east_of_utc, source)` where source is `"zoneinfo"` or `"explicit"`; `dates.window(start_local: str, *, timezone=None, utc_offset=None, hours=2.0) -> dict`. Task 7 (`plaud reassemble`) reuses `resolve_offset_minutes`. CLI: `dates window --start <ISO> [--timezone <IANA> | --utc-offset ±HH:MM] [--hours N]` — note this subcommand takes **no `--vault`**, which forces the `_dispatch` change in Step 4.

- [ ] **Step 1: Write the failing tests** — `scripts/tests/test_vaultlib_dates.py`:

```python
"""dates.window: deterministic UTC windows for calendar queries.

The lab hardcoded Brussels CET/CEST; the product takes the executive's
timezone (or an explicit offset) as an argument. Offset-based tests run on
every platform; the zoneinfo path is skipped where the host has no tz
database (Windows CI without the tzdata package).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import dates

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def _zoneinfo_available() -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
        return True
    except Exception:
        return False


def test_window_with_explicit_offset():
    result = dates.window("2026-08-20T16:42", utc_offset="-05:00", hours=2)
    assert result["utc_from"] == "2026-08-20T19:42:00"
    assert result["utc_to"] == "2026-08-20T23:42:00"
    assert result["offset"] == "-05:00"
    assert result["offset_source"] == "explicit"


def test_window_date_only_input_spans_whole_day():
    result = dates.window("2026-08-20", utc_offset="+00:00", hours=0)
    assert result["utc_from"] == "2026-08-20T00:00:00"
    assert result["utc_to"] == "2026-08-20T23:59:59"


def test_window_positive_offset():
    result = dates.window("2026-01-10T09:00", utc_offset="+02:00", hours=1)
    assert result["utc_from"] == "2026-01-10T06:00:00"
    assert result["utc_to"] == "2026-01-10T08:00:00"


@pytest.mark.skipif(not _zoneinfo_available(), reason="no tz database on host")
def test_window_zoneinfo_applies_dst():
    # America/Chicago is CDT (-05:00) in August, CST (-06:00) in January.
    aug = dates.window("2026-08-20T16:42", timezone="America/Chicago", hours=0)
    jan = dates.window("2026-01-20T16:42", timezone="America/Chicago", hours=0)
    assert aug["utc_from"] == "2026-08-20T21:42:00"
    assert jan["utc_from"] == "2026-01-20T22:42:00"
    assert aug["offset_source"] == "zoneinfo"


def test_unknown_timezone_raises_with_offset_hint():
    with pytest.raises(dates.DatesError, match="utc-offset"):
        dates.window("2026-08-20T16:42", timezone="Not/AZone")


def test_requires_timezone_or_offset_but_not_both():
    with pytest.raises(dates.DatesError):
        dates.window("2026-08-20T16:42")
    with pytest.raises(dates.DatesError):
        dates.window("2026-08-20T16:42", timezone="Europe/Brussels",
                     utc_offset="+01:00")


def test_malformed_inputs_raise():
    with pytest.raises(dates.DatesError):
        dates.window("20-08-2026T16:42", utc_offset="+01:00")
    with pytest.raises(dates.DatesError):
        dates.window("2026-08-20T16:42", utc_offset="+2:00")


def test_cli_window_envelope():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--start", "2026-08-20T16:42", "--utc-offset", "-05:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    # local 16:42 at -05:00 → UTC 21:42; default hours=2 → from 19:42
    assert payload["result"]["utc_from"] == "2026-08-20T19:42:00"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dates.py -q`
Expected: FAIL — `ImportError: cannot import name 'dates'`.

- [ ] **Step 3: Implement** `plugin/lib/vaultlib/dates.py`:

```python
"""UTC window computation for calendar queries.

The executive's timezone is prose in the context portfolio; the model reads
it and passes an IANA name (or, where the host has no tz database, an
explicit offset). Nothing here hardcodes a region — the lab's CET/CEST
arithmetic deliberately did not port.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

_OFFSET_RE = re.compile(r"\A([+-])(\d{2}):(\d{2})\Z")
_DATETIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?\Z")
_UTC_FMT = "%Y-%m-%dT%H:%M:%S"


class DatesError(Exception):
    """A date, timezone, or offset argument the caller must fix."""


def _parse_offset_minutes(text: str) -> int:
    match = _OFFSET_RE.match(text.strip())
    if not match:
        raise DatesError(
            f"utc-offset {text!r} must look like +02:00 or -05:30"
        )
    sign = 1 if match.group(1) == "+" else -1
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59:
        raise DatesError(f"utc-offset {text!r} is out of range")
    return sign * (hours * 60 + minutes)


def _parse_local(start_local: str) -> Tuple[datetime, bool]:
    """Return (datetime, had_time). Date-only input means a whole-day window."""
    text = str(start_local).strip()
    if not _DATETIME_RE.match(text):
        raise DatesError(
            f"start {start_local!r} must be ISO YYYY-MM-DD or YYYY-MM-DDTHH:MM"
        )
    if "T" in text:
        fmt = _UTC_FMT if text.count(":") == 2 else "%Y-%m-%dT%H:%M"
        return datetime.strptime(text, fmt), True
    return datetime.strptime(text, "%Y-%m-%d"), False


def resolve_offset_minutes(local_dt: datetime, timezone: Optional[str],
                           utc_offset: Optional[str]) -> Tuple[int, str]:
    """The UTC offset in force at local_dt, and where it came from.

    zoneinfo handles DST correctly but needs a tz database, which a Windows
    host may not have — hence the explicit-offset escape hatch.
    """
    if (timezone is None) == (utc_offset is None):
        raise DatesError(
            "pass exactly one of --timezone (IANA name, e.g. America/Chicago) "
            "or --utc-offset (e.g. -05:00)"
        )
    if utc_offset is not None:
        return _parse_offset_minutes(utc_offset), "explicit"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
    except Exception as exc:
        raise DatesError(
            f"timezone {timezone!r} could not be resolved on this host "
            f"({exc.__class__.__name__}) — check the IANA name, or pass "
            "--utc-offset (e.g. -05:00) instead"
        ) from exc
    delta = local_dt.replace(tzinfo=tz).utcoffset()
    return int(delta.total_seconds() // 60), "zoneinfo"


def _format_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def window(start_local: str, *, timezone: Optional[str] = None,
           utc_offset: Optional[str] = None, hours: float = 2.0) -> dict:
    """A UTC [from, to] window around a local timestamp.

    With a time component: ±hours around it. Date-only: that whole local day
    (00:00:00–23:59:59), still widened by ±hours.
    """
    if hours < 0:
        raise DatesError(f"hours {hours!r} must be >= 0")
    local, had_time = _parse_local(start_local)
    offset_minutes, source = resolve_offset_minutes(local, timezone, utc_offset)
    pad = timedelta(hours=float(hours))
    if had_time:
        lo, hi = local - pad, local + pad
    else:
        lo = local - pad
        hi = local + timedelta(hours=23, minutes=59, seconds=59) + pad
    shift = timedelta(minutes=offset_minutes)
    return {
        "start_local": str(start_local).strip(),
        "utc_from": (lo - shift).strftime(_UTC_FMT),
        "utc_to": (hi - shift).strftime(_UTC_FMT),
        "offset": _format_offset(offset_minutes),
        "offset_source": source,
    }
```

- [ ] **Step 4: Wire the CLI** — in `plugin/lib/vaultlib/cli.py`:

Add `dates` to the import line:

```python
from vaultlib import dates, decision, entity, person, project, schema, vault  # noqa: E402
```

In `build_parser()`, after the `identity` group:

```python
    dates_group = top.add_parser("dates", help="date and timezone arithmetic")
    dates_sub = dates_group.add_subparsers(dest="action", required=True)
    dates_window = dates_sub.add_parser(
        "window", help="UTC query window around a local timestamp")
    dates_window.add_argument("--start", required=True,
                              help="local ISO date or datetime")
    dates_window.add_argument("--timezone", help="IANA timezone name")
    dates_window.add_argument("--utc-offset", dest="utc_offset",
                              help="explicit offset like -05:00")
    dates_window.add_argument("--hours", type=float, default=2.0,
                              help="half-width of the window (default 2)")
```

In `_dispatch`, replace the first line and add the branch:

```python
def _dispatch(args: argparse.Namespace) -> int:
    # dates (and later stateless subcommands) take no --vault.
    root = vault.resolve(args.vault) if hasattr(args, "vault") else None
    if args.group == "dates":
        return _ok(dates.window(args.start, timezone=args.timezone,
                                utc_offset=args.utc_offset, hours=args.hours))
```

And add the exception arm in `main` (before the `ValueError` arm — `DatesError` must not be swallowed by a broader handler with a worse hint):

```python
    except dates.DatesError as exc:
        return _fail(str(exc), "Fix the date or timezone argument and retry.")
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dates.py scripts/tests/test_vaultlib_cli.py scripts/tests/test_skill_contracts.py -q`
Expected: PASS (the cli/skill-contract suites confirm the parser refactor broke nothing).

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/dates.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_dates.py
git commit -m "feat: dates window subcommand — UTC calendar windows, timezone as a parameter

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `sync scan` / `sync dedup` / `sync skip` — the ledger

**Files:**
- Create: `plugin/lib/vaultlib/syncjob.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_syncjob.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter`, `vault.resolve`.
- Produces: `syncjob.SyncError`; `syncjob.content_id(path: Path) -> str` (`"inbox:" + sha256 first 16 hex`); `syncjob.known_recording_ids(root) -> tuple[dict[str, str], list[str]]` (`{id: meeting relpath}`, warnings); `syncjob.read_skip_list(root) -> set[str]`; `syncjob.scan(root) -> dict`; `syncjob.dedup(root, ids: list) -> dict`; `syncjob.skip(root, recording_id: str) -> dict`. Constants: `INBOX_DIR = "10-inbox"`, `MEETINGS_DIR = "20-meetings"`, `NAMESPACES = ("inbox", "plaud", "m365")`, `SKIP_FILE_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"`. Task 5's `meeting write` reuses `known_recording_ids`; the SKILL.md (Task 9) calls all three actions.

- [ ] **Step 1: Write the failing tests** — `scripts/tests/test_vaultlib_syncjob.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q`
Expected: FAIL — `ImportError: cannot import name 'syncjob'`.

- [ ] **Step 3: Implement** `plugin/lib/vaultlib/syncjob.py`:

```python
"""Inbox scan, dedup, and the skip list: the deterministic ledger under
/sync-recordings.

The vault itself is the ledger — a recording is synced iff its namespaced
source-recording-id appears in some 20-meetings/*.md. There is no second
state file to reconcile, so a failed item (which wrote nothing) retries
naturally on the next run. The skip list exists for the one case the ledger
cannot express: a human said "never propose this one again".
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Set, Tuple

from . import markdown

INBOX_DIR = "10-inbox"
MEETINGS_DIR = "20-meetings"
NAMESPACES = ("inbox", "plaud", "m365")
SKIP_FILE_RELPATH = Path("99-workflow-config") / "sync-state" / "skipped-recordings.txt"
_IGNORED_NAMES = {"README.md"}


class SyncError(Exception):
    """A sync argument or id the caller must fix."""


def content_id(path: Path) -> str:
    """inbox:{16 hex} — content-addressed, so a renamed drop stays deduped."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"inbox:{digest}"


def _validate_id(recording_id: str) -> str:
    text = str(recording_id or "").strip()
    prefix = text.split(":", 1)[0] if ":" in text else ""
    if prefix not in NAMESPACES or not text.split(":", 1)[1]:
        raise SyncError(
            f"recording id {recording_id!r} must carry a namespace prefix, "
            f"one of {[n + ':' for n in NAMESPACES]}"
        )
    return text


def known_recording_ids(root: Path) -> Tuple[Dict[str, str], List[str]]:
    """{source-recording-id: meeting relpath} across 20-meetings/, plus
    warnings for unparseable notes (reported, never fatal — one mangled file
    must not stop the sync)."""
    ids: Dict[str, str] = {}
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        rid = data.get("source-recording-id")
        if rid:
            ids[str(rid)] = path.relative_to(root).as_posix()
    return ids, warnings


def read_skip_list(root: Path) -> Set[str]:
    skip_file = root / SKIP_FILE_RELPATH
    if not skip_file.is_file():
        return set()
    return {line.strip() for line in
            skip_file.read_text(encoding="utf-8").splitlines() if line.strip()}


def skip(root: Path, recording_id: str) -> dict:
    """Append one id to the skip list (idempotent)."""
    rid = _validate_id(recording_id)
    existing = read_skip_list(root)
    if rid in existing:
        return {"recording_id": rid, "already_present": True}
    skip_file = root / SKIP_FILE_RELPATH
    skip_file.parent.mkdir(parents=True, exist_ok=True)
    with open(skip_file, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(rid + "\n")
    return {"recording_id": rid, "already_present": False}


def scan(root: Path) -> dict:
    """Partition inbox files into candidates / already synced / skipped.

    Which candidates are transcript-shaped is judgment and stays with the
    model; this returns every regular file with enough metadata to decide.
    """
    known, warnings = known_recording_ids(root)
    skipped_ids = read_skip_list(root)
    candidates, synced, skipped = [], [], []
    inbox = root / INBOX_DIR
    for path in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if not path.is_file() or path.name in _IGNORED_NAMES \
                or path.name.startswith("."):
            continue
        rid = content_id(path)
        entry = {
            "name": path.name,
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "recording_id": rid,
        }
        if rid in known:
            synced.append({**entry, "synced_as": known[rid]})
        elif rid in skipped_ids:
            skipped.append(entry)
        else:
            candidates.append(entry)
    return {"candidates": candidates, "already_synced": synced,
            "skipped": skipped, "known_ids_count": len(known),
            "warnings": warnings}


def dedup(root: Path, ids: List[str]) -> dict:
    """Filter an adapter's discovery list against the ledger and skip list."""
    validated = [_validate_id(rid) for rid in ids]
    known, warnings = known_recording_ids(root)
    skipped_ids = read_skip_list(root)
    return {
        "new": [rid for rid in validated
                if rid not in known and rid not in skipped_ids],
        "synced": {rid: known[rid] for rid in validated if rid in known},
        "skipped": [rid for rid in validated if rid in skipped_ids],
        "warnings": warnings,
    }
```

- [ ] **Step 4: Wire the CLI** — in `build_parser()`:

```python
    sync = top.add_parser("sync", help="recording-sync ledger operations")
    sync_sub = sync.add_subparsers(dest="action", required=True)

    sync_scan = sync_sub.add_parser(
        "scan", help="partition 10-inbox/ files against the sync ledger")
    _add_vault_argument(sync_scan)

    sync_dedup = sync_sub.add_parser(
        "dedup", help="filter a JSON list of namespaced ids against the ledger")
    _add_vault_argument(sync_dedup)
    sync_dedup.add_argument("--ids", required=True,
                            help="path to a JSON array of ids, or - for stdin")

    sync_skip = sync_sub.add_parser(
        "skip", help="never propose this recording id again")
    _add_vault_argument(sync_skip)
    sync_skip.add_argument("--id", dest="recording_id", required=True)
```

In `_dispatch` (import `syncjob` on the existing import line):

```python
    if args.group == "sync":
        if args.action == "scan":
            return _ok(syncjob.scan(root))
        if args.action == "dedup":
            payload = (json.load(sys.stdin) if args.ids == "-"
                       else json.loads(Path(args.ids).read_text(encoding="utf-8")))
            if not isinstance(payload, list):
                raise syncjob.SyncError("--ids must be a JSON array of id strings")
            return _ok(syncjob.dedup(root, payload))
        if args.action == "skip":
            return _ok(syncjob.skip(root, args.recording_id))
```

And in `main`:

```python
    except syncjob.SyncError as exc:
        return _fail(str(exc), "Fix the named id or argument and retry.")
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/syncjob.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_syncjob.py
git commit -m "feat: sync scan/dedup/skip — the vault as recording-sync ledger

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `sync reconcile-reviews` — the confirm path

**Files:**
- Modify: `plugin/lib/vaultlib/syncjob.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_syncjob.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter`, `markdown.replace_scalar_field`, `vault.atomic_write`.
- Produces: `syncjob.reconcile_reviews(root) -> dict` with keys `flipped` (list of relpaths), `needs_attention_ticks` (list of relpaths — reviewed ticks on `needs-attention` notes, surfaced but never auto-confirmed), `warnings`. CLI: `sync reconcile-reviews --vault`.

- [ ] **Step 1: Write the failing tests** — append to `scripts/tests/test_vaultlib_syncjob.py`:

```python
def write_triaged_meeting(root, stem, review_status, reviewed):
    text = "\n".join([
        "---", "date: 2026-08-20T10:00", "type: meeting",
        'calendar-subject: "X"', f"review_status: {review_status}",
        f"reviewed: {'true' if reviewed else 'false'}", "archived: false",
        "---", "", "## Key Takeaways", "- x", "",
    ])
    (root / "20-meetings" / f"{stem}.md").write_text(text, encoding="utf-8")


def test_reconcile_flips_only_reviewed_needs_review(tmp_path):
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "a-ticked", "needs-review", True)
    write_triaged_meeting(root, "b-unticked", "needs-review", False)
    write_triaged_meeting(root, "c-confirmed", "confirmed", True)
    write_triaged_meeting(root, "d-attention", "needs-attention", True)

    result = syncjob.reconcile_reviews(root)
    assert result["flipped"] == ["20-meetings/a-ticked.md"]
    assert result["needs_attention_ticks"] == ["20-meetings/d-attention.md"]

    text = (root / "20-meetings" / "a-ticked.md").read_text(encoding="utf-8")
    assert "review_status: confirmed" in text
    assert "reviewed: true" in text          # the tick itself is never touched
    untouched = (root / "20-meetings" / "b-unticked.md").read_text(encoding="utf-8")
    assert "review_status: needs-review" in untouched


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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q -k reconcile`
Expected: FAIL — `AttributeError: ... no attribute 'reconcile_reviews'`.

- [ ] **Step 3: Implement** — append to `syncjob.py` (add `vault` to the module's relative import):

```python
def reconcile_reviews(root: Path) -> dict:
    """Fold triage ticks back into review_status: reviewed true flips
    needs-review -> confirmed. One-way and narrow: a tick on a
    needs-attention note is surfaced for a human, never auto-confirmed, and
    `archived` is never read by any pipeline.
    """
    flipped: List[str] = []
    attention: List[str] = []
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        if data.get("reviewed") is not True:
            continue
        status = data.get("review_status")
        if status == "needs-attention":
            attention.append(rel)
            continue
        if status != "needs-review":
            continue
        try:
            updated = markdown.replace_scalar_field(
                text, "review_status", "confirmed")
        except ValueError as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        vault.atomic_write(path, updated)
        flipped.append(rel)
    return {"flipped": flipped, "needs_attention_ticks": attention,
            "warnings": warnings}
```

- [ ] **Step 4: Wire the CLI** — parser:

```python
    sync_rec = sync_sub.add_parser(
        "reconcile-reviews",
        help="flip review_status needs-review -> confirmed where reviewed is ticked")
    _add_vault_argument(sync_rec)
```

Dispatch (inside the existing `sync` branch):

```python
        if args.action == "reconcile-reviews":
            return _ok(syncjob.reconcile_reviews(root))
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/syncjob.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_syncjob.py
git commit -m "feat: sync reconcile-reviews — the one-way triage-tick confirm path

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `meeting write` — validation and the happy path

**Files:**
- Create: `plugin/lib/vaultlib/meeting.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_meeting.py`

**Interfaces:**
- Consumes: `schema.validate("meeting", fm)`, `schema.for_object("meeting")["confidence_reasons"]`, `schema.enum_values`, `naming.slugify/validate_slug`, `markdown.emit_frontmatter`, `vault.atomic_write`, `syncjob.known_recording_ids`.
- Produces: `meeting.MeetingError`; `meeting.write(root: Path, payload: dict) -> dict` returning `{"stem", "path", "review_status", "recording_id", "conflict": None}` (Task 6 adds the conflict shapes). CLI: `meeting write --vault --note <path|->`. Payload contract (consumed verbatim by the SKILL.md in Task 9):

```
required: title, date (ISO date or datetime), type, calendar-subject,
          calendar_match (bool), attendees (slug list), projects (slug list),
          recording-duration (int >= 0), source (enum),
          takeaways (1-5 strings), debrief (non-empty string)
optional: attendee-emails, organizer, location, recurring (bool),
          source-recording-id (namespaced), source-filename,
          confidence + confidence-reasons (together, 3 reasons: one per group;
          attendees group admits new-attendees:{N}),
          action-items (string list), people (slug list)
```

- [ ] **Step 1: Write the failing tests** — `scripts/tests/test_vaultlib_meeting.py`:

```python
"""meeting write: schema-validated emission of meeting notes.

review_status is not a payload field — every synced meeting lands
needs-review (the auto-confirm gate deliberately did not ship; a fresh vault
has no calibration data)."""
from pathlib import Path

import pytest
import yaml

from vaultlib import meeting, syncjob


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "10-inbox").mkdir()
    (tmp_path / "20-meetings").mkdir()
    (tmp_path / "30-projects" / "yard-automation").mkdir(parents=True)
    (tmp_path / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nslug: yard-automation\n---\n", encoding="utf-8")
    (tmp_path / "50-people").mkdir()
    for slug in ("priya-nathan", "morgan-ellery"):
        (tmp_path / "50-people" / f"{slug}.md").write_text(
            f"---\nperson-name: X\nslug: {slug}\nrelationship:\n---\n",
            encoding="utf-8")
    return tmp_path


def payload(**overrides) -> dict:
    base = {
        "title": "vendor strategy brainstorm",
        "date": "2026-05-20T11:00",
        "type": "brainstorm",
        "calendar-subject": "Vendor strategy: working session",
        "calendar_match": False,
        "attendees": ["priya-nathan", "morgan-ellery"],
        "projects": ["yard-automation"],
        "recording-duration": 41,
        "source": "recorder",
        "source-recording-id": "inbox:3f9c2a41d8e07b56",
        "source-filename": "REC-2026-0520-1103.m4a",
        "confidence": "low",
        "confidence-reasons": ["calendar-tool-unavailable",
                               "content-keyword-match", "new-attendees:1"],
        "takeaways": ["Single-vendor consolidation preferred.",
                      "Yard 2 timeline at risk."],
        "debrief": "### Vendor strategy\nDiscussion of consolidation.",
        "action-items": ["**Priya Nathan** — circulate revised schedule"],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_write_happy_path_is_conformant_yaml(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload())
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm"
    assert result["review_status"] == "needs-review"
    assert result["conflict"] is None

    text = (root / result["path"]).read_text(encoding="utf-8")
    # PyYAML is the second parser CI trusts; the emitted block must satisfy it.
    block = text.split("---\n")[1]
    data = yaml.safe_load(block)
    assert data["calendar-subject"] == "Vendor strategy: working session"
    assert data["review_status"] == "needs-review"
    assert data["reviewed"] is False and data["archived"] is False
    assert data["processed"] is True
    assert data["confidence-reasons"] == ["calendar-tool-unavailable",
                                          "content-keyword-match",
                                          "new-attendees:1"]
    assert "## Key Takeaways" in text and "## Debrief" in text
    assert "## Action Items" in text


def test_one_to_one_type_survives_pyyaml(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(type="1:1",
                                         title="priya check in"))
    block = (root / result["path"]).read_text(encoding="utf-8").split("---\n")[1]
    assert yaml.safe_load(block)["type"] == "1:1"   # not the integer 61


def test_action_items_section_omitted_when_absent(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(**{"action-items": None}))
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "## Action Items" not in text


def test_rejects_unknown_project_and_unknown_attendee(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="no-such-project"):
        meeting.write(root, payload(projects=["no-such-project"]))
    with pytest.raises(meeting.MeetingError, match="person ensure"):
        meeting.write(root, payload(attendees=["ghost-attendee"]))


def test_rejects_incomplete_confidence_stamp(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="travel together"):
        meeting.write(root, payload(**{"confidence-reasons": None}))
    bad = payload(**{"confidence-reasons":
                     ["calendar-match-high", "calendar-match-low",
                      "all-attendees-known"]})
    with pytest.raises(meeting.MeetingError, match="project-link"):
        meeting.write(root, bad)
    bad2 = payload(**{"confidence-reasons":
                      ["calendar-match-high", "no-project-match",
                       "new-attendees:0"]})
    with pytest.raises(meeting.MeetingError, match="new-attendees"):
        meeting.write(root, bad2)


def test_rejects_unknown_payload_key_and_bad_enum(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="unknown payload key"):
        meeting.write(root, payload(review_status="confirmed"))
    with pytest.raises(meeting.MeetingError, match="source"):
        meeting.write(root, payload(source="carrier-pigeon"))


def test_rejects_zero_takeaways_and_too_many(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="takeaways"):
        meeting.write(root, payload(takeaways=[]))
    with pytest.raises(meeting.MeetingError, match="takeaways"):
        meeting.write(root, payload(takeaways=["a", "b", "c", "d", "e", "f"]))
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py -q`
Expected: FAIL — `ImportError: cannot import name 'meeting'`.

- [ ] **Step 3: Implement** `plugin/lib/vaultlib/meeting.py`:

```python
"""Meeting notes: schema-validated emission with collision guards.

The model extracts; this module writes. review_status is never a payload
field: every synced meeting lands needs-review (design decision 7 — the
auto-confirm gate needs per-deployment calibration data that a fresh vault
does not have), and the only paths out of it are the reviewed checkbox
(sync reconcile-reviews) or a human edit in Meetings.base.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import markdown, naming, schema, syncjob, vault

MEETINGS_DIR = "20-meetings"

REQUIRED_PAYLOAD = ("title", "date", "type", "calendar-subject",
                    "calendar_match", "attendees", "projects",
                    "recording-duration", "source", "takeaways", "debrief")
OPTIONAL_PAYLOAD = ("attendee-emails", "organizer", "location", "recurring",
                    "source-recording-id", "source-filename",
                    "confidence", "confidence-reasons",
                    "action-items", "people")

# confidence-reasons is quoted wholesale: a "new-attendees:1" item in an
# unquoted flow list is exactly the kind of value PyYAML may read as a nested
# mapping — quoting every item costs nothing and parses identically in both
# parsers.
_QUOTE_KEYS = frozenset({"calendar-subject", "source-filename", "organizer",
                         "location", "conflicts-with", "confidence-reasons"})
_DATETIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?\Z")
_NEW_ATTENDEES_RE = re.compile(r"\Anew-attendees:[1-9]\d*\Z")
MAX_TAKEAWAYS = 5


class MeetingError(Exception):
    """A payload field or vault state the caller must fix."""


def _require_keys(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise MeetingError("the payload must be a JSON object")
    unknown = sorted(set(payload) - set(REQUIRED_PAYLOAD) - set(OPTIONAL_PAYLOAD))
    if unknown:
        raise MeetingError(
            f"unknown payload key(s) {unknown} — review_status, reviewed, "
            "archived and processed are set by this CLI, not by the caller"
        )
    missing = [key for key in REQUIRED_PAYLOAD if key not in payload]
    if missing:
        raise MeetingError(f"missing payload key(s) {missing}")


def _require_slug_list(payload: dict, key: str, *, allow_empty: bool) -> list:
    values = payload.get(key) or []
    if not isinstance(values, list) or (not values and not allow_empty):
        raise MeetingError(f"{key} must be a non-empty list of slugs")
    for value in values:
        try:
            naming.validate_slug(str(value))
        except ValueError as exc:
            raise MeetingError(f"{key} entry {value!r}: {exc}") from exc
    return [str(v) for v in values]


def _require_joins(root: Path, attendees: list, projects: list,
                   people: list) -> None:
    for slug in projects:
        if not (root / "30-projects" / slug / "index.md").is_file():
            raise MeetingError(
                f"projects entry {slug!r} matches no project at "
                f"30-projects/{slug}/index.md — create it with /new-project, "
                "or leave projects empty for triage to catch"
            )
    for slug in dict.fromkeys(attendees + people):
        if not (root / "50-people" / f"{slug}.md").is_file():
            raise MeetingError(
                f"attendee {slug!r} has no person note at 50-people/{slug}.md "
                f"— run `person ensure` for them first"
            )


def _validate_confidence(payload: dict) -> None:
    rating = payload.get("confidence")
    reasons = payload.get("confidence-reasons")
    if (rating is None) != (reasons is None):
        raise MeetingError(
            "confidence and confidence-reasons travel together — pass both "
            "or neither"
        )
    if rating is None:
        return
    allowed_ratings = schema.enum_values("meeting", "confidence")
    if rating not in allowed_ratings:
        raise MeetingError(f"confidence {rating!r} is not one of {allowed_ratings}")
    groups = schema.for_object("meeting")["confidence_reasons"]
    if not isinstance(reasons, list):
        raise MeetingError("confidence-reasons must be a list")
    cal = [r for r in reasons if r in groups["calendar"]]
    proj = [r for r in reasons if r in groups["project-link"]]
    att = [r for r in reasons
           if r in groups["attendees"] or _NEW_ATTENDEES_RE.match(str(r))]
    leftovers = [r for r in reasons if r not in cal + proj + att]
    if leftovers:
        raise MeetingError(
            f"confidence-reasons {leftovers} are not in the closed vocabulary "
            "(new-attendees:{N} needs N >= 1)"
        )
    for name, hits in (("calendar", cal), ("project-link", proj),
                       ("attendees", att)):
        if len(hits) != 1:
            raise MeetingError(
                f"confidence-reasons needs exactly one {name} reason, got {hits}"
            )


def _validate_scalars(payload: dict) -> None:
    if not _DATETIME_RE.match(str(payload["date"])):
        raise MeetingError(
            f"date {payload['date']!r} must be ISO YYYY-MM-DD or YYYY-MM-DDTHH:MM"
        )
    duration = payload["recording-duration"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        raise MeetingError("recording-duration must be an integer >= 0")
    if not isinstance(payload["calendar_match"], bool):
        raise MeetingError("calendar_match must be a boolean")
    takeaways = payload["takeaways"]
    if (not isinstance(takeaways, list) or not takeaways
            or len(takeaways) > MAX_TAKEAWAYS
            or not all(isinstance(t, str) and t.strip() for t in takeaways)):
        raise MeetingError(
            f"takeaways must be 1-{MAX_TAKEAWAYS} non-empty strings"
        )
    if not isinstance(payload["debrief"], str) or not payload["debrief"].strip():
        raise MeetingError("debrief must be a non-empty string")
    rid = payload.get("source-recording-id")
    if rid is not None:
        syncjob._validate_id(rid)


def _date_prefix(date_value: str) -> str:
    day = datetime.strptime(str(date_value)[:10], "%Y-%m-%d").date()
    return day.strftime("%d-%m-%y")


def _render_body(payload: dict) -> str:
    lines = ["", "## Key Takeaways"]
    lines += [f"- {item.strip()}" for item in payload["takeaways"]]
    lines += ["", "## Debrief", str(payload["debrief"]).strip()]
    action_items = payload.get("action-items") or []
    if action_items:
        lines += ["", "## Action Items"]
        lines += [f"- {item.strip()}" for item in action_items]
    people = payload.get("people") or []
    if people:
        lines += ["", "## People", " · ".join(f"[[{slug}]]" for slug in people)]
    return "\n".join(lines) + "\n"


def _frontmatter(payload: dict, review_status: str,
                 conflicts_with: Optional[str]) -> dict:
    data = {
        "date": payload["date"],
        "type": payload["type"],
        "calendar-subject": payload["calendar-subject"],
        "calendar_match": payload["calendar_match"],
    }
    for key in ("organizer", "location", "recurring", "attendee-emails"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    data.update({
        "attendees": payload["attendees"],
        "projects": payload["projects"],
        "review_status": review_status,
        "reviewed": False,
        "archived": False,
    })
    for key in ("confidence", "confidence-reasons"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    data["recording-duration"] = payload["recording-duration"]
    data["source"] = payload["source"]
    for key in ("source-recording-id", "source-filename"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    if conflicts_with is not None:
        data["conflicts-with"] = f"[[{conflicts_with}]]"
    data["processed"] = True
    return data


def write(root: Path, payload: dict) -> dict:
    _require_keys(payload)
    _validate_scalars(payload)
    _validate_confidence(payload)
    attendees = _require_slug_list(payload, "attendees", allow_empty=False)
    projects = _require_slug_list(payload, "projects", allow_empty=True)
    people = _require_slug_list(payload, "people", allow_empty=True)
    _require_joins(root, attendees, projects, people)

    prefix = _date_prefix(payload["date"])
    title_slug = naming.slugify(str(payload["title"]))
    stem = f"{prefix}-{title_slug}"
    naming.validate_slug(stem, max_length=naming.MAX_STEM_LENGTH)

    stem, review_status, conflicts_with, conflict = _resolve_target(
        root, stem, payload)

    frontmatter = _frontmatter(payload, review_status, conflicts_with)
    problems = schema.validate("meeting", frontmatter)
    if problems:
        raise MeetingError(
            "refusing to write non-conformant meeting frontmatter: "
            + "; ".join(problems)
        )
    quote_keys = set(_QUOTE_KEYS)
    if ":" in str(payload["type"]):
        quote_keys.add("type")   # unquoted 1:1 is YAML for the integer 61

    target = root / MEETINGS_DIR / f"{stem}.md"
    vault.atomic_write(
        target, markdown.emit_frontmatter(frontmatter, quote_keys)
        + _render_body(payload))
    return {
        "stem": stem,
        "path": target.relative_to(root).as_posix(),
        "review_status": review_status,
        "recording_id": payload.get("source-recording-id"),
        "conflict": conflict,
    }


def _resolve_target(root: Path, stem: str, payload: dict):
    """Task 6 replaces this stub with the collision guards."""
    return stem, "needs-review", None, None
```

- [ ] **Step 4: Wire the CLI** — parser:

```python
    meetings = top.add_parser("meeting", help="meeting notes")
    meetings_sub = meetings.add_subparsers(dest="action", required=True)
    meeting_write = meetings_sub.add_parser(
        "write", help="write one meeting note from a JSON payload")
    _add_vault_argument(meeting_write)
    meeting_write.add_argument("--note", required=True,
                               help="path to a JSON file, or - to read stdin")
```

Dispatch (import `meeting` in the import line):

```python
    if args.group == "meeting":
        payload = (json.load(sys.stdin) if args.note == "-"
                   else json.loads(Path(args.note).read_text(encoding="utf-8")))
        return _ok(meeting.write(root, payload))
```

And in `main`:

```python
    except meeting.MeetingError as exc:
        return _fail(str(exc), "Fix the named payload field and retry.")
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/meeting.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_meeting.py
git commit -m "feat: meeting write — schema-validated meeting notes, needs-review always

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `meeting write` collision guards

**Files:**
- Modify: `plugin/lib/vaultlib/meeting.py` (replace the `_resolve_target` stub)
- Test: `scripts/tests/test_vaultlib_meeting.py`

**Interfaces:**
- Consumes: `syncjob.known_recording_ids`.
- Produces: final `_resolve_target(root, stem, payload) -> tuple[str, str, Optional[str], Optional[dict]]` = `(final_stem, review_status, conflicts_with_stem, conflict_report)`. Three guards, in order:
  1. **Ledger guard** — payload's `source-recording-id` already in some meeting → `MeetingError` naming that path (dedup failed upstream; defense in depth).
  2. **Confirmed guard** — target stem exists (case-insensitive) with `review_status: confirmed` → never overwrite; write sibling `{stem}--v2` (first free `--vN`, N ≥ 2) with `review_status: needs-attention` and `conflicts-with: "[[{stem}]]"`; `conflict = {"kind": "confirmed-target", "conflicts_with": stem}`.
  3. **Stem guard** — target exists with any other status → different meeting, same date+title; suffix `-2`/`-3`… (first free), stays `needs-review`; `conflict = {"kind": "stem-collision", "suffixed_from": stem}`. (Deviation from the lab, which overwrote non-confirmed targets: our §Meeting is write-once and dedup already handles re-syncs, so an overwrite here could only destroy someone else's note.)

- [ ] **Step 1: Write the failing tests** — append to `test_vaultlib_meeting.py`:

```python
def test_refuses_when_recording_id_already_in_ledger(tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload())
    with pytest.raises(meeting.MeetingError, match="already synced"):
        meeting.write(root, payload(title="different title entirely"))


def test_confirmed_target_gets_needs_attention_sibling(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    # A human confirms it via triage.
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")

    dup = payload(**{"source-recording-id": "inbox:ffff2a41d8e07b56"})
    result = meeting.write(root, dup)
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm--v2"
    assert result["review_status"] == "needs-attention"
    assert result["conflict"] == {
        "kind": "confirmed-target",
        "conflicts_with": "20-05-26-vendor-strategy-brainstorm",
    }
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'conflicts-with: "[[20-05-26-vendor-strategy-brainstorm]]"' in text
    # The confirmed note was not touched.
    assert "review_status: confirmed" in p.read_text(encoding="utf-8")


def test_second_conflict_takes_v3(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")
    meeting.write(root, payload(**{"source-recording-id": "inbox:aaaa2a41d8e07b56"}))
    third = meeting.write(root, payload(**{"source-recording-id": "inbox:bbbb2a41d8e07b56"}))
    assert third["stem"] == "20-05-26-vendor-strategy-brainstorm--v3"


def test_unconfirmed_stem_collision_suffixes_instead_of_overwriting(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    result = meeting.write(
        root, payload(**{"source-recording-id": "inbox:cccc2a41d8e07b56"}))
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-2"
    assert result["review_status"] == "needs-review"
    assert result["conflict"]["kind"] == "stem-collision"
    # Both notes exist; nothing was overwritten.
    assert (root / first["path"]).is_file() and (root / result["path"]).is_file()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py -q -k "ledger or sibling or v3 or suffixes"`
Expected: FAIL (stub returns the bare stem; ledger guard missing).

- [ ] **Step 3: Implement** — replace the `_resolve_target` stub in `meeting.py`:

```python
def _find_stem(folder: Path, stem: str) -> Optional[Path]:
    """Case-insensitive stem lookup (Linux VM writes, APFS/NTFS host)."""
    if not folder.is_dir():
        return None
    lowered = stem.lower()
    for candidate in sorted(folder.glob("*.md")):
        if candidate.stem.lower() == lowered:
            return candidate
    return None


def _first_free(folder: Path, pattern: str) -> str:
    for n in range(2, 100):
        candidate = pattern.format(n=n)
        if _find_stem(folder, candidate) is None:
            return candidate
    raise MeetingError(f"more than 98 collisions for {pattern!r} — clean up first")


def _resolve_target(root: Path, stem: str, payload: dict):
    """Apply the three collision guards, in order. Never overwrites."""
    rid = payload.get("source-recording-id")
    if rid is not None:
        known, _ = syncjob.known_recording_ids(root)
        if rid in known:
            raise MeetingError(
                f"recording {rid!r} is already synced as {known[rid]} — "
                "this is the dedup ledger working; do not write it again"
            )

    folder = root / MEETINGS_DIR
    existing = _find_stem(folder, stem)
    if existing is None:
        return stem, "needs-review", None, None

    try:
        data, _ = markdown.split_frontmatter(existing.read_text(encoding="utf-8"))
        status = data.get("review_status")
    except (ValueError, OSError):
        status = None   # unreadable counts as not-confirmed: suffix, don't touch

    if status == "confirmed":
        sibling = _first_free(folder, stem + "--v{n}")
        conflict = {"kind": "confirmed-target", "conflicts_with": existing.stem}
        return sibling, "needs-attention", existing.stem, conflict

    suffixed = _first_free(folder, stem + "-{n}")
    conflict = {"kind": "stem-collision", "suffixed_from": existing.stem}
    return suffixed, "needs-review", None, conflict
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py -q`
Expected: PASS (all of Task 5's tests still green — `conflicts-with` and `--vN` stems stay within `MAX_STEM_LENGTH` because `slugify` capped the title slug at 60 and the guard suffix adds at most 4 chars; `naming.validate_slug` on the final stem still runs in `write`... **note**: `validate_slug` is called on the *base* stem before `_resolve_target`; the suffixed stem is derived from it and safe by construction).

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/meeting.py scripts/tests/test_vaultlib_meeting.py
git commit -m "feat: meeting write collision guards — ledger, confirmed sibling, stem suffix

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: `plaud reassemble` — the Plaud capture-bundle adapter

**Files:**
- Create: `plugin/lib/vaultlib/plaud.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_plaud.py`

**Interfaces:**
- Consumes: `dates.resolve_offset_minutes`, `dates.DatesError`.
- Produces: `plaud.PlaudError`; `plaud.reassemble(meta_path, transcript_path, note_path, out_dir, *, timezone=None, utc_offset=None) -> dict` returning `{"recording_id": "plaud:{id}", "duration_min", "recorded_local", "has_enrichment", "blob_path"}`. CLI: `plaud reassemble --meta <path> --transcript <path> [--note <path>] --out <dir> [--timezone|--utc-offset]` (no `--vault` — the blob goes to session scratch, never into the vault).
- Input shapes (ported verbatim from the lab's `sync-helper.py`, proven against the live Plaud MCP):
  - meta: `{"id", "name", "start_at" (ISO, UTC naive), "duration" (ms)}` — the `list_files` entry.
  - transcript (`get_transcript`): dict `{"segments": [{"speaker", "content", "end_time"}, ...]}` **or** legacy array `[{"data_type": "transaction", "data_error_code", "data_content": "<json string of segments>"}]`.
  - note (`get_note`, optional): array with a `{"data_type": "auto_sum_note", "data_content": "<markdown>"}` entry.

- [ ] **Step 1: Write the failing tests** — `scripts/tests/test_vaultlib_plaud.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_plaud.py -q`
Expected: FAIL — `ImportError: cannot import name 'plaud'`.

- [ ] **Step 3: Implement** `plugin/lib/vaultlib/plaud.py`:

```python
"""Plaud MCP adapter: reassemble raw tool JSON into one capture-bundle blob.

Transcript-first: the summary note is optional enrichment and its absence or
breakage never fails the bundle. Shapes are the lab-verified Plaud MCP
responses; anything else raises rather than guessing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from . import dates

ENRICHMENT_HEADER = "## Enrichment (recorder summary)"


class PlaudError(Exception):
    """A malformed or failed Plaud payload the caller must handle."""


def _render_transcript(payload) -> Tuple[str, int]:
    """(speaker-labeled body, max end_time ms) from either response shape."""
    if isinstance(payload, dict):
        utterances = payload.get("segments") or []
        if not utterances:
            raise PlaudError("empty transcript (no segments)")
    elif isinstance(payload, list):
        txn = next((e for e in payload
                    if e.get("data_type") == "transaction"), None)
        if txn is None:
            raise PlaudError("no 'transaction' entry in transcript response")
        code = txn.get("data_error_code")
        if code is not None and code != 10:
            raise PlaudError(f"transcript data_error_code={code}")
        utterances = json.loads(txn["data_content"]) if txn.get("data_content") else []
        if not utterances:
            raise PlaudError("empty transcript")
    else:
        raise PlaudError(
            f"unrecognized transcript shape ({type(payload).__name__})"
        )
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


def reassemble(meta_path: str, transcript_path: str, note_path: Optional[str],
               out_dir: str, *, timezone: Optional[str] = None,
               utc_offset: Optional[str] = None) -> dict:
    meta = _load(meta_path, "meta")
    if not isinstance(meta, dict) or not meta.get("id") or not meta.get("start_at"):
        raise PlaudError("meta must be the list_files entry: id, name, start_at, duration")
    transcript = _load(transcript_path, "transcript")
    note = _load(note_path, "note")

    try:
        start_utc = datetime.fromisoformat(str(meta["start_at"]))
    except ValueError as exc:
        raise PlaudError(f"meta start_at {meta['start_at']!r} is not ISO") from exc
    offset_minutes, _ = dates.resolve_offset_minutes(
        start_utc, timezone, utc_offset)
    local = start_utc + timedelta(minutes=offset_minutes)
    recorded_local = local.strftime("%Y-%m-%d %H:%M:%S")

    body, max_end_ms = _render_transcript(transcript)
    title = meta.get("name") or "Untitled recording"
    parts = [title, "", f"> Recorded: {recorded_local}", "", "#Transcript", body]
    summary = _extract_summary(note)
    if summary:
        parts += ["", ENRICHMENT_HEADER, str(summary).rstrip()]
    blob = "\n".join(parts) + "\n"

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    blob_path = out / f"{meta['id']}.blob.md"
    blob_path.write_text(blob, encoding="utf-8", newline="\n")

    duration_ms = max_end_ms or int(meta.get("duration") or 0)
    return {
        "recording_id": f"plaud:{meta['id']}",
        "duration_min": round(duration_ms / 60000),
        "recorded_local": recorded_local,
        "has_enrichment": summary is not None,
        "blob_path": str(blob_path),
    }
```

- [ ] **Step 4: Wire the CLI** — parser (no `--vault`):

```python
    plaud_group = top.add_parser("plaud", help="Plaud MCP adapter helpers")
    plaud_sub = plaud_group.add_subparsers(dest="action", required=True)
    plaud_re = plaud_sub.add_parser(
        "reassemble", help="render raw MCP JSON into one capture-bundle blob")
    plaud_re.add_argument("--meta", required=True)
    plaud_re.add_argument("--transcript", required=True)
    plaud_re.add_argument("--note")
    plaud_re.add_argument("--out", required=True,
                          help="scratch directory for the blob (never the vault)")
    plaud_re.add_argument("--timezone", help="IANA timezone name")
    plaud_re.add_argument("--utc-offset", dest="utc_offset")
```

Dispatch (import `plaud`):

```python
    if args.group == "plaud":
        return _ok(plaud.reassemble(
            args.meta, args.transcript, args.note, args.out,
            timezone=args.timezone, utc_offset=args.utc_offset))
```

And in `main`:

```python
    except plaud.PlaudError as exc:
        return _fail(str(exc), "Check the raw MCP JSON files named in the error.")
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_plaud.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/plaud.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_plaud.py
git commit -m "feat: plaud reassemble — capture bundles from raw MCP JSON

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Meeting-fixture enrichment + coverage tests

**Files:**
- Modify: all 8 `fixtures/demo-vault/20-meetings/*.md`
- Test: `scripts/tests/test_fixtures_ontology.py`

**Interfaces:**
- Consumes: Task 1's vocabulary tests (they stop being vacuous here).
- Produces: fixtures in `/sync-recordings`' real output shape; three new coverage tests later tasks and P2b rely on.

- [ ] **Step 1: Write the failing coverage tests** — append to `test_fixtures_ontology.py`:

```python
EXEC_SLUG = "morgan-ellery"   # the demo vault's executive (P1a person fixture)


def test_meeting_source_enum_fully_covered():
    files = iter_fixture_files(SCHEMAS["meeting"]["glob"])
    seen = {parse_frontmatter(p).get("source") for p in files}
    expected = SCHEMAS["meeting"]["enums"]["source"]
    assert seen == expected, f"missing source coverage: {expected - seen}"


def test_every_meeting_carries_confidence_stamp():
    # Fixtures model the sync pipeline's REAL output shape (issue #2 rule);
    # a real synced meeting always carries its stamp.
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        fm = parse_frontmatter(path)
        assert "confidence" in fm and "confidence-reasons" in fm, (
            f"{path}: fixture meetings carry the confidence stamp"
        )


def test_confidence_ratings_fully_covered():
    files = iter_fixture_files(SCHEMAS["meeting"]["glob"])
    seen = {parse_frontmatter(p).get("confidence") for p in files}
    expected = SCHEMAS["meeting"]["enums"]["confidence"]
    assert seen == expected, f"missing confidence coverage: {expected - seen}"


def test_executive_attends_every_meeting():
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        attendees = parse_frontmatter(path).get("attendees") or []
        assert EXEC_SLUG in attendees, (
            f"{path}: the executive is in the room in their own vault"
        )


def test_meeting_attendee_joins_resolve():
    person_slugs = slugs_of(SCHEMAS["person"]["glob"])
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        for slug in parse_frontmatter(path).get("attendees") or []:
            assert slug in person_slugs, (
                f"{path}: attendee {slug!r} matches no person fixture"
            )
```

(If a meeting→person join test already exists in the file, keep the existing one and skip the duplicate.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py -q`
Expected: FAIL — source coverage (no `manual`/`email` fixture), missing confidence stamps, executive absent.

- [ ] **Step 3: Enrich the 8 fixtures.** Frontmatter-only edits plus the two source re-tags; bodies stay. Add `morgan-ellery` to every `attendees` list (and `morgan.ellery@cascadia-intermodal.example` to each existing `attendee-emails` list). Insert `confidence` and `confidence-reasons` directly after `archived:` in each file. Per file:

| File | source | recording-duration | confidence | confidence-reasons |
|---|---|---|---|---|
| `01-06-26-commercial-ops-status-update.md` | `email` (re-tag from teams) | `0` (nothing recorded) | `medium` | `[calendar-match-medium, content-keyword-match, all-attendees-known]` |
| `02-03-26-nordbridge-intro-call.md` | `teams` | keep 32 | `high` | `[calendar-match-high, entity-domain-match, "new-attendees:2"]` |
| `05-06-26-pipeline-governance-review.md` | `teams` | keep 30 | `low` | `[calendar-match-low, content-keyword-match, all-attendees-known]` |
| `10-03-26-meridian-steerco-01.md` | `teams` | keep 58 | `high` | `[calendar-match-high, calendar-subject-match, all-attendees-known]` |
| `12-06-26-jordan-1on1.md` | `teams` | keep 22 | `high` | `[calendar-match-high, entity-domain-match, all-attendees-known]` |
| `15-04-26-priya-1on1.md` | `manual` (re-tag) | `0` | `low` | `[no-calendar-match, content-keyword-match, all-attendees-known]` — also set `calendar_match: false` and **remove** the calendar-enriched keys (`organizer`, `location`, `recurring`, `start-time`, `attendee-emails`) if present: a typed note has no calendar enrichment |
| `20-04-26-commercial-ops-workshop.md` | `teams` | keep 75 | `medium` | `[calendar-match-medium, content-keyword-match, "new-attendees:1"]` |
| `20-05-26-meridian-vendor-strategy-brainstorm.md` | `recorder` (already) | keep 41 | `low` | `[calendar-tool-unavailable, content-keyword-match, "new-attendees:1"]` — also add `source-recording-id: inbox:3f9c2a41d8e07b56` next to `source-filename` |

Quote the `new-attendees:2`-style reasons (they contain `:` — PyYAML would otherwise read a nested mapping inside the flow list). Example result for the brainstorm file's frontmatter:

```yaml
---
date: 2026-05-20T11:00
type: brainstorm
calendar-subject: "Vendor strategy — single vs multi-vendor working session"
calendar_match: false
attendees: [priya-nathan, leo-marchetti, jamie-ellwood, morgan-ellery]
projects: [meridian-yard-automation-program]
review_status: needs-review
reviewed: false
archived: false
confidence: low
confidence-reasons: [calendar-tool-unavailable, content-keyword-match, "new-attendees:1"]
recording-duration: 41
source: recorder
source-recording-id: inbox:3f9c2a41d8e07b56
source-filename: "REC-2026-0520-1103.m4a"
processed: true
---
```

(Keep each file's existing `calendar-subject`, `reviewed`, `archived`, and other values as they are — the table lists only what changes.)

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest scripts/tests -q && python3 scripts/lint_plugin.py && python3 scripts/validate_template.py`
Expected: all pass — including Task 1's `test_meeting_confidence_reasons_conform`, now exercised against real stamps, and the Bases/Dataview simulation tests (`test_bases_views.py`) which read these fixtures.

- [ ] **Step 5: Commit**

```bash
git add fixtures/demo-vault/20-meetings scripts/tests/test_fixtures_ontology.py
git commit -m "test: meeting fixtures carry the sync pipeline's real output shape

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: `/sync-recordings` SKILL.md, changelog, version bump

**Files:**
- Create: `plugin/skills/sync-recordings/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py` (expected-skills set)
- Modify: `CHANGELOG.md` (Unreleased entry)
- Modify: `plugin/.claude-plugin/plugin.json` (0.2.0 → 0.3.0)

**Interfaces:**
- Consumes: every CLI subcommand from Tasks 2–7 (the skill-contract test verifies each `"$VAULTLIB" <group> <action>` reference resolves against `cli.build_parser()`).
- Produces: the shipped skill.

- [ ] **Step 1: Extend the failing test** — in `scripts/tests/test_skill_contracts.py`, update:

```python
def test_expected_skills_exist():
    # Each skill task appends its own name here as it lands, so this test is
    # always satisfiable by the task that touches it.
    names = {path.parent.name for path in SKILL_FILES}
    assert {"new-project", "update-entity", "log-decision",
            "sync-recordings"} <= names
```

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q` — expected: FAIL (skill absent).

- [ ] **Step 2: Write the skill** — `plugin/skills/sync-recordings/SKILL.md`, exactly this content:

````markdown
---
name: sync-recordings
description: Sync new meeting transcripts into the vault — from files dropped in the inbox, from a Plaud recorder connector, or from Microsoft 365. Triggers when the user invokes /sync-recordings or asks to sync recordings, process transcripts, or pull in what's in the inbox.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Sync Recordings

Turn captured transcripts into meeting notes in `20-meetings/`. The vault is
the ledger: a recording is synced exactly when its `source-recording-id`
appears in a meeting note, so failed items retry naturally and nothing is
synced twice. You decide routing (projects, attendees, confidence); the CLI
decides what is written.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say so
plainly rather than hand-writing meeting notes.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure surface `error` and `hint`.

## Usage

```
/sync-recordings                 # interactive: show the plan, confirm once, run
/sync-recordings --unattended    # no prompts — scheduled runs and pipeline stages
```

## The three adapters

Read `99-workflow-config/context/tools-and-systems.md` first: it says which
capture channels this deployment uses. Then, per adapter, verify the tools
actually exist before running it. An adapter that is declared but unavailable
is **skipped with an explicit line in the summary** — never a silent zero.

| Adapter | Discovery | Availability check |
|---|---|---|
| `inbox` | `sync scan` over `10-inbox/` | always available |
| `plaud` | Plaud MCP `list_files` | ToolSearch finds `mcp__plaud__list_files` |
| `m365` | — | **not yet supported** — the retrieval path is pending verification; say so if declared |

## Workflow

### 1. Scan and dedup

**Inbox:**

```bash
python3 "$VAULTLIB" sync scan --vault "$VAULT"
```

`candidates` are files whose content hash is in no meeting note and not on
the skip list. Which candidates are actually transcripts is your judgment —
read the head of each file; a forwarded email that is meeting notes by
another name qualifies, a random PDF does not. Report `already_synced` files
so the user can archive them (inbox discipline: nothing lives there).

**Plaud** (when available): call `mcp__plaud__list_files` for the recent
window. Write the raw JSON result to your session scratch directory with the
Write tool — never echo large JSON through Bash. Then dedup the ids,
namespaced:

```bash
printf '%s' '["plaud:abc123", "plaud:def456"]' > "$SCRATCH/ids.json"
python3 "$VAULTLIB" sync dedup --vault "$VAULT" --ids "$SCRATCH/ids.json"
```

Only `new` ids proceed. For each: `mcp__plaud__get_transcript` (required — on
a transient error retry up to 3×, then skip this recording this run; it
retries next run by construction) and `mcp__plaud__get_note` (optional
enrichment — on failure proceed without). Write each raw result to scratch,
then normalize:

```bash
python3 "$VAULTLIB" plaud reassemble \
  --meta "$SCRATCH/rec_42.meta.json" \
  --transcript "$SCRATCH/rec_42.transcript.json" \
  --note "$SCRATCH/rec_42.note.json" \
  --out "$SCRATCH" --timezone <executive-timezone>
```

The result names the blob file and carries `recording_id`, `duration_min`,
and `recorded_local`. On a Plaud **401**: report it and stop this adapter —
never retry auth in a loop; re-authentication is interactive and belongs to
the user.

The executive's timezone is prose in
`99-workflow-config/context/identity.md` — read it and pass the IANA name.
If the host cannot resolve timezone names, the error's hint says to pass
`--utc-offset` instead.

### 2. Calendar enrichment (optional, honest about absence)

If the Microsoft 365 calendar tool is available (ToolSearch
`outlook_calendar_search`), match each recording to a calendar event. Compute
the query window deterministically:

```bash
python3 "$VAULTLIB" dates window --start 2026-08-20T16:42 --timezone <tz>
```

Query with `utc_from`/`utc_to`. Score candidates: title-keyword overlap and
attendee-name matches beat same-day-only. A match pre-fills
`calendar-subject`, `organizer`, `location`, `recurring`, `attendee-emails`.

**Stamp honestly — these are different facts, never collapse them:**

- searched, nothing matched → reason `no-calendar-match`
- tool missing or errored → reason `calendar-tool-unavailable`

(Upstream, collapsing them hid a six-day connector outage.)

### 3. Route: projects and attendees

Judgment, with signals in this order — stop at the first confident match:

1. External attendee email domains → entity: list `40-entities/*/`, match the
   domain root against entity slugs, then link that entity's active projects
   (`30-projects/*/index.md` where `entity` matches).
2. Calendar subject keywords against project names and slugs.
3. Transcript content keywords against project names and slugs (lower
   confidence).

An empty `projects: []` is fine — triage catches unassigned meetings. Never
force a link.

Attendees are **person slugs**. For each attendee named by the calendar or
clearly identified in the transcript, ensure the note exists:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<Full Name>"
```

Use the returned slugs. The executive attends their own meetings — include
them. Names only guessed from transcript audio are unreliable: leave them
out of `attendees` and mention them in the debrief instead.

### 4. Stamp confidence

Every meeting gets `confidence` + `confidence-reasons` — exactly one reason
per group (vocabulary: ontology §Meeting):

| Rating | When |
|---|---|
| `high` | calendar-match-high AND a strong link (`entity-domain-match` or `calendar-subject-match`) AND `all-attendees-known` |
| `medium` | calendar match high or medium AND any project link AND at most one new attendee — but not qualifying for high |
| `low` | everything else |

There is no auto-confirm: every synced meeting lands `needs-review`, and the
reviewed checkbox in Meetings.base is the confirm path. The stamp is the data
a future calibration needs — write it accurately, not optimistically.

### 5. Confirm the plan (interactive mode only)

Skipped entirely under `--unattended`. Show one table — title, date,
projects, new people, confidence — and ask once: proceed / edit / skip
items. For a recording the user says to permanently drop:

```bash
python3 "$VAULTLIB" sync skip --vault "$VAULT" --id plaud:abc123
```

### 6. Extract and write

For each recording, build the payload and write. With several recordings,
fan out subagents (one per recording, up to ~4 in parallel) and pass each
one: the blob or file content, the routing you decided (projects, attendee
slugs, confidence stamp, calendar fields), and the payload contract below.
Extraction is structured work — takeaways, debrief, action items **from the
transcript**; enrichment summaries are supporting context only, never the
source of record.

```bash
cat > "$SCRATCH/rec_42.payload.json" <<'JSON'
{
  "title": "vendor strategy walk-through",
  "date": "2026-05-20T11:03",
  "type": "brainstorm",
  "calendar-subject": "Vendor strategy — working session",
  "calendar_match": false,
  "attendees": ["priya-nathan", "morgan-ellery"],
  "projects": ["meridian-yard-automation-program"],
  "recording-duration": 40,
  "source": "recorder",
  "source-recording-id": "plaud:rec_42",
  "source-filename": "Vendor strategy walk-through",
  "confidence": "low",
  "confidence-reasons": ["calendar-tool-unavailable", "content-keyword-match", "all-attendees-known"],
  "takeaways": ["Consolidating on a single automation vendor.", "Yard 2 commissioning slips ~6 weeks."],
  "debrief": "### Vendor strategy\nWhat was argued, by whom, and what shifted.",
  "action-items": ["**Priya Nathan** — circulate the revised schedule"]
}
JSON
python3 "$VAULTLIB" meeting write --vault "$VAULT" --note "$SCRATCH/rec_42.payload.json"
```

Payload rules the CLI enforces (so get them right the first time):

- `title` is a short kebab-able label — the filename becomes
  `{DD-MM-YY}-{title-slug}.md`. `date` is ISO, the recording's local start.
- `attendees`/`projects` are slugs and must resolve (person notes, project
  folders). `takeaways` is 1–5 strings. `type` values with a colon
  (`"1:1"`) are handled by the CLI — pass them as plain strings.
- Do NOT pass `review_status`, `reviewed`, `archived`, or `processed` — the
  CLI sets them.
- Inbox files: `source-recording-id` is the `recording_id` from `sync scan`.
  Every write carries one — it IS the dedup ledger.

Read the result: a `conflict` of kind `confirmed-target` means the CLI wrote
a `--v2` sibling marked `needs-attention` instead of touching a confirmed
note — report it, it surfaces in triage. `stem-collision` means a `-2`
suffix. An `error` about an already-synced id means dedup was bypassed —
stop and say so.

### 7. Summarize — from disk, not from memory

Count what exists, not what you intended (a lab run once reported
"Processed: 0" after writing a meeting correctly):

```
## Sync Complete
**Processed:** {N} → `20-meetings/` ({list the stems})
**New people:** {N} created in `50-people/`
**Needs attention:** {N} (would have overwritten confirmed notes)
**Skipped / errors:** {N} (will retry next run)
**Adapters:** inbox ok · plaud ok · m365 not configured
**Calendar enrichment:** ok | UNAVAILABLE
```

## Unattended mode

`--unattended` is what scheduled runs and the evening pipeline pass. Two
rules, not negotiable:

1. **Never ask a question.** A blocked prompt means the run exits having
   done nothing. Ambiguity → skip that recording and report it; it retries
   next run.
2. **Prefer under-routing to wrong routing.** No confident project match →
   `projects: []` and low confidence; triage exists for exactly this.

## Rules

1. **Every write goes through `meeting write`.** No hand-authored
   frontmatter, ever.
2. **`source-recording-id` on every synced meeting.** The vault is the only
   ledger; an id that is missing makes the recording sync twice.
3. **Transcript-first.** Recorder summaries and calendar data enrich; the
   transcript is the source of record.
4. **Never overwrite a confirmed meeting.** The CLI guards this; if you see
   a `confirmed-target` conflict, report it — do not work around it.
5. **`calendar-tool-unavailable` ≠ `no-calendar-match`.** Couldn't look vs
   looked and found nothing.
6. **Errors are not recorded.** A failed recording writes nothing and
   reappears next run. Never write a partial note to mark an attempt.
````

- [ ] **Step 3: Changelog + version bump.** In `CHANGELOG.md`, add under `## Unreleased` (above the existing entries):

```markdown
- **`/sync-recordings` — transcripts become meeting notes.** Drop a
  transcript in the inbox (or connect a Plaud recorder) and the sync turns
  it into a structured meeting note: takeaways, debrief, action items,
  attendees, and a link to the right project. Every note lands in the
  Meetings review queue with an honest confidence stamp saying how sure the
  routing is — nothing is auto-confirmed, and nothing is ever synced twice.
  Ticking "reviewed" in the Meetings base now confirms the note. (#14)
```

In `plugin/.claude-plugin/plugin.json`: `"version": "0.2.0"` → `"0.3.0"`.

- [ ] **Step 4: Run the full trio**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all pass — `test_skill_contracts` now also verifies every `"$VAULTLIB" <group> <action>` in the new SKILL.md exists in `cli.build_parser()`, and `lint_plugin` accepts the frontmatter + provenance.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/sync-recordings plugin/.claude-plugin/plugin.json CHANGELOG.md scripts/tests/test_skill_contracts.py
git commit -m "feat: /sync-recordings — three-adapter transcript intake skill

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: End-to-end verification and PR

**Files:** none created — verification only.

- [ ] **Step 1: Full local CI**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
python3 -m pytest scripts/tests -q
```

Expected: exit 0, exit 0, all tests passing (baseline was 515; expect ~560+).

- [ ] **Step 2: Hand-test against a scratch vault** (the runbook check from the spec):

```bash
python3 scripts/make_test_vault.py /tmp/p2a-vault --with-plugins
cp fixtures/demo-vault/10-inbox/2026-08-19-teams-transcript-nordbridge-checkin.txt /tmp/p2a-vault/10-inbox/
python3 plugin/lib/vaultlib/cli.py sync scan --vault /tmp/p2a-vault
```

Expected: `ok: true` and the transcript appears under `candidates` (if `make_test_vault` also copied the fixture inbox, the identical copy shares the same `recording_id` — that shared id is the ledger working). Then exercise a real write:

```bash
python3 plugin/lib/vaultlib/cli.py dates window --start 2026-08-19T10:00 --utc-offset -05:00
printf '%s' '{"title":"nordbridge quarterly check in","date":"2026-08-19T10:00","type":"meeting","calendar-subject":"Nordbridge quarterly check-in","calendar_match":false,"attendees":["jordan-vance","morgan-ellery"],"projects":["nordbridge-regional-rollout-proposal"],"recording-duration":35,"source":"teams","source-recording-id":"inbox:cafe2a41d8e07b99","confidence":"low","confidence-reasons":["calendar-tool-unavailable","content-keyword-match","all-attendees-known"],"takeaways":["ERP freeze holds through Q3."],"debrief":"### Check-in\nPhase 1 scoped around the Kentucky plant."}' > /tmp/p2a-payload.json
python3 plugin/lib/vaultlib/cli.py meeting write --vault /tmp/p2a-vault --note /tmp/p2a-payload.json
```

Expected: `ok: true`, note at `20-meetings/19-08-26-nordbridge-quarterly-check-in.md`; open it and read it as the judged artifact. Re-run the same `meeting write` — expected: `ok: false` with the already-synced hint (ledger works).

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: /sync-recordings — daily-loop P2a (#14)" --body "$(cat <<'EOF'
Closes #14. Implements P2a of docs/superpowers/specs/2026-08-23-daily-loop-port-design.md
(also included, with its implementation plan): three-adapter transcript intake
over new vaultlib subcommands (dates window, sync scan/dedup/skip/reconcile-reviews,
plaud reassemble, meeting write), the §Meeting ontology extension (confidence
stamp, source enum, source-recording-id, conflicts-with), and meeting-fixture
enrichment to the pipeline's real output shape. Version 0.2.0 → 0.3.0.

Not in this PR (P2b, after this merges): /evening-sync, the daily-note
contract, update-queue metrics.
EOF
)"
```

Expected: three required checks green; `claude-review` posts findings or "No issues found". Do not merge with red CI.

---

## Self-Review Notes

- **Spec coverage:** §Meeting extension → Task 1; `dates` → Task 2; `sync scan`/dedup ledger + skip list → Task 3; reconcile-reviews → Task 4; `meeting write` + guards (`--v2` sibling, `conflicts-with`) → Tasks 5–6; plaud adapter/capture bundle → Task 7; fixture enrichment (executive in attendees, stamps, source coverage, recording id) → Task 8; skill + adapters-as-configuration + unattended rules + m365 stub → Task 9; hand-test runbook → Task 10. Spec items deliberately absent here (P2b): `update-queue`, `daily-note`, `/evening-sync`, §Daily-note block, daily-note fixtures.
- **Deviations from spec, argued:** (1) The lab overwrote non-confirmed stem collisions; this plan suffixes instead — §Meeting is write-once and the ledger already covers re-syncs (noted in Task 6). (2) `sync skip` + the skip list is not named in the spec's subcommand table but is required for "never propose this again" to survive across runs; it is the lab's `skipped-plaud-ids.txt` generalized. (3) `dates` ships as `dates window` only; the spec's recap-window/next-business-day duties are P2b, where their consumer lives.
- **Type consistency:** `syncjob` (not `sync`) is the module name to avoid shadowing ambiguity; the CLI group remains `sync`. `recording_id` in results, `source-recording-id` in frontmatter/payloads. `_validate_id` is intentionally reused by `meeting.py` (single namespace authority).
