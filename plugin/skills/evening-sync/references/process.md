# Processing (shared)

Followed by `/evening-sync` (after stage 3b) and by `/sync-recordings` step 9 (on demand). Everything here runs the same for both callers. Only the inputs differ — see Inputs.

## Inputs

| Input | Evening | On demand |
|---|---|---|
| Ticks folded (`reconcile-reviews`, in B) | yes | yes — after the chat triage |
| Notes ticked Include (A) | yes | yes |
| Daily-note jottings (context for C) | yes — from stage 2 | no — they are read in the evening |
| To Do's | yes — evening stage 2 | no |
| Mail and Teams | evening stage 3b runs first | not read; `update-queue` still sees any log already on disk that is newer than a project's last state write |
| Project-state updates and decisions (C) | yes | yes |

On demand, C's subagents get no harvest jottings. Everything else in A–C is
identical: same caps, same batching, same `--background` decision capture.

## A. Your notes ticked Include

**Your notes ticked Include.** Run `python3 "$VAULTLIB" migrate status --vault "$VAULT"`.
While `structure_version` is below 11, skip this paragraph — the vault has no
Include yet. Otherwise:

```bash
python3 "$VAULTLIB" notes harvest --vault "$VAULT"
```

Each listed note with a `body` is input tonight, read like a jotting but
longer; a `body: null` note is over the size cap and its warning goes to
`sync_notes`. All `notes harvest` warnings, and a failed `notes harvest` call,
go to `sync_notes`, never to `watch`. For a note whose `projects` is empty, pick zero or more active
projects it is about — the same signals as for a meeting that are available
in free text: the project `keywords`, the project and entity names. Then:

```bash
python3 "$VAULTLIB" notes assign --vault "$VAULT" --path "<path>" --projects "<slug>[,<slug>]"
```

Zero projects is a valid answer: skip `assign`, and the note still informs
the recap. `assign` only writes an empty `projects` — never second-guess the
owner's choice. The run never changes a note's text, never moves a note, and
never reads `95-private/`.

## B. Refresh

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
`newFiles`, `newNotes` (owner notes ticked Include that belong to the project), and the `existingDecisions` projection. Next to the queue it returns
`notesNotQueued`: harvested notes with projects that no queue entry carries
(their project could not be queued) — the write-back in section C never marks
them. Carry `warnings` — especially `SELF-CHECK`
lines — into the final summary verbatim.

## C. Project-state updates

If the queue is empty, record "no projects to update", run the write-back for
your notes below (a note with no project is still marked), then go to the caller's next step (evening: stage 6, the recap; on demand: step 10).
Otherwise, dispatch one subagent per queued project (each with `model:
sonnet`), each carrying the queue entry, the harvest jottings (evening only; on demand there are none) that mention
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
   When the entry has `newLogs`, also run
   `python3 "$VAULTLIB" messages for-project --vault "$VAULT" --slug <slug> --logs <comma-separated newLogs>`
   and read the returned groups as input next to the meetings. Every state item
   you take from one (a Needs attention item, an Owe, an Awaiting, a closed action) ends
   with its source marker, `(mail · <link>)` or `(chat · <link>)` (`mail` or
   `chat` per the group's `kind`), where `<link>` is the group's `link`
   verbatim. The marker counts toward the item's
   word cap (hot potatoes ≤ 30 words, owe and awaiting items ≤ 40), so write
   the item short enough to carry it. When the entry has `removedSources`, drop
   every current item whose marker links one of those logs unless a meeting or
   a remaining group still supports it.
   When the entry has `newNotes`, read each note end-to-end next to the
   meetings. Every state item you take from one ends with
   `(note · <note title>)` — plain text, no wikilink: a note is not a vault
   object the state writer resolves, and its title may hold characters a
   link refuses.
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
  "coming_up": [{"when": "Wed 16 Sept", "what": "≤ 40 words", "date": "2026-09-16"},
                {"when": "Thu 1 Oct", "what": "Contract signature", "date": "2026-10-01", "milestone": true}],
  "owe": [{"owner": "Full Name", "items": ["one task per item — never chain with ';'"]}],
  "awaiting": ["…"], "questions": ["…"], "pending": ["…"], "watch": ["…"],
  "context": {"contacts": "…", "source": "…"}
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
   dated events only, ≤ 10 rows, the `date` sorts them; drop the ones that
   have passed. Mark the significant events — a go-live, a signature, a
   steerco decision, not a routine sync — with `"milestone": true`; it needs
   a `date`. The Projects table's next milestone is the first marked row
   dated today or later, and with none it is cleared, so carry the mark
   forward on rows that keep it (the current one is `next-milestone` in the
   frontmatter). Identity names
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
4. Decision capture: extract candidates from the new meetings, the
   harvest jottings, the message log groups AND the `newNotes` read in step 1, then follow
   `${CLAUDE_PLUGIN_ROOT}/skills/log-decision/SKILL.md` in **background mode**
   (`/log-decision <slug> --background`) with those candidates as the
   source. A decision from a message log group carries `source: <log stem>`, where `<log stem>` is the
   group's `log` field. A decision from a note carries `source: <note stem>`.
   Its rules apply unchanged: the material-decision test (commits
   the engagement AND changes a stakeholder's behaviour), dedup against
   `existingDecisions` (a `dismissed` one included — the owner rejected it,
   so it is never captured again), supersession only on explicit conflict language,
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
Because section C dispatch is strictly blocking, you cannot "notice" a
straggler mid-batch — the message you sent returns when every call in it is
done, full stop. This differs from `/sync-recordings` step 6, which states a
duration-scaled patience rule (a worker is a straggler only after
max(10 minutes, half the recording's duration)) because that fan-out has a
concrete per-item duration to scale against and a documented incident of a
42-minute-transcript worker being written off too early. Section C projects
have no equivalent duration signal, so no such formula applies here; if the
harness itself reports a dispatch as failed or timed out, name the project
in the final summary as a ⚠ warning rather than silently dropping it — that
is the only patience judgment section C makes.

Projects with only `needs-review` meetings never reach the queue — do not
"help" one by confirming meetings yourself.

**Write-back for your notes.** After every section C batch has returned, take
each harvested note with a `body` and mark a note only when it appears in at
least one queue entry's `newNotes` and every such entry came back
`stateWritten: true`, or when its harvested `projects` is empty. A note in
`notesNotQueued` is never marked: it keeps `include` ticked and gets one
`sync_notes` line.

```bash
python3 "$VAULTLIB" notes mark-absorbed --vault "$VAULT" --path "<path>" --date <today>
```

A note whose project failed keeps `include` ticked and is read again tomorrow;
say so in `sync_notes`. `missing` (the owner deleted or moved it during the run)
is not an error.

## Returns

What the caller carries into its summary:

- folded ticks (from B, including the second `reconcile-reviews`) and any `conflict_ticks`
- metrics written (`metricsWritten`: projects, people) from B
- `projectsNeedingUpdate` slugs
- per project: `stateWritten`, `decisionsWritten` (stems, each with its `source`), `decisionsSkipped`
- notes absorbed — `{path, projects}` for each note whose `mark-absorbed` returned `marked`
- notes kept (`include` still ticked), each with why, including `notesNotQueued`
- `sync_notes` lines from A and C — kept apart from warnings
- warnings, verbatim, including `SELF-CHECK` lines
