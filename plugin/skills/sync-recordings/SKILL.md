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

Read the deployment config first — it, not prose, says which adapters this
vault uses:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

Adapters with `enabled: false` are skipped with an explicit line in the
summary. For an enabled adapter, verify the tools actually exist before
running it — declared but unavailable is also **an explicit skip line,
never a silent zero**. Anything in `missing` that blocks a step below is
reported the same way.

`sync.start-date` is the vault's horizon: **no adapter lists, fetches, or
writes a meeting dated before it.** `dates window --vault "$VAULT"` clamps
every query window to it automatically, and the Plaud listing window below
is bounded by it too. A null value (a vault provisioned before this key
existed) means no bound — say so in the summary's warnings so the
deployment gets the date added. Backfilling older meetings stays possible,
but only as a deliberate interactive run with an explicitly stated range
(`dates window` without `--vault`) — never something a routine sync does.

| Adapter | Discovery | Availability check |
|---|---|---|
| `inbox` | `sync scan` over `10-inbox/` | always available |
| `plaud` | Plaud MCP `list_files` | ToolSearch finds `mcp__plaud__list_files` |
| `m365` | M365 calendar search + full event reads | ToolSearch finds `outlook_calendar_search` **and** `read_resource` |

### Account binding — before anything is listed

A connector adapter runs against whatever account is signed in at the *user*
level, which may not be this vault's account. The config's `account_hint`
binds them, and the check is deterministic, not judgment:

1. Call the connector's whoami tool (`mcp__plaud__get_current_user` for
   plaud; `get_me` for m365 — both the adapter and calendar enrichment).
   Write the raw JSON to scratch with the Write tool.
2. Run the gate:

```bash
python3 "$VAULTLIB" config verify-account --vault "$VAULT" \
  --adapter plaud --identity "$SCRATCH/plaud.whoami.json"
```

3. Only `match: true` proceeds. On `match: false` the adapter is **refused,
   in both modes** — nothing is listed, nothing is synced. Delete the whoami
   scratch file immediately:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

   Interactively, tell the user the `reason` and
   that binding the account means writing its identifier into
   `adapters.<name>.account_hint` in `99-workflow-config/config.json` — a
   conscious act, not something you do for them. Quote the signed-in
   account's stable identifiers from the whoami payload you just read (its
   `id` and account email) so binding is copy-paste: connectors often
   report a synthetic address for Apple/Google sign-ins, so the email the
   user knows may never appear in the whoami — and a display name is never
   a valid hint (the CLI rejects it). Under `--unattended`, write
   a refuse-and-alert line in the summary (see below) and move on to the
   other adapters.

The reasons: `account-mismatch` (wrong account signed in — the S1 this gate
exists for), `no-account-hint` (enabled but never bound — same refusal), and
`adapter-disabled`. A whoami tool that is missing or errors means the
adapter is *unavailable* (skip line), not unbound — do not guess either way.

## Workflow

### 1. Scan and dedup

First fold pending triage ticks back into `review_status` — this is what
makes the reviewed checkbox in Meetings.base actually confirm a note, and
it runs in both modes:

```bash
python3 "$VAULTLIB" sync reconcile-reviews --vault "$VAULT"
```

Report `flipped` in the summary; surface any `conflict_ticks` for a human — a
note that still carries a `conflicts-with` edge is a duplicate nobody has
resolved yet, so a tick on it is never auto-confirmed. Say so in words, and say
what settles it: merge or delete one of the two notes, then clear the
`⚠ Duplicate of` field in Obsidian, and the next run confirms the tick. Also
surface any `warnings` — a note whose review status predates this release
needs the pending vault migration before its tick can fold.

**Inbox:**

```bash
python3 "$VAULTLIB" sync scan --vault "$VAULT"
```

`candidates` are files whose content hash is in no meeting note and not on
the skip list. Read the head of each and classify it — this is judgment, and
it has exactly three outcomes:

| Shape | Outcome |
|---|---|
| A record of an interaction — transcript, meeting recording, meeting notes | a meeting note, the normal path below |
| Carries context about people, projects or entities but is not a meeting — forwarded correspondence, a voice memo, pasted context | a capture: a note with `type: note` |
| Not a capture at all — a whitepaper, a deck, a spreadsheet, an image, a stray binary | **park** it |

**When you cannot decide between a capture and a park, write the `note`.**
A wrongly written note sits in Triage and is one click from `archived: true`;
a wrongly parked file is out of the queue and on a never-propose-again list,
and getting it back means reading the archive and editing that list. The error
direction matters more than the error rate. Both modes decide all
three outcomes — `--unattended` does not defer, because routing captures
into the pipeline is the point.

A capture's payload differs from a meeting's in five fields and nothing else:

- `type: note`
- `calendar_match: false` — no calendar is ever consulted for a capture.
  `calendar-subject` is still required and still non-empty: give it the
  item's own subject (a forwarded email's `Subject:` line) or a short
  descriptive title (a voice memo). It is the Subject column in
  `Meetings.base`, so this is the label a human triages by.
- `recording-duration: 0` — nothing was recorded
- `source` is still the arrival channel: `email` for forwarded mail,
  `recorder` for a voice memo, `manual` for pasted text
- `confidence` uses the capture rule in step 4 (`medium` only on
  `entity-domain-match` plus `all-attendees-known`, otherwise `low`), and the
  calendar reason is `calendar-not-applicable` — never `no-calendar-match`
  (that means you searched) and never `calendar-tool-unavailable` (that means
  you tried)

`attendees` are the people the item names, resolved through `person ensure`
as usual. A capture that names nobody may pass `attendees: []` — it is the
one type for which that is valid — and still carries `all-attendees-known`,
because with nobody named there is nobody unknown. `takeaways` and `debrief`
keep their meanings: what this says, and what it means.

Parking is one call, and it will not run without a reason:

```bash
python3 "$VAULTLIB" sync park --vault "$VAULT" \
  --path "10-inbox/<name>" --id "inbox:<hash>" \
  --reason "<what it is, and what it is not>"
```

That moves the file to `90-archive/inbox/{YYYY-MM}/`, puts the id on the
never-propose-again list with the reason and the original filename, and writes
a short `<name>.parked.md` beside the archived file explaining it. Write the
reason for someone reading it in three months with no memory of this run:
name the thing and say what it lacks — `"vendor whitepaper on yard automation,
no meeting and no context about people or projects"`, not `"not a capture"`.
One or two sentences.

Report every parked item in the summary **with why it was not a capture** — a
park is a decision, not a throughput number. The summary is no longer the only
record of that decision, but it is still the only place the user sees it the
day it happens.

Every file `already_synced` reports is swept the same way (it was processed
by an earlier run, or dropped back in), and so is every file under
`skipped` — those were dropped permanently on some earlier run and the skip
list already records the decision, so leaving them in the inbox only
inflates the pending count. Ids are content hashes, so an archived file
keeps its id and stays deduped.

**Plaud** (when enabled, available, and account-verified): call `mcp__plaud__list_files` for the recent
window — never a range that starts before `sync.start-date`. Write the raw
JSON result to `$SCRATCH/plaud.list.json` with the Write tool
— never echo large JSON through Bash. Then dedup the ids,
namespaced:

```bash
printf '%s' '["plaud:abc123", "plaud:def456"]' > "$SCRATCH/ids.json"
python3 "$VAULTLIB" sync dedup --vault "$VAULT" --ids "$SCRATCH/ids.json"
```

Only `new` ids proceed. For each: `mcp__plaud__get_transcript` (required — on
a transient error retry up to 3×, then skip this recording this run; it
retries next run by construction) and `mcp__plaud__get_note` (optional
enrichment — on failure proceed without). Write each raw result to scratch.

**`get_transcript` is paginated, and one page is not the meeting.** It
answers `limit` utterances at a time — 50 by default — and reports `total`,
`offset` and a `next_cursor`. A half-hour meeting runs to well over a hundred
utterances, so a single call is a fraction of the conversation, and the
duration derived from it is the same fraction of the meeting. Call again with
the returned `cursor` until `next_cursor` comes back **null** (the last page
carries the key with a null value, it does not omit it), and write **every**
page to its own scratch file (`rec_42.transcript.01.json`, `.02.json`, …).
`plaud reassemble` counts what you pass against `total` and refuses an
incomplete set — a missed page is an error you see, not a short note nobody
notices.

**If a page is too large for the tool result**, the harness spills it to a
file under `~/.claude/projects/…/tool-results/`. Do not go near that path:
anything under `~/.claude` trips the harness's sensitive-file prompt, which
lands in front of the user mid-run and reads as the product asking for their
secrets. Never `cp`, `cat`, `mv` — or `rm` — a tool-result overflow file:
deleting one is just as much a touch as copying it, and cleaning up that
directory is the harness's job, not this skill's. Halve `limit` and re-fetch
from the same `cursor` instead.

Then normalize — one path per page, in any order (the CLI orders them by each
page's own `offset`, so scratch filenames carry no meaning):

```bash
python3 "$VAULTLIB" plaud reassemble \
  --meta "$SCRATCH/rec_42.meta.json" \
  --transcript "$SCRATCH"/rec_42.transcript.*.json \
  --note "$SCRATCH/rec_42.note.json" \
  --out "$SCRATCH" --timezone <config.timezone>
```

The result names the blob file and carries `recording_id`, `duration_min`,
and `recorded_local` — an ISO `YYYY-MM-DDTHH:MM` stamp that `meeting write`
(`date`) and `sync collide` (`--start`) both take **verbatim**, with no
reformatting. On a Plaud **401**: report it and stop this adapter — never
retry auth in a loop; re-authentication is interactive and belongs to the
user.

The vault owner's timezone is `timezone` from `config read` — pass the IANA
name. If it is in `missing`, the plaud and m365 adapters and calendar
enrichment cannot run: skip them with an explicit line. If the host cannot
resolve timezone names, the error's hint says to pass `--utc-offset` instead.

**Microsoft 365** (when enabled, available, and account-verified): Teams
transcribes meetings on the vault owner's calendar, and the calendar event is the
key to its own transcript. Search the trailing **7 local days**
(`outlook_calendar_search`, query `*`, `utc_from`/`utc_to` from
`dates window --vault "$VAULT"` — the clamp to `sync.start-date` rides
along; a `window_empty: true` result means skip the search outright), drop
cancelled and all-day events, and keep online meetings.

**A full event read is expensive, so dedup runs before the fetch, not
after.** Write the kept listing entries — the raw search objects, carrying
at least `id`, `subject`, `start` and `end` — as one JSON array to
`$SCRATCH/m365_search.json` with the Write tool, then ask the seen-events
cache which occurrences still need the full read:

```bash
python3 "$VAULTLIB" sync m365-triage --vault "$VAULT" \
  --events "$SCRATCH/m365_search.json"
```

Everything the cache already answers is filtered out here, before any
fetch: `filtered` counts occurrences already written into the vault,
permanently skipped, or finally transcript-less. A `no-transcript` outcome
stays provisional for 48 hours after the meeting ends — Teams delivers
transcripts with delay — so those come back in `fetch` as
`recheck-no-transcript` until the window passes. Only the occurrences in
`fetch` proceed; surface any `warnings`. The cache is disposable by design
(the vault ledger still dedups every write), so on the first run after
upgrading everything fetches once and the outcomes recorded below make
every later run cheap.

For each `fetch` entry, fetch the **full event** with `read_resource`
on its `calendar:///events/...` URI and write the raw JSON to
`$SCRATCH/m365_event_<n>.json` with the Write tool — never echo it through
Bash. Collect the full event objects into one array,
`$SCRATCH/m365_events.json`, then derive the dedup ids:

```bash
python3 "$VAULTLIB" m365 ids --events "$SCRATCH/m365_events.json"
```

Events in `skipped` (`no-transcript-url`) have no transcript *yet* — report
them as one count, not per-event lines; they retry naturally while inside
the window, and stop costing a fetch once their recorded outcome below goes
final. Feed the `recording_id` values through `sync dedup` exactly as
for plaud. Only `new` ids proceed — but an id `sync dedup` reports as
already `synced` still gets a `written` outcome recorded below: that is how
the cache back-fills for meetings synced before the cache existed.

For each new id, fetch the transcript: `read_resource` on the entry's
`transcript_url` **exactly as `m365 ids` returned it** — never rebuild or
re-scope the URL; a recurring series answers a rebuilt, unscoped URL with
other occurrences' transcripts. A `NOT_FOUND` with `transcripts_empty` is an
explicit skip line (transcription was off for that meeting), not an error.
Write the raw result to `$SCRATCH/m365_<hex>.transcript.json`, then
normalize:

```bash
python3 "$VAULTLIB" m365 reassemble --event "$SCRATCH/m365_event_3.json" \
  --transcript "$SCRATCH/m365_3.transcript.json" \
  --out "$SCRATCH" --timezone <config.timezone>
```

The result names the blob file and carries `recording_id`, `duration_min`,
and `recorded_local`, like `plaud reassemble`.

**The M365 branch's last act — after step 6 has written its notes — is
recording every settled occurrence back into the seen-events cache**, so the
next run's triage answers for them without a fetch. Write one JSON array to
`$SCRATCH/m365_outcomes.json` with the Write tool, one entry per occurrence,
keyed by the `id` and `start_utc` the triage result carried:

- `"outcome": "written"` plus its `recording_id` — the meeting note is
  verified on disk, or `sync dedup` said the id was already in the vault;
- `"outcome": "no-transcript"` — the event carried no `meetingTranscriptUrl`
  (`m365 ids` skipped it), or the transcript fetch answered
  `transcripts_empty`;
- `"outcome": "skipped"` — the id went onto the never-propose-again list
  (`sync skip`), here or on an earlier run.

A recording that *failed* — a transport error, a refused write — gets **no
outcome line**, and neither does a cross-adapter duplicate deferred under
`--unattended`: like everywhere else here, what is not settled is not
recorded, and the occurrence surfaces again next run.

```bash
python3 "$VAULTLIB" sync m365-record --vault "$VAULT" \
  --outcomes "$SCRATCH/m365_outcomes.json"
```

**Then check for a cross-adapter duplicate before anything is written.**
The ledger keys on exact ids, so it cannot see that a Plaud recording and a
Teams transcript are the same conversation captured twice. The window check
can — `recorded_local` is already the form `--start` wants, so pass it
straight through:

```bash
python3 "$VAULTLIB" sync collide --vault "$VAULT" \
  --start 2026-08-25T16:00 --duration-min 63
```

A match whose `source-recording-id` carries another namespace means this
meeting is probably already in the vault. Interactively: show both — the
existing note and this candidate — and ask once; the user either writes it
anyway or drops it permanently with `sync skip --id m365:<hex> --reason
"same meeting already synced as <existing id>"`. Under `--unattended`:
**do not write it and do not skip it** — count it in the summary's
cross-adapter duplicates line; it will keep deferring until an interactive
run settles it, and that is the safe direction. A match flagged
`imprecise: true` (a date-only note) is a *possible* duplicate — surface
it the same way, never auto-resolve it.

An m365 recording's routing starts ahead of plaud's: the event **is** the
calendar record. Pre-fill `calendar-subject`, `organizer`, `location`,
`attendee-emails`, and `recurring` from the event, set
`calendar_match: true`, and use `calendar-match-high` as the calendar
reason — step 2 below is skipped for m365-sourced items. `source` is
`teams`. Resolve attendees from the event's attendee list via
`person ensure`; Teams transcripts carry no speaker names (a tenant
setting most deployments have off), and its speech recognition garbles
names and product terms — so attendees come from the calendar, never from
the transcript, and transcript keywords stay the weakest routing signal
(step 3 already ranks them last).

### 2. Calendar enrichment (optional, honest about absence)

This step is for recordings that arrived *without* a calendar record —
inbox files and plaud recordings. An m365-sourced item skips it: its event
read already is the match, stamped in step 1.

Calendar enrichment uses the M365 connector, so it is gated like an adapter:
it runs only when `adapters.m365.enabled` is true, the calendar tool exists
(ToolSearch `outlook_calendar_search`), and `config verify-account
--adapter m365` (whoami: `get_me`, raw JSON written to
`$SCRATCH/m365.whoami.json`) returns `match: true`. Disabled, missing
tool, or a refused account all stamp `calendar-tool-unavailable` — the
calendar was never consulted — and the summary says which one happened.
When the gate passes, match each recording to a calendar event. Compute
the query window deterministically:

```bash
python3 "$VAULTLIB" dates window --vault "$VAULT" --start 2026-08-20T16:42 --timezone <tz>
```

Query with `utc_from`/`utc_to`. Score candidates: title-keyword overlap and
attendee-name matches beat same-day-only. A match pre-fills
`calendar-subject`, `organizer`, `location`, `recurring`, `attendee-emails`.

**Stamp honestly — these are different facts, never collapse them:**

- searched, nothing matched → reason `no-calendar-match`
- tool missing or errored → reason `calendar-tool-unavailable`

(Upstream, collapsing them hid a six-day connector outage.)

### 3. Route: projects, entities and attendees

Judgment, with signals in this order — stop at the first confident match:

1. External attendee email domains → entity: list `40-entities/*/`, match the
   domain root against entity slugs, then link that entity's active projects
   (`30-projects/*/index.md` where `entity` matches).
2. Calendar subject keywords against project names and slugs.
3. Transcript content keywords against project names and slugs (lower
   confidence).

An empty `projects: []` is fine — triage catches unassigned meetings. Never
force a link.

**Pass `entities` only when `projects` is empty.** Once a meeting carries a
project, `meeting write` derives `entities` itself from that project's
`entity:` field (deduped across every project the meeting carries) — passing
`entities` alongside a non-empty `projects` is refused as a strict-payload
error, because a hand-passed value would drift the moment triage reassigns
`projects[]` later and nothing would repair it until the evening fold's next
pass. So when signal 2 or 3 gave you a project, just pass `projects`; do not
also compute or pass `entities`.

The case that still needs `entities` from you is a project-less meeting that
is nonetheless about an entity: signal 1 resolves the entity directly (an
external attendee's domain) with no project yet to carry it — an intro call
with a prospect, for instance. That is the *only* way such a meeting reaches
its entity's dossier, since the dossier's Meeting Log is a Dataview query
over this field and Dataview sees just what the meeting note itself says.

Attendees are **person slugs**. For each attendee named by the calendar or
clearly identified in the transcript, ensure the note exists:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<Full Name>"
```

Use the returned slugs. The vault owner attends their own meetings — include
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

A **capture** (`type: note`) is rated on a different axis, because it has no
calendar to match: `medium` when the project link is `entity-domain-match`
*and* `all-attendees-known`; `low` otherwise. `high` is unreachable for a
capture by construction, and that is correct — nothing corroborated it.

There is no auto-confirm: every synced meeting lands `needs-review`, and the
reviewed checkbox in Meetings.base is the confirm path. The stamp is the data
a future calibration needs — write it accurately, not optimistically.

### 5. Confirm the plan (interactive mode only)

Skipped entirely under `--unattended`. Show one table — title, date,
projects, new people, confidence — and ask once: proceed / edit / skip
items. For a recording the user says to permanently drop:

```bash
python3 "$VAULTLIB" sync skip --vault "$VAULT" --id plaud:abc123 \
  --reason "user dropped it: pocket recording, nothing said"
```

`--reason` is optional here but always worth passing — record what the user
said, so the entry still makes sense to whoever reads the list next year.

If the dropped item came from the inbox, use `sync park` instead. It does the
same suppression *and* gets the file out of the pending set, which the skip
list alone does not:

```bash
python3 "$VAULTLIB" sync park --vault "$VAULT" \
  --path "10-inbox/<name>" --id "inbox:<hash>" \
  --reason "user dropped it: <what they said>"
```

A `plaud:` or `m365:` id has no inbox file, so `skip` is the whole story
there.

### 6. Extract and write

For each recording, build the payload and write. With several recordings,
fan out subagents (one per recording, up to ~4 in parallel) and pass each
one: the blob or file content, the routing you decided (projects, attendee
slugs, confidence stamp, calendar fields), and the payload contract below.
Extraction is structured work — takeaways, debrief, action items **from the
transcript**; enrichment summaries are supporting context only, never the
source of record.

**Spawn each with `model: sonnet`.** A subagent inherits the session's model
unless you say otherwise, so a nightly run started from an expensive session
extracts every recording at that price. This work is bounded — one blob in,
one payload out, against a contract that is already written down — and it
does not need the session model. The cost shows up on the client's bill, so
being deliberate about it is part of the product.

**Never poll a batch with no-op Bash.** A live cost analysis of the evening
pipeline found 362 of 423 requests in one run were idle `Bash(true)` /
`sleep` / `echo waiting` polls babysitting a background subagent batch — each
poll re-reads the entire session context, and that alone was most of that
run's bill. A **blocking** subagent spawn already returns when the subagent
finishes; there is nothing to wait for and nothing to poll. Spawn each small
batch (up to ~4, per above) as blocking calls, or spawn them sequentially
one at a time — either way, the loop resumes exactly when a batch completes,
because that is what a blocking call does. Never spawn in the background and
then loop checking on it.

**Each subagent returns one line, not its payload.** The blob or transcript
content goes to the subagent; the orchestrator gets back the fenced payload
JSON for `meeting write` plus a one-line outcome — never the raw transcript
or blob text echoed back into the main context. That is what keeps this
step's context cost flat as the number of recordings grows.

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

No `entities` key here on purpose: `projects` is non-empty, so `meeting
write` derives `entities` from `meridian-yard-automation-program`'s `entity:`
field itself. Passing `entities` alongside a non-empty `projects` is refused.

Payload rules the CLI enforces (so get them right the first time):

- `title` is a short kebab-able label — the filename becomes
  `{DD-MM-YY}-{title-slug}.md`. `date` is ISO, the recording's local start —
  for a Plaud or Teams recording that is `recorded_local` unchanged.
- `type` is a closed enum and nothing else is accepted: **`meeting` · `1:1` ·
  `steerco` · `workshop` · `brainstorm` · `status-update` · `note`**. A plain
  conversation is `meeting`; there is no `call`, no `review`, no `sync`. When
  none of the others clearly fits, `meeting` is the right answer.
- `source` is a closed enum too: **`teams` · `recorder` · `manual` ·
  `email`** — the channel the item arrived by, not the tool that made it.
- `attendees`/`projects`/`entities` are slugs and must resolve (person notes,
  project folders, `40-entities/<slug>/dossier.md`). `attendees` must be
  non-empty — except on a `type: note` capture, which may pass `[]` when the
  item names nobody. `projects` may be empty (triage catches unassigned
  meetings). `entities` is optional, machine-derived from `projects` whenever
  `projects` is non-empty, and omitted from the file when there is nothing to
  write — pass it yourself only when `projects` is empty, and never alongside
  a non-empty `projects` (refused). Optional `people` (slug list) renders a
  `## People` wikilink section. `takeaways` is 1–5 strings. `type` values
  with a colon (`"1:1"`) are handled by the CLI — pass them as plain strings.
- Do NOT pass `review_status`, `reviewed`, `archived`, or `processed` — the
  CLI sets them.
- `source-recording-id` is **required** on every write — it IS the dedup
  ledger. For inbox files it is the `recording_id` from `sync scan`; for
  Plaud and Microsoft 365 it comes from `plaud reassemble` /
  `m365 reassemble`.

Read the result: a `conflict` of kind `confirmed-target` means the CLI wrote a
`-v2` sibling carrying a `conflicts-with` edge instead of touching a confirmed
note — report it as a possible duplicate; it shows in triage under
`⚠ Duplicate of`. `stem-collision` means a `-2` suffix and nothing was at
risk. An `error` about an already-synced id means dedup was bypassed — stop and
say so.

**Then sweep what you wrote.** For each recording whose `meeting write`
returned a `path` that exists on disk, move its inbox source out of the
queue:

```bash
python3 "$VAULTLIB" sync archive --vault "$VAULT" --path "10-inbox/<name>"
```

Only after the note is verified against disk — a file that produced nothing
stays in the inbox and retries next run, which is the same failure rule as
everywhere else here. This applies to inbox-sourced items only; Plaud and
M365 recordings have no inbox file to move.

`10-inbox/` is the pending set. What is left in it after a run is exactly
what still needs processing — that is what makes the folder answerable
without running anything, and why no index note or state file exists.

### 7. Summarize — from disk, not from memory

Count what exists, not what you intended (a lab run once reported
"Processed: 0" after writing a meeting correctly):

```
## Sync Complete
**Processed:** {N} meetings → `20-meetings/` ({list the stems})
**Captures:** {N} → `20-meetings/` as `type: note` ({list the stems})
**Parked:** {N} → `90-archive/inbox/` ({filenames, each with why it was not a capture})
**Inbox swept:** {N} files → `90-archive/inbox/{YYYY-MM}/` · {N} left pending in `10-inbox/`
**New people:** {N} created in `50-people/`
**Meetings you ticked as reviewed:** {N} now confirmed
**Possible duplicates:** {N} ({list the stems}) — kept as separate notes; each would have overwritten a meeting you already confirmed
**Possible cross-adapter duplicates:** {N} — deferred; needs an interactive run
**Skipped / errors:** {N} (will retry next run)
**M365 fetches saved:** {N} of {N} listed occurrences answered from the seen-events cache | cache cold (first run)
**Adapters:** inbox ok · plaud ok | REFUSED — signed in as a different account (account-mismatch) | REFUSED — no account bound to this vault yet (no-account-hint) | disabled | unavailable · m365 ok | REFUSED — signed in as a different account (account-mismatch) | REFUSED — no account bound to this vault yet (no-account-hint) | disabled | unavailable
**Calendar enrichment:** ok | UNAVAILABLE
**Warnings:** {verbatim} | none
```

`Inbox swept` counts every file moved this run — processed meetings,
captures and parks alike, plus anything already synced — and reports the
pending remainder — that remainder is the number the vault owner actually
cares about. Count it from disk like everything else in this step.

## Scratch hygiene

Raw connector JSON — whoami payloads, `list_files` listings, transcripts —
is engagement data that must not outlive the run. It lands only in the
session scratch directory, never the vault. At the end of the run, success
or refusal, sweep it:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

`scratch sweep` is stdlib-only and deletes a fixed, built-in pattern list
(`plaud.whoami.json`, `m365.whoami.json`, `rec_*.json`, `plaud.list.json`,
`m365_*.json`, `*.blob.md`, `ids.json`, `*.payload.json`, `decision.json`,
plus `sentmail.sample.json`, `calendar.*.json` and `*.block.md` from
Session-1 onboarding) directly inside `--dir`, never recursing — this is the whole reason it
exists rather than `rm -f`. **Every scratch file this contract names you
write already matches one of those patterns; name any other raw connector
file to match one too** (`m365_events.json` fits `m365_*.json`,
`rec_42.blob.md` fits `*.blob.md`), so one sweep call always catches
everything this run wrote, and it is the only deletion this skill ever
performs. This is *why* every scratch write above uses those exact
filenames rather than something more descriptive. Cleanup never leaves
`$SCRATCH`: a tool-result overflow file under `~/.claude` is not yours to
delete — it is the harness's own housekeeping, and an `rm` on it trips the
same sensitive-file prompt as reading it would. `scratch sweep` cannot
reach it either; it only ever looks inside the directory it is given.

On an account-mismatch refusal, run the sweep immediately — before writing
the summary. (The gate runs before listing, so on a refusal no listing ever
reaches disk.)

## Unattended mode

`--unattended` is what scheduled runs and the evening pipeline pass. Three
rules, not negotiable:

1. **Never ask a question.** A blocked prompt means the run exits having
   done nothing. Ambiguity in *extraction or routing* → skip that recording
   and report it; it retries next run. Classification is not covered by this
   rule: the three-outcome call in step 1 is decided in both modes, and its
   own ambiguity rule resolves toward writing the `note`. Note also that
   "skip" here means *defer to the next run* — unrelated to `sync skip` and
   `sync park`, which write the permanent never-propose-again list.
2. **Prefer under-routing to wrong routing.** No confident project match →
   `projects: []` and low confidence; triage exists for exactly this.
3. **A refused account binding is an alert, not a fallback.** The summary
   carries the refuse-and-alert line; the adapter synced nothing, and no
   judgment call overrides the gate.
4. **The run ends with exactly one run-log line, always.** `--unattended`
   exiting 0 having done nothing is a silent failure a human has no reason to
   go looking for — including the "nothing to do" case (inbox empty, no new
   recordings on any enabled adapter). The very last action of an unattended
   run, after the summary above, is:

```bash
python3 "$VAULTLIB" runlog append --vault "$VAULT" --routine sync-recordings \
  --outcome "<one line: e.g. '3 processed, 1 parked, 0 pending' or 'nothing to do: inbox empty, no new recordings'>"
```

   Write it whether the run succeeded, refused an adapter, or found nothing —
   it is the one place a human looks after the fact, in
   `99-workflow-config/logs/routine-runs.log`.

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
