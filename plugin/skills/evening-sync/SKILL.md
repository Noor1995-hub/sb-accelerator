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
/evening-sync                    # interactive: asks only where a stage says so
/evening-sync --unattended       # scheduled shape — never prompts, ever
```

Stages are **failure-isolated**: a failed stage logs its error into the final
summary and the chain continues. A crashed calendar still gets a daily note;
a failed sync still gets metrics and project updates.

## Stage 1 — Dates (authoritative, never re-derived)

Take the run lock:

```bash
python3 "$VAULTLIB" runlock acquire --vault "$VAULT" --routine evening-sync
```

`acquired: false` means the owner's on-demand processing is running. Wait
with the CLI itself — up to 10 more calls, each one waiting 60 seconds inside
the call and trying once more:

```bash
python3 "$VAULTLIB" runlock acquire --vault "$VAULT" --routine evening-sync --wait 60
```

Never a separate sleep command (a scheduled run is only allowed the CLI) and
never a loop the model polls. Still `acquired: false` after the 10th → continue
anyway and add to the warnings: "ran while the meeting sync held the lock
(since <started_at>)".

Release it on every early exit as well as at stage 7 (below).

Read the deployment config, then plan the dates:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <config.timezone>
```

If `timezone` or `owner` is in `missing`, the pipeline cannot run
deterministically: release the lock, stop, and say which key to fill in
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

## Stage 2 — Harvest (read-only, except assigning a note's empty projects and recording actions)

```bash
python3 "$VAULTLIB" daily-note read --vault "$VAULT" --date <recap_from>
```

`exists: false` is a normal first-run state — note it and move on. Otherwise
collect, per meeting, `notes` (the owner's bullets under `#### Your notes`
— `#### Notes` on notes written before 0.12.11 — or bullets directly under
the heading on a note written before v2) and `actions` (`{text, done}` from
the `- [ ]` / `- [x]` list under `#### Your to do's`), plus the `notes` bullets (the day's `## Notes` section — `## End of day` on notes written before structure 11; the CLI reads both). All of it is context for the
recap (stage 6) and decision candidates (stage 4). Each `- [ ]` line is also
followed up in the To Do's table — see **To Do's** below. The note itself is
the archive of the day — **never modify it**.

**Your notes ticked Include:** follow section A of `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md`.

**To Do's.** While `structure_version` is below 12, skip this paragraph — the
vault has no To Do's table yet. To the owner they are always "to do's", never "actions". Otherwise:

```bash
python3 "$VAULTLIB" actions harvest --vault "$VAULT" --from <recap_from> --to <recap_to>
```

`closed` lists to-do notes whose line the owner ticked in a daily note
since; the CLI already marked them done. `filled` lists notes made with
**New** whose empty Done the CLI set to no; nothing to do about either. `new` lists every open `- [ ]` line
not yet recorded, each with its `source` (the daily note's date), `text`,
the `meeting` subject and `entity` it sits under (null for a line outside a
meeting) and `entity_projects`, that entity's active projects. For each,
fill in what you can tell and leave the rest open — the owner fills it in on
the row:

- `project` — the entity's project when `entity_projects` holds exactly one;
  otherwise the active project the text names (its name, its `keywords`).
  Unsure → omit it. Never guess between two.
- `due` — the deadline **phrase exactly as the owner wrote it** ("Friday",
  "14/10", "tomorrow", "2026-10-14"). Never turn it into a date yourself:
  the CLI resolves it against the daily note's date and leaves `due` empty
  when it cannot. No phrase → omit it.

Write every item to one JSON list (`source`, `text` verbatim, then `project`
and `due` when known) and:

```bash
python3 "$VAULTLIB" actions create --vault "$VAULT" --items "$SCRATCH/actions.payload.json"
```

A line already recorded comes back under `skipped`; that is the normal
second run, not an error. `warnings` (a project that is not active, a
deadline the CLI could not read) go to `sync_notes`. Count `created` and
`closed` for the summary. Unattended runs do exactly the same — nothing
here asks.

## Stage 3 — Sync, refresh

**Sync:** run the `/sync-recordings` workflow (follow
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/SKILL.md`) — unattended when this run is
unattended, interactive otherwise. The workflow's steps 8–11 (the owner's
on-demand triage and processing) never run here, in either mode: this run
processes in its own stage 4. Its step 1 runs `sync reconcile-reviews`,
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

### Stage 3b — Mail and Teams

When `messages.enabled` is true in `config read`: run the `/sync-messages`
workflow (follow `${CLAUDE_PLUGIN_ROOT}/skills/sync-messages/SKILL.md`),
unattended when this run is unattended. Record its outcome line for the
summary, verbatim, and `since` when it reports a first run (stage 6 needs it).
It runs before the refresh below so tonight's update queue sees tonight's
logs. A failed stage 3b is recorded and the evening continues. Off, or no
M365: skip with one line in the summary.

### Stage 3c — Refresh (every evening)

Runs every evening, whatever stage 3b did — off, skipped or failed.

Follow section B of `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md`.

## Stage 4 — Project-state updates

Follow sections C, D and E of `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md`, passing the stage-2 harvest jottings to C. Record its Returns for stages 6 and 7.

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

Prep never reads a person page's `## What I know`: facts about people stay
on their page.

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
characters, and it is read once (by the CLI, below) then never needed again;
keeping it in context past that point is pure waste that every later turn in
the run pays for again. Write the pages exactly as the tool answered them —
objects back to back, paging markers included; the CLI reads that shape.

Then let the CLI turn the listing into the day's agenda:

```bash
python3 "$VAULTLIB" m365 agenda --events "$SCRATCH/m365_calendar.json" --timezone <tz> --date <next_business_day>
```

The result's `meetings[]` is already filtered (all-day, cancelled and
other-day entries dropped and counted under `dropped`), sorted by start, and
rendered in the vault owner's local time. **Carry each entry's `time` and
`subject` into the payload verbatim.** Never read `start.dateTime` yourself:
the connector answers every start as a wall clock in the mailbox's own
zone (`"UTC"` on some mailboxes, a Windows name like `"Romance Standard
Time"` on others), and a hand-copied clock put every meeting two hours early
in a daily note once — the offset is the CLI's to apply, not yours. The
remaining fields (`organizer`, `attendees`, `location`, `show_as`,
`is_organizer`, `uri`) are the inputs for the prep below.
For each event, build
the prep as **three fields**: `attendees` (names, organizer first),
`last_meeting` (a wikilink to the most recent note for this entity or
project with a one-line what-happened, or `none on file`), and `context`
(one line from the entity dossier and the project's *Where it stands* card,
or, with no confident match, one line from the event alone and `No tracked
project.`). Each field is one line; the CLI renders them under `#### Prep`
and adds empty `#### Your notes` and `#### Your to do's` lists for the owner.
It also opens every new note with the `> [!review] Waiting for you` block —
the live Meetings and Decisions review queues; nothing to pass for it.
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
- `notes_read` — one `{path, projects}` per note whose `mark-absorbed` returned `marked` tonight (never `unchanged` or `missing`; a path that no longer exists by render time is dropped with a warning); the CLI renders the line. Omit it when none were.
- `messages` — whenever `messages.enabled` is true in `config read`,
  whatever stage 3b did (ran, skipped or failed): a feed that keeps failing
  must still say so in the note. Omit the field only when the feed is off.
  The CLI renders it as the *Mail and Teams* block right after *At a
  glance*, inside the recap (below the *Waiting for you* queues). Build it
  in this order:
  1. `python3 "$VAULTLIB" messages status --vault "$VAULT" --now <now UTC> [--first-run-since <since from stage 3b, first run only>] [--auth-error]`
     gives `{"lines": [...]}`; use those lines verbatim as `status` (at most 3).
     Pass `--auth-error` when stage 3b's outcome line was `auth-error`: the
     CLI then adds the one line asking the owner to reconnect Microsoft 365;
     never write that line yourself.
  2. `python3 "$VAULTLIB" messages keywords-propose --vault "$VAULT" --today <today>`
     gives `{"proposal": {"keyword", "project", "count"} | null}`;
     `keyword_proposal` is the proposal's `keyword` and `project` without
     `count`, or `null`.
  3. `decisions_to_confirm` — the number of decisions stage 4 wrote with a log
     `source`.
  4. `items` — at most 5 lines (≤ 30 words each) from tonight's logs: first
     what needs the owner (groups with **Needs you**), each with one concrete
     action (`kind: "needs-you"`); then one context line per project
     (`kind: "context"`). Write them to `$SCRATCH/msg_lines.payload.json` as
     `{"lines": [{"kind", "text", "cites": ["<YYYY-MM-DD>-messages#<gid>"]}]}`,
     run `python3 "$VAULTLIB" messages check-lines --vault "$VAULT" --lines "$SCRATCH/msg_lines.payload.json"`,
     and use only the `passed` lines (`{kind, text}`) as `items`. No counts,
     no internal terms.

  Run steps 1 and 2 exactly once per evening and reuse their results on any
  retry of the daily-note payload — never run them again: `messages status`
  clears the closed-unread state and `messages keywords-propose` records the
  proposal, so a second run would lose or double what the first one did.

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
    "sync_notes": ["<mechanical item, one line>"],
    "messages": {
      "items": [{"kind": "needs-you", "text": "<≤ 30 words, one concrete action>"},
                {"kind": "context", "text": "<≤ 30 words>"}],
      "status": ["<line from messages status, verbatim>"],
      "decisions_to_confirm": 0,
      "keyword_proposal": {"keyword": "<keyword>", "project": "<project-slug>"}
    }
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

Then release the run lock, before the summary (`released: false` is expected
when stage 1 carried on without it — not a failure):

```bash
python3 "$VAULTLIB" runlock release --vault "$VAULT" --routine evening-sync
```

```
## Evening Sync Complete
**Synced:** {N} recordings → `20-meetings/` ({stems})
**Meetings you ticked Keep on:** {N} now confirmed
**Possible duplicates:** {N} ({list the stems}) — kept as separate notes; each would have overwritten a meeting you already confirmed
**Mail and Teams:** {outcome line | off | skipped: no M365 | failed: …}
**To Do's:** {N} new → `65-to-dos/` ({K} with a project, {D} with a deadline) · {C} closed from ticks in daily notes | skipped: vault below structure 12
**Metrics refreshed:** {P} projects · {Q} people
**Entity pages updated:** {names, a team as "Finance (Acme)"} | none
**People pages:** {N} facts added for {M} people | none
**Projects updated:** {N} ({slugs}) — {M} decisions captured for review, {K} candidates skipped
**Next note:** `60-daily-notes/{date}.md` ({DayName}, {tomorrow | today — for-today catch-up}) — {N} meetings prepped | calendar unavailable | calendar REFUSED — signed in as a different account (account-mismatch) | calendar REFUSED — no account bound to this vault yet (no-account-hint) | m365 disabled
**Recap window:** {recap_from} → {recap_to} — {catch-up: N business days missed, detailed from {date}} | current
**Recap:** regenerated | unchanged since the last run (inputs identical)
**Warnings:** {verbatim, including SELF-CHECK lines} | none
```

A non-empty warnings block means investigate before tomorrow's run.

**Scratch hygiene, one last time.** Stage 3's `/sync-recordings` and `/sync-messages`
runs already swept their own scratch files at their own end (including
`msg_*.payload.json`); this run may also have written
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
   write`, `meeting write`, `daily-note write`, `actions create` — those are
   the writers.
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
