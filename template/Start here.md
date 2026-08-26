---
type: note
---

Your second brain. Five things to know, then you can close this note.

> [!tip] The one habit that matters
> Run **`/evening-sync`** at the end of the day. Everything else in here
> follows from it.

## The daily loop

Everything runs off your daily note in `60-daily-notes`, and one command
drives it: **`/evening-sync`**, at the end of the day. It writes *tomorrow's*
note — a recap of today, then a prepared section for each meeting on
tomorrow's calendar, with who's coming and what happened last time. There is
no morning command to run: tomorrow's note is already waiting when you open
the vault.

Each note has three parts. **Recap** is written for you. **Meetings** is one
heading per meeting. **End of day** is yours. Jot whatever you like under any
of them — free text is fine, nothing needs a format, and the next evening run
reads what you wrote.

## The five tables

Each is a live view, not a document — they update themselves as notes change.

| | What it holds |
|---|---|
| **Meetings** | Every meeting, and notes captured from email or voice memo — newest first. The *Triage* view is your queue. |
| **Projects** | What's in flight, with the next milestone. |
| **Entities** | Organisations you deal with — one dossier each. |
| **People** | Individuals, their role, and when you last spoke. |
| **Decisions** | What was decided, when, and what it superseded. |

They're pinned at the top of the sidebar.

## Reviewing

Everything in the **Meetings** table arrives marked **needs-review** because
something was inferred rather than known — a name matched by guess, a calendar
entry matched loosely, an email routed to a project by its sender's domain.
Open the *Triage* view and tick **Reviewed** once it looks right. That tick is
the signal that a row can be trusted downstream; nothing else writes it.

A row typed `note` is a capture rather than a meeting: a forwarded email or a
voice memo that carried context worth keeping. Its **Cal** column is empty
because no calendar was ever consulted — nothing corroborated it but the item
itself.

Anything marked `<!-- needs-review -->` in a table cell is the same idea: a
value that was inferred and wants your eye.

## Asking for things

Ask in plain language — you don't need to remember commands. Each one below
has a name in case you'd rather type it.

| When you want to… | Say | Command |
|---|---|---|
| pull in new recordings or transcripts | "sync what's in the inbox" | `/sync-recordings` |
| write down a decision that was just made | "log that decision" | `/log-decision` |
| start a project, or an area you own | "start a project for…" | `/new-project` |
| record context on a client or partner | "update the dossier on that client" | `/update-entity` |
| tell delaware something is broken | "report this to delaware" | `/report-feedback` |
| write tomorrow's note now | "run the evening sync" | `/evening-sync` |

> [!info] Nothing leaves this vault unless you say so
> Two commands can talk to delaware, and only these two: `/report-feedback`
> and `/health-check`. Between them they carry version numbers, which skill
> was involved, what went wrong, and counts — never a name, never a line of
> your notes — and never without your yes on the exact text they would send.
> `95-private` is read by nothing at all.

Your assistant has one more: **`/health-check`** — a numbers-only pulse on the
vault, no names and no content in it. Worth running weekly in the first month;
it will offer to send the numbers to delaware, and take no for an answer.

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

Nothing in here is hidden from you. If something reads wrong, say so.
