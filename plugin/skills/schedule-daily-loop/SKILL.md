---
name: schedule-daily-loop
description: Set up (or move) the standing evening run, so tomorrow's note is written without anyone remembering to ask. Triggers when the user invokes /schedule-daily-loop or asks to schedule, reschedule, or stop the evening sync.
user_invocable: true
origin: net-new
---

# Schedule the Daily Loop

`/evening-sync` writes tomorrow's note. This skill is what makes it happen on
its own, every working evening, instead of whenever someone remembers.

Run at the end of Session 1 (`/setup-my-brain` phase 4b invokes it), and again
whenever the answer changes: a new laptop, a different working rhythm, an
assistant taking the run over, or a routine that turns out to fire at a bad
hour. It is safe to run as often as you like — it updates the task it already
made rather than stacking a second one.

## Requirements

The scheduled task is created through Claude's own scheduler, so this skill
runs where that scheduler exists: **Cowork** or **Claude Code**. It cannot run
in Chat.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure surface `error` and `hint`.

### The scheduler has to actually be there

Before promising anything, look for it:

```
ToolSearch: select:mcp__scheduled-tasks__list_scheduled_tasks,mcp__scheduled-tasks__create_scheduled_task,mcp__scheduled-tasks__update_scheduled_task
```

Found: continue. **Not found: go straight to "When there is no scheduler"**
at the bottom of this file and hand the job over in writing. Do not describe
a routine you did not create — that overclaim is the exact defect this skill
was written to remove.

## Usage

```
/schedule-daily-loop
```

No arguments and **no unattended mode**: this skill asks a person what time
they want their evenings to run, which is not a question a scheduled run can
answer.

## Step 1 — the config has to support a scheduled run

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

If `timezone` or `executive` is in `missing`, stop here and say which one.
`/evening-sync` refuses to run without them, so scheduling it would create a
task whose every firing writes an alert and nothing else — a routine that
looks alive in the task list and is dead in the vault. Fill them (Session 1
does, in phase 1) and come back.

Keep two values from the result: `timezone`, and `executive` — the person slug
that names the task.

## Step 2 — what is already scheduled

```
mcp__scheduled-tasks__list_scheduled_tasks
```

The task ids this skill owns are:

| Task | id |
|---|---|
| Evening run | `second-brain-evening-<executive-slug>` |
| Morning recordings sync (optional) | `second-brain-morning-sync-<executive-slug>` |

The slug is in the id because task ids are global to the machine while a vault
is not: an assistant who supports two people, or a consultant's own laptop,
would otherwise have the second vault silently overwrite the first one's
routine.

If a task with that id already exists, **read its `path`** and show the user
what is set today — the time, and when it next runs — before asking anything.
Then this run is a change, not a setup: use `update_scheduled_task`, never
`create_scheduled_task`, or the machine ends up with two evenings.

Trust `list_scheduled_tasks`, not `~/.claude/scheduled-tasks/`. The two can
disagree — a deleted task leaves its `SKILL.md` behind on purpose (see
"Turning it off"), so a directory on disk is not evidence that anything is
scheduled. The list is the scheduler; the folder is a filing cabinet.

## Step 3 — ask when

Use **AskUserQuestion** — the times are known options, and this is a question
about someone's day, not a configuration value to type.

Ask for the evening run first. Frame it in their terms: *"When should the
vault prepare tomorrow? It reads your calendar and writes the note, so it
wants to run after your last meeting but before you close the laptop."*

Offer early-evening choices and let them pick their own. Two things to
say while they choose, both consequences rather than trivia:

- Anything recorded **after** the run lands in the next run, not this one.
- The run needs the app open (see step 5), so a time inside their working
  evening beats one at midnight.

**Do not schedule on the hour or the half hour** unless they name that exact
time and mean it. Every deployment that asks for "seven" gets `0 19`, and the
whole fleet then calls the same connectors in the same second; `47 18` serves
the same person just as well. Convert their answer to a five-field cron
expression in **local time** — the scheduler evaluates cron in the machine's
local timezone, so `timezone` from step 1 is a cross-check on the machine's
setting, not something to convert against.

Weekdays (`1-5`) is the sensible default for a working rhythm. Ask, do not
assume, if they mentioned a weekend rhythm during the interview.

**Always create the task with a cron expression.** A task created with no
schedule at all is manual-only, and a manual-only task is a dead end: it is
listed, but `update_scheduled_task` and `delete_scheduled_task` both report it
as not found, so it can only be removed by deleting its directory by hand.
Nothing this skill creates should ever need that.

### The optional second task

Offer the morning recordings sync as a *choice*, not a recommendation:
`/sync-recordings --unattended`, early, so a conversation recorded after last
night's run is a meeting note before the day starts. Someone who records
rarely does not need it, and an unused routine is one more thing on the
machine to explain later. If they decline, say so in the closing line rather
than leaving it ambiguous.

## Step 4 — compose a self-contained prompt

**A scheduled run starts with no memory of this session.** Everything it needs
is in the prompt or it is not there at all. Write the prompt so that a fresh
Claude, in a fresh session, on this machine, can carry it out with nothing
else:

- **The vault's absolute path**, as `VAULT`. Not `.`, not a relative path, not
  "the vault" — the scheduled run has no working directory in common with this
  session.
- **The skill to invoke and its mode** — `/evening-sync --unattended` for the
  evening task, `/sync-recordings --unattended` for the morning one. Nothing
  more: the pipeline is the skill's business, and a prompt that re-specifies
  its stages is a second copy of the pipeline that will drift from the first.
- **The interpreter rule** — try `python3`, then `python`, then `py -3`, first
  one that works. The prompt says this because the machine that runs at 18:47
  may not be the machine anyone tested on.
- **A final-line contract** — the run ends with exactly one line, and it is
  either a plain completion (naming the note it wrote) or a line that starts
  with a word a human can grep for. The scheduler notifies on completion; that
  notification is worth reading only if the last line says what actually
  happened.
- **What not to do** — never ask a question (the mode already says so, but the
  prompt is read by an agent that will otherwise try to be helpful), and never
  write a note by hand if a stage fails. A failed stage is reported, not
  worked around.

<!-- #82/B4: when model pinning lands, the composed prompt pins the sync
     subagents to a cheaper model here. Until then the scheduled run inherits
     whatever the machine's session model is, which is the current cost
     behaviour and is worth saying out loud to the consultant. -->

Then create or update it, with a `description` that carries the schedule in
plain words ("evening run — writes tomorrow's note, weekdays 18:47") so the
task list is readable without opening anything.

## Step 5 — say the condition out loud

This is the honest half of the promise, and it is not optional.

**The task fires while the Claude app is running on this machine.** If the app
is closed when the task is due, it runs at next launch instead — so a night
where the laptop is shut produces tomorrow's note the next time Claude opens,
not at the hour on the clock. `/evening-sync` handles that gracefully: the
catch-up window widens on its own and the note says so. What it cannot do is
run on a machine that is off.

Say the two consequences plainly:

- **The vault is a local folder**, so a cloud-scheduled run has nothing to
  read or write. There is no version of this that runs while the laptop is
  closed. That is a real product limit today, not a setup step anyone
  forgot.
- If the routine is meant to run on a **different machine** — an assistant's,
  typically — it has to be created there, from a session that can see this
  vault. Creating it here schedules it here.

## Step 6 — run it once by hand, to pre-approve its tools

Do not skip this, and do not leave it for the client to discover.

**Tool permissions are granted per task, during a run.** A scheduled run that
reaches for the Plaud or Microsoft 365 connector for the first time stops at a
permission prompt — in an unattended run, with nobody watching, that is a
routine that silently does nothing on the night it matters most. Starting the
task manually once, with the exec present, grants those approvals and stores
them on the task, and every automatic run afterwards has them.

So: start the task once from the scheduler, watch it through, and confirm it
wrote what it should. It is also the only chance anyone gets to see the
routine work before trusting it — worth the four minutes on its own.

## Step 7 — verify, then report a date

```
mcp__scheduled-tasks__list_scheduled_tasks
```

Confirm the task is present, `enabled`, and carries a `nextRunAt`. Read the
task's `path` and check the prompt that landed actually names the absolute
vault path — a task that quietly points at the wrong folder runs happily and
writes nothing where anyone will look.

Then report it as a **date and time**, never as a cron expression: *"Your
first automatic run is Tuesday evening at 18:47."* Nobody should have to parse
`47 18 * * 1-5` to learn when their vault next does something.

Take that date from **`nextRunAt`**, and from nowhere else. The human-readable
`schedule` string and the line the create call echoes back are both derived
summaries and both go wrong on anything but a plain daily or weekday cron —
a five-hour list renders as a single hour, and a jittered minute is shown as
the scheduled one. `nextRunAt` is the timestamp the scheduler will actually
act on.

## Turning it off, or moving it

Same skill. Show what exists, ask what it should become, then
`update_scheduled_task` for a new time or `delete_scheduled_task` to stop it.
Deleting the routine is a legitimate answer — say what the vault does without
it (`/evening-sync` on demand still writes the same note) rather than talking
someone out of it.

**A delete leaves the task's `SKILL.md` on disk**, deliberately, so the prompt
can be recovered. That is fine and needs no action — but say it, because a
client who goes looking will otherwise find a folder for the routine you told
them you removed. Remove the directory only if they ask.

To pause rather than stop — a long holiday, a machine going away for a
fortnight — `update_scheduled_task` with `enabled: false` keeps everything and
fires nothing.

## When there is no scheduler

The scheduler tools were not found, or their call failed. **Do not improvise a
cron job, a launchd plist, or a shell script**; nothing of that kind ships
with this plugin, and one written by hand at a client becomes an unowned
artifact nobody can find at the next tune-up.

Hand the job over in writing instead, and be specific enough that the hand-off
is actionable without this session:

1. **What** must be scheduled — `/evening-sync --unattended`, against this
   vault path.
2. **Where** — the machine that holds the vault, from Cowork or Claude Code.
3. **Who** — name them. "The consultant" and "IT" are not people.
4. **By when** — before the routine is described to anyone as existing.

Then say what happens meanwhile: nothing is broken, and `/evening-sync` run by
hand writes exactly the same note. An honest "not yet, and here is who does
it" is a fine outcome for this skill. A vague one is not.

## Hard rules

1. **Never describe a routine that was not created.** Either the task exists
   and `list_scheduled_tasks` shows it, or the hand-off above is delivered.
   There is no third ending.
2. **Update, never duplicate.** The ids in step 2 are checked before anything
   is created.
3. **The prompt is self-contained.** Absolute vault path, mode flag,
   interpreter rule, final-line contract — a scheduled run has nothing else.
4. **The laptop-on condition is stated every time**, including on a re-run.
   It is the part people forget, and forgetting it is what turns a working
   routine into a broken promise.
5. **No cron, launchd or systemd artifact is ever written.** Scheduling
   happens through Claude's scheduler or it is handed off.
6. **Every task this skill creates has a cron expression**, and is started
   once by hand before the session ends.
