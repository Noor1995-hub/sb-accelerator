# On-demand processing: `/sync-recordings` brings a meeting into the brain the same day (#271)

## Problem

Today a meeting takes up to three days to reach the brain:

1. Day 1, evening: `/evening-sync` writes the meeting note and puts it in triage (`needs-review`).
2. Day 2: the owner ticks Keep in Meetings.base.
3. Day 2, evening: the evening run folds the tick, queues the project, and rewrites the project page and decisions.

The owner has a meeting in the morning and wants to work with it in the
afternoon. Calling `/sync-recordings` during the day does not help: it stops
at "in triage". The second half (project pages, decisions, people numbers)
exists only inside `/evening-sync` stages 2–4.

The issue as filed (#271, "meeting sync can run repeatedly without
triggering a daily note") was a symptom. `/sync-recordings` never writes a
daily note (verified on 0.13.11: no reference to `daily-note`,
`60-daily-notes` or `evening-sync` in the skill). The note the owner saw
came from elsewhere, most likely Obsidian's daily-notes autorun introduced
in #263, which creates today's note on open. Undoing that autorun is a
separate follow-up and not part of this spec.

## Decisions (vault owner + manager, 2026-10-12)

- **No scheduled daytime runs.** The owner calls the existing
  `/sync-recordings` when they need it. The evening run stays as it is and
  stays the only writer of the daily note.
- **No new skill.** `/sync-recordings` gains two steps when called by the
  owner: triage in the chat, then processing.
- **Triage in the chat**, short and dry: for each meeting in triage, accept,
  dismiss, or change project / attendees. One answer for all of them is fine.
- **Processing covers** accepted meetings **and** Thoughts & ideas notes
  ticked Include. **Not** mail and Teams: those stay evening-only.
- **One shared processing part**, used by both `/sync-recordings` and
  `/evening-sync`. No copy of the stage-4 logic.

## Design

### Flow of `/sync-recordings` (interactive)

| Step | What | Change |
|---|---|---|
| 1–4 | Scan, calendar enrichment, route, stamp confidence | unchanged |
| 5 | Confirm the plan | **dropped in interactive mode** (see "One question round") |
| 6 | Extract and write | unchanged |
| 7 | Summarize the sync | unchanged |
| **8** | **Triage in the chat** | new |
| **9** | **Process** (follow the shared part) | new |
| **10** | **Decisions in the chat** | new |
| **11** | **Summary of what changed in the brain** | new |

Under `--unattended` (scheduled runs, and `/evening-sync` stage 3) the skill
behaves exactly as today: no steps 8–11.

**One question round.** Today interactive mode asks once before extraction
(step 5: proceed / edit / skip, on provisional titles). With step 8 added,
the owner would be asked twice. Step 8 asks about the real notes with real
titles, so it is the better of the two. Interactive mode therefore extracts
like unattended mode (no plan shown, ambiguous routing becomes
`projects: []` and low confidence), and everything is settled in step 8.
A recording the owner never wants to see again is dismissed in step 8
(`archived: true`), which hides it, the same as Dismiss in Obsidian.

Approved by the owner 2026-10-12, accepting that a long extraction can no
longer be stopped before it starts.

### Step 8: Triage in the chat

The queue is every meeting note with `review_status: needs-review` and no
`archived: true`. That covers the new ones from step 6 and any left from earlier runs
(last night's evening run included).

1. `meeting triage list` (new CLI, read-only) returns, per note: path, title,
   date and time, `projects`, `attendees` (names), confidence, and
   `conflicts-with` when set.
2. Show one numbered list, one line per meeting:
   `1. Weekly with Acme · Tue 09:00 · project: Acme ERP rollout · Jan, Sofie`.
   Ask once: *accept, dismiss or change?* The owner answers in free text
   ("1 and 3 accept, 2 dismiss, 4 project is acme-finance").
3. Translate the answer into one payload, and **read the interpretation back
   in one line before writing** when anything was changed (not for plain
   accept/dismiss).
4. `meeting triage apply --items <payload>` (new CLI) writes, per note:
   - accept → `reviewed: true`
   - dismiss → `archived: true`
   - change → `projects` / `attendees` (slugs that must resolve, as in
     `meeting write`), then `reviewed: true` unless the owner said otherwise
   It refuses an unknown slug or path, naming it, and writes nothing for that
   item. A note with `conflicts-with` cannot be accepted (same rule as
   `reconcile-reviews`); it is reported with how to settle it.
5. `sync reconcile-reviews` folds the ticks (stamps `confirmed-at`) and
   `sync rederive-entities` repairs `entities` after project changes.

"Not now" (or no answer) ends the run after step 7. Everything stays in
triage, and the evening run processes whatever the owner ticks in Obsidian.

### The shared processing part

A new reference file, `plugin/skills/evening-sync/references/process.md`,
holds what today is stage 2's *Your notes ticked Include* paragraph, stage
3c and stage 4 (including the write-back for notes). Both callers follow it:

- `/evening-sync` follows it at the same place in the run, with nothing
  changed in behaviour. Its stage text becomes a pointer plus the
  evening-only inputs.
- `/sync-recordings` step 9 follows it with the on-demand inputs.

The two callers differ only in their inputs:

| Input | Evening | On demand |
|---|---|---|
| Ticks folded (`reconcile-reviews`) | yes | yes (after step 8) |
| Notes ticked Include (`notes harvest` / `assign` / `mark-absorbed`) | yes | yes |
| Daily-note jottings (stage 2 harvest) | yes | **no** (they are read in the evening) |
| To Do's harvest | yes | **no** (built on the daily note) |
| Mail and Teams logs | yes (stage 3b runs first) | **no** new logs are read. The queue still sees any log already on disk that is newer than the project's last state write, which is correct |
| `update-queue` → project pages + decisions (sonnet, batches of ≤ 3) | yes | yes |

Only projects with something new are queued, as today: `update-queue`
compares each meeting's activity (later of its datetime and `confirmed-at`)
and each log's `updated-at` against the project's `state-updated`.

**Why the evening run does not redo or lose anything:**

- A project processed at noon has a newer `state-updated`. In the evening
  it is queued only if something arrived after noon.
- Mail read by the evening run gets a log `updated-at` of that evening, which
  is after noon, so the project is queued again for its mail. Nothing read
  in the morning's mailbox is lost by the midday run. (Verified in
  `updatequeue.py`: logs compare on `updated-at`, the write time, not the
  message time.)
- Notes absorbed at noon are unticked (`absorbed` stamped) and are not read
  again in the evening.

### Step 10: Decisions in the chat

Decisions captured in step 9 are written `reviewed: false` (background
mode, unchanged). The owner is in the chat anyway, so the skill shows them
the same way as the meetings, one line each
(`1. Acme ERP rollout · Go-live moved to 3 Nov`), and asks once: *keep or
dismiss?*

- keep → `reviewed: true`
- dismiss → `archived: true` (the same as Dismiss in Decisions.base)

Both are written by a new CLI, `decision review --path <p> --keep|--dismiss`.
It refuses a path that is not a decision note. "Not now" leaves them in
Decisions › To review.

This is a second question, after the work. The decisions only exist once
step 9 has run, so they cannot be part of step 8.

Dismissing a decision that superseded an earlier one leaves the earlier one
`superseded`, exactly as Dismiss in Obsidian does today. The skill names the
earlier decision so the owner can restore it by hand. Reversing the edge
automatically is out of scope.

### Step 11: Summary

Short, counted from disk:

```
## Brain updated
**Meetings:** {N} accepted · {N} dismissed · {N} changed · {N} left in triage
**Your notes:** {N} absorbed ({titles}) · {N} kept for tonight ({why})
**Project pages rewritten:** {project names}
**Decisions:** {N} kept · {N} dismissed · {N} left in Decisions › To review
**Not done now:** mail and Teams (tonight's run) · daily note (tonight's run)
**Warnings:** {verbatim} | none
```


### Not running twice at once

Today nothing stops the owner's call and a scheduled evening run from
overlapping. With step 9 both would rewrite the same project pages.

New CLI `runlock acquire --routine <name>` / `runlock release`: a lock file
in `99-workflow-config/` with routine, start time and host. Acquire refuses
when a lock younger than 2 hours exists and returns who holds it. An older
lock is reported stale and is taken over.

- `/sync-recordings` interactive takes the lock **only for steps 8–9**.
  On refusal it ends after step 7 and says: *"Your evening run is busy; your
  meetings stay in triage and that run will pick up what you tick."*
- `/evening-sync` takes it at stage 1 and releases it at stage 7. An
  unattended run that finds a fresh lock waits up to 10 minutes (one check
  per minute, CLI-only), then runs anyway with a warning. A missed evening
  run costs more than a rare overlap.

> Inferred, not verified: in Cowork the vault sits on OneDrive, and two
> machines could hold separate copies. The lock only covers runs that see
> the same folder.

### Rules added to `/sync-recordings`

- **This skill never creates, writes or edits anything under
  `60-daily-notes/`.** The daily note belongs to `/evening-sync` stage 6.
  Safe to run any number of times a day.
- Steps 8–11 run only in interactive mode. `--unattended` never asks and
  never processes.
- It never reads mail or Teams.

## Testing

- **CLI (pytest):**
  - `meeting triage list`: filters, and fields including `conflicts-with`.
  - `meeting triage apply`: accept / dismiss / change, unknown slug refused,
    conflicted note refused, and an idempotent re-apply.
  - `decision review`: keep, dismiss, refused non-decision path,
    superseding decision named on dismiss.
  - `runlock`: acquire, refuse, stale takeover, release.
- **Skill contracts (`test_skill_contracts.py`):**
  - `daily-note write` appears only in `evening-sync`.
  - `sync-recordings` never names `60-daily-notes`.
  - `sync-recordings` and `evening-sync` both point at `references/process.md`.
  - The stage-4 batching rule lives in exactly one place.
- **Queue behaviour (`test_vaultlib_updatequeue.py`):** a project written at
  noon is not re-queued in the evening without new input, and is re-queued
  by a log whose `updated-at` is after noon.
- **End-to-end on a preview vault:** morning meeting, `/sync-recordings` at
  noon with accept, project page shows it, evening run does not rewrite that
  project unless mail arrived.

## Out of scope

- Undoing the #263 daily-notes autorun (separate follow-up; owner asked).
- Entity and team pages updated automatically (#184), and person context:
  these can later be added to the shared part, so both callers get them.
- Renaming `/sync-recordings` now that it does more than recordings.
- Mail and Teams in the on-demand run.

## Release

Skill text, CLI and tests only: no vault structure change, so no
migration. `Start here.md` gets one paragraph explaining "call the meeting
sync to get today's meetings in now" (template refresh via
`/upgrade-vault`). Version bump and CHANGELOG entry as usual.
