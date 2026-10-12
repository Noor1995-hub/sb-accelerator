---
name: add
description: Put one thing into the second brain now — pasted text, a file, or this conversation — with the owner's intent, then update the project pages right away. Triggers when the user invokes /add, or says "add this to my second brain" or "remember this". For recordings from Teams or a recorder, and for fetching everything waiting in the inbox, /sync-recordings is the skill.
user_invocable: true
origin: net-new
---

# Add

The owner hands over one thing. You work out what it is about and ask only
what you cannot tell; the CLI writes it as already accepted, and the brain is
updated before the owner leaves the chat.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat; say so plainly.

Set `VAULT` to the vault root. `$SCRATCH` is the session scratch directory: payloads land there, never in the vault. Also:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Read `ok` on every call; on failure surface `error` and `hint`. Run
`python3 "$VAULTLIB" config read --vault "$VAULT"` once at the start: its
`owner` and `timezone` are used below. Then run
`python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <config.timezone>`
once and keep its `today` field, verbatim.

## Usage

```
/add                      # this conversation, or what the owner pastes or names next
/add <text or file path>  # that text or file
```

## Rules

1. **One item per call**: one pasted text or file, or this one conversation.
   Several: call `/add` again.
2. **Nothing is written before the owner's OK** on the step-4 line.
3. **Always processed right away.** There is no "now or tonight".
4. **This skill never creates, writes or edits anything under `60-daily-notes/`.**
   It never reads mail or Teams.
5. **Never kept:** passwords, keys and tokens; anything from `95-private/`;
   personal matters about other people that are not about the work. When in
   doubt, leave it out and say so on the step-4 line.
6. **Never compute a date or a weekday.** `today` is the `today` field of
   `dates plan`, used as given.
7. **One question at a time**, dry and short. An unclear answer gets one short
   question back.
8. **Scratch.** Once anything has been written to `$SCRATCH`, every exit ends
   with `python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"`.

## Workflow

### 1. What was handed over

- **Text or a file**: pasted text, or a path.
- **This conversation**: `/add` with nothing else, or "add this conversation" /
  "add what we decided about X".

Unclear → ask once: *"This conversation, or something you'll paste?"* A
recording from a recorder or Teams → say that `/sync-recordings` fetches it
and lets you set its project, and end.

### 2. Get the content

**Text or a file.** Pasted text, or the file's text. A deck, spreadsheet,
image or other non-text file: refuse with that reason, write nothing.

**This conversation.** Summarize it yourself in step 3: the whole
conversation, or only the part the owner named.

### 3. Understand

Decide, from the content:

- **type**: `meeting` (a record of an interaction between people) or `note`
  (context, not a meeting) for text. A conversation with Claude is always a
  **session**.
- **projects**: zero or more active projects, matched on project names,
  entity names and the people involved. Use the routing digest
  (`sync routing-signals`) as `/sync-recordings` step 3 does. **A session
  needs at least one active project**: with none, it would be stored and
  never shown anywhere. If none fits, ask which project it belongs to, or
  offer `/new-project` first; if the owner wants no project, do not add it.
- **entities**: for an item with no project that is still about an entity,
  decide it as `/sync-recordings` step 3 does (passed in step 5 only when
  `projects` is empty).
- **calendar** (a `meeting` only): run calendar enrichment for this one item
  as `/sync-recordings` step 2 does, so `calendar_match` and the calendar
  confidence reason are true: found → the match; searched, nothing →
  `no-calendar-match`; tool unavailable → `calendar-tool-unavailable`. A
  `note` gets `calendar_match: false` and `calendar-not-applicable`.
- **people**: existing people by name. Someone new is created only after the
  step-4 OK.
- **facts about people**: anything the owner tells you a person said about
  themselves ("Jan told me he's moving to Antwerp") — kept only as the
  person said it, never your interpretation of them. A conversation that
  holds only such facts needs no project and no session record: step 5
  writes just the facts.

Ask one short question per thing you cannot tell. Never more than needed.

### 4. One line, one OK

Show one line and wait for a yes:

`Meeting · Acme ERP rollout · Jan Peeters, Sofie Maes · "Forecast call moves to Thursday"`

For a session, show the line plus at most five bullets of what will be kept:

```
Session · Acme ERP rollout · "Pricing approach for Acme"
- Fixed price for phase 1
- Time and material after go-live
```

Facts about people go under it as `Jan Peeters: moving to the Antwerp office`.

Anything you left out under rule 5: say so in one short line under it. For a
file already in `10-inbox/` (processed in place), the original keeps what it
holds: if it contains something rule 5 forbids, say so and ask the owner to
remove it from the file first. A
correction from the owner → show the line again. No → write nothing, end.

### 5. Write

Take the run lock — only now, never while a question is open:

```bash
python3 "$VAULTLIB" runlock acquire --vault "$VAULT" --routine add
```

`acquired: false` → nothing written; say *"Another run is busy (the evening run or another sync); try
again in a few minutes."* and end.

**From here until the end of step 6, every exit releases the lock first** —
the early exits below, an error from any command in steps 5–6, a failed
step 6:

```bash
python3 "$VAULTLIB" runlock release --vault "$VAULT" --routine add
```

New people the owner confirmed: `person ensure` as
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/SKILL.md` step 3 does.

**Text or a file.** First write it to `10-inbox/<today>-<short-kebab-title>.md`
(the text as given, minus anything rule 5 leaves out — named on the step-4
line; the name uses a–z, 0–9 and hyphens only, and if it exists add `-2`,
`-3`), with the owner's intent on the first line:

```markdown
<!-- added with /add on <today>: "<the owner's words: what it is, for which project>" -->
```

A file the owner gave that is already inside `10-inbox/` is processed in place
instead: prepend the same header line to it and use it as the inbox file below
(no copy).

Then run `sync scan` and take the entry for that file: its `recording_id`.
Listed under `already_synced` (the same content was synced before) → `sync
archive` it, tell the owner it is already in the brain, release the lock,
sweep scratch and end. Dispatch **one** worker exactly as `/sync-recordings`
step 6 ("Extract and write", the **inbox** briefing in
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/SKILL.md`) does, with a
blocking Agent call. That briefing already has the slots for the routing: pass
the owner-confirmed `projects`, `type` (`note` for a note; for a meeting leave
the subtype to the worker), attendee slugs (from `person ensure`), a
`calendar-subject` (the step-4 title), `calendar_match` and the calendar
confidence reason from step 3, `source` (the arrival channel: `manual` for
pasted text or a file, `email` for forwarded mail; `sync scan` does not
return it), `recording_id` from the scan, `recording-duration` (0 when
unknown), `entities` only when `projects` is empty, and `confidence` +
`confidence-reasons` stamped by `/sync-recordings` step 4's rules. The
owner's OK is recorded by the accept below, not by the confidence. The item's
date is a full date written in its own content, otherwise `today`.
Never derive a date from "Tuesday" or the like. Do not read the worker contract
yourself.

The worker replies `written: <stem>`. Verify the note is on disk, then move
the inbox file out:

```bash
python3 "$VAULTLIB" sync archive --vault "$VAULT" --path "10-inbox/<name>"
```

When the file was processed in place, this moves the original too.

No note written, or any other worker reply → leave the file in the inbox (the
evening run retries it), say so in one line, release the lock, sweep scratch
and end. Otherwise mark the note accepted:

```bash
cat > "$SCRATCH/add.payload.json" <<'JSON'
[{"path": "20-meetings/<stem>.md", "action": "accept"}]
JSON
python3 "$VAULTLIB" meeting triage-apply --vault "$VAULT" --items "$SCRATCH/add.payload.json"
python3 "$VAULTLIB" sync reconcile-reviews --vault "$VAULT"
python3 "$VAULTLIB" sync rederive-entities --vault "$VAULT"
```

A `refused` item: say the reason in one line, release the lock, sweep scratch
and end.

**This conversation.**

```bash
cat > "$SCRATCH/session.payload.json" <<'JSON'
{"title": "Pricing approach for Acme", "date": "<today>",
 "projects": ["acme-erp-rollout"], "people": ["jan-peeters"],
 "summary": ["Fixed price for phase 1", "Time and material after go-live"],
 "decisions": ["Phase 1 is fixed price"],
 "scope": "what we decided about pricing"}
JSON
python3 "$VAULTLIB" session write --vault "$VAULT" --note "$SCRATCH/session.payload.json"
```

`scope` is `"whole"` when the owner named no part. `decisions` lists the
decision candidates you saw (may be empty); section C applies the
material-decision test to them. If `session write` fails: surface `error` and
`hint`, release the lock, sweep scratch and end.

**Facts about people** (each confirmed in step 4), per person — after
`session write`, or as the whole write when there is no session record:

```bash
cat > "$SCRATCH/person-facts-<slug>.payload.json" <<'JSON'
{"facts": [{"date": "<today>", "fact": "Is moving to the Antwerp office. (session · [[_messages/sessions/<stem>|<title>]])"}]}
JSON
python3 "$VAULTLIB" person write --vault "$VAULT" --slug <slug> --automatic --facts "$SCRATCH/person-facts-<slug>.payload.json"
```

`<stem>` is the `stem` `session write` returned. With no session record the
marker is `(session · /add, <today>)`. A fact is what the person said about
themselves, never your reading of them; it stays on their page and goes into
nothing meant for someone else. A fact listed in `skipped`: fix it and retry
once, else say so in step 8's **Warnings**.

### 6. Process

Follow `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md` with
the **On demand** column of its Inputs table, exactly as `/sync-recordings`
step 9 does: sections A, B, C, D and E, `<today>` from the `dates plan` run above,
`<owner-slug>` = `owner` from `config read`, `sync_notes` lines to step 8's
**Warnings**. When section E has returned, release the lock — the project,
entity and people pages are written, and the question that follows must not
hold up the evening run:

```bash
python3 "$VAULTLIB" runlock release --vault "$VAULT" --routine add
```

### 7. Decisions in the chat

As `/sync-recordings` step 10: list `decisionsWritten`, one line each, none →
skip to step 8. Ask once **"Keep or dismiss?"**, and run
`decision review --keep|--dismiss` with `--path "<decisionsDir>/<stem>.md"`.
"Not now" → they stay in Decisions › To review.

### 8. Summary

```
## Added
**What:** Meeting · Acme ERP rollout · "Forecast call moves to Thursday"  (or Session · …)
**Project pages updated:** {names}
**Entity pages updated:** {names, a team as "Finance (Acme)"} | none
**People pages:** {N} facts added for {M} people | none
**Decisions:** {N} kept · {N} dismissed · {N} left in Decisions › To review
**Warnings:** {verbatim} | none
```

Then sweep scratch:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```
