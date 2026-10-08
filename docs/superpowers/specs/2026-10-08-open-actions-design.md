# Open actions — design (#257)

Status: approved by the vault owner in session, 2026-10-08; renamed from "Actions" to "To Do's" everywhere the owner looks, same day. Plan:
`docs/superpowers/plans/2026-10-08-open-actions.md`.

## Why

The owner writes actions in the daily note (`- [ ]` under a meeting's
`#### Your to do's`), and nothing ever follows them up: the reader returns
them as context, "nothing routes it anywhere yet" (evening-sync stage 2). An
action written on Tuesday is invisible by Thursday. The owner wants one
table of every open action, **grouped per project and sorted by deadline**,
that looks and works like the other tables in the menu.

## What the owner approved

- **A real `.base`, not a Dataview list.** Prototyped both in Obsidian on
  2026-10-08. A Dataview task list cannot match the Bases look (no view tabs,
  no group header, no in-place checkbox, needs DataviewJS for clean output).
  Bases index properties, not checkbox lines, so each action becomes a note.
- **Menu: "Actions", directly under "Thoughts & ideas".**
- **Three ways to make an action, one note format:**
  1. Write `- [ ] …` in the daily note as today (the main way). The evening
     run turns each new one into an action note, **fills in what it can
     (project, deadline) and leaves the rest open**.
  2. **New** in the Actions table (makes an empty action note in the folder).
  3. Ask Claude in a session ("add an action: … by Friday, Acme").
- Done is the checkbox in the table — ticking it removes the row from
  *Open* at once (verified in Obsidian).

## The Action object

`65-to-dos/{YYYY-MM-DD}-{slug}.md` · Base: `65-to-dos/To Do's.base`.
A new top-level folder, next to the daily notes the actions come from; inside
an existing folder the notes would leak into that folder's table.

```yaml
object: action
required: [type]
optional: [action, project, due, source, created]
keys_present: [done]
enums:
  type: [action]
```

- `action` — the action as the owner wrote it. Display name in the table
  (falls back to the file name: a note made with **New** is named by its
  title).
- `project` — one active project slug, or empty. The table groups by the
  project's **name** ("Not linked" when empty), like Thoughts & ideas.
- `due` — unquoted ISO date, or empty. Empty sorts last.
- `done` — the checkbox. `keys_present`, so a filter on it is never fooled by
  a missing key.
- `source` — `[[YYYY-MM-DD]]`, the daily note it came from (absent for
  actions made by New or in a session). `created` — ISO date.
- The note body is empty; the owner may write in it. Nothing rewrites it.

## To Do's.base

- Filters: `file.inFolder("65-to-dos")`, `type == "action"`. **New** fills
  in `type: action` from the filter and lands in `65-to-dos/` even when new
  notes default elsewhere (both verified in Obsidian 1.14).
- View **Open** (first): `done != true`, grouped by project name, sorted by
  `due` ascending; columns Action · Done · Due · Overdue · Project · From.
  The Project column is also what gives a New note an empty `project` to fill.
- View **Done**: `done == true`, grouped by project name, last edited first.

## Evening run

Gated on `structure_version >= 12`, inside stage 2:

1. `actions harvest --from <recap_from> --to <recap_to>` (CLI, deterministic):
   - lists every **open, not yet recorded** task in the daily notes of the
     window — under a meeting (with its subject, entity and that entity's
     active projects) or anywhere else in the note;
   - **closes** an action note whose source line was ticked in its daily
     note (any date, not only the window), so ticking in either place counts;
   - a task ticked the same day it was written is not recorded.
2. For each new task Claude picks the project (judgment — the entity's only
   active project, else names/keywords in the text, else none) and copies
   the deadline **phrase** from the text, never computing a date.
3. `actions create --payload` (CLI) resolves the phrase against the daily
   note's date, writes the notes, and skips duplicates (same source + text).
   A phrase it cannot resolve leaves `due` empty.

Deadline phrases resolved: ISO `2026-10-14`; `14/10`, `14/10/2026`,
`14-10-2026`, `14.10`; weekday names in English, Dutch and French (the next
such day after the note's date); today / tomorrow (+ nl, fr). Anything else
is left open — filling in what is possible, not guessing.

The daily note is never edited. A tick in the table does not tick the daily
note's box; the table is where actions are followed up.

## Upgrade

Migration `011-structure-version-12` inserts the Actions bookmark directly
after Thoughts & ideas (or after Daily notes / at the end if the owner moved
those), keeping every other bookmark where it is — not lossy.
`To Do's.base`, the menu colour and the wording arrive with the template
refresh. A vault below 12 skips the actions step; nothing breaks.

## Out of scope

Actions from meeting transcripts (`## Action items` in meeting notes), owners
other than the vault owner, reminders, and showing actions on project pages.
