# Entity and team pages update themselves (#273 piece 3, #184)

## Problem

An entity's dossier changes only when the owner runs `/update-entity`.
Context, Relationship History, Dynamics (under the Meeting Log) and
Sensitivities stay `*No entries yet.*` for weeks while meetings, mail and
sessions about that entity pile up. Piece 2 (#281) made Stakeholders and
Engagements live; this piece makes the remaining four sections current
without the owner asking.

Builds on #277 (shared processing part `evening-sync/references/process.md`,
followed by `/evening-sync`, `/sync-recordings` step 9 and `/add` step 6) and
#281 (live Stakeholders/Engagements; `entity write` accepts only `context`,
`relationship_history`, `meeting_log`, `sensitivities`). **Built on top of
#281; the PR waits until #281 is merged** (no stacked PRs).

## Decisions (vault owner, 2026-10-12)

- **When:** in the shared processing part, so **every evening and on
  demand** (`/sync-recordings`, `/add`), for entities with something new.
  **No cap** on the number of entities per night, for now.
- **What:** all four sections are written automatically: Context,
  Relationship History, Dynamics and Sensitivities. Safeguards: every
  automatic line names its source; nothing is ever removed (`entity
  write`'s existing rules).
- **Teams (option C):** a team's material updates the **team's** page fully.
  The **parent** page gets only big events (milestones, decisions,
  escalations) in its Relationship History, marked with the team name.

## Design

### Which entities are queued

`sync update-queue` gains an **entity queue** next to `projectsNeedingUpdate`:
`entitiesNeedingUpdate`. An entity is queued when, since its
`entity-updated` stamp (or, when absent, its `last-updated` day at 00:00),
any of these arrived:

| Source | Belongs to entity E when | Activity time |
|---|---|---|
| Confirmed meeting (not `type: note`) | its `entities` contains E (derived from its projects, or set directly) | later of `date` and `confirmed-at` (as for projects) |
| Message log | its frontmatter `entities` contains E, or one of its strong `projects` has `entity: E` | `updated-at` |
| Session record (`_messages/sessions/`) | one of its `projects` has `entity: E` | `updated-at` |
| Note ticked Include | one of its `projects` has `entity: E` | queued while ticked (as for projects) |

**Teams.** For a queued **team** T (an entity with `parent: P`), the parent
P is queued too, in **parent mode**: its entry carries `teamFiles` (T's new
material, labelled with T's name) and P only takes big events from them into
Relationship History. P's own new material, if any, is handled in full as
usual. One entry per entity; a parent with its own material and team
material gets both lists.

Each queue entry: `{slug, dossierPath, entityName, entityUpdated, newFiles,
newLogs, newSessions, newNotes, teamFiles: [{team, teamName, files, logs,
sessions}], current}`. `current` is the dossier's four writable sections as
`entity read` returns them, so the subagent sees what is there.

Only `status` `active` and `prospect` entities are queued (`dormant` ones are
not).

### Writing: `entity write` + `entity touch`

The subagent writes through `entity write` (unchanged rules: Context and
Sensitivities replace a point with the same label, append otherwise;
Relationship History and Dynamics bullets are dated and added; nothing is
removed; the unvalidated banner stays). New: `entity touch --slug S
--timestamp YYYY-MM-DDTHH:MM` stamps `entity-updated` (byte-preserving), the
entity's equivalent of `project touch`. The subagent calls it after a
successful write, or when it judged nothing worth writing. Either way the
material is "seen".

**Source on every line.** Each item ends with its source marker, exactly as
on project pages:

- `(meeting · [[<stem>]])`
- `(mail · <link>)` / `(chat · <link>)` (the log group's link)
- `(session · [[<path>|<title>]])`
- `(note · <title>)`

The markers sit in the field that renders last (`why` for Context, `significance`
for Relationship History, `dynamics` for Dynamics, `implications` for
Sensitivities). Team material on a parent page adds `(<team name> team)`
before the marker.

### The subagent (process.md section D)

New section **D. Entity updates** in `process.md`, after C (so it can read
the projects' fresh "Where it stands"). Dispatch is one subagent per queued
entity, `model: sonnet`, in blocking batches of at most 3, with no cap on the
total. It is the same batching rule as C, with C's paragraph referenced, not
copied. Instructions:

1. Read the new material end to end (meetings: Key Takeaways, Debrief, Action
   items; logs via `messages for-project`; sessions; notes). Read the
   entity's `current` sections and the Engagements' projects' `stage`.
2. Decide what, if anything, changes, per section:
   - **Relationship History:** dated events that matter for the relationship
     (a milestone reached, a decision, an escalation, a contract, a key
     person change). Date = the event's date from the material. At most 3
     per run.
   - **Dynamics:** how the relationship feels, one line per real signal
     ("CFO pushes back on every budget line"). At most 3 per run.
   - **Context:** standing facts about the organisation (size, strategy,
     systems, priorities). Use a label that updates an existing point when
     the fact is the same topic; never restate what is there.
   - **Sensitivities:** what to handle with care (a topic, a person, a
     history). Same labelling rule.
   - **Parent mode:** only Relationship History, only big events, each
     marked `(<team name> team)`.
   Writing nothing is a valid outcome. Never invent; every item cites its
   source.
3. `entity write --slug S --edits <file>` with the chosen items, then
   `entity touch`. A refusal names the field: fix it and retry once.
4. Return `{"slug", "written": {section: count}, "notes"}`. A failure
   becomes a warning, not a retry; the entity stays queued for next time.

### Callers

- `/evening-sync`: section D runs after C, every evening.
- `/sync-recordings` step 9 and `/add` step 6: they follow `process.md`, so
  D runs on demand for the entities of what was just processed. The lock
  (#277) stays held through D; it is released after D, before the decision
  question.
- Returns gain `entitiesUpdated: [{slug, written}]`; the evening summary and
  the on-demand summaries list them in one line ("Entity pages updated:
  Acme, Finance (Acme)").

### Ontology

Entity gains `entity-updated` (optional, machine-maintained, ISO minute),
documented next to `last-updated` ("last-updated is the day the page last
changed; entity-updated is when the automatic update last read new
material"). No migration: the field appears with the first update.

## Testing

- **CLI:**
  - `entity touch`: stamps, is byte-preserving, refuses a bad timestamp.
  - `update-queue` entity queue:
    - each source type queues its entity;
    - material before `entity-updated` does not;
    - a team's material queues the team in full and the parent in parent
      mode with `teamFiles`;
    - dormant entities are skipped;
    - a meeting with `entities` but no project queues;
    - a session queues through its project's entity.
- **Skill contracts:**
  - process.md has section D after C;
  - D references C's batching rule rather than copying it;
  - D names `entity write` and `entity touch`;
  - D names the source markers and parent mode;
  - the Inputs table and Returns list entities;
  - the evening and on-demand summaries list entity pages updated.
- **End to end on a demo vault:** a confirmed meeting with an entity → the
  queue lists it → a hand-made subagent payload written with `entity write`
  + `entity touch` → the next queue does not list it.

## Out of scope

- Facts about people (piece 4).
- A cap or a weekly cadence (owner: no cap for now; revisit if the evening
  run gets too long).
- Rewriting or removing existing dossier content.

## Release

CLI (`update-queue` entity queue, `entity touch`), `process.md` section D,
summaries in evening-sync / sync-recordings / add, ontology, tests. No
structure change. CHANGELOG: entity pages now update themselves every
evening and on demand. Version bump.
