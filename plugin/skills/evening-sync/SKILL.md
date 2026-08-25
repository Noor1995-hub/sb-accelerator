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

If `timezone` or `executive` is in `missing`, the pipeline cannot run
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

Every number above is read, never computed. If you find yourself counting
days, you are re-introducing the bug `dates plan` exists to prevent.

The executive's **person slug** is `executive` from the config — a slug,
used as-is. Stage 3 needs it.

## Stage 2 — Harvest (read-only)

```bash
python3 "$VAULTLIB" daily-note read --vault "$VAULT" --date <recap_from>
```

`exists: false` is a normal first-run state — note it and move on. Otherwise
collect per-meeting `jottings` and `end_of_day` bullets: they are context for
the recap (stage 6) and decision candidates (stage 4). The note itself is the
archive of the day — **never modify it**, and never route jottings into other
notes; in v1 they inform, nothing more.

## Stage 3 — Sync, refresh

**Sync:** run the `/sync-recordings` workflow (follow
`${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/SKILL.md`) — unattended when this run is
unattended, interactive otherwise. Its step 1 already runs
`sync reconcile-reviews`, which IS this pipeline's reconcile stage — do not
run it a second time. Record what it reports: synced stems, folded ticks,
conflicts, per-adapter lines.

**Refresh:**

```bash
python3 "$VAULTLIB" sync update-queue --vault "$VAULT" --today <today> --executive <exec-slug>
```

This writes `meetings-7d` / `meetings-30d` / `key-people` on active projects
and `meetings-7d` / `meetings-30d` on people (confirmed meetings only — the
review queue is the quality gate), and returns `projectsNeedingUpdate`: each
entry carries `indexPath`, `decisionsDir`, `lastUpdated`, `newFiles`, and the
`existingDecisions` projection. Carry `warnings` — especially `SELF-CHECK`
lines — into the final summary verbatim.

## Stage 4 — Project-state updates

If the queue is empty, record "no projects to update" and skip to stage 6.
Otherwise, per queued project, dispatch a subagent (up to 3 in parallel) with
the queue entry, the harvest jottings that mention the project, today's date,
and these instructions:

1. Read the `newFiles` meetings end-to-end — Key Takeaways, Debrief, Action
   Items.
2. Rewrite the `> [!summary]+ **Now**` callout in `indexPath` — **exactly 5
   bullets**: Stage · Defining decision (wikilink) · Next event · Owe ·
   Watch. Rewrite `## Open Items` (add new, remove resolved — vocabulary:
   📤 Owe · 👤 Awaiting · ❓ Question · ⏳ Pending). Touch **nothing else in
   the body** — the Dataview blocks render themselves.
3. Frontmatter goes through the CLI, never your editor:

```bash
python3 "$VAULTLIB" project touch --vault "$VAULT" --slug <slug> --date <today> --next-milestone "<one line>" --next-milestone-date <ISO>
```

   (Omit the milestone pair when no concrete next event was identified.)
4. Decision capture: extract candidates from the new meetings AND the
   harvest jottings, then follow
   `${CLAUDE_PLUGIN_ROOT}/skills/log-decision/SKILL.md` in **background mode**
   (`/log-decision <slug> --background`) with those candidates as the
   source. Its rules apply unchanged: the material-decision test (commits
   the engagement AND changes a stakeholder's behaviour), dedup against
   `existingDecisions`, supersession only on explicit conflict language,
   never delete, status flips only. Writing nothing is a valid outcome.
5. Return a fenced JSON block: `{"slug", "indexUpdated": bool,
   "decisionsWritten": [stems], "decisionsSkipped": N, "notes"}`. A subagent
   that fails or returns no block becomes a warning, not a retry.

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
wrong engagement must never prep this vault's meetings. Delete the whoami
scratch file immediately on a refusal, and in any case before the run ends.
When the gate passes, pull `next_business_day`'s events; compute the query
window deterministically:

```bash
python3 "$VAULTLIB" dates window --start <next_business_day> --timezone <tz> --hours 0
```

Filter out all-day and cancelled events; sort by start time; render times in
the executive's local timezone. For each event, build one prep line —
**Attendees:** names · **Last meeting:** date + one-liner · **Context:** one
line from the entity dossier and the project's Now callout. The lookups:
match attendee email domains and subject keywords against `40-entities/*/`
and active projects in `30-projects/*/index.md` (same signals, same order,
as `/sync-recordings` step 3); read the matched dossier and the most recent
meeting note for that entity or project. No match → no entity suffix and a
prep line from the event alone.

Calendar tool missing or erroring → `meetings: []` with
`meetings_note: "*Calendar unavailable — meetings could not be prepped.*"`.
The note is still written. "Couldn't look" is not "looked and found
nothing" — say which one happened in the summary.

## Stage 6 — Write tomorrow's note

Compose the recap from: the recap window's meetings (everything in
`20-meetings/` dated within `recap_from`..`recap_to`), decisions written in
stage 4, harvest jottings worth carrying forward, and watch items
(conflicts, unresolved duplicates, self-check warnings). Respect the
language and depth preferences in
`99-workflow-config/context/preferences-and-constraints.md`.

**A flat list of meetings is not a recap.** Required shape, in order:

1. `> [!info] At a glance` — one line: N meetings · entities touched · themes.
2. **Themes** — with ≥2 meetings in the window, 2–4 bullets, each a pattern
   *across* meetings and each naming what it draws on. With one meeting, say
   what it means, not that it happened.
3. **Project pulse** — one line per project touched: where it stands (from
   the project's `Now` callout) and what moved this window.
4. **Decisions logged** — from stage 4, wikilinked.
5. **Watch** — conflicts, unresolved duplicates, `SELF-CHECK` lines.
6. **Carried forward** — jottings worth carrying.

**Every entity, person and project you name is a wikilink to the object you
looked up — never a name you recalled.**
`daily-note write` refuses a link that resolves to nothing, and where the
target is an **entity, person or project** it refuses `[[slug|Display Name]]`
whose display name disagrees with the vault. Meeting, decision and
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
  "recap": "> [!info] At a glance\n> {N meetings · entities · themes}\n\n**Themes**\n- {pattern across meetings}\n\n**Project pulse**\n- [[project-slug]] — {where it stands; what moved}",
  "meetings": [
    {"time": "09:00", "subject": "Weekly Status", "entity": "acme-industries",
     "prep": "**Attendees:** … · **Last meeting:** … · **Context:** …"}
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

**A refused link must not cost the exec their note.** The link check runs
before anything is written, so a refusal here means tomorrow has no note at
all — discovered next morning, which is the failure rule 7 already forbids
for a refused calendar. The error is precise enough to act on: an
unresolvable target names the slug, an alias mismatch names the true display
name. So take the resolved name from the error, or drop the offending link,
and retry the write once — never a third attempt. Record the refusal and
what you changed as a stage-7 warning. Never end the run without a note.

`recap_window` is what makes the run idempotent: the CLI fingerprints the
window's meetings, jottings and decisions and stamps the digest on the recap
marker. A re-run over an unchanged input set comes back with
`recap_skipped: true` and leaves the recap byte-identical — that is success,
not a failure to write. Omitting `recap_window` silently forfeits both the
guard and the catch-up banner, so always pass it. Carry any `warnings` from
the result into stage 7 verbatim.

## Stage 7 — Verify against disk, then summarize

Counts come from what exists, not from what you intended (a lab run once
reported "Processed: 0" after writing a meeting correctly):

- tomorrow's note exists at `note_to_write` with a fresh mtime;
- every project reported updated shows today's `last-updated` in its
  frontmatter;
- every recording reported synced has its stem in `20-meetings/`.

```
## Evening Sync Complete
**Synced:** {N} recordings → `20-meetings/` ({stems})
**Meetings you ticked as reviewed:** {N} now confirmed
**Possible duplicates:** {N} ({list the stems}) — kept as separate notes; each would have overwritten a meeting you already confirmed
**Metrics refreshed:** {P} projects · {Q} people
**Projects updated:** {N} ({slugs}) — {M} decisions captured for review, {K} candidates skipped
**Tomorrow's note:** `60-daily-notes/{date}.md` ({DayName}) — {N} meetings prepped | calendar unavailable | calendar REFUSED — signed in as a different account (account-mismatch) | calendar REFUSED — no account bound to this vault yet (no-account-hint) | m365 disabled
**Recap window:** {recap_from} → {recap_to} — {catch-up: N business days missed, detailed from {date}} | current
**Recap:** regenerated | unchanged since the last run (inputs identical)
**Warnings:** {verbatim, including SELF-CHECK lines} | none
```

A non-empty warnings block means investigate before tomorrow's run.

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
9. **Machine decisions come from `config read`** — timezone, executive
   slug, adapter enablement. Prose context files carry style and narrative,
   never these.
10. **Catch-up state is reported, never inferred, and never back-filled.**
    `business_days_missed` and `recap_detail_from` come from `dates plan`;
    the banner comes from the CLI; one note covers the whole window.
11. **Names in a machine region are looked up, not recalled.** Entities,
    people and projects appear as wikilinks to objects that exist. The CLI
    refuses the rest — treat a refusal as a lookup you skipped.
