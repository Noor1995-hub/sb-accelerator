# sync-recordings: per-recording worker fetch — design

**Date:** 2026-08-31
**Status:** approved design, awaiting implementation plan
**Supersedes (partially):** the M365 dispatch-gate mechanism from PR #123
(the gate's *guarantees* are preserved; its *mechanism* changes — see §6).
**Depends on:** the sync-recordings hardening PR (fan-out rule moved to the
skill's opening rules; verbatim-or-stop transcript rule; CLI-call batching
guidance) landing first. This design rebases on that text.

## 1. Problem

A measured interactive `/sync-recordings` run (2026-08-31, 4 short Plaud
recordings + 2 usable M365 transcripts) took 23 minutes and ~$6:

- The orchestrator context grew 74k → 467k tokens. 15.6M cache-read tokens —
  over half the bill — were the same transcripts re-read on every one of 55
  requests, plus long-context premium past 200k.
- ~700 of 1390 seconds were model-response latency at 300–460k context.
- Every transcript byte necessarily transits main context **twice** under the
  current skill: once as an MCP tool result (Plaud `get_transcript` pages,
  M365 `read_resource`), once re-emitted as a scratch `Write`. Step 6's
  extraction subagents cannot fix this: the skill requires the orchestrator
  to fetch every transcript before any subagent exists.

An earlier run of the same skill took 62 minutes. This is the skill's shape,
not a bad day.

## 2. Goals and non-goals

**Goals**

- Raw transcript content never enters the orchestrator's context, for both
  adapters (Plaud and M365).
- Preserve the three guarantees behind PR #123's dispatch gate:
  1. *Economics* — never pay a full extraction dispatch to learn "nothing to
     write" (the #122 pathology: 15 subagents × ~62k tokens, 0 notes).
  2. *Crash-safety* — settled availability outcomes are banked in the
     seen-events cache promptly, so a run that dies mid-extraction does not
     lose paid-for answers (bounded loss accepted, see §7).
  3. *Central accounting* — the seen-events cache has exactly one writer.
- Recordings process in parallel (up to ~4), not serially.
- Target profile for the measured workload: orchestrator context ≤ ~150k,
  6–9 minutes, roughly a third of the current cost.

**Non-goals**

- No change to the vault ledger, dedup semantics, `meeting write` contract,
  or the seen-events cache file format.
- No CLI locking / concurrent-writer support (ruled out by §7 Option A).
- No fix for the oversized-M365-transcript overflow case (§9).

## 3. The worker contract

One subagent per recording, identical shape for both adapters. Spawned
**blocking**, `model: sonnet`, in batches of up to ~4 in parallel. The batch
cap is a throttling/burst guardrail — Graph throttles per user, and a batch
bounds the burst token spend on the client's bill — not a measured optimum;
it is tunable if Graph proves tolerant.

**Briefing (input), per recording:**

- The recording reference:
  - Plaud: the file id and its listing metadata.
  - M365: the path of its event JSON already in `$SCRATCH`, plus the exact
    `transcript_url` from `m365 ids` — passed verbatim, never rebuilt
    (a rebuilt, unscoped URL answers with other occurrences' transcripts).
- The routing already decided by the orchestrator: `projects`, attendee
  slugs, confidence stamp, calendar fields (§5).
- When routing signals 1–2 were inconclusive: the project/entity slug
  catalog, for worker-side signal-3 matching (§5).
- The payload contract and scratch naming rules (names must match
  `scratch sweep`'s built-in patterns, as today).
- The verbatim-or-stop transcript rule from the hardening PR: scratch pages
  are verbatim tool-result content; `offset`/`returned`/`total` are never
  edited; a refused reassembly means a missing page to re-fetch.

**Job:** fetch its one transcript (Plaud: paginate `get_transcript` until
`next_cursor` is null, halving `limit` on tool-result overflow; M365: one
`read_resource` on the given `transcript_url`), write every raw page
verbatim to `$SCRATCH`, `reassemble`, run `sync collide`, then
`meeting write`, and verify the note on disk.

**Return (output): one line from a closed vocabulary, never transcript or
payload text:**

| Line | Meaning |
|---|---|
| `written: <stem>` | note verified on disk |
| `no-transcript` | M365: fetch answered `transcripts_empty` (NOT_FOUND) |
| `forbidden` | M365: 403 — another tenant owns it, permanent |
| `fetch-error` | transport failure after retries; retries next run |
| `possible-duplicate-of: <stem> (payload at <path>)` | collision; did not write (§6) |

A worker never asks a question (subagents cannot), never makes a Graph or
Plaud call for any recording other than its own, and never touches the
seen-events cache.

## 4. Orchestrator flow (what step 1 becomes)

**Unchanged, orchestrator-side:** config read, account-binding gates,
`reconcile-reviews`, inbox scan and classification, Plaud `list_files`,
M365 calendar search, **full event reads** (small — a few KB each — and
triage, dedup and routing all need them), `sync m365-triage`, `m365 ids`,
`sync dedup`, calendar enrichment for Plaud recordings (the `list_files`
timestamps give the query window; no transcript needed), `person ensure`,
the interactive plan confirmation, the summary, and the unattended run-log
line. The plan confirmation runs **before dispatch** and is built from what
the orchestrator holds — listing metadata, calendar fields, routing,
confidence — not from reassembled data, which now exists only worker-side.

**Moved into workers:** every transcript fetch, every scratch transcript
write, `plaud reassemble` / `m365 reassemble`, `sync collide`,
`meeting write`, on-disk verification.

**New orchestrator step — banking:** after each batch returns, collect all
outcome lines and write them in **one** `sync m365-record` call — negative
settlements (`no-transcript`, `forbidden`, plus any `skipped` decided
interactively) and `written` outcomes together; the cache merges across
calls. `fetch-error` and deferred duplicates get no outcome line, exactly as
today: what is not settled is not recorded. Plaud outcomes have no cache;
`written`/`fetch-error` lines feed the summary only.

The `no-transcript-url` skips from `m365 ids` are settled before any
dispatch, as today — those occurrences never reach a worker.

## 5. Routing split

The orchestrator still decides routing, in the current signal order, from
what it has:

1. External attendee email domains → entity (calendar/event data).
2. Calendar subject keywords → project.

Signal 3 (transcript-content keywords) needs the transcript, which the
orchestrator no longer holds. When signals 1–2 are inconclusive, the
briefing carries the project/entity slug catalog and the *worker* performs
signal-3 matching against the transcript it fetched, stamping the lower
confidence that signal already carries. Signal 3 remains the weakest signal
and `projects: []` remains a valid outcome — under-routing beats wrong
routing, and triage catches the unassigned.

## 6. Collision handling and the interactive gap

`sync collide` runs in the worker (it produces `recorded_local` and
`duration_min` there). Clean check → write. Match → the worker does **not**
write, but its payload JSON is already on disk in `$SCRATCH`, so it returns
`possible-duplicate-of: <stem> (payload at <path>)`.

- Interactive: the orchestrator shows both notes and asks once. "Write it
  anyway" → the orchestrator runs `meeting write --note <payload>` itself —
  no re-extraction, no second worker. "Drop it" → `sync skip` with the
  user's reason, and (M365) a `skipped` outcome line in the next banking
  call.
- `--unattended`: defer — no write, no skip, counted in the summary — as
  today.

An `imprecise: true` match surfaces the same way and is never auto-resolved.

## 7. Outcome banking and crash semantics (Option A)

The orchestrator is the cache's only writer. Accepted trade-off: if the run
dies after a worker settled an outcome but before the orchestrator banked
it, that answer is lost and the next run re-fetches it — inside a worker, at
worker prices (a negative is a first-tool-call exit, ~5–10k tokens). The
crash window is seconds wide per batch. The alternative (workers call
`sync m365-record` themselves) was rejected: it puts up to 4 concurrent
read-modify-write cycles on one cache file, and fixing that means file
locking in stdlib-only vaultlib — real complexity for a marginal gain.

Bank **after each batch**, not once at the end of the run: that keeps the
maximum loss to one batch and matches the #123 principle that answers a
fetch paid for are recorded as soon as practically possible.

## 8. The dispatch gate, reworded

The current rule — "a subagent never makes a Graph call, never fetches a
transcript" — is replaced by:

> A worker makes exactly the connector calls for its one assigned recording,
> and is dispatched only for an occurrence that survived triage and dedup.
> Discovering a negative is a first-tool-call exit. Every settled outcome is
> returned as one line and banked by the orchestrator; a worker never writes
> the seen-events cache.

What prevents a #122 regression is no longer "the orchestrator fetched
first" but: (a) `sync m365-triage` filters known-dead occurrences before
dispatch — the cache did not exist when #122 happened; (b) a fetch-first
worker's negative costs ~5–10k tokens, not ~62k, because the fetch is its
first action and the extraction contract is never exercised; (c) terminal
outcomes (`forbidden`, final `no-transcript`) stop costing anything from the
next run onward.

The skill-contract test from PR #123 pins the *current* wording and must be
rewritten to pin the new invariants instead: dispatch-only-after-triage-and-
dedup stated; the closed outcome vocabulary present; the single-writer rule
("a worker never writes the seen-events cache") stated; banking appearing
after batch return.

## 9. Known limitation (unchanged by this design)

An M365 transcript too large for a tool result overflows to a harness file
under `~/.claude` that neither orchestrator nor worker may touch, and
`read_resource` has no pagination. Such an occurrence still cannot be
processed or settled; it re-fetches (now worker-side, so cheaply and out of
main context) each run. Tracked separately; this design only moves where the
dead end happens.

## 10. Testing

- Skill-contract tests (`scripts/tests`): rewrite the PR #123 gate test per
  §8; add assertions that the worker briefing/return vocabulary and the
  batch-banking rule are stated in SKILL.md.
- No vaultlib behavior changes are required by this design, so no new CLI
  unit tests beyond what the hardening PR adds (`plaud reassemble`
  cross-check).
- E2E: one interactive DryRunVault run over a mixed batch (Plaud + M365,
  including at least one known-negative occurrence and one cross-adapter
  duplicate), verifying: orchestrator context stays flat (no transcript text
  in main context), outcomes banked, duplicate deferred/resolved correctly,
  notes extracted from full transcripts.

## 11. Sequencing

1. Hardening PR (fan-out rule hoisting, verbatim-or-stop, batching guidance)
   lands first — in flight in a separate session.
2. This design's PR rebases on it: SKILL.md step-1/step-6 restructure, gate
   rewording, skill-contract test rewrite, CHANGELOG line, plugin version
   bump.
3. DryRunVault E2E run before merge, per the visual/E2E conventions.
