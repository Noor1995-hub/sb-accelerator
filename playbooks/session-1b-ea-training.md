# Session 1b — EA operator training

delaware-side material; never ships. A **2-hour** hands-on session with the
assistant, run once Session 1 has seeded the vault. Session 1 is the
executive's interview; this is the EA's cockpit briefing — the day-to-day
operator surface, not the onboarding conversation.

Run it on the assistant's own machine, against the vault they will actually
operate. If the standing evening run lives on their machine (see below),
confirm that before this session so the hands-on exercise exercises the real
routine, not a stand-in.

## The daily loop, from the EA's chair

Most days need nothing from her at all. The scheduled evening run
(`/evening-sync --unattended`, set up in Session 1 Phase 4b) fires on its
own each working evening the machine is awake, syncing new recordings,
folding review ticks, and writing tomorrow's note. Her day looks like:

- **Morning** — nothing to do unless a recording needs manual attention;
  the scheduled sync already ran overnight or that morning.
- **During the day** — drop anything that arrived outside a connector
  (a forwarded email, a voice memo) into `10-inbox/`. It waits there for the
  next sync, scheduled or manual.
- **Weekly** — run `/health-check` and read the numbers (below).
- **Whenever something breaks or confuses** — `/report-feedback`.

Everything else in this session is what she does when the loop needs a
hand, not what she does instead of it.

## The skill repertoire

| Skill | When | What it writes | What to check afterwards |
|---|---|---|---|
| `/sync-recordings` | Inbox has new files, or the scheduled run didn't fire and today can't wait | Meeting notes (or captures) in `20-meetings/` | The **Triage** view in `Meetings.base` — anything landed `needs-review` |
| `/log-decision <project-slug>` | A reviewed meeting committed the engagement to something | A decision note under that project's `decisions/` | `reviewed: true`; if it names a `supersedes`, both notes flipped |
| `/update-entity <entity-slug>` | New context about an organisation surfaces — a person, a fact, a dynamic | The entity's dossier, in the matching section | The `changes` list; any new stakeholder carries `needs-review` on purpose — leave it for a human |
| `/new-project` | A new engagement, initiative, or standing responsibility starts | `30-projects/<slug>/index.md` and an empty `decisions/` | Whether the dossier's Engagements table picked up the link |
| `/health-check` | Weekly during hypercare, and before every tune-up | `99-workflow-config/health-reports/{date}.md` | The six numbers, read against last week's |
| `/report-feedback` | Something broke, confused, or could be better | A GitHub issue on `sb-client-<slug>`, or a draft in `10-inbox/` if the channel isn't wired up | The `issue_url` it hands back, or that the draft actually landed |
| `/evening-sync` | The scheduled run didn't fire and tomorrow's note is missing | Tomorrow's (or today's, on a catch-up) daily note | The note opened and reads right; a run-log line in `routine-runs.log` |

None of these need a shell command memorised — they are slash commands, run
from Cowork or Claude Code with the vault open. None of them run in Chat;
if she opens the vault there, say so plainly rather than letting her guess
why nothing happens.

## Inbox discipline

The loop, end to end: a file lands in `10-inbox/` — dropped by hand, or
already there from Session 1's context. `/sync-recordings` turns it into a
meeting note or a capture in `20-meetings/`, and it appears in
`Meetings.base`'s **Triage** view, filtered to `needs-review` and not yet
reviewed or archived.

From there, she works the row:

- **`✓ Reviewed`** — tick it once she is satisfied the note is right. The
  next sync run folds the tick into the note's own review status; it is not
  instant.
- **`🗑 Archive`** — tick it to drop something that reached `20-meetings/`
  but is not worth keeping visible in Triage.
- **`⚠ Duplicate of`** — if this column is filled, the note conflicts with
  another one already in the vault. A tick on a note carrying this field
  does not auto-confirm; it needs a human to merge or delete one of the two
  first.

## Hands-on: `/log-decision` on a reviewed meeting

Once a meeting note is ticked `✓ Reviewed`, it is a candidate for
`/log-decision <project-slug>`. Point it at the note (paste the text, name
the file, or describe what was decided) and let it extract. Not every
meeting produces one — a reviewed meeting with nothing that committed the
engagement is a valid "wrote nothing" outcome, and that is correct, not a
miss.

## `/update-entity` and `/new-project`, in one line each

`/update-entity` is for routing anything new about an organisation — a
person, a company fact, a political dynamic — into its dossier, section by
section. `/new-project` is for standing up a new engagement or standing
responsibility with its own index and decision log. Both refuse to guess:
they ask which entity, which type, which owner rather than inventing an
answer.

## Weekly `/health-check`

Run it weekly through hypercare (weeks 2–4) and again before every tune-up.
It reports counts, rates and ages — never names — and offers, only on her
explicit yes, to share the numbers with delaware. `hypercare-guide.md`
covers how to read what comes back.

## `/report-feedback` and the report-it nudge

When something in the daily loop breaks or confuses her, `/report-feedback`
drafts a scrubbed report — no note text, no names, no meeting titles — shows
her the exact text and a disclosure, and sends it only on her explicit yes.
If the feedback channel isn't configured on this vault yet, the draft lands
in `10-inbox/feedback-draft-{date}.md` instead of going nowhere. Encourage
her to report the moment something feels off rather than saving up a list —
a fresh "I expected X, got Y" is worth more than a recollection a week later.

## What she never sees

`95-private/` is the executive's own folder, and it stays that way by
construction, not by convention: it is excluded from Obsidian Sync on every
machine, so nothing in it ever reaches her machine at all — there is no
permission to accidentally grant. If she ever notices a gap where something
should be (a person the executive mentioned who has no note), the honest
answer may be that it lives there, and that is not a bug to chase.

## Who owns the scheduled evening run

Confirm, out loud, which machine holds the scheduled task — hers or the
executive's — and who is responsible for it staying awake at the scheduled
hour. `provisioning-runbook.md` §8 covers the mechanics: the task is
machine-local, so it only runs where it was created, and its first manual
run (already done in Session 1 Phase 4b, on whichever machine that was)
granted it the connector and Bash permissions it needs. If it should move to
her machine, that needs a fresh `/schedule-daily-loop` run from a session
that can see the vault on her side — say this now rather than at the first
missed evening.

## Troubleshooting ladder: nothing got written

Three rungs, in order, before calling it a bug:

1. **Was the machine holding the scheduled task awake, with Claude open, at
   the scheduled hour?** If the laptop was closed, the run fires at next
   launch instead — `/evening-sync` recovers on its own (the recap window
   widens, and the note says so), it just wasn't last night.
2. **Is the routine actually running where you think it is?** Cowork runs
   its shell in its own Linux VM; Claude Code runs against the host
   directly. A task created from one surface does not exist on the other —
   confirm which surface Session 1 Phase 4b actually used.
3. **`config read --vault <vault>`** — if `owner` or `timezone` came back
   missing, `/evening-sync` refuses to run deterministically and the
   scheduled task fires an alert instead of writing anything. Fill the
   missing field and re-run.

Then check `99-workflow-config/logs/routine-runs.log` — every run, success
or failure, ends in exactly one line there. No line for last night at all
usually means rung 1; a line ending in an alert rather than a plain
completion means rung 2 or 3.

## Hands-on exercise

Do this together, on her machine, against the real vault:

1. Drop one transcript or note into `10-inbox/`.
2. Run `/sync-recordings` (interactive — watch the plan-confirmation step
   she will never see once it runs on schedule).
3. Open `Meetings.base`'s Triage view and find the new row.
4. Tick `✓ Reviewed` on it, and note that the tick folds in on the *next*
   run, not instantly.
5. Run `/log-decision` against the project it landed on, and confirm or
   drop whatever it proposes.
6. Run `/health-check` and read the numbers back to her — this is also the
   first baseline reading for `hypercare-guide.md`.
