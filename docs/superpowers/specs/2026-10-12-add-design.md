# `/add`: put something into the brain now, with your intent (#267)

## Problem

Two kinds of input have no good way in today:

- **Informal recordings and transcripts.** A Plaud recording of a hallway
  conversation has no calendar event behind it, so the sync cannot tell which
  project or people it belongs to: it lands in triage with `projects: []`. A
  transcript or notes from another app can be dropped in Input, but it waits
  for a sync, and nobody tells the sync what it is about.
- **A conversation with Claude itself.** A useful working session (a pricing
  discussion, a plan for a client) is lost when the session ends.

The owner wants one call: *"add this to my second brain"*. Claude reads it,
asks only what it cannot tell, and the brain is updated right away.

Builds on #277 (on-demand processing in `/sync-recordings`: `process.md`,
`meeting triage-apply`, `decision review`, `runlock`). **Not built until
#277 is merged** (no stacked PRs in this repo).

## Decisions (vault owner, 2026-10-12)

- **Inputs:** a Plaud recording without a calendar event; text the owner has
  (pasted, or a file: transcript, notes); this conversation with Claude.
  Audio files that need transcription are out of scope.
- **Claude asks only what it cannot tell** (type, project, people), then
  shows one line for the owner's OK.
- **Always processed right away.** No "now or tonight" question.
- **A recording or transcript becomes a normal meeting note**, written as
  already accepted (the owner confirmed it in the chat), so it never sits in
  triage.
- **A conversation does not become a visible note.** Its summary is kept as a
  hidden *session record*, so project pages, decisions and people can point
  to their source. It appears in no table and no menu.
- **What is kept of a conversation:** a summary, by default of the whole
  conversation; only the part the owner names when they name one
  ("add what we decided about pricing").
- **Approach:** `/add` writes the item as accepted and then follows the same
  shared processing part as #277 (`evening-sync/references/process.md`). It
  is not a front door that sends the item back through triage.

## Design

### Flow

| Step | What |
|---|---|
| 1 | Work out what was handed over: a Plaud recording, text or a file, or this conversation |
| 2 | Get the content |
| 3 | Understand: type (meeting or context), projects, people. Ask only what is unclear |
| 4 | Show one line, wait for OK |
| 5 | Take the run lock, write |
| 6 | Process (`process.md`, on demand) |
| 7 | Decisions in the chat (keep / dismiss) |
| 8 | Summary |

The name is `/add`. "Add this to my second brain" and "remember this" in
plain words also trigger it. The skill description must keep `/sync-recordings`
as the skill for "sync my meetings": `/add` is for **one** item the owner hands
over.

### Step 1–2: Getting the content

**Plaud recording.** List the owner's recent recordings that are not yet in
the vault: the same Plaud adapter, account-binding gate and `sync dedup` that
`/sync-recordings` uses (follow its "The three adapters" and "Account
binding" sections; never a second implementation). Show at most 10, newest
first: `1. Today 14:20 · 32 min · "Hallway chat"`. The owner picks one. If the
owner already described it ("this afternoon's recording"), and exactly one
matches, take it without the list.

**Text or a file.** Pasted text, or a file path the owner gives. The text is
written to `10-inbox/` as a file, with an **intent header** in the owner's
words at the top:

```markdown
<!-- added with /add on 2026-10-12: "notes from the Acme pricing call, for Acme ERP" -->
```

Then it follows the inbox path (below). A file in a format the inbox already
parks (a deck, a spreadsheet, an image) is refused here with that reason,
before anything is written.

**This conversation.** Claude writes the summary itself (step 3). Nothing is
fetched.

### Step 3–4: Understand, then one OK

Claude decides:

- **type:** `meeting` (a record of an interaction between people) or `note`
  (context, not a meeting). A conversation with Claude is always a session
  record, never a meeting.
- **projects:** zero or more active projects, from the same signals the sync
  uses (project names, `keywords`, entity names, people).
- **people:** existing people by name; a new person is created as the sync
  does (`person ensure`), but only after the owner's OK.

It asks one short question per thing it cannot tell, never more than needed.
Then it shows one line and waits for a yes:

`Meeting · Acme ERP rollout · Jan Peeters, Sofie Maes · "Forecast call moves to Thursday"`

For a conversation, the line shows the summary's key points in at most five
bullets, so the owner sees what will be kept before anything is written.

### Step 5: Write

Take the run lock first (`runlock acquire --routine add`). Refused → nothing
written; say *"Your evening run is busy; try again in a few minutes"* and end.
From here, every exit releases the lock first, up to the end of step 6.

**Plaud recording, or text/file (meeting or note).** Dispatch **one**
`sync-worker` with the same briefing `/sync-recordings` step 6 gives it,
plus the routing the owner just confirmed (projects, attendees, type). It
writes the meeting note (`meeting write`, `needs-review`), and for an inbox
file it archives the file as usual. Then mark it accepted with the #277 commands:

```bash
python3 "$VAULTLIB" meeting triage-apply --vault "$VAULT" --items "$SCRATCH/add.payload.json"   # [{"path": ..., "action": "accept"}]
python3 "$VAULTLIB" sync reconcile-reviews --vault "$VAULT"
python3 "$VAULTLIB" sync rederive-entities --vault "$VAULT"
```

The meeting note keeps the normal `confirmed-at` stamp, so the evening run's
queue treats it exactly as a meeting accepted in triage.

**Conversation.** New CLI:

```bash
python3 "$VAULTLIB" session write --vault "$VAULT" --note "$SCRATCH/session.payload.json"
```

The payload has `title`, `date` (from `dates plan`, never computed),
`projects`, `people`, `summary` (bullets), `decisions` (candidate lines, may
be empty) and `scope` (`whole` or the owner's words for the part kept). The
CLI writes `_messages/<date>-session-<title-slug>.md`:

```yaml
---
type: session
date: 2026-10-12
updated-at: 2026-10-12T15:42
projects: [acme-erp-rollout]
people: [jan-peeters]
scope: "what we decided about pricing"
---
# Pricing approach for Acme
- …
```

Why `_messages/`: it is already hidden in Obsidian (`app.json`), already a
place `decision write` resolves a `source` in, and already linkable
(`links.py`). Every existing reader there globs `*-messages.md`, so a
`*-session-*.md` file is invisible to mail and Teams code. No new folder, no
migration. The CLI refuses unknown project or people slugs (as
`triage-apply` does) and refuses a payload with an empty summary.

### Step 6: Process

Follow `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md`,
**On demand** column, exactly as `/sync-recordings` step 9 does. One change
in the shared part makes session records count:

- **`update-queue` indexes session records** next to message logs: a session
  whose `projects` contains the project and whose `updated-at` is at or after
  the project's `state-updated` queues it, under a new `newSessions` list.
  Sessions do not count as meetings or messages in any metric.
- **Section C reads `newSessions`** like `newLogs`: every state item taken
  from one ends with `(session · <link>)`, where `<link>` is the record's
  link. A decision from a session carries `source: <session stem>`.

So the project page and decisions point to "(session · …)", and the evening
run does not take the session again (its `updated-at` is older than the
state write).

Notes ticked Include are processed too, as in `/sync-recordings` on demand:
`/add` follows the same part, so they come along when they belong to the same
projects. This is accepted (it is what "process now" means), not avoided.

Release the lock when section C has returned.

### Step 7–8: Decisions and summary

The same as `/sync-recordings` steps 10–11: list `decisionsWritten`, ask
*"Keep or dismiss?"*, `decision review`; then a short summary:

```
## Added
**What:** Meeting · Acme ERP rollout · "Forecast call moves to Thursday"  (or: Session · …)
**Project pages updated:** {names}
**Decisions:** {N} kept · {N} dismissed · {N} left in Decisions › To review
**Warnings:** {verbatim} | none
```

### Never kept

From a conversation or pasted text: passwords, keys and tokens; anything
from `95-private/`; personal matters about other people that are not about
the work. When in doubt, leave it out and say so in the line at step 4.
The owner sees the summary before it is written (step 4).

### Not running twice

The same `runlock` as #277, routine `add`. A Plaud recording added with
`/add` is not fetched again by the evening run: `sync dedup` finds its
`source-recording-id` in the written meeting note (existing behaviour).

### Rules added to `/add`

- Never writes, creates or edits anything under `60-daily-notes/`.
- Never reads mail or Teams.
- One item per call. Several items: call it again.
- Never written without the owner's OK on the step-4 line.

## Testing

- **CLI (pytest):**
  - `session write`: writes to `_messages/` with the frontmatter above;
    refuses unknown slugs and an empty summary; the title slug is safe; a
    second call with the same title on the same day gets a suffix, never an
    overwrite.
  - `update-queue`: a session after `state-updated` queues its project under
    `newSessions`; one before does not; sessions do not change any metric;
    a `*-session-*.md` file is ignored by the mail/Teams readers (`msglog`,
    `health`, `dailynote` recap).
  - `decision write`: `source: <session stem>` resolves.
- **Skill contracts:**
  - `/add` points at `process.md` and at `/sync-recordings`' adapter and
    worker sections (no second Plaud implementation).
  - It never names `60-daily-notes` and never calls `daily-note write`.
  - It takes and releases `runlock` with routine `add`.
  - `process.md` section C handles `newSessions` with the `(session · …)`
    marker.
- **End to end on the demo vault:** a pasted transcript becomes an accepted
  meeting note and updates its project; a conversation becomes a session
  record, the project page cites it, the evening `update-queue` does not
  re-queue it, and nothing appears in Meetings.

## Out of scope

- Audio files that need transcription.
- Several items in one call.
- `sync-messages`' "forget someone" reaching into session records. Noted as a
  follow-up: a forget request today does not remove that person from
  session records.
- The event use case (#275).

## Release

New skill, CLI and `update-queue` change, tests. No vault structure change
(sessions live in the existing hidden `_messages/`), so no migration.
`Start here.md` gets one line about `/add` (template refresh). Version bump
and CHANGELOG entry as usual.
