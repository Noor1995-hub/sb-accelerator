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
7. **Extraction and payload drafting happen only in subagents** — never
   inline, even for a single recording. Step 6 has the mechanics; the
   payload contract lives in `references/payload-contract.md`, which only
   the subagents read. Without the schema in this context there is nothing
   to draft inline — that is deliberate.
8. **Scratch transcripts are verbatim.** Every transcript file written to
   scratch is the tool result's content, unchanged — never condensed,
   summarized, or re-typed from memory. The pagination fields (`offset`,
   `returned`, `total`, `next_cursor`) are facts about what the connector
   sent and are never edited; when `plaud reassemble` refuses a page set,
   the only remedy is re-fetching the missing pages by cursor. Catching
   yourself editing those fields to satisfy the validator is a
   stop-and-report condition: stop that recording, say so in the summary,
   let it retry next run. The same verbatim rule covers this context's own
   listing writes — `$SCRATCH/m365_search.json` and
   `$SCRATCH/m365_routing.json` hold the calendar search's own field
   values unchanged, never rebuilt or retyped. The **full-event JSON**
   verbatim obligation is not this context's problem any more: the m365
   adapter's own full-event and transcript reads happen inside the worker
   now, which writes its own `$SCRATCH/m365_event_<n>.json` under the same
   doctrine, stated in its own contract (`worker-contract.md`) — a live run
   once re-typed an event "from memory" there and garbled three transcript
   URLs and two ids before catching itself, back when that read still
   happened in this context. Calendar enrichment (step 2) never reaches a
   full event either: it scores candidates and pre-fills fields straight
   off the calendar-search listing already in context, so there is nothing
   there to spill to scratch. (A calendar listing is not a transcript —
   the step 1 trim to `m365_search.json`'s four fields, and to
   `m365_routing.json`'s nine, is fine.)
9. **Batch independent CLI calls into one Bash call.** Every separate tool
   turn re-reads the whole session context. Calls with no data dependency —
   `sync reconcile-reviews` and `sync scan`; the `person ensure` calls for a
   meeting's attendees — go in one invocation, separate lines, never
   `&&`-chained — a failed call must not swallow the envelopes behind it.
   Each still prints its own JSON envelope, in order; read `ok` on every one.

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
| `m365` | M365 calendar search (workers fetch their own events and transcripts) | ToolSearch finds `outlook_calendar_search` **and** `read_resource` |

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
it runs in both modes. Batch it with the inbox scan below — neither has a
data dependency on the other (rule 9):

```bash
python3 "$VAULTLIB" sync reconcile-reviews --vault "$VAULT"
python3 "$VAULTLIB" sync scan --vault "$VAULT"
```

Report `flipped` in the summary; surface any `conflict_ticks` for a human — a
note that still carries a `conflicts-with` edge is a duplicate nobody has
resolved yet, so a tick on it is never auto-confirmed. Say so in words, and say
what settles it: merge or delete one of the two notes, then clear the
`⚠ Duplicate of` field in Obsidian, and the next run confirms the tick. Also
surface any `warnings` — a note whose review status predates this release
needs the pending vault migration before its tick can fold.

**Inbox:**

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

**Plaud** (when enabled, available, and account-verified): compute the
discovery window — the trailing **7 local days**, ending now, narrowed to
whatever is left uncovered since this adapter's last successful run:

```bash
python3 "$VAULTLIB" dates window --vault "$VAULT" --trailing-days 7 --adapter plaud --timezone <tz>
```

The result's `effective_days` is the real span this run asks for — the
summary's window figure below — and `watermark_used` says whether the
narrowing applied at all. A missing or corrupt watermark fails open to the
full 7, same as a cold cache anywhere else in this skill. Pass `date_from`
as the local date of the window's `utc_from`, and `date_to` as today
(local), to `mcp__plaud__list_files` — never a range that starts before
`sync.start-date`, which the window's own clamp already enforces. Write the
raw JSON result to `$SCRATCH/plaud.list.json` with the Write tool
— never echo large JSON through Bash. Then dedup the ids,
namespaced:

```bash
printf '%s' '["plaud:abc123", "plaud:def456"]' > "$SCRATCH/ids.json"
python3 "$VAULTLIB" sync dedup --vault "$VAULT" --ids "$SCRATCH/ids.json"
```

Before writing meta files, drop the throwaway ones: for each `new` id, read
its listing entry's `duration` (milliseconds). One that is a number
**greater than 0 and strictly under 60000 ms** is a tiny clip — a pocket
recording, a false start — so write no `rec_N.meta.json` for it and
dispatch nothing; skip it instead:

```bash
python3 "$VAULTLIB" sync skip --vault "$VAULT" --id "plaud:<id>" \
  --reason "tiny clip: <N>s recording, under the 60s auto-skip threshold"
```

`<N>` is `duration` divided by 1000, rounded. Count these under **Skipped /
errors** in the summary with the duration visible, not folded anonymously
into the generic retry count. A missing, null, zero, or non-numeric
`duration` **fails open — dispatch normally**: `duration: 0` is plaud.py's
own unknown-duration sentinel, indistinguishable from absent, so losing a
recording to a parsing edge case is the one wrong answer here, same doctrine
as the seen-events cache. Interactively, this is an information line, not a
question — the skip list already records the reversal path if the
auto-skip turns out to be wrong.

For each `new` id that cleared the tiny-clip check, write its `list_files`
entry — the object exactly as the listing carried it — to
`$SCRATCH/rec_N.meta.json`. `plaud reassemble` cross-checks the
transcript's timeline against this meta's `duration`, so it must be the
connector's own record, never reconstructed.

That is where this context's Plaud work ends. **Never call
`mcp__plaud__get_transcript` or `mcp__plaud__get_note` yourself** — the
fetch, pagination, reassembly, extraction and write all happen inside the
per-recording worker step 6 dispatches, following
`references/worker-contract.md`. A transcript that entered this context
would be re-read by every request that follows; a live cost analysis
measured exactly that as most of a long run's bill. Routing (step 3) works
from the listing metadata and the calendar; when it needs transcript
keywords, the worker matches them itself (signal 3).

The vault owner's timezone is `timezone` from `config read` — pass the IANA
name. If it is in `missing`, the plaud and m365 adapters and calendar
enrichment cannot run: skip them with an explicit line — the timezone rides
into every worker briefing. If the host cannot resolve timezone names, the
error's hint says to pass `--utc-offset` instead.

**Microsoft 365** (when enabled, available, and account-verified): Teams
transcribes meetings on the vault owner's calendar, and the calendar event is the
key to its own transcript. Compute the discovery window — the trailing
**7 local days**, ending now, narrowed the same way Plaud's is, to whatever
is left uncovered since this adapter's own last successful run:

```bash
python3 "$VAULTLIB" dates window --vault "$VAULT" --trailing-days 7 --adapter m365 --timezone <tz>
```

Pass its `utc_from`/`utc_to` values to `outlook_calendar_search` as
`afterDateTime`/`beforeDateTime` — the clamp to `sync.start-date` rides
along, and the window ends at *now*, never in the future: M365 synthesizes
a transcript URL even for meetings that have not happened yet, so a window
that reaches forward lists events nothing can honestly sync. A
`window_empty: true` result means skip the search outright. Drop cancelled
and all-day events, and keep online meetings.
The tool answers at most **25 events per call**: when a
response carries `nextOffset`, call again with `offset` set to it until it
stops. A trailing week routinely holds more than 25 events, and a
first-page-only search silently drops the rest — nothing fails, those
meetings just never sync.

**A full event read is expensive, so it no longer happens here at all —
it's the worker's job, gated by triage.** Keep the listing lean: never
search a window wider than `dates window` returned, and write only the
four fields triage reads — `id`, `subject`, `start`, `end`, values
verbatim — for each kept event, across every page, as one JSON array to
`$SCRATCH/m365_search.json` with the Write tool. The connector's calendar
search selects no fields, so this scratch write is where the listing gets
trimmed — a live run wrote 53k characters of raw listing for 33 events
when 11 mattered and four fields per event were ever read. (A listing is
not a transcript — rule 8 does not apply.) Then ask the seen-events cache
which occurrences still need a worker at all:

```bash
python3 "$VAULTLIB" sync m365-triage --vault "$VAULT" \
  --events "$SCRATCH/m365_search.json"
```

Everything the cache already answers is filtered out here, before any
dispatch: `filtered` counts occurrences already written into the vault,
permanently skipped, refused by another organization's tenant, or finally
transcript-less. A `no-transcript` outcome
stays provisional for 48 hours after the meeting ends — Teams delivers
transcripts with delay — so those come back in `fetch` as
`recheck-no-transcript` until the window passes. A provisional occurrence
checked within the last 6 hours comes back in `filtered.no_transcript_waiting`
instead and is not fetched this run — the 48h horizon above is unchanged.
Occurrences whose meeting
has not yet ended come back in `deferred` (reason `not-ended`) — count them
in the summary, bank nothing for them, and let them sync normally on the
first run after they end. Only the occurrences in
`fetch` proceed; surface any `warnings`. The cache is disposable by design
(the vault ledger still dedups every write), so on the first run after
upgrading everything dispatches once and the outcomes recorded below make
every later run cheap.

For each `fetch` survivor, match its `id` back against the calendar-search
pages you already hold and write one compact array,
`$SCRATCH/m365_routing.json`, with — per event, **values verbatim from the
listing, never rebuilt** — `id`, `subject`, `start`, `end`, `organizer`,
`attendees`, `location`, `recurrence`, and `uri` (the URL-encoded
`calendar:///events/<id>` form; never decode or reconstruct it — the
worker reads it exactly as given). There is no full event read and no id
derivation here any more: the worker fetches its own event, derives its
own ids, and dedups itself before it ever reads a transcript —
`worker-contract.md`'s Fetching — M365 section has the mechanics. The
event is never fetched in this context, and neither is the transcript —
the worker's step 6 dispatch makes both `read_resource` calls itself, and
what it finds comes back as its outcome line: `already-synced:
<recording_id>` (its own dedup call found the id already in the ledger —
no transcript fetch, no payload), `no-transcript` (its own id-derivation
call found no `meetingTranscriptUrl`, or the transcript read answered
`transcripts_empty`), `"forbidden"` (a 403 — another organization's tenant
owns the transcript, permanently), or a written note. Those outcomes are
banked per batch in step 6. A recording that *failed* — a transport error
— gets **no outcome line**, and neither does a cross-adapter duplicate
deferred under `--unattended`: what is not settled is not recorded, and
the occurrence surfaces again next run.

An m365 recording's routing starts ahead of plaud's: the listing **is**
the calendar record. Pre-fill `calendar-subject`, `organizer`, `location`,
`attendee-emails`, and `recurring` from `m365_routing.json`, set
`calendar_match: true`, and use `calendar-match-high` as the calendar
reason — step 2 below is skipped for m365-sourced items. `source` is
`teams`. The listing carries attendees as bare **email addresses**, never
names, so attendee slugs are not yours to produce here: the worker
resolves them itself from the full event it fetches (`person ensure`, per
`worker-contract.md`'s Attendees and confidence section) — Teams
transcripts carry no speaker names besides (a tenant setting most
deployments have off), and its speech recognition garbles names and
product terms, so attendee resolution never touches the transcript either
way. Pass `attendee-emails` in the worker's briefing (step 6); it derives
the slugs, never you.

**The dispatch gate.** A worker is dispatched for every occurrence that
survived triage (`sync m365-triage`'s `fetch` list) — never to discover
whether a transcript exists for anything else. The ledger dedup that used
to run here, once, before dispatch now runs inside the worker instead, as
its first move after it derives its own ids (`worker-contract.md`): an id
already in the ledger stops there, before any transcript fetch, and
reports `already-synced: <recording_id>` rather than costing an
extraction — `meeting write`'s own already-synced refusal is the backstop
behind that, not a second gate you maintain here. Each worker makes
exactly the connector calls for its one assigned recording, and a
negative answer (no transcript, forbidden, already-synced, skip-listed) is one of its
first tool calls, costing a skip, not an extraction — that, plus triage,
is what keeps a fleet of workers from ever being paid to learn "nothing to
write". A worker **never writes the seen-events cache**: every settled
outcome comes back as one line, and step 6 banks each batch's lines the
moment it returns — including any `already-synced` lines, banked as
`written`, which is how the cache back-fills for meetings synced before it
existed.

### 2. Calendar enrichment (optional, honest about absence)

This step is for recordings that arrived *without* a calendar record —
inbox files and plaud recordings. An m365-sourced item skips it: its
calendar record already is the match, stamped in step 1 straight from the
listing.

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

Pass its `utc_from`/`utc_to` values as the tool's
`afterDateTime`/`beforeDateTime`. The window around one recording is narrow,
but if the response carries `nextOffset`, page through (`offset` set to it)
before scoring. Score candidates: title-keyword overlap and
attendee-name matches beat same-day-only. A match pre-fills
`calendar-subject`, `organizer`, `location`, `recurring`, `attendee-emails`.

**Stamp honestly — these are different facts, never collapse them:**

- searched, nothing matched → reason `no-calendar-match`
- tool missing or errored → reason `calendar-tool-unavailable`

(Upstream, collapsing them hid a six-day connector outage.)

### 3. Route: projects, entities and attendees

Pull the routing digest once, batched with nothing else it depends on:

```bash
python3 "$VAULTLIB" sync routing-signals --vault "$VAULT"
```

Its `projects` (slug, name, entity, status), `entities` (slugs), and
`people` (slugs) replace listing `40-entities/*/` or
`30-projects/*/index.md` by hand — judgment below runs on this digest,
matched against each recording's own attendee data (`attendee-emails` from
`m365_routing.json` for m365; the calendar or transcript for plaud and
inbox).

Judgment, with signals in this order — stop at the first confident match:

1. External attendee email domains → entity: match the domain root against
   the digest's entity slugs, then link that entity's active projects
   (the digest's `projects` where `entity` matches).
2. Calendar subject keywords against the digest's project names and slugs.
3. Transcript content keywords against the digest's project names and slugs
   (lower confidence) — the worker's signal, not yours: no transcript
   exists in this context. When signals 1–2 are inconclusive, the step-6
   briefing carries the project/entity slug catalog and the worker matches
   transcript keywords against it itself.

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

Attendees are **person slugs**. For plaud, inbox, and capture recordings —
where the calendar match (if any) or the transcript names people — ensure
each attendee's note exists:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<Full Name>"
```

Use the returned slugs. The vault owner attends their own meetings — include
them. Names only guessed from transcript audio are unreliable: leave them
out of `attendees` and mention them in the debrief instead.

**M365 is the exception.** The listing carries no attendee names, only
emails, so this context cannot resolve slugs for an m365 recording at all —
skip this paragraph for it entirely. The worker does its own `person
ensure` from the full event it fetches (step 6 passes `attendee-emails` and
the vault owner's person slug instead of resolved attendees).

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

**M365 is the exception.** You never stamp a final `confidence` for an
m365-sourced recording, and (per step 3) you never resolve its attendees
either — only the worker knows the new-attendee count, because only it has
attendee *names*. What you compute instead are the two `confidence-inputs`
booleans the table above reduces to once attendee knownness is set aside:

- `high-if-no-new-attendees` — `calendar-match-high` and a strong link
  (`entity-domain-match` or `calendar-subject-match`)
- `medium-if-at-most-one-new` — calendar match high or medium and any
  project link

Pass both, plus the calendar-group and project-link-group
`confidence-reasons` entries, in the worker's briefing (step 6); the worker
settles `high`/`medium`/`low` against its own new-attendee count and
derives the attendees-group `confidence-reasons` entry that goes with it
(`worker-contract.md`'s Attendees and confidence section).

There is no auto-confirm: every synced meeting lands `needs-review`, and the
reviewed checkbox in Meetings.base is the confirm path. The stamp is the data
a future calibration needs — write it accurately, not optimistically.

### 5. Confirm the plan (interactive mode only)

Skipped entirely under `--unattended`. Show one table — title, date,
projects, new people, confidence — and ask once: proceed / edit / skip
items. The title column is provisional: the real title is a step-6
subagent output, decided from the transcript, not yet drafted here — show
the source filename or the calendar subject in its place.

**M365 rows carry two more provisional columns, for the same reason.**
Neither the attendee count nor the final confidence exists yet at step 5
for an m365 recording — the worker settles both at dispatch (step 4's
M365 exception, step 6). Show what step 4 actually computed, honestly,
never a resolved value that doesn't exist yet:

- **New people** — show "resolves at dispatch ({N} attendee emails)",
  `{N}` being the length of that row's `attendee-emails` in
  `m365_routing.json`; the email count is real, the new-person count is
  not knowable until the worker runs `person ensure`.
- **Confidence** — show the pre-computed component, not a guessed final
  rating: `high-if-no-new-attendees` true → `"≤high — final at
  dispatch"`; otherwise `medium-if-at-most-one-new` true → `"≤medium —
  final at dispatch"`; otherwise `"low"` outright — when neither component
  is true no new-attendee count could raise it, so `low` is already final
  and needs no caveat.

For a recording the user says to permanently drop:

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

A `plaud:` id has no inbox file, so `sync skip` — with its recording id
already known at step 5 — is the whole story there.

An m365 row is different: there is no recording id for it yet at step 5
(that only exists once the worker derives it from the full event, per
`worker-contract.md`), so there is nothing to hand `sync skip` and no file
to hand `sync park`. Dropping an m365 row banks it straight into the
seen-events cache instead, keyed the same way triage keys everything else
— the `id` and `start_utc` that row's triage result carried:

```
[{"id": "<event id>", "start_utc": "<triage start_utc>", "outcome": "skipped"}]
```

Fold that entry into step 6's next banking call rather than reaching for
`sync skip` — the cache accepts a `"skipped"` outcome with no
`recording_id` at all, and the seen-events cache has no separate
never-propose-again list the way the plaud/inbox ledger does. Say so
honestly, not as a permanent suppression: this one is cache-backed, so it
can resurface if the cache entry is later pruned (its own retention
horizon) *and* a wide-enough window still lists the occurrence — in which
case the user just drops it once more. No worker is dispatched for a row
dropped this way.

### 6. Extract and write

For each recording that survived step 1 — **also when there is only one**
(rule 7) — dispatch a worker, up to ~4 in parallel, blocking, as the
plugin's own agent type: `subagent_type: second-brain:sync-worker` for
plaud and inbox recordings, `subagent_type: second-brain:sync-worker-m365`
for m365 ones (the M365 connector's tool names differ per deployment, so
that worker's tool surface stays open where the other's is pinned). Both
agent definitions pin `model: sonnet` structurally — the model is never a
per-dispatch decision. On a harness where the plugin agent types do not
resolve, fall back to a generic subagent spawned with `model: sonnet`
passed explicitly — a live cost analysis found dispatches that omitted it
silently inheriting the session's model, and generic workers each re-read
the session's full base context on every request besides.

The worker fetches its own transcript, reassembles,
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
  `$SCRATCH/rec_N.meta.json`; M365 — the listing's own `uri` field, verbatim
  (the URL-encoded `calendar:///events/<id>` form — never decoded or
  rebuilt), from `m365_routing.json`, and the scratch stem
  `m365_event_<n>`; there is no pre-read event file and no `transcript_url`
  to pass — the worker fetches the event and derives both itself
  (`worker-contract.md`'s Fetching — M365 section); inbox — the file's
  path, its `recording_id` from `sync scan`, its date read from the file's
  own content or header, and its scratch stem — the inbox file's own name
  stem (its payload file `<stem>.payload.json` is swept by pattern like the
  rest);
- the routing you decided: `projects`, `calendar_match`, `calendar-subject`
  (always non-empty — the matched event's subject, or the item's own
  subject or a short descriptive title), whichever of
  `organizer`/`location`/`recurring`/`attendee-emails` are known, `source`,
  and the step-1 classification (`type: note` for a capture; otherwise the
  worker picks the meeting subtype from the transcript). For plaud, inbox,
  and captures this also includes attendee slugs, `confidence` +
  `confidence-reasons`, and `source-recording-id`. **M365 is the
  exception**: attendee slugs, the final `confidence`, and the
  `confidence-reasons` attendees-group entry are not yours to pass — the
  worker derives all three itself. Pass instead: `attendee-emails` straight
  from `m365_routing.json` (never resolved to slugs here — the listing
  carries no names), the `confidence-inputs` pair from step 4's M365
  exception, the calendar-group and project-link-group
  `confidence-reasons` entries verbatim (the worker copies these in
  unchanged and derives only the attendees-group entry), and the vault
  owner's person slug (`owner` from `config read`) for the worker to fold
  straight into `attendees` — the worker never calls `person ensure` for
  the owner, only for the event's other attendees. `source-recording-id`
  is also not yours for M365: the worker derives it from its own ids call.
  `date` and `recording-duration` the worker derives from its own
  `reassemble` result for every adapter — pass them only for inbox items
  and captures;
- `entities`, but only when `projects` is empty (step 3);
- when routing signals 1–2 were inconclusive: the project/entity slug
  catalog, for worker-side signal-3 matching.

Extraction is structured work — takeaways, debrief, action items **from the
transcript**; enrichment summaries are supporting context only, never the
source of record.

**Never poll a batch with no-op Bash.** A live cost analysis of the evening
pipeline found 362 of 423 requests in one run were idle `Bash(true)` /
`sleep` / `echo waiting` polls babysitting a background subagent batch —
each poll re-reads the entire session context, and that alone was most of
that run's bill. A **blocking** spawn already returns when the worker
finishes. Spawn each batch (up to ~4) as blocking calls, or sequentially —
never spawn in the background and then loop checking on it.

**When a batch returns, act on each line, then bank.**

- `written: <stem>` — count it; step 7 verifies from disk anyway. For an
  m365 recording, the line carries a `(recording-id: m365:<hex>)` clause —
  parse it for the banking call below; a missing or malformed clause is a
  banking error to surface, never a silently dropped occurrence
  (`worker-contract.md` says the same). It also carries a `(new-people:
  <names>` or `none)` clause — fold the names into the summary's New
  People count. A `written:` line that mentions a `confirmed-target`
  conflict counts under **Possible duplicates**, not Processed: the CLI
  wrote a `-v2` sibling carrying a `conflicts-with` edge instead of
  touching the confirmed note, and it shows in triage under `⚠ Duplicate
  of`. A mentioned `stem-collision` is just a `-2` filename suffix —
  nothing was at risk.
- `already-synced: <recording_id>` — the worker's own dedup call found the
  id already in the ledger before it ever fetched a transcript; bank it as
  `{"outcome": "written", "recording_id": <recording_id>}` alongside the
  batch's other lines. This is how the cache back-fills for meetings
  synced before it existed — there is no separate pre-dispatch call for it
  any more, because every triage survivor gets a worker now.
- `skip-listed: <recording_id>` — the worker's own dedup call found the id
  already on the permanent skip list before it ever fetched a transcript;
  bank it as `{"outcome": "skipped"}`, keyed by the `id` and `start_utc`
  triage carried — no `recording_id` required (`sync m365-record` only
  demands one for `written`). The skip list already recorded why; there is
  nothing left to decide here.
- `no-transcript` / `forbidden` — settled negatives, banked keyed by the
  `id` and `start_utc` triage carried, same as always.
- `fetch-error` — no outcome line is banked; it retries next run.
- `auth-error` — stop dispatching that adapter's remaining recordings and
  report it; re-authentication belongs to the user.
- `possible-duplicate-of: <stem> (recording-id: m365:<hex>, payload at
  <path>) (new-people: <names>` or `none)` — the ledger keys on exact ids,
  so it cannot see one conversation captured twice across adapters; the
  worker's window check can, and it drafted its payload without writing.
  Parse the `recording-id:` clause — you need it whichever way the user
  decides. Interactively: show both notes and ask once — "write it anyway"
  is `meeting write --vault "$VAULT" --note "<path>"` right here, no
  re-extraction — then include a `written` entry for it, keyed to that
  parsed `recording_id`, in the batch outcomes you bank below, and fold
  its `new-people` clause into the summary count; "drop it" is `sync skip
  --id m365:<hex> --reason "same meeting already synced as <existing
  id>"`, using that same parsed id, which banks as a `"skipped"` outcome.
  Under `--unattended`: neither — count it in the summary's cross-adapter
  duplicates line; it defers until an interactive run settles it, and that
  is the safe direction.

Then write the batch's settled lines — `written` (with each
`recording_id`, including any `already-synced`-derived entries),
`no-transcript`, `forbidden`, `skipped` (including any
`skip-listed`-derived entries, plus the step-5 drop-path entries described
above) — one entry per occurrence, keyed by the `id` and `start_utc` the
triage result carried, to `$SCRATCH/m365_outcomes_batch.json`, and bank
them before dispatching the next batch:

```bash
python3 "$VAULTLIB" sync m365-record --vault "$VAULT" \
  --outcomes "$SCRATCH/m365_outcomes_batch.json"
```

The cache merges across calls; Plaud and inbox outcomes have no cache and
feed only the summary. Banking per batch keeps the maximum crash loss to
one batch — one cheap worker-side re-fetch next run.

There is no separate pre-dispatch banking call any more, and no special
case for "every candidate deduped away": dispatch happens for every triage
survivor (the dispatch gate, above), so an already-synced occurrence still
gets a worker, still returns an outcome line, and still gets banked through
the ordinary batch flow above — the back-fill for meetings synced before
the cache existed just rides along with everything else the batch banks.

**Then sweep what you wrote.** For each inbox-sourced recording whose
worker replied `written:` with a note verified on disk, move its inbox
source out of the queue:

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

**Advance the watermark — only for an adapter whose status this run is
`ok`.** Once an adapter's processing above is done, record how far this run
actually reached, using that adapter's own step-1 window, never "now":

```bash
python3 "$VAULTLIB" sync watermark --vault "$VAULT" --adapter plaud --utc-to "<plaud window's utc_to>"
python3 "$VAULTLIB" sync watermark --vault "$VAULT" --adapter m365 --utc-to "<m365 window's utc_to>"
```

Run it for whichever adapters finished `ok` — often just one. Skip it for an
adapter that was `REFUSED`, `unavailable`, or stopped mid-run on
`auth-error`: nothing past the point of failure was actually covered, and
advancing the mark past that would hide what still needs listing next run.
Skip it too for an adapter that deferred one or more cross-adapter
duplicates under `--unattended` this run: that recording settled nothing —
no note, no seen-events entry, no skip-list line, its payload swept with the
rest of scratch — so it is still sitting there unsettled next run, and it
needs the window open wide enough for an interactive run to reach it. A
batch's `fetch-error` outcomes do not hold this back — a persistently
failing item (an oversized transcript, say) retries itself next run inside
`dates window`'s own 2-day floor regardless of where the watermark sits — but
a deferred cross-adapter duplicate waits on a human, not on a retry, so the
watermark has to hold for it too. Everything after the window's `utc_to` was
never listed this run, so stamping "now" instead would silently skip
whatever synced late between the window and the stamp. The write is
monotonic — an earlier `utc_to` than what is already stored is a no-op — so
holding it back only widens the next run's window, day by day back toward
the full 7, until an interactive run settles the duplicate and the hold
lifts.

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
**Skipped / errors:** {N} (will retry next run) · {N} tiny clips auto-skipped ({list each with its duration}) — permanent, not a retry
**M365 fetches saved:** {N} of {N} listed occurrences answered from the seen-events cache ({N} held in the 6h recheck window) | cache cold (first run)
**Workers dispatched:** {N} ({N} plaud · {N} m365 · {N} inbox) — m365 candidates not dispatched were answered by the cache ({N}) or hadn't ended yet ({N}); worker outcomes: {N} written · {N} already-synced · {N} skip-listed · {N} no-transcript · {N} forbidden · {N} fetch-error · {N} auth-error
**Adapters:** inbox ok · plaud ok (window {N}d) | REFUSED — signed in as a different account (account-mismatch) | REFUSED — no account bound to this vault yet (no-account-hint) | disabled | unavailable | STOPPED mid-run — connector wants re-authentication (auth-error) · m365 ok (window {N}d) | REFUSED — signed in as a different account (account-mismatch) | REFUSED — no account bound to this vault yet (no-account-hint) | disabled | unavailable | STOPPED mid-run — connector wants re-authentication (auth-error)
**Calendar enrichment:** ok | UNAVAILABLE
**Warnings:** {verbatim} | none
```

`Inbox swept` counts every file moved this run — processed meetings,
captures and parks alike, plus anything already synced — and reports the
pending remainder — that remainder is the number the vault owner actually
cares about. Count it from disk like everything else in this step.

Each adapter's `(window {N}d)` is that step-1 `dates window` call's
`effective_days` — 7 on a cold or missing watermark, narrower once the
watermark is doing its job. It is reported only for `ok`; a refused,
disabled, or unavailable adapter never computed one.

`New people` sums two sources, never just one: the orchestrator's own
`person ensure` calls for plaud, inbox, and capture attendees (step 3), and
the `new-people:` clause each m365 worker's `written` or
`possible-duplicate-of` line carries — you never call `person ensure` for
an m365 attendee yourself (step 6), so its count has to come from the
worker.

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
file to match one too** (`m365_routing.json` fits `m365_*.json`,
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

`--unattended` is what scheduled runs and the evening pipeline pass. Four
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
