---
name: evening-sync
description: Run the evening pipeline — sync recordings, fold review ticks, refresh project metrics, update project state, capture decisions, and write tomorrow's daily note. Triggers when the user invokes /evening-sync or asks to run the evening sync or prepare tomorrow's note.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Evening Sync

The engine of the daily loop. One run harvests today's jottings, syncs new
recordings, refreshes project metrics, updates the state of projects with new
confirmed meetings, captures decisions for review, and writes **tomorrow's**
daily note — a recap of today plus a prepared section per upcoming meeting.
(On a morning catch-up after a missed run, the note is **today's** — stage 1
decides, never you.)
Deterministic stages are CLI subcommands; judgment (recap prose, themes,
project-state synthesis, decision candidates) is yours.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say so
plainly rather than assembling a note by hand.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure surface `error` and `hint`.

## Usage

```
/evening-sync                    # interactive: one confirmation at the sync stage
/evening-sync --unattended       # scheduled shape — never prompts, ever
```

Stages are **failure-isolated**: a failed stage logs its error into the final
summary and the chain continues. A crashed calendar still gets a daily note;
a failed sync still gets metrics and project updates.

## Stage 1 — Dates (authoritative, never re-derived)

Read the deployment config, then plan the dates:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <config.timezone>
```

If `timezone` or `owner` is in `missing`, the pipeline cannot run
deterministically: stop, and say which key to fill in
`99-workflow-config/config.json` (interactive), or write the alert as the
run's only output (unattended).

Consume the result **verbatim** — `today`, `next_business_day`, the day
names, `recap_from`/`recap_to`, `last_daily_note`, `note_to_write`. Never
derive day-of-week or date arithmetic yourself; that is the bug class this
subcommand exists to kill. The recap window is *everything since the last
daily note*: after a missed run or a gap, it widens automatically — no
weekend special case.

**The catch-up block.** `business_days_missed` is how many evening runs did
not happen; `is_catchup` is that count above zero. Skipped days are **never
back-filled** — one note covers the whole window, because fabricating past
daily notes would invent days that have no jottings. The CLI writes that
sentence into the note itself (stage 6); you do not have to compose it.

When `over_threshold` is true, the window is too wide to recap in full.
Detail the window from `recap_detail_from` onward and let
`business_days_not_detailed` stand as a count:

- **interactive** — ask once, here, before any work: detail the last
  `catchup_threshold` business days (the default), or the whole window? Pass
  `detailed_from` in stage 6 only if the answer was to cap.
- **unattended** — always cap, never ask, and carry the catch-up window into
  the Warnings block so a human reviews it.

**The missed-evening run (`--for-today`).** Sometimes the evening run cannot
happen at all — the laptop was closed. The vault owner opens it the next
morning, sees no note for today, and triggers the sync by hand. Running the
standard plan then writes *tomorrow's* note and today never gets one (a live
catch-up at 10:28 did exactly that: the skipped day's meetings were never
prepped). `dates plan` reports the state instead of leaving it to you:
`for_today_available` — today is a business day, today's note is missing,
and at least one daily note exists (a brand-new vault has nothing to catch
up, so Session-1's first run never sees this offer) — and
`for_today_suggested`, which adds "and it is before noon local". When
`for_today_available` is true:

- **interactive** — ask once, here, before any work: catch up **today's**
  missing note, or prepare **tomorrow's** as usual? Recommend the answer
  `for_today_suggested` gives. If the answer is today, re-run `dates plan`
  with `--for-today` and consume that result verbatim instead.
- **unattended** — never ask. When `for_today_suggested` is true, re-run
  with `--for-today` and continue on that plan; otherwise keep the standard
  plan. Name the choice in the summary either way.

The `--for-today` frame is last night's run executed late: the same keys,
shifted — `next_business_day` and `note_to_write` point at **today**, the
recap ends **yesterday**. Nothing downstream changes: stage 5 already pulls
`next_business_day`'s events, so it preps today's remaining calendar, and
stage 6 writes today's note. The clock heuristic and the frame arithmetic
live in the CLI; whether to ask is the only judgment here.

Every number above is read, never computed. If you find yourself counting
days, you are re-introducing the bug `dates plan` exists to prevent.

The vault owner's **person slug** is `owner` from the config — a slug,
used as-is. Stage 3 needs it.

## Stage 2 — Harvest (read-only)

```bash
python3 "$VAULTLIB" daily-note read --vault "$VAULT" --date <recap_from>
```

`exists: false` is a normal first-run state — note it and move on. Otherwise
collect, per meeting, `notes` (the owner's bullets under `#### Notes`, or
bullets directly under the heading on a note written before v2) and
`actions` (`{text, done}` from the `- [ ]` / `- [x]` list under
`#### Actions`), plus the `end_of_day` bullets. All of it is context for the
recap (stage 6) and decision candidates (stage 4); an action is a jotting
the owner marked as a task, nothing routes it anywhere yet. The note itself
is the archive of the day — **never modify it**.

## Stage 3 — Sync, refresh

**Sync:** run the `/sync-recordings` workflow (follow
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/SKILL.md`) — unattended when this run is
unattended, interactive otherwise. Its step 1 runs `sync reconcile-reviews`,
which IS this pipeline's reconcile stage. Record what it reports: synced
stems, folded ticks, conflicts, per-adapter lines.

**Repair:** re-derive `entities` from `projects` on every meeting note —
`meeting write` derives it once at creation, but nothing keeps the two in
sync afterward, so a project reassigned by hand during triage leaves the old
entity behind until this runs:

```bash
python3 "$VAULTLIB" sync rederive-entities --vault "$VAULT"
```

Carry `changed` (a count worth mentioning if non-zero) and `unresolved` (a
project slug missing its `entity:` field, or missing outright — the note is
left untouched, not silently skipped) into the final summary.

**Refresh:**

```bash
python3 "$VAULTLIB" sync reconcile-reviews --vault "$VAULT"
python3 "$VAULTLIB" sync update-queue --vault "$VAULT" --today <today> --owner <owner-slug>
```

The second `reconcile-reviews` is deliberate, and it is the only place this
pipeline repeats a step: a sync with recordings to process can run for the
better part of an hour, and a tick placed in Meetings.base during that window
would otherwise fold tomorrow evening instead of tonight. It is one cheap
read of `20-meetings/`; add anything it `flipped` to the folded-ticks count
you recorded above, and surface its `conflict_ticks` the same way step 1's
were.

This writes `meetings-7d` / `meetings-30d` / `key-people` on active projects
and `meetings-7d` / `meetings-30d` on people (confirmed meetings only — the
review queue is the quality gate), and returns `projectsNeedingUpdate`: each
entry carries `indexPath`, `decisionsDir`, `lastUpdated`, `stateUpdated`,
`newFiles`, and the `existingDecisions` projection. Carry `warnings` — especially `SELF-CHECK`
lines — into the final summary verbatim.

## Stage 4 — Project-state updates

If the queue is empty, record "no projects to update" and skip to stage 6.
Otherwise, dispatch one subagent per queued project (each with `model:
sonnet`), each carrying the queue entry, the harvest jottings that mention
the project, today's date, and these instructions.

**Dispatch in blocking batches of at most 3 — this is the cap, not a
suggestion layered on top of it.** Send ONE message containing at most 3
blocking Agent calls (`run_in_background: false`); only once every call in
that message has returned do you send the next message with the next batch
of up to 3, repeating until every queued project has been dispatched. There
is no background mode for this fan-out: a blocking call already returns
exactly when its subagent finishes, so a batch's completion is the signal to
send the next one — never a separate check. `/sync-recordings`'s own fan-out
in step 6 dispatches its worker batches the same shape.

The instructions each subagent gets:

1. Read the `newFiles` meetings end-to-end — Key Takeaways, Debrief, Action
   Items.
2. Compose the project's **state** as JSON and write it to
   `$SCRATCH/project-state-<slug>.json`. The CLI renders the whole index body
   from it and refuses anything over its caps, naming the field:

```bash
cat > "$SCRATCH/project-state-<slug>.json" <<'JSON'
{
  "as_of": "<today>",
  "stage": "one or two sentences, ≤ 60 words",
  "hot_potatoes": [{"signal": "red", "text": "≤ 30 words — needs the owner's hand this week"},
                   {"signal": "amber", "text": "≤ 30 words — a risk building, nothing to do yet"}],
  "insights": ["≤ 30 words, at most two"],
  "defining_decision": "<decision stem under this project, or null>",
  "coming_up": [{"when": "Wed 16 Sept", "what": "≤ 40 words", "date": "2026-09-16"}],
  "owe": [{"owner": "Full Name", "items": ["one task per item — never chain with ';'"]}],
  "awaiting": ["…"], "questions": ["…"], "pending": ["…"], "watch": ["…"],
  "context": {"contacts": "…", "source": "…"},
  "next_milestone": {"text": "one line", "date": "<ISO>"}
}
JSON
python3 "$VAULTLIB" project state write --vault "$VAULT" --slug <slug> \
  --state "$SCRATCH/project-state-<slug>.json" --today <today>
```

   Start from the index as it stands (read it: the current card, Coming up,
   and every Background list are your prior state) and fold the new meetings
   in — carry items that are still open, drop the ones the meetings closed,
   never invent. `hot_potatoes` are the ≤ 3 things the owner must act on or
   watch this week; `insights` are patterns, not events. `coming_up` holds
   dated events only, ≤ 10 rows, the `date` sorts them. Omit
   `next_milestone` when no concrete next event exists. Identity names
   (entities, projects, people) go in as `[[slug]]` wikilinks — the CLI
   rewrites them to links that open. A refusal names the field and the cap;
   fix that field and retry once. `state write` also stamps `last-updated`
   and `state-updated` — that timestamp, not the day in `last-updated`, is
   what the next run's update queue compares against each meeting's
   datetime or, when later, its `confirmed-at` stamp; so a meeting ticked
   after tonight's write queues tomorrow, however old the meeting itself
   is. Do **not** call `project touch` separately.
3. Never edit `index.md` with your editor — the body is machine-rendered and
   a hand edit is overwritten on the next run; the owner's own `## Notes`
   section at the bottom, if present, is the one thing the CLI preserves.
4. Decision capture: extract candidates from the new meetings AND the
   harvest jottings, then follow
   `${CLAUDE_PLUGIN_ROOT}/skills/log-decision/SKILL.md` in **background mode**
   (`/log-decision <slug> --background`) with those candidates as the
   source. Its rules apply unchanged: the material-decision test (commits
   the engagement AND changes a stakeholder's behaviour), dedup against
   `existingDecisions`, supersession only on explicit conflict language,
   never delete, status flips only. Writing nothing is a valid outcome.
5. Return a fenced JSON block: `{"slug", "stateWritten": bool,
   "decisionsWritten": [stems], "decisionsSkipped": N, "notes"}`. A subagent
   that fails or returns no block becomes a warning, not a retry.

Pin the model rather than letting it inherit. This pipeline is built to run
unattended every evening, and a subagent spawned with no `model` runs at
whatever the session costs — a scheduled run started from an expensive
session quietly bills every project at that rate. The work is bounded: read
the named meetings, compose the state JSON, apply the material-decision
test. `/sync-recordings`'s own fan-out in stage 3 pins the same way.

**Why this is a hard batching rule and not a warning.** A live cost analysis
of this pipeline found a run whose orchestrator dispatched a 4th subagent
within seconds of narrating "dispatching the first 3", then spawned that
batch in the background and spent roughly 80 extra calls — polling tools and
idle `Bash(true)` checks — babysitting it over twelve minutes; each idle
check re-reads the full session context, and that alone was most of the
run's bill. A prose warning against exactly this ("dispatch as blocking
calls, never poll") was already in this skill at the time, and did not
bind. The batching instruction above replaces that warning with a shape
that leaves no room for the same reading: a batch is at most 3, sent as one
message of blocking calls, and the only thing that ever triggers the next
batch is that message returning — there is no step where "send one more"
or "check on it" is even an available move.

**A subagent that never returns is a warning, never a silently dropped
item — but there is nothing to check on while a batch is in flight.**
Because stage-4 dispatch is strictly blocking, you cannot "notice" a
straggler mid-batch — the message you sent returns when every call in it is
done, full stop. This differs from `/sync-recordings` step 6, which states a
duration-scaled patience rule (a worker is a straggler only after
max(10 minutes, half the recording's duration)) because that fan-out has a
concrete per-item duration to scale against and a documented incident of a
42-minute-transcript worker being written off too early. Stage-4 projects
have no equivalent duration signal, so no such formula applies here; if the
harness itself reports a dispatch as failed or timed out, name the project
in the final summary as a ⚠ warning rather than silently dropping it — that
is the only patience judgment stage 4 makes.

Projects with only `needs-review` meetings never reach the queue — do not
"help" one by confirming meetings yourself.

## Stage 5 — Tomorrow's calendar and prep

The calendar pull uses the M365 connector, so it is gated like an adapter:
it runs only when `adapters.m365.enabled` is true, the calendar tool exists
(ToolSearch `outlook_calendar_search`), and the account binding verifies —
call `get_me`, write the raw JSON to scratch, then:

```bash
python3 "$VAULTLIB" config verify-account --vault "$VAULT" \
  --adapter m365 --identity "$SCRATCH/m365.whoami.json"
```

Only `match: true` pulls events. A refusal (`account-mismatch`,
`no-account-hint`) or a disabled adapter takes the calendar-unavailable
path below, and the summary names the cause — a signed-in account from the
wrong engagement must never prep this vault's meetings. Run the sweep
immediately on a refusal, and in any case before the run ends:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

When the gate passes, pull `next_business_day`'s events; compute the query
window deterministically:

```bash
python3 "$VAULTLIB" dates window --start <next_business_day> --timezone <tz> --hours 0
```

Pass the window's `utc_from`/`utc_to` values as the tool's
`afterDateTime`/`beforeDateTime`. The tool answers at most **25 events per
call** — a packed day plus its all-day entries can exceed that — so when a
response carries `nextOffset`, call again with `offset` set to it until it
stops.

**Write the raw `outlook_calendar_search` results — every page — to
`$SCRATCH/m365_calendar.json` with the Write tool — never hold them in the
main context.** A day's calendar search easily runs tens of thousands of
characters, and it is read once (to
filter and sort) then never needed again; keeping it in context past that
point is pure waste that every later turn in the run pays for again. Read it
back from the file to filter out all-day and cancelled events; sort by start
time; render times in the vault owner's local timezone. For each event, build
the prep as **three fields**: `attendees` (names, organizer first),
`last_meeting` (a wikilink to the most recent note for this entity or
project with a one-line what-happened, or `none on file`), and `context`
(one line from the entity dossier and the project's *Where it stands* card,
or, with no confident match, one line from the event alone and `No tracked
project.`). Each field is one line; the CLI renders them under `#### Prep`
and adds empty `#### Notes` and `#### Actions` lists for the owner.
The lookups: match attendee email domains and subject keywords against
`40-entities/*/` and active projects in `30-projects/*/index.md` (same
signals, same order, as `/sync-recordings` step 3); read the matched dossier
and the most recent meeting note for that entity or project. No match → no
entity suffix and a prep line from the event alone. `m365_calendar.json`
matches the `m365_*.json` sweep pattern, so the end-of-run sweep above
clears it with everything else.

Calendar tool missing or erroring → `meetings: []` with
`meetings_note: "*Calendar unavailable — meetings could not be prepped.*"`.
The note is still written. "Couldn't look" is not "looked and found
nothing" — say which one happened in the summary.

## Stage 6 — Write tomorrow's note

Compose the recap from: the recap window's meetings (everything in
`20-meetings/` dated within `recap_from`..`recap_to`), decisions written in
stage 4, harvest jottings worth carrying forward, content risks worth the
owner's attention, and the run's own mechanics (conflicts, unresolved
duplicates, self-check warnings) — the last group is `sync_notes`, never
`watch`. Respect the
language and depth preferences in
`99-workflow-config/context/preferences-and-constraints.md`.

**Write from the note's date, not from the day you are running.** The note is
dated `next_business_day` and it is read on that day, so every relative
word resolves against *that* day. The meetings you are recapping happened
inside the recap window — from the note's vantage that is **yesterday** (or
earlier), and "today" is the day being prepped. **"Tomorrow" never belongs in a recap at all**: from
inside the note it means the day *after* the note, which is not a day this
run knows anything about. Safest is to skip relative words and use the day
names `dates plan` already handed you — `next_day_name` for the day being
prepped, `recap_from_day_name`/`recap_to_day_name` for the recapped window's
bounds — or the ISO date; those cannot point at the wrong day.
(`today_day_name` is the run day: in the `--for-today` frame that is the
note's own day, not the recapped one, so a recapped meeting's day name comes
from the recap-bound keys, never from `today_day_name`.) This is the one
error a reader always catches, because they are reading it on the day it is
wrong about.

**A flat list of meetings is not a recap.** The CLI renders the recap from
fields; you supply the judgment. Caps are enforced by field, and a refusal
names the field, so one retry always suffices.

- `glance.headlines` — 1–4 items, each `{label, text ≤ 20 words}` with
  `label` one of `Needs your hand` · `Moved` · `New` · `Decided` · `Quiet`.
  `glance.entities` — the entity slugs touched. The first line (meeting
  count, window, theme and decision counts) is computed by the CLI; never
  write it.
- `themes` — 0–4 patterns *across* meetings: `headline` ≤ 12 words, `body`
  ≤ 80 words, `sources` as `{stem, label}` meeting or daily-note stems. With
  one meeting, say what it means, not that it happened.
- `pulse` — one row per project touched: `project` slug, `signal`, `text`
  ≤ 40 words on where it stands and what moved. Signals: **red** = needs the
  owner's hand this week · **amber** = a risk building, nothing to do yet ·
  **green** = moved forward · **quiet** = no activity in the window.
- `decisions` — the stems stage 4 wrote; the CLI renders each with its
  summary and project.
- `watch` — **content risks only**, one line each (≤ 40 words).
  **Watch is content only**: every conflict, unresolved duplicate, fetch
  error, refusal, out-of-reach transcript and `SELF-CHECK` line goes in
  `sync_notes`, which renders folded, and never in `watch`.
- `carried_forward` — jottings worth carrying, one line each.
- `sync_notes` — the mechanics, one line each; also in the run summary.

The catch-up banner is the CLI's: `dates plan`'s `is_catchup` becomes the
callout on write, and a banner you put in a payload is stripped with a
warning.

**Every entity, person and project you name is a wikilink to the object you
looked up — never a name you recalled.**
`daily-note write` refuses a link that resolves to nothing, and where the
target is an **entity, person or project** it refuses `[[slug|Display Name]]`
whose display name disagrees with the vault. Write them as `[[slug]]`; the
CLI rewrites identity links to the path form that opens the object in
Obsidian. Meeting, decision and
daily-note aliases are free prose — "Friday's status call" is a reference,
not a claim about what something is called. A plain-prose name it cannot
check at all, which is exactly why the linked form is required. If a name
has no object, create it first or leave the name out. Open items live on
projects — link them, never duplicate a task list.

$SCRATCH below is your session scratch directory — payloads never land in
the vault.

```bash
cat > "$SCRATCH/daily-note.payload.json" <<'JSON'
{
  "date": "<next_business_day>",
  "recap_window": {"from": "<recap_from>", "to": "<recap_to>",
                   "detailed_from": "<recap_detail_from, only when capped>"},
  "recap": {
    "glance": {
      "entities": ["<entity-slug>"],
      "headlines": [{"label": "Needs your hand", "text": "<≤ 20 words>"},
                    {"label": "Moved", "text": "<≤ 20 words>"}]
    },
    "themes": [{"headline": "<≤ 12 words>", "body": "<≤ 80 words>",
                "sources": [{"stem": "<meeting-stem>", "label": "<short label>"}]}],
    "pulse": [{"project": "<project-slug>", "signal": "green", "text": "<≤ 40 words>"}],
    "decisions": ["<decision-stem>"],
    "watch": ["<content risk, one line>"],
    "carried_forward": ["<jotting worth carrying>"],
    "sync_notes": ["<mechanical item, one line>"]
  },
  "meetings": [
    {"time": "09:00", "subject": "Weekly Status", "entity": "<entity-slug>",
     "prep": {"attendees": "<names>",
              "last_meeting": "[[<meeting-stem>|<date — one-liner>]]",
              "context": "[[<project-slug>]] · <one line>"}}
  ]
}
JSON
python3 "$VAULTLIB" daily-note write --vault "$VAULT" --note "$SCRATCH/daily-note.payload.json"
```

The CLI renders the contract on a fresh note and region-merges on an
existing one — your payload carries content only, never markers. A
`structure changed` error means the note already exists with a different
meeting set: either a different number of meetings, or a meeting heading that
no longer matches the payload (the calendar moved, or the user retyped the
heading). Report it and leave the note alone (it may hold human jottings); do
not delete it to force a rewrite.

**A refused link must not cost the vault owner their note.** The link check runs
before anything is written, so a refusal here means tomorrow has no note at
all — discovered next morning, which is the failure rule 7 already forbids
for a refused calendar. The error names every offender at once, not just the
first, precisely so one retry is enough: an unresolvable target names the
slug, an alias mismatch names the true display name. So take the resolved
name from the error, or drop the offending link — fix or drop every link the
error names, not only the first — and retry the write once — never a third
attempt. Record the refusal and what you changed as a stage-7 warning. Never
end the run without a note.

`recap_window` is what makes the run idempotent: the CLI fingerprints the
window's meetings, jottings and decisions and stamps the digest on the recap
marker. A re-run over an unchanged input set comes back with
`recap_skipped: true` and leaves the recap byte-identical — that is success,
not a failure to write. Omitting `recap_window` silently forfeits both the
guard and the catch-up banner, so always pass it. That applies to a
*correction* too: if you have to rewrite a recap you already wrote this run,
re-run `daily-note write` with `recap_window` again. A rewrite without it
strips the stamp, and the next evening regenerates a recap the vault owner has
already read. Carry any `warnings` from the result into stage 7 verbatim.

## Stage 7 — Verify against disk, then summarize

Counts come from what exists, not from what you intended (a lab run once
reported "Processed: 0" after writing a meeting correctly):

- tomorrow's note exists at `note_to_write` with a fresh mtime;
- every project reported updated shows today's `last-updated` **and a fresh
  `state-updated`** in its frontmatter;
- every recording reported synced has its stem in `20-meetings/`.

```
## Evening Sync Complete
**Synced:** {N} recordings → `20-meetings/` ({stems})
**Meetings you ticked as reviewed:** {N} now confirmed
**Possible duplicates:** {N} ({list the stems}) — kept as separate notes; each would have overwritten a meeting you already confirmed
**Metrics refreshed:** {P} projects · {Q} people
**Projects updated:** {N} ({slugs}) — {M} decisions captured for review, {K} candidates skipped
**Next note:** `60-daily-notes/{date}.md` ({DayName}, {tomorrow | today — for-today catch-up}) — {N} meetings prepped | calendar unavailable | calendar REFUSED — signed in as a different account (account-mismatch) | calendar REFUSED — no account bound to this vault yet (no-account-hint) | m365 disabled
**Recap window:** {recap_from} → {recap_to} — {catch-up: N business days missed, detailed from {date}} | current
**Recap:** regenerated | unchanged since the last run (inputs identical)
**Warnings:** {verbatim, including SELF-CHECK lines} | none
```

A non-empty warnings block means investigate before tomorrow's run.

**Scratch hygiene, one last time.** Stage 3's `/sync-recordings` run already
swept its own scratch files at its own end; this run may also have written
`m365.whoami.json` and `m365_calendar.json` in stage 5. Sweep once more
before the run ends, whether or not stage 5 ran:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

## Unattended mode

`--unattended` is what a scheduled run passes. Non-negotiable:

1. **Never ask a question.** A blocked prompt means the run exits having
   done nothing. Ambiguity → skip that item, report it, let it retry next
   run.
2. **Decision capture is always `--background`** (writes `reviewed: false`
   for the Decisions.base review queue).
3. **Prefer under-doing to wrong-doing.** No confident project match, no
   confident prep — leave it out and say so.
4. **A catch-up run caps rather than sprawls.** When `over_threshold` is
   true, detail from `recap_detail_from` and never ask which to do; put the
   window and `business_days_missed` in the Warnings block so a human
   reviews the note before relying on it. A two-month mega-recap composed
   unattended is the "wrong-doing" rule 3 is about.
5. **The run ends with exactly one run-log line, always** — including the
   "nothing happened" shape (no recordings, empty queue, calendar
   unavailable). This is the very last action of the run, after the summary
   above and the scratch sweep:

```bash
python3 "$VAULTLIB" runlog append --vault "$VAULT" --routine evening-sync \
  --outcome "<one line: e.g. 'wrote 60-daily-notes/2026-08-29.md, 2 recordings synced, 1 decision logged' or 'wrote note, nothing else to do'>"
```

   It lands in `99-workflow-config/logs/routine-runs.log` — the one place a
   human looks after the fact, whether or not they open the note itself.

## Rules

1. **Consume `dates plan` verbatim.** No day-of-week or window arithmetic
   outside the CLI.
2. **Harvest is read-only.** Today's note is never modified.
3. **Only confirmed meetings drive metrics and project updates.**
4. **Frontmatter is never model-authored.** `project touch`, `decision
   write`, `meeting write`, `daily-note write` — those are the writers.
5. **Bytes outside daily-note markers are the user's.** The CLI enforces
   it; never work around a structure error.
6. **Supersession needs explicit conflict language; never delete a
   decision.** Status flips only.
7. **Calendar unavailable, refused, or disabled still writes the note** —
   with the explicit line naming which, never a silent empty section.
8. **Verify against disk before claiming success.**
9. **Machine decisions come from `config read`** — timezone, owner
   slug, adapter enablement. Prose context files carry style and narrative,
   never these.
10. **Catch-up state is reported, never inferred, and never back-filled.**
    `business_days_missed` and `recap_detail_from` come from `dates plan`;
    the banner comes from the CLI; one note covers the whole window.
11. **Names in a machine region are looked up, not recalled.** Entities,
    people and projects appear as wikilinks to objects that exist. The CLI
    refuses the rest — treat a refusal as a lookup you skipped. Write them
    as `[[slug]]`; the CLI rewrites identity links to the path form that
    opens the object in Obsidian.
