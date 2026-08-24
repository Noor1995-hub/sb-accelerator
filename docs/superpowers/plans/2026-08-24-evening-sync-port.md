# P2b — `/evening-sync` Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the evening pipeline (#16) and the daily-note contract, closing #15 as superseded: `/evening-sync` chains harvest → sync → refresh → project-state update → decision capture → tomorrow's daily note, over new deterministic vaultlib subcommands (`dates plan`, `sync update-queue`, `project touch`, `daily-note write/read`).

**Architecture:** Stages, not skills, are the unit (design decision 3). Deterministic stages are vaultlib subcommands; judgment stages are skill prose and subagents. The daily note is the single daily artifact: the evening run writes *tomorrow's* `60-daily-notes/{YYYY-MM-DD}.md`, machine regions are marker-fenced (`<!-- evening-sync:{region}:begin/end -->`), the CLI owns the merge and never touches a byte outside markers, and harvest reads today's note read-only.

**Tech Stack:** Python stdlib only in `plugin/lib/` (3.10 floor); PyYAML/pytest only in `scripts/` (dev side). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-23-daily-loop-port-design.md` (P2b row of "Scope: two PRs"; decisions 1–14 are binding). Conventions: `docs/superpowers/specs/2026-08-23-object-skills-port-design.md`, `plugin/CLAUDE.md`. Predecessor plan (shape reference): `docs/superpowers/plans/2026-08-24-sync-recordings-port.md`.

## Global Constraints

- **Stdlib only, Python 3.10 floor** for everything under `plugin/lib/` — no PyYAML, no 3.11+ constructs; CI's `runtime floor (python 3.10)` job catches violations. Local dev Python is 3.14 — argparse < 3.14 rejects space-separated dash-prefixed option values; `cli._merge_dash_values` handles `--utc-offset`. If you add a flag whose value can start with a dash, extend `_DASH_VALUE_FLAGS`. Subprocess CLI tests are what catch this class.
- **Vault root is always a parameter** (`--vault`), never derived. Writes go through `vault.atomic_write` (UTF-8, LF).
- **CLI envelope:** every run prints exactly one JSON object — `{"ok": true, "result": {...}}` exit 0, or `{"ok": false, "error": "...", "hint": "..."}` exit 1. New modules raise their own `XxxError`; `cli.main` catches and wraps (add the arm **before** the `ValueError` arm).
- **Clean-room:** nothing under `plugin/`, `template/`, `fixtures/` may contain `michael`, `bulthe`, `busdev` (except `upstreamed-from: busdev@ccc27b8` provenance in skill frontmatter), or client names. No Dutch strings.
- **No hardcoded timezone.** Timezone or UTC offset is always a caller argument; day-of-week names come from an explicit English tuple, never locale-dependent `%A`.
- **Ontology is machine truth:** after editing `template/99-workflow-config/reference/ontology.md`, run `python3 scripts/compile_ontology.py` and commit the regenerated `plugin/lib/vaultlib/schema.json` in the same commit — `test_compile_ontology.py` diffs it.
- **Frontmatter must parse identically under PyYAML and the repo's stdlib parser** (`vaultlib/markdown.py`). Everything the CLI emits here uses that module.
- **Every commit message ends with the exact trailer** (own line): `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Verification trio** must pass before claiming any task done: `python3 scripts/lint_plugin.py` · `python3 scripts/validate_template.py` · `python3 -m pytest scripts/tests -q` (baseline at plan time: **564 passed**).
- Work on the current branch `claude/daily-loop-port-p2b-238174` (already at latest main). Never commit to `main`.
- **Never run `git checkout`, `git switch`, `git reset`, `git stash`, or `git rebase` in this worktree** (see `docs/superpowers/lessons.md`). Use `git show <sha>:<path>` to read history.
- **Version bump:** this PR touches `plugin/`, so `plugin/.claude-plugin/plugin.json` goes 0.3.0 → **0.4.0**, and `test_marketplace_manifest.py`'s pinned version follows in the same commit (Task 8).
- **Scheduling ships nothing.** The skill is schedule-agnostic; `--unattended` is the scheduled shape, and how it fires is playbook territory.

## File Structure

```
plugin/lib/vaultlib/
  dates.py         MODIFY — add DAY_NAMES, utc_to_local (DST-correct), plan (recap window + next business day)
  plaud.py         MODIFY — recorded_local via dates.utc_to_local (fixes the DST edge parked from P2a)
  markdown.py      MODIFY — add upsert_scalar_field (replace-or-insert one frontmatter scalar)
  updatequeue.py   NEW    — port of build_update_queue.py: metrics, queue, reverse self-check
  project.py       MODIFY — add touch() (last-updated + next-milestone frontmatter bump)
  dailynote.py     NEW    — daily-note render, marker-region merge, harvest read
  cli.py           MODIFY — wire dates plan · sync update-queue · project touch · daily-note write/read
  schema.json      REGENERATED — carries the new §Daily-note block
plugin/skills/evening-sync/SKILL.md      NEW — the engine (stages 1–7)
plugin/CLAUDE.md                         MODIFY — "Daily-note regions" section (merge contract)
plugin/.claude-plugin/plugin.json        MODIFY — version 0.3.0 → 0.4.0
template/99-workflow-config/reference/ontology.md  MODIFY — §Daily-note block + prose; "Five" → "Six object types"
template/CLAUDE.md                       MODIFY — "Five" → "Six object types"
scripts/tests/
  test_vaultlib_dates.py       MODIFY — plan + utc_to_local tests
  test_vaultlib_plaud.py       MODIFY — DST regression test
  test_vaultlib_markdown.py    MODIFY — upsert_scalar_field tests
  test_vaultlib_updatequeue.py NEW
  test_vaultlib_project.py     MODIFY — touch tests
  test_vaultlib_dailynote.py   NEW
  test_fixtures_ontology.py    MODIFY — daily-note harness entry + marker/jotting/conflict coverage
  test_compile_ontology.py     MODIFY — six objects, daily-note body_sections
  test_skill_contracts.py      MODIFY — evening-sync in the expected set
  test_marketplace_manifest.py MODIFY — version pin 0.4.0
fixtures/demo-vault/
  60-daily-notes/2026-06-01.md  REWRITE to the contract (jotted)
  60-daily-notes/2026-06-05.md  REWRITE to the contract (jotted)
  60-daily-notes/2026-06-12.md  REWRITE to the contract (jotted)
  60-daily-notes/2026-06-15.md  NEW — fresh machine-written note (empty-calendar shape)
  20-meetings/12-06-26-jordan-1on1-v2.md  NEW — conflicts-with sibling (parked P2a item)
  30-projects/*/index.md, 50-people/*.md  RE-STAMP metrics to update-queue's real output at 2026-06-12
CHANGELOG.md                             MODIFY — Unreleased entries
docs/superpowers/plans/2026-08-24-evening-sync-port.md  THIS FILE
```

Existing helpers tasks MUST reuse (do not reimplement): `vault.resolve`, `vault.atomic_write`, `vault.today_iso`, `vault.read_identity_block`, `markdown.split_frontmatter`, `markdown.replace_scalar_field`, `naming.slugify`, `naming.validate_slug`, `schema.validate`, `schema.for_object`, `decision.list_decisions`, `dates.resolve_offset_minutes`, `syncjob.*`, `meeting.write`.

Test fixture convention: vaultlib test files build a minimal vault in `tmp_path` — `99-workflow-config/` plus the numbered folders each test needs (`vault.resolve` requires the config folder and at least one numbered folder). See `scripts/tests/test_vaultlib_syncjob.py` for the pattern.

**What P2a already landed — consume, don't rebuild:** `sync reconcile-reviews` exists and `/sync-recordings` runs it as its step 1, so the evening pipeline's reconcile stage is folded into its sync stage — the skill must say this, not duplicate the call. `decision.list_decisions` already returns the `existingDecisions` projection the queue needs. `meeting write` owns collision guards (`-v2` siblings, single hyphen). Attendees on meetings are **person slugs**, so metrics join on slug (the lab joined on display names — that difference is deliberate).

### The daily-note contract (normative for Tasks 1, 5, 6, 7)

`60-daily-notes/{YYYY-MM-DD}.md`, written the evening before, jotted in during the day, harvested that evening. Exact shape `daily-note write` renders on a fresh file:

```markdown
---
date: 2026-06-15
type: daily-note
---

# 2026-06-15 · Monday

## Recap
<!-- evening-sync:recap:begin -->
{recap — model-supplied markdown}
<!-- evening-sync:recap:end -->

## Meetings

### {HH:MM} — {Subject} · [[{entity-slug}]]
<!-- evening-sync:prep:begin -->
{prep — model-supplied markdown}
<!-- evening-sync:prep:end -->
- 

## End of day
- 
```

Rules: the ` · [[{entity-slug}]]` heading suffix appears only when an entity is linked. Consecutive meetings are separated by one blank line. With an empty calendar, `## Meetings` holds a single prep region containing `*No meetings scheduled.*` (or a caller-supplied single line, e.g. the calendar-unavailable line) and no `###` headings. The `- ` lines (dash + one space) are jotting affordances. H1 day names come from an explicit English tuple. Machine regions regenerate wholesale on re-run; every byte outside the markers is untouchable; the note is never deleted or rewritten by a later day's run. Recap window rule (decision 9): **from = date of the most recent daily note on disk with date ≤ today (inclusive); to = today**; no note yet → from = today.

---

### Task 1: §Daily-note ontology block + daily-note fixture rewrite

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md`
- Modify: `template/CLAUDE.md` (line 42)
- Regenerate: `plugin/lib/vaultlib/schema.json`
- Modify: `scripts/tests/test_fixtures_ontology.py`
- Modify: `scripts/tests/test_compile_ontology.py`
- Rewrite: `fixtures/demo-vault/60-daily-notes/2026-06-01.md`, `2026-06-05.md`, `2026-06-12.md`

**Interfaces:**
- Consumes: `compile_ontology.compile_schema` (body_sections is already in CARRIED_KEYS — no compiler change needed).
- Produces: `schema.json` → `objects.daily-note` with `required: [date, type]`, `enums.type: [daily-note]`, `body_sections: [Recap, Meetings, End of day]`. Task 5 calls `schema.validate("daily-note", ...)`. The three fixture notes are the corpus Tasks 5–7 test merge/read against.

- [ ] **Step 1: Write the failing tests.** In `scripts/tests/test_compile_ontology.py`, replace `test_all_five_objects_compile` with:

```python
def test_all_six_objects_compile():
    objects = co.compile_schema()["objects"]
    assert set(objects) == {"meeting", "project", "person", "decision",
                            "entity", "daily-note"}
    for name, block in objects.items():
        assert block["required"], f"{name}: empty required list"


def test_daily_note_block_is_deliberately_thin():
    block = co.compile_schema()["objects"]["daily-note"]
    assert block["required"] == ["date", "type"]
    assert block["enums"]["type"] == ["daily-note"]
    assert block["body_sections"] == ["Recap", "Meetings", "End of day"]
```

In `scripts/tests/test_fixtures_ontology.py`:
- add to `HARNESS`: `"daily-note": {"glob": "60-daily-notes/*.md"},`
- add to `MINIMUMS`: `"daily-note": 3,`
- change the `test_body_sections_present_in_every_fixture` parametrize list to `["project", "entity", "daily-note"]`, and the tuple in `test_ontology_declares_body_sections_where_the_guard_expects_them` to `("project", "entity", "daily-note")`
- in `test_ontology_schema_blocks_present_and_wellformed`'s docstring, change "five object blocks" to "six object blocks"
- append:

```python
# --- Daily-note fixtures model the evening-sync contract ---

DAILY_MARKER_RE = re.compile(r"<!-- evening-sync:(recap|prep):(begin|end) -->")


def test_daily_note_filename_is_its_date():
    for path in iter_fixture_files(SCHEMAS["daily-note"]["glob"]):
        fm = parse_frontmatter(path)
        assert str(fm["date"]) == path.stem, (
            f"{path}: frontmatter date must equal the filename stem"
        )


def test_daily_note_machine_regions_are_balanced():
    files = iter_fixture_files(SCHEMAS["daily-note"]["glob"])
    assert files, "no daily-note fixtures found"
    for path in files:
        text = path.read_text(encoding="utf-8")
        stack = []
        for name, kind in DAILY_MARKER_RE.findall(text):
            if kind == "begin":
                stack.append(name)
            else:
                assert stack and stack.pop() == name, (
                    f"{path}: unbalanced {name!r} markers"
                )
        assert not stack, f"{path}: region {stack!r} never closed"
        assert text.count("evening-sync:recap:begin") == 1, (
            f"{path}: exactly one recap region"
        )


def _jotting_lines_outside_markers(path):
    """Non-empty '- ' bullets in the Meetings section, outside machine regions."""
    found, inside, in_meetings = [], False, False
    for line in path.read_text(encoding="utf-8").split("\n"):
        marker = DAILY_MARKER_RE.search(line)
        if marker:
            inside = marker.group(2) == "begin"
            continue
        if line.startswith("## "):
            in_meetings = line[3:].strip() == "Meetings"
            continue
        if in_meetings and not inside and line.strip().startswith("- ") \
                and line.strip()[2:].strip():
            found.append(line.strip())
    return found


def test_daily_note_fixtures_carry_hand_jottings_outside_markers():
    # The merge rule is only real if fixtures exercise it (spec: fixture
    # enrichment — "hand-written jottings outside markers").
    jotted = [p for p in iter_fixture_files(SCHEMAS["daily-note"]["glob"])
              if _jotting_lines_outside_markers(p)]
    assert len(jotted) >= 2, (
        "at least two daily-note fixtures must carry hand jottings outside "
        f"markers; found {len(jotted)}"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_compile_ontology.py scripts/tests/test_fixtures_ontology.py -q`
Expected: collection ERROR from `build_schemas()` — `missing schema block(s) for ['daily-note']`.

- [ ] **Step 3: Add the §Daily-note block to the ontology.** In `template/99-workflow-config/reference/ontology.md`: change line 11 to `Six object types: **Meeting · Project · Person · Decision · Entity · Daily note**.` and append a new section after the Entity body-structure section (before `## 2. Relationship graph`):

`````markdown
### Daily note — `60-daily-notes/{YYYY-MM-DD}.md` · no Base

One note per working day, written the evening before by `/evening-sync`,
jotted in by hand during the day, harvested (read-only) that evening. It is
the day's canvas and its archive — deliberately the thinnest object type.

```yaml
object: daily-note
required: [date, type]
optional: []
enums:
  type: [daily-note]
body_sections: [Recap, Meetings, End of day]
```

- `date` is an unquoted ISO date and MUST equal the filename stem.
- **Machine regions are marker-fenced.** Inside the body, machine-written
  content sits between `<!-- evening-sync:{region}:begin -->` and
  `<!-- evening-sync:{region}:end -->` markers — one `recap` region under
  `## Recap`, one `prep` region per meeting under `## Meetings` (or a single
  prep region carrying `*No meetings scheduled.*` on an empty calendar).
  `daily-note write` regenerates marked regions wholesale on any re-run and
  is forbidden from touching a byte outside them. One writer class per
  region.
- **Everything outside the markers is human territory**: jotting bullets
  under each meeting heading, `## End of day`, anything else. The evening
  harvest reads jottings as input; nothing ever edits or routes them in v1.
- A note is never deleted or rewritten by a later day's run. Times are the
  executive's local timezone.

A day in the life of a daily note:

```markdown
### 10:00 — 1:1 — Jordan Vance · [[nordbridge-components]]
<!-- evening-sync:prep:begin -->
**Attendees:** Jordan Vance · **Last meeting:** 2026-03-02 — intro call · **Context:** …
<!-- evening-sync:prep:end -->
- proposal on track for September submission   ← hand jotting, untouchable
```
`````

- [ ] **Step 4: Update the second object-count line.** In `template/CLAUDE.md` line 42: `Five object types: **Meeting · Project · Person · Decision · Entity**.` → `Six object types: **Meeting · Project · Person · Decision · Entity · Daily note**.`

- [ ] **Step 5: Regenerate the compiled schema**

Run: `python3 scripts/compile_ontology.py`
Expected: `wrote plugin/lib/vaultlib/schema.json` (the diff adds the `daily-note` object).

- [ ] **Step 6: Rewrite the three daily-note fixtures to the contract.** These cross-reference the meeting fixtures of their dates and carry hand jottings OUTSIDE the markers. Exact content:

`fixtures/demo-vault/60-daily-notes/2026-06-01.md`:

```markdown
---
date: 2026-06-01
type: daily-note
---

# 2026-06-01 · Monday

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> 1 meeting captured since the last run · Meridian Freight · vendor consolidation theme
- [[20-05-26-meridian-vendor-strategy-brainstorm]] — single-vendor consolidation preferred; yard 2 timeline at risk.
- Decision logged: [[2026-05-20-single-vendor-strategy-adopted]].
- Watch: the brainstorm was captured off-calendar (recorder) and is still in the review queue.
<!-- evening-sync:recap:end -->

## Meetings

### 09:00 — Commercial Operations — Weekly Status Update · [[commercial-operations]]
<!-- evening-sync:prep:begin -->
**Attendees:** Sam Okafor, Omar Siddiqui · **Last meeting:** 2026-04-20 — CRM data modernization kickoff workshop · **Context:** vendor shortlist decision expected this session.
<!-- evening-sync:prep:end -->
- Shortlist approved — Sam to draft RFP scoring criteria by Friday.

## End of day
- Nordbridge proposal drafting continues in the background.
```

`fixtures/demo-vault/60-daily-notes/2026-06-05.md`:

```markdown
---
date: 2026-06-05
type: daily-note
---

# 2026-06-05 · Friday

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> 1 meeting since the last note · Commercial Operations · shortlist approved
- [[01-06-26-commercial-ops-status-update]] — vendor shortlist approved; RFP scoring criteria next.
- Decision logged: [[2026-06-01-vendor-shortlist-approved]].
<!-- evening-sync:recap:end -->

## Meetings

### 15:00 — Commercial Operations — Pipeline Governance Review · [[commercial-operations]]
<!-- evening-sync:prep:begin -->
**Attendees:** Sam Okafor, Taylor Brooks · **Last meeting:** 2026-06-01 — weekly status update; shortlist approved · **Context:** quarterly cadence review; no decisions expected.
<!-- evening-sync:prep:end -->
- Cadence holds; no material decision this cycle — archive the capture.

## End of day
- Quiet close; Meridian steady ahead of the next steerco.
```

`fixtures/demo-vault/60-daily-notes/2026-06-12.md`:

```markdown
---
date: 2026-06-12
type: daily-note
---

# 2026-06-12 · Friday

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> 1 meeting since the last note · Commercial Operations · 1 capture needs attention
- [[05-06-26-pipeline-governance-review]] — cadence reviewed; capture flagged needs-attention (low-confidence match), no decision logged.
- Watch: resolve the flagged capture in Meetings triage.
<!-- evening-sync:recap:end -->

## Meetings

### 10:00 — 1:1 — Jordan Vance · [[nordbridge-components]]
<!-- evening-sync:prep:begin -->
**Attendees:** Jordan Vance · **Last meeting:** 2026-03-02 — Nordbridge intro call · **Context:** regional rollout proposal targeted for September submission; Dana Whitfield is the procurement contact.
<!-- evening-sync:prep:end -->
- Proposal drafting on track for September submission.

## End of day
- Follow up with Dana on rollout scope next week.
```

- [ ] **Step 7: Run the full suite**

Run: `python3 -m pytest scripts/tests -q`
Expected: all pass. (The new harness entry validates the rewritten fixtures; `test_compile_ontology` passes because schema.json was regenerated; nothing else reads daily notes yet.)

- [ ] **Step 8: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md template/CLAUDE.md plugin/lib/vaultlib/schema.json scripts/tests/test_fixtures_ontology.py scripts/tests/test_compile_ontology.py fixtures/demo-vault/60-daily-notes/
git commit -m "feat: §Daily-note — the sixth object type, and fixtures on the contract

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `dates plan` + `utc_to_local` (and the plaud DST fix)

**Files:**
- Modify: `plugin/lib/vaultlib/dates.py`
- Modify: `plugin/lib/vaultlib/plaud.py` (lines 101–104)
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_dates.py`, `scripts/tests/test_vaultlib_plaud.py`

**Interfaces:**
- Consumes: existing `dates._parse_offset_minutes`, `DatesError`; `vault.resolve` (via cli).
- Produces: `dates.DAY_NAMES` (7-tuple, Monday first); `dates.utc_to_local(utc_dt: datetime, timezone: Optional[str], utc_offset: Optional[str]) -> tuple[datetime, str]` (naive local dt, `"zoneinfo"|"explicit"`) — used by `plaud.reassemble` and available to future adapters; `dates.plan(root: Path, today: Optional[str], *, timezone=None, utc_offset=None) -> dict` with keys `today`, `today_day_name`, `next_business_day`, `next_day_name`, `note_to_write`, `last_daily_note` (relpath or null), `recap_from`, `recap_to`. CLI: `dates plan --vault <path> [--today YYYY-MM-DD] [--timezone <IANA> | --utc-offset ±HH:MM]` (unlike `dates window`, this one takes `--vault`). Tasks 5/7/8 consume `DAY_NAMES` and the plan output.

- [ ] **Step 1: Write the failing tests** — append to `scripts/tests/test_vaultlib_dates.py` (its header already imports `json`, `subprocess`, `sys`, `pytest`, `dates`, and defines `CLI` and `_zoneinfo_available`):

```python
from datetime import datetime, timedelta, timezone as _timezone


def make_vault(tmp_path):
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "60-daily-notes").mkdir()
    return tmp_path


def note(root, date_iso):
    (root / "60-daily-notes" / f"{date_iso}.md").write_text(
        f"---\ndate: {date_iso}\ntype: daily-note\n---\n", encoding="utf-8")


def test_plan_friday_rolls_to_monday(tmp_path):
    root = make_vault(tmp_path)
    for d in ("2026-06-01", "2026-06-05", "2026-06-12"):
        note(root, d)
    result = dates.plan(root, "2026-06-12")
    assert result["today"] == "2026-06-12"
    assert result["today_day_name"] == "Friday"
    assert result["next_business_day"] == "2026-06-15"
    assert result["next_day_name"] == "Monday"
    assert result["note_to_write"] == "60-daily-notes/2026-06-15.md"
    assert result["last_daily_note"] == "60-daily-notes/2026-06-12.md"
    # Decision 9: Friday's run writes Monday's note recapping Friday.
    assert result["recap_from"] == "2026-06-12"
    assert result["recap_to"] == "2026-06-12"


def test_plan_weekend_rolls_to_monday(tmp_path):
    root = make_vault(tmp_path)
    assert dates.plan(root, "2026-06-13")["next_business_day"] == "2026-06-15"
    assert dates.plan(root, "2026-06-14")["next_business_day"] == "2026-06-15"


def test_plan_gap_recap_window_covers_the_gap(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-01")
    result = dates.plan(root, "2026-06-10")
    assert result["recap_from"] == "2026-06-01"
    assert result["recap_to"] == "2026-06-10"
    assert result["next_business_day"] == "2026-06-11"


def test_plan_with_no_notes_yet(tmp_path):
    result = dates.plan(make_vault(tmp_path), "2026-06-10")
    assert result["last_daily_note"] is None
    assert result["recap_from"] == "2026-06-10"


def test_plan_ignores_future_notes_and_non_date_files(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    note(root, "2026-06-15")   # tomorrow's note, written by an earlier run today
    (root / "60-daily-notes" / "README.md").write_text("# x", encoding="utf-8")
    result = dates.plan(root, "2026-06-12")
    assert result["last_daily_note"] == "60-daily-notes/2026-06-12.md"


def test_plan_requires_today_or_a_zone(tmp_path):
    with pytest.raises(dates.DatesError, match="--today"):
        dates.plan(make_vault(tmp_path), None)


def test_plan_rejects_malformed_today(tmp_path):
    with pytest.raises(dates.DatesError):
        dates.plan(make_vault(tmp_path), "12-06-2026")


def test_plan_derives_today_from_an_explicit_offset(tmp_path):
    root = make_vault(tmp_path)
    before = (datetime.now(_timezone.utc) + timedelta(hours=14)).date().isoformat()
    result = dates.plan(root, None, utc_offset="+14:00")
    after = (datetime.now(_timezone.utc) + timedelta(hours=14)).date().isoformat()
    assert result["today"] in {before, after}


def test_utc_to_local_explicit_offset():
    local, source = dates.utc_to_local(datetime(2026, 8, 20, 12, 0), None, "-05:30")
    assert local == datetime(2026, 8, 20, 6, 30)
    assert source == "explicit"


@pytest.mark.skipif(not _zoneinfo_available(), reason="no tz database on host")
def test_utc_to_local_is_correct_across_the_dst_edge():
    # Brussels springs forward at 2026-03-29 01:00 UTC. An instant after the
    # switch must land at +02:00; interpreting the UTC value as wall time (the
    # P2a bug this replaces) yields 02:30 instead of 03:30.
    local, source = dates.utc_to_local(
        datetime(2026, 3, 29, 1, 30), "Europe/Brussels", None)
    assert local == datetime(2026, 3, 29, 3, 30)
    assert source == "zoneinfo"


def test_utc_to_local_requires_exactly_one_zone_argument():
    with pytest.raises(dates.DatesError):
        dates.utc_to_local(datetime(2026, 1, 1), None, None)
    with pytest.raises(dates.DatesError):
        dates.utc_to_local(datetime(2026, 1, 1), "Europe/Brussels", "+01:00")


def test_cli_plan_envelope(tmp_path):
    root = make_vault(tmp_path)
    note(root, "2026-06-12")
    proc = subprocess.run(
        [sys.executable, str(CLI), "dates", "plan",
         "--vault", str(root), "--today", "2026-06-12"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["next_business_day"] == "2026-06-15"
```

And append to `scripts/tests/test_vaultlib_plaud.py` (it already imports `json` and `plaud`; add the skipif helper import from the dates test or inline it):

```python
def test_reassemble_recorded_local_handles_the_dst_edge(tmp_path):
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
    except Exception:
        import pytest
        pytest.skip("no tz database on host")
    meta = tmp_path / "m.json"
    meta.write_text(json.dumps({"id": "r1", "name": "T",
                                "start_at": "2026-03-29T01:30:00",
                                "duration": 60000}), encoding="utf-8")
    tr = tmp_path / "t.json"
    tr.write_text(json.dumps({"segments": [
        {"speaker": "A", "content": "hi", "end_time": 60000}]}),
        encoding="utf-8")
    result = plaud.reassemble(str(meta), str(tr), None, str(tmp_path / "out"),
                              timezone="Europe/Brussels")
    assert result["recorded_local"] == "2026-03-29 03:30:00"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dates.py scripts/tests/test_vaultlib_plaud.py -q`
Expected: FAIL — `AttributeError: module 'vaultlib.dates' has no attribute 'plan'` (and `utc_to_local`); the plaud DST test yields `2026-03-29 02:30:00`.

- [ ] **Step 3: Implement.** Append to `plugin/lib/vaultlib/dates.py` (add `from datetime import date, datetime, timedelta, timezone as _timezone` to the existing import — keep one import line — and `from pathlib import Path`, `from typing import Optional, Tuple` already partially present):

```python
DAILY_NOTES_DIR = "60-daily-notes"

# Explicit and English on purpose: %A is locale-dependent, and the whole point
# of this module is that the model never derives day-of-week itself.
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")

# weekday(): Mon=0 … Sun=6. Fri -> Mon (+3), Sat -> Mon (+2), Sun -> Mon (+1).
_NEXT_BUSINESS_DAYS = {4: 3, 5: 2, 6: 1}

_ISO_DATE_ONLY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _parse_date(text, label: str) -> date:
    raw = str(text).strip()
    if not _ISO_DATE_ONLY_RE.match(raw):
        raise DatesError(f"{label} {text!r} must be ISO YYYY-MM-DD")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise DatesError(f"{label} {text!r} is not a real date") from exc


def utc_to_local(utc_dt: datetime, timezone: Optional[str],
                 utc_offset: Optional[str]) -> Tuple[datetime, str]:
    """A naive UTC datetime rendered in the executive's local time.

    The zoneinfo path converts properly (attach UTC, astimezone) rather than
    asking what offset is in force at the UTC value read as wall time — those
    differ inside the DST transition window, which is exactly the recorded_local
    bug this fixes.
    """
    if (timezone is None) == (utc_offset is None):
        raise DatesError(
            "pass exactly one of --timezone (IANA name, e.g. Europe/Brussels) "
            "or --utc-offset (e.g. +02:00)"
        )
    if utc_offset is not None:
        return utc_dt + timedelta(minutes=_parse_offset_minutes(utc_offset)), "explicit"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
    except Exception as exc:
        raise DatesError(
            f"timezone {timezone!r} could not be resolved on this host "
            f"({exc.__class__.__name__}) — check the IANA name, or pass "
            "--utc-offset (e.g. +02:00) instead"
        ) from exc
    local = utc_dt.replace(tzinfo=_timezone.utc).astimezone(tz)
    return local.replace(tzinfo=None), "zoneinfo"


def plan(root: Path, today: Optional[str] = None, *,
         timezone: Optional[str] = None,
         utc_offset: Optional[str] = None) -> dict:
    """The authoritative date block for the evening run.

    Everything downstream consumes these values verbatim — the model never
    derives day-of-week or offsets from an ISO date. The recap window is
    design decision 9: everything since the last daily note on disk
    (inclusive), through today. A note dated in the future (tomorrow's,
    written by an earlier run today) is not "the last daily note".
    """
    if today is not None:
        today_date = _parse_date(today, "today")
    else:
        if timezone is None and utc_offset is None:
            raise DatesError(
                "pass --today, or --timezone/--utc-offset so today can be "
                "derived from the clock"
            )
        now_utc = datetime.now(_timezone.utc).replace(tzinfo=None, microsecond=0)
        local_now, _ = utc_to_local(now_utc, timezone, utc_offset)
        today_date = local_now.date()

    notes_dir = root / DAILY_NOTES_DIR
    existing = []
    for path in sorted(notes_dir.glob("*.md")) if notes_dir.is_dir() else []:
        if not _ISO_DATE_ONLY_RE.match(path.stem):
            continue
        try:
            noted = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if noted <= today_date:
            existing.append(noted)
    last = max(existing) if existing else None

    nxt = today_date + timedelta(
        days=_NEXT_BUSINESS_DAYS.get(today_date.weekday(), 1))
    return {
        "today": today_date.isoformat(),
        "today_day_name": DAY_NAMES[today_date.weekday()],
        "next_business_day": nxt.isoformat(),
        "next_day_name": DAY_NAMES[nxt.weekday()],
        "note_to_write": f"{DAILY_NOTES_DIR}/{nxt.isoformat()}.md",
        "last_daily_note": (f"{DAILY_NOTES_DIR}/{last.isoformat()}.md"
                            if last else None),
        "recap_from": (last or today_date).isoformat(),
        "recap_to": today_date.isoformat(),
    }
```

In `plugin/lib/vaultlib/plaud.py`, replace lines 101–104:

```python
    offset_minutes, _ = dates.resolve_offset_minutes(
        start_utc, timezone, utc_offset)
    local = start_utc + timedelta(minutes=offset_minutes)
    recorded_local = local.strftime("%Y-%m-%d %H:%M:%S")
```

with (also normalize an offset-aware `start_at`, which the old arithmetic silently mishandled):

```python
    if start_utc.tzinfo is not None:
        from datetime import timezone as _timezone
        start_utc = start_utc.astimezone(_timezone.utc).replace(tzinfo=None)
    local, _ = dates.utc_to_local(start_utc, timezone, utc_offset)
    recorded_local = local.strftime("%Y-%m-%d %H:%M:%S")
```

(`timedelta` may now be unused in plaud.py — remove it from the import if so.)

- [ ] **Step 4: Wire the CLI.** In `build_parser()` after the `dates_window` block:

```python
    dates_plan = dates_sub.add_parser(
        "plan", help="authoritative date block: today, next business day, recap window")
    _add_vault_argument(dates_plan)
    dates_plan.add_argument("--today", help="ISO date override (tests, backfills)")
    dates_plan.add_argument("--timezone", help="IANA timezone name")
    dates_plan.add_argument("--utc-offset", dest="utc_offset",
                            help="explicit offset like +02:00")
```

In `_dispatch`, replace the `dates` branch:

```python
    if args.group == "dates":
        if args.action == "window":
            return _ok(dates.window(args.start, timezone=args.timezone,
                                    utc_offset=args.utc_offset, hours=args.hours))
        return _ok(dates.plan(root, args.today, timezone=args.timezone,
                              utc_offset=args.utc_offset))
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dates.py scripts/tests/test_vaultlib_plaud.py scripts/tests/test_vaultlib_cli.py scripts/tests/test_skill_contracts.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/dates.py plugin/lib/vaultlib/plaud.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_dates.py scripts/tests/test_vaultlib_plaud.py
git commit -m "feat: dates plan — authoritative evening date block, DST-correct utc_to_local

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `sync update-queue` — metrics, queue, reverse self-check

**Files:**
- Modify: `plugin/lib/vaultlib/markdown.py` (add `upsert_scalar_field`)
- Create: `plugin/lib/vaultlib/updatequeue.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_markdown.py`, `scripts/tests/test_vaultlib_updatequeue.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter`, `markdown.upsert_scalar_field` (new), `naming.validate_slug`, `vault.atomic_write`, `decision.list_decisions`.
- Produces: `markdown.upsert_scalar_field(text, field, value) -> str` (replace in place, or insert before the closing `---` when absent); `updatequeue.UpdateQueueError`; `updatequeue.self_check(confirmed, queued_slugs, active_last_updated) -> list[str]`; `updatequeue.run(root: Path, today: str, executive: str) -> dict` with keys `today`, `executive`, `meetingsIndexed`, `confirmedMeetings`, `projectsNeedingUpdate` (list of `{slug, indexPath, decisionsDir, lastUpdated, newCount, newFiles, existingDecisions}`), `metricsWritten` (`{projects, people}`), `warnings`. `existingDecisions` is `decision.list_decisions(...)["decisions"]` verbatim (stem/path/date/status/summary/supersedes/source/reviewed, newest first). CLI: `sync update-queue --vault <path> --executive <slug> [--today YYYY-MM-DD]`. Task 8's skill consumes the queue; Task 7 pins fixture values.

Definitions (port of `build_update_queue.py`, adapted to the product):
- Only `review_status: confirmed` meetings with a parseable ISO date count — everywhere.
- Windows are **strictly greater than** `today − 7d/30d/90d` (lab semantics; a meeting exactly 7 days old is outside the 7d window).
- `key-people` = top-3 attendee slugs by frequency over confirmed meetings in the 90d window, **excluding the executive by person slug** (never by name); ties break by slug ascending (deterministic, unlike `Counter.most_common`).
- Queue: active projects whose confirmed meetings are dated strictly after `last-updated`. Sorted by `newCount` desc, then slug.
- Metrics are written to every active project and every person note (fields upserted if absent), but a file is only rewritten when its content actually changes.
- One mangled file never stops the run: parse failures become warnings.

- [ ] **Step 1: Write the failing tests.** Append to `scripts/tests/test_vaultlib_markdown.py`:

```python
def test_upsert_scalar_field_replaces_in_place():
    text = "---\nslug: x\nmeetings-7d: 3\n---\nBody stays.\n"
    result = markdown.upsert_scalar_field(text, "meetings-7d", "0")
    assert result == "---\nslug: x\nmeetings-7d: 0\n---\nBody stays.\n"


def test_upsert_scalar_field_inserts_before_the_closing_fence():
    text = "---\nslug: x\n---\nBody stays.\n"
    result = markdown.upsert_scalar_field(text, "meetings-7d", "2")
    assert result == "---\nslug: x\nmeetings-7d: 2\n---\nBody stays.\n"


def test_upsert_scalar_field_requires_frontmatter():
    import pytest
    with pytest.raises(ValueError):
        markdown.upsert_scalar_field("no fences here", "a", "b")
```

Create `scripts/tests/test_vaultlib_updatequeue.py`:

```python
"""sync update-queue: the deterministic data layer under /evening-sync.

Ports build_update_queue.py minus --auto-fix (parked toward /health-check) and
minus allowedTags (decision tags were dropped in P1a). Attendees are person
slugs in the product, so metrics join on slug — and the executive is excluded
from key-people by slug, never by display name.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from vaultlib import updatequeue

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def make_vault(tmp_path: Path) -> Path:
    for folder in ("99-workflow-config", "20-meetings", "30-projects", "50-people"):
        (tmp_path / folder).mkdir()
    write_person(tmp_path, "exec-morgan")
    return tmp_path


def write_person(root: Path, slug: str) -> None:
    (root / "50-people" / f"{slug}.md").write_text(
        f'---\nperson-name: "X"\nslug: {slug}\nrelationship:\n---\n',
        encoding="utf-8")


def write_project(root: Path, slug: str, *, status="active",
                  last_updated="2026-06-01", with_metrics=True) -> Path:
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", "type: project", f'project-name: "{slug}"', f"slug: {slug}",
             f"status: {status}", "project-type: initiative", "entity: acme",
             "owner: exec-morgan", "created: 2026-01-01",
             f"last-updated: {last_updated}"]
    if with_metrics:
        lines += ["meetings-7d: 9", "meetings-30d: 9", "key-people: [stale-slug]"]
    lines += ["---", "", "## Decisions", "", "## Open Items", "",
              "## Related Meetings", ""]
    (folder / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return folder / "index.md"


def write_meeting(root: Path, stem: str, *, date_value="2026-06-10T10:00",
                  review_status="confirmed", projects=(), attendees=()) -> None:
    proj = ", ".join(projects)
    att = ", ".join(attendees)
    (root / "20-meetings" / f"{stem}.md").write_text("\n".join([
        "---", f"date: {date_value}", "type: meeting",
        f"review_status: {review_status}",
        f"projects: [{proj}]", f"attendees: [{att}]", "---", "", "- x", "",
    ]), encoding="utf-8")


def write_decision(root: Path, project: str, stem: str) -> None:
    folder = root / "30-projects" / project / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.md").write_text("\n".join([
        "---", "type: decision", f"project: {project}", "date: 2026-06-02",
        "status: active", 'summary: "A prior decision."', "supersedes:",
        "reviewed: true", "---", "", "**Decision** — x.", "",
        "**Why** — y.", "", "**Implications** — z.", "",
    ]), encoding="utf-8")


def test_metrics_windows_exclusion_and_tie_break(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    write_person(root, "bo-marsh")
    index = write_project(root, "alpha", last_updated="2026-06-12")
    # Inside 7d; exec attends everything and must not appear in key-people.
    write_meeting(root, "m1", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "exec-morgan"))
    # Inside 30d only (2026-05-20 > 2026-05-13, but <= 2026-06-05).
    write_meeting(root, "m2", date_value="2026-05-20T09:00",
                  projects=("alpha",), attendees=("bo-marsh", "exec-morgan"))
    # Exactly on the 7d edge: 2026-06-05 is NOT strictly greater than d7.
    write_meeting(root, "m3", date_value="2026-06-05T09:00",
                  projects=("alpha",), attendees=("bo-marsh", "exec-morgan"))
    # needs-review never counts.
    write_meeting(root, "m4", date_value="2026-06-11T09:00",
                  review_status="needs-review",
                  projects=("alpha",), attendees=("ana-fields",))

    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 1" in text
    assert "meetings-30d: 3" in text
    # In the 90d window: bo-marsh 2 (m2, m3), ana-fields 1 (m1); exec excluded.
    assert "key-people: [bo-marsh, ana-fields]" in text
    assert result["confirmedMeetings"] == 3
    # exec-morgan, ana-fields, bo-marsh
    assert result["metricsWritten"] == {"projects": 1, "people": 3}

    person = (root / "50-people" / "bo-marsh.md").read_text(encoding="utf-8")
    assert "meetings-7d: 0" in person and "meetings-30d: 2" in person


def test_key_people_ties_break_by_slug(tmp_path):
    root = make_vault(tmp_path)
    for slug in ("zed-quill", "ana-fields"):
        write_person(root, slug)
    write_project(root, "alpha", last_updated="2026-06-12")
    write_meeting(root, "m1", date_value="2026-06-10T10:00", projects=("alpha",),
                  attendees=("zed-quill", "ana-fields", "exec-morgan"))
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert "key-people: [ana-fields, zed-quill]" in text


def test_queue_membership_and_projection(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "ana-fields")
    write_project(root, "alpha", last_updated="2026-06-01")
    write_project(root, "beta", last_updated="2026-06-12")
    write_project(root, "gamma", status="paused", last_updated="2026-01-01")
    write_decision(root, "alpha", "2026-06-02-a-prior-decision")
    write_meeting(root, "new-alpha", date_value="2026-06-10T10:00",
                  projects=("alpha",), attendees=("ana-fields", "exec-morgan"))
    # Dated exactly on beta's last-updated day: not strictly after -> not queued.
    write_meeting(root, "old-beta", date_value="2026-06-12T10:00",
                  projects=("beta",), attendees=("ana-fields",))
    # Paused projects are never queued, even with newer meetings.
    write_meeting(root, "for-gamma", date_value="2026-06-10T10:00",
                  projects=("gamma",), attendees=("ana-fields",))

    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    queue = result["projectsNeedingUpdate"]
    assert [entry["slug"] for entry in queue] == ["alpha"]
    entry = queue[0]
    assert entry["indexPath"] == "30-projects/alpha/index.md"
    assert entry["decisionsDir"] == "30-projects/alpha/decisions/"
    assert entry["lastUpdated"] == "2026-06-01"
    assert entry["newCount"] == 1
    assert entry["newFiles"] == ["20-meetings/new-alpha.md"]
    assert entry["existingDecisions"][0]["stem"] == "2026-06-02-a-prior-decision"
    assert entry["existingDecisions"][0]["summary"] == "A prior decision."


def test_upserts_metrics_when_fields_are_absent_and_writes_only_on_change(tmp_path):
    root = make_vault(tmp_path)
    index = write_project(root, "alpha", with_metrics=False,
                          last_updated="2026-06-12")
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    text = index.read_text(encoding="utf-8")
    assert "meetings-7d: 0" in text and "key-people: []" in text
    before = index.stat().st_mtime_ns
    updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    assert index.stat().st_mtime_ns == before  # unchanged content -> no rewrite


def test_broken_files_warn_and_the_run_continues(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    (root / "20-meetings" / "broken.md").write_text("no frontmatter",
                                                    encoding="utf-8")
    write_project(root, "beta", last_updated="not-a-date")
    result = updatequeue.run(root, today="2026-06-12", executive="exec-morgan")
    assert any("broken.md" in w for w in result["warnings"])
    assert any("last-updated" in w and "beta" in w for w in result["warnings"])
    assert result["metricsWritten"]["projects"] == 2


def test_executive_slug_is_validated(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(updatequeue.UpdateQueueError, match="person note"):
        updatequeue.run(root, today="2026-06-12", executive="ghost-exec")
    with pytest.raises(updatequeue.UpdateQueueError):
        updatequeue.run(root, today="2026-06-12", executive="Not A Slug")
    with pytest.raises(updatequeue.UpdateQueueError, match="--today"):
        updatequeue.run(root, today="12-06-2026", executive="exec-morgan")


def test_self_check_trips_on_a_silent_skip():
    confirmed = [{"file": "20-meetings/m.md", "date": date(2026, 6, 10),
                  "projects": ["alpha"], "attendees": []}]
    warnings = updatequeue.self_check(
        confirmed, queued_slugs=set(),
        active_last_updated={"alpha": date(2026, 6, 1)})
    assert len(warnings) == 1 and "SELF-CHECK" in warnings[0]
    # Queued or up-to-date projects never trip it.
    assert updatequeue.self_check(confirmed, {"alpha"},
                                  {"alpha": date(2026, 6, 1)}) == []
    assert updatequeue.self_check(confirmed, set(),
                                  {"alpha": date(2026, 6, 12)}) == []


def test_cli_update_queue_envelope(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-06-12")
    proc = subprocess.run(
        [sys.executable, str(CLI), "sync", "update-queue",
         "--vault", str(root), "--today", "2026-06-12",
         "--executive", "exec-morgan"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["projectsNeedingUpdate"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_markdown.py scripts/tests/test_vaultlib_updatequeue.py -q`
Expected: FAIL — `AttributeError: ... 'upsert_scalar_field'` and `ImportError: cannot import name 'updatequeue'`.

- [ ] **Step 3: Implement.** Append to `plugin/lib/vaultlib/markdown.py` (next to `replace_scalar_field`):

```python
def upsert_scalar_field(text: str, field: str, value: str) -> str:
    """replace_scalar_field, but inserting the field before the closing `---`
    when it is absent. For metric fields that are optional in the schema —
    every other byte, including hand-authored key order, stays put.
    """
    normalized = _normalize(text)
    match = _FRONTMATTER_RE.match(normalized)
    if not match:
        raise ValueError("file has no YAML frontmatter")
    block = match.group(1)
    pattern = re.compile(rf"^({re.escape(field)}:)([ \t]*)(.*)$", re.MULTILINE)
    if pattern.search(block):
        updated_block = pattern.sub(rf"\g<1> {value}", block, count=1)
    else:
        updated_block = f"{block}\n{field}: {value}"
    return normalized[: match.start(1)] + updated_block + normalized[match.end(1):]
```

Create `plugin/lib/vaultlib/updatequeue.py`:

```python
"""Project/person meeting metrics and the project-state update queue.

Port of the lab's build_update_queue.py, minus --auto-fix (decision-graph
drift repair is parked toward /health-check; v1 surfaces drift as warnings
only) and minus allowedTags (decision tags were dropped in P1a).

Only review_status: confirmed meetings count — triage is the quality gate.
Attendees are person slugs here, so metrics join on slug, and the executive
is excluded from key-people by slug — never by display name, which is why the
lab's name-prefix filter could not have ported.

The reverse self-check re-derives the queue by iterating meetings -> projects
(the opposite direction from the queue's per-project scan) so a silent skip
in either pass shows up as a warning instead of staying invisible — the bug
class that once cost the lab nine unqueued projects.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import decision, markdown, naming, vault

MEETINGS_DIR = "20-meetings"
PROJECTS_DIR = "30-projects"
PEOPLE_DIR = "50-people"
KEY_PEOPLE_WINDOW_DAYS = 90
TOP_KEY_PEOPLE = 3

_ISO_DATE_ONLY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


class UpdateQueueError(Exception):
    """An argument the caller must fix."""


def _parse_first_iso_date(value) -> Optional[date]:
    """First 10 chars as YYYY-MM-DD, or None. Meeting dates are ISO datetimes;
    last-updated is an ISO date; both reduce to the day."""
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _index_meetings(root: Path) -> Tuple[List[dict], List[str]]:
    meetings: List[dict] = []
    warnings: List[str] = []
    folder = root / MEETINGS_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        meetings.append({
            "file": rel,
            "date": _parse_first_iso_date(data.get("date")),
            "review_status": data.get("review_status"),
            "projects": [str(s) for s in (data.get("projects") or []) if s],
            "attendees": [str(s) for s in (data.get("attendees") or []) if s],
        })
    return meetings, warnings


def _upsert_all(text: str, fields: Dict[str, str]) -> str:
    for field, value in fields.items():
        text = markdown.upsert_scalar_field(text, field, value)
    return text


def self_check(confirmed: List[dict], queued_slugs: Set[str],
               active_last_updated: Dict[str, Optional[date]]) -> List[str]:
    """Independent reverse-direction verification of the queue."""
    warnings: List[str] = []
    flagged: Set[str] = set()
    for meeting in confirmed:
        for slug in meeting["projects"]:
            if slug in queued_slugs or slug in flagged:
                continue
            last_updated = active_last_updated.get(slug)
            if last_updated is None:
                continue
            if meeting["date"] > last_updated:
                warnings.append(
                    f"SELF-CHECK: confirmed meeting '{meeting['file']}' "
                    f"({meeting['date'].isoformat()}) references active project "
                    f"'{slug}' (last-updated {last_updated.isoformat()}) but the "
                    "project was not queued — possible silent skip, investigate."
                )
                flagged.add(slug)
    return warnings


def run(root: Path, today: str, executive: str) -> dict:
    exec_slug = str(executive or "").strip()
    try:
        naming.validate_slug(exec_slug)
    except ValueError as exc:
        raise UpdateQueueError(f"--executive {executive!r}: {exc}") from exc
    if not (root / PEOPLE_DIR / f"{exec_slug}.md").is_file():
        raise UpdateQueueError(
            f"--executive {exec_slug!r} has no person note at "
            f"{PEOPLE_DIR}/{exec_slug}.md — the executive is excluded from "
            "key-people by slug, so a mistyped slug silently poisons the metric"
        )
    if not _ISO_DATE_ONLY_RE.match(str(today or "").strip()):
        raise UpdateQueueError(f"--today {today!r} must be ISO YYYY-MM-DD")
    today_date = _parse_first_iso_date(today)
    if today_date is None:
        raise UpdateQueueError(f"--today {today!r} is not a real date")
    d7 = today_date - timedelta(days=7)
    d30 = today_date - timedelta(days=30)
    d90 = today_date - timedelta(days=KEY_PEOPLE_WINDOW_DAYS)

    meetings, warnings = _index_meetings(root)
    confirmed = [m for m in meetings
                 if m["review_status"] == "confirmed" and m["date"]]

    queue: List[dict] = []
    active_last_updated: Dict[str, Optional[date]] = {}
    projects_written = 0
    projects_dir = root / PROJECTS_DIR
    for index_path in (sorted(projects_dir.glob("*/index.md"))
                       if projects_dir.is_dir() else []):
        rel = index_path.relative_to(root).as_posix()
        try:
            text = index_path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        slug = data.get("slug")
        if data.get("status") != "active" or not slug:
            continue
        slug = str(slug)

        for_project = [m for m in confirmed if slug in m["projects"]]
        m7 = sum(1 for m in for_project if m["date"] > d7)
        m30 = sum(1 for m in for_project if m["date"] > d30)
        counts: Dict[str, int] = {}
        for meeting in for_project:
            if meeting["date"] > d90:
                for attendee in meeting["attendees"]:
                    if attendee != exec_slug:
                        counts[attendee] = counts.get(attendee, 0) + 1
        key_people = [s for s, _ in sorted(counts.items(),
                                           key=lambda kv: (-kv[1], kv[0]))
                      ][:TOP_KEY_PEOPLE]
        updated = _upsert_all(text, {
            "meetings-7d": str(m7),
            "meetings-30d": str(m30),
            "key-people": "[{}]".format(", ".join(key_people)),
        })
        if updated != text:
            vault.atomic_write(index_path, updated)
        projects_written += 1

        last_updated = _parse_first_iso_date(data.get("last-updated"))
        active_last_updated[slug] = last_updated
        if last_updated is None:
            warnings.append(
                f"{rel}: unparseable last-updated "
                f"{data.get('last-updated')!r} — project cannot be queued"
            )
            continue
        new_meetings = [m for m in for_project if m["date"] > last_updated]
        if new_meetings:
            queue.append({
                "slug": slug,
                "indexPath": rel,
                "decisionsDir": f"{PROJECTS_DIR}/{slug}/decisions/",
                "lastUpdated": last_updated.isoformat(),
                "newCount": len(new_meetings),
                "newFiles": [m["file"] for m in new_meetings],
                "existingDecisions":
                    decision.list_decisions(root, slug)["decisions"],
            })
    queue.sort(key=lambda entry: (-entry["newCount"], entry["slug"]))

    people_written = 0
    people_dir = root / PEOPLE_DIR
    for path in sorted(people_dir.glob("*.md")) if people_dir.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        slug = data.get("slug")
        if not slug:
            warnings.append(f"{rel}: no slug — metrics skipped")
            continue
        slug = str(slug)
        m7 = sum(1 for m in confirmed
                 if slug in m["attendees"] and m["date"] > d7)
        m30 = sum(1 for m in confirmed
                  if slug in m["attendees"] and m["date"] > d30)
        updated = _upsert_all(text, {"meetings-7d": str(m7),
                                     "meetings-30d": str(m30)})
        if updated != text:
            vault.atomic_write(path, updated)
        people_written += 1

    warnings.extend(self_check(confirmed, {entry["slug"] for entry in queue},
                               active_last_updated))
    return {
        "today": today_date.isoformat(),
        "executive": exec_slug,
        "meetingsIndexed": len(meetings),
        "confirmedMeetings": len(confirmed),
        "projectsNeedingUpdate": queue,
        "metricsWritten": {"projects": projects_written,
                           "people": people_written},
        "warnings": warnings,
    }
```

- [ ] **Step 4: Wire the CLI.** Import: add `updatequeue` to the `from vaultlib import ...` line. Parser (inside the existing `sync` group):

```python
    sync_queue = sync_sub.add_parser(
        "update-queue",
        help="write meeting metrics and list projects needing state synthesis")
    _add_vault_argument(sync_queue)
    sync_queue.add_argument("--executive", required=True,
                            help="the executive's person slug (excluded from key-people)")
    sync_queue.add_argument("--today", help="ISO date; defaults to today")
```

Dispatch (inside the `sync` branch):

```python
        if args.action == "update-queue":
            return _ok(updatequeue.run(root, vault.today_iso(args.today),
                                       args.executive))
```

Exception arm in `main` (before `ValueError`):

```python
    except updatequeue.UpdateQueueError as exc:
        return _fail(str(exc), "Fix the named argument and retry.")
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_markdown.py scripts/tests/test_vaultlib_updatequeue.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/markdown.py plugin/lib/vaultlib/updatequeue.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_markdown.py scripts/tests/test_vaultlib_updatequeue.py
git commit -m "feat: sync update-queue — metrics, project queue, reverse self-check

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `project touch` — the frontmatter side of a project-state update

**Files:**
- Modify: `plugin/lib/vaultlib/project.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_project.py`

**Interfaces:**
- Consumes: `markdown.upsert_scalar_field`, `vault.atomic_write`, `naming.validate_slug`, existing `project.ProjectError`.
- Produces: `project.touch(root, *, slug, date_iso, next_milestone=None, next_milestone_date=None) -> dict` returning `{"slug", "path", "last-updated", "next-milestone", "next-milestone-date", "changed"}`. CLI: `project touch --vault <path> --slug <slug> [--date YYYY-MM-DD] [--next-milestone "<one line>" --next-milestone-date YYYY-MM-DD]`. Rationale: stage-5 subagents rewrite the Now callout and `## Open Items` as body prose (model territory, via Edit), but frontmatter is never model-authored — this is the CLI half of that split.

- [ ] **Step 1: Write the failing tests** — append to `scripts/tests/test_vaultlib_project.py` (reuse that file's existing vault/scaffold helpers; if it has none suitable, build the minimal vault inline as below):

```python
def make_touch_vault(tmp_path):
    (tmp_path / "99-workflow-config").mkdir()
    folder = tmp_path / "30-projects" / "alpha"
    folder.mkdir(parents=True)
    (folder / "index.md").write_text("\n".join([
        "---", "type: project", 'project-name: "Alpha"', "slug: alpha",
        "status: active", "project-type: initiative", "entity: acme",
        "owner: exec-morgan", "created: 2026-01-01",
        "last-updated: 2026-06-01", "---", "",
        "> [!summary]+ **Now**", "> - Stage — running", "",
        "## Decisions", "", "## Open Items", "", "## Related Meetings", "",
    ]), encoding="utf-8")
    return tmp_path


def test_touch_bumps_last_updated_and_nothing_else(tmp_path):
    root = make_touch_vault(tmp_path)
    before = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    result = project.touch(root, slug="alpha", date_iso="2026-06-12")
    after = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert result["last-updated"] == "2026-06-12" and result["changed"] is True
    assert after == before.replace("last-updated: 2026-06-01",
                                   "last-updated: 2026-06-12")


def test_touch_upserts_the_milestone_pair(tmp_path):
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12",
                  next_milestone="Vendor contract signature",
                  next_milestone_date="2026-09-01")
    text = (root / "30-projects" / "alpha" / "index.md").read_text(encoding="utf-8")
    assert 'next-milestone: "Vendor contract signature"' in text
    assert "next-milestone-date: 2026-09-01" in text


def test_touch_milestone_fields_travel_together(tmp_path):
    root = make_touch_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="travel together"):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="Half a milestone")


def test_touch_is_idempotent(tmp_path):
    root = make_touch_vault(tmp_path)
    project.touch(root, slug="alpha", date_iso="2026-06-12")
    second = project.touch(root, slug="alpha", date_iso="2026-06-12")
    assert second["changed"] is False


def test_touch_rejects_unknown_project_and_bad_dates(tmp_path):
    root = make_touch_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="no project"):
        project.touch(root, slug="ghost", date_iso="2026-06-12")
    with pytest.raises(project.ProjectError):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="X", next_milestone_date="12-06-2026")
    with pytest.raises(project.ProjectError, match="single line"):
        project.touch(root, slug="alpha", date_iso="2026-06-12",
                      next_milestone="two\nlines",
                      next_milestone_date="2026-09-01")
```

(If the file does not already import `pytest` and `project`, add those imports.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_project.py -q -k touch`
Expected: FAIL — `AttributeError: ... no attribute 'touch'`.

- [ ] **Step 3: Implement** — append to `plugin/lib/vaultlib/project.py` (it already imports `markdown`, `naming`, `vault`; add `re` if absent):

```python
_ISO_DATE_ONLY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _require_iso_date(value, label: str) -> str:
    text = str(value or "").strip()
    if not _ISO_DATE_ONLY_RE.match(text):
        raise ProjectError(f"{label} {value!r} must be ISO YYYY-MM-DD")
    return text


def touch(root, *, slug: str, date_iso: str,
          next_milestone=None, next_milestone_date=None) -> dict:
    """Bump the auto-maintained frontmatter of a project-state update.

    Stage-5 subagents own the Now callout and Open Items as body prose; the
    frontmatter half comes through here so no model ever authors it. Only
    last-updated (and, together, the milestone pair) can change; every other
    byte of index.md stays put.
    """
    try:
        naming.validate_slug(str(slug or "").strip())
    except ValueError as exc:
        raise ProjectError(f"slug {slug!r}: {exc}") from exc
    index_path = root / "30-projects" / slug / "index.md"
    if not index_path.is_file():
        raise ProjectError(
            f"no project {slug!r} at 30-projects/{slug}/index.md — "
            "create it first with /new-project"
        )
    stamped = _require_iso_date(date_iso, "date")
    if (next_milestone is None) != (next_milestone_date is None):
        raise ProjectError(
            "next-milestone and next-milestone-date travel together — "
            "pass both or neither"
        )
    text = index_path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "last-updated", stamped)
    milestone = None
    milestone_date = None
    if next_milestone is not None:
        milestone = str(next_milestone).strip()
        if not milestone or "\n" in milestone:
            raise ProjectError("next-milestone must be a single line of text")
        milestone_date = _require_iso_date(next_milestone_date,
                                           "next-milestone-date")
        quoted = '"{}"'.format(milestone.replace('"', '\\"'))
        updated = markdown.upsert_scalar_field(updated, "next-milestone", quoted)
        updated = markdown.upsert_scalar_field(updated, "next-milestone-date",
                                               milestone_date)
    changed = updated != text
    if changed:
        vault.atomic_write(index_path, updated)
    return {
        "slug": slug,
        "path": f"30-projects/{slug}/index.md",
        "last-updated": stamped,
        "next-milestone": milestone,
        "next-milestone-date": milestone_date,
        "changed": changed,
    }
```

- [ ] **Step 4: Wire the CLI.** Parser (inside the existing `project` group, after `scaffold`):

```python
    proj_touch = projects_sub.add_parser(
        "touch", help="bump last-updated (and optionally the milestone pair)")
    _add_vault_argument(proj_touch)
    proj_touch.add_argument("--slug", required=True)
    proj_touch.add_argument("--date", help="ISO date; defaults to today")
    proj_touch.add_argument("--next-milestone", dest="next_milestone",
                            help="one line; requires --next-milestone-date")
    proj_touch.add_argument("--next-milestone-date", dest="next_milestone_date",
                            help="ISO date; requires --next-milestone")
```

Dispatch — the `project` branch currently assumes `scaffold`; make it branch:

```python
    if args.group == "project":
        if args.action == "touch":
            return _ok(project.touch(
                root, slug=args.slug, date_iso=vault.today_iso(args.date),
                next_milestone=args.next_milestone,
                next_milestone_date=args.next_milestone_date,
            ))
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(project.scaffold(
            root, name=args.name, project_type=args.project_type,
            entity=args.entity, owner=args.owner, today=today,
            parent=args.parent, stage=args.stage,
            contacts=args.contacts, source=args.source,
        ))
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_project.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/project.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_project.py
git commit -m "feat: project touch — the CLI half of a project-state update

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `daily-note write` — render and the marker-region merge

**Files:**
- Create: `plugin/lib/vaultlib/dailynote.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Modify: `plugin/CLAUDE.md` (new "Daily-note regions" section)
- Test: `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: `dates.DAY_NAMES`, `naming.validate_slug`, `vault.atomic_write`, `markdown.split_frontmatter` (Task 6).
- Produces: `dailynote.DailyNoteError`; `dailynote.NO_MEETINGS_LINE = "*No meetings scheduled.*"`; `dailynote.write(root: Path, payload: dict) -> dict` returning `{"path", "date", "day_name", "created", "regions_replaced", "changed"}`. Payload contract (consumed verbatim by the SKILL.md in Task 8):

```
required: date (ISO YYYY-MM-DD), recap (markdown string, no markers),
          meetings (list, possibly empty) of
            {time "HH:MM", subject (one line), entity (slug or null),
             prep (markdown string, no markers)}
optional: meetings_note (single line, only when meetings is empty —
          e.g. "*Calendar unavailable — check Outlook directly.*")
```

Semantics: fresh file → render the full contract (see "The daily-note contract" above). Existing file → replace region interiors ONLY, positionally per region name; region counts must match the payload (one recap; `len(meetings)` preps, or exactly one when meetings is empty) or the call fails with a structural-change error; marker lines and every byte outside regions are preserved exactly; a no-op payload leaves the file untouched (`changed: false`). CLI: `daily-note write --vault <path> --note <json path | ->`.

- [ ] **Step 1: Write the failing tests** — `scripts/tests/test_vaultlib_dailynote.py`:

```python
"""daily-note write/read: the machine half of the daily-note contract.

The CLI owns the marker-region merge; bytes outside markers are untouchable
(design decision 10) — pinned here by exact byte comparisons.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import dailynote

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "60-daily-notes").mkdir()
    folder = tmp_path / "40-entities" / "acme-industries"
    folder.mkdir(parents=True)
    (folder / "dossier.md").write_text(
        "---\ntype: entity\nentity-name: \"Acme\"\nslug: acme-industries\n"
        "status: active\n---\n", encoding="utf-8")
    return tmp_path


def payload(**overrides) -> dict:
    base = {
        "date": "2026-06-15",
        "recap": ("> [!info] At a glance\n"
                  "> 1 meeting Friday · quiet weekend ahead\n"
                  "- Recap bullet one."),
        "meetings": [
            {"time": "09:00", "subject": "Weekly Status",
             "entity": "acme-industries",
             "prep": "**Attendees:** Sam · **Last meeting:** 2026-06-08 · **Context:** cadence."},
            {"time": "14:00", "subject": "Deep dive — vendor scoring",
             "entity": None,
             "prep": "**Attendees:** Omar · **Last meeting:** none · **Context:** first session."},
        ],
    }
    base.update(overrides)
    return base


EXPECTED_FRESH = """---
date: 2026-06-15
type: daily-note
---

# 2026-06-15 · Monday

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> 1 meeting Friday · quiet weekend ahead
- Recap bullet one.
<!-- evening-sync:recap:end -->

## Meetings

### 09:00 — Weekly Status · [[acme-industries]]
<!-- evening-sync:prep:begin -->
**Attendees:** Sam · **Last meeting:** 2026-06-08 · **Context:** cadence.
<!-- evening-sync:prep:end -->
- 

### 14:00 — Deep dive — vendor scoring
<!-- evening-sync:prep:begin -->
**Attendees:** Omar · **Last meeting:** none · **Context:** first session.
<!-- evening-sync:prep:end -->
- 

## End of day
- 
"""


def test_fresh_render_matches_the_contract_exactly(tmp_path):
    root = make_vault(tmp_path)
    result = dailynote.write(root, payload())
    assert result["created"] is True
    assert result["day_name"] == "Monday"
    assert result["regions_replaced"] == 3
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert text == EXPECTED_FRESH


def test_empty_calendar_renders_the_no_meetings_region(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload(meetings=[]))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "### " not in text
    assert ("<!-- evening-sync:prep:begin -->\n*No meetings scheduled.*\n"
            "<!-- evening-sync:prep:end -->") in text


def test_meetings_note_replaces_the_default_line(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload(
        meetings=[], meetings_note="*Calendar unavailable — check Outlook directly.*"))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "*Calendar unavailable — check Outlook directly.*" in text
    with pytest.raises(dailynote.DailyNoteError, match="meetings_note"):
        dailynote.write(root, payload(meetings_note="x"))  # meetings non-empty


def test_merge_replaces_regions_and_preserves_every_other_byte(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    # The user jots into the note by hand — outside the markers.
    jotted = path.read_text(encoding="utf-8")
    jotted = jotted.replace(
        "<!-- evening-sync:prep:end -->\n- \n\n### 14:00",
        "<!-- evening-sync:prep:end -->\n- shortlist approved, log it\n\n### 14:00")
    jotted = jotted.replace("## End of day\n- \n",
                            "## End of day\n- long day; Meridian steady\n")
    path.write_text(jotted, encoding="utf-8")

    updated = payload()
    updated["recap"] = "- A completely regenerated recap."
    updated["meetings"][1]["prep"] = "**Attendees:** Omar, Taylor · fresh prep."
    result = dailynote.write(root, updated)
    assert result["created"] is False and result["changed"] is True
    text = path.read_text(encoding="utf-8")
    assert "- shortlist approved, log it" in text
    assert "- long day; Meridian steady" in text
    assert "- A completely regenerated recap." in text
    assert "fresh prep." in text
    # Byte-level pin: strip region interiors from both sides; the remainder
    # (markers included) must be identical.
    def skeleton(raw):
        lines, keep, inside = raw.split("\n"), [], False
        for line in lines:
            if line.startswith("<!-- evening-sync:") and line.endswith(":begin -->"):
                inside = True
                keep.append(line)
                continue
            if line.startswith("<!-- evening-sync:") and line.endswith(":end -->"):
                inside = False
            if not inside:
                keep.append(line)
        return "\n".join(keep)
    assert skeleton(text) == skeleton(jotted)


def test_merge_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    first = path.read_text(encoding="utf-8")
    result = dailynote.write(root, payload())
    assert result["changed"] is False
    assert path.read_text(encoding="utf-8") == first


def test_merge_refuses_a_structural_change(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())   # two meetings -> two prep regions
    smaller = payload()
    smaller["meetings"] = smaller["meetings"][:1]
    with pytest.raises(dailynote.DailyNoteError, match="structure"):
        dailynote.write(root, smaller)


def test_rejects_markers_inside_payload_content(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="markers"):
        dailynote.write(root, payload(
            recap="sneaky <!-- evening-sync:recap:end --> escape"))


def test_rejects_bad_time_unknown_entity_and_unknown_keys(tmp_path):
    root = make_vault(tmp_path)
    bad_time = payload()
    bad_time["meetings"][0]["time"] = "9am"
    with pytest.raises(dailynote.DailyNoteError, match="HH:MM"):
        dailynote.write(root, bad_time)
    bad_entity = payload()
    bad_entity["meetings"][0]["entity"] = "ghost-corp"
    with pytest.raises(dailynote.DailyNoteError, match="dossier"):
        dailynote.write(root, bad_entity)
    with pytest.raises(dailynote.DailyNoteError, match="unknown payload key"):
        dailynote.write(root, payload(extra="nope"))
    with pytest.raises(dailynote.DailyNoteError):
        dailynote.write(root, payload(date="15-06-2026"))


def test_cli_write_envelope(tmp_path):
    root = make_vault(tmp_path)
    note_file = tmp_path / "payload.json"
    note_file.write_text(json.dumps(payload()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "daily-note", "write",
         "--vault", str(root), "--note", str(note_file)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["result"]["path"] == "60-daily-notes/2026-06-15.md"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py -q`
Expected: FAIL — `ImportError: cannot import name 'dailynote'`.

- [ ] **Step 3: Implement** `plugin/lib/vaultlib/dailynote.py`:

```python
"""Daily notes: render the contract, merge the marker-fenced machine regions.

One daily artifact (design decision 1): the evening run writes tomorrow's
note. Machine content lives between <!-- evening-sync:{region}:begin/end -->
markers; this module regenerates region interiors wholesale and is forbidden
from touching a byte outside them (decision 10). One writer class per region.
A structural change (the meeting set differs from the note's prep regions) is
refused rather than guessed at — by then the note may hold human jottings,
and those outrank the calendar.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dates, markdown, naming, vault

DAILY_NOTES_DIR = "60-daily-notes"
NO_MEETINGS_LINE = "*No meetings scheduled.*"

_MARKER_RE = re.compile(r"\A<!-- evening-sync:([a-z-]+):(begin|end) -->\s*\Z")
_KNOWN_REGIONS = ("recap", "prep")
_ISO_DATE_ONLY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_TIME_RE = re.compile(r"\A([01]\d|2[0-3]):[0-5]\d\Z")
_HEADING_RE = re.compile(
    r"\A(\d{2}:\d{2}) — (.*?)(?: · \[\[([a-z0-9-]+)\]\])?\Z")
_ALLOWED_KEYS = ("date", "recap", "meetings", "meetings_note")
_ALLOWED_MEETING_KEYS = ("time", "subject", "entity", "prep")


class DailyNoteError(Exception):
    """A payload field or note state the caller must fix."""


def _require_date(raw) -> str:
    text = str(raw or "").strip()
    if not _ISO_DATE_ONLY_RE.match(text):
        raise DailyNoteError(f"date {raw!r} must be ISO YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise DailyNoteError(f"date {raw!r} is not a real date") from exc
    return text


def _day_name(date_iso: str) -> str:
    return dates.DAY_NAMES[datetime.strptime(date_iso, "%Y-%m-%d").weekday()]


def _clean_region_text(value, label: str) -> str:
    text = str(value or "").rstrip()
    if not text.strip():
        raise DailyNoteError(f"{label} must be a non-empty string")
    if "evening-sync:" in text:
        raise DailyNoteError(
            f"{label} must not contain region markers — the CLI writes those"
        )
    return text


def _validate(root: Path, payload) -> dict:
    if not isinstance(payload, dict):
        raise DailyNoteError("the payload must be a JSON object")
    unknown = sorted(set(payload) - set(_ALLOWED_KEYS))
    if unknown:
        raise DailyNoteError(f"unknown payload key(s) {unknown}")
    date_iso = _require_date(payload.get("date"))
    recap = _clean_region_text(payload.get("recap"), "recap")
    raw_meetings = payload.get("meetings")
    if not isinstance(raw_meetings, list):
        raise DailyNoteError("meetings must be a list (possibly empty)")
    meetings: List[dict] = []
    for position, entry in enumerate(raw_meetings, 1):
        if not isinstance(entry, dict):
            raise DailyNoteError(f"meeting {position}: must be an object")
        unknown_keys = sorted(set(entry) - set(_ALLOWED_MEETING_KEYS))
        if unknown_keys:
            raise DailyNoteError(
                f"meeting {position}: unknown key(s) {unknown_keys}")
        time_text = str(entry.get("time") or "").strip()
        if not _TIME_RE.match(time_text):
            raise DailyNoteError(
                f"meeting {position}: time {entry.get('time')!r} must be "
                "HH:MM (24h, local)")
        subject = str(entry.get("subject") or "").strip()
        if not subject or "\n" in subject or "evening-sync:" in subject:
            raise DailyNoteError(
                f"meeting {position}: subject must be one non-empty line "
                "without markers")
        entity = entry.get("entity")
        if entity is not None:
            entity = str(entity)
            try:
                naming.validate_slug(entity)
            except ValueError as exc:
                raise DailyNoteError(
                    f"meeting {position}: entity {entity!r}: {exc}") from exc
            if not (root / "40-entities" / entity / "dossier.md").is_file():
                raise DailyNoteError(
                    f"meeting {position}: entity {entity!r} has no dossier at "
                    f"40-entities/{entity}/dossier.md — pass null rather than "
                    "guessing")
        prep = _clean_region_text(entry.get("prep"),
                                  f"meeting {position} prep")
        meetings.append({"time": time_text, "subject": subject,
                         "entity": entity, "prep": prep})
    meetings_note = payload.get("meetings_note")
    if meetings_note is not None:
        if meetings:
            raise DailyNoteError(
                "meetings_note only applies when meetings is empty")
        meetings_note = _clean_region_text(meetings_note, "meetings_note")
        if "\n" in meetings_note:
            raise DailyNoteError("meetings_note must be a single line")
    return {"date": date_iso, "recap": recap, "meetings": meetings,
            "meetings_note": meetings_note}


def _region(name: str, content: str) -> str:
    return (f"<!-- evening-sync:{name}:begin -->\n{content}\n"
            f"<!-- evening-sync:{name}:end -->")


def _render(data: dict) -> str:
    date_iso = data["date"]
    parts = ["---", f"date: {date_iso}", "type: daily-note", "---", "",
             f"# {date_iso} · {_day_name(date_iso)}", "",
             "## Recap", _region("recap", data["recap"]), "",
             "## Meetings", ""]
    if data["meetings"]:
        chunks = []
        for meeting in data["meetings"]:
            heading = f"### {meeting['time']} — {meeting['subject']}"
            if meeting["entity"]:
                heading += f" · [[{meeting['entity']}]]"
            chunks.append("\n".join([heading,
                                     _region("prep", meeting["prep"]), "- "]))
        parts.append("\n\n".join(chunks))
    else:
        parts.append(_region("prep",
                             data["meetings_note"] or NO_MEETINGS_LINE))
    parts += ["", "## End of day", "- ", ""]
    return "\n".join(parts)


def _find_regions(lines: List[str]) -> List[dict]:
    regions: List[dict] = []
    open_marker: Optional[Tuple[str, int]] = None
    for index, line in enumerate(lines):
        match = _MARKER_RE.match(line)
        if not match:
            continue
        name, kind = match.group(1), match.group(2)
        if name not in _KNOWN_REGIONS:
            raise DailyNoteError(
                f"unknown region {name!r} at line {index + 1}; "
                f"known regions: {_KNOWN_REGIONS}")
        if kind == "begin":
            if open_marker is not None:
                raise DailyNoteError(
                    f"nested region marker at line {index + 1}")
            open_marker = (name, index)
        else:
            if open_marker is None or open_marker[0] != name:
                raise DailyNoteError(
                    f"unmatched end marker for {name!r} at line {index + 1}")
            regions.append({"name": name, "begin": open_marker[1],
                            "end": index})
            open_marker = None
    if open_marker is not None:
        raise DailyNoteError(f"region {open_marker[0]!r} is never closed")
    return regions


def _merge(text: str, data: dict) -> Tuple[str, int]:
    lines = text.split("\n")
    regions = _find_regions(lines)
    recaps = [r for r in regions if r["name"] == "recap"]
    preps = [r for r in regions if r["name"] == "prep"]
    if len(recaps) != 1:
        raise DailyNoteError(
            f"expected exactly one recap region, found {len(recaps)}")
    expected_preps = len(data["meetings"]) if data["meetings"] else 1
    if len(preps) != expected_preps:
        raise DailyNoteError(
            f"the note has {len(preps)} prep region(s) but the payload "
            f"carries {expected_preps} — the meeting structure changed since "
            "this note was written. Only region interiors are replaced and "
            "bytes outside markers are never touched, so a structural change "
            "needs a human (or a fresh note)."
        )
    prep_contents = ([m["prep"] for m in data["meetings"]]
                     if data["meetings"]
                     else [data["meetings_note"] or NO_MEETINGS_LINE])
    replacements: Dict[int, Tuple[dict, str]] = {
        recaps[0]["begin"]: (recaps[0], data["recap"])}
    for region, content in zip(preps, prep_contents):
        replacements[region["begin"]] = (region, content)
    out: List[str] = []
    index = 0
    while index < len(lines):
        if index in replacements:
            region, content = replacements[index]
            out.append(lines[region["begin"]])
            out.extend(content.split("\n"))
            out.append(lines[region["end"]])
            index = region["end"] + 1
        else:
            out.append(lines[index])
            index += 1
    return "\n".join(out), len(replacements)


def write(root: Path, payload) -> dict:
    data = _validate(root, payload)
    path = root / DAILY_NOTES_DIR / f"{data['date']}.md"
    if path.is_file():
        original = path.read_text(encoding="utf-8")
        merged, replaced = _merge(original, data)
        changed = merged != original
        if changed:
            vault.atomic_write(path, merged)
        created = False
    else:
        merged = _render(data)
        replaced = 1 + (len(data["meetings"]) or 1)
        changed, created = True, True
        vault.atomic_write(path, merged)
    return {
        "path": f"{DAILY_NOTES_DIR}/{data['date']}.md",
        "date": data["date"],
        "day_name": _day_name(data["date"]),
        "created": created,
        "regions_replaced": replaced,
        "changed": changed,
    }
```

- [ ] **Step 4: Wire the CLI and document the contract.** Import: add `dailynote` to the `from vaultlib import ...` line. Parser:

```python
    daily = top.add_parser("daily-note",
                           help="daily notes: region write and harvest read")
    daily_sub = daily.add_subparsers(dest="action", required=True)
    daily_write = daily_sub.add_parser(
        "write", help="render or region-merge one daily note from a JSON payload")
    _add_vault_argument(daily_write)
    daily_write.add_argument("--note", required=True,
                             help="path to a JSON file, or - to read stdin")
    daily_read = daily_sub.add_parser(
        "read", help="parse a daily note into regions and human jottings")
    _add_vault_argument(daily_read)
    daily_read.add_argument("--date", required=True, help="ISO date of the note")
```

Dispatch:

```python
    if args.group == "daily-note":
        if args.action == "write":
            payload = (json.load(sys.stdin) if args.note == "-"
                       else json.loads(Path(args.note).read_text(encoding="utf-8")))
            return _ok(dailynote.write(root, payload))
        return _ok(dailynote.read(root, args.date))
```

(`dailynote.read` lands in Task 6 — add a one-line placeholder is NOT allowed; instead wire only `write` in this task and add the `read` parser+dispatch lines in Task 6. Concretely: in this task add the `daily` group with only the `write` action; Task 6 appends the `read` parser and the read dispatch branch.)

Exception arm in `main` (before `ValueError`):

```python
    except dailynote.DailyNoteError as exc:
        return _fail(str(exc), "Fix the named payload field or note state and retry.")
```

Append to `plugin/CLAUDE.md`:

```markdown
## Daily-note regions

`daily-note write` owns the machine half of a daily note. The payload carries
region *content* only — never the `<!-- evening-sync:{region}:begin/end -->`
markers, which the CLI writes and refuses to accept inside content. On an
existing note, region interiors are replaced in place and every byte outside
the markers is preserved exactly; jottings are the user's, permanently. The
region structure must match the payload (one recap; one prep per meeting, or
a single no-meetings prep) — if the meeting set changed since the note was
written, the write fails with a structural-change error instead of guessing,
because by then the note may hold human text that outranks the calendar.
Surface that error; do not delete the note to force a rewrite unless the user
says so.
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_vaultlib_cli.py -q -k "not read"`
Expected: PASS (read tests come in Task 6).

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py plugin/lib/vaultlib/cli.py plugin/CLAUDE.md scripts/tests/test_vaultlib_dailynote.py
git commit -m "feat: daily-note write — contract render and marker-region merge

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `daily-note read` — the harvest parser

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py`
- Modify: `plugin/lib/vaultlib/cli.py` (the `read` parser + dispatch lines deferred from Task 5)
- Test: `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter`, Task 5's `_find_regions`, `_require_date`, `_HEADING_RE`.
- Produces: `dailynote.read(root: Path, date_iso: str) -> dict` — `{"exists": false, "path"}` when the note is absent (a normal first-run state, not an error), else `{"exists": true, "path", "date", "frontmatter", "recap" (region content or null), "meetings": [{heading, time, subject, entity, prep, jottings}], "end_of_day": [...], "other_lines": [...], "warnings": [...]}`. Jottings and end-of-day entries are bullet text with the `- ` prefix stripped; the empty `- ` affordance is dropped. Task 8's harvest stage consumes this.

- [ ] **Step 1: Write the failing tests** — append to `scripts/tests/test_vaultlib_dailynote.py`:

```python
def jotted_note_text() -> str:
    return """---
date: 2026-06-12
type: daily-note
---

# 2026-06-12 · Friday

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> recap content here
<!-- evening-sync:recap:end -->

## Meetings

### 10:00 — 1:1 — Jordan Vance · [[acme-industries]]
<!-- evening-sync:prep:begin -->
**Attendees:** Jordan Vance · **Context:** rollout proposal.
<!-- evening-sync:prep:end -->
- Proposal on track for September submission.
- 

## End of day
- Follow up with Dana next week.
"""


def test_read_extracts_regions_meetings_and_jottings(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        jotted_note_text(), encoding="utf-8")
    result = dailynote.read(root, "2026-06-12")
    assert result["exists"] is True
    assert result["frontmatter"]["type"] == "daily-note"
    assert result["recap"].startswith("> [!info] At a glance")
    assert len(result["meetings"]) == 1
    meeting = result["meetings"][0]
    assert meeting["time"] == "10:00"
    assert meeting["subject"] == "1:1 — Jordan Vance"
    assert meeting["entity"] == "acme-industries"
    assert meeting["prep"].startswith("**Attendees:** Jordan Vance")
    # The empty '- ' affordance is dropped; the real jotting survives.
    assert meeting["jottings"] == ["Proposal on track for September submission."]
    assert result["end_of_day"] == ["Follow up with Dana next week."]
    assert result["warnings"] == []


def test_read_on_a_missing_note_is_a_normal_state(tmp_path):
    root = make_vault(tmp_path)
    result = dailynote.read(root, "2026-06-12")
    assert result == {"exists": False, "path": "60-daily-notes/2026-06-12.md"}


def test_read_tolerates_a_hand_written_note_without_markers(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        "---\ndate: 2026-06-12\ntype: daily-note\n---\n\n"
        "# 2026-06-12 · Friday\n\n## Recap\n- hand recap line\n\n"
        "## Meetings\n\n## End of day\n- wrap up\n", encoding="utf-8")
    result = dailynote.read(root, "2026-06-12")
    assert result["recap"] is None
    assert result["meetings"] == []
    assert result["end_of_day"] == ["wrap up"]
    assert "hand recap line" in result["other_lines"]


def test_read_parses_every_daily_note_fixture():
    for path in sorted((FIXTURE_ROOT / "60-daily-notes").glob("*.md")):
        result = dailynote.read(FIXTURE_ROOT, path.stem)
        assert result["exists"] is True
        assert result["recap"], f"{path}: fixture recap region is empty"


def test_cli_read_envelope(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        jotted_note_text(), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "daily-note", "read",
         "--vault", str(root), "--date", "2026-06-12"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["result"]["meetings"][0]["jottings"] == [
        "Proposal on track for September submission."]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py -q -k read`
Expected: FAIL — `AttributeError: ... no attribute 'read'`.

- [ ] **Step 3: Implement** — append to `plugin/lib/vaultlib/dailynote.py`:

```python
def _frontmatter_end_line(lines: List[str]) -> int:
    """Index of the closing '---' fence line, or -1 if none."""
    if not lines or lines[0].strip() != "---":
        return -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index
    return -1


def read(root: Path, date_iso_raw) -> dict:
    """Parse a daily note into machine regions and human jottings.

    Read-only by design (decision 8): the note is the archive of the day.
    A missing note is a normal state — the first run of a fresh vault — not
    an error. A hand-written note without markers is tolerated: everything
    is human text then, and recap comes back null.
    """
    date_iso = _require_date(date_iso_raw)
    rel = f"{DAILY_NOTES_DIR}/{date_iso}.md"
    path = root / DAILY_NOTES_DIR / f"{date_iso}.md"
    if not path.is_file():
        return {"exists": False, "path": rel}
    text = path.read_text(encoding="utf-8")
    warnings: List[str] = []
    try:
        frontmatter, _ = markdown.split_frontmatter(text)
    except ValueError as exc:
        frontmatter = {}
        warnings.append(f"{rel}: {exc}")

    lines = text.split("\n")
    regions = _find_regions(lines)
    region_lines = set()
    for region in regions:
        region_lines.update(range(region["begin"], region["end"] + 1))
    recap = None
    recap_regions = [r for r in regions if r["name"] == "recap"]
    if recap_regions:
        region = recap_regions[0]
        recap = "\n".join(lines[region["begin"] + 1:region["end"]])
    prep_by_begin = {r["begin"]: "\n".join(lines[r["begin"] + 1:r["end"]])
                     for r in regions if r["name"] == "prep"}

    meetings: List[dict] = []
    end_of_day: List[str] = []
    other_lines: List[str] = []
    current: Optional[dict] = None
    section = ""
    fm_end = _frontmatter_end_line(lines)
    for index, line in enumerate(lines):
        if index <= fm_end:
            continue
        if index in region_lines:
            if current is not None and index in prep_by_begin:
                current["prep"] = prep_by_begin[index]
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        if line.startswith("# "):
            continue
        if section == "Meetings" and line.startswith("### "):
            heading = line[4:].strip()
            match = _HEADING_RE.match(heading)
            current = {
                "heading": heading,
                "time": match.group(1) if match else None,
                "subject": match.group(2) if match else heading,
                "entity": match.group(3) if match else None,
                "prep": None,
                "jottings": [],
            }
            meetings.append(current)
            continue
        stripped = line.strip()
        if not stripped:
            continue
        content = stripped[2:].strip() if stripped.startswith("- ") else (
            "" if stripped == "-" else stripped)
        if not content:
            continue   # the empty '- ' jot affordance
        if section == "End of day":
            end_of_day.append(content)
        elif section == "Meetings" and current is not None:
            current["jottings"].append(content)
        else:
            other_lines.append(content)
    return {
        "exists": True, "path": rel, "date": date_iso,
        "frontmatter": frontmatter, "recap": recap, "meetings": meetings,
        "end_of_day": end_of_day, "other_lines": other_lines,
        "warnings": warnings,
    }
```

Then add the `daily_read` parser lines and the read dispatch branch exactly as written in Task 5 Step 4 (they were deferred to here).

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_vaultlib_cli.py scripts/tests/test_skill_contracts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "feat: daily-note read — regions and jottings for the harvest stage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Fixture enrichment — the conflict sibling, the fresh note, honest metrics

**Files:**
- Create: `fixtures/demo-vault/20-meetings/12-06-26-jordan-1on1-v2.md` (via the CLI, not by hand)
- Create: `fixtures/demo-vault/60-daily-notes/2026-06-15.md` (via the CLI, not by hand)
- Modify: `fixtures/demo-vault/30-projects/{4 active}/index.md`, `fixtures/demo-vault/50-people/*.md` (metric re-stamps, via the CLI)
- Test: `scripts/tests/test_fixtures_ontology.py`, `scripts/tests/test_vaultlib_updatequeue.py`, `scripts/tests/test_vaultlib_dailynote.py`

**Interfaces:**
- Consumes: `meeting.write` (P2a), `updatequeue.run` (Task 3), `dailynote.write` (Task 5).
- Produces: the fixture vault as a converged evening-run snapshot at story date **2026-06-12** (the Friday run just finished: metrics fresh, queue empty, Monday's note written). Closes both P2a parked items: a `conflicts-with` fixture and coherent metric stamps.

Story: on Friday 2026-06-12 evening, the run synced a duplicate recorder capture of the confirmed 1:1 — the collision guard wrote the `-v2` `needs-attention` sibling instead of touching the confirmed note — refreshed metrics (`--today 2026-06-12`, executive `morgan-ellery`), and wrote Monday's note (empty calendar). Metric zeros are the truthful consequence of confirmed-only counting: only 3 of 9 meetings are confirmed (2026-03-10, 2026-04-15, 2026-06-12), so most 7d/30d counts are 0 and the triage backlog *is* the fixture story.

- [ ] **Step 1: Write the failing tests.** Append to `scripts/tests/test_fixtures_ontology.py`:

```python
def test_conflict_sibling_fixture_exercises_conflicts_with():
    """P2a parked item: the collision-guard output shape, on disk."""
    carriers = []
    stems = {p.stem for p in iter_fixture_files(SCHEMAS["meeting"]["glob"])}
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        fm = parse_frontmatter(path)
        raw = fm.get("conflicts-with")
        if raw in (None, ""):
            continue
        carriers.append(path)
        match = WIKILINK_RE.match(str(raw).strip())
        assert match, f"{path}: conflicts-with must be a quoted wikilink"
        assert match.group(1) in stems, (
            f"{path}: conflicts-with target {match.group(1)!r} is not a fixture"
        )
        assert fm["review_status"] == "needs-attention", (
            f"{path}: conflicts-with appears only on needs-attention siblings"
        )
    assert carriers, "expected at least one conflicts-with fixture"


def test_recording_id_namespaces_are_covered():
    seen = set()
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        rid = parse_frontmatter(path).get("source-recording-id")
        if rid:
            seen.add(str(rid).split(":", 1)[0])
    assert {"inbox", "plaud"} <= seen, (
        f"fixtures should cover the shipping id namespaces; found {seen}"
    )
```

Append to `scripts/tests/test_vaultlib_updatequeue.py`:

```python
import shutil

FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"


def copy_fixture_vault(tmp_path: Path) -> Path:
    target = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def test_fixture_vault_is_a_fixed_point_of_update_queue(tmp_path):
    """The demo vault is a converged evening-run snapshot at 2026-06-12: the
    checked-in metric stamps ARE update-queue's output, so a run changes
    nothing. This pins metric arithmetic against real fixture data AND keeps
    the stamps honest (P2a lesson: fixture stamps must survive scrutiny)."""
    root = copy_fixture_vault(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    result = updatequeue.run(root, today="2026-06-12",
                             executive="morgan-ellery")
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
    assert after == before
    assert result["meetingsIndexed"] == 9
    assert result["confirmedMeetings"] == 3
    assert result["projectsNeedingUpdate"] == []
    assert result["warnings"] == []
    assert result["metricsWritten"] == {"projects": 4, "people": 10}
```

Append to `scripts/tests/test_vaultlib_dailynote.py`:

```python
import shutil


FRESH_FIXTURE_PAYLOAD = {
    "date": "2026-06-15",
    "recap": (
        "> [!info] At a glance\n"
        "> 1 meeting Friday · Nordbridge Components · 1 duplicate capture flagged\n"
        "- [[12-06-26-jordan-1on1]] — proposal drafting on track for September submission.\n"
        "- Duplicate recorder capture written as [[12-06-26-jordan-1on1-v2]] — needs attention in triage.\n"
        "- Jotting carried forward: follow up with Dana Whitfield on rollout scope this week."
    ),
    "meetings": [],
}


def test_fresh_fixture_is_exactly_what_daily_note_write_renders(tmp_path):
    """60-daily-notes/2026-06-15.md is the just-written artifact of the
    2026-06-12 evening run — pinned byte-for-byte to the renderer."""
    target = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, target)
    fixture_path = target / "60-daily-notes" / "2026-06-15.md"
    expected = fixture_path.read_text(encoding="utf-8")
    fixture_path.unlink()
    dailynote.write(target, dict(FRESH_FIXTURE_PAYLOAD))
    assert fixture_path.read_text(encoding="utf-8") == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py scripts/tests/test_vaultlib_updatequeue.py scripts/tests/test_vaultlib_dailynote.py -q`
Expected: FAIL — no conflicts-with fixture; no plaud namespace; fixed-point test finds changed bytes / meetingsIndexed 8; missing 2026-06-15.md.

- [ ] **Step 3: Generate the conflict sibling via the CLI.** Copy the fixture vault to scratch and run `meeting write` with a payload that collides with the confirmed 1:1:

```bash
SCRATCH=$(mktemp -d)
cp -R fixtures/demo-vault "$SCRATCH/vault"
cat > "$SCRATCH/v2.payload.json" <<'JSON'
{
  "title": "jordan 1on1",
  "date": "2026-06-12T10:00",
  "type": "1:1",
  "calendar-subject": "1:1 — Jordan Vance",
  "calendar_match": true,
  "organizer": "jordan-vance",
  "location": "Microsoft Teams",
  "recurring": true,
  "attendee-emails": ["jordan.vance@cascadia-intermodal.example", "morgan.ellery@cascadia-intermodal.example"],
  "attendees": ["jordan-vance", "morgan-ellery"],
  "projects": ["nordbridge-regional-rollout-proposal"],
  "recording-duration": 21,
  "source": "recorder",
  "source-recording-id": "plaud:d41e9f27c3a85b60",
  "source-filename": "REC-2026-0612-1002.m4a",
  "confidence": "high",
  "confidence-reasons": ["calendar-match-high", "entity-domain-match", "all-attendees-known"],
  "takeaways": ["Regional rollout proposal drafting on track for September submission.", "Dana Whitfield confirmed as the procurement contact for scoping."],
  "debrief": "### Rollout proposal status\nSame 1:1 as the confirmed Teams capture — the recorder ran in parallel. Jordan confirmed the September submission target and flagged that Dana Whitfield owns procurement scoping on the Nordbridge side.",
  "action-items": ["**Morgan Ellery** — follow up with Dana Whitfield on rollout scope"]
}
JSON
python3 plugin/lib/vaultlib/cli.py meeting write --vault "$SCRATCH/vault" --note "$SCRATCH/v2.payload.json"
cp "$SCRATCH/vault/20-meetings/12-06-26-jordan-1on1-v2.md" fixtures/demo-vault/20-meetings/
```

Verify the result JSON reports a `confirmed-target` conflict and the copied file carries `review_status: needs-attention` and `conflicts-with: "[[12-06-26-jordan-1on1]]"`. If the payload key set above mismatches what `meeting.write` accepts (check `plugin/lib/vaultlib/meeting.py` REQUIRED/OPTIONAL if it errors), adjust the payload — never hand-edit the emitted file except to remove nothing: the fixture must be the CLI's exact output. Also verify `start-time` handling: if `meeting.write` derives or requires it, keep whatever the CLI emits.

- [ ] **Step 4: Re-stamp metrics via the CLI.** In the same scratch vault (which now has the `-v2` file):

```bash
python3 plugin/lib/vaultlib/cli.py sync update-queue --vault "$SCRATCH/vault" --today 2026-06-12 --executive morgan-ellery
cp "$SCRATCH/vault/30-projects/commercial-ops-crm-modernization/index.md" fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/
cp "$SCRATCH/vault/30-projects/commercial-ops-pipeline-governance/index.md" fixtures/demo-vault/30-projects/commercial-ops-pipeline-governance/
cp "$SCRATCH/vault/30-projects/meridian-yard-automation-program/index.md" fixtures/demo-vault/30-projects/meridian-yard-automation-program/
cp "$SCRATCH/vault/30-projects/nordbridge-regional-rollout-proposal/index.md" fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/
cp "$SCRATCH/vault/50-people/"*.md fixtures/demo-vault/50-people/
```

Expected stamps (verify with `git diff` — these are the confirmed-only truths at 2026-06-12):
- crm-modernization: `meetings-7d: 0`, `meetings-30d: 0`, `key-people: []`
- pipeline-governance: `0`, `0`, `key-people: []`
- meridian-yard-automation-program: `0`, `0`, `key-people: [priya-nathan]`
- nordbridge-regional-rollout-proposal: `1`, `1`, `key-people: [jordan-vance]`
- warehouse-pilot (completed): untouched
- people: `jordan-vance` and `morgan-ellery` get `1`/`1`; everyone else `0`/`0`

- [ ] **Step 5: Generate the fresh Monday note via the CLI.** Write `FRESH_FIXTURE_PAYLOAD` (exact content from Step 1's test) to a JSON file and run:

```bash
python3 - <<'PY'
import json, pathlib
payload = {
    "date": "2026-06-15",
    "recap": (
        "> [!info] At a glance\n"
        "> 1 meeting Friday · Nordbridge Components · 1 duplicate capture flagged\n"
        "- [[12-06-26-jordan-1on1]] — proposal drafting on track for September submission.\n"
        "- Duplicate recorder capture written as [[12-06-26-jordan-1on1-v2]] — needs attention in triage.\n"
        "- Jotting carried forward: follow up with Dana Whitfield on rollout scope this week."
    ),
    "meetings": [],
}
pathlib.Path("/tmp/dn.payload.json").write_text(json.dumps(payload), encoding="utf-8")
PY
python3 plugin/lib/vaultlib/cli.py daily-note write --vault fixtures/demo-vault --note /tmp/dn.payload.json
```

(This writes directly into the fixture vault — intended, it becomes the checked-in fixture.)

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest scripts/tests -q && python3 scripts/lint_plugin.py && python3 scripts/validate_template.py`
Expected: all pass — including the Task 1 daily-note harness on the new 06-15 note (4 fixtures now), meeting minimums/coverage on 9 meetings, and the new fixed-point and byte-equality tests.

- [ ] **Step 7: Commit**

```bash
git add fixtures/demo-vault scripts/tests/test_fixtures_ontology.py scripts/tests/test_vaultlib_updatequeue.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "test: fixture vault as a converged evening-run snapshot at 2026-06-12

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: `/evening-sync` SKILL.md, changelog, version 0.4.0

**Files:**
- Create: `plugin/skills/evening-sync/SKILL.md`
- Modify: `plugin/.claude-plugin/plugin.json` (0.3.0 → 0.4.0)
- Modify: `scripts/tests/test_marketplace_manifest.py` (version pin)
- Modify: `scripts/tests/test_skill_contracts.py` (expected set)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: every subcommand from Tasks 2–6 plus P2a's skill and P1b's `/log-decision --background`. `test_every_cli_invocation_named_by_a_skill_exists` will verify each `"$VAULTLIB" <group> <action>` reference against the real parser.
- Produces: the shipped engine.

- [ ] **Step 1: Write the failing tests.** In `scripts/tests/test_skill_contracts.py`, extend `test_expected_skills_exist`'s set to `{"new-project", "update-entity", "log-decision", "sync-recordings", "evening-sync"}`. In `scripts/tests/test_marketplace_manifest.py`, change the pinned version in `test_plugin_version_is_bumped_for_this_release` to `"0.4.0"`.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py scripts/tests/test_marketplace_manifest.py -q`
Expected: FAIL — evening-sync missing; version still 0.3.0.

- [ ] **Step 3: Bump the version.** In `plugin/.claude-plugin/plugin.json`: `"version": "0.4.0"`.

- [ ] **Step 4: Write the skill** — `plugin/skills/evening-sync/SKILL.md`, exactly:

````markdown
---
name: evening-sync
description: Run the evening pipeline — sync recordings, fold review ticks, refresh project metrics, update project state, capture decisions, and write tomorrow's daily note. Triggers when the user invokes /evening-sync or asks to run the evening sync or prepare tomorrow's note.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Evening Sync

The engine of the daily loop. One run harvests today's jottings, syncs new
recordings, refreshes project metrics, updates the state of projects with new
confirmed meetings, captures decisions for review, and writes **tomorrow's**
daily note — a recap of today plus a prepared section per upcoming meeting.
Deterministic stages are CLI subcommands; judgment (recap prose, themes,
project-state synthesis, decision candidates) is yours.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say so
plainly rather than assembling a note by hand.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure surface `error` and `hint`.

## Usage

```
/evening-sync                    # interactive: one confirmation at the sync stage
/evening-sync --unattended       # scheduled shape — never prompts, ever
```

Stages are **failure-isolated**: a failed stage logs its error into the final
summary and the chain continues. A crashed calendar still gets a daily note;
a failed sync still gets metrics and project updates.

## Stage 1 — Dates (authoritative, never re-derived)

Read the executive's timezone from
`99-workflow-config/context/identity.md` (IANA name in prose), then:

```bash
python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <executive-timezone>
```

Consume the result **verbatim** — `today`, `next_business_day`, the day
names, `recap_from`/`recap_to`, `last_daily_note`, `note_to_write`. Never
derive day-of-week or date arithmetic yourself; that is the bug class this
subcommand exists to kill. The recap window is *everything since the last
daily note*: after a missed run or a gap, it widens automatically — no
weekend special case.

Also resolve the executive's **person slug**: their name is in the identity
block; the matching note is in `50-people/` (its `person-name`). Stage 3
needs the slug.

## Stage 2 — Harvest (read-only)

```bash
python3 "$VAULTLIB" daily-note read --vault "$VAULT" --date <recap_from>
```

`exists: false` is a normal first-run state — note it and move on. Otherwise
collect per-meeting `jottings` and `end_of_day` bullets: they are context for
the recap (stage 6) and decision candidates (stage 4). The note itself is the
archive of the day — **never modify it**, and never route jottings into other
notes; in v1 they inform, nothing more.

## Stage 3 — Sync, refresh

**Sync:** run the `/sync-recordings` workflow (follow
`plugin/skills/sync-recordings/SKILL.md`) — unattended when this run is
unattended, interactive otherwise. Its step 1 already runs
`sync reconcile-reviews`, which IS this pipeline's reconcile stage — do not
run it a second time. Record what it reports: synced stems, folded ticks,
conflicts, per-adapter lines.

**Refresh:**

```bash
python3 "$VAULTLIB" sync update-queue --vault "$VAULT" --today <today> --executive <exec-slug>
```

This writes `meetings-7d` / `meetings-30d` / `key-people` on active projects
and `meetings-7d` / `meetings-30d` on people (confirmed meetings only — the
review queue is the quality gate), and returns `projectsNeedingUpdate`: each
entry carries `indexPath`, `decisionsDir`, `lastUpdated`, `newFiles`, and the
`existingDecisions` projection. Carry `warnings` — especially `SELF-CHECK`
lines — into the final summary verbatim.

## Stage 4 — Project-state updates

If the queue is empty, record "no projects to update" and skip to stage 6.
Otherwise, per queued project, dispatch a subagent (up to 3 in parallel) with
the queue entry, the harvest jottings that mention the project, today's date,
and these instructions:

1. Read the `newFiles` meetings end-to-end — Key Takeaways, Debrief, Action
   Items.
2. Rewrite the `> [!summary]+ **Now**` callout in `indexPath` — **exactly 5
   bullets**: Stage · Defining decision (wikilink) · Next event · Owe ·
   Watch. Rewrite `## Open Items` (add new, remove resolved — vocabulary:
   📤 Owe · 👤 Awaiting · ❓ Question · ⏳ Pending). Touch **nothing else in
   the body** — the Dataview blocks render themselves.
3. Frontmatter goes through the CLI, never your editor:

```bash
python3 "$VAULTLIB" project touch --vault "$VAULT" --slug <slug> --date <today> --next-milestone "<one line>" --next-milestone-date <ISO>
```

   (Omit the milestone pair when no concrete next event was identified.)
4. Decision capture: extract candidates from the new meetings AND the
   harvest jottings, then follow
   `plugin/skills/log-decision/SKILL.md` in **background mode**
   (`/log-decision <slug> --background`) with those candidates as the
   source. Its rules apply unchanged: the material-decision test (commits
   the engagement AND changes a stakeholder's behaviour), dedup against
   `existingDecisions`, supersession only on explicit conflict language,
   never delete, status flips only. Writing nothing is a valid outcome.
5. Return a fenced JSON block: `{"slug", "indexUpdated": bool,
   "decisionsWritten": [stems], "decisionsSkipped": N, "notes"}`. A subagent
   that fails or returns no block becomes a warning, not a retry.

Projects with only `needs-review` meetings never reach the queue — do not
"help" one by confirming meetings yourself.

## Stage 5 — Tomorrow's calendar and prep

If the Microsoft 365 calendar tool is available (ToolSearch
`outlook_calendar_search`), pull `next_business_day`'s events; compute the
query window deterministically:

```bash
python3 "$VAULTLIB" dates window --start <next_business_day> --timezone <tz> --hours 0
```

Filter out all-day and cancelled events; sort by start time; render times in
the executive's local timezone. For each event, build one prep line —
**Attendees:** names · **Last meeting:** date + one-liner · **Context:** one
line from the entity dossier and the project's Now callout. The lookups:
match attendee email domains and subject keywords against `40-entities/*/`
and active projects in `30-projects/*/index.md` (same signals, same order,
as `/sync-recordings` step 3); read the matched dossier and the most recent
meeting note for that entity or project. No match → no entity suffix and a
prep line from the event alone.

Calendar tool missing or erroring → `meetings: []` with
`meetings_note: "*Calendar unavailable — meetings could not be prepped.*"`.
The note is still written. "Couldn't look" is not "looked and found
nothing" — say which one happened in the summary.

## Stage 6 — Write tomorrow's note

Compose the recap from: the recap window's meetings (everything in
`20-meetings/` dated within `recap_from`..`recap_to` — takeaway one-liners,
entities, themes when there are ≥2 meetings), decisions written in stage 4,
harvest jottings worth carrying forward, and watch items (conflicts,
needs-attention flags, self-check warnings). Respect the language and depth
preferences in `99-workflow-config/context/preferences-and-constraints.md`.
Open items live on projects — link them, never duplicate a task list.

```bash
cat > "$SCRATCH/daily-note.payload.json" <<'JSON'
{
  "date": "<next_business_day>",
  "recap": "> [!info] At a glance\n> {N meetings · entities · themes}\n- {takeaway bullets, decisions logged, watch items}",
  "meetings": [
    {"time": "09:00", "subject": "Weekly Status", "entity": "acme-industries",
     "prep": "**Attendees:** … · **Last meeting:** … · **Context:** …"}
  ]
}
JSON
python3 "$VAULTLIB" daily-note write --vault "$VAULT" --note "$SCRATCH/daily-note.payload.json"
```

The CLI renders the contract on a fresh note and region-merges on an
existing one — your payload carries content only, never markers. A
`structure changed` error means the note already exists with a different
meeting set: report it and leave the note alone (it may hold human
jottings); do not delete it to force a rewrite.

## Stage 7 — Verify against disk, then summarize

Counts come from what exists, not from what you intended (a lab run once
reported "Processed: 0" after writing a meeting correctly):

- tomorrow's note exists at `note_to_write` with a fresh mtime;
- every project reported updated shows today's `last-updated` in its
  frontmatter;
- every recording reported synced has its stem in `20-meetings/`.

```
## Evening Sync Complete
**Synced:** {N} recordings → `20-meetings/` ({stems})
**Reviewed ticks folded:** {N} confirmed
**Metrics refreshed:** {P} projects · {Q} people
**Projects updated:** {N} ({slugs}) — {M} decisions written (reviewed: false), {K} candidates skipped
**Tomorrow's note:** `60-daily-notes/{date}.md` ({DayName}) — {N} meetings prepped | calendar unavailable
**Warnings:** {verbatim, including SELF-CHECK lines} | none
```

A non-empty warnings block means investigate before tomorrow's run.

## Unattended mode

`--unattended` is what a scheduled run passes. Non-negotiable:

1. **Never ask a question.** A blocked prompt means the run exits having
   done nothing. Ambiguity → skip that item, report it, let it retry next
   run.
2. **Decision capture is always `--background`** (writes `reviewed: false`
   for the Decisions.base review queue).
3. **Prefer under-doing to wrong-doing.** No confident project match, no
   confident prep — leave it out and say so.

## Rules

1. **Consume `dates plan` verbatim.** No day-of-week or window arithmetic
   outside the CLI.
2. **Harvest is read-only.** Today's note is never modified.
3. **Only confirmed meetings drive metrics and project updates.**
4. **Frontmatter is never model-authored.** `project touch`, `decision
   write`, `meeting write`, `daily-note write` — those are the writers.
5. **Bytes outside daily-note markers are the user's.** The CLI enforces
   it; never work around a structure error.
6. **Supersession needs explicit conflict language; never delete a
   decision.** Status flips only.
7. **Calendar unavailable still writes the note** — with the explicit
   unavailable line, never a silent empty section.
8. **Verify against disk before claiming success.**
```` 

- [ ] **Step 5: Changelog.** Under `## Unreleased` in `CHANGELOG.md`, append:

```markdown
- **`/evening-sync` — the vault maintains itself overnight.** One run syncs the
  day's recordings, folds review ticks into confirmations, refreshes each
  project's meeting metrics, updates the state of projects with new confirmed
  meetings, captures decisions for review, and writes tomorrow's daily note: a
  recap of today plus a prepared section per upcoming calendar meeting. Runs
  unattended on whatever schedule the engagement chooses, or by hand after a
  missed evening. (#16)
- **Daily notes become the one daily artifact.** Each day gets a single note in
  `60-daily-notes/`, written the evening before: recap on top, one section per
  meeting with prep, room to jot underneath. Jot freely — the machine only ever
  rewrites its own marked regions, and the evening run reads your jottings back
  into the recap and decision capture. The separate morning brief is gone on
  purpose: tomorrow's note *is* the morning brief. (#15)
```

- [ ] **Step 6: Run the verification trio**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all pass — lint accepts the new skill (name matches dir, clean-room), skill-contract tests confirm every referenced subcommand exists and both surface words are present.

- [ ] **Step 7: Commit**

```bash
git add plugin/skills/evening-sync/SKILL.md plugin/.claude-plugin/plugin.json scripts/tests/test_marketplace_manifest.py scripts/tests/test_skill_contracts.py CHANGELOG.md
git commit -m "feat: /evening-sync — the daily-loop engine (closes #15 as superseded, #16)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: End-to-end verification, hand-test, PR

**Files:** none new (fixes only, if the hand-test surfaces any).

- [ ] **Step 1: Full verification**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
python3 -m pytest scripts/tests -q
```

Expected: all green (baseline was 564; expect roughly 640+ with the new suites).

- [ ] **Step 2: Hand-test per the spec's runbook** (controller session, not a subagent). Build a scratch vault and run the pipeline pieces against it:

```bash
python3 scripts/make_test_vault.py /tmp/loop-vault --with-plugins
```

Then, acting as the skill would (follow `plugin/skills/evening-sync/SKILL.md` stage by stage against `/tmp/loop-vault`, with the fixture inbox already in place):
1. `dates plan` with an explicit `--today` → confirm the block.
2. Run the sync stage (inbox adapter only) → meeting notes land.
3. `sync update-queue` → metrics stamped, queue populated or empty, no warnings.
4. `daily-note write` for the next business day → **read tomorrow's note as the judged artifact**: does the recap read like something an exec opens at 07:30?
5. Jot two lines into it by hand (one under a meeting, one under End of day), re-run `daily-note write` with a changed recap → **confirm the jottings survive byte-for-byte** and `daily-note read` surfaces them.
6. Fix anything that fails; add a regression test for any code fix.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin claude/daily-loop-port-p2b-238174
gh pr create --title "feat: /evening-sync — daily-loop P2b (#15, #16)" --body "$(cat <<'EOF'
## Summary

P2b of the daily-loop port (design: `docs/superpowers/specs/2026-08-23-daily-loop-port-design.md`, plan: `docs/superpowers/plans/2026-08-24-evening-sync-port.md`).

- **`/evening-sync`** — the pipeline engine: harvest (read-only) · sync (reconcile folded in) · metrics refresh · project-state updates · `/log-decision --background` capture · tomorrow's daily note · verify-against-disk summary. `--unattended` never prompts.
- **Daily-note contract + §Daily-note ontology block** (sixth object type): machine regions marker-fenced, the CLI owns the merge, zero bytes touched outside markers — pinned by byte-comparison tests.
- **New vaultlib subcommands:** `dates plan` (authoritative date block, recap window since last daily note, next business day) · `sync update-queue` (metrics on projects AND people, key-people excluding the executive by slug, queue + reverse self-check) · `project touch` · `daily-note write/read`. Plus `dates.utc_to_local`, fixing the `recorded_local` DST edge parked from P2a.
- **Fixtures:** daily notes rewritten to the contract (jottings outside markers exercise the merge), a fresh machine-written Monday note, a `conflicts-with` collision sibling (P2a parked item), and metric stamps re-computed to update-queue's real output — the fixture vault is now a converged evening-run snapshot, pinned by a fixed-point test.
- Version 0.3.0 → 0.4.0.

**#15 closes as superseded** (design decision 2): there is no morning skill — the evening run is the only writer of the daily note, tomorrow's note *is* the morning brief, and recovery from a missed run is invoking `/evening-sync` manually.

Closes #15, Closes #16

## Test plan

- `python3 scripts/lint_plugin.py` · `python3 scripts/validate_template.py` · `python3 -m pytest scripts/tests -q` (all green locally)
- Hand-tested per the spec runbook: scratch vault via `make_test_vault.py`, pipeline run end-to-end, hand jottings survive a re-run byte-for-byte and surface in the harvest.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch the checks**

```bash
gh pr checks --watch
```

Expected: three green required checks. Fix and push if not. Squash-merge is gated on the checks per `CONTRIBUTING.md`; stop at a green, open PR.

---

## Self-Review Notes

Checked against the spec (P2b row + decisions 1–14) after writing:

- **Decision coverage:** 1 (one artifact — `daily-note write`, Task 5) · 2 (#15 superseded — PR body, changelog) · 3 (stages — skill structure) · 8 (harvest read-only — `daily-note read`, skill rule 2) · 9 (recap window — `dates.plan`, gap test) · 10 (markers, CLI-owned merge, zero outside bytes — Task 5 byte-pin tests) · 11 (no sidecar — stage 4 returns render into the same run's summary) · 12 (`update-queue` ports, `--auto-fix` does not — module docstring says where it went) · 13 (no scheduling artifact) · 14 (timezone/exec-slug/preferences from the context portfolio — skill stages 1, 4, 6).
- **`project touch` is additive scope** the spec's subcommand table doesn't list, but "skills never author frontmatter" (plugin/CLAUDE.md, P1a) makes stage 4's `last-updated` bump impossible without it. Smallest possible surface: three fields, upsert-only.
- **Fixture metric re-stamp** is justified by the standing issue-#2 rule (fixtures = real output shape) and P2a's coherence lesson; current stamps are impossible under confirmed-only counting (e.g. sam-okafor 30d=3 with zero confirmed meetings ever). The fixed-point test makes the stamps self-verifying forever.
- **Type consistency spot-checks:** `dates.DAY_NAMES` consumed by `dailynote._day_name` ✓; `updatequeue` queue entry keys match the skill's stage-4 prose ✓; `daily-note read --date <recap_from>` matches `plan`'s key name ✓; `_HEADING_RE` accepts subjects containing " — " because the entity suffix group is anchored at end-of-line ✓; Task 7's `FRESH_FIXTURE_PAYLOAD` recap matches Step 5's generator script byte-for-byte ✓.
- **Known test-fallout pins are in-scope files:** `test_compile_ontology` (six objects), `test_marketplace_manifest` (0.4.0), `test_skill_contracts` (expected set), harness HARNESS/MINIMUMS — all named in their tasks, per the P2a lesson about under-scoped briefs.
