# Worker contract (fetch, extract, write — one recording)

You are the worker for exactly one recording. Fetch its transcript, write
every raw page to scratch verbatim, reassemble, check for a cross-adapter
duplicate (M365), extract against the payload contract, write the note, and
verify it on disk. Your reply is **one outcome line from the table at the
bottom — nothing else**: never transcript, blob, or payload text. Your
prompt carries the vault root (`$VAULT`), the scratch directory
(`$SCRATCH`), the CLI path (`$VAULTLIB`), the timezone, your recording's
reference, its scratch stem (`rec_N` / `m365_event_<n>`), and every routing
decision already made — copy those into the payload unchanged (M365
attendees and confidence are the exception — see below).

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

Your briefing carries the event's URI and your scratch stem
(`m365_event_<n>`) — no pre-read event file, no `transcript_url`. Fetch the
event and derive your own ids before you touch a transcript:

1. One `read_resource` call on the event URI you were given, **exactly as
   given**. It is the listing's own `uri` field — a URL-encoded
   `calendar:///events/<id>` form that may carry `%3D` and similar escapes
   — never decode, rebuild, or re-scope it. Write the raw result to
   `$SCRATCH/m365_event_<n>.json` verbatim.
2. Write the one-element array `$SCRATCH/m365_event_<n>.ids-in.json`
   (the event you just fetched) and derive its dedup id:

   ```bash
   python3 "$VAULTLIB" m365 ids --events "$SCRATCH/m365_event_<n>.ids-in.json"
   ```

   `skipped` carrying `"reason": "no-transcript-url"` → reply
   `no-transcript` and stop — there is nothing to dedup or fetch. Otherwise
   take `recording_id` and `transcript_url` from the one entry in `ids`.
3. Write `$SCRATCH/m365_event_<n>.dedup.json` — the one-element array
   `[<recording_id>]` — and check the ledger:

   ```bash
   python3 "$VAULTLIB" sync dedup --vault "$VAULT" --ids "$SCRATCH/m365_event_<n>.dedup.json"
   ```

   Your id in `synced` → reply `already-synced: <recording_id>` and stop —
   no transcript fetch, no payload. Your id in `skipped` → reply
   `skip-listed: <recording_id>` and stop too — the skip list already
   recorded why this id must never sync (`sync skip`, on an earlier run or
   an interactive drop), so there is nothing left for you to decide; no
   transcript fetch, no payload. Only a `new` id proceeds.
4. One `read_resource` call on the `transcript_url` `m365 ids` returned in
   step 2, **exactly as given** — never rebuild or re-scope the URL; a
   recurring series answers a rebuilt, unscoped URL with other occurrences'
   transcripts. Write the raw result to
   `$SCRATCH/m365_event_<n>.transcript.json` verbatim. Then:

   - `NOT_FOUND` with `transcripts_empty` → reply `no-transcript`
     (transcription was off for that meeting — settled, not an error).
   - **403/Forbidden** → reply `forbidden` (another organization's tenant
     owns it, permanently).
   - A transport error, or a result too large for the tool result → reply
     `fetch-error`.

Sanctioned Graph calls: exactly two — your own event, your own transcript.
You make no other Graph call — not the calendar, not another occurrence.

**Pre-fetched event variant.** Some briefings name an already-fetched event
file plus its already-derived `recording_id` and a verbatim
`transcript_url` instead of a URI to fetch — skip steps 1 and 2 and start
at step 3 (dedup) with the ids you were given. You make only the one
Graph call step 4 makes (the transcript) — the event was never yours to
fetch on this path; everything else, including that single-call ceiling,
stands as written.

## Attendees and confidence (M365 only)

Once your transcript fetch has succeeded — not `no-transcript`, not
`forbidden`, not `fetch-error` — you are going to draft a payload: resolve
the meeting's people before anything else, from the event you fetched,
never from the transcript (Teams speech recognition garbles names). For
every attendee **name** in your fetched event, batch one call per name
into a single Bash invocation:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<name>"
```

Use each result's `slug`, plus the vault owner's person slug your prompt
already carries, for the payload's `attendees` — the owner's slug arrives
pre-resolved (the orchestrator read it from `config read`'s `owner`), so
you never call `person ensure` for it yourself. Count the calls whose
result carries `"created": true` — those are people this vault has never
seen before; everyone else came back `"created": false`.

Your prompt carries `confidence-inputs` — two booleans the orchestrator
already computed from the calendar match, `high-if-no-new-attendees` and
`medium-if-at-most-one-new` — never a final `confidence`. Settle it
yourself against the count above:

- `high` — `high-if-no-new-attendees` is true and the count is 0.
- `medium` — not `high`, and `medium-if-at-most-one-new` is true and the
  count is at most 1.
- `low` — otherwise.

`meeting write` requires `confidence-reasons` whenever `confidence` is
set — they travel together — as exactly one entry per group (calendar,
project-link, attendees; `references/payload-contract.md` has the closed
vocabulary). Your prompt already carries the calendar-group and
project-link-group entries verbatim — copy those in unchanged, as with any
other routing field. The attendees-group entry is the one you derive
yourself, from the same count: `all-attendees-known` when the count is 0,
otherwise `new-attendees:{N}` with `N` set to the count (never 0 — the
schema requires `N` ≥ 1). Assemble all three entries into the
`confidence-reasons` list you write to the payload, alongside the
`confidence` you just settled.

Keep the names of everyone counted as new (`"created": true`) — your
outcome line reports them (see the outcome table).

## Reassemble

One call, matching your adapter — the meta/event and transcript files sit at
the scratch paths you wrote them to above. On the **pre-fetched event
variant**, the event file is not one of them — pass the path your briefing
named instead; you never wrote it, and its stem is the dispatcher's
(a probe's `m365_probe_<n>.event.json`, say), not `m365_event_<n>`:

```bash
python3 "$VAULTLIB" plaud reassemble \
  --meta "$SCRATCH/rec_N.meta.json" \
  --transcript "$SCRATCH"/rec_N.transcript.*.json \
  --note "$SCRATCH/rec_N.note.json" \
  --out "$SCRATCH" --timezone <timezone from your prompt>
```

```bash
python3 "$VAULTLIB" m365 reassemble --event "$SCRATCH/m365_event_<n>.json" \
  --transcript "$SCRATCH/m365_event_<n>.transcript.json" \
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

```
possible-duplicate-of: <existing stem> (recording-id: <your recording_id>, payload at $SCRATCH/<stem>.payload.json) (new-people: <comma-separated names>)
```

and stop — for M365, append `(new-people: none)` in place of the names
when nobody was counted new; that clause carries the list you kept in the
Attendees and confidence step above. The orchestrator decides with the
user and can write your payload without re-extraction.

## Extract and write

Extract from the blob file the `reassemble` result named — never from the raw
transcript files you wrote to scratch: the M365 one is unparsed WEBVTT, and
for a recurring series it may carry other occurrences' transcripts (an inbox
item has no blob: extract from the file you were given). Read
`references/payload-contract.md` (its path is in your prompt) and draft
the payload to `$SCRATCH/<stem>.payload.json`: content fields from the
transcript; every routing field copied from your prompt unchanged — except
for M365's `attendees`, `confidence`, and the `confidence-reasons`
attendees-group entry, which you computed yourself in Attendees and
confidence above, not your prompt (the `confidence-reasons`
calendar-group and project-link-group entries still copy from your prompt
unchanged); `date` is
`recorded_local` unchanged and `recording-duration` is `duration_min`. When
your prompt says routing signals 1–2 were inconclusive and carries the
project/entity slug catalog, match transcript keywords against it yourself —
it is the weakest signal, so a match adds the project with the lower
confidence your prompt already stamped, and no match means `projects: []`.

```bash
python3 "$VAULTLIB" meeting write --vault "$VAULT" --note "$SCRATCH/<stem>.payload.json"
```

If `meeting write` refuses, fix the payload per the `error` and `hint` and
retry — the contract names every rule. The one refusal you never retry is
an `error` naming an already-synced id: dedup was bypassed upstream — stop
and reply `fetch-error: already-synced id (dedup bypassed)` so a human sees
it. Read the result: `conflict` of kind
`confirmed-target` or `stem-collision` still counts as written — mention it
in your outcome line. Verify the result's `path` exists on disk before
replying `written:` — for M365, append `(recording-id: <your recording_id>)`
and the same `(new-people: ...)` clause described in the collision section
above.

## The outcome line (your entire reply)

| Line | When |
|---|---|
| `written: <note stem>` | note verified on disk (append any reassemble warnings / conflict kind; M365 additionally appends `(recording-id: m365:<hex>)` and `(new-people: <names>` or `none)`) |
| `no-transcript` | M365: `m365 ids` returned `skipped: no-transcript-url` (before any fetch), or the transcript read answered `transcripts_empty` |
| `forbidden` | M365: 403 on the transcript read — permanent |
| `fetch-error: <one clause why>` | transport failure, incomplete page set, oversized result — retries next run |
| `auth-error` | connector wants re-authentication — the adapter should stop |
| `already-synced: <recording_id>` | M365 only: `sync dedup` already reports your derived id `synced` — stop before the transcript read; no payload |
| `skip-listed: <recording_id>` | M365 only: `sync dedup` already reports your derived id `skipped` — stop before the transcript read; no payload |
| `possible-duplicate-of: <stem> (payload at <path>)` | collision found; payload drafted, nothing written (M365 additionally appends `(recording-id: m365:<hex>, ...)` and `(new-people: ...)` — see the collision section) |

For an M365 recording, the orchestrator parses `recording-id:` out of your
`written` and `possible-duplicate-of` lines to bank the outcome —
`sync m365-record` **requires** a namespaced `recording_id` on every
`written` outcome (`seenevents.py:234-242`). Get that clause right: a
missing or malformed `recording-id:` must surface to the orchestrator as a
banking error, never silently drop the occurrence from the ledger. A
`skip-listed:` line banks as a plain `"skipped"` outcome instead — it
needs no `recording_id` (`seenevents.py`'s `OUTCOMES` only requires one for
`written`).
