---
name: log-decision
description: Extract material decisions from a meeting note, transcript, or description and write them as atomic decision notes on a project, setting both sides of any supersession edge. Triggers when the user invokes /log-decision or asks to record, log, or capture a decision.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Log Decision

Turn a source into atomic decision notes on a project. You decide what counts
as a decision and what it supersedes; the CLI writes the notes and maintains
both sides of every supersession edge.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there. Say so
plainly rather than hand-writing a decision note.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure show the `error` and `hint`
rather than retrying blind or writing the file by hand.

## Usage

```
/log-decision
/log-decision meridian-yard-automation-program
/log-decision meridian-yard-automation-program --background
```

**Foreground** (the default) proposes each candidate and waits for the user.
**Background** never prompts — it is what the evening run calls, and it marks
what it writes `reviewed: false` for later audit.

## What counts as a decision

The test both modes apply, and the reason the decision log stays worth reading:
a candidate qualifies only if it **commits the engagement** *and* **would change
a stakeholder's behaviour**.

| Not a decision | Why |
|---|---|
| "Omar will send the scoring sheet" | A task. It belongs in the project's Owe list (the folded 📤 Owe callout under Background), written through `project state write`. |
| "Leo thinks the yard-2 timeline is tight" | An opinion. Record it in the dossier's Sensitivities if it matters. |
| "We'll meet again on the 14th" | Scheduling. |
| "We prefer the phased approach" | A preference, until something is committed. |
| Anything already in `decision list` | A restatement. Say so and move on. |

**Writing nothing is a valid outcome.** If the source carries no material
decision, say what you read, say why none of it earned a note, and stop. A
fabricated entry to justify the invocation is the failure mode this skill has to
avoid.

## Workflow

### 1. Identify the project

If no slug was given, list what exists and ask:

```bash
ls "$VAULT/30-projects"
```

The project must already exist — `decision write` refuses otherwise and points
at `/new-project`. Do not create a project just to hold a decision; ask.

### 2. Read what is already recorded

```bash
python3 "$VAULTLIB" decision list --vault "$VAULT" --project <slug>
```

You get every decision on the project, newest first: `stem`, `date`, `status`,
`summary`, `supersedes`, `source`, `reviewed`, `dismissed`. **Read this before
extracting.** It is what lets you recognise a restatement, and it is where any
supersession candidate comes from.

An entry with `dismissed: true` is a capture the owner ticked **Dismiss** on:
not a real decision. It still counts for dedup — a candidate that restates it
is skipped, never written again — but it is never cited and never
superseded.

`supersedes` and `source` come back as **bare stems**
(`2026-03-10-phased-rollout-adopted`), which is exactly the form `decision
write` takes. Pass them back as they came — do not add `[[…]]`.

An entry carrying `unreadable` is a hand-mangled file. Mention it once and work
around it; do not try to repair it here.

### 3. Get the source

In foreground mode, if the user has not already provided it:

> What should I read? Paste the notes, point me at a file, or just tell me what
> was decided.

Accept any of three forms: pasted text, a file anywhere in the vault (inbox
captures live in `10-inbox/`, meeting notes in `20-meetings/`), or a spoken
description. In background mode the source is handed to you by the caller.

### 4. Extract candidates

For each candidate, decide:

- **`title`** — a short kebab-able label, three to six words. This becomes the
  filename after the date: `2026-05-20-single-vendor-strategy-adopted`. Do not
  reuse the summary sentence; a slug of it is a truncated paragraph.
- **`summary`** — one full sentence, specific enough to be useful in a table
  without opening the note. This is the Decision column in `Decisions.base`.
- **`decision` / `why` / `implications`** — one paragraph each. `why` includes
  what was traded away; `implications` says what actually changes — scope,
  dates, who does what. No lists: each field is rendered as a single wrapped
  paragraph.
- **`status`** — `active`, or `withdrawn` if the source shows it was decided and
  then reversed. Never `superseded`; that status is set on the *prior* note.
- **`source`** — the stem of the meeting note this came from, or of the message
  log (`_messages/<YYYY-MM-DD>-messages`) when the decision came from mail or
  chat. A meeting stem must resolve to a file in `20-meetings/`. **Omit
  `source`** only when there is neither (an inbox transcript, a pasted
  paragraph or dictation): put the provenance in the `why` text instead.
- **`supersedes`** — see below.
- **the date** — the date the decision was **made**, read out of the source. A
  steerco on the 12th logged on the 14th is dated the 12th; the date is what
  orders the log. Today is the fallback, not the answer.

### 5. Supersession — only on explicit conflict

A new decision supersedes a prior one when the source **says** it replaces it:
"instead of", "we're reversing", "this replaces". Not because you judge two
notes inconsistent.

When you are unsure, write the new note **without** `supersedes` and say in your
summary that the two look inconsistent. Two active decisions a human resolves
beats a wrong edge, because the flip is a write on somebody else's note.

Only an `active` decision can be superseded, only one in the same project,
and never a dismissed one. The CLI enforces all three.

### 6. Confirm, then write

**Foreground.** Present each candidate before writing — title, summary, and what
it supersedes if anything — and let the user confirm, edit, or drop it. Then
write the accepted ones, one call each:

```bash
cat > "$SCRATCH/decision-meridian-yard-automation-program.json" <<'JSON'
{
  "title": "single vendor strategy adopted",
  "summary": "Consolidate on a single automation vendor across all three yards to simplify integration and reduce total cost of ownership.",
  "decision": "Consolidate on a single automation vendor across all three yards.",
  "why": "Running three vendors' control software in parallel created integration overhead that outweighed the site-pacing benefit of the phased approach.",
  "implications": "The pilot vendor stays for yard 1; yards 2-3 re-scope onto the same platform, pushing commissioning out roughly six weeks.",
  "source": "20-05-26-vendor-strategy-brainstorm",
  "supersedes": "2026-03-10-phased-rollout-adopted"
}
JSON
python3 "$VAULTLIB" decision write --vault "$VAULT" \
  --project meridian-yard-automation-program \
  --date 2026-05-20 --note "$SCRATCH/decision-meridian-yard-automation-program.json" --foreground
```

Build the payload into `$SCRATCH`, never a hardcoded system temp directory,
and qualify the filename with the project slug — `decision-<slug>.json`,
never a bare `decision.json`. This skill runs in background mode from
evening-sync's per-project subagents, which all share one session scratch
directory: in a live run, two concurrent invocations racing on the one
generic name made `decision write` read the *other* project's payload and
publish it, misattributed, into the wrong project's decision log — with two
clients' projects in flight, a confidentiality breach, not just a wrong
file. The slug makes the collision structurally impossible (the evening run
dispatches one subagent per project), a fixed path outside `$SCRATCH` is
not guaranteed writable or private, and `decision-<slug>.json` matches the
`decision-*.json` pattern `scratch sweep` clears at the end of the calling
run.

Build the payload as a **file**, never inline — shell quoting mangles
apostrophes and em dashes. One decision per call: a failure then names exactly
which decision failed.

`--foreground` writes `reviewed: true`, which is a claim that a human validated
this note. Only pass it when one actually did.

**Background.** Identical, with `--background` and two rules that are not
negotiable:

1. **Never ask a question.** An unattended run that blocks on a prompt exits
   having done nothing. Ambiguity means skip that candidate and report it — a
   skipped decision is recoverable, a hung job is not.
2. **Verify against disk, not your own narrative.** Build the summary from what
   `decision write` returned and from the files that exist, never from your
   intent. A lab job once reported "Processed: 0" while having correctly written
   a note.
3. **A background supersession needs verbatim replacement language.** Flipping
   a human-validated note is the riskiest unattended write this skill makes,
   and there is no inverse operation. If the source does not literally state
   that the old decision is replaced, write the new note without `supersedes`
   and flag the tension in your summary.

Extract more conservatively here than in foreground: if a candidate would need a
question to get right, it is not a background candidate.

### 7. Summarise

Report, from the CLI's results rather than from memory:

- each note written — path, and what it supersedes
- **each supersession, both sides**: "flipped `2026-03-10-phased-rollout-adopted`
  to superseded". If `supersession.error` is present the edge is one-sided —
  surface that verbatim, it needs a human.
- what you read and deliberately did **not** record, and why
- any inconsistency you spotted but did not resolve into a supersession

In background mode this summary is the caller's return value — the evening run
renders it directly, so it must be complete and it must be true.

## Rules

1. **Never hand-write a decision note.** Every write goes through
   `decision write`. It validates against the ontology; you do not.
2. **Never delete a decision.** Status flips only. The CLI has no delete.
3. **Read `decision list` before extracting.** Without it you cannot tell a new
   decision from a restatement, and you cannot find a supersession target.
4. **Pass stems back as they came.** `supersedes` and `source` cross this
   boundary as bare stems in both directions. Wrapping one in `[[…]]` yourself
   is how you get `[[[[…]]]]`.
5. **Supersession needs explicit conflict language.** When in doubt, leave both
   active and say so.
6. **`--foreground` is a claim about a human.** Unattended writes are
   `--background`, always.
7. **Do not invent.** No decision is better than a plausible one; this vault is
   read as a record.
