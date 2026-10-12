# Session 1 — the onboarding interview

> **Status 2026-10-12 — read this first.** Since v0.12.5 (#229) Session 1 is
> `/setup-my-brain` run by the **vault owner alone**, with no consultant in
> the room. The skill now runs in Steps 0–11 (preflight; welcome and connect;
> what only they know; a consented read of calendar, sent mail and Teams chat
> list; entities; work; people; how they write; systems and boundaries; the
> first evening note; the standing evening run; close), not the Phase 0–5
> interview this script was written for. The source of truth is
> `plugin/skills/setup-my-brain/SKILL.md`.
>
> This script is kept for reference, and for a consultant who sits in at the
> owner's request. If you do: the owner types, not you; the phase names and
> timings below no longer match the skill; and the "Day before" checks still
> apply — they are yours to do, including `/upgrade-vault`, which is run by
> the consultant and never handed to the owner alone.

delaware-side material; never ships. The consultant's side of
`/setup-my-brain`: how to run the room while the skill runs the interview.
This is not a transcript of what the skill says — read
`plugin/skills/setup-my-brain/SKILL.md` for that. This is what you do around
it: before it starts, while it runs, and after it ends.

Budget the whole session at **two hours**, live, vault open on screen.

## Day before

- `python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" migrate status --vault <vault>`
  — `pending` must be empty. Phase 0 of `/setup-my-brain` stops the session
  outright on a non-empty `pending`, and discovering that live, in front of
  the executive, is a worse first impression than a five-minute check the day
  before. If it is not empty, run `/upgrade-vault` before session day.
- `python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" config read --vault <vault>`
  — confirm the vault is provisioned (`ok: true`) and `missing` reads the
  fresh-run default, `["owner", "sync.start-date", "timezone"]`. Anything else
  means either a re-run (see below) or a vault that provisioning did not
  finish — settle that before the executive sits down, not during Phase 1.
- Connector admin consent already done: the M365 tenant consent for the
  connector, and the Plaud account provisioned — both are pre-flight items,
  not something to arrange live. Phase 2 asks the executive what they want to
  connect; it cannot make either exist.
- Recorder charged. If Plaud is in play, it is handed over physically at the
  close of Phase 2 (see "Kit handover" below) — arrive with it working, not
  arriving.
- **Tomorrow's calendar has real meetings.** This is the one item that is
  easy to forget and expensive to skip: Phase 4 writes tomorrow's daily note
  live, on screen, with a prepared section per real meeting naming the
  entities, projects and people just seeded. A calendar with nothing on it
  still produces a valid note — the no-meetings line — but the close reads as
  correct instead of impressive. If the executive's calendar is thin
  tomorrow, move the session rather than accept a flat close.

## Room setup

*Superseded — see the status note at the top.* The skill is now built for
the owner at their own keyboard. If you sit in, stay beside them and let them
answer and type.

Originally: the consultant drove the keyboard and the executive watched the
screen and answered, never typing the interview themselves.

## The arc

Six stretches, mapped to the skill's own phase names:

| Time | Skill phase | What happens |
|---|---|---|
| 10 min | Phase 1 — opening + company | Frame the session, ask about their company first |
| 45 min | Phase 1 — the five files | identity, role-and-responsibilities, communication-style, preferences-and-constraints, tools-and-systems |
| 15 min | Phase 2 — connecting the accounts | Plaud and/or Microsoft 365, account binding |
| 25 min | Phase 3 — seeding | entities, then projects, then people |
| 15 min | Phase 4 + 4b — first note + schedule | tomorrow's daily note, the standing evening run |
| 10 min | Phase 5 — close | what's true now, what to look at, what's still owed |

Phase 0 (the preflight `config read` / `migrate status` checks) already
happened the day before — the executive never sees it.

## Say it in their language, phase by phase

**Opening + company.** Say plainly this is a conversation, not a form, and
roughly how long it takes. Ask what their company does before anything
else — it is the easiest question in the room, and it is what every later
question calibrates against. The skill offers a short public-research pass
once, in one line — let the executive say yes or no; do not skip the offer
because you already did the reading.

**The five files.** The skill frames this stretch as "the part that stops it
sounding like a consultant and starts it sounding like you" — use that
framing, do not paraphrase around it. Two things worth watching for rather
than saying: file 2 is where a responsibility ("the yard network") gets
confused with a project ("this year's tender") — the skill has its own line
for pulling those apart the first time it comes up, use it once and then
just keep the two lists separate as they talk. File 3's mail-read offer is
asked here but only ever acted on once Microsoft 365 is actually connected in
Phase 2 — say so and move on; there is nothing to connect yet.

**Connecting the accounts.** Ask what they want connected before showing any
machinery — Plaud, Microsoft 365, both, or neither, in their words, not as a
checklist. The account hint that binds a connector to this vault is always
copied verbatim from the connector's own signed-in-account payload — never
ask the executive to type or spell an email address; it is often not even
the address they think they use.

**Seeding.** Say the shape of the stretch up front ("about ten to twenty
minutes, I'll ask you to confirm a few lists") and the reassurance that
covers all three lists at once: whatever does not make today's cut can be
added in under a minute later, so a short list beats a long one. Entities
come from what the executive names, never from the calendar; the calendar
only ever proposes people and projects, and only for the executive to
confirm or drop.

**First note + schedule.** Open tomorrow's daily note on screen and walk it
section by section, naming what they are looking at as you go. Then say the
schedule's honest version of the promise: "your note is prepared each
evening the laptop is on" — never "your note arrives every evening." Keep
the executive in the room for the one manual run that grants the routine its
connector and Bash permissions; it is their only chance to watch it work
before they are asked to trust it.

**Close.** Close from their side of the table, in this order: what is true
now, what to go look at by name, what happens next and when, what to do when
something is missing, what is still owed. The counts — files filled,
connectors live, objects seeded — come last, and are your footnote, not
their summary.

## Hesitation handling

- **Won't share something.** Say that anything they would rather keep out of
  the shared vault belongs in `95-private/` — the owner-private folder that
  is never read by any skill. A real boundary, not a polite one.
- **Won't have their mail read.** The decline path is fine and it is
  recorded as such — file 3's block stands as drafted from the interview,
  and the skill needs no further commentary from you. Do not push back on a
  decline; a declined offer needs no defending.

## The three don'ts

1. **Never read the skill aloud.** The wording in `SKILL.md` is instructions
   to you, not a script for the executive's ears — the framing lines it
   quotes are the exception, said in your own voice, not read off the file.
2. **Never type frontmatter.** Every write in this session goes through the
   vaultlib CLI the skill calls. If you find yourself editing a note's
   properties by hand to make something look right, stop — that is the skill
   failing to do its job, not a shortcut to take.
3. **Never promise "every evening."** Say what Phase 4b actually delivers:
   a routine that fires while the machine is awake and Claude is open. The
   gap between those two sentences is the first thing a travelling executive
   notices is false.

## Kit handover

If Plaud is one of the connectors chosen in Phase 2, hand over the physical
recorder once the account is bound and verified — not before, so the device
they walk away with is already tied to their own vault, not a demo account.
Say, in one line, what it is for (their pocket recorder for the meetings
Microsoft 365 cannot see) and where to charge it.

## Exit checklist

Before you close the laptop:

- [ ] `config read` shows `owner`, `timezone` and `sync.start-date` filled.
- [ ] Every connector chosen in Phase 2 reports `match: true` from
      `config verify-account`, or was explicitly declined and left disabled.
- [ ] All five context files are written (`context read` for each, or trust
      the skill's own read-backs during the session).
- [ ] At least the entities, projects and people the executive actually
      confirmed exist — check counts against what you seeded, not against a
      target number.
- [ ] Tomorrow's daily note exists and was walked through on screen.
- [ ] The evening run is either scheduled (`nextRunAt` confirmed) or handed
      off in writing, named to a person and a date.
- [ ] Kit handed over, if applicable.
- [ ] Anything skipped or declined is named out loud in the close, not left
      implicit.

## Re-run mode — a second session

A config whose `owner` and `timezone` are already filled is a re-run, not a
fresh start — a tune-up, a second session with the same executive, or
picking a session back up after an interruption. Say so plainly at the
start: "we're revisiting what's already here, not starting over." Every
phase opens by showing what already exists — the current context block, the
current config values, the entities and projects already seeded — before
asking whether to revise anything. Revising is cheap; expect this session to
run well under two hours once past the first file, because most phases are a
quick confirm rather than a fresh interview. `project scaffold` refuses a
slug that already has a folder — treat that refusal as "that one's already
there" and move on, never as a failure to retry under a different name.
