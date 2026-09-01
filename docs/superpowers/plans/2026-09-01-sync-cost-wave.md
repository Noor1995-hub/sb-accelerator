# Sync-Recordings Cost & Latency Optimization Wave — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the /sync-recordings run's wasted worker dispatches and pre-dispatch wall clock, measured against the 2026-09-01 DryRunVault baseline (12m41s pre-dispatch, 14 sonnet workers for 4 written notes, ~45k tokens per no-transcript recheck, 43 calendar events listed for 9 candidates).

**Architecture:** Four serially-merged PRs. PR 1 (small, ships first) adds a 6h hold to no-transcript rechecks and trims the m365 worker tool surface. PR 2 narrows discovery windows with a per-adapter watermark and auto-skips tiny Plaud clips. PR 3 makes m365 workers self-sufficient (fetch own event, derive own ids, dedup pre-transcript) and moves routing onto a compact CLI digest, removing the orchestrator's full-event reads and retyping. PR 4 adds the haiku recheck probe as a thin variant of PR 3's worker contract — designed once, not twice (a design-review finding: probe-before-PR3 would build the self-fetch protocol twice).

**Tech Stack:** Python 3.10+ stdlib (`plugin/lib/vaultlib/`), skill prose (`plugin/skills/sync-recordings/`), plugin agent frontmatter (`plugin/agents/`), pytest (`scripts/tests/`).

**Spec:** This plan doubles as the spec; evidence in Context. At execution time commit a copy to `docs/superpowers/plans/2026-09-01-sync-cost-wave.md`.

## Context

Analysis of the 2026-09-01 15:23 DryRunVault run (timestamped session-transcript evidence):

1. **Recheck storm.** `no-transcript` is provisional for 48h ([seenevents.py:40](plugin/lib/vaultlib/seenevents.py) `NO_TRANSCRIPT_FINAL_AFTER_HOURS = 48`). Every run inside the horizon re-dispatches a full ~45k-token sonnet worker per untranscribed meeting (verified: the 21:12 run re-fetched all six, reason `recheck-no-transcript`). 3 runs/day ⇒ ~6 wasted dispatches per untranscribed meeting.
2. **Pre-dispatch wall clock is ~90% model generation** (no tool call over 8s): 79s retyping the Plaud listing, 101s retyping 43 calendar events, ~2m writing 9 full event JSONs serially, ~4m routing over raw project frontmatter + person listings.
3. **The calendar search listing already carries `attendees`, `organizer`, `subject`, `start`/`end`, `id`, `location`, `recurrence`, `uri`** (keys verified against the live payload; value *shapes* not yet — see PR 3 precondition). Only `meetingTranscriptUrl` needs the full event read (`m365 ids`, m365.py:76-107) — and only the worker consumes it.
4. **7-day windows re-list everything daily.** No watermark exists anywhere (verified).
5. **Tiny Plaud clips dispatch workers.** A 7s clip burned a 23.6k-token worker. `list_files` entries carry `duration` (ms).

Decisions taken with Michael (2026-09-01):
- 6h min recheck interval + haiku probe (haiku ONLY there for now). Extraction workers stay sonnet; orchestrator stays session model.
- Account binding check stays as-is.
- Watermark window (both adapters), **floor 2 days**, cap 7 days — Michael chose 2 knowing it shortens the unbanked fetch-error retry horizon from ~7d to ~2-3d in steady state. The only known persistent fetch-error (oversized transcript) never succeeds by retrying and gets its own issue (Task 0.1).
- Tiny clips: **hard skip strictly under 60s** with recorded reason.
- Workers fetch their own full event JSON; orchestrator routes from the listing. Accepted trade-off (design review): with a **cold seen-events cache** (first run / deleted cache), already-synced occurrences are discovered by early-exiting workers (~3 tool calls each, no transcript fetch) instead of pre-dispatch — one expensive run, bounded by the 7d window; steady-state (warm cache) is what we optimize. The dispatch-gate doctrine line and its contract tests change accordingly: dispatch is gated on **triage**; ledger dedup is a worker-side pre-transcript gate.
- New `vaultlib sync routing-signals` command.
- #129 lever 1 (extend m365 worker `disallowedTools`) folded into PR 1.
- Built-in summaries parked as issue #132 — OUT OF SCOPE.
- Oversized-transcript defect: **separate issue, next wave** (Task 0.1).

## Global Constraints

- Clean-room: nothing in `plugin/` references delaware clients, Michael, or busdev content.
- Python 3.10 syntax floor; stdlib only in `plugin/lib/`; vault root always a parameter; writes via `vault.atomic_write` (UTF-8, `newline="\n"`).
- Versions pre-allocated: PR 1 → `0.10.15`, PR 2 → `0.10.16`, PR 3 → `0.10.17`, PR 4 → `0.10.18`. Each PR: version bump + one CHANGELOG line under `Unreleased` ending with the PR number.
- Commit trailer (exact, every commit): `Co-Authored-By: Claude <noreply@anthropic.com>`
- No stacked PRs. Strictly serial merges; rebase each PR on main after the previous one lands (release-file trio collides every time). After each squash-merge verify the base with a tree diff and rebase `--onto`.
- Gate per PR: `python scripts/lint_plugin.py` && `python scripts/validate_template.py` && `python -m pytest scripts/tests -q`, then CI green, then `/review`, then squash-merge (`--admin`).
- Cache doctrine (seenevents.py:12-16): a cache, not a ledger — deleting it stays *safe* (no double-writes; post-PR3 it costs one expensive re-check run, documented).
- Not UI-impacting → no `/visual-check` tier.

---

## Task 0.1: File the oversized-transcript issue (no code)

- [ ] **Step 1:** `gh issue create --repo DLW-INT-BTA-BELUX/sb-accelerator --label "area:plugin,type:infra"` — title: `M365 transcripts larger than the tool-result limit are unsyncable (fetch-error every run)`. Body: evidence from the 2026-09-01 run ("DI AI - Bi-weekly Local Alignment", outcome `fetch-error: transcript result too large for the tool result (spilled to harness tool-results file)`, recurs bi-weekly; worker-contract forbids the spill path; the M365 fetch has no pagination unlike Plaud's cursor). Candidate directions (note, don't decide): sanctioned read of the harness spill file; chunked fetch if the connector supports it. Flag that PR 2's 2-day window floor shortens the visible retry horizon, raising this defect's priority.

---

# PR 1 — Recheck hold + worker tool-surface trim (`0.10.15`, branch `claude/sync-recheck-hold`)

### Task 1.1: 6h minimum recheck interval in `seenevents.triage()`

**Files:**
- Modify: `plugin/lib/vaultlib/seenevents.py`
- Test: `scripts/tests/test_vaultlib_seenevents.py`

**Interfaces:**
- Produces: `triage()` result gains `filtered["no_transcript_waiting"]` (int). `recheck-no-transcript` fetch entries appear only when the last check is ≥ `RECHECK_MIN_INTERVAL_HOURS` (6) old. Implemented **inside** the `elif outcome == "no-transcript":` branch — the not-ended deferral guard above it (seenevents.py:167-174) must keep running first.

- [ ] **Step 1: Write failing tests** (direct-call style, `listing_event()`/`outcome()` builders, naive-UTC `NOW`):

```python
def test_recent_recheck_is_filtered_as_waiting(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00", "Weekly")
    seenevents.record(root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")], NOW)
    result = seenevents.triage(root, [ev], NOW + timedelta(hours=3))
    assert result["fetch"] == []
    assert result["filtered"]["no_transcript_waiting"] == 1

def test_recheck_boundary_is_inclusive_at_6h(tmp_path):
    # checked_at exactly 6h old → fetch (>=6h re-checks); 5h59m → waiting

def test_stale_recheck_still_fetches(tmp_path):
    # 7h since check, <48h since end → fetch, reason recheck-no-transcript

def test_final_wins_over_waiting(tmp_path):
    # end + 49h AND checked 1h ago → filtered["no_transcript_final"], not waiting

def test_refresh_restarts_the_hold(tmp_path):
    # record() no-transcript again at T+7h → triage at T+8h → waiting

def test_missing_or_malformed_checked_at_fails_open(tmp_path):
    # entry without checked_at, and one with "not-a-date" → both fetch
```

  Also update **every existing exact-equality assertion on `result["filtered"]`** in this file (lines 56-57, 70-71, 105, 118, 122, and any others) for the new key — required companion change.

- [ ] **Step 2:** `python -m pytest scripts/tests/test_vaultlib_seenevents.py -q` → new tests FAIL.
- [ ] **Step 3: Implement.** Add `RECHECK_MIN_INTERVAL_HOURS = 6` beside the 48h constant (comment: a recheck costs a dispatch; three runs a day must not pay three times). Add `"no_transcript_waiting": 0` to `filtered`. In the `no-transcript` branch, before appending to `fetch`:

```python
checked = None
raw = seen.get("checked_at") if isinstance(seen, dict) else None
if isinstance(raw, str):
    try:
        checked = datetime.strptime(raw, _KEY_FMT)
    except ValueError:
        checked = None  # fail open: an unreadable stamp never blocks a fetch
if checked is not None and now_utc - checked < timedelta(
        hours=RECHECK_MIN_INTERVAL_HOURS):
    filtered["no_transcript_waiting"] += 1
else:
    fetch.append({**candidate, "reason": "recheck-no-transcript"})
```

- [ ] **Step 4:** Full suite PASS. **Step 5:** Commit `feat: seen-events cache holds no-transcript rechecks for 6h`.

### Task 1.2: Skill surfaces the hold

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` (triage paragraph ~L313-326; summary line L665)

- [ ] **Step 1:** Triage paragraph: add one sentence — occurrences checked within the last 6 hours come back in `filtered.no_transcript_waiting` and are not fetched this run; the 48h horizon is unchanged.
- [ ] **Step 2:** Summary L665 → `**M365 fetches saved:** {N} of {N} listed occurrences answered from the seen-events cache ({N} held in the 6h recheck window) | cache cold (first run)`.
- [ ] **Step 3:** While in the file: fix "Three rules, not negotiable" (L711) → "Four rules" (pre-existing count bug, one word).
- [ ] **Step 4:** lint + pytest PASS. Commit `docs: sync-recordings surfaces the 6h recheck hold`.

### Task 1.3: Extend `sync-worker-m365` `disallowedTools` (#129 lever 1)

**Files:**
- Modify: `plugin/agents/sync-worker-m365.md`
- Test: `scripts/tests/test_skill_contracts.py` (agent-frontmatter test ~L270)

- [ ] **Step 1:** Extend `disallowedTools` from the current 8 to also include: `Artifact, ListAgents, ReportFindings, ShareOnboardingGuide, Monitor, SendMessage, PushNotification, RemoteTrigger, TaskStop, CronCreate, CronDelete, CronList` (per issue #129; drop any name the Step-3 probe shows the harness rejects).
- [ ] **Step 2:** Update the contract test to assert the extended list (module-level constant in the test — PR 4 reuses it for the probe agent).
- [ ] **Step 3 (measurement, not a gate):** re-run the #128 base-context probe (method in `docs/superpowers/plans/2026-09-01-sync-worker-agent-type.md`) on a scratch vault; record before/after tokens in the PR description and on issue #129.
- [ ] **Step 4:** Commit `feat: trim m365 sync-worker tool surface (issue #129 lever 1)`.

### Task 1.4: Release PR 1

- [ ] Version → `0.10.15`. CHANGELOG: `- Untranscribed Teams meetings are no longer re-checked more than once per 6 hours (#<PR>).`
- [ ] Gate green → push → CI → `/review` → squash-merge (`--admin`).

---

# PR 2 — Watermark discovery window + tiny-clip skip (`0.10.16`, branch `claude/sync-watermark`)

### Task 2.1: `lastsync` module + `sync watermark` CLI

**Files:**
- Create: `plugin/lib/vaultlib/lastsync.py`
- Modify: `plugin/lib/vaultlib/cli.py` (sync group, flat dispatch chain, error→`_fail` mapping in `main()`)
- Test: `scripts/tests/test_vaultlib_lastsync.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Produces: `STATE_RELPATH = Path("99-workflow-config") / "sync-state" / "last-sync.json"`, shape `{"version": 1, "adapters": {"m365": {"last_utc_to": "%Y-%m-%dT%H:%M:%S", "set_at": ...}, "plaud": {...}}}`. `lastsync.read(root, adapter) -> Optional[datetime]` (naive UTC; None on missing/malformed/wrong-version — cache doctrine). `lastsync.set_mark(root, adapter, utc_to, now_utc) -> dict` — **monotonic**: a `utc_to` earlier than the stored mark is a no-op reported as `{"advanced": false, ...}` (design-review finding: a stale replay must never widen-then-corrupt the next window). `ADAPTERS = ("m365", "plaud")`; unknown adapter raises `LastSyncError`. Graph-form datetimes (`...Z`) parsed the `seenevents.parse_now` way (Python 3.10 floor). CLI: `sync watermark --vault --adapter {m365,plaud} --utc-to <dt>`.

- [ ] **Step 1: Failing tests:** set→read roundtrip; missing file → None; malformed JSON → None; wrong version → None; unknown adapter → `LastSyncError`; setting `m365` does not clobber `plaud`; **monotonicity** (earlier utc_to after later → stored value unchanged, `advanced: false`); CLI envelope via in-process `run(capsys, argv)` helper.
- [ ] **Step 2:** FAIL. **Step 3:** Implement (`vault.atomic_write`; module docstring: cache-not-ledger — deleting the file just widens the next window to the cap). Wire CLI + error mapping. **Step 4:** PASS. **Step 5:** Commit `feat: per-adapter last-sync watermark in sync-state`.

### Task 2.2: `dates window --trailing-days` consumes the watermark

**Files:**
- Modify: `plugin/lib/vaultlib/dates.py` (`trailing_window`), `plugin/lib/vaultlib/cli.py` (dates dispatch ~L480-502)
- Test: `scripts/tests/test_vaultlib_dates.py`

**Interfaces:**
- Produces: `dates window --vault ... --trailing-days 7 --adapter m365` → `trailing_window(..., watermark=<datetime|None>)`. `WATERMARK_FLOOR_DAYS = 2` in dates.py (comment: covers the 48h no-transcript recheck horizon; unbanked fetch-errors retry only while listed — Michael's accepted trade-off, see the oversized-transcript issue). Effective days = `min(days, max(WATERMARK_FLOOR_DAYS, (now_utc.date() - watermark.date()).days + 1))`; a future watermark (clock skew) clamps to the floor — must not trip `trailing_window`'s `days < 1` guard (dates.py:181). Result gains `effective_days` and `watermark_used: bool`. No `--adapter` or no watermark → today's behavior exactly (`effective_days == days`). `--adapter` without `--vault` → `DatesError`.

- [ ] **Step 1: Failing tests:** no watermark → 7; watermark 3h ago → 2; 4 days ago → 5; 10 days ago → 7 (cap); future watermark → 2, no raise; corrupt `last-sync.json` → widest window (fail open, mirror `test_a_corrupt_cache_is_a_cold_cache`); `--adapter` without `--vault` refused; `sync.start-date` clamp still applies after narrowing; subprocess envelope test for the new flag (pattern at test_vaultlib_dates.py:566-597).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: dates window narrows trailing discovery to the last-sync watermark`.

### Task 2.3: Skill adopts the watermark + writes it back

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` (plaud listing ~L242-246; m365 window L276-289; adapter completion points; summary L667)

- [ ] **Step 1: M365:** discovery-window call gains `--adapter m365`; downstream (utc_from/utc_to → afterDateTime/beforeDateTime) unchanged.
- [ ] **Step 2: Plaud:** replace the prose "recent window" with the same call (`--adapter plaud`); `date_from` = local date of `utc_from`, `date_to` = today (local). `sync.start-date` floor sentence stays.
- [ ] **Step 3: Write-back semantics (pin them, design-review finding):** run `sync watermark --vault "$VAULT" --adapter <name> --utc-to <the window's own utc_to>` when the adapter's status line is `ok` — item-level `fetch-error` outcomes do NOT block advancement (rationale in the skill text: a persistent oversized transcript must not pin every future window wide; transient errors get the 2-day tail). `REFUSED`/`unavailable`/auth-error stop → no write. Use the window's `utc_to`, never "now": everything after it was never listed.
- [ ] **Step 4: Summary:** adapters line gains the window: `plaud ok (window 2d) · m365 ok (window 2d)`.
- [ ] **Step 5:** lint + pytest PASS. Commit `feat: sync-recordings lists only since the last successful run`.

### Task 2.4: Tiny-clip skip at Plaud triage

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` (plaud section, after the dedup block ~L248-256)

- [ ] **Step 1:** After the `new`-ids paragraph: for each `new` entry whose listing `duration` is a number **strictly under 60000 ms**, write no `rec_N.meta.json` and dispatch nothing — run `python3 "$VAULTLIB" sync skip --vault "$VAULT" --id "plaud:<id>" --reason "tiny clip: <N>s recording, under the 60s auto-skip threshold"` (`<N>` = duration/1000 rounded). A missing, null, or non-numeric `duration` **fails open — dispatch normally** (losing a recording is the one wrong answer; same doctrine as the seen-events cache). Count skips under **Skipped / errors** with the duration visible. Interactive mode: an information line, not a question — the skip list records the reversal path.
- [ ] **Step 2:** lint + pytest PASS. Commit `feat: sync-recordings auto-skips Plaud clips under 60s`.

### Task 2.5: Release PR 2

- [ ] Rebase on main. Version → `0.10.16`. CHANGELOG: `- Daily syncs scan only since the last successful run (2-day floor, 7-day cap) and auto-skip Plaud clips under 60 seconds (#<PR>).`
- [ ] Gate green → push → CI → `/review` → squash-merge.

---

# PR 3 — Orchestrator context diet (`0.10.17`, branch `claude/sync-worker-fetch-events`)

**Execution precondition (live probe, before Task 3.2):** in a DryRunVault session, inspect one real `outlook_calendar_search` event and pin the value shapes of `attendees` (does each entry carry an email address? — signal-1 routing needs domains), `organizer`, `location`, `recurrence`, and `uri` (is it the `calendar:///events/<id>` form the full-read step uses?). Keys were verified live 2026-09-01; shapes were not. **If attendee addresses are missing from the listing, STOP — routing cannot move off full events — and re-plan with Michael.**

### Task 3.1: `sync routing-signals` CLI

**Files:**
- Modify: `plugin/lib/vaultlib/syncjob.py`, `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_syncjob.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Produces: `syncjob.routing_signals(root) -> dict`:

```json
{"projects": [{"slug": "...", "name": "...", "entity": "...", "status": "..."}],
 "entities": ["slug", ...],
 "people": ["slug", ...],
 "warnings": ["<slug>: unparseable frontmatter", ...]}
```

  Projects from `30-projects/*/index.md` frontmatter (`project-name`, `entity`, `status`); malformed frontmatter → slug with nulls + a warning, never a failure. Entities from `40-entities/*/` dir names. People from `50-people/*.md` stems. Values only — no free text, no note bodies (the digest exists to be small). CLI: `sync routing-signals --vault`.

- [ ] **Step 1: Failing tests:** vault with 2 projects (one mangled YAML) + 2 entities + 3 people → exact dict incl. warning; empty vault → empty lists; a compactness assertion (result for the fixture vault serializes under ~1KB — the digest must never grow bodies).
- [ ] **Step 2:** FAIL. **Step 3:** Implement, reusing syncjob's existing frontmatter reader. **Step 4:** PASS. **Step 5:** Commit `feat: sync routing-signals emits the routing digest`.

### Task 3.2: Worker contract — workers fetch their own event

**Files:**
- Modify: `plugin/skills/sync-recordings/references/worker-contract.md` (M365 fetch L39-54, reassemble L69-73, outcome table L130-139)
- Test: `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Failing contract test:** worker-contract.md must contain `calendar:///` (event self-fetch), `already-synced:`, `recording-id:`, and a "pre-fetched event" variant paragraph; the outcome-vocabulary test (`test_sync_recordings_worker_outcomes_are_a_closed_vocabulary`, ~L305) updated for the new/changed lines.
- [ ] **Step 2: Rewrite the M365 fetch section.** Briefing carries the event URI + stem `m365_event_<n>` (no pre-read file, no transcript_url). Worker sequence:
  1. One `read_resource` on the event URI **exactly as given**; Write raw JSON to `$SCRATCH/m365_event_<n>.json`.
  2. Write the one-element array `$SCRATCH/m365_event_<n>.ids-in.json`; run `m365 ids` on it. Result `skipped: no-transcript-url` → reply `no-transcript`. Else take `recording_id` + `transcript_url` from the result.
  3. Write `$SCRATCH/m365_event_<n>.dedup.json` (one-element ids array); run `sync dedup`. `synced` → reply `already-synced: <recording_id>`, stop — no transcript fetch.
  4. Transcript: one `read_resource` on the derived `transcript_url` **verbatim** (never composed — the recurring-series warning stays, anchored to "the URL `m365 ids` returned"). Mapping unchanged (`transcripts_empty` → `no-transcript`, 403 → `forbidden`, oversized/transport → `fetch-error`, 401 → `auth-error`).
  Sanctioned Graph calls: exactly two — own event, own transcript.
  **Pre-fetched event variant** (used by PR 4's probe flow): a briefing may instead name an already-fetched event file plus a verbatim transcript_url — the worker then starts at step 3 (dedup).
- [ ] **Step 3: Outcome-line changes (M365 only):** `written: <stem> (recording-id: m365:<hex>)`; `possible-duplicate-of: <stem> (recording-id: m365:<hex>, payload at <path>)`; new settled line `already-synced: <recording_id>`. Update the outcome table. Note in the banking paragraph that the orchestrator parses `recording-id:` because `sync m365-record` **requires** a namespaced `recording_id` on `written` outcomes (seenevents.py:214-223) — a malformed line must surface as a banking error, not a silent drop.
- [ ] **Step 4:** Contract tests + lint PASS. Commit `feat: m365 sync workers fetch their own event and derive their own ids`.

### Task 3.3: Skill rework — routing from the listing, banking from outcome lines

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` (M365 section L296-394; routing L430-472; briefings L548-569; per-line handling L583-606; banking L608-630; summary L665-666; scratch-hygiene pattern list L688-696)
- Test: `scripts/tests/test_skill_contracts.py` (ordering tests ~L233-257)

- [ ] **Step 1: Post-triage extract replaces full reads.** Keep `m365_search.json` (4 fields, all kept events — triage input, unchanged). Delete: the full-event-read block (L328-336), `m365_events.json`, the orchestrator's `m365 ids` and m365 `sync dedup` calls, and the pre-dispatch settled-outcomes banking (L344-358) — workers surface all of it via outcome lines. For `fetch` survivors only, Write one compact array `$SCRATCH/m365_routing.json`: per event `id`, `subject`, `start`, `end`, `organizer`, `attendees`, `location`, `recurrence`, `uri` — **values verbatim from the listing** (`location`/`recurrence` included so the step-1 pre-fill of `location`/`recurring` loses nothing — design-review finding). `m365_routing.json` matches the existing `m365_*.json` sweep pattern; no hygiene change needed.
- [ ] **Step 2: Routing reads the digest.** Replace the raw entity/project/person listing instructions (L432-434, L467) with one `sync routing-signals --vault` call; signals 1–3 logic unchanged, matched against the digest + `m365_routing.json` attendees. `person ensure` batching unchanged. Step-1 pre-fill fields now come from `m365_routing.json`.
- [ ] **Step 3: Briefing change (M365):** recording reference = the event URI (from the listing) + stem `m365_event_<n>`; transcript_url dropped.
- [ ] **Step 4: Banking:** `written` and `possible-duplicate` recording_ids parsed from outcome lines; `already-synced: <id>` banks `{"outcome": "written", "recording_id": <id>}` (the back-fill, now worker-discovered); `no-transcript`/`forbidden` keyed by triage's `id`+`start_utc` as today. Cross-adapter duplicate `sync skip` takes its id from the duplicate line.
- [ ] **Step 5: Doctrine + tests:** rewrite the dispatch-gate line (L383-394) to the new invariant — dispatched only for occurrences that survived **triage**; ledger dedup is the worker's first gate and `meeting write`'s already-synced refusal remains the backstop. Update `test_sync_recordings_triages_m365_before_the_fetch` (L233-239) and `test_sync_recordings_dispatches_workers_only_after_triage_and_dedup` (L247-257) to assert the new ordering (triage before dispatch; dedup present in worker-contract.md, not SKILL.md).
- [ ] **Step 6: Summary:** workers-dispatched line replaces "had no transcript URL yet ({N})" bucketing with worker-reported outcomes (`{N} already-synced` joins the list).
- [ ] **Step 7:** lint + full pytest PASS. Commit `feat: sync-recordings routes from the listing; orchestrator stops reading full events`.

### Task 3.4: Release PR 3

- [ ] Rebase on main. Version → `0.10.17`. CHANGELOG: `- Sync startup is minutes faster: recording workers fetch their own meeting data and routing reads a compact vault digest (#<PR>).`
- [ ] Gate green → push → CI → `/review` → squash-merge.

---

# PR 4 — Haiku recheck probe (`0.10.18`, branch `claude/sync-recheck-probe`)

### Task 4.1: Probe contract + agent

**Files:**
- Create: `plugin/agents/sync-probe-m365.md`
- Create: `plugin/skills/sync-recordings/references/probe-contract.md`
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Produces: agent type `second-brain:sync-probe-m365` (`model: haiku`, no `tools:` key, `disallowedTools` identical to `sync-worker-m365.md` — assert via the shared test constant from Task 1.3). Outcome lines (complete set): `still-no-transcript` · `transcript-found: <recording_id> (event at <path>)` · `forbidden` · `fetch-error: <one clause>` · `auth-error`.

- [ ] **Step 1: Failing contract test:** probe agent frontmatter (name/model/no-tools/disallowedTools), body mentions "probe contract" and "outcome line"; probe-contract.md exists, contains `still-no-transcript`, `transcript-found`, and references the worker contract's fetch steps.
- [ ] **Step 2: Write `probe-contract.md`.** The probe is steps 1–2 of the worker contract's M365 fetch (Task 3.2) with a classification tail instead of extraction — the contract says so explicitly and defers to worker-contract.md for fetch mechanics (one protocol, two depths — design-review finding). Specifics:
  - Job: one occurrence previously settled provisional `no-transcript`; answer "did the transcript appear?" — never extract, never write a note, never touch the seen-events cache.
  - Steps: fetch own event (URI verbatim from briefing) → Write `$SCRATCH/m365_probe_<n>.event.json` (matches the `m365_*` sweep pattern) → `m365 ids` (one-element array file) → `skipped: no-transcript-url` → `still-no-transcript`. Else fetch the returned `transcript_url` verbatim: `transcripts_empty` → `still-no-transcript`; transcript content → `transcript-found: <recording_id> (event at <path>)`; 403 → `forbidden`; 401 → `auth-error`; transport/oversized after 3 retries → `fetch-error`.
  - **Explicit rule-8 carve-out, stated in the contract:** the probe classifies its transcript fetch in place and writes it nowhere — the extraction worker re-fetches per its own contract. The double-fetch on `transcript-found` is accepted: it is the rare success case, and haiku input is cheap.
- [ ] **Step 3: Write `sync-probe-m365.md`** modeled on `sync-worker-m365.md` (same disallowedTools, same missing-briefing refusal line, `model: haiku`, `color: cyan`, description: "Recheck probe for one M365 occurrence, dispatched by /sync-recordings step 6 with a full briefing. Not for direct invocation.").
- [ ] **Step 4:** Contract test + lint PASS. Commit `feat: haiku recheck probe agent`.

### Task 4.2: Skill wiring for the probe

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` (triage paragraph; step 6 dispatch; summary L665-666)

- [ ] **Step 1:** Triage paragraph: `fetch` entries split by reason — `unseen`/`unkeyed` → normal worker path; `recheck-no-transcript` → probe dispatch list.
- [ ] **Step 2:** Step-6 probe block (before worker batches): dispatch `second-brain:sync-probe-m365`, up to ~4 in parallel; briefing = probe-contract path, `$VAULT`/`$SCRATCH`/`$VAULTLIB`/timezone, event URI, stem `m365_probe_<n>`. Outcomes:
  - `still-no-transcript` → bank `{"id", "start_utc", "outcome": "no-transcript"}` (refreshes `checked_at`, restarting the 6h hold).
  - `transcript-found: <recording_id> (event at <path>)` → run `m365 ids` on the probe's event file for the verbatim `transcript_url` (no Graph call — the file is local); the occurrence is in `m365_routing.json`? No — rechecks skipped the routing extract, so **add it now**: it is in the listing, extract its routing row, run steps 2–5 (routing/confidence) for it like any survivor, then dispatch a full `sync-worker-m365` using the contract's **pre-fetched event variant** (event path + transcript_url; worker starts at dedup — the dedup gate is therefore never skipped, design-review finding).
  - `forbidden` → bank `forbidden`. `fetch-error`/`auth-error` → as for workers.
- [ ] **Step 3:** Summary: workers-dispatched line gains `· {N} probes ({N} still-no-transcript · {N} transcript-found)`.
- [ ] **Step 4:** lint + pytest PASS. Commit `feat: sync-recordings dispatches haiku probes for no-transcript rechecks`.

### Task 4.3: Release PR 4

- [ ] Rebase on main. Version → `0.10.18`. CHANGELOG: `- Re-checks of untranscribed Teams meetings now run as lightweight probes instead of full sync workers (#<PR>).`
- [ ] Gate green → push → CI → `/review` → squash-merge.

---

## Verification (end-to-end, after all merges)

1. **Deploy:** re-cut the dist per the established git-archive recipe (dist currently `0.10.14` @ `c7f4691`); update the DryRunVault plugin cache to `0.10.18`. `last-sync.json` starts absent → first window is 7d (correct cold behavior).
2. **Live run 1 (cold watermark):** `/sync-recordings` in a fresh DryRunVault session. Expect: 7d window; no orchestrator full-event reads; `m365_routing.json` + one `routing-signals` call in the transcript; probes only for provisional no-transcript occurrences ≥6h since last check.
3. **Live run 2 (+1h):** expect `no_transcript_waiting` holds every recheck (zero probes/workers unless new meetings); 2-day windows both adapters; pre-dispatch wall clock from session timestamps — target under ~5 min vs 12m41s baseline.
4. **Tiny clip:** a <60s Plaud clip in the window → skip-list line with duration in the reason, no worker.
5. **Probe live check:** next morning's run — any provisional occurrence probed by haiku (verify agent type + token count in the transcript), and a transcript-found case (if one occurs) produces a normally-routed note.
6. Report the before/after table (pre-dispatch minutes, workers, probes, tokens per outcome class) to Michael; update issue #129 with the Task 1.3 measurement; update memory files (recheck semantics, watermark, PR outcomes).

## Execution & orchestration model

- Orchestrator: this session (session model). Implementers: `model: sonnet` subagents via superpowers:subagent-driven-development, one per task with its two-stage review; skill-prose tasks (1.2, 2.3, 2.4, 3.2, 3.3, 4.1, 4.2) additionally get a full-diff orchestrator read before commit (prose has no test net beyond test_skill_contracts.py).
- PRs strictly serial; after each squash-merge, tree-diff the base and rebase `--onto`.
- PR 3's live-probe precondition runs between PR 2's merge and Task 3.2; its failure is a stop-and-replan gate with Michael.
- Michael's gates: plan approval (now); the PR-3 precondition only on failure; the final before/after report.
