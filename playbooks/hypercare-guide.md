# Hypercare guide — weeks 2–4

delaware-side material; never ships. The three weeks after Session 2, before
the engagement settles into steady state. The vault owner runs the
machinery; the consultant reads what they share and stays reachable.

## Weekly `/health-check`

The vault owner runs `/health-check` weekly through weeks 2–4 — the cadence
`session-2-habits.md` sets up. It is their call whether to share the numbers
with delaware each week; `/health-check` never sends anything without an
explicit yes to the exact report shown. When they do share, it goes out
through the same scrubbed, disclosure-gated `feedback send` path
`/report-feedback` uses — counts only, never a name, a title, or note text.

## How to read the numbers

`/health-check` reports counts, rates and ages, never vault objects. Three
thresholds worth knowing before the first read, each pointing at a different
part of the deployment:

- **Daily-note coverage under 80% of working days** → a scheduler or machine
  problem, not a content problem. Before touching anything else, check
  three things in order: was the machine awake with Claude open at the
  scheduled hour; is the routine actually running on the surface you think
  it is (a task created in Cowork's VM does not exist in Claude Code, or
  vice versa); and does `config read --vault <vault>` return `owner` and
  `timezone` — a missing one makes the scheduled run refuse to fire
  deterministically. `99-workflow-config/logs/routine-runs.log` carries one
  line per run either way, so a missing line points at the first check and
  a line ending in an alert points at the second or third.
- **Meetings without a project linked over 30%** → a routing or seeding
  gap. Either too few projects were seeded in Session 1 for the vault
  owner's actual portfolio, or the sync routing keeps landing meetings as
  low-confidence. Revisit the seeded project list before assuming the sync
  itself is wrong.
- **Inbox items pending growing week on week** → the vault owner's own
  time, not a vault problem. The queue is only draining if someone works
  the Triage view regularly; a week-over-week climb means the loop needs
  more of their time than it's getting, not a different tool.

Read the trend, not the single week: one thin week can be a real quiet week.
Two or three in a row against the same threshold is the signal.

## One more signal, off the sync-recordings run summary

This one is not in `/health-check` at all, so read it from a different
place: `/sync-recordings`' own run summary carries two distinct M365
signals — do not conflate them. **External meetings** lists occurrences
organised outside `adapters.m365.home_domains` — hosted in another
organisation's tenant, so this account can never read their transcripts.
That is expected and needs no fix; it is recorder territory by design.
The **no-access** tally is different: a 403 on a meeting whose organizer
*is* in the client's own organisation, which means either that domain is
missing from `home_domains` or the tenant's Microsoft Graph
transcript-access setting is off. Because both counts are facts about one
run, not a persisted ledger, capture them as the run happens — the vault
owner notes them, week by week, alongside their `/health-check` reading,
rather than expecting to look it up later.

If the external list stays non-zero for the same meetings, that is simply
their permanent shape — plan the deployment around Plaud for that set
instead of chasing tenant permissions that were never going to grant
access. If the no-access tally stays non-zero, fix the actual cause first
(add the missing domain, or have IT flip the tenant setting), then
`sync m365-forget --outcome no-access` forces the next sync to re-check
rather than leaving them parked on the old answer.

## Check-in call agenda

A short standing call each week, vault owner plus consultant:

1. Walk the numbers from that week's `/health-check` against the three
   thresholds above, plus whatever the vault owner captured off that
   week's `/sync-recordings` run summaries for the no-access signal.
2. Anything the vault owner flagged through `/report-feedback` since the
   last call — confirm they have heard back on each (see below).
3. Anything the three habits from `session-2-habits.md` aren't sticking to
   yet.
4. One line on what changes, if anything, before the next call.

## Triage of `sb-client` issues

Every report the vault owner sends through `/report-feedback` or
`/health-check` lands as an issue on that client's own `sb-client-<slug>`
repository.
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
against every threshold above, the no-access signal has settled or has a
named plan (recorder-as-primary, or an access grant already requested), and
the vault owner has stopped needing the troubleshooting steps above to
explain a gap. Say so explicitly on the last check-in call rather than
letting the weekly cadence quietly lapse — the vault owner should hear
"we're calling this steady state" as a decision, not notice it by the calls
stopping.

## What the care package owes quarterly

Steady state is not silence. Each quarter:

- **A plugin update** — the quarterly care-package release, per
  `plugin-distribution.md`'s release train.
- **`/upgrade-vault`**, run by the consultant, including the template
  refresh it makes possible — never something the vault owner runs alone;
  it is a consultant-attended operation by design.
- **A brief re-tune** — the same `/setup-my-brain` re-run mode used in
  Session 2, scoped to whichever context file has drifted since the last
  visit.
- **A feedback review** — read back through the quarter's `sb-client` issues
  as a set, not just the ones already triaged, and check whether any pattern
  across them deserves a `field-proposal` of its own even if no single
  report did.
