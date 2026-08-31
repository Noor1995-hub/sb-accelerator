# sync-recordings Worker Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Plaud and M365 transcript fetches into the per-recording extraction workers so raw transcripts never enter the orchestrator's context, while preserving the PR #123 dispatch-gate guarantees (triage-filtered dispatch, banked outcomes, single-writer cache).

**Architecture:** Prose redesign of `plugin/skills/sync-recordings/SKILL.md` step 1 (both connector branches stop at dedup/meta), a new worker-only reference file carrying the fetch/reassemble/write mechanics, a rewritten step 6 (dispatch briefing + closed outcome vocabulary + per-batch banking), and rewritten skill-contract tests pinning the new invariants. One small test-infra change (contract tests also scan `references/*.md` for CLI invocations). No vaultlib behavior changes.

**Tech Stack:** Markdown skill prose; pytest contract tests (`scripts/tests/test_skill_contracts.py`); stdlib-only constraints apply to nothing here (no runtime code changes).

**Spec:** `docs/superpowers/specs/2026-08-31-sync-recordings-worker-fetch-design.md`

## Global Constraints

- Baseline is post-PR-#126 main (`4799f42`): Rules section is up front (rules 1–9), payload contract lives in `plugin/skills/sync-recordings/references/payload-contract.md`, `plaud reassemble` cross-checks meta.
- Clean-room rule: nothing under `plugin/` names delaware clients, Michael, busdev paths, or internal issue/PR numbers. Evidence is cited generically ("a live cost analysis found…"), matching existing skill style.
- Plugin version pre-allocation: **0.10.12** (PR #125 is expected to take 0.10.11; verify at Task 7 and take 0.10.11 if #125 died).
- Every commit message ends with the exact trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`
- Local gate before every commit that claims green: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
- The M365 *event* reads (`read_resource` on `calendar:///events/...`) stay orchestrator-side. Only the *transcript* fetch moves. Do not touch `sync m365-triage`, `m365 ids`, `sync dedup`, or any vaultlib module.
- Working branch: `claude/dryrunvault-sync-optimization-b6b9d0` (already carries the spec commit, rebased on main).

---

### Task 1: Rewrite the skill-contract tests to pin the new invariants

**Files:**
- Modify: `scripts/tests/test_skill_contracts.py:227-250` (the two gate tests) and the `test_every_cli_invocation_named_by_a_skill_exists` parametrization (~line 76)

**Interfaces:**
- Consumes: `read_skill(name)` helper and `SKILLS_DIR` constant already defined at the top of the file.
- Produces: test names `test_sync_recordings_dispatches_workers_only_after_triage_and_dedup`, `test_sync_recordings_worker_outcomes_are_a_closed_vocabulary`, `test_sync_recordings_worker_contract_carries_the_fetch_mechanics`, and a `read_ref(skill, name)` helper — Tasks 2–5 make these pass.

- [ ] **Step 1: Add a `read_ref` helper next to `read_skill`**

Find the existing `read_skill` definition in `scripts/tests/test_skill_contracts.py` and add directly below it:

```python
def read_ref(skill: str, name: str) -> str:
    return (SKILLS_DIR / skill / "references" / name).read_text(encoding="utf-8")
```

- [ ] **Step 2: Extend the CLI-invocation check to reference files**

`test_every_cli_invocation_named_by_a_skill_exists` is parametrized over `SKILL_FILES`. Add below the `SKILL_FILES` definition:

```python
REF_FILES = sorted(SKILLS_DIR.glob("*/references/*.md"))
```

and change that test's parametrize decorator to run over `SKILL_FILES + REF_FILES` (keep the test body unchanged — it matches `$VAULTLIB`/`cli.py` invocations and asserts each names a real subcommand).

- [ ] **Step 3: Replace the old dispatch-gate test**

Delete `test_sync_recordings_gates_dispatch_on_a_fetched_transcript` (lines ~236-250) **including its `# #122:` comment block**, and add in its place:

```python
# The #122 failure shape — a fleet of extraction subagents each paid ~62k
# tokens to learn "nothing to write" — is prevented by triage + dedup gating
# dispatch and by workers fetching FIRST (a negative is a first-tool-call
# exit), not by centralizing fetches. The orchestrator stays the seen-events
# cache's only writer.
def test_sync_recordings_dispatches_workers_only_after_triage_and_dedup():
    text = read_skill("sync-recordings")
    assert "survived triage" in text, (
        "the dispatch gate must condition dispatch on triage + dedup")
    assert '"forbidden"' in text, (
        "a cross-tenant 403 needs a recorded outcome or it refetches forever")
    dispatch = text.index("### 6.")
    assert text.index("sync m365-record") < dispatch, (
        "no-transcript-url and skipped outcomes are banked before dispatch")
    assert text.rindex("sync m365-record") > dispatch, (
        "batch outcomes are banked after workers return")


def test_sync_recordings_worker_outcomes_are_a_closed_vocabulary():
    text = read_skill("sync-recordings")
    for token in ("written:", "no-transcript", "forbidden",
                  "fetch-error", "auth-error", "possible-duplicate-of"):
        assert token in text, f"outcome vocabulary is missing {token}"
    assert "never writes the seen-events cache" in text, (
        "the single-writer rule must be stated")


def test_sync_recordings_worker_contract_carries_the_fetch_mechanics():
    text = read_skill("sync-recordings")
    assert "references/worker-contract.md" in text, (
        "step 6 must point workers at the contract file")
    step1 = text.split("## The three adapters")[1].split("### 6.")[0]
    assert "Never call" in step1 and "mcp__plaud__get_transcript" in step1, (
        "step 1 must forbid the orchestrator fetching")
    assert "next_cursor" not in step1, (
        "pagination mechanics belong to the worker contract, not step 1")
    ref = read_ref("sync-recordings", "worker-contract.md")
    for phrase in ("next_cursor", "transcript_url", "plaud reassemble",
                   "m365 reassemble", "sync collide", "meeting write",
                   "payload-contract.md", "verbatim"):
        assert phrase in ref, f"worker contract is missing {phrase}"
```

- [ ] **Step 4: Run the contract tests to verify the new ones fail and nothing else broke**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: exactly the three new tests FAIL (`survived triage` absent; `fetch-error` absent; `worker-contract.md` missing → `FileNotFoundError` in `read_ref`). `test_sync_recordings_triages_m365_before_the_fetch` and all others still PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_skill_contracts.py
git commit -m "test: pin worker-fetch dispatch invariants for sync-recordings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Create `references/worker-contract.md`

**Files:**
- Create: `plugin/skills/sync-recordings/references/worker-contract.md`

**Interfaces:**
- Consumes: `references/payload-contract.md` (exists, unchanged).
- Produces: the file step 6's briefing points workers at; the outcome-line vocabulary Tasks 4–5 repeat in SKILL.md must match this file exactly.

- [ ] **Step 1: Write the file with exactly this content**

````markdown
# Worker contract (fetch, extract, write — one recording)

You are the worker for exactly one recording. Fetch its transcript, write
every raw page to scratch verbatim, reassemble, check for a cross-adapter
duplicate (M365), extract against the payload contract, write the note, and
verify it on disk. Your reply is **one outcome line from the table at the
bottom — nothing else**: never transcript, blob, or payload text. Your
prompt carries the vault root, the scratch directory (`$SCRATCH`), the CLI
path (`$VAULTLIB`), the timezone, your recording's reference, its scratch
stem (`rec_N` / `m365_<hex>`), and every routing decision already made —
copy those into the payload unchanged.

Scratch filenames must match the stems you were given: `scratch sweep`
deletes by pattern (`rec_*.json`, `m365_*.json`, `*.blob.md`,
`*.payload.json`), and a file named outside the patterns outlives the run.

## Fetching — Plaud

`mcp__plaud__get_transcript` is paginated: it answers `limit` utterances at
a time (50 by default) and reports `total`, `offset` and `next_cursor`.
Call again with the returned `cursor` until `next_cursor` comes back
**null** (the last page carries the key with a null value, it does not omit
it). Write **every** page to its own scratch file
(`rec_N.transcript.01.json`, `.02.json`, …) — the tool result's content
verbatim, never condensed, summarized, or re-typed; the pagination fields
(`offset`, `returned`, `total`, `next_cursor`) are facts about what the
connector sent and are never edited.

If a page is too large for the tool result, the harness spills it to a file
under `~/.claude/projects/…/tool-results/`. Do not go near that path — not
to read, copy, or delete. Halve `limit` and re-fetch from the same `cursor`
instead.

On a transient error retry up to 3×, then reply `fetch-error`. On a **401**,
reply `auth-error` — re-authentication is interactive and belongs to the
user; never retry auth in a loop. `mcp__plaud__get_note` is optional
enrichment (write it to `rec_N.note.json`); on failure proceed without.

## Fetching — M365

One `read_resource` call on the `transcript_url` you were given, **exactly
as given** — never rebuild or re-scope the URL; a recurring series answers
a rebuilt, unscoped URL with other occurrences' transcripts. Write the raw
result to `$SCRATCH/m365_<hex>.transcript.json` verbatim. Then:

- `NOT_FOUND` with `transcripts_empty` → reply `no-transcript` (transcription
  was off for that meeting — settled, not an error).
- **403/Forbidden** → reply `forbidden` (another organization's tenant owns
  it, permanently).
- A transport error, or a result too large for the tool result → reply
  `fetch-error`.

You make no other Graph call — not the event, not the calendar, not another
occurrence.

## Reassemble

One call, matching your adapter — the meta/event files already exist at the
paths you were given:

```bash
python3 "$VAULTLIB" plaud reassemble \
  --meta "$SCRATCH/rec_N.meta.json" \
  --transcript "$SCRATCH"/rec_N.transcript.*.json \
  --note "$SCRATCH/rec_N.note.json" \
  --out "$SCRATCH" --timezone <timezone from your prompt>
```

```bash
python3 "$VAULTLIB" m365 reassemble --event "$SCRATCH/m365_event_<n>.json" \
  --transcript "$SCRATCH/m365_<hex>.transcript.json" \
  --out "$SCRATCH" --timezone <timezone from your prompt>
```

The result names the blob file and carries `recording_id`, `duration_min`,
and `recorded_local` — an ISO stamp `meeting write` (`date`) and
`sync collide` (`--start`) both take **verbatim**. A refusal means a page is
missing or inconsistent: re-fetch by cursor, never edit counts to satisfy
the validator — if you cannot complete the set, reply `fetch-error`. Include
any `warnings` from the result at the end of your outcome line, verbatim.

An inbox item has no fetch and no reassemble: read the file you were given;
its `date` and `source-recording-id` arrive in your prompt.

## Collision check (M365 only)

Before writing, check whether another adapter already captured this
conversation:

```bash
python3 "$VAULTLIB" sync collide --vault "$VAULT" \
  --start <recorded_local> --duration-min <duration_min>
```

A match whose `source-recording-id` carries another namespace — or one
flagged `imprecise: true` — means a probable duplicate. **Draft the payload
anyway** (next section), but do **not** call `meeting write`: reply
`possible-duplicate-of: <existing stem> (payload at $SCRATCH/<stem>.payload.json)`
and stop. The orchestrator decides with the user and can write your payload
without re-extraction.

## Extract and write

Read `references/payload-contract.md` (its path is in your prompt) and draft
the payload to `$SCRATCH/<stem>.payload.json`: content fields from the
transcript; every routing field copied from your prompt unchanged; `date` is
`recorded_local` unchanged and `recording-duration` is `duration_min`. When
your prompt says routing signals 1–2 were inconclusive and carries the
project/entity slug catalog, match transcript keywords against it yourself —
it is the weakest signal, so a match adds the project with the lower
confidence your prompt already stamped, and no match means `projects: []`.

```bash
python3 "$VAULTLIB" meeting write --vault "$VAULT" --note "$SCRATCH/<stem>.payload.json"
```

If `meeting write` refuses, fix the payload per the `error` and `hint` and
retry — the contract names every rule. Read the result: `conflict` of kind
`confirmed-target` or `stem-collision` still counts as written — mention it
in your outcome line. Verify the result's `path` exists on disk before
replying `written:`.

## The outcome line (your entire reply)

| Line | When |
|---|---|
| `written: <note stem>` | note verified on disk (append any reassemble warnings / conflict kind) |
| `no-transcript` | M365: `transcripts_empty` |
| `forbidden` | M365: 403 — permanent |
| `fetch-error: <one clause why>` | transport failure, incomplete page set, oversized result — retries next run |
| `auth-error` | connector wants re-authentication — the adapter should stop |
| `possible-duplicate-of: <stem> (payload at <path>)` | collision found; payload drafted, nothing written |
````

- [ ] **Step 2: Run lint + the worker-contract test**

Run: `python scripts/lint_plugin.py && python -m pytest scripts/tests/test_skill_contracts.py::test_sync_recordings_worker_contract_carries_the_fetch_mechanics -q`
Expected: lint PASS (clean-room: file names no client, no person, no issue numbers). Test still FAILS — but now only on the two SKILL.md assertions (`references/worker-contract.md` not yet referenced; `get_transcript` still in step 1), not on `FileNotFoundError`.

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/sync-recordings/references/worker-contract.md
git commit -m "feat: worker contract for per-recording fetch and write

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: SKILL.md — the Plaud branch stops at meta

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md:254-304` (from "Only `new` ids proceed…" through the Plaud-401 paragraph; keep the meta-write paragraph at 249-252 and the timezone paragraph at 306-309)

**Interfaces:**
- Consumes: rule 7/8/9 wording (unchanged), `$SCRATCH/rec_N.meta.json` convention from #126.
- Produces: step-1 Plaud prose with no fetch instructions; step 6 (Task 5) references "the listing metadata already in `rec_N.meta.json`".

- [ ] **Step 1: Replace lines 254–304 (the five paragraphs from "Only `new` ids proceed" through "…belongs to the user.") with:**

```markdown
That is where this context's Plaud work ends. **Never call
`mcp__plaud__get_transcript` or `mcp__plaud__get_note` yourself** — the
fetch, pagination, reassembly, extraction and write all happen inside the
per-recording worker step 6 dispatches, following
`references/worker-contract.md`. A transcript that entered this context
would be re-read by every request that follows; a live cost analysis
measured exactly that as most of a long run's bill. Routing (step 3) works
from the listing metadata and the calendar; when it needs transcript
keywords, the worker matches them itself (signal 3).
```

Keep the reassemble bash block OUT of step 1 (it moved to the worker contract). Keep the timezone paragraph ("The vault owner's timezone is `timezone` from `config read`…") — reword its second sentence to end: "…cannot run: skip them with an explicit line — the timezone rides into every worker briefing."

- [ ] **Step 2: Run the invocation + gate tests**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: `test_every_cli_invocation_named_by_a_skill_exists` PASSES for both SKILL.md and worker-contract.md. The three new tests still fail (M365 + step 6 not yet rewritten).

- [ ] **Step 3: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md
git commit -m "fix: sync-recordings plaud branch hands fetching to workers

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: SKILL.md — the M365 branch settles listings, workers settle transcripts

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md:365-455` (transcript-fetch paragraph, settled-outcomes block, reassemble block, collide block, dispatch-gate paragraph; keep 311–364 — search, triage, event reads, `m365 ids`, dedup — untouched, and keep the routing pre-fill paragraph at 436–446)

- [ ] **Step 1: Replace the transcript-fetch paragraph (365–373) and the settled-outcomes block (375–398) with:**

```markdown
**Bank what the listing already settled — before any worker exists** — so
the next run's triage answers for them without a fetch, even if this run
dies mid-dispatch. Write one JSON array to
`$SCRATCH/m365_outcomes_settled.json` with the Write tool, one entry per
occurrence, keyed by the `id` and `start_utc` the triage result carried:

- `"outcome": "no-transcript"` — the event carried no `meetingTranscriptUrl`
  (`m365 ids` skipped it);
- `"outcome": "skipped"` — the id went onto the never-propose-again list
  (`sync skip`), here or on an earlier run.

```bash
python3 "$VAULTLIB" sync m365-record --vault "$VAULT" \
  --outcomes "$SCRATCH/m365_outcomes_settled.json"
```

The transcript itself is never fetched in this context. The worker step 6
dispatches makes the one `read_resource` call on its occurrence's
`transcript_url` — passed to it **exactly as `m365 ids` returned it** — and
what it finds comes back as its outcome line: `"forbidden"` (a 403 —
another organization's tenant owns the transcript, permanently),
`no-transcript` (`transcripts_empty` — transcription was off), or a written
note. Those outcomes are banked per batch in step 6. A recording that
*failed* — a transport error — gets **no outcome line**, and neither does a
cross-adapter duplicate deferred under `--unattended`: what is not settled
is not recorded, and the occurrence surfaces again next run.
```

- [ ] **Step 2: Delete the per-occurrence reassemble block (400–410) and the collide block (412–434)** — both moved into `references/worker-contract.md`. The `sync skip` sentence from the collide block survives in step 6 (Task 5 carries it).

- [ ] **Step 3: Replace the dispatch-gate paragraph (448–455) with:**

```markdown
**The dispatch gate.** A worker is dispatched only for an occurrence that
survived triage (`sync m365-triage`) and dedup (`sync dedup`) — never to
discover whether a transcript exists for anything else. Each worker makes
exactly the connector calls for its one assigned recording, and a negative
answer is its first tool call, costing a skip, not an extraction — that,
plus triage, is what keeps a fleet of workers from ever being paid to learn
"nothing to write". A worker **never writes the seen-events cache**: every
settled outcome comes back as one line, and you bank each batch's lines in
one `sync m365-record` call the moment the batch returns (step 6). An id
`sync dedup` reported as already `synced` still gets a `written` outcome
banked there — that is how the cache back-fills for meetings synced before
it existed.
```

(Delete the now-duplicated back-fill sentence from the dedup paragraph at 361–363.)

- [ ] **Step 4: Run the gate tests**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: `test_sync_recordings_dispatches_workers_only_after_triage_and_dedup` PASSES (both `sync m365-record` occurrences exist once Task 5 lands the batch-banking call — if it still fails on `rindex`, that is correct until Task 5). `triages_m365_before_the_fetch` PASSES.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md
git commit -m "fix: sync-recordings m365 branch banks listing-settled outcomes only

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: SKILL.md — step 6 dispatches fetch-workers; step 3 signal-3 delegation; summary

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` — step 3 signal list (~490-497), step 6 entire section, step-7 summary template ("M365 subagents dispatched" line), spec table sync
- Modify: `docs/superpowers/specs/2026-08-31-sync-recordings-worker-fetch-design.md:§3` — add the `auth-error` row to the outcome table (deviation found during planning: a Plaud 401 must stop the adapter, not read as a per-recording retry)

- [ ] **Step 1: Rewrite step 3's signal 3 (line ~496-497) to:**

```markdown
3. Transcript content keywords against project names and slugs (lower
   confidence) — the worker's signal, not yours: no transcript exists in
   this context. When signals 1–2 are inconclusive, the step-6 briefing
   carries the project/entity slug catalog and the worker matches transcript
   keywords against it itself.
```

- [ ] **Step 2: Rewrite step 6.** Replace the section body from "For each recording — **also when there is only one** (rule 7)…" down to (but not including) "**Then sweep what you wrote.**" with:

```markdown
For each recording that survived step 1 — **also when there is only one**
(rule 7) — dispatch a worker, up to ~4 in parallel, blocking, spawned with
`model: sonnet`. The worker fetches its own transcript, reassembles,
extracts, writes, and replies with one outcome line; its mechanics live in
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/references/worker-contract.md`
and the payload schema in
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/references/payload-contract.md`.
**You read neither file yourself.** The schema and the transcript staying
out of this context is what keeps this step's cost flat as the number of
recordings grows.

Pass each worker *paths and decisions*, not content:

- both contract paths above, `$VAULT`, `$SCRATCH`, the `$VAULTLIB` path,
  and the vault timezone;
- its recording reference and scratch stem: Plaud — the file id and
  `$SCRATCH/rec_N.meta.json`; M365 — `$SCRATCH/m365_event_<n>.json` and the
  `transcript_url` from `m365 ids`, verbatim; inbox — the file's path, its
  `recording_id` from `sync scan`, and its date read from the file's own
  content or header;
- the routing you decided: `projects`, attendee slugs, `confidence` +
  `confidence-reasons`, `calendar_match`, `calendar-subject` (always
  non-empty — the matched event's subject, or the item's own subject or a
  short descriptive title), whichever of `organizer`/`location`/
  `recurring`/`attendee-emails` are known, `source`,
  `source-recording-id`, and the step-1 classification (`type: note` for a
  capture; otherwise the worker picks the meeting subtype from the
  transcript). `date` and `recording-duration` the worker derives from its
  own `reassemble` result — pass them only for inbox items and captures;
- `entities`, but only when `projects` is empty (step 3);
- when routing signals 1–2 were inconclusive: the project/entity slug
  catalog, for worker-side signal-3 matching.

**Never poll a batch with no-op Bash.** A live cost analysis of the evening
pipeline found 362 of 423 requests in one run were idle `Bash(true)` /
`sleep` / `echo waiting` polls babysitting a background subagent batch —
each poll re-reads the entire session context, and that alone was most of
that run's bill. A **blocking** spawn already returns when the worker
finishes. Spawn each batch (up to ~4) as blocking calls, or sequentially —
never spawn in the background and then loop checking on it.

**When a batch returns, act on each line, then bank.**

- `written: <stem>` — count it; step 7 verifies from disk anyway.
- `no-transcript` / `forbidden` — settled negatives.
- `fetch-error` — no outcome line is banked; it retries next run.
- `auth-error` — stop dispatching that adapter's remaining recordings and
  report it; re-authentication belongs to the user.
- `possible-duplicate-of: <stem> (payload at <path>)` — the ledger keys on
  exact ids, so it cannot see one conversation captured twice across
  adapters; the worker's window check can, and it drafted its payload
  without writing. Interactively: show both notes and ask once — "write it
  anyway" is `meeting write --vault "$VAULT" --note "<path>"` right here,
  no re-extraction; "drop it" is `sync skip --id m365:<hex> --reason "same
  meeting already synced as <existing id>"`, which banks as a `"skipped"`
  outcome. Under `--unattended`: neither — count it in the summary's
  cross-adapter duplicates line; it defers until an interactive run
  settles it, and that is the safe direction.

Then write the batch's settled lines — `written` (with each
`recording_id`), `no-transcript`, `forbidden`, `skipped` — one entry per
occurrence, keyed by the `id` and `start_utc` the triage result carried, to
`$SCRATCH/m365_outcomes_batch.json`, and bank them before dispatching the
next batch:

```bash
python3 "$VAULTLIB" sync m365-record --vault "$VAULT" \
  --outcomes "$SCRATCH/m365_outcomes_batch.json"
```

The cache merges across calls; Plaud and inbox outcomes have no cache and
feed only the summary. Banking per batch keeps the maximum crash loss to
one batch — one cheap worker-side re-fetch next run.
```

Then **delete** the old post-return prose that this replaces: the "Each subagent returns one fenced payload JSON…" block, its `meeting write` bash block, the "If `meeting write` refuses…" paragraph, and the old "**Then bank the M365 `written` outcomes.**" block near the end of step 6 (batch banking above replaces it). Keep "**Then sweep what you wrote.**" and its `sync archive` block (inbox-only, orchestrator-side, verified-from-disk) — reword its first sentence to "For each inbox-sourced recording whose worker replied `written:` with a note verified on disk…".

- [ ] **Step 3: Update the step-7 summary line** `**M365 subagents dispatched:** …` to:

```markdown
**Workers dispatched:** {N} ({N} plaud · {N} m365 · {N} inbox) — m365 candidates not dispatched had no transcript URL yet ({N}), were already in the vault ({N}), or were answered by the cache ({N}); worker outcomes: {N} written · {N} no-transcript · {N} forbidden · {N} fetch-error
```

- [ ] **Step 4: Add the `auth-error` row to the spec's §3 outcome table** in `docs/superpowers/specs/2026-08-31-sync-recordings-worker-fetch-design.md`: `| `auth-error` | connector wants re-authentication; orchestrator stops dispatching that adapter |` with a one-line note that planning surfaced it (a Plaud 401 is an adapter-stop, not a retry).

- [ ] **Step 5: Full local gate**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: ALL PASS, including all three Task-1 tests and every pre-existing contract test (`sweeps-the-inbox`, `parks-through-the-one-call`, `scratch-hygiene`, `summaries-speak-plainly` — if any of these fails, the rewrite dropped a phrase it pins; restore the phrase, do not weaken the test).

- [ ] **Step 6: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md docs/superpowers/specs/2026-08-31-sync-recordings-worker-fetch-design.md
git commit -m "feat: sync-recordings workers fetch their own transcripts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Release trio

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json` (version → `0.10.12`)
- Modify: `scripts/tests/test_marketplace_manifest.py` (the version assertion → `0.10.12`)
- Modify: `CHANGELOG.md` (Unreleased section)

- [ ] **Step 1: Bump both version sites** (`plugin.json` `"version"` and the assertion in `test_marketplace_manifest.py`).

- [ ] **Step 2: Add the CHANGELOG line under `## Unreleased`:**

```markdown
- `/sync-recordings` now fetches each transcript inside its per-recording worker instead of the main session — long-context cost and latency drop sharply on multi-recording syncs, and recordings process in parallel (#PR)
```

(`#PR` is backfilled in Task 7 once the PR number exists.)

- [ ] **Step 3: Run the full gate and commit**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: ALL PASS.

```bash
git add plugin/.claude-plugin/plugin.json scripts/tests/test_marketplace_manifest.py CHANGELOG.md
git commit -m "chore: bump plugin to 0.10.12; changelog for worker fetch

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Rebase on post-#125 main, open the PR

- [ ] **Step 1: Check #125's state**

Run: `gh pr view 125 --repo DLW-INT-BTA-BELUX/sb-accelerator --json state,mergeCommit`
- MERGED → `git fetch origin main && git rebase origin/main`. Expect conflicts in the release trio (take main's side, re-apply 0.10.12 — if #125 merged at a version ≥ 0.10.12, take the next patch number in all three sites) and possibly in SKILL.md's M365 *search* paragraph (#125 edits the search window/pagination wording; ours starts at the settled-outcomes block — merge both, they touch adjacent but distinct paragraphs).
- OPEN → ask Michael whether to wait or open now and rebase later; do not silently proceed.
- CLOSED (unmerged) → re-bump all three version sites to `0.10.11` and amend the Task 6 commit.

- [ ] **Step 2: Verify the base honestly after any rebase** (lesson from a previous squash-merge): `git diff origin/main...HEAD --stat` must list only this plan's files.

- [ ] **Step 3: Full gate once more**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: ALL PASS.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin claude/dryrunvault-sync-optimization-b6b9d0
gh pr create --repo DLW-INT-BTA-BELUX/sb-accelerator --base main \
  --title "feat: sync-recordings workers fetch their own transcripts" \
  --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-08-31-sync-recordings-worker-fetch-design.md.

Transcript fetches (Plaud pagination, M365 read_resource) move into the
per-recording extraction workers; the orchestrator settles which occurrences
to attempt (triage + dedup + event reads) and banks every outcome per batch
as the seen-events cache's only writer. The #123 gate's guarantees survive
under a new mechanism: dispatch-only-after-triage, first-tool-call negative
exits, single-writer banking. Measured motivation: a 4-recording run at 23
min / ~$6 with a 467k-token orchestrator context, most of it transcripts
re-read on every request.

- New references/worker-contract.md (worker-only reading, like the payload contract)
- SKILL.md step 1 both connector branches stop at dedup/meta; step 6 dispatches fetch-workers with a closed outcome vocabulary
- Contract tests rewritten to pin the new invariants; CLI-invocation check now also scans references/*.md
- Plugin 0.10.12

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Backfill the PR number** into the CHANGELOG line, amend the Task 6 commit or add `chore: backfill PR number into changelog line`, push.

- [ ] **Step 6: Report** — CI status, PR link, and the reminder that this changes runtime behavior of a skill: the merge gate is Michael's, and a DryRunVault E2E run (spec §10: mixed Plaud+M365 batch with one known-negative and one cross-adapter duplicate; verify flat orchestrator context and banked outcomes) belongs before merge.

---

## Verification (spec §10 traceability)

- Spec §3 worker contract → Task 2 (+ `auth-error` extension, Task 5 Step 4)
- Spec §4 orchestrator flow → Tasks 3–5
- Spec §5 routing split → Task 5 Step 1 + worker-contract "Extract and write"
- Spec §6 collision → worker-contract "Collision check" + Task 5 batch-return handling
- Spec §7 Option A banking → Task 4 Step 1 + Task 5 batch banking
- Spec §8 gate rewording + test rewrite → Task 4 Step 3 + Task 1
- Spec §9 known limitation → worker-contract M365 `fetch-error` for oversized results (unchanged dead end, now out of main context)
- Spec §11 sequencing → Task 7
