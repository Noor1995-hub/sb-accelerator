# Hypercare guide — weeks 2–4

delaware-side material; never ships. The three weeks after Session 2, before
the engagement settles into steady state. The EA runs the machinery; the
consultant reads what she shares and stays reachable.

## Weekly EA-run `/health-check`

The EA runs `/health-check` weekly through weeks 2–4 — the cadence
`session-1b-ea-training.md` and `session-2-habits.md` both set up. It is her
call whether to share the numbers with delaware each week; `/health-check`
never sends anything without an explicit yes to the exact report shown. When
she does share, it goes out through the same scrubbed, disclosure-gated
`feedback send` path `/report-feedback` uses — counts only, never a name, a
title, or note text.

## How to read the numbers

`/health-check` reports counts, rates and ages, never vault objects. Four
thresholds worth knowing before the first read, each pointing at a different
part of the deployment:

- **Daily-note coverage under 80% of working days** → a scheduler or machine
  problem, not a content problem. Work the troubleshooting ladder in
  `session-1b-ea-training.md` before touching anything else — the scheduled
  evening run isn't firing reliably, or isn't firing at all.
- **Meetings without a project linked over 30%** → a routing or seeding
  gap. Either too few projects were seeded in Session 1 for the executive's
  actual portfolio, or the sync routing keeps landing meetings as
  low-confidence. Revisit the seeded project list before assuming the sync
  itself is wrong.
- **Inbox items pending growing week on week** → EA capacity, not a vault
  problem. The queue is only draining if someone works the Triage view
  regularly; a week-over-week climb means the loop needs more of her time
  than it's getting, not a different tool.
- **`no-access` count high** (the sync-recordings run summary's `forbidden`
  and `no-transcript` tallies for Microsoft 365, not falling week to week) →
  the recorder, not Teams, is the primary capture for those meetings. Stop
  chasing tenant permissions and plan the deployment around Plaud for that
  set of meetings instead.

Read the trend, not the single week: one thin week can be a real quiet week.
Two or three in a row against the same threshold is the signal.

## Check-in call agenda

A short standing call each week, EA plus consultant:

1. Walk the numbers from that week's `/health-check`, against the
   thresholds above.
2. Anything the EA flagged through `/report-feedback` since the last call —
   confirm she has heard back on each (see below).
3. Anything the three habits from `session-2-habits.md` aren't sticking to
   yet.
4. One line on what changes, if anything, before the next call.

## Triage of `sb-client` issues

Every report the EA sends through `/report-feedback` or `/health-check`
lands as an issue on that client's own `sb-client-<slug>` repository.
Two rules for hypercare:

- **Reply within two working days.** Even a report that turns out to be a
  one-off or a misunderstanding gets a human reply in that window — silence
  on a client's own feedback repo is what erodes trust in the channel faster
  than any single bad report would.
- **Promote real ones.** A report that names a genuine product gap gets the
  `field-proposal` label and is triaged onto the delaware backlog the same
  way an upstream proposal would be. A one-off or a training gap gets a
  reply and stays closed on the client's repo — it does not need a
  delaware-side issue of its own.

## Exit into steady state

Hypercare ends when the numbers hold for two consecutive weekly checks
against every threshold above, and the EA has stopped needing the
troubleshooting ladder to explain a gap. Say so explicitly on the last
check-in call rather than letting the weekly cadence quietly lapse — the EA
should hear "we're calling this steady state" as a decision, not notice it
by the calls stopping.

## What the care package owes quarterly

Steady state is not silence. Each quarter:

- **A plugin update** — the quarterly care-package release, per
  `plugin-distribution.md`'s release train.
- **`/upgrade-vault`**, run by the consultant, including the template
  refresh it makes possible — never something the EA runs alone; it is a
  consultant-attended operation by design.
- **A brief re-tune** — the same `/setup-my-brain` re-run mode used in
  Session 2, scoped to whichever context file has drifted since the last
  visit.
- **A feedback review** — read back through the quarter's `sb-client` issues
  as a set, not just the ones already triaged, and check whether any pattern
  across them deserves a `field-proposal` of its own even if no single
  report did.
