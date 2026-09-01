# Dates Window Discovery Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/sync-recordings` step 1 gets a real, parsing trailing-window
invocation whose future edge can never pass "now", triage refuses meetings
that have not ended, the skill's scratch-verbatim rule covers event JSON, and
a contract test validates skill-prescribed `dates window` invocations against
the real argparse parser.

**Architecture:** A new `--trailing-days` discovery mode on `dates window`
(mutually exclusive with `--start`), implemented as `dates.trailing_window()`
with `utc_to = now` by construction and the existing `sync.start-date` floor
reused verbatim. A not-ended guard in `seenevents.triage()` — the cheap
listing layer that gates every fetch — defers future occurrences without
recording anything. Skill text moves the step-1 prescription into a fenced
block; a new contract test extracts every fenced `dates window` invocation
and runs it through `cli.build_parser().parse_args`.

**Tech Stack:** Python stdlib only (plugin runtime), pytest (scripts/tests),
argparse.

**Spec:** the GitHub issue filed for this fix (sync-recordings discovery
window: skill prescribes a non-parsing dates window call; improvised windows
reach into the future) — root cause verified against
`plugin/lib/vaultlib/cli.py:108-124` (`--start` required, `--hours`
half-width default 2), `plugin/skills/sync-recordings/SKILL.md:272-276`
(bare `dates window --vault "$VAULT"` prescribed for discovery), and
`plugin/lib/vaultlib/m365.py` / `seenevents.py` (no future-event guard
anywhere; M365 synthesizes `meetingTranscriptUrl` for future events).

## Global Constraints

- `plugin/lib/` is **stdlib only**; **Python 3.10 syntax floor**; vault root
  always a parameter; writes UTF-8 with `newline="\n"` (plugin/CLAUDE.md).
- Clean-room: nothing new in `plugin/` names clients, people, or PR/issue
  numbers — cite evidence as "a live run …".
- Interpreter in docs/skills: `python3` (fallback chain documented in
  plugin/CLAUDE.md; local gate uses `python3`).
- Do not break existing contract tests: keep `### 6.` heading, "survived
  triage", the banking order (`sync m365-triage` < `m365 ids`;
  `sync m365-record` both before and after `### 6.`), outcome vocabulary,
  and the literal `dates window --vault "$VAULT"` string in the skill.
- Release trio: `plugin/.claude-plugin/plugin.json` → **0.10.14** (verified
  free: only open PR is #90, docs-only), same literal in
  `scripts/tests/test_marketplace_manifest.py:65`, CHANGELOG bullet under
  `## Unreleased` (PR number backfilled after the PR opens).
- Every commit ends with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Local gate before the PR: `python3 scripts/lint_plugin.py &&
  python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`.

## Design decisions (settled here, with rationale)

**D1 — Discovery-mode shape: `--trailing-days N`, mutually exclusive with
`--start`.** An argparse `add_mutually_exclusive_group(required=True)`
holding `--start` and `--trailing-days` keeps the enrichment shape untouched
(anything passing `--start` behaves exactly as today) and makes the bare
call fail with a self-explaining message. The window is **local-midnight
aligned**: `utc_from` = UTC of local midnight `N` days before today's local
date, `utc_to` = the UTC clock now. Rationale: the skill says "trailing 7
local days"; day-boundary alignment matches that phrasing, and a
slightly-generous window is harmless (cache + ledger dedup) where a
`now − 168h` window would cut off a week-old meeting mid-day. `utc_to = now`
by construction satisfies invariant (a). `--hours` is rejected in trailing
mode (it is the enrichment half-width; midnight→now has no half-width): its
argparse default moves to `None` so an explicit value is detectable, and the
dispatch substitutes `2.0` for enrichment. A `--now` override (UTC ISO,
tests only — same convention as `sync m365-triage --now`) is accepted only
with `--trailing-days`. The `sync.start-date` floor logic is extracted into
a private helper used by both `window()` and `trailing_window()` so the
clamp cannot drift between the two modes.

**D2 — Future-event guard lives in `seenevents.triage()`.** Triage is the
one gate every occurrence passes before any money is spent: it sees the
cheap listing (which carries `start`/`end` as UTC dateTime + timeZone — and
`_occurrence_dt` already refuses non-UTC), it already has `now_utc` plumbed
(`--now`), and refusing there kills the whole class — no full event fetch,
no `m365 ids`, no dispatch, nothing banked. The guard runs **before** the
cache lookup so no cache content can resurrect a future occurrence. A
deferred occurrence goes into a new top-level `deferred` list (reason
`not-ended`), never into `fetch` and never into any banked outcome, so after
the meeting ends the next run's triage finds no cache entry and fetches it
normally — invariant satisfied structurally. In-progress meetings
(start ≤ now < end) are deferred too: no transcript can exist before the
meeting ends. A guard in `m365 ids` instead would fire after the expensive
fetch, would need new `--now` plumbing, and would still let the fetch be
paid; with the window fix (utc_to ≤ now) plus the triage guard there are
already two independent layers.

**D3 — Argparse-validation test scope.** The new contract test extracts
every `dates window` invocation that appears **inside a fenced code block**
of any SKILL.md or references file, substitutes shell placeholders
(`"$VAULT"`, `<tz>`), and `parse_args`es it against `cli.build_parser()`
with a SystemExit guard. It additionally asserts the sync-recordings M365
discovery section contains such a fenced invocation carrying
`--trailing-days` — that second assertion is what would have caught the
original bug, where the "prescription" existed only as inline prose.
Full generality across all CLI commands is disproportionate (most
invocations carry payload-file args whose validity is not parse-level);
pinning the `dates window` family — the shape that shipped broken — is the
acceptance bar, and both current fenced `dates window` invocations
(step 1 discovery, step 2 enrichment) are covered.

## File structure

- Modify: `plugin/lib/vaultlib/dates.py` — `_parse_now()`, `_start_date_floor()` helper, `trailing_window()`
- Modify: `plugin/lib/vaultlib/cli.py:108-124` (parser), `:470-479` (dispatch)
- Modify: `plugin/lib/vaultlib/seenevents.py` — not-ended guard in `triage()`
- Modify: `plugin/skills/sync-recordings/SKILL.md` — rule 8, "The three adapters" intro (stays truthful as-is; verify), M365 step-1 discovery paragraph, triage paragraph, summary line
- Modify: `scripts/tests/test_vaultlib_dates.py`, `scripts/tests/test_vaultlib_seenevents.py`, `scripts/tests/test_skill_contracts.py`
- Modify: `plugin/.claude-plugin/plugin.json`, `scripts/tests/test_marketplace_manifest.py`, `CHANGELOG.md`

---

### Task 1: `dates.trailing_window()` + CLI discovery mode

**Files:**
- Modify: `plugin/lib/vaultlib/dates.py`
- Modify: `plugin/lib/vaultlib/cli.py:108-124, 470-479`
- Test: `scripts/tests/test_vaultlib_dates.py`

**Interfaces:**
- Produces: `dates.trailing_window(days: int, *, timezone: Optional[str] = None, utc_offset: Optional[str] = None, start_date: Optional[str] = None, now_utc: Optional[datetime] = None) -> dict` with keys `trailing_days`, `now_utc`, `utc_from`, `utc_to`, `offset`, `offset_source`, and (when `start_date` given) `start_date`, `clamped`, `window_empty`. CLI: `dates window --trailing-days N [--now ISO]`, `--start`/`--trailing-days` mutually exclusive and one required, `--hours` default now `None` (dispatch substitutes 2.0 for enrichment).

- [ ] **Step 1: Write the failing tests** (append to `scripts/tests/test_vaultlib_dates.py`, after the window tests)

```python
def test_trailing_window_ends_now_and_starts_at_local_midnight():
    # now: 2026-09-01T10:00 UTC = 12:00 local at +02:00; 7 local days back
    # from Sep 1 is Aug 25; local midnight Aug 25 at +02:00 = Aug 24 22:00 UTC.
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now)
    assert result["utc_to"] == "2026-09-01T10:00:00"
    assert result["utc_from"] == "2026-08-24T22:00:00"
    assert result["trailing_days"] == 7
    assert result["offset"] == "+02:00"
    assert result["offset_source"] == "explicit"


def test_trailing_window_never_reaches_past_now():
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now)
    assert result["utc_to"] <= "2026-09-01T10:00:00"


def test_trailing_window_clamps_to_start_date():
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now,
                                   start_date="2026-08-28")
    # floor: local midnight Aug 28 at +02:00 = Aug 27 22:00 UTC
    assert result["utc_from"] == "2026-08-27T22:00:00"
    assert result["utc_to"] == "2026-09-01T10:00:00"
    assert result["clamped"] is True
    assert result["window_empty"] is False


def test_trailing_window_entirely_before_a_future_start_date_is_empty():
    now = datetime(2026, 9, 1, 10, 0, 0)
    result = dates.trailing_window(7, utc_offset="+02:00", now_utc=now,
                                   start_date="2026-09-15")
    assert result["window_empty"] is True
    assert result["utc_from"] == result["utc_to"]


def test_trailing_window_rejects_a_nonpositive_day_count():
    with pytest.raises(dates.DatesError):
        dates.trailing_window(0, utc_offset="+02:00")
    with pytest.raises(dates.DatesError):
        dates.trailing_window(-3, utc_offset="+02:00")


def test_cli_bare_window_call_fails_to_parse():
    """The live failure: the skill used to prescribe `dates window --vault X`
    with no mode flag, which argparse refuses. Pin that refusal."""
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window", "--vault", "/nowhere"],
        capture_output=True, text=True)
    assert proc.returncode != 0
    assert "--start" in proc.stderr and "--trailing-days" in proc.stderr


def test_cli_trailing_window_envelope():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--trailing-days", "7", "--utc-offset", "+02:00",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["utc_to"] == "2026-09-01T10:00:00"
    assert payload["result"]["utc_from"] == "2026-08-24T22:00:00"


def test_cli_trailing_window_refuses_hours():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--trailing-days", "7", "--utc-offset", "+02:00", "--hours", "4"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "hours" in payload["error"]


def test_cli_now_requires_trailing_mode():
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "window",
         "--start", "2026-08-20T16:42", "--utc-offset", "+02:00",
         "--now", "2026-09-01T10:00:00"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dates.py -q`
Expected: FAIL — `AttributeError: module 'vaultlib.dates' has no attribute 'trailing_window'`, and the CLI tests fail on unknown `--trailing-days`.

- [ ] **Step 3: Implement**

In `dates.py`, extract the floor logic shared with `window()` and add:

```python
def _parse_now(text: str) -> datetime:
    """A UTC ISO override (tests) -> naive UTC datetime."""
    raw = str(text).strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1]
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DatesError(f"now {text!r} must be a UTC ISO datetime") from exc


def _start_date_floor(result: dict, lo_utc: datetime, hi_utc: datetime,
                      start_date, timezone, utc_offset) -> dict:
    """Clamp [lo_utc, hi_utc] to the vault's sync start date (local
    midnight). Shared by both window modes so the clamp cannot drift."""
    floor_local = datetime.combine(_parse_date(start_date, "start-date"),
                                   datetime.min.time())
    floor_offset, _ = resolve_offset_minutes(floor_local, timezone, utc_offset)
    floor_utc = floor_local - timedelta(minutes=floor_offset)
    result["start_date"] = str(start_date).strip()
    result["window_empty"] = hi_utc < floor_utc
    result["clamped"] = lo_utc < floor_utc
    if result["window_empty"]:
        result["utc_from"] = result["utc_to"] = floor_utc.strftime(_UTC_FMT)
    elif result["clamped"]:
        result["utc_from"] = floor_utc.strftime(_UTC_FMT)
    return result


def trailing_window(days: int, *, timezone: Optional[str] = None,
                    utc_offset: Optional[str] = None,
                    start_date: Optional[str] = None,
                    now_utc: Optional[datetime] = None) -> dict:
    """Discovery mode: the trailing `days` local days, ending exactly now.

    `utc_to` is the UTC clock at call time — by construction the window
    never reaches into the future, so a calendar search over it can never
    list a meeting that has not happened. `utc_from` is local midnight
    `days` days before today's local date: day-boundary aligned because the
    callers reason in "trailing N local days", and a slightly generous
    window is harmless (the seen-events cache and the vault ledger dedup)
    where an hour-arithmetic window would cut off a week-old meeting
    mid-day. The `start_date` floor is the same clamp `window` applies.
    """
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise DatesError(f"trailing-days {days!r} must be a positive integer")
    if now_utc is None:
        now_utc = datetime.now(_timezone.utc).replace(tzinfo=None,
                                                      microsecond=0)
    local_now, source = utc_to_local(now_utc, timezone, utc_offset)
    from_local = datetime.combine(local_now.date() - timedelta(days=days),
                                  datetime.min.time())
    from_offset, _ = resolve_offset_minutes(from_local, timezone, utc_offset)
    lo_utc = from_local - timedelta(minutes=from_offset)
    result = {
        "trailing_days": days,
        "now_utc": now_utc.strftime(_UTC_FMT),
        "utc_from": lo_utc.strftime(_UTC_FMT),
        "utc_to": now_utc.strftime(_UTC_FMT),
        "offset": _format_offset(
            round((local_now - now_utc).total_seconds() / 60)),
        "offset_source": source,
    }
    if start_date is None:
        return result
    return _start_date_floor(result, lo_utc, now_utc, start_date,
                             timezone, utc_offset)
```

Rewrite the tail of `window()` (the `if start_date is None: return result`
block onward) to call `_start_date_floor(result, lo - shift, hi - shift,
start_date, timezone, utc_offset)` — behavior identical, one clamp.

In `cli.py` parser (lines 110-124): replace the `--start` add_argument with
a mutually exclusive required group; add `--now`; `--hours` default `None`:

```python
    dates_mode = dates_window.add_mutually_exclusive_group(required=True)
    dates_mode.add_argument("--start",
                            help="enrichment mode: local ISO date or datetime "
                                 "the window centers on")
    dates_mode.add_argument("--trailing-days", dest="trailing_days", type=int,
                            help="discovery mode: the trailing N local days, "
                                 "ending now — the window never reaches into "
                                 "the future")
    dates_window.add_argument("--timezone", help="IANA timezone name")
    dates_window.add_argument("--utc-offset", dest="utc_offset",
                              help="explicit offset like -05:00")
    dates_window.add_argument("--hours", type=float, default=None,
                              help="enrichment half-width (default 2); "
                                   "not accepted with --trailing-days")
    dates_window.add_argument(
        "--now", help="UTC ISO datetime override (tests); "
                      "--trailing-days only")
```

In `_dispatch` (lines 470-476):

```python
        if args.action == "window":
            start_date = (config.read(root)["config"]["sync"]["start-date"]
                          if root is not None else None)
            if args.trailing_days is not None:
                if args.hours is not None:
                    raise dates.DatesError(
                        "--hours is the enrichment half-width; the trailing "
                        "window runs local midnight to now and takes none")
                now_utc = (dates._parse_now(args.now)
                           if args.now is not None else None)
                return _ok(dates.trailing_window(
                    args.trailing_days, timezone=args.timezone,
                    utc_offset=args.utc_offset, start_date=start_date,
                    now_utc=now_utc))
            if args.now is not None:
                raise dates.DatesError(
                    "--now applies to --trailing-days discovery only")
            return _ok(dates.window(args.start, timezone=args.timezone,
                                    utc_offset=args.utc_offset,
                                    hours=(2.0 if args.hours is None
                                           else args.hours),
                                    start_date=start_date))
```

- [ ] **Step 4: Run the dates tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dates.py -q`
Expected: PASS, including every pre-existing window/plan test (enrichment shape untouched).

- [ ] **Step 5: Run the full suite to catch collateral**

Run: `python3 -m pytest scripts/tests -q`
Expected: only failures are pre-existing-none; `test_skill_contracts.py` still green (the skill's step-2 invocation carries `--start`).

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/dates.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_dates.py
git commit -m "feat: dates window --trailing-days discovery mode, never past now

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: triage defers occurrences that have not ended

**Files:**
- Modify: `plugin/lib/vaultlib/seenevents.py` (`triage()`)
- Test: `scripts/tests/test_vaultlib_seenevents.py`

**Interfaces:**
- Produces: `triage()` result gains `"deferred": [{"id", "start_utc", "subject", "reason": "not-ended"}]`; `fetch`/`filtered`/`warnings` semantics unchanged.

- [ ] **Step 1: Write the failing tests** (append; reuse `make_vault`, `listing_event`, `outcome`, `NOW = 2026-08-31T18:00`)

```python
def test_triage_defers_an_occurrence_that_has_not_ended(tmp_path):
    """M365 synthesizes meetingTranscriptUrl for future occurrences too, so
    without this guard a future meeting reaches dispatch and can pull a past
    occurrence's transcript — a live run nearly wrote future-dated junk."""
    root = make_vault(tmp_path)
    future = listing_event(start="2026-09-03T14:00:00.0000000",
                           end="2026-09-03T15:00:00.0000000")
    result = seenevents.triage(root, [future], NOW)
    assert result["fetch"] == []
    assert result["deferred"] == [{"id": "AAMkAGId1",
                                   "start_utc": "2026-09-03T14:00:00",
                                   "subject": "Weekly sync",
                                   "reason": "not-ended"}]


def test_triage_defers_a_meeting_still_in_progress(tmp_path):
    root = make_vault(tmp_path)
    running = listing_event(start="2026-08-31T17:30:00.0000000",
                            end="2026-08-31T18:30:00.0000000")
    result = seenevents.triage(root, [running], NOW)
    assert result["fetch"] == []
    assert [e["reason"] for e in result["deferred"]] == ["not-ended"]


def test_triage_defers_a_future_start_with_no_end(tmp_path):
    root = make_vault(tmp_path)
    event = listing_event(start="2026-09-03T14:00:00.0000000")
    del event["end"]
    result = seenevents.triage(root, [event], NOW)
    assert result["fetch"] == []
    assert [e["reason"] for e in result["deferred"]] == ["not-ended"]


def test_a_deferred_occurrence_fetches_normally_after_it_ends(tmp_path):
    root = make_vault(tmp_path)
    event = listing_event(start="2026-09-03T14:00:00.0000000",
                          end="2026-09-03T15:00:00.0000000")
    assert seenevents.triage(root, [event], NOW)["fetch"] == []
    later = datetime(2026, 9, 3, 16, 0, 0)
    result = seenevents.triage(root, [event], later)
    assert result["deferred"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_the_guard_outranks_the_cache(tmp_path):
    # Nothing legitimate can record an outcome for an unfinished occurrence,
    # so if one exists (clock skew, an improvised window) it must not
    # resurrect the fetch — deferral is checked before the cache.
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(start_utc="2026-09-03T14:00:00")],
                      NOW)
    event = listing_event(start="2026-09-03T14:00:00.0000000",
                          end="2026-09-03T15:00:00.0000000")
    result = seenevents.triage(root, [event], NOW)
    assert result["fetch"] == []
    assert result["filtered"]["written"] == 0
    assert [e["reason"] for e in result["deferred"]] == ["not-ended"]


def test_past_events_are_never_deferred(tmp_path):
    root = make_vault(tmp_path)
    result = seenevents.triage(root, [listing_event()], NOW)
    assert result["deferred"] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_seenevents.py -q`
Expected: FAIL with `KeyError: 'deferred'`.

- [ ] **Step 3: Implement**

In `triage()`: initialize `deferred: List[dict] = []`; after `candidate` is
built and **before** the `entries.get(...)` cache lookup insert:

```python
        # A meeting that has not ended cannot have a transcript — M365
        # synthesizes meetingTranscriptUrl for future occurrences of a
        # recurring series, and on those the URL can answer with *past*
        # occurrences' transcripts. Deferral is per-run and never recorded:
        # once the occurrence ends, the next run fetches it normally. Checked
        # before the cache so no recorded outcome can resurrect the fetch.
        end = _occurrence_dt(event, "end") or start
        if end > now_utc:
            deferred.append({**candidate, "reason": "not-ended"})
            continue
```

Return `{"fetch": fetch, "deferred": deferred, "filtered": filtered,
"warnings": warnings}`. Update the docstring's first paragraph to mention
the not-ended deferral. Timezone care: `_occurrence_dt` already refuses a
non-UTC `timeZone` and returns naive UTC, and `now_utc` is naive UTC — the
comparison is same-basis by construction.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_seenevents.py scripts/tests/test_vaultlib_m365.py -q`
Expected: PASS (existing tests never index `deferred`, and all fixture events are in the past relative to their `NOW`).

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/seenevents.py scripts/tests/test_vaultlib_seenevents.py
git commit -m "feat: m365 triage defers occurrences that have not ended

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: skill text — parsing discovery invocation, deferred-future visibility, event-JSON verbatim rule — plus the contract tests that pin them

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md`
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's CLI shape (`--trailing-days 7 --timezone <tz>`), Task 2's `deferred` result key.

- [ ] **Step 1: Write the failing contract tests** (append to `test_skill_contracts.py`)

```python
# The discovery-window regression: the skill used to prescribe a bare
# `dates window --vault "$VAULT"` for step-1 discovery — an invocation that
# does not parse (--start was required), so orchestrators improvised windows
# that reached a week into the future. Two pins: every fenced `dates window`
# invocation must parse against the real argparse parser, and the M365
# discovery paragraph must prescribe the trailing form as a fenced block,
# not as prose.

FENCED_BLOCK_RE = re.compile(r"```(?:bash)?\n(.*?)```", re.DOTALL)
PLACEHOLDERS = {'"$VAULT"': "/placeholder/vault", "<tz>": "Europe/Brussels"}


def fenced_dates_window_invocations(text: str):
    import shlex
    found = []
    for block in FENCED_BLOCK_RE.findall(text):
        for line in block.replace("\\\n", " ").splitlines():
            if "dates window" not in line:
                continue
            command = line[line.index("dates window"):]
            for token, value in PLACEHOLDERS.items():
                command = command.replace(token, value)
            found.append(shlex.split(command))
    return found


@pytest.mark.parametrize("path", SKILL_FILES + REF_FILES,
                         ids=lambda p: p.parent.name)
def test_every_fenced_dates_window_invocation_parses(path):
    parser = cli.build_parser()
    for tokens in fenced_dates_window_invocations(
            path.read_text(encoding="utf-8")):
        try:
            parser.parse_args(tokens)
        except SystemExit:
            pytest.fail(
                f"{path.parent.name} prescribes a dates window invocation "
                f"argparse refuses: {' '.join(tokens)}")


def test_sync_recordings_discovery_window_is_a_fenced_trailing_invocation():
    text = read_skill("sync-recordings")
    m365 = text.split("**Microsoft 365**")[1].split("### 2.")[0]
    invocations = fenced_dates_window_invocations(m365)
    assert invocations, (
        "step 1 must prescribe the discovery window as a fenced invocation — "
        "a prose-only mention is how a non-parsing call shipped")
    assert any("--trailing-days" in tokens and "--vault" in tokens
               for tokens in invocations), (
        "the discovery window must be the trailing form, vault-clamped")


def test_sync_recordings_reports_deferred_future_meetings():
    text = read_skill("sync-recordings")
    assert "not-ended" in text, (
        "triage's deferred-future bucket must be surfaced, not lumped into "
        "no-transcript outcomes")
    assert text.index("not-ended") < text.index("### 2."), (
        "the deferral is a step-1 triage fact")


def test_sync_recordings_extends_verbatim_rule_to_event_json():
    rules = read_skill("sync-recordings").split("## The three adapters")[0]
    flat = re.sub(r"\s+", " ", rules)
    assert "full-event JSON" in flat, (
        "rule 8 must cover event reads — a live run re-typed events from "
        "memory and garbled transcript URLs and ids")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: the three sync-recordings tests FAIL (no fenced trailing invocation, no `not-ended`, no `full-event JSON`); the parametrized parse test PASSES only for files whose fenced `dates window` lines already parse (the step-2 enrichment block does) — confirm it fails if fed the old bare form by inspection of the step-1 edit below.

- [ ] **Step 3: Edit the skill**

(a) **Rule 8** — append before the closing parenthetical sentence, keeping
the rule one paragraph:

> The same verbatim rule covers **full-event JSON**: every
> `$SCRATCH/m365_event_<n>.json` and the `m365_events.json` array hold the
> tool results' content unchanged — a live run that re-typed events "from
> memory" garbled three transcript URLs and two ids before catching itself.

(b) **M365 step-1 discovery paragraph** (current lines 270-281): replace the
parenthetical prescription with a fenced invocation. New text:

> **Microsoft 365** (when enabled, available, and account-verified): Teams
> transcribes meetings on the vault owner's calendar, and the calendar event
> is the key to its own transcript. Compute the discovery window — the
> trailing **7 local days**, ending now:
>
> ```bash
> python3 "$VAULTLIB" dates window --vault "$VAULT" --trailing-days 7 --timezone <tz>
> ```
>
> Pass its `utc_from`/`utc_to` to `outlook_calendar_search` as
> `afterDateTime`/`beforeDateTime` — the clamp to `sync.start-date` rides
> along, and the window ends at *now*, never in the future: M365 synthesizes
> a transcript URL even for meetings that have not happened, so a window
> that reaches forward lists events nothing can honestly sync yet. A
> `window_empty: true` result means skip the search outright. Drop cancelled
> and all-day events, and keep online meetings. The tool answers at most
> **25 events per call**: …(rest of paragraph unchanged).

(c) **Triage paragraph** (after "filtered counts occurrences …
transcript-less." sentence): add:

> Occurrences whose meeting has not yet ended come back in `deferred`
> (reason `not-ended`) — count them in the summary, bank nothing for them,
> and let them sync normally on the first run after they end.

(d) **Summary line** (step 7, "Workers dispatched"): extend the
not-dispatched reasons with `, or hadn't ended yet ({N})`.

(e) Verify, do not edit: the "three adapters" intro sentence
(`dates window --vault "$VAULT"` clamps every query window) stays literally
true — trailing mode clamps identically via the shared floor helper — and
the literal string `dates window --vault "$VAULT"` still appears (contract
test `test_sync_recordings_states_the_start_date_bound`). Line 96's
deliberate-backfill escape hatch (`dates window` without `--vault`) also
stays true: enrichment mode with an explicit `--start` still exists.

- [ ] **Step 4: Run the contract tests and the ordering guards**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS — including the pre-existing `test_sync_recordings_triages_m365_before_the_fetch`, `test_sync_recordings_dispatches_workers_only_after_triage_and_dedup`, `test_sync_recordings_states_the_start_date_bound`, and worker-vocabulary tests.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "fix: sync-recordings prescribes the parsing trailing-window call and verbatim event JSON

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: release trio

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json` (`0.10.13` → `0.10.14`)
- Modify: `scripts/tests/test_marketplace_manifest.py:65` (same literal)
- Modify: `CHANGELOG.md` under `## Unreleased`

- [ ] **Step 1: Bump both version literals**

- [ ] **Step 2: CHANGELOG bullet** (client-visible voice, PR number backfilled after the PR opens):

> - `/sync-recordings` no longer trips over future meetings: the discovery
>   window is computed by the CLI (trailing 7 days, ending now, never
>   forward), and a meeting that has not ended yet is deferred until after
>   it happens instead of being fetched — a run can no longer draft notes
>   for meetings that haven't taken place (#TBD)

- [ ] **Step 3: Run the full local gate**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all three green.

- [ ] **Step 4: Commit, push, open the PR**

```bash
git add plugin/.claude-plugin/plugin.json scripts/tests/test_marketplace_manifest.py CHANGELOG.md docs/superpowers/plans/2026-09-01-dates-window-discovery.md
git commit -m "chore: bump plugin to 0.10.14 with changelog

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin claude/dates-window-discovery
gh pr create ...   # body: root cause, the four changes + test hole, gate tail,
                   # "Closes #<issue>", note the sb-dist-dryrun re-cut after merge
```

- [ ] **Step 5: Backfill the PR number into the CHANGELOG bullet, commit, push** (prior PRs' pattern)

## Self-review

- Spec coverage: fix 1 → Task 1; fix 2 → Task 3(b,e); fix 3 → Task 2 +
  Task 3(c,d); fix 4 → Task 3(a); test hole → Task 3 (`fenced_dates_window_invocations`
  + the discovery-section assertion). Release trio + issue/PR → Task 4 and
  the execution notes. No gaps found.
- Placeholders: none — the `#TBD` in the CHANGELOG bullet is the documented
  backfill step, not a plan gap.
- Type consistency: `trailing_window` signature matches Task 1 tests and the
  Task 3 skill invocation; `deferred` key name matches Task 2 tests and the
  Task 3(c) prose; `--now` parse helper `_parse_now` used only by cli.py.
