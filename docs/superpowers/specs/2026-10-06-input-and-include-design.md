# Input and Include — design

**Date:** 2026-10-06 · **Status:** draft for owner review · **Branch:** `feat/input-and-include`

## Problem

Two menu entries confuse the vault owner, and both are about capture:

- **Inbox** reads like a mail inbox, which is something *you* work through.
  In fact it is a drop slot that the evening run empties. The name sets the
  wrong expectation.
- **Thoughts & ideas** is where a new note lands, but nothing ever reads it.
  The owner's own writing never reaches the second brain. If we fixed that by
  moving notes away after absorbing them, users would feel they had lost
  their notes. If we keep them, the folder becomes an unstructured pile
  within a month.

The vault's purpose is that the owner does not have to file or browse their
own notes. But owners still want to write their own notes, OneNote-style, and
keep them.

## Decisions (agreed with the owner, 2026-10-06)

| # | Decision |
|---|---|
| D1 | **Inbox → Input** in the menu, its table and all user-facing text. The folder stays `10-inbox/`; renaming it would mean a migration on every vault and a change to every skill that writes paths, for a folder the owner rarely sees by name. |
| D2 | Input stays a clickable table. It shows **everything the evening run picks up tonight**: dropped files, plus notes ticked **Include**. |
| D3 | Notes in Thoughts & ideas are **not absorbed by default**. A checkbox property **`include`** opts a note in. |
| D4 | An absorbed note **stays where it is**. The Thoughts & ideas table hides absorbed notes by default; a second view shows them grouped by project. The note text is never changed. |
| D5 | Two places to write: quick jottings go in **today's note**, longer pieces in their **own note**. |
| D6 | The daily note's `## End of day` section is renamed **`## Notes`**: jot anything there, any time of day, and it is read that evening. |

## 1. Input

**Table.** `99-workflow-config/views/Inbox.base` is renamed to `Input.base`,
because the file name is the tab title. The bookmark entry follows, with
title **Input** and the same icon and colour. Filter:

```yaml
filters:
  or:
    - and:
        - file.inFolder("10-inbox")
        - file.name != "README"
        - file.ext != "base"
    - and:
        - file.inFolder("80-thoughts-ideas")
        - file.ext == "md"
        - include == true
```

Columns:
- **Picked up tonight**: the link
- **Kind**: `Your note` for a Thoughts & ideas note; otherwise `Text`, `Note`
  or the upper-cased extension, as today
- **Added**

There is one view, **Tonight**.

**Stuck files are visible.** At render time, after the sync has run, the
recap counts the files still in `10-inbox/` (excluding README and `.base`).
If that count is above zero, the recap's glance callout gets one
CLI-computed line: `N item(s) still in [[Input]]: the evening run could not
process them`. Anything still in the folder at that point was not handled,
so the count is deterministic and needs no state. A count of zero adds no
line.

**Words.** Several texts are rewritten as "drop it here, it is picked up
tonight":
- the `10-inbox/README.md` title and opening
- Start here's menu line: **Input**, "what the evening run picks up tonight"
- How it works
- `CLAUDE.md` § Inbox Discipline, retitled **Input**

Skill prose that addresses the owner says "Input". Internal paths and
adapter names (`inbox` as a recording source) are unchanged.

## 2. Include: absorbing your own notes

**Properties on a note in `80-thoughts-ideas/`.** All are optional, and a
note without them behaves exactly as it does today.

| Property | Type | Set by | Meaning |
|---|---|---|---|
| `include` | checkbox | owner | read this note in tonight's run |
| `absorbed` | date | evening run | last date the run read it |
| `projects` | list of project slugs | owner, or the run if empty | where the note belongs; same shape as a meeting's `projects[]` |

**Pipeline (evening-sync).** Notes enter the existing stages; they do not get
a parallel path.

1. **Stage 2, harvest.** A new read-only CLI call, `notes harvest --vault`,
   lists the notes with `include: true` and returns each one's path, title,
   body, `projects` and modification time. A note over a size cap is listed
   with a warning, and its body is not passed on.
2. **Project assignment.** For a note with empty `projects`, the
   orchestrator picks zero or more projects using the meeting signals that
   are available for free text: content keyword match against project
   `keywords`, and entity/project names. Zero is a valid answer. Such a note
   is still absorbed (for recap and decision context) and is shown as
   *Not linked*.
3. **Update queue.** `updatequeue.run` takes the harvested notes as an extra
   input. A note assigned to a project queues that project the way a new
   meeting does, so a project with no meetings tonight is still updated. The
   queue entry gains `newNotes: [paths]`.
4. **Stage 4.** Each project subagent reads its `newNotes` end-to-end next to
   its meetings and logs. A state item taken from a note ends with the
   source marker `(note · [[stem]])`. Decision capture includes notes. A
   decision from a note carries `source: <note stem>`.
5. **Write-back, after stage 4.** A new CLI call, `notes mark-absorbed
   --path … --date <today> [--projects …]`, edits frontmatter only: it sets
   `include: false` and `absorbed`, and writes `projects` only if it was
   empty. A note is marked only when every project it was queued for came
   back with `stateWritten: true`, or when it had no project. Otherwise
   `include` stays ticked and the note retries tomorrow, which is the same
   failure rule the inbox sweep uses.
6. **Stage 6, recap.** A CLI-computed glance line, shown only when it
   applies: `Read N of your notes → [[project]], [[project]]`.

**Re-reading.** If the owner edits an absorbed note and wants the change
picked up, they tick `include` again. There is no automatic re-read on
edit, because that would absorb half-finished drafts. That is exactly what
D3 rules out.

**Never.** The run never changes a note's body, never moves or deletes a
note, and never reads `95-private/`.

**Thoughts & ideas table.** It gets two views, both with a visible
**Include** checkbox column so the owner can tick from the table:

- **Yours** (default): `absorbed` is empty, or the note was last modified on
  a **later day** than `absorbed`. Sorted by last edited. An edited note
  reappears here so the owner can choose to re-include it. The comparison is
  by day because the write-back itself bumps the modification time. An edit
  made on the evening of absorption, after the run, is therefore not
  flagged; this is acceptable because the run is the day's last step.
- **Absorbed**: `absorbed` is set, grouped by `projects`, with an *Absorbed*
  date column. A note with no project groups under *Not linked*.

## 3. Daily note: `## Notes`

- `daily-note write` renders `## Notes` with an empty `- ` jot line, in the
  place where `## End of day` is today.
- `daily-note read` maps **both** `## Notes` and `## End of day` to the same
  harvest field, so every existing daily note keeps working. The field is
  renamed `notes` in the read output, and `end_of_day` is kept as an alias
  for one release.
- Existing daily notes are **not rewritten**. Each one is the archive of its
  day.
- Ontology: daily-note `body_sections: [Recap, Meetings, Notes]`, with a
  line saying that `End of day` is the pre-structure-11 name.

## 4. Upgrade

Migration **010 → structure 11**:

- renames `99-workflow-config/views/Inbox.base` to `Input.base`, if
  unmodified; a modified copy is left in place and reported
- refreshes managed files: bookmarks, `Thoughts & ideas.base`, the inbox
  README, Start here, How it works, the CLAUDE.md section, and the ontology
- touches no notes

Evening-sync gates note absorption on `structure_version >= 11`, the
specific version it needs, not on "no migrations pending". This follows
the lesson from #264. On an older vault, stage 2 skips `notes harvest` and
everything else runs as it does today.

Version: the next patch on `main` at implementation time.

## 5. Testing

- **`notes harvest`:** reads only ticked notes. Covers the size cap, a
  malformed frontmatter warning, and that it never reads outside
  `80-thoughts-ideas/`.
- **`notes mark-absorbed`:** changes frontmatter only (body byte-identical),
  never overwrites a non-empty `projects`, and is idempotent.
- **`updatequeue`:** a project with only a new note queues, with `newNotes`.
  A note with no project queues nothing.
- **`daily-note`:** read covers both headings and the alias; write emits
  `## Notes`.
- **Recap:** the stuck-files line appears for N > 0 and is absent for 0. The
  notes line appears only when notes were read.
- **Migration 010:** the rename covers both the unmodified and the modified
  case, and the structure version bump is applied.
- **Template:** `validate_template.py` checks the Input and Thoughts & ideas
  bases, and that the YAML parses (a filter starting with `!` must be
  quoted).
- **Manual:** in a preview vault, check that
  - ticking Include makes the note appear in Input
  - after a run, the note is in *Absorbed* under its project
  - Input is empty
  - grouping by a list property renders acceptably in Bases (open risk,
    see below)

## Open risks

- **Grouping by a list property.** Bases groups by the whole list value, so
  a note on two projects forms its own group. This is acceptable because
  most notes have one project. Check it in the preview vault. If it looks
  bad, group by the first project with a formula.
- **Project assignment on free text** is weaker than on meetings, which have
  attendees and calendar subjects. A wrong assignment can be fixed by the
  owner editing `projects` and ticking Include again.

## Out of scope (separate issues)

- Dragging a file into today's note to drop it in Input. The note's link
  breaks when the sync archives the file outside Obsidian.
- `/report-feedback` saving an unsent draft into `10-inbox/`. That breaks
  "skill outputs never land in the inbox", and the sync would then process
  it.
