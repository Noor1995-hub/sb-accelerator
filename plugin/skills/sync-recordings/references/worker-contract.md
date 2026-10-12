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
instead. (M365 has no `limit` to halve, so its transcript read has its own
rule — `m365 capture`, in step 4 below — and that is the only time a
spilled file is ever touched, by the CLI, never by you.)

On a transient error retry up to 3×, then reply `fetch-error`. On a **401**,
reply `auth-error` — re-authentication is interactive and belongs to the
user; never retry auth in a loop. `mcp__plaud__get_note` is optional
enrichment (write it to `rec_N.note.json`); on failure proceed without.

## Fetching — M365

A worker dispatched by `/sync-recordings` always gets the **pre-fetched
event variant** below — the probe already read the event — so it skips
step 1. Steps 1–2 are the raw-URI path, which the probe contract restates:
the briefing carries the event's URI and a scratch stem (`m365_event_<n>`)
— no pre-read event file, no `transcript_url`. Fetch the event and derive
your own ids before you touch a transcript:

1. One `read_resource` call on the event URI you were given, **exactly as
   given**. It is a CLI-derived `calendar:///events/<id>` form that may
   carry `%3D` and similar escapes — never decode, rebuild, or re-scope it,
   and never re-derive it from an id you see in the event you fetch. If it
   fails, it is still not yours to repair: a 400 whose Graph code is
   `RequestBroker--ParseUri` means the URI was rebuilt somewhere upstream
   rather than copied (issue #205), so reply
   `fetch-error: event uri rejected by Graph (ParseUri — rebuilt upstream?)`
   and let a human see it, instead of trying other spellings. Write the
   result to `$SCRATCH/m365_event_<n>.json`, restricted to these top-level
   keys, values verbatim: `id`, `subject`, `start`, `end`,
   `meetingTranscriptUrl`, `organizer`, `attendees` (each `name`,
   `address`, `type`) — drop everything else (`body`, `bodyPreview`,
   `location`, `locations`, `recurrence`, `onlineMeeting`, `webLink`,
   `@odata.*`, …). Copying a kept value is still verbatim — the rule is
   which keys you keep, not how you transcribe them.
2. Write the one-element array `$SCRATCH/m365_event_<n>.ids-in.json`
   (the event you just fetched) and derive its dedup id — with your
   timezone, so the entry also carries `recorded_local` and
   `event_duration_min` for the collision check below:

   ```bash
   python3 "$VAULTLIB" m365 ids --events "$SCRATCH/m365_event_<n>.ids-in.json" --timezone <timezone from your prompt>
   ```

   `skipped` carrying `"reason": "no-transcript-url"` → reply
   `no-transcript` and stop — there is nothing to dedup or fetch. Otherwise
   take `recording_id`, `transcript_url`, `recorded_local`, and
   `event_duration_min` from the one entry in `ids`.
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

   **Collision check.** Before you touch a transcript, check whether
   another adapter already captured this conversation, using the values
   step 2 just derived:

   ```bash
   python3 "$VAULTLIB" sync collide --vault "$VAULT" \
     --start <recorded_local> --duration-min <event_duration_min>
   ```

   A match flagged `strong: true` from a different `source-recording-id`
   namespace means a probable duplicate: reply

   ```
   possible-duplicate-of: <existing stem> (recording-id: <recording_id>, existing: <source-recording-id>)
   ```

   and stop — no transcript fetch, no payload. `collide`'s 15-minute grace
   makes two merely-adjacent meetings (one ending as the other starts) a
   *match* with essentially no real overlap; a match that is `imprecise`,
   or precise but not `strong`, does not stop you: continue to step 4
   below — `meeting write`'s own collide check reports it as a warning
   later instead, at write time. When `event_duration_min` is absent (the
   event has no `end`), there is nothing to give `sync collide
   --duration-min`, so skip this collision check entirely and continue to
   step 4 — the write-time net (`meeting write`'s own check) still applies
   regardless. Skip this check entirely too when your briefing carries
   `collision: accepted` (the interactive "write it anyway" re-dispatch) —
   go straight to step 4, and pass `--accept-collision` to `meeting write`
   in Extract and write below.
4. One `read_resource` call on the `transcript_url` `m365 ids` returned in
   step 2, **exactly as given** — never rebuild or re-scope the URL; a
   recurring series answers a rebuilt, unscoped URL with other occurrences'
   transcripts. Write the raw result to
   `$SCRATCH/m365_event_<n>.transcript.json` verbatim. Then:

   - **Oversized — the result is a notice, not content.** A transcript of
     roughly an hour or more exceeds the tool-result cap, and the host
     answers with an error like `result (104,221 characters across 1
     line) exceeds maximum allowed tokens. Output has been saved to
     <path>`. That is not a failed read: the full transcript is on disk.
     Never open, read, grep, or re-type that file — not even a few lines —
     and never write the scratch transcript yourself. Hand the path to the
     CLI, **exactly as the notice gave it** (a Windows path in Cowork is
     expected; the CLI resolves it inside the sandbox):

     ```bash
     python3 "$VAULTLIB" m365 capture --from "<path from the notice>" \
       --out "$SCRATCH/m365_event_<n>.transcript.json" \
       --event <your event file — the object file, as in Reassemble>
     ```

     `ok: true` → the scratch transcript is written, verbatim; continue
     to Attendees and confidence as for any found transcript, and carry
     the result's `warnings` (if any) to the end of your outcome line.
     `ok: false` → reply `fetch-error: transcript too large to capture
     (<the CLI's error, first clause>)` — it retries next run, and a
     human can still drop the Teams transcript file in the inbox.
   - `NOT_FOUND` with `transcripts_empty` → reply `no-transcript`
     (transcription was off for that meeting — settled, not an error).
   - **403/Forbidden** — classify by the body: Graph code 3003 / "does not
     have access to lookup meeting" → reply `no-access`. An unreadable
     body, or a 403 with no readable Graph error code at all, also replies
     `no-access` — the safer default. Either way the transcript is not
     reachable from this account; it does not mean the meeting was
     organised by someone else (attendee access to an intra-tenant
     transcript works once the tenant enables it — live reproduction
     2026-08-31). The two real causes are the meeting being hosted in
     another organisation's tenant (`sync m365-triage`'s home_domains
     filter is meant to catch these before you are ever dispatched, so you
     seeing one at all means the organizer's domain is missing from
     `adapters.m365.home_domains`, or that list is unset) or the
     organisation's own tenant having the "Transcript API access —
     Microsoft Graph access" setting off. Only a 403 body that positively
     names a different cause → reply `forbidden` (another tenant owns it,
     permanently).
   - A transport error → reply `fetch-error`. (A result too large for the
     tool result is the oversized case above, not this one.)

Sanctioned Graph calls: exactly two — your own event, your own transcript.
You make no other Graph call — not the calendar, not another occurrence.

**Pre-fetched event variant.** Every `/sync-recordings` worker briefing names an already-fetched event
in two forms — the **object** file (for Reassemble and Attendees below)
and its one-element **array** wrapping (for the `ids` call right here) —
plus its already-derived `recording_id` and a verbatim `transcript_url`,
instead of a URI to fetch — skip only step 1, the Graph fetch. Still run
step 2's
`m365 ids --events <the briefing's events-*array* file> --timezone
<timezone from your prompt>` yourself, locally, against the **array**
file specifically: `m365 ids` refuses anything that is not a JSON array,
so the bare object file raises, not derives. It is a CLI call, not a
Graph call, so it costs nothing against the single-call ceiling below,
and it is the only way you get `recorded_local` and `event_duration_min`
for your own collision check (the briefing did not derive those — only
`recording_id` and `transcript_url`). Cross-check the `ids` result's
`recording_id` and `transcript_url` against the ones your briefing
already named: any disagreement means the pre-fetch and this worker are
looking at two different events, so reply
`fetch-error: pre-fetched ids disagree` and stop — do not guess which one
is right. Agreement confirmed, continue at step 3 (dedup) as before,
using the **object** file (never the array) for Reassemble and
Attendees. You make only the one Graph call step 4 makes (the
transcript) — the event was never yours to fetch on this path;
everything else, including that single-Graph-call ceiling, stands as
written.

## Attendees and confidence (M365 only)

Once your transcript fetch has succeeded — not `no-transcript`, not
`forbidden`, not `fetch-error` — you are going to draft a payload: resolve
the meeting's people before anything else, from the event you fetched,
never from the transcript (Teams speech recognition garbles names). On the
pre-fetched event variant this is the event file your briefing named, not
one you fetched yourself — its `attendees[].name` array is already sitting
in that file verbatim, whichever way it got there. For every attendee
**name** in your fetched event, batch one call per name into a single Bash
invocation, passing that attendee's `address` from the same entry:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<name>" --email "<address>"
```

The address is stored on a new person and filled into an existing one whose
email is empty; a set email is never overwritten. Leave `--email` off for an
entry with no address — never guess one. A person already on file with that
address comes back under their own slug, whatever name Outlook shows
("Peeters, Jan"), so no second note is made.

Skip an entry that is a meeting room or equipment rather than a person (an
entry typed `resource`, or a name and address that plainly belong to a
room); when unsure, keep it.

Do not link attendees to an entity: your briefing carries no per-attendee
routing, so which entity a person belongs to would be a guess.

Use each result's `slug`, plus the vault owner's person slug your prompt
already carries, for the payload's `attendees` — the owner's slug arrives
pre-resolved (the orchestrator read it from `config read`'s `owner`), so
you never call `person ensure` for it yourself. The owner is usually among
the event's attendees too: list every slug once, so a result that is the
owner's own slug adds nothing. Count the calls whose
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

## Extract and write

Extract from the blob file the `reassemble` result named — never from the raw
transcript files you wrote to scratch: the M365 one is unparsed WEBVTT, and
for a recurring series it may carry other occurrences' transcripts (an inbox
item has no blob: extract from the file you were given). Read the blob
**completely**: both `reassemble` commands report `blob_lines` and
`blob_chars`, and a long meeting's blob is larger than one Read call
returns. When `blob_chars` is over 60,000, read it in consecutive
`offset`/`limit` windows of 400 lines until you have covered all
`blob_lines` lines, and draft from the whole meeting — never from the first
window alone. An inbox file gets the same treatment: if one Read did not
reach its end, keep reading in 400-line windows until it does. Read
`references/payload-contract.md` (its path is in your prompt) and draft
the payload to `$SCRATCH/<scratch stem>.payload.json`: content fields from the
transcript; every routing field copied from your prompt unchanged — except
for M365's `attendees`, `confidence`, and the `confidence-reasons`
attendees-group entry, which you computed yourself in Attendees and
confidence above, not your prompt (the `confidence-reasons`
calendar-group and project-link-group entries still copy from your prompt
unchanged). `<scratch stem>` is the scratch stem your briefing carries
(`rec_N` / `m365_event_<n>` / the inbox file's name stem) — **never a stem
you derive from the meeting itself**: two workers in one run can capture
the same meeting from two sources and derive the same name, and the
briefing stem is the one name that is yours alone (it still matches the
`*.payload.json` sweep pattern). `date` is
`recorded_local` unchanged and `recording-duration` is `duration_min`. When
your prompt says routing signals 1–2 were inconclusive and carries the
project/entity slug catalog, match transcript keywords against it yourself —
it is the weakest signal, so a match adds the project with the lower
confidence your prompt already stamped, and no match means `projects: []`.

```bash
python3 "$VAULTLIB" meeting write --vault "$VAULT" --note "$SCRATCH/<scratch stem>.payload.json"
```

If your briefing carries `collision: accepted` (the interactive "write it
anyway" re-dispatch — you skipped the M365 collision check above, or you
are a plaud/inbox worker with no early check of your own), add
`--accept-collision` to this call.

If `meeting write` refuses, fix the payload per the `error` and `hint` and
retry — the contract names every rule. Two refusals you never retry:

- an `error` naming an already-synced id: dedup was bypassed upstream —
  stop and reply `fetch-error: already-synced id (dedup bypassed)` so a
  human sees it.
- an `error` starting `cross-adapter-duplicate:` — this write-time net
  applies to every worker type, not just M365, and can fire even after an
  M365 worker's own early collision check found nothing (a sibling
  worker's note can land on disk in the gap between the two checks). Take
  the existing stem and id the error names and reply

  ```
  possible-duplicate-of: <existing stem> (recording-id: <your recording_id>, existing: <existing_id>)
  ```

  and stop — do not retry with a different payload; nothing was written.

Read the result: `conflict` of kind `confirmed-target`,
`cross-source-duplicate` (a sibling worker in this run — or an earlier run —
already wrote this meeting's note from another source; the CLI wrote your
note as a flagged sibling instead), or `stem-collision` still counts as
written — mention the kind in your outcome line. Verify the result's `path` exists on disk before
replying `written:` — for M365, append `(recording-id: <your recording_id>)`
and the same `(new-people: ...)` clause described in the Attendees and
confidence section above. Include any `warnings` the `meeting write` result
carries at the end of your outcome line, verbatim — the same obligation
Reassemble's own `warnings` already carry (an accepted collision, or an
imprecise/weak-overlap collision match `meeting write` flagged but did not
refuse on); this is the only way that information ever reaches the
orchestrator's summary.

## The outcome line (your entire reply)

| Line | When |
|---|---|
| `written: <note stem>` | note verified on disk (append any capture / reassemble warnings / conflict kind; M365 additionally appends `(recording-id: m365:<hex>)` and `(new-people: <names>` or `none)`) |
| `no-transcript` | M365: `m365 ids` returned `skipped: no-transcript-url` (before any fetch), or the transcript read answered `transcripts_empty` |
| `no-access` | M365: 403 on the transcript read, body carries Graph code 3003 / "does not have access to lookup meeting" — or the body is unreadable / carries no readable Graph error code at all (safer default); the transcript is not reachable from this account, either because the organizer's domain is missing from `adapters.m365.home_domains` (or the list is unset) or because the tenant's Microsoft Graph transcript-access setting is off; permanent |
| `forbidden` | M365: a 403 on the transcript read whose body positively names a different cause — another tenant, permanent |
| `fetch-error: <one clause why>` | transport failure, incomplete page set, a Plaud page still oversized at the smallest `limit`, or an oversized M365 transcript `m365 capture` refused — retries next run; append `(recording-id: <ns:id>)` whenever the id is known — Plaud: always, straight from your briefing; M365: only once your own `m365 ids` call has already succeeded, never before |
| `auth-error` | connector wants re-authentication — the adapter should stop |
| `already-synced: <recording_id>` | M365 only: `sync dedup` already reports your derived id `synced` — stop before the transcript read; no payload |
| `skip-listed: <recording_id>` | M365 only: `sync dedup` already reports your derived id `skipped` — stop before the transcript read; no payload |
| `possible-duplicate-of: <existing stem> (recording-id: <recording_id>, existing: <existing_id>)` | a cross-adapter collision, caught either before the transcript fetch (M365's own collision check above) or at write time (`meeting write`'s `cross-adapter-duplicate` refusal, any adapter) — nothing was written, and no payload was ever drafted |

For an M365 recording, the orchestrator parses `recording-id:` out of your
`written` and `possible-duplicate-of` lines to bank the outcome —
`sync m365-record` **requires** a namespaced `recording_id` on every
`written` outcome (`seenevents._validate_outcome`'s `written` branch). Get
that clause right: a
missing or malformed `recording-id:` must surface to the orchestrator as a
banking error, never silently drop the occurrence from the ledger. A
`skip-listed:` line banks as a plain `"skipped"` outcome instead — it
needs no `recording_id` (`seenevents.py`'s `OUTCOMES` only requires one for
`written`).
