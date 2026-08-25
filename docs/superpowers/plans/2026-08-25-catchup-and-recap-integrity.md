# Catch-up Visibility and Recap Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/evening-sync` say when it is catching up after missed days, stop it rewriting a recap whose inputs have not changed, and refuse any name in a machine region that does not resolve to a vault object.

**Architecture:** Three deterministic guarantees move into `vaultlib`, where they can be tested, and out of skill prose, where they were hoped for. `dates` learns business-day counting and reports the gap as data. `dailynote` learns an optional `key=value` grammar on its region markers, stamps a content fingerprint of the recap's inputs onto the recap marker, skips the recap region when that fingerprint is unchanged, renders the catch-up banner itself, and validates every wikilink in payload content against the vault. `evening-sync/SKILL.md` then consumes facts instead of deriving them.

**Tech Stack:** Python 3.10 stdlib only (`hashlib`, `re`, `datetime`, `pathlib`), pytest, argparse. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-25-catchup-and-recap-integrity-design.md` — read it before Task 1. Decisions 15–19 there are the "why" behind every task below.

## Global Constraints

Every task's requirements implicitly include all of these.

- **Stdlib only** in `plugin/lib/`. PyYAML's presence in the Cowork VM is unverified; nothing parses YAML at runtime.
- **Python 3.10 is the syntax floor.** Cowork ships 3.10; CI runs 3.13. A 3.11+ construct fails only on the client machine.
- **The vault root is always a parameter** (`root: Path`), never inferred.
- **Writes are UTF-8 with `newline="\n"`** — always through `vault.atomic_write`.
- **Clean-room rule:** nothing in `plugin/` or `template/` may name a delaware client, a real person, or a busdev path. Test fixtures use the demo vault's fictional names (Meridian Freight Holdings, Nordbridge Components, commercial-operations).
- **Every commit message ends with the exact trailer:** `Co-Authored-By: Claude <noreply@anthropic.com>`
- **No SKILL.md may reference `identity.md` or `tools-and-systems.md`** — a contract test from #62 forbids it. Machine decisions come from `config read`.
- **Version bump is mandatory** for any PR touching `plugin/` except `plugin/CLAUDE.md`: `plugin/.claude-plugin/plugin.json` goes `0.5.0` → `0.6.0`. Task 7 owns it.
- **CI is three commands**, all runnable locally:
  ```bash
  python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q
  ```

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `plugin/lib/vaultlib/dates.py` | business-day counting; the catch-up block on `plan()` | 1 |
| `plugin/lib/vaultlib/cli.py` | `--catchup-threshold` wiring | 1 |
| `plugin/lib/vaultlib/dailynote.py` | marker attribute grammar | 2 |
| `plugin/lib/vaultlib/meeting.py` | `date_from_stem` — the inverse of `_date_prefix` | 3 |
| `plugin/lib/vaultlib/dailynote.py` | recap fingerprint, `recap_window` validation, skip-on-unchanged | 3 |
| `plugin/lib/vaultlib/dailynote.py` | catch-up banner rendering | 4 |
| `plugin/lib/vaultlib/dailynote.py` | wikilink resolution + identity alias check | 5 |
| `plugin/skills/evening-sync/SKILL.md` | stages 1/6/7, unattended, Rules 10–11 | 6 |
| `plugin/CLAUDE.md` | the two new CLI-boundary contracts | 6 |
| `CHANGELOG.md`, `plugin/.claude-plugin/plugin.json` | release notes + version | 7 |

`dailynote.py` is 404 lines and grows by roughly 180. It stays one file: every addition is a region-merge concern, and the module docstring already frames it as "the machine half of a daily note". Splitting it would separate the marker grammar from its only consumer.

---

### Task 1: `dates` — business-day counting and the catch-up block

Implements spec **D1**.

**Files:**
- Modify: `plugin/lib/vaultlib/dates.py` (add `business_days`, extend `plan`)
- Modify: `plugin/lib/vaultlib/cli.py:80-86` (the `dates plan` subparser) and `cli.py:248-249` (the dispatch call)
- Test: `scripts/tests/test_vaultlib_dates.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `dates.business_days(start: date, end: date) -> int` — Mon–Fri days in the half-open interval `[start, end)`; `0` when `end <= start`. Task 4 calls this.
  - `dates.plan(root, today=None, *, timezone=None, utc_offset=None, catchup_threshold: int = 5) -> dict` — the existing 8 keys plus `business_days_missed`, `is_catchup`, `catchup_threshold`, `over_threshold`, `recap_detail_from`, `business_days_not_detailed`.

- [ ] **Step 1: Write the failing tests for `business_days`**

Append to `scripts/tests/test_vaultlib_dates.py` (the file already imports `date`-adjacent names near line 117; add `date` to that import line so it reads `from datetime import date, datetime, timedelta, timezone as _timezone`):

```python
def test_business_days_counts_a_half_open_interval():
    # Mon 2026-06-15 .. Fri 2026-06-19 exclusive of the end: Mon-Thu.
    assert dates.business_days(date(2026, 6, 15), date(2026, 6, 19)) == 4


def test_business_days_skips_the_weekend():
    # Fri 2026-06-12 -> Mon 2026-06-15 exclusive: Friday only.
    assert dates.business_days(date(2026, 6, 12), date(2026, 6, 15)) == 1


def test_business_days_of_an_empty_or_reversed_interval_is_zero():
    assert dates.business_days(date(2026, 6, 15), date(2026, 6, 15)) == 0
    assert dates.business_days(date(2026, 6, 19), date(2026, 6, 15)) == 0


def test_business_days_over_a_weekend_only_span_is_zero():
    # Sat 2026-06-13 -> Mon 2026-06-15 exclusive: Sat + Sun, no business days.
    assert dates.business_days(date(2026, 6, 13), date(2026, 6, 15)) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dates.py -k business_days -v`
Expected: 4 FAILs with `AttributeError: module 'vaultlib.dates' has no attribute 'business_days'`

- [ ] **Step 3: Implement `business_days`**

In `plugin/lib/vaultlib/dates.py`, immediately after the `_NEXT_BUSINESS_DAYS` constant (around line 120), add:

```python
def business_days(start: date, end: date) -> int:
    """Mon-Fri days in the half-open interval [start, end).

    Half-open on purpose: with start = the last daily note's date and
    end = today, the count is exactly the number of evening runs that did
    not happen. A note dated `start` on disk proves the run on the evening
    before it completed, so `start` itself is not a missed day.

    No holiday calendar: a public holiday counts as missed, which is
    literally true ("no run happened") and is the honest reading rather
    than a silent one.
    """
    if end <= start:
        return 0
    # Whole weeks contribute 5 each; walk only the remainder. A 6-month gap
    # must not become a 180-iteration loop on the client's machine.
    whole_weeks, remainder = divmod((end - start).days, 7)
    count = whole_weeks * 5
    for offset in range(remainder):
        if (start + timedelta(days=offset)).weekday() < 5:
            count += 1
    return count
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_dates.py -k business_days -v`
Expected: 4 PASS

- [ ] **Step 5: Write the failing tests for the catch-up block**

Append to `scripts/tests/test_vaultlib_dates.py`:

```python
def test_plan_on_a_healthy_run_reports_no_catchup(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    result = dates.plan(root, "2026-06-15")
    assert result["business_days_missed"] == 0
    assert result["is_catchup"] is False
    assert result["over_threshold"] is False
    assert result["recap_detail_from"] == "2026-06-15"
    assert result["business_days_not_detailed"] == 0


def test_plan_counts_one_missed_friday_run(tmp_path):
    # Thursday's run wrote Friday's note; Friday evening never ran; the
    # Monday run recaps Fri+Mon and reports the one missed run.
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    result = dates.plan(root, "2026-06-15")
    assert result["recap_from"] == "2026-06-12"
    assert result["recap_to"] == "2026-06-15"
    assert result["business_days_missed"] == 1
    assert result["is_catchup"] is True
    assert result["over_threshold"] is False


def test_plan_pins_the_e2e_two_month_gap(tmp_path):
    # The observed finding: last note 2026-06-15 (Mon), run on 2026-08-21
    # (Fri). 49 business days of missed runs; detail from the 5th-last
    # business day, 2026-08-17 (Mon); 45 earlier business days uncounted.
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    result = dates.plan(root, "2026-08-21")
    assert result["business_days_missed"] == 49
    assert result["is_catchup"] is True
    assert result["catchup_threshold"] == 5
    assert result["over_threshold"] is True
    assert result["recap_detail_from"] == "2026-08-17"
    assert result["business_days_not_detailed"] == 45


def test_plan_at_exactly_the_threshold_is_not_over_it(tmp_path):
    # Mon 2026-06-08 -> Mon 2026-06-15 exclusive = 5 business days.
    root = make_vault(tmp_path)
    note(root, "2026-06-08")
    result = dates.plan(root, "2026-06-15")
    assert result["business_days_missed"] == 5
    assert result["over_threshold"] is False
    assert result["recap_detail_from"] == "2026-06-08"
    assert result["business_days_not_detailed"] == 0


def test_plan_honours_a_custom_threshold(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-08")
    result = dates.plan(root, "2026-06-15", catchup_threshold=2)
    assert result["business_days_missed"] == 5
    assert result["catchup_threshold"] == 2
    assert result["over_threshold"] is True
    # Two business days ending at 2026-06-15 (Mon): Fri 12th and Mon 15th.
    assert result["recap_detail_from"] == "2026-06-12"
    assert result["business_days_not_detailed"] == 4


def test_plan_threshold_zero_details_only_the_final_business_day(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-08")
    result = dates.plan(root, "2026-06-15", catchup_threshold=0)
    assert result["over_threshold"] is True
    assert result["recap_detail_from"] == "2026-06-15"


def test_plan_detail_window_clamps_to_recap_from(tmp_path):
    # A one-day gap can never detail from before the window starts.
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    result = dates.plan(root, "2026-06-15", catchup_threshold=0)
    assert result["recap_detail_from"] == "2026-06-15"
    assert result["business_days_not_detailed"] == 1


def test_plan_detail_window_walks_back_from_a_weekend_today(tmp_path):
    # today = Sat 2026-06-20: the 5 business days ending there are
    # Mon 15th .. Fri 19th.
    root = make_vault(tmp_path)
    note(root, "2026-06-01")
    result = dates.plan(root, "2026-06-20")
    assert result["over_threshold"] is True
    assert result["recap_detail_from"] == "2026-06-15"


def test_plan_on_a_fresh_vault_is_not_a_catchup(tmp_path):
    result = dates.plan(make_vault(tmp_path), "2026-06-10")
    assert result["business_days_missed"] == 0
    assert result["is_catchup"] is False


def test_plan_rejects_a_negative_threshold(tmp_path):
    with pytest.raises(dates.DatesError, match="catchup-threshold"):
        dates.plan(make_vault(tmp_path), "2026-06-15", catchup_threshold=-1)


def test_cli_plan_reports_the_catchup_block(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-15")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "plan", "--vault", str(root),
         "--today", "2026-08-21", "--catchup-threshold", "5"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["business_days_missed"] == 49
    assert result["is_catchup"] is True
    assert result["recap_detail_from"] == "2026-08-17"
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dates.py -k "catchup or threshold or missed or detail or fresh_vault" -v`
Expected: FAILs — `KeyError: 'business_days_missed'` on the `dates.plan` tests, and `TypeError: plan() got an unexpected keyword argument 'catchup_threshold'` on the threshold ones.

- [ ] **Step 7: Extend `plan` with the catch-up block**

In `plugin/lib/vaultlib/dates.py`, add this helper directly below `business_days`:

```python
def _walk_back_business_days(end: date, count: int) -> date:
    """The date `count` business days back from `end`, counting `end` itself.

    A weekend `end` contributes nothing, so the walk simply continues into
    the previous week.
    """
    remaining = max(count, 1)
    cursor = end
    while True:
        if cursor.weekday() < 5:
            remaining -= 1
            if remaining == 0:
                return cursor
        cursor -= timedelta(days=1)
```

Change the `plan` signature (currently at line 162) to:

```python
def plan(root: Path, today: Optional[str] = None, *,
         timezone: Optional[str] = None,
         utc_offset: Optional[str] = None,
         catchup_threshold: int = 5) -> dict:
```

Extend the docstring's closing paragraph by appending:

```
    A gap is reported, not inferred (decision 15): business_days_missed is
    the count of business days in [recap_from, recap_to), which is exactly
    the set of evening runs that did not happen. Above catchup_threshold,
    recap_detail_from bounds how far back the caller should recap in detail
    (decision 17) — the caller does no arithmetic, only prose.
```

Immediately after the `if today is not None:` / `else:` block that resolves `today_date` (i.e. before `notes_dir = root / DAILY_NOTES_DIR`), insert the guard:

```python
    if not isinstance(catchup_threshold, int) or isinstance(catchup_threshold, bool):
        raise DatesError("catchup-threshold must be an integer")
    if catchup_threshold < 0:
        raise DatesError(
            f"catchup-threshold {catchup_threshold} must be >= 0")
```

Then replace the `return {...}` block at the end of `plan` with:

```python
    recap_from = last or today_date
    missed = business_days(recap_from, today_date)
    over_threshold = missed > catchup_threshold
    detail_from = (max(recap_from,
                       _walk_back_business_days(today_date, catchup_threshold))
                   if over_threshold else recap_from)
    return {
        "today": today_date.isoformat(),
        "today_day_name": DAY_NAMES[today_date.weekday()],
        "next_business_day": nxt.isoformat(),
        "next_day_name": DAY_NAMES[nxt.weekday()],
        "note_to_write": f"{DAILY_NOTES_DIR}/{nxt.isoformat()}.md",
        "last_daily_note": (f"{DAILY_NOTES_DIR}/{last.isoformat()}.md"
                            if last else None),
        "recap_from": recap_from.isoformat(),
        "recap_to": today_date.isoformat(),
        "business_days_missed": missed,
        "is_catchup": missed > 0,
        "catchup_threshold": catchup_threshold,
        "over_threshold": over_threshold,
        "recap_detail_from": detail_from.isoformat(),
        "business_days_not_detailed": business_days(recap_from, detail_from),
    }
```

- [ ] **Step 8: Wire the CLI flag**

In `plugin/lib/vaultlib/cli.py`, after the `dates_plan.add_argument("--utc-offset", ...)` block (around line 85), add:

```python
    dates_plan.add_argument(
        "--catchup-threshold", dest="catchup_threshold", type=int, default=5,
        help="business days missed before the recap is bounded (default 5)")
```

And in `_dispatch`, change the `dates.plan` call to pass it:

```python
        return _ok(dates.plan(root, args.today, timezone=args.timezone,
                              utc_offset=args.utc_offset,
                              catchup_threshold=args.catchup_threshold))
```

- [ ] **Step 9: Run the full dates suite**

Run: `python -m pytest scripts/tests/test_vaultlib_dates.py -q`
Expected: all PASS, including the pre-existing `test_plan_*` tests — the 8 original keys are unchanged.

- [ ] **Step 10: Commit**

```bash
git add plugin/lib/vaultlib/dates.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_dates.py
git commit -m "$(cat <<'MSG'
feat(dates): report the gap as data, not silence

business_days counts Mon-Fri in a half-open interval, which makes
[recap_from, recap_to) exactly the set of evening runs that did not
happen. plan() reports that count plus the detail bound, so the skill
does no arithmetic — it copies integers into prose. (#56)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: `dailynote` — the region marker attribute grammar

Implements spec **D3, part 1**. This task adds *only* the grammar. Nothing writes an attribute yet; Task 3 does.

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py:23-24` (`_MARKER_RE`), `:121-123` (`_region`), `:153-179` (`_find_regions`)
- Test: `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - Region dicts from `_find_regions` gain an `"attrs": dict` key, populated from the *begin* marker.
  - `_region(name: str, content: str, attrs: Optional[dict] = None) -> str` — renders `<!-- evening-sync:{name}:begin[ k=v] -->`, content, end marker. With `attrs` empty or None the output is byte-identical to today's.
  - `_marker_line(name: str, kind: str, attrs: Optional[dict] = None) -> str` — one marker line on its own, used by Task 3 to restamp a begin marker during a merge.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_dailynote.py`:

```python
def test_find_regions_reads_an_inputs_attribute():
    lines = [
        "<!-- evening-sync:recap:begin inputs=a1b2c3d4e5f6a7b8 -->",
        "recap prose",
        "<!-- evening-sync:recap:end -->",
    ]
    regions = dailynote._find_regions(lines)
    assert regions[0]["attrs"] == {"inputs": "a1b2c3d4e5f6a7b8"}


def test_find_regions_defaults_attrs_to_empty():
    lines = ["<!-- evening-sync:recap:begin -->", "x",
             "<!-- evening-sync:recap:end -->"]
    assert dailynote._find_regions(lines)[0]["attrs"] == {}


def test_find_regions_refuses_an_unknown_attribute():
    lines = ["<!-- evening-sync:recap:begin mode=terse -->", "x",
             "<!-- evening-sync:recap:end -->"]
    with pytest.raises(dailynote.DailyNoteError, match="mode"):
        dailynote._find_regions(lines)


def test_find_regions_refuses_an_attribute_on_an_end_marker():
    lines = ["<!-- evening-sync:recap:begin -->", "x",
             "<!-- evening-sync:recap:end inputs=a1b2c3d4e5f6a7b8 -->"]
    with pytest.raises(dailynote.DailyNoteError, match="inputs"):
        dailynote._find_regions(lines)


def test_find_regions_refuses_an_attribute_on_a_prep_region():
    lines = ["<!-- evening-sync:prep:begin inputs=a1b2c3d4e5f6a7b8 -->", "x",
             "<!-- evening-sync:prep:end -->"]
    with pytest.raises(dailynote.DailyNoteError, match="inputs"):
        dailynote._find_regions(lines)


def test_region_without_attrs_renders_exactly_as_before():
    assert dailynote._region("recap", "body") == (
        "<!-- evening-sync:recap:begin -->\nbody\n"
        "<!-- evening-sync:recap:end -->")


def test_region_with_attrs_renders_them_on_the_begin_marker():
    assert dailynote._region("recap", "body", {"inputs": "abc123"}) == (
        "<!-- evening-sync:recap:begin inputs=abc123 -->\nbody\n"
        "<!-- evening-sync:recap:end -->")


def test_marker_line_renders_one_line():
    assert dailynote._marker_line("recap", "begin", {"inputs": "abc123"}) == (
        "<!-- evening-sync:recap:begin inputs=abc123 -->")
    assert dailynote._marker_line("recap", "end") == (
        "<!-- evening-sync:recap:end -->")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -k "attr or marker_line or region_with or region_without" -v`
Expected: FAILs — `KeyError: 'attrs'`, `AttributeError: ... has no attribute '_marker_line'`, and the two "refuses" tests failing because no error is raised.

- [ ] **Step 3: Extend the grammar**

In `plugin/lib/vaultlib/dailynote.py`, replace the `_MARKER_RE` line (line 23) with:

```python
_MARKER_RE = re.compile(
    r"\A<!-- evening-sync:([a-z-]+):(begin|end)"
    r"((?: [a-z][a-z0-9-]*=[A-Za-z0-9._-]+)*) -->\s*\Z")
_ATTR_RE = re.compile(r"([a-z][a-z0-9-]*)=([A-Za-z0-9._-]+)")
# Region metadata the CLI owns. Only the recap's begin marker carries any:
# `inputs` is the fingerprint of what the recap was composed from. Anything
# else means a version this plugin does not understand, and guessing at a
# marker is how a note gets silently mis-merged.
_ALLOWED_ATTRS = {("recap", "begin"): frozenset({"inputs"})}
```

Replace `_region` (lines 121-123) with:

```python
def _marker_line(name: str, kind: str,
                 attrs: Optional[dict] = None) -> str:
    suffix = "".join(f" {key}={value}"
                     for key, value in sorted((attrs or {}).items()))
    return f"<!-- evening-sync:{name}:{kind}{suffix} -->"


def _region(name: str, content: str, attrs: Optional[dict] = None) -> str:
    return (f"{_marker_line(name, 'begin', attrs)}\n{content}\n"
            f"{_marker_line(name, 'end')}")
```

In `_find_regions`, replace the body of the loop and the `open_marker` handling so attributes are parsed and carried from begin to region:

```python
def _find_regions(lines: List[str]) -> List[dict]:
    regions: List[dict] = []
    open_marker: Optional[Tuple[str, int, dict]] = None
    for index, line in enumerate(lines):
        match = _MARKER_RE.match(line)
        if not match:
            continue
        name, kind = match.group(1), match.group(2)
        if name not in _KNOWN_REGIONS:
            raise DailyNoteError(
                f"unknown region {name!r} at line {index + 1}; "
                f"known regions: {_KNOWN_REGIONS}")
        attrs = dict(_ATTR_RE.findall(match.group(3)))
        stray = sorted(set(attrs) - _ALLOWED_ATTRS.get((name, kind), frozenset()))
        if stray:
            raise DailyNoteError(
                f"unknown region attribute(s) {stray} on {name}:{kind} at "
                f"line {index + 1} — this note may have been written by a "
                "newer plugin version; upgrade the plugin rather than "
                "editing the marker")
        if kind == "begin":
            if open_marker is not None:
                raise DailyNoteError(
                    f"nested region marker at line {index + 1}")
            open_marker = (name, index, attrs)
        else:
            if open_marker is None or open_marker[0] != name:
                raise DailyNoteError(
                    f"unmatched end marker for {name!r} at line {index + 1}")
            regions.append({"name": name, "begin": open_marker[1],
                            "end": index, "attrs": open_marker[2]})
            open_marker = None
    if open_marker is not None:
        raise DailyNoteError(f"region {open_marker[0]!r} is never closed")
    return regions
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -q`
Expected: all PASS. The pre-existing byte-comparison tests (`test_fresh_render_matches_the_contract_exactly`, `test_merge_replaces_regions_and_preserves_every_other_byte`) are the proof that the no-attrs rendering path did not change.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "$(cat <<'MSG'
feat(dailynote): region markers carry CLI-owned key=value metadata

The begin marker is already the CLI's line, so region metadata belongs
there rather than in frontmatter (which decision 10 forbids touching on a
merge) or a sidecar (which decision 11 forbids outright). Only
recap:begin may carry `inputs`; an unknown attribute is an error naming
it, never a silent ignore. Nothing writes one yet. (#57)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: the recap fingerprint — skip a regeneration whose inputs are unchanged

Implements spec **D3, part 2**. This is the H2 fix.

**Files:**
- Modify: `plugin/lib/vaultlib/meeting.py:145-148` (add `date_from_stem` beside `_date_prefix`)
- Modify: `plugin/lib/vaultlib/dailynote.py` (`_ALLOWED_KEYS`, `_validate`, `_render`, `_merge`, `write`, `read`)
- Test: `scripts/tests/test_vaultlib_meeting.py`, `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: `dailynote._marker_line`, `dailynote._region(name, content, attrs)` and the `region["attrs"]` key from Task 2.
- Produces:
  - `meeting.date_from_stem(stem: str) -> Optional[date]`
  - `dailynote.recap_fingerprint(root: Path, window: dict) -> str` — 16 lowercase hex chars. `window` is the validated dict `{"from": date, "to": date, "detailed_from": Optional[date]}`.
  - `_validate(root, payload) -> dict` gains a `"recap_window"` key holding that dict or `None`. **Note for Task 5:** `_validate`'s return type changes again there, to a `(data, warnings)` tuple.
  - `write()`'s result gains `recap_skipped: bool` and `recap_inputs: Optional[str]`.
  - `read()`'s result gains `recap_inputs: Optional[str]`.

- [ ] **Step 1: Write the failing test for `date_from_stem`**

Append to `scripts/tests/test_vaultlib_meeting.py`:

```python
def test_date_from_stem_is_the_inverse_of_the_date_prefix():
    from datetime import date
    # meeting._date_prefix renders 2026-06-01 as 01-06-26; this reads it back.
    assert meeting.date_from_stem(
        "01-06-26-commercial-ops-status-update") == date(2026, 6, 1)
    # A conflict variant keeps its prefix.
    assert meeting.date_from_stem("12-06-26-jordan-1on1-v2") == date(2026, 6, 12)


def test_date_from_stem_returns_none_for_a_non_conforming_stem():
    # An ISO-prefixed stem is a decision note, not a meeting note.
    assert meeting.date_from_stem("2026-06-12-phase-1-deferred") is None
    assert meeting.date_from_stem("notes-from-the-call") is None
    assert meeting.date_from_stem("") is None
    # A real-looking but impossible date.
    assert meeting.date_from_stem("32-06-26-nope") is None


def test_date_prefix_round_trips_through_date_from_stem():
    stem = f"{meeting._date_prefix('2026-05-20T11:00')}-vendor-strategy"
    assert meeting.date_from_stem(stem).isoformat() == "2026-05-20"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest scripts/tests/test_vaultlib_meeting.py -k date_from_stem -v`
Expected: FAIL — `AttributeError: module 'vaultlib.meeting' has no attribute 'date_from_stem'`

- [ ] **Step 3: Implement `date_from_stem`**

In `plugin/lib/vaultlib/meeting.py`, first widen the datetime import at line 12 so `date` is available for the annotation:

```python
from datetime import date, datetime
```

Then, directly below `_date_prefix` (line 148), add:

```python
def date_from_stem(stem: str) -> Optional[date]:
    """The meeting date encoded in a stem, or None if it carries none.

    The inverse of _date_prefix, and it lives here so the pair moves
    together: meeting stems are DD-MM-YY-title, never ISO, and a caller
    that assumes otherwise (the recap fingerprint's window filter, for one)
    silently matches nothing. An ISO-prefixed stem is a decision note, and
    a hand-named note is simply not in any window.
    """
    try:
        return datetime.strptime(str(stem)[:8], "%d-%m-%y").date()
    except ValueError:
        return None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest scripts/tests/test_vaultlib_meeting.py -q`
Expected: all PASS

- [ ] **Step 5: Write the failing tests for the fingerprint**

Append to `scripts/tests/test_vaultlib_dailynote.py`. These need a vault with a meeting and a daily note inside the recap window, so add this helper next to the existing `make_vault`:

```python
def make_windowed_vault(tmp_path: Path) -> Path:
    """A vault whose recap window 2026-06-12..2026-06-12 has real inputs."""
    root = make_vault(tmp_path)
    (root / "20-meetings").mkdir()
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n\n"
        "## Key Takeaways\n- Shortlist approved.\n", encoding="utf-8")
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        "---\ndate: 2026-06-12\ntype: daily-note\n---\n\n"
        "## End of day\n- Ran long.\n", encoding="utf-8")
    return root


def windowed_payload(**overrides) -> dict:
    base = payload(date="2026-06-15",
                   recap_window={"from": "2026-06-12", "to": "2026-06-12"})
    base.update(overrides)
    return base


def test_fresh_render_stamps_the_recap_inputs(tmp_path):
    root = make_windowed_vault(tmp_path)
    result = dailynote.write(root, windowed_payload())
    assert re.fullmatch(r"[0-9a-f]{16}", result["recap_inputs"])
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert f"<!-- evening-sync:recap:begin inputs={result['recap_inputs']} -->" in text


def test_second_write_over_unchanged_inputs_leaves_the_file_byte_identical(tmp_path):
    """The H2 repro: a re-run must not regenerate the recap with LLM variance."""
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    before = path.read_bytes()
    result = dailynote.write(root, windowed_payload(
        recap="> [!info] At a glance\n> synced from Teams transcript"))
    assert result["recap_skipped"] is True
    assert result["changed"] is False
    assert path.read_bytes() == before


def test_a_changed_meeting_inside_the_window_regenerates_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n\n"
        "## Key Takeaways\n- Shortlist approved.\n- TCO comparison owed.\n",
        encoding="utf-8")
    result = dailynote.write(root, windowed_payload(
        recap="> [!info] At a glance\n> 1 meeting · TCO comparison now owed"))
    assert result["recap_skipped"] is False
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "TCO comparison now owed" in text


def test_a_meeting_outside_the_window_does_not_invalidate_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    (root / "20-meetings" / "01-06-26-older-call.md").write_text(
        "---\ndate: 2026-06-01T09:00\ntype: status-update\n---\n",
        encoding="utf-8")
    assert dailynote.write(root, windowed_payload())["recap_skipped"] is True


def test_a_new_jotting_in_the_window_regenerates_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    note_path = root / "60-daily-notes" / "2026-06-12.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8") + "- Call Dana about scope.\n",
        encoding="utf-8")
    assert dailynote.write(root, windowed_payload())["recap_skipped"] is False


def test_a_decision_written_in_the_window_regenerates_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    decisions = root / "30-projects" / "yard-automation" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\n---\n", encoding="utf-8")
    assert dailynote.write(root, windowed_payload())["recap_skipped"] is False


def test_prep_regions_still_merge_when_the_recap_is_skipped(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    updated = windowed_payload()
    updated["meetings"][0]["prep"] = "**Attendees:** Sam · **Context:** rescheduled."
    result = dailynote.write(root, updated)
    assert result["recap_skipped"] is True
    assert result["changed"] is True
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "**Context:** rescheduled." in text
    assert "Recap bullet one." in text          # the recap survived untouched


def test_a_write_without_a_window_strips_a_stale_stamp(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    result = dailynote.write(root, payload(date="2026-06-15"))
    assert result["recap_inputs"] is None
    assert result["recap_skipped"] is False
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "<!-- evening-sync:recap:begin -->" in text
    assert "inputs=" not in text


def test_read_returns_the_recap_inputs(tmp_path):
    root = make_windowed_vault(tmp_path)
    written = dailynote.write(root, windowed_payload())
    assert dailynote.read(root, "2026-06-15")["recap_inputs"] == written["recap_inputs"]


def test_read_returns_a_null_recap_inputs_for_an_unstamped_note(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    assert dailynote.read(root, "2026-06-15")["recap_inputs"] is None


def test_window_must_end_before_the_note_it_recaps(tmp_path):
    root = make_windowed_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="before the note"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-15"}))


def test_window_rejects_a_reversed_range_and_unknown_keys(tmp_path):
    root = make_windowed_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="after"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-10"}))
    with pytest.raises(dailynote.DailyNoteError, match="unknown key"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-12",
                          "until": "2026-06-12"}))
    with pytest.raises(dailynote.DailyNoteError, match="required"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12"}))
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -k "inputs or skipped or window or regenerates or invalidate or jotting or decision_written" -v`
Expected: FAILs — `unknown payload key(s) ['recap_window']` from `_validate`, and `KeyError: 'recap_inputs'`.

- [ ] **Step 7: Implement the window validation**

In `plugin/lib/vaultlib/dailynote.py`, add `hashlib` to the imports and `meeting` to the package import:

```python
import hashlib
import re
from datetime import date, datetime
...
from . import dates, markdown, meeting, naming, vault
```

Extend the allow-lists (line 28):

```python
_ALLOWED_KEYS = ("date", "recap", "meetings", "meetings_note", "recap_window")
_ALLOWED_WINDOW_KEYS = ("from", "to", "detailed_from")
_DIGEST_LENGTH = 16
```

`_require_date` (line 36) already does exactly the parse-and-explain the window fields need, with `date` hardcoded into its two messages. Give it a label instead of writing a second copy — the existing two call sites keep working unchanged:

```python
def _require_date(raw, label: str = "date") -> str:
    text = str(raw or "").strip()
    if not vault.ISO_DATE_RE.match(text):
        raise DailyNoteError(f"{label} {raw!r} must be ISO YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise DailyNoteError(f"{label} {raw!r} is not a real date") from exc
    return text
```

Then add these below it:

```python
def _require_date_obj(raw, label: str) -> date:
    return datetime.strptime(_require_date(raw, label), "%Y-%m-%d").date()


def _validate_window(payload: dict, note_date: str) -> Optional[dict]:
    """The recap window: what the recap covers, and what it was built from.

    Optional so existing callers keep working — but a caller that omits it
    forgoes both the catch-up banner and the idempotence guard, which is
    why a skill-contract test pins it into the SKILL.md payload example.
    """
    raw = payload.get("recap_window")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DailyNoteError("recap_window must be a JSON object")
    unknown = sorted(set(raw) - set(_ALLOWED_WINDOW_KEYS))
    if unknown:
        raise DailyNoteError(f"recap_window: unknown key(s) {unknown}")
    for key in ("from", "to"):
        if key not in raw:
            raise DailyNoteError(
                f"recap_window: {key} is required — pass recap_from and "
                "recap_to from `dates plan` verbatim")
    start = _require_date_obj(raw["from"], "recap_window.from")
    end = _require_date_obj(raw["to"], "recap_window.to")
    if start > end:
        raise DailyNoteError(
            f"recap_window: from {start.isoformat()} is after to "
            f"{end.isoformat()}")
    if end >= datetime.strptime(note_date, "%Y-%m-%d").date():
        raise DailyNoteError(
            f"recap_window.to ({end.isoformat()}) must be before the note's "
            f"own date ({note_date}) — the window is what the note recaps, "
            "not the note itself")
    detailed = raw.get("detailed_from")
    if detailed is not None:
        detailed = _require_date_obj(detailed, "recap_window.detailed_from")
        if not start <= detailed <= end:
            raise DailyNoteError(
                f"recap_window.detailed_from ({detailed.isoformat()}) must "
                f"fall within {start.isoformat()}..{end.isoformat()}")
    return {"from": start, "to": end, "detailed_from": detailed}
```

In `_validate`, after `date_iso = _require_date(payload.get("date"))`, add:

```python
    window = _validate_window(payload, date_iso)
```

and add `"recap_window": window` to the returned dict.

- [ ] **Step 8: Implement the fingerprint**

Add below `_validate` in `dailynote.py`:

```python
def _iso_prefix_date(stem: str) -> Optional[date]:
    head = str(stem)[:10]
    if not vault.ISO_DATE_RE.match(head):
        return None
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fingerprint_inputs(root: Path, start: date, end: date) -> List[Tuple[str, Path]]:
    """Every file whose content the recap for [start, end] was built from.

    Meetings and jottings are the recap's stated inputs; decisions are here
    so a stage-4 retry that finally wrote one is not read as "unchanged".
    """
    found: List[Tuple[str, Path]] = []
    meetings = root / vault.MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        noted = meeting.date_from_stem(path.stem)
        if noted is not None and start <= noted <= end:
            found.append((f"{vault.MEETINGS_DIR}/{path.name}", path))
    notes = root / DAILY_NOTES_DIR
    for path in sorted(notes.glob("*.md")) if notes.is_dir() else []:
        noted = _iso_prefix_date(path.stem)
        if noted is not None and path.stem == noted.isoformat() and start <= noted <= end:
            found.append((f"{DAILY_NOTES_DIR}/{path.name}", path))
    projects = root / vault.PROJECTS_DIR
    for folder in sorted(projects.glob("*/decisions")) if projects.is_dir() else []:
        for path in sorted(folder.glob("*.md")):
            noted = _iso_prefix_date(path.stem)
            if noted is not None and start <= noted <= end:
                found.append((
                    f"{vault.PROJECTS_DIR}/{folder.parent.name}/decisions/"
                    f"{path.name}", path))
    return found


def recap_fingerprint(root: Path, window: dict) -> str:
    """A content hash of the recap's inputs — 16 hex, as `syncjob.content_id`.

    Computed here, never accepted from a caller: a caller-supplied hash is
    a caller-supplied fact, and the whole point is that this one is not.
    The window bounds are part of the digest, so widening the window
    invalidates even when no file changed.
    """
    start, end = window["from"], window["to"]
    lines = [f"window\t{start.isoformat()}\t{end.isoformat()}"]
    for relpath, path in sorted(_fingerprint_inputs(root, start, end)):
        lines.append(f"{relpath}\t{hashlib.sha256(path.read_bytes()).hexdigest()}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest[:_DIGEST_LENGTH]
```

- [ ] **Step 9: Thread the fingerprint through render, merge, write and read**

Change `_render` (line 133) to take the fingerprint and stamp it:

```python
def _render(data: dict, fingerprint: Optional[str]) -> str:
    date_iso = data["date"]
    attrs = {"inputs": fingerprint} if fingerprint else None
    parts = ["---", f"date: {date_iso}", "type: daily-note", "---", "",
             f"# {date_iso} · {_day_name(date_iso)}", "",
             "## Recap", _region("recap", data["recap"], attrs), "",
             "## Meetings", ""]
```

(the rest of `_render` is unchanged)

Replace the tail of `_merge` — from the `prep_contents` assignment to the `return` — with:

```python
    prep_contents = ([m["prep"] for m in data["meetings"]]
                     if data["meetings"]
                     else [data["meetings_note"] or NO_MEETINGS_LINE])
    # Each entry: begin index -> (region, content, marker line or None).
    # None means "re-emit the line that is already there"; only the recap's
    # begin marker is ever rewritten, and only to restamp `inputs`.
    replacements: Dict[int, Tuple[dict, str, Optional[str]]] = {}
    recap = recaps[0]
    recap_skipped = (fingerprint is not None
                     and recap["attrs"].get("inputs") == fingerprint)
    if not recap_skipped:
        attrs = {"inputs": fingerprint} if fingerprint else None
        replacements[recap["begin"]] = (
            recap, data["recap"], _marker_line("recap", "begin", attrs))
    for region, content in zip(preps, prep_contents):
        replacements[region["begin"]] = (region, content, None)
    out: List[str] = []
    index = 0
    while index < len(lines):
        if index in replacements:
            region, content, marker = replacements[index]
            out.append(marker if marker is not None else lines[region["begin"]])
            out.extend(content.split("\n"))
            out.append(lines[region["end"]])
            index = region["end"] + 1
        else:
            out.append(lines[index])
            index += 1
    return "\n".join(out), len(replacements), recap_skipped
```

and change its signature to:

```python
def _merge(text: str, data: dict,
           fingerprint: Optional[str]) -> Tuple[str, int, bool]:
```

Replace `write` (line 278) with:

```python
def write(root: Path, payload) -> dict:
    data = _validate(root, payload)
    window = data["recap_window"]
    fingerprint = recap_fingerprint(root, window) if window else None
    path = root / DAILY_NOTES_DIR / f"{data['date']}.md"
    if path.is_file():
        original = path.read_text(encoding="utf-8")
        merged, replaced, recap_skipped = _merge(original, data, fingerprint)
        changed = merged != original
        if changed:
            vault.atomic_write(path, merged)
        created = False
    else:
        merged = _render(data, fingerprint)
        replaced = 1 + (len(data["meetings"]) or 1)
        changed, created, recap_skipped = True, True, False
        vault.atomic_write(path, merged)
    return {
        "path": f"{DAILY_NOTES_DIR}/{data['date']}.md",
        "date": data["date"],
        "day_name": _day_name(data["date"]),
        "created": created,
        "regions_replaced": replaced,
        "changed": changed,
        "recap_skipped": recap_skipped,
        "recap_inputs": fingerprint,
    }
```

In `read`, after the `recap` extraction block, capture the stamp:

```python
    recap = None
    recap_inputs = None
    recap_regions = [r for r in regions if r["name"] == "recap"]
    if recap_regions:
        region = recap_regions[0]
        recap = "\n".join(lines[region["begin"] + 1:region["end"]])
        recap_inputs = region["attrs"].get("inputs")
```

and add `"recap_inputs": recap_inputs,` to `read`'s returned dict, next to `"recap": recap,`.

- [ ] **Step 10: Fix the one existing caller of `_render`**

`test_fresh_fixture_is_exactly_what_daily_note_write_renders` calls `dailynote.write` (not `_render`) and passes no `recap_window`, so it needs no change — the fixture stays unstamped, which is the "exists, no attribute" state D3 documents. Confirm by running it explicitly:

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -k fixture -v`
Expected: PASS

- [ ] **Step 11: Run the whole dailynote suite**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_vaultlib_meeting.py -q`
Expected: all PASS

- [ ] **Step 12: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py plugin/lib/vaultlib/meeting.py scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_vaultlib_meeting.py
git commit -m "$(cat <<'MSG'
fix(dailynote): an unchanged input set leaves the recap alone

A re-run used to regenerate the recap region with LLM variance, which in
the E2E round replaced a real takeaway with a description of plumbing.
daily-note write now hashes the recap's actual inputs — meetings,
jottings and decisions inside the window — stamps the digest on the recap
marker, and skips the region entirely when it matches.

meeting.date_from_stem lands beside _date_prefix because meeting stems
are DD-MM-YY, not ISO: the window filter needs the inverse, and a
round-trip pair that drifts apart is a failure this repo has already
documented twice. (#57)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 4: the catch-up banner

Implements spec **D2**.

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py` (`_recap_body`, wired into `_render` and `_merge`)
- Test: `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: `dates.business_days` (Task 1); the validated `data["recap_window"]` dict (Task 3).
- Produces: `_recap_body(data: dict) -> str` — the recap region's full interior: the banner, a blank line, then `data["recap"]`; or just `data["recap"]` when no days were missed. Both `_render` and `_merge` must call it instead of using `data["recap"]` directly.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_dailynote.py`:

```python
def test_no_banner_when_no_business_days_were_missed(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        recap_window={"from": "2026-06-12", "to": "2026-06-12"}))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "Catch-up note" not in text
    # The recap interior is exactly the payload's prose.
    assert ("<!-- evening-sync:recap:begin inputs=" in text
            and "-->\n> [!info] At a glance" in text)


def test_banner_states_the_window_and_the_no_back_fill_rule(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window={"from": "2026-06-15", "to": "2026-08-21"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert "> [!warning] Catch-up note" in text
    assert "Covers 2026-06-15 → 2026-08-21" in text
    assert "49 business days without an evening run" in text
    assert "not back-filled" in text
    assert "Detailed from" not in text


def test_banner_adds_the_detail_line_only_when_capped(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window={"from": "2026-06-15", "to": "2026-08-21",
                      "detailed_from": "2026-08-17"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert ("Detailed from 2026-08-17; the 45 earlier business days are "
            "counted, not recapped in detail.") in text


def test_banner_omits_the_detail_line_when_it_covers_the_whole_window(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window={"from": "2026-06-15", "to": "2026-08-21",
                      "detailed_from": "2026-06-15"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert "Detailed from" not in text


def test_banner_is_singular_for_one_missed_day(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        recap_window={"from": "2026-06-12", "to": "2026-06-13",
                      "detailed_from": "2026-06-13"}))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "1 business day without an evening run" in text
    assert "the 1 earlier business day is counted" in text


def test_banner_sits_above_the_payload_prose_inside_the_region(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap="> [!info] At a glance\n> quiet stretch",
        recap_window={"from": "2026-06-15", "to": "2026-08-21"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    region = text.split("<!-- evening-sync:recap:begin", 1)[1]
    region = region.split("-->", 1)[1].split("<!-- evening-sync:recap:end", 1)[0]
    assert region.strip().startswith("> [!warning] Catch-up note")
    assert region.strip().endswith("> quiet stretch")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -k banner -v`
Expected: FAILs — the "Catch-up note" assertions fail because nothing renders a banner.

- [ ] **Step 3: Implement `_recap_body`**

In `plugin/lib/vaultlib/dailynote.py`, add below `recap_fingerprint`:

```python
def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _catchup_banner(window: Optional[dict]) -> Optional[str]:
    """The exec-facing statement of decisions 15-17, or None on a normal run.

    Rendered here rather than composed by the caller: the count is
    arithmetic and the no-back-fill rule is a promise the CLI keeps, so
    neither is left to a model to remember.
    """
    if window is None:
        return None
    missed = dates.business_days(window["from"], window["to"])
    if missed <= 0:
        return None
    lines = [
        "> [!warning] Catch-up note",
        f"> Covers {window['from'].isoformat()} → {window['to'].isoformat()} "
        f"— {_plural(missed, 'business day')} without an evening run. "
        "Skipped days are not back-filled: this is the only note for that "
        "window.",
    ]
    detailed = window.get("detailed_from")
    if detailed is not None and detailed > window["from"]:
        earlier = dates.business_days(window["from"], detailed)
        verb = "is" if earlier == 1 else "are"
        lines.append(
            f"> Detailed from {detailed.isoformat()}; the "
            f"{_plural(earlier, 'earlier business day')} {verb} counted, "
            "not recapped in detail.")
    return "\n".join(lines)


def _recap_body(data: dict) -> str:
    banner = _catchup_banner(data["recap_window"])
    return f"{banner}\n\n{data['recap']}" if banner else data["recap"]
```

- [ ] **Step 4: Wire it into both write paths**

In `_render`, change the recap region line to use it:

```python
             "## Recap", _region("recap", _recap_body(data), attrs), "",
```

In `_merge`, change the recap replacement to use it:

```python
        replacements[recap["begin"]] = (
            recap, _recap_body(data), _marker_line("recap", "begin", attrs))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -q`
Expected: all PASS, including the pre-existing byte-exact tests — a payload with no `recap_window` produces no banner, so their bytes are unchanged.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "$(cat <<'MSG'
feat(dailynote): render the catch-up window into the note itself

A 67-day recap window used to render indistinguishably from a normal
daily run. When the window spans missed business days, the CLI now
prepends a warning callout naming the window, the count, and the fact
that skipped days are never back-filled — the design decision that was
real but unstated. A capped run says where its detail starts.

Rendered by the CLI, not composed by the caller: the count is arithmetic
and the no-back-fill rule is a promise, so neither is left to a model to
remember. (#56)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 5: names by lookup — resolve or refuse

Implements spec **D4**. This is the "Meridian Industrial Holdings" fix.

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py` (`_resolve_link`, `_check_links`, `_validate` returns warnings, `write` surfaces them)
- Test: `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter` (already imported).
- Produces:
  - `_resolve_link(root: Path, target: str) -> Tuple[Optional[str], Optional[Path], Optional[str]]` — `(kind, path, display_name_key)`. `display_name_key` is non-None only for identity kinds.
  - `_validate(root, payload) -> Tuple[dict, List[str]]` — **the return type changes**; `write` must unpack it.
  - `write()`'s result gains `warnings: List[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_dailynote.py`. The `make_vault` helper already creates `40-entities/acme-industries/dossier.md` with `entity-name: "Acme"`; these tests add the other object kinds they need.

```python
def make_linkable_vault(tmp_path: Path) -> Path:
    root = make_vault(tmp_path)
    (root / "50-people").mkdir()
    (root / "50-people" / "taylor-brooks.md").write_text(
        "---\nperson-name: Taylor Brooks\nslug: taylor-brooks\n"
        "relationship: external\n---\n", encoding="utf-8")
    project = root / "30-projects" / "yard-automation"
    project.mkdir(parents=True)
    (project / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\n"
        "slug: yard-automation\n---\n", encoding="utf-8")
    (project / "decisions").mkdir()
    (project / "decisions" / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\n---\n", encoding="utf-8")
    (root / "20-meetings").mkdir()
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n",
        encoding="utf-8")
    return root


def test_a_recap_link_to_no_vault_object_is_refused(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError,
                       match="resolves to no vault object"):
        dailynote.write(root, payload(
            recap="- [[meridian-industrial-holdings]] wants a comparison."))


def test_links_to_every_object_kind_resolve(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(recap=(
        "- [[acme-industries]] · [[taylor-brooks]] · [[yard-automation]]\n"
        "- [[12-06-26-weekly-status]] · [[2026-06-12-phase-1-deferred]]")))
    assert result["created"] is True
    assert result["warnings"] == []


def test_an_entity_alias_that_contradicts_the_vault_is_refused(tmp_path):
    """The H2 name defect: a display name the model invented."""
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="called 'Acme'"):
        dailynote.write(root, payload(
            recap="- [[acme-industries|Acme Industrial Holdings]] escalated."))


def test_a_person_alias_that_contradicts_the_vault_is_refused(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="Taylor Brooks"):
        dailynote.write(root, payload(
            recap="- [[taylor-brooks|Tyler Brooks]] owns the draft."))


def test_a_project_alias_that_contradicts_the_vault_is_refused(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError,
                       match="Yard Automation Program"):
        dailynote.write(root, payload(
            recap="- [[yard-automation|Yard Automation Programme]] slipped."))


def test_an_identity_alias_that_matches_the_vault_is_accepted(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(
        recap="- [[taylor-brooks|Taylor Brooks]] owns the board pack draft."))
    assert result["created"] is True


def test_an_event_object_alias_is_free_prose(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(recap=(
        "- [[12-06-26-weekly-status|Friday's status call]] — shortlist "
        "approved.\n- [[2026-06-12-phase-1-deferred|the deferral]] is queued.")))
    assert result["created"] is True


def test_a_heading_anchor_is_stripped_before_resolution(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(
        recap="- [[acme-industries#Sensitivities|Acme]] needs care."))
    assert result["created"] is True
    with pytest.raises(dailynote.DailyNoteError,
                       match="resolves to no vault object"):
        dailynote.write(root, payload(
            date="2026-06-16", recap="- [[nope#Context]] is nothing."))


def test_an_embed_is_checked_like_a_link(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError,
                       match="resolves to no vault object"):
        dailynote.write(root, payload(recap="- ![[not-a-thing]]"))


def test_links_in_prep_and_in_meetings_note_are_checked_too(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="meeting 1 prep"):
        bad = payload()
        bad["meetings"][0]["prep"] = "**Context:** [[ghost-entity]] escalated."
        dailynote.write(root, bad)
    with pytest.raises(dailynote.DailyNoteError, match="meetings_note"):
        dailynote.write(root, payload(
            meetings=[], meetings_note="*Calendar down; see [[ghost-entity]].*"))


def test_an_unreadable_dossier_warns_instead_of_blocking_the_note(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "40-entities" / "acme-industries" / "dossier.md").write_text(
        "no frontmatter here\n", encoding="utf-8")
    result = dailynote.write(root, payload(
        recap="- [[acme-industries|Acme]] escalated."))
    assert result["created"] is True
    assert len(result["warnings"]) == 1
    assert "display name not verified" in result["warnings"][0]


def test_a_missing_display_name_warns_instead_of_blocking(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "50-people" / "taylor-brooks.md").write_text(
        "---\nslug: taylor-brooks\nrelationship: external\n---\n",
        encoding="utf-8")
    result = dailynote.write(root, payload(
        recap="- [[taylor-brooks|Taylor Brooks]] owns the draft."))
    assert result["created"] is True
    assert "person-name" in result["warnings"][0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -k "resolve or alias or anchor or embed or dossier or display_name or prep_and" -v`
Expected: FAILs — the writes succeed where an error is expected, and `KeyError: 'warnings'` on the rest.

- [ ] **Step 3: Implement the resolver and the check**

In `plugin/lib/vaultlib/dailynote.py`, add near the other module constants:

```python
# `#heading` is stripped before resolution; `|alias` is the display-name
# claim. `!?` catches embeds, which make the same claim as a plain link.
_WIKILINK_RE = re.compile(
    r"!?\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")
```

Add these functions above `_validate`:

```python
def _resolve_link(root: Path, target: str):
    """(kind, path, display-name key) for a wikilink target, or three Nones.

    Identity objects come first: they are the ones whose *name* an alias
    claims, and a slug that is both a person note and a project folder is a
    collision the vault should not have. Event objects resolve but make no
    name claim — "Friday's Acme sync" is a reference, not a name.
    """
    candidates = (
        ("entity", root / vault.ENTITIES_DIR / target / "dossier.md",
         "entity-name"),
        ("person", root / vault.PEOPLE_DIR / f"{target}.md", "person-name"),
        ("project", root / vault.PROJECTS_DIR / target / "index.md",
         "project-name"),
        ("meeting", root / vault.MEETINGS_DIR / f"{target}.md", None),
        ("daily note", root / DAILY_NOTES_DIR / f"{target}.md", None),
    )
    for kind, path, name_key in candidates:
        if path.is_file():
            return kind, path, name_key
    projects = root / vault.PROJECTS_DIR
    for folder in sorted(projects.glob("*/decisions")) if projects.is_dir() else []:
        path = folder / f"{target}.md"
        if path.is_file():
            return "decision", path, None
    return None, None, None


def _check_links(root: Path, text: str, label: str,
                 warnings: List[str]) -> None:
    """Every wikilink resolves; every identity alias matches the vault.

    Decision 19. A plain-prose name cannot be checked by anything, which is
    why the skill mandates the wikilink form — this is the half that a
    machine can hold.
    """
    for match in _WIKILINK_RE.finditer(text):
        target = match.group(1).strip()
        alias = match.group(2)
        kind, path, name_key = _resolve_link(root, target)
        if kind is None:
            raise DailyNoteError(
                f"{label}: [[{target}]] resolves to no vault object — link "
                "only to objects that exist (create one with /update-entity "
                "or /new-project first), or leave the name out. Never write "
                "a name you have not looked up.")
        if alias is None or name_key is None:
            continue
        try:
            frontmatter, _ = markdown.split_frontmatter(
                path.read_text(encoding="utf-8"))
        except ValueError as exc:
            warnings.append(
                f"{label}: [[{target}]] resolves but its frontmatter could "
                f"not be read ({exc}) — display name not verified")
            continue
        actual = str(frontmatter.get(name_key) or "").strip()
        if not actual:
            warnings.append(
                f"{label}: [[{target}]] carries no {name_key} — display name "
                "not verified")
            continue
        if alias.strip() != actual:
            raise DailyNoteError(
                f"{label}: [[{target}|{alias}]] — that {kind} is called "
                f"{actual!r}. Display names come from the vault, never from "
                "the model.")
```

- [ ] **Step 4: Call it from `_validate` and surface the warnings**

Change `_validate`'s signature and return, and call `_check_links` on each piece of content. In `_validate`:

```python
def _validate(root: Path, payload) -> Tuple[dict, List[str]]:
```

Add `warnings: List[str] = []` right after the `isinstance(payload, dict)` guard. Then:

- after `recap = _clean_region_text(payload.get("recap"), "recap")`, add
  `_check_links(root, recap, "recap", warnings)`
- after the per-meeting `prep = _clean_region_text(...)` line, add
  `_check_links(root, prep, f"meeting {position} prep", warnings)`
- after `meetings_note = _clean_region_text(meetings_note, "meetings_note")`, add
  `_check_links(root, meetings_note, "meetings_note", warnings)`

and change the final return to:

```python
    return ({"date": date_iso, "recap": recap, "meetings": meetings,
             "meetings_note": meetings_note, "recap_window": window},
            warnings)
```

In `write`, unpack it and pass the warnings out:

```python
def write(root: Path, payload) -> dict:
    data, warnings = _validate(root, payload)
```

and add to the returned dict:

```python
        "warnings": warnings,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py -q`
Expected: all PASS, including `test_fresh_fixture_is_exactly_what_daily_note_write_renders` — every wikilink in `FRESH_FIXTURE_PAYLOAD` resolves against the copied fixture vault and none carries an alias (verified before this plan was written).

- [ ] **Step 6: Run the full suite — this is the task most likely to break a neighbour**

Run: `python -m pytest scripts/tests -q`
Expected: all PASS. If a test in `test_vaultlib_roundtrip.py` or `test_fixtures_ontology.py` fails on an unresolvable link, that is a real finding: the payload names something the vault does not have. Fix the payload (or add the object), never the check.

- [ ] **Step 7: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "$(cat <<'MSG'
fix(dailynote): a name in a machine region is looked up or refused

The E2E round put "Meridian Industrial Holdings" into an exec's daily
note; the entity is called Meridian Freight Holdings. Every wikilink in
payload content must now resolve to a vault object, and an alias on an
entity, person or project must equal that object's name in frontmatter —
the error names the real one, so the caller fixes it in one retry.

Aliases on meetings, decisions and daily notes stay free prose: those are
references, not name claims. An unreadable dossier warns rather than
costing the exec their note. (#57)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 6: the skill and the boundary docs

Implements spec **D5** and the Documentation section. No production code changes — this task makes the skill consume what Tasks 1–5 built, and pins it.

**Files:**
- Modify: `plugin/skills/evening-sync/SKILL.md` (stages 1, 6, 7; Unattended mode; Rules)
- Modify: `plugin/CLAUDE.md` (the *Daily-note regions* section, plus one new subsection)
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: every CLI contract from Tasks 1–5. The exact key names matter — `business_days_missed`, `is_catchup`, `over_threshold`, `recap_detail_from`, `business_days_not_detailed`, `recap_window` with `from`/`to`/`detailed_from`, `recap_skipped`.
- Produces: nothing code-level.

- [ ] **Step 1: Write the failing contract tests**

Append to `scripts/tests/test_skill_contracts.py`:

```python
def _evening_sync() -> str:
    return (SKILLS_DIR / "evening-sync" / "SKILL.md").read_text(encoding="utf-8")


def test_evening_sync_states_the_no_back_fill_rule():
    # Decision 16: one catch-up note covers the window; the exec is told so.
    text = _evening_sync().lower()
    assert "back-fill" in text, (
        "the no-back-fill decision was real but unstated, which is the "
        "finding — the skill has to say it"
    )


def test_evening_sync_consumes_the_catchup_facts_rather_than_deriving_them():
    text = _evening_sync()
    for key in ("business_days_missed", "over_threshold",
                "recap_detail_from", "business_days_not_detailed"):
        assert key in text, f"stage 1 must consume {key} from dates plan"


def test_evening_sync_payload_example_carries_the_recap_window():
    # recap_window is optional in the CLI for backward compatibility, so
    # this test is the only thing keeping the idempotence guard wired up.
    text = _evening_sync()
    assert '"recap_window"' in text, (
        "without recap_window in the payload there is no fingerprint and no "
        "catch-up banner — the guard is silently off"
    )


def test_evening_sync_mandates_wikilinks_for_looked_up_names():
    text = _evening_sync().lower()
    assert "wikilink" in text and "never" in text, (
        "decision 19: a plain-prose name cannot be validated by anything, so "
        "the skill has to require the linked form"
    )


def test_evening_sync_states_unattended_catchup_behaviour():
    section = _evening_sync().split("## Unattended mode", 1)
    assert len(section) == 2, "evening-sync has no Unattended mode section"
    body = section[1].split("\n## ", 1)[0].lower()
    assert "catch-up" in body or "catchup" in body, (
        "unattended mode caps and flags rather than composing a mega-recap; "
        "finding F4 is that this mode has no coverage at all"
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k evening_sync -v`
Expected: 5 FAILs

- [ ] **Step 3: Rewrite stage 1's consumption paragraph**

In `plugin/skills/evening-sync/SKILL.md`, find the paragraph beginning "Consume the result **verbatim**" and replace it (through the end of that paragraph) with:

```markdown
Consume the result **verbatim** — `today`, `next_business_day`, the day
names, `recap_from`/`recap_to`, `last_daily_note`, `note_to_write`. Never
derive day-of-week or date arithmetic yourself; that is the bug class this
subcommand exists to kill. The recap window is *everything since the last
daily note*: after a missed run or a gap, it widens automatically — no
weekend special case.

**The catch-up block.** `business_days_missed` is how many evening runs did
not happen; `is_catchup` is that count above zero. Skipped days are **never
back-filled** — one note covers the whole window, because fabricating past
daily notes would invent days that have no jottings. The CLI writes that
sentence into the note itself (stage 6); you do not have to compose it.

When `over_threshold` is true, the window is too wide to recap in full.
Detail the window from `recap_detail_from` onward and let
`business_days_not_detailed` stand as a count:

- **interactive** — ask once, here, before any work: detail the last
  `catchup_threshold` business days (the default), or the whole window? Pass
  `detailed_from` in stage 6 only if the answer was to cap.
- **unattended** — always cap, never ask, and carry the catch-up window into
  the Warnings block so a human reviews it.

Every number above is read, never computed. If you find yourself counting
days, you are re-introducing the bug `dates plan` exists to prevent.
```

- [ ] **Step 4: Rewrite stage 6's composition guidance and payload**

Replace stage 6's opening paragraph (from "Compose the recap from:" through the line ending "payloads never land in the vault.") with:

```markdown
Compose the recap from: the recap window's meetings (everything in
`20-meetings/` dated within `recap_from`..`recap_to`), decisions written in
stage 4, harvest jottings worth carrying forward, and watch items
(conflicts, needs-attention flags, self-check warnings). Respect the
language and depth preferences in
`99-workflow-config/context/preferences-and-constraints.md`.

**A flat list of meetings is not a recap.** Required shape, in order:

1. `> [!info] At a glance` — one line: N meetings · entities touched · themes.
2. **Themes** — with ≥2 meetings in the window, 2–4 bullets, each a pattern
   *across* meetings and each naming what it draws on. With one meeting, say
   what it means, not that it happened.
3. **Project pulse** — one line per project touched: where it stands (from
   the project's `Now` callout) and what moved this window.
4. **Decisions logged** — from stage 4, wikilinked.
5. **Watch** — conflicts, needs-attention flags, `SELF-CHECK` lines.
6. **Carried forward** — jottings worth carrying.

**Every entity, person and project you name is a wikilink to the object you
looked up — never a name you recalled.** `daily-note write` refuses a link
that resolves to nothing, and refuses `[[slug|Display Name]]` where the
display name disagrees with the vault; a plain-prose name it cannot check at
all, which is exactly why the linked form is required. If a name has no
object, create it first or leave the name out. Open items live on projects —
link them, never duplicate a task list.

$SCRATCH below is your session scratch directory — payloads never land in
the vault.
```

Then replace the payload heredoc with one that carries the window:

```bash
cat > "$SCRATCH/daily-note.payload.json" <<'JSON'
{
  "date": "<next_business_day>",
  "recap_window": {"from": "<recap_from>", "to": "<recap_to>",
                   "detailed_from": "<recap_detail_from, only when capped>"},
  "recap": "> [!info] At a glance\n> {N meetings · entities · themes}\n\n**Themes**\n- {pattern across meetings}\n\n**Project pulse**\n- [[project-slug]] — {where it stands; what moved}",
  "meetings": [
    {"time": "09:00", "subject": "Weekly Status", "entity": "acme-industries",
     "prep": "**Attendees:** … · **Last meeting:** … · **Context:** …"}
  ]
}
JSON
python3 "$VAULTLIB" daily-note write --vault "$VAULT" --note "$SCRATCH/daily-note.payload.json"
```

And after the existing paragraph about the `structure changed` error, add:

```markdown
`recap_window` is what makes the run idempotent: the CLI fingerprints the
window's meetings, jottings and decisions and stamps the digest on the recap
marker. A re-run over an unchanged input set comes back with
`recap_skipped: true` and leaves the recap byte-identical — that is success,
not a failure to write. Omitting `recap_window` silently forfeits both the
guard and the catch-up banner, so always pass it. Carry any `warnings` from
the result into stage 7 verbatim.
```

- [ ] **Step 5: Extend stage 7's summary block**

In stage 7, add two lines to the summary template, directly above `**Warnings:**`:

```
**Recap window:** {recap_from} → {recap_to} — {catch-up: N business days missed, detailed from {date}} | current
**Recap:** regenerated | unchanged since the last run (inputs identical)
```

- [ ] **Step 6: Extend Unattended mode and Rules**

In the `## Unattended mode` section, add a fourth numbered item:

```markdown
4. **A catch-up run caps rather than sprawls.** When `over_threshold` is
   true, detail from `recap_detail_from` and never ask which to do; put the
   window and `business_days_missed` in the Warnings block so a human
   reviews the note before relying on it. A two-month mega-recap composed
   unattended is the "wrong-doing" rule 3 is about.
```

In the `## Rules` section, append:

```markdown
10. **Catch-up state is reported, never inferred, and never back-filled.**
    `business_days_missed` and `recap_detail_from` come from `dates plan`;
    the banner comes from the CLI; one note covers the whole window.
11. **Names in a machine region are looked up, not recalled.** Entities,
    people and projects appear as wikilinks to objects that exist. The CLI
    refuses the rest — treat a refusal as a lookup you skipped.
```

- [ ] **Step 7: Document both contracts in `plugin/CLAUDE.md`**

In the `## Daily-note regions` section, append two paragraphs:

```markdown
Region markers may carry CLI-owned `key=value` attributes, and exactly one
is defined: `<!-- evening-sync:recap:begin inputs=<16 hex> -->`. That digest
fingerprints what the recap was composed *from* — the window's meeting
notes, the daily notes holding its jottings, and any decision notes written
inside it. `daily-note write` recomputes it whenever the payload carries
`recap_window`, and when it matches the stamp already on the note the recap
region is skipped outright: bytes untouched, `recap_skipped: true`, prep
regions still merged. That is what stops a re-run replacing a recap the exec
already read with a differently-worded, occasionally worse one.

The stamp lives on the marker line rather than in frontmatter (which a merge
may never touch) or a sidecar file (which the design rules out), and a
payload with no `recap_window` *strips* any stamp it finds — leaving one
above a recap whose inputs nobody verified would make the marker lie, and a
lying stamp causes a skip, which is the one failure mode that silently does
nothing. An unknown attribute is an error, not an ignore: guessing at a
marker is how a note gets mis-merged.
```

Then add a new subsection immediately after it:

```markdown
### Wikilinks in region content resolve, or the write fails

Every `[[target]]` in a `daily-note write` payload — recap, prep,
`meetings_note` — must resolve to a vault object: an entity dossier, a
person note, a project index, a meeting note, a decision note, or a daily
note. `#heading` is stripped first; embeds count.

Where the link carries an alias and the target is an *identity* object
(entity, person, project), the alias must equal that object's `entity-name`
/ `person-name` / `project-name` exactly, and the error names the real one
so a caller can fix it without a second lookup. Meetings, decisions and
daily notes must resolve but their aliases are free prose — "Friday's Acme
sync" is a reference, not a claim about what something is called.

This is the same boundary lesson as the two above it. There, a caller that
re-sends what it read corrupts the value; here, a caller that writes a name
it *remembers* instead of one it looked up publishes a plausible fiction
into the exec's daily note. An unreadable dossier is a warning rather than a
refusal: one mangled file must not cost the exec their note.
```

- [ ] **Step 8: Run the contract tests and the linter**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q && python scripts/lint_plugin.py`
Expected: all PASS. `lint_plugin.py` also enforces the clean-room denylist over the new prose — the only names in it are the demo vault's fictional ones.

- [ ] **Step 9: Commit**

```bash
git add plugin/skills/evening-sync/SKILL.md plugin/CLAUDE.md scripts/tests/test_skill_contracts.py
git commit -m "$(cat <<'MSG'
docs(evening-sync): consume the catch-up facts; require looked-up names

Stage 1 reads the catch-up block instead of inferring a gap, and states
the no-back-fill rule. Stage 6 gets a required recap shape — themes and
project pulse, not a meeting list, which is the quality bar the E2E round
asked for — plus the wikilink mandate and the recap_window payload that
arms the idempotence guard. Stage 7 reports the window and whether the
recap regenerated; unattended mode caps rather than sprawls.

Contract tests pin all of it, including recap_window in the payload
example: the CLI keeps it optional for compatibility, so that test is the
only thing keeping the guard switched on. (#56, #57)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 7: release notes, version, and end-to-end verification

**Files:**
- Modify: `CHANGELOG.md` (under `## Unreleased`)
- Modify: `plugin/.claude-plugin/plugin.json` (`0.5.0` → `0.6.0`)

**Interfaces:**
- Consumes: everything.
- Produces: a PR-ready branch.

- [ ] **Step 1: Bump the version**

In `plugin/.claude-plugin/plugin.json`, change `"version": "0.5.0"` to `"version": "0.6.0"`. #62 took 0.5.0; CI's version guard fails a `plugin/` PR that does not move it.

- [ ] **Step 2: Add the changelog entries**

At the top of the list under `## Unreleased` in `CHANGELOG.md`, add two bullets. Client-visible only, in the file's established voice — something you would say out loud to the exec:

```markdown
- **Tomorrow's note tells you when it is catching up.** After missed evenings —
  a holiday, travel, a laptop that stayed shut — the recap used to quietly cover
  the whole gap and look like any other day. It now opens by naming the window
  it covers, how many working days went without a run, and the fact that the
  skipped days are not written up separately: one note covers the stretch. Past
  a week, it recaps the recent days properly and counts the rest rather than
  compressing two months into one summary. (#56)
- **Re-running the evening sync no longer rewrites a recap you have read.** A
  second run on the same day used to regenerate the recap from scratch, which
  could quietly replace a real takeaway with a worse line. It now leaves the
  recap exactly as it was unless the meetings or your jottings actually changed.
  Company, people and project names in the recap are also read from the vault
  instead of recalled, so a near-miss like the wrong middle word in a client's
  name cannot reach the note. (#57)
```

- [ ] **Step 3: Run the three CI commands**

```bash
python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q
```
Expected: all three green. Record the pytest count in the PR body.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md plugin/.claude-plugin/plugin.json
git commit -m "$(cat <<'MSG'
chore: release notes and version bump for 0.6.0 (#56, #57)

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

- [ ] **Step 5: Hand-test in a dated local vault**

Local vaults live in the **main checkout's** gitignored `test-vaults/`, never in a worktree and never in `/tmp`:

```bash
python scripts/make_test_vault.py ../../test-vaults/2026-08-25-catchup --with-plugins
```

Then, from a Claude Code session opened on that vault:

1. `/evening-sync --today 2026-08-21` — the demo fixtures' last daily note is 2026-06-15, so this is the E2E scenario. Read the note in Obsidian: the catch-up callout names the window, the count, and the no-back-fill rule.
2. Re-run the same command. The recap region must be byte-identical (`git diff` in the vault, or compare a copy), and the summary must say the inputs were unchanged.
3. Jot a line into today's note by hand, re-run. The recap regenerates and the jotting survives.
4. `/evening-sync --today 2026-06-15` on a fresh copy — no banner, and the recap reads as themes plus project pulse rather than a meeting list.

Record what each step actually showed. A step you did not run is a step that did not pass.

- [ ] **Step 6: Open the PR**

```bash
git push -u origin claude/issues-56-57-superpowersworkflow-323348
```

PR body must state: the two issues closed (`Closes #56`, `Closes #57`), the three green local checks with the pytest count, the version bump, no new migration, and the hand-test results from Step 5.

---

## Self-Review

**Spec coverage.** D1 → Task 1. D2 → Task 4. D3 part 1 → Task 2, part 2 → Task 3 (including `meeting.date_from_stem`). D4 → Task 5. D5 → Task 6. Contracts-changed table → Tasks 1, 3, 5 (result fields) and Task 7 (version). Documentation section → Task 6 (SKILL.md, `plugin/CLAUDE.md`) and Task 7 (CHANGELOG). Verification section → every task's test steps, plus Task 7 Steps 3 and 5. The fixture precondition the spec records is asserted in Task 5 Step 5. Parked items are deliberately unimplemented.

**Placeholder scan.** No TBD/TODO, no "add error handling", no "similar to Task N" — Task 5's resolver repeats the full candidate tuple rather than referring back. Every code step carries the code. The only `<...>` placeholders are inside SKILL.md prose, where they are the skill's own substitution syntax for values the model fills at runtime (`<recap_from>`, `<next_business_day>`), matching the file's existing convention.

**Type consistency.** `_validate`'s return type changes twice — a plain dict through Task 3, then a `(dict, List[str])` tuple in Task 5, where `write`'s unpacking is updated in the same step. Task 3's Interfaces block flags this so a subagent reading Task 3 alone is not surprised by Task 5. `_merge` returns a 3-tuple from Task 3 onward and Task 4 does not change its arity. `_region`/`_marker_line` take `attrs` as `Optional[dict]` in Task 2 and are called that way in Tasks 3 and 4. `window` dicts hold `date` objects (not ISO strings) everywhere after `_validate_window`, which is why `_catchup_banner` calls `.isoformat()` on them.

**Known ordering constraint.** Task 4's `_recap_body` reads `data["recap_window"]`, which Task 3 adds to `_validate`'s output. Tasks 3 and 4 cannot be swapped. Tasks 2 → 3 → 4 → 5 is a hard chain; Task 1 is independent of that chain but Task 4 needs it.
