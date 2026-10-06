---
type: note
---

The detail behind [[Start here]]. Nothing here is needed day to day.

## Reviewing

A meeting arrives **To review** because something about it was inferred rather than known — a name matched by guess, a calendar entry matched loosely, an email routed to a project by its sender's domain. Per row, tick **Keep** once it looks right, or **Dismiss** if it is noise (a bad recording, something that was not really a meeting). A dismissed row leaves the tables; the file stays. Keep is the signal that a row can be trusted; nothing else sets it.

To fix a wrong project or person on a meeting, type the right one in its **Projects** or **Attendees** cell in *To review*. Those cells take the short code — `acme-industries-operating-model`, `jordan-reyes` — that you see in the note's properties; every other table shows names.

A row of type **Note** is a capture rather than a meeting: a forwarded email or a voice memo worth keeping. Its **Calendar match** box is never ticked, because no calendar was consulted.

A decision is **To review** when it was captured during the evening run rather than logged by you. Tick **Keep** once you have read it, or **Dismiss** if it was not really a decision. A decision is never deleted; one that a later decision replaces shows as **Replaced**.

Anything marked `<!-- needs-review -->` in a table on a page is the same idea: a value that was inferred and wants your eye.

## Projects and responsibilities

A **project** is work with an end. A **responsibility** is something that stays yours, with no end date. Both live in the Projects table, grouped by which they are.

## Asking for things

You never need a command, but each request has one, in case you'd rather type it.

| When you want to… | Command |
|---|---|
| pull in new recordings or transcripts | `/sync-recordings` |
| write down a decision that was just made | `/log-decision` |
| start a project or a responsibility | `/new-project` |
| record what you know about a company or team | `/update-entity` |
| write tomorrow's note now | `/evening-sync` |
| tell delaware something is broken | `/report-feedback` |
| a numbers-only health check of the vault | `/health-check` |

## Privacy

Only two commands talk to delaware: `/report-feedback` and `/health-check`. Between them they carry version numbers, which command was involved, what went wrong, and counts — never a name, never a line of your notes — and never without your yes on the exact text. `/health-check` is worth running weekly in the first month; it offers to send its numbers and takes no for an answer. `95-private` is read by nothing at all.

## Where things live

- `10-inbox` — **Input**: drop files here; the evening run picks them up.
- `20-meetings` · `30-projects` · `40-entities` · `50-people` — the notes behind the tables.
- `60-daily-notes` — one note per day. Jot anything under **Notes** on today's note; it is read that evening.
- `70-resources` · `80-thoughts-ideas` — reference material and your own notes. Tick **Include** on a note and the evening run reads it into your projects; the note stays where it is.
- `90-archive` — finished, kept.
- `95-private` — never read by any command. Yours alone.
- `99-workflow-config` and `claude` — how the assistant works: who you are, how you like things written, and its own machinery. Not in the menu but not hidden from you either; worth editing when something reads wrong.

If something reads wrong, say so.
