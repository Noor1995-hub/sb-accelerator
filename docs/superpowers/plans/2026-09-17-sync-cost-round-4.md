# /sync-recordings cost round 4 — stop paying for non-notes

## Context

The DryRunVault routine `dryrun-sync-recordings` (14:10Z, 2026-09-17, plugin 0.11.3, Sonnet) cost ~$16 at list price ($11 on the app card) for **two** meeting notes. Only 28% of the spend produced notes. The rest:

| Bucket | $ | Why it exists |
|---|---|---|
| 3 re-dispatched known Plaud↔Teams duplicates | 4.3 | unattended `possible-duplicate-of` is never recorded → full re-fetch every run since 09-15 (10 runs for one event) |
| orchestrator | 3.0 | 14 briefings, retyped listings, reasoning |
| 4 first-look M365 no-transcript workers on Sonnet | 2.1 | probe (Haiku) only used for rechecks (#173 parked) |
| 3 improvised `general-purpose` helpers around single MCP calls | 1.2 | skill doesn't forbid it; 11:45 run didn't do it |
| 2 persistent fetch-errors (oversized Teams transcript #133, Plaud id returning `[]`) | 1.0 | retried every run forever |
| verbatim retype of 14–24 KB event JSON per M365 worker | ~1.0 | contract says verbatim, CLI reads a handful of fields |

Decisions taken with Michael (2026-09-17): duplicates are **auto-skipped** under `--unattended` (banked `skipped` + skip-list line, named in the summary); lever 6 (CLI-side Plaud fetch) is gated on **Cowork parity as a hard requirement** — if the spike shows Cowork can't, it is a documented no-go.

Costing method (reused for verification): export the routine session with `mcp__ccd_session_mgmt__export_transcript`, sum `message.usage` **max per `message.id`** over `transcript.jsonl` + `*/subagents/*.jsonl` (lines repeat per content block); `*.meta.json` carries `agentType`/`description`. Memory: `sync-cost-analysis-2026-09-17`.

## Packaging

Three plugin PRs plus one docs/tools PR, merged serially (every PR collides on plugin.json / CHANGELOG — rebase each onto the previous squash, never stack):

| PR | Levers | plugin.json |
|---|---|---|
| A `fix/sync-duplicates-settle` | 1 + 2 | main+1 |
| B `feat/sync-probe-first-trimmed-event` | 3 + 5 | main+2 |
| C `fix/sync-skill-hygiene-fetch-error-parking` | 4 | main+3 |
| D `chore/sync-cost-report-and-plaud-spike` | cost-report tool + spike doc + probe script | no bump (nothing under `plugin/`) |

Each PR: tests first (`scripts/tests/test_skill_contracts.py` prose contracts + vaultlib unit tests), then code, then the three CI commands, then `/code-review`, CHANGELOG `Unreleased` line (client-visible behaviour changes: A, B, C all qualify). Implementation teammates: `model: sonnet` (memory `cheap-execution-teammates`).

---

## PR A — settle duplicates, collide before the fetch (levers 1 + 2)

Three nets, each with a distinct job (design-review finding: no single check covers both the cross-run loop and the same-run race):
- **Triage-time** (A2) — catches duplicates of notes written in *earlier* runs, before any dispatch. This is the 26% problem.
- **Worker-time, before the transcript fetch** (A3) — the cost saver for anything triage missed; sees notes on disk at that moment.
- **Write-time, in the CLI** (A1) — the correctness net: Plaud and Teams workers for the same meeting can sit in the same ~4-batch (SKILL.md `:798–805, 862–875`), so a Teams worker's early collide can run before the Plaud note exists. `meeting write` closes that window itself; prose cannot (lesson `lessons.md:773`: put the transform in the CLI).

### A1. `meeting write` refuses a precise cross-adapter duplicate
`plugin/lib/vaultlib/meeting.py:_resolve_target` (`:349–396`) already refuses `cross-source-duplicate` when two sources derive the **same stem**. Add a second, stem-independent check: run `syncjob.collide(root, payload["date"], payload["recording-duration"])`; a match with `imprecise: false` whose `source-recording-id` namespace differs from the payload's → refuse with conflict kind `cross-adapter-duplicate`, naming `existing_stem` + `existing_id`. New flag `--accept-collision` writes anyway (the interactive "write it anyway"). Imprecise matches are returned as a `warnings` entry, never a refusal (date-only note = "look at it", `syncjob.py:363–365`). Skip the scan when the payload has no `recording-duration` (captures, inbox items without duration).
Tests: `scripts/tests/test_vaultlib_meeting.py` (refusal; same-namespace overlap writes; imprecise → warning; `--accept-collision` writes; missing duration → no scan). Note `meeting write --note` is called by both worker types, so the Plaud worker also becomes able to reply `possible-duplicate-of` (today M365-only) — the outcome table row loses its "(M365 only)" qualifier.

### A2. Triage-time collide (orchestrator, zero dispatch for known duplicates)
`plugin/lib/vaultlib/seenevents.py:triage()` — the listing carries **no** `meetingTranscriptUrl` (SKILL.md `:352–361`), so `m365 ids` cannot be used here (`m365.py:157–159` skips such events). Compute the collide inputs from the listing itself: `_occurrence_dt(event,"start"/"end")` (`seenevents.py:117–132`, already UTC-validated) → owner-local `"%Y-%m-%dT%H:%M"` via `dates.utc_to_local` and `(end − start)` minutes. New flag `--collide` plus the existing-pattern `--timezone`/`--utc-offset` pair on `sync m365-triage` (`cli.py:357–368`; the CLI never reads config — every command takes the timezone explicitly, cf. `cli.py:131,458`; the orchestrator already holds it from `config read`, SKILL.md `:323–327`). For each candidate that would land in `fetch`, run `syncjob.collide`; a precise match from another namespace moves it to a **new top-level bucket `duplicate`**: `{id, start_utc, subject, event_uri, existing_stem, existing_id}`. Imprecise → stays in `fetch`. Recurring series are safe: the key stays `id|start_utc` (`seenevents.py:256`).
**Accepted trade-off, documented in the skill:** a triage-caught duplicate has no `m365:<hex>` id yet (needs the full event), so it is banked as `{"id","start_utc","outcome":"skipped"}` in seen-events only (precedent SKILL.md `:694–705`), which `record()` prunes after 30 days (`seenevents.py:338–347`). Inside the 7-day discovery cap that is permanent in practice; a deliberate >30-day backfill would re-surface it once, at which point the worker-time net (A3) settles it permanently.
Tests: `test_vaultlib_seenevents.py` (precise cross-namespace → `duplicate`; same-namespace → `fetch`; imprecise → `fetch`; without `--collide` unchanged; two occurrences of one series independent; `skipped`-without-`recording_id` banks and filters next run), `test_vaultlib_cli.py` (flag wiring; round-trip like `:712`).

### A3. Worker-side collide moves before the transcript fetch
`plugin/lib/vaultlib/m365.py` — `ids` gains optional `--timezone`/`--utc-offset`; when supplied, each entry also carries `recorded_local` (factor `_recorded_local(event, tz)` out of `reassemble:232–237`) and `event_duration_min` (factor out of the fallback at `:273–278`). Omitted → fields absent (id-only callers unchanged; `test_skill_contracts.py:521` substring still holds).
`references/worker-contract.md`:
- Step 2 (`:56–65`): call `m365 ids --timezone <timezone from your prompt>`.
- New **Collision check** between step 3 (dedup) and step 4 (transcript read): `sync collide --start <recorded_local> --duration-min <event_duration_min>`. Precise cross-namespace hit → reply `possible-duplicate-of: <existing stem> (recording-id: <recording_id>, existing: <source-recording-id>)` and stop — no transcript fetch, no payload. Imprecise hit → continue (the write-time net reports it as a warning). Remove the post-reassemble collision section (`:197–218`) including "Draft the payload anyway" and the `payload at …` clause (also `:274`, SKILL.md `:944`).
- `meeting write` refusal `cross-adapter-duplicate` → the same `possible-duplicate-of` reply (both worker types). Briefing field `collision: accepted` → the worker passes `--accept-collision` and skips the early check.
- Pre-fetched event variant (`:109–115`) unchanged (starts at step 3 → collide → step 4).
Contract tests: keep `:252`/`:525–530` ordering; add `sync collide` index < transcript-read index; `possible-duplicate-of` row no longer names `payload`; `:481` still finds `sync collide`. Fix the stale citation `worker-contract.md:279` ↔ `test_skill_contracts.py:655–662` (the `written` branch is at `seenevents.py:311–320`).

### A4. Orchestrator: unattended duplicates are settled, not deferred — one CLI verb
New `sync settle-duplicate --vault --id <ns:hex> --existing <ns:id> --stem <stem> [--event-id <id> --start-utc <utc>]`: writes the skip-list line (`syncjob.skip`, reason `same meeting already synced as <existing> (<stem>)`) **and**, when the m365 keys are given, the seen-events `skipped` entry, atomically — the "two writes that must not come apart" shape `sync park` set the precedent for (`plugin/CLAUDE.md`). Plus `sync unskip --vault --id` (removes the line; refuses an unknown id).
`plugin/skills/sync-recordings/SKILL.md`:
- Step 1 (`:365–367`): triage gains `--collide --timezone …`; `duplicate` bucket → bank as `skipped` in the step-6 batch file (no dispatch); count in summary.
- Step 6 `possible-duplicate-of` (`:944–958`): interactive — show both notes, ask once; "write it anyway" = re-dispatch the same worker with `collision: accepted` (a full second worker run — deliberate cost trade for a rare interactive path, replacing today's free `meeting write --note` of a pre-drafted payload); "drop it" = `sync settle-duplicate`. **Unattended = drop, automatically.** Delete "it defers until an interactive run settles it" and `:453–457`.
- Watermark (`:1014–1023`): delete the deferred-duplicate hold; keep the fetch-error sentence.
- Summary (`:1045`) → `**Cross-adapter duplicates skipped:** {N} ({subject} → already synced as {stem}; undo: sync unskip --id <id>)`; imprecise write-time warnings listed under the existing `**Possible duplicates:**` line (`:1044`).
- Tests: `:404` vocabulary, `:586` counts, `:231` plain-speech denylist, `:90` every named `sync <x>` exists.

### A5. CHANGELOG
"Teams meetings already captured by the recorder are skipped automatically in scheduled runs instead of being re-checked every run; the collision check now runs before the transcript is fetched."

### A6. DryRunVault after merge
First routine run settles the three looping duplicates (AI Tooling Governance weekly, AI tooling approver session, AI Growth call) as `skipped`; the M365 watermark advances again. Verify with `skipped-recordings.txt` + `last-sync.json`.

---

## PR B — probe-first for M365 + trimmed event write (levers 3 + 5)

Unparks issue #173. Its stated blocker ("depends on the external-organizer filter from #124") is already met: triage's `external` bucket / `adapters.m365.home_domains` exist (`seenevents.py:237–247`). This run is the field measurement #173 asked for: 5 of 8 M365 dispatches ended no-transcript/fetch-error.

### B1. Every M365 first look is a Haiku probe
`plugin/skills/sync-recordings/SKILL.md`:
- Step 1 split (`:399–411`): **all** `fetch` entries — `unseen`, `unkeyed`, `recheck-no-transcript` — go on the probe dispatch list. The `m365_routing.json` extract (`:413–431`) and steps 3–5 run only for entries a probe promotes with `transcript-found` (mechanics already written for rechecks at `:744–761` — "route this entry like any fetch survivor"; generalise the wording, it is no longer the rare case). Dispatch gate (`:481–501`): "a worker is dispatched for every occurrence whose probe replied `transcript-found`".
- Step 6 (`:710–783`): probe waves first (cap ~4 blocking per message, unchanged), then Plaud/inbox worker batches, then promoted M365 workers via the **pre-fetched event variant** (`worker-contract.md:109–115`). A first-look probe's `still-no-transcript` banks `{"outcome":"no-transcript"}` — that *is* the provisional entry that starts the 48h/6h recheck cycle (`seenevents.py:266–286`); `no-access`/`forbidden` bank as today; `fetch-error`/`auth-error` as today.
- Summary (`:1047–1048`): probe sub-tally gains all outcomes — `{N} probes ({N} no-transcript · {N} transcript-found · {N} no-access · {N} forbidden · {N} fetch-error)`; "Workers dispatched … m365" counts promoted workers only; add "M365 first looks answered by a probe: {N}".
- `references/probe-contract.md`: framing (`:1–16`, "already settled `no-transcript` on a provisional basis") → "one M365 occurrence that has not been synced; your only question is whether a transcript exists". Outcome vocabulary unchanged.
- `plugin/agents/sync-probe-m365.md` unchanged (haiku, open surface, same disallowedTools).
Contract tests to update: `test_skill_contracts.py:1000–1012` (step-1 split), `:1015–1033` (probe before worker — still true), `:1036–1065` (promotion prose), `:1068–1076` (summary shape), `:481–485`/dispatch-gate assertions. New: "every fetch reason is probed" assertion; "no `unseen` worker dispatch" assertion.

**Double-fetch economics (review question, answered with this run's numbers).** On `transcript-found` the transcript is read twice (probe, then worker) — `probe-contract.md:76–87` accepts this for rechecks; probe-first makes it the path for every found meeting. Cost of the extra read: the transcript enters a Haiku context once (~30k tokens ≈ $0.03–0.05 at Haiku input/cache-write rates). Saving per not-found meeting: a Sonnet worker ($0.45–0.60 in this run) replaced by a Haiku probe (~$0.10). Break-even needs >90% of first looks to have a transcript; the run log since 09-15 shows the opposite (this run 5 of 8 M365 dispatches ended without a transcript, the 11:45 run similar, one M365 note written in three days). Having the probe *write* the transcript to avoid the second read would cost more (Haiku output $5/M ≫ input), so the double read stays. Re-measure with `scripts/cost_report.py` after B lands; if found-rate ever exceeds ~80%, revisit.

### B2. Trimmed event file
Honest sizing: the model still ingests Graph's full event (input tokens are fixed by the connector); the saving is the **retype** — 8–12k output tokens per event today ($0.12–0.18 on Sonnet; ~$0.05 on Haiku once B1 moves the event write to the probe). Worth doing for cost, scratch hygiene and a smaller pre-fetched handoff, but it is the smallest lever here.
Evidence: the CLI reads only `meetingTranscriptUrl`, `start.dateTime`, `start.timeZone`, `end.dateTime`, `subject` (`m365.py:73–92, 146–162, 206–212, 215–296`); the model reads `attendees[].name` (`worker-contract.md:117–163`); `id`/`organizer` are used by triage from the listing only. `scripts/tests/test_vaultlib_cli.py:670–700` already proves a four-key event reassembles.
- `worker-contract.md:46–55` and `probe-contract.md:18–30`: the event file is the `read_resource` result **restricted to these top-level keys, values verbatim**: `id`, `subject`, `start`, `end`, `meetingTranscriptUrl`, `organizer`, `attendees` (each: `name`, `address`, `type`). Everything else (`body`, `bodyPreview`, `location`, `locations`, `recurrence`, `onlineMeeting`, `webLink`, `@odata.*`, …) is dropped. Copying a value is still verbatim; the rule-8 incident was retyping *from memory*, not selecting keys.
- SKILL.md rule 8 (`:60–85`) "full-event JSON" → "the event's kept keys"; update `test_skill_contracts.py:989–994` to the new phrase.
- `m365.py`: `_transcript_window` (`:206–212`) and the duration fallback (`:273–278`) must check `end.timeZone` the way `_event_start` checks `start.timeZone` (`:73–79`) — today a non-UTC `end` would silently mis-window a recurring series. Add a required-keys check in `ids`/`reassemble` that names a missing key plainly. Tests in `test_vaultlib_m365.py` (non-UTC `end` refused; trimmed event round-trips).

### B3. CHANGELOG
"Teams meetings are first checked by a lightweight probe; the full sync worker runs only when a transcript exists. Scheduled runs on days with untranscribed meetings cost a fraction of before."

---

## PR C — skill hygiene + fetch-error parking (lever 4)

### C1. Rule 10: connector calls are never delegated
SKILL.md Rules block (`:38–91`, rules 1–9): add rule 10 — "**Connector calls are made by this context.** `get_current_user`, `get_me`, `list_files`, `outlook_calendar_search`: call the tool yourself and write the raw result to scratch with the Write tool. Never wrap a connector call in a subagent of any type — a generic subagent re-reads the whole base context to make one call, and its result still comes back through this context to be written. The only subagents this skill dispatches are step 6's worker and probe agent types." No rule existed at all (grep `general-purpose` under `plugin/` is empty), so this is a first statement, not a restatement (cf. `lessons.md:773` — restating a violated rule buys nothing; a first statement is a different case). Also add the same line to the routine wrapper `~/.claude/scheduled-tasks/dryrun-sync-recordings/SKILL.md` (local, not in repo).
Contract test: rules block (`split("## The three adapters")[0]`) names all four tools + "subagent"; `general-purpose` absent from the skill.

### C2. Fetch-error parking (CLI-enforced, not prose)
There is no per-recording retry state anywhere today (`scancache`, `seenevents`, `lastsync`, skip list — none counts attempts). Add one, under the same "a cache, not a ledger" doctrine:
- New `plugin/lib/vaultlib/fetcherrors.py`: `99-workflow-config/sync-state/fetch-errors.json` `{"version":1,"recordings":{"<canonical id>":{"count":N,"first_seen":..,"last_seen":..,"last_reason":..}}}`. `PARK_AFTER = 3` consecutive runs, `PRUNE_AFTER_DAYS = 14`. `record(root, entries, now)` — one entry per failed recording `{id, reason}`; increments `count` **at most once per calendar day per id** (three runs a day must not park in one day — parking means "failed on three different days"); when `count >= PARK_AFTER` → `syncjob.skip(root, id, reason=f"parked after {count} fetch-errors: {reason}")` and the entry is returned with `parked: true`. `clear(root, ids)` for ids that later succeed (called from the batch path when a `written` line arrives for an id present in the file).
- CLI `sync fetch-error --vault --outcomes <file|->` (array of `{id, reason}`; returns `{recorded, parked:[{id, reason}], cleared}`) and `sync unskip --vault --id` (removes the skip-list line; refuses an id that is not there). Register both in `cli.py` (the prose-contract test `:90` requires every `sync <x>` the skill names to exist).
- Worker/probe contracts: `fetch-error: <clause>` gains `(recording-id: <ns:id>)` whenever the id is known (Plaud always; M365 after `m365 ids`). Outcome table rows `worker-contract.md:270`, `probe-contract.md:74,106`.
- SKILL.md step 6 batch handling (`:941`, `:762–765`): a `fetch-error` line with a recording id is appended to `$SCRATCH/fetch_errors_batch.json`; after banking, run `sync fetch-error`. For a parked **m365** id also bank `{"id","start_utc","outcome":"skipped"}` so triage stops listing it. Summary: `**Parked after repeated fetch-errors:** {N} ({id} — {reason}; undo: sync unskip --id <id>)`. Rule 6 (`:53`) keeps "a failed recording writes nothing to the vault" and adds "the CLI counts the failure; a third failure parks it".
- DryRunVault effect: the oversized "DI AI Local Alignment" transcript (#133) and the Plaud recording returning `[]` park after their third day and stop costing ~$1/run; #133 stays open as the real fix, and the summary names the parked meeting each run until unskipped… no — once parked it is silent; the park line appears **once**, in the run that parks it. Add a `runlog` mention so the evening note can pick it up (check `runlog append` usage `:1152`).
Tests: `scripts/tests/test_vaultlib_fetcherrors.py` (new: increments once per day, parks on the third day, writes the skip line with reason, prunes, clear), CLI wiring test, contract tests for the new lines.

### C3. CHANGELOG
"A recording that fails to fetch on three different days is parked with its reason instead of being retried at every run; `sync unskip` brings it back."

---

## PR D — cost-report tool + Plaud direct-fetch spike (lever 6) — no plugin bump

### D1. `scripts/cost_report.py`
The costing method from this analysis as a repo tool (stdlib): input = a session export zip or its extracted dir; output = per-agent table (agentType · description · requests · out · cache-read · cache-write · $ at list) and by-type totals; `--pricing` table for sonnet/haiku/opus list prices. Dedupe usage by **max per `message.id`**. Test with a 3-line fixture jsonl + meta.json. `docs/cost-measurement.md`: the export → report loop, and the app card's under-count.

### D2. Spike: CLI-side Plaud transcript fetch — Cowork parity is the gate
Facts established (read-only, 2026-09-17):
- The host-side `@plaud-ai/mcp` 0.3.13 is a real MCP server: it calls `https://platform.plaud.ai/developer/api/open/third-party/files/{fileId}` (whole transcript per recording; `get_transcript` paginates *locally*) and `/open/third-party/users/current`, `Authorization: Bearer` from `~/.plaud/tokens-mcp.json` (`access_token`, `refresh_token`, `expires_at`), refresh = POST form `refresh_token=` to `…/oauth/third-party/access-token/refresh`; its OAuth client id is Plaud's own MCP client.
- Plaud's support page states there is **no public API**; the developer platform ("Plaud Embedded") is a partner transcription API for audio you upload, not an account-data API.
- Cowork's Plaud connector is the remote `https://mcp.plaud.ai/mcp` (OAuth held by the connector platform) — the VM has no token file; the sandbox egress allowlists package hosts only (memory `cowork-provisioning-constraints`).
Deliverables:
- `scripts/spikes/plaud_direct_fetch_probe.py` (stdlib, **read-only GETs, never calls refresh, never prints token bytes**): reports token-file presence + `expires_at`; `GET users/current` status; `GET files/{id}` status/size; optional `--compare <scratch pages…>` asserting the returned utterances equal the MCP pages byte-for-byte; egress result per host. Runs: (1) on this Mac with a DryRunVault recording id — by me, after Michael's go (it uses his token, read-only); (2) in a Cowork session on the DryRunVault folder — by Michael (I cannot open Cowork); expected: no token, 403 on CONNECT.
- `docs/superpowers/specs/2026-09-17-plaud-direct-fetch-spike.md`: findings + the go/no-go against three gates: (a) Cowork VM can reach `platform.plaud.ai`; (b) a credential exists in Cowork that is not the MCP's own rotating token (sharing a refresh-rotating token between two clients breaks the MCP); (c) Plaud sanctions the API for third parties. Fail any → **no-go**, recorded, with the Claude-Code-only variant noted under #133's "ideas for Claude Code deployments" and no plugin change.

---

## Merge order and release
A → B → C → D (D is independent, can land any time). Pre-allocate versions from `main` at merge time; rebase each PR `--onto` the previous squash (memories `release-file-trio-and-merge-mechanics`, `stacked-prs-get-no-ci`). After C: cut a dryrun release (memory `cutting-a-release-from-a-worktree`), `claude plugin update` for DryRunVault, routine restart. Michael merges.

## Verification
Per PR: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`; `/code-review`; contract tests are written **before** the prose/CLI changes (TDD).
End-to-end, after A+B+C are on DryRunVault:
1. Trigger `dryrun-sync-recordings` via `run_scheduled_task`; export the session; `python scripts/cost_report.py <zip>`.
2. Expect: the three looping duplicates appear once under "Cross-adapter duplicates skipped", then never again; `skipped-recordings.txt` gains three `m365:` lines (or seen-events `skipped` entries where the id was not derivable); `last-sync.json` m365 watermark advances; M365 first looks show as probes with **zero** Sonnet workers on a no-transcript day; no `general-purpose` agent in the export; a 2-note run ≤ ~$7 list (baseline $16).
3. After three days: the oversized transcript and the `[]` Plaud recording are parked with reasons; summary named them once.
4. Spike: probe script output from both surfaces pasted into the spec; decision recorded.
