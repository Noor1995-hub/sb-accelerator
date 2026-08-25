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

| Adapter | Discovery | Availability check |
|---|---|---|
| `inbox` | `sync scan` over `10-inbox/` | always available |
| `plaud` | Plaud MCP `list_files` | ToolSearch finds `mcp__plaud__list_files` |
| `m365` | — | **not yet supported** — the retrieval path is pending verification; say so if enabled |

### Account binding — before anything is listed

A connector adapter runs against whatever account is signed in at the *user*
level, which may not be this vault's account. The config's `account_hint`
binds them, and the check is deterministic, not judgment:

1. Call the connector's whoami tool (`mcp__plaud__get_current_user`; for
   M365 calendar enrichment, `get_me`). Write the raw JSON to scratch with
   the Write tool.
2. Run the gate:

```bash
python3 "$VAULTLIB" config verify-account --vault "$VAULT" \
  --adapter plaud --identity "$SCRATCH/plaud.whoami.json"
```

3. Only `match: true` proceeds. On `match: false` the adapter is **refused,
   in both modes** — nothing is listed, nothing is synced. Delete the whoami
   scratch file immediately. Interactively, tell the user the `reason` and
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
window. Write the raw JSON result to `$SCRATCH/plaud.list.json` with the Write tool
— never echo large JSON through Bash. Then dedup the ids,
namespaced:

```bash
printf '%s' '["plaud:abc123", "plaud:def456"]' > "$SCRATCH/ids.json"
python3 "$VAULTLIB" sync dedup --vault "$VAULT" --ids "$SCRATCH/ids.json"
```

Only `new` ids proceed. For each: `mcp__plaud__get_transcript` (required — on
a transient error retry up to 3×, then skip this recording this run; it
retries next run by construction) and `mcp__plaud__get_note` (optional
enrichment — on failure proceed without). Write each raw result to scratch,
then normalize:

```bash
python3 "$VAULTLIB" plaud reassemble \
  --meta "$SCRATCH/rec_42.meta.json" \
  --transcript "$SCRATCH/rec_42.transcript.json" \
  --note "$SCRATCH/rec_42.note.json" \
  --out "$SCRATCH" --timezone <config.timezone>
```

The result names the blob file and carries `recording_id`, `duration_min`,
and `recorded_local`. On a Plaud **401**: report it and stop this adapter —
never retry auth in a loop; re-authentication is interactive and belongs to
the user.

The executive's timezone is `timezone` from `config read` — pass the IANA
name. If it is in `missing`, the plaud adapter and calendar enrichment
cannot run: skip them with an explicit line. If the host cannot resolve
timezone names, the error's hint says to pass `--utc-offset` instead.

### 2. Calendar enrichment (optional, honest about absence)

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
python3 "$VAULTLIB" dates window --start 2026-08-20T16:42 --timezone <tz>
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

**Also pass `entities`** — the entity slugs the meeting was *about*, which is
wider than who was in the room. You have them already: signal 1 resolves the
entity directly, and a match via signal 2 or 3 gives a project whose
`entity:` field names one. An internal 1:1 reviewing a client account carries
that client; a meeting about no entity at all carries nothing.

This is the field an entity dossier's Meeting Log joins on, and it is the
*only* one: Dataview sees just what a meeting note itself says, and a note
that names its projects does not name the organization behind them. So pass
it even when `projects` is empty — an intro call with a prospect that has no
project yet still belongs in that prospect's dossier, and this is the only
way it gets there.

Attendees are **person slugs**. For each attendee named by the calendar or
clearly identified in the transcript, ensure the note exists:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<Full Name>"
```

Use the returned slugs. The executive attends their own meetings — include
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
  "entities": ["meridian-freight-holdings"],
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

Payload rules the CLI enforces (so get them right the first time):

- `title` is a short kebab-able label — the filename becomes
  `{DD-MM-YY}-{title-slug}.md`. `date` is ISO, the recording's local start.
- `attendees`/`projects`/`entities` are slugs and must resolve (person notes,
  project folders, `40-entities/<slug>/dossier.md`). `attendees` must be
  non-empty — except on a `type: note` capture, which may pass `[]` when the
  item names nobody. `projects` may be empty (triage catches unassigned
  meetings). `entities` is optional and omitted from the file when not passed.
  Optional `people` (slug list) renders a `## People` wikilink section.
  `takeaways` is 1–5 strings. `type` values with a colon (`"1:1"`) are handled
  by the CLI — pass them as plain strings.
- Do NOT pass `review_status`, `reviewed`, `archived`, or `processed` — the
  CLI sets them.
- `source-recording-id` is **required** on every write — it IS the dedup
  ledger. For inbox files it is the `recording_id` from `sync scan`; for
  Plaud it comes from `plaud reassemble`.

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
**Skipped / errors:** {N} (will retry next run)
**Adapters:** inbox ok · plaud ok | REFUSED — signed in as a different account (account-mismatch) | REFUSED — no account bound to this vault yet (no-account-hint) | disabled | unavailable · m365 disabled | not yet supported
**Calendar enrichment:** ok | UNAVAILABLE
**Warnings:** {verbatim} | none
```

`Inbox swept` counts every file moved this run — processed meetings,
captures and parks alike, plus anything already synced — and reports the
pending remainder — that remainder is the number the executive actually
cares about. Count it from disk like everything else in this step.

## Scratch hygiene

Raw connector JSON — whoami payloads, `list_files` listings, transcripts —
is engagement data that must not outlive the run. It lands only in the
session scratch directory, never the vault. At the end of the run, success
or refusal, delete the raw connector files this run wrote:
The names below are the ones this contract instructs; if you wrote any
other raw connector file, delete it too.

```bash
rm -f "$SCRATCH"/plaud.whoami.json "$SCRATCH"/m365.whoami.json "$SCRATCH"/rec_*.json "$SCRATCH"/plaud.list.json "$SCRATCH"/*.blob.md "$SCRATCH"/ids.json
```

On an account-mismatch refusal, delete the whoami payload immediately —
before writing the summary. (The gate runs before listing, so on a refusal
no listing ever reaches disk.)

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
