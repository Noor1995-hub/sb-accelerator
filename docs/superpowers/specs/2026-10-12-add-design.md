# `/add`: put something into the brain now, with your intent (#267)

## Problem

Two kinds of input have no good way in today:

- **Transcripts and notes without a source.** A transcript or notes from
  another app can be dropped in Input, but it waits for a sync, and nobody
  tells the sync what it is about.
- **Informal Plaud recordings** (no calendar event) are already fetched by
  `/sync-recordings`, but land in its triage list as "no project". That is
  solved in `/sync-recordings`, not in `/add` (see "Project suggestion in the
  meeting sync").
- **A conversation with Claude itself.** A useful working session (a pricing
  discussion, a plan for a client) is lost when the session ends.

The owner wants one call: *"add this to my second brain"*. Claude reads it,
asks only what it cannot tell, and the brain is updated right away.

Builds on #277 (on-demand processing in `/sync-recordings`: `process.md`,
`meeting triage-apply`, `decision review`, `runlock`). **Not built until
#277 is merged** (no stacked PRs in this repo).

## Decisions (vault owner, 2026-10-12)

- **Inputs:** text the owner has (pasted, or a file: transcript, notes); this
  conversation with Claude. **Not Plaud** (owner, 2026-10-12):
  `/sync-recordings` already fetches every Plaud recording and its triage can
  set project and people, so `/add` would be a second way to do the same.
  `/sync-recordings` handles everything that comes from a source; `/add`
  handles what has none. Audio files that need transcription are out of scope.
- **Project suggestion in the meeting sync** (owner, 2026-10-12): in
  `/sync-recordings`' chat triage, a meeting with no project gets a suggested
  project from its content. Built on this branch, next to `/add`.
- **Claude asks only what it cannot tell** (type, project, people), then
  shows one line for the owner's OK.
- **Always processed right away.** No "now or tonight" question.
- **A transcript or notes become a normal meeting note** (or a `note`), written as
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
| 1 | Work out what was handed over: text or a file, or this conversation |
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

**Text or a file (meeting or note).** Dispatch **one** inbox
`sync-worker` with the same briefing `/sync-recordings` step 6 gives it,
plus the routing the owner just confirmed (projects, attendees, type). It
writes the meeting note (`meeting write`, `needs-review`). `/add` then moves the inbox file out with `sync archive` once the note
is verified on disk, as `/sync-recordings` does: Input is only a stop on the
way and is empty again when `/add` ends. If no note was written, the file
stays in Input and the evening run retries it; the summary says so. Then mark it accepted with the #277 commands:

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
CLI writes `_messages/sessions/<date>-session-<title-slug>.md` ("session" in
the name keeps it apart from decision notes, which are `<date>-<title>`; a
session needs at least one active project, and its title may not contain
`[`, `]` or `|`):

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

Why `_messages/sessions/`: `_messages/` is already hidden in Obsidian
(`app.json` ignores the whole folder, subfolders included), and a subfolder
keeps the sessions apart from the mail and Teams day logs (owner, 2026-10-12).
Every existing reader in `_messages/` globs `*-messages.md` in the folder
itself, never recursively, so sessions are invisible to mail and Teams code.
Two readers must learn the subfolder: `decision write`'s source lookup
(`decision._resolve_source`, which today searches `_messages/` only) and
`links.py`'s object kinds (which today accepts `_messages/<file>` only). The
CLI creates `sessions/` on first write; no migration. The CLI refuses unknown project or people slugs (as
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

The same `runlock` as #277, routine `add`. A text added with `/add` is not
taken again by the evening run: its inbox file is archived, and its content
hash is in the written meeting note (existing `sync scan` behaviour).

### Rules added to `/add`

- Never writes, creates or edits anything under `60-daily-notes/`.
- Never reads mail or Teams.
- One item per call: one pasted text or file, or this
  one conversation. Several items: call it again. (Owner, 2026-10-12: start
  with one at a time; a multi-item list with one OK is a possible follow-up.)
- Never written without the owner's OK on the step-4 line.

## Project suggestion in the meeting sync

In `/sync-recordings` step 8 (#277), a meeting with no project today shows
"no project". New: for each such item, read the note (title, Key Takeaways,
Debrief) and suggest **at most one** active project, from the same signals as
routing (project names, `keywords`, entity names, the people on it). Only
when one project clearly fits; otherwise it stays "no project". The line
shows the suggestion with a question mark:

`3. Hallway chat · Mon 12 Oct 14:20 · no project — Acme ERP rollout? · Jan Peeters`

**Accept on that line takes the suggestion**: it is applied as a change
(`projects: [<suggested>]`, accepted). The owner can say otherwise in the same
answer ("3 accept, no project", "3 project is finance close"). The
interpretation read-back (#277) covers it: a suggestion taken counts as a
change. Skill text only: `triage-apply` already writes a project change.

## Testing

- **CLI (pytest):**
  - `session write`: writes to `_messages/` with the frontmatter above;
    refuses unknown slugs and an empty summary; the title slug is safe; a
    second call with the same title on the same day gets a suffix, never an
    overwrite; `sessions/` is created on first write.
  - `update-queue`: a session after `state-updated` queues its project under
    `newSessions`; one before does not; sessions do not change any metric;
    a file in `_messages/sessions/` is ignored by the mail/Teams readers
    (`msglog`, `health`, `dailynote` recap).
  - `decision write`: `source: <session stem>` resolves to the file in
    `_messages/sessions/`.
  - `links.py`: a `_messages/sessions/<file>` link resolves as a session.
- **Skill contracts:**
  - `/sync-recordings` step 8 suggests a project for a meeting with none, shows
    it with a question mark, and says that accept takes the suggestion.
  - `/add` points at `process.md` and at `/sync-recordings`' worker step
    (no second extraction); it never mentions Plaud.
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
(sessions live in `_messages/sessions/`, inside the existing hidden folder), so no migration.
`Start here.md` gets one line about `/add` (template refresh). Version bump
and CHANGELOG entry as usual.
