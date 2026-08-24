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

Read `99-workflow-config/context/tools-and-systems.md` first: it says which
capture channels this deployment uses. Then, per adapter, verify the tools
actually exist before running it. An adapter that is declared but unavailable
is **skipped with an explicit line in the summary** — never a silent zero.

| Adapter | Discovery | Availability check |
|---|---|---|
| `inbox` | `sync scan` over `10-inbox/` | always available |
| `plaud` | Plaud MCP `list_files` | ToolSearch finds `mcp__plaud__list_files` |
| `m365` | — | **not yet supported** — the retrieval path is pending verification; say so if declared |

## Workflow

### 1. Scan and dedup

**Inbox:**

```bash
python3 "$VAULTLIB" sync scan --vault "$VAULT"
```

`candidates` are files whose content hash is in no meeting note and not on
the skip list. Which candidates are actually transcripts is your judgment —
read the head of each file; a forwarded email that is meeting notes by
another name qualifies, a random PDF does not. Report `already_synced` files
so the user can archive them (inbox discipline: nothing lives there).

**Plaud** (when available): call `mcp__plaud__list_files` for the recent
window. Write the raw JSON result to your session scratch directory with the
Write tool — never echo large JSON through Bash. Then dedup the ids,
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
  --out "$SCRATCH" --timezone <executive-timezone>
```

The result names the blob file and carries `recording_id`, `duration_min`,
and `recorded_local`. On a Plaud **401**: report it and stop this adapter —
never retry auth in a loop; re-authentication is interactive and belongs to
the user.

The executive's timezone is prose in
`99-workflow-config/context/identity.md` — read it and pass the IANA name.
If the host cannot resolve timezone names, the error's hint says to pass
`--utc-offset` instead.

### 2. Calendar enrichment (optional, honest about absence)

If the Microsoft 365 calendar tool is available (ToolSearch
`outlook_calendar_search`), match each recording to a calendar event. Compute
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

### 3. Route: projects and attendees

Judgment, with signals in this order — stop at the first confident match:

1. External attendee email domains → entity: list `40-entities/*/`, match the
   domain root against entity slugs, then link that entity's active projects
   (`30-projects/*/index.md` where `entity` matches).
2. Calendar subject keywords against project names and slugs.
3. Transcript content keywords against project names and slugs (lower
   confidence).

An empty `projects: []` is fine — triage catches unassigned meetings. Never
force a link.

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

There is no auto-confirm: every synced meeting lands `needs-review`, and the
reviewed checkbox in Meetings.base is the confirm path. The stamp is the data
a future calibration needs — write it accurately, not optimistically.

### 5. Confirm the plan (interactive mode only)

Skipped entirely under `--unattended`. Show one table — title, date,
projects, new people, confidence — and ask once: proceed / edit / skip
items. For a recording the user says to permanently drop:

```bash
python3 "$VAULTLIB" sync skip --vault "$VAULT" --id plaud:abc123
```

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
- `attendees`/`projects` are slugs and must resolve (person notes, project
  folders). `takeaways` is 1–5 strings. `type` values with a colon
  (`"1:1"`) are handled by the CLI — pass them as plain strings.
- Do NOT pass `review_status`, `reviewed`, `archived`, or `processed` — the
  CLI sets them.
- Inbox files: `source-recording-id` is the `recording_id` from `sync scan`.
  Every write carries one — it IS the dedup ledger.

Read the result: a `conflict` of kind `confirmed-target` means the CLI wrote
a `--v2` sibling marked `needs-attention` instead of touching a confirmed
note — report it, it surfaces in triage. `stem-collision` means a `-2`
suffix. An `error` about an already-synced id means dedup was bypassed —
stop and say so.

### 7. Summarize — from disk, not from memory

Count what exists, not what you intended (a lab run once reported
"Processed: 0" after writing a meeting correctly):

```
## Sync Complete
**Processed:** {N} → `20-meetings/` ({list the stems})
**New people:** {N} created in `50-people/`
**Needs attention:** {N} (would have overwritten confirmed notes)
**Skipped / errors:** {N} (will retry next run)
**Adapters:** inbox ok · plaud ok · m365 not configured
**Calendar enrichment:** ok | UNAVAILABLE
```

## Unattended mode

`--unattended` is what scheduled runs and the evening pipeline pass. Two
rules, not negotiable:

1. **Never ask a question.** A blocked prompt means the run exits having
   done nothing. Ambiguity → skip that recording and report it; it retries
   next run.
2. **Prefer under-routing to wrong routing.** No confident project match →
   `projects: []` and low confidence; triage exists for exactly this.

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
