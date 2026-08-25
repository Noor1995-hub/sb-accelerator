---
type: note
---

Your second brain. Four things to know, then you can close this note.

## The daily loop

Everything runs off your daily note in `60-daily-notes`. Two commands drive it:

- **`/morning-brief`** — what's happening today, who you're seeing, what's
  waiting on you.
- **`/evening-sync`** — what happened, what changed, what's queued for
  tomorrow.

Between them, jot whatever you like directly in the daily note. Free text is
fine; nothing needs a format.

## The five tables

Each is a live view, not a document — they update themselves as notes change.

| | What it holds |
|---|---|
| **Meetings** | Every meeting, newest first. The *Triage* view is your queue. |
| **Projects** | What's in flight, with the next milestone. |
| **Entities** | Organisations you deal with — one dossier each. |
| **People** | Individuals, their role, and when you last spoke. |
| **Decisions** | What was decided, when, and what it superseded. |

They're pinned at the top of the sidebar.

## Reviewing

Meetings arrive marked **needs-review** because something was inferred rather
than known — a name matched by guess, a calendar entry matched loosely. Open
the *Triage* view and tick **Reviewed** once it looks right. That tick is the
signal that a meeting can be trusted downstream; nothing else writes it.

Anything marked `<!-- needs-review -->` in a table cell is the same idea: a
value that was inferred and wants your eye.

## Where things live

- `10-inbox` — anything unfiled. Gets swept into the right place.
- `20-meetings` · `30-projects` · `40-entities` · `50-people` — the objects
  behind the five tables.
- `60-daily-notes` — the daily loop.
- `70-resources` · `80-thoughts-ideas` — reference material and your own notes.
- `90-archive` — finished, kept.
- `95-private` — never read by any command. Yours alone.
- `99-workflow-config` — how the assistant works: who you are, how you like
  things written, what the vocabulary means. Worth editing when something
  reads wrong.
- `claude` — the assistant's own machinery. Visible on purpose, so nothing
  about how it works is hidden from you; nothing you need day to day.

Ask for anything in plain language. If a command would help, you'll be told.
