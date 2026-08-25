# Decision review loop, and retiring `needs-attention` — design

**Issue:** #58 (E2E-6; findings A9/S2, A8/S3, F6/S3, F5/S3) · **Date:** 2026-08-25 ·
**Status:** design approved, implementation pending

## Problem

The 2026-08-24/25 E2E test (plugin 0.4.0 @ `3c91b70`) found the decision review
loop half-built, the wrong Decisions view opening first, one review status that
predates this product, and summary lines a reader cannot decode without opening
the source.

Four findings, one PR: they overlap in the same five files, and F6 cannot land
safely without the clobber-risk signal it removes being relocated in the same
change.

## What A9 actually is

The issue reported "no way to confirm a decision from Obsidian" and prescribed a
two-part fix — a Base column plus a fold path — on the reasoning that the column
alone would be a dead control. Reading the code first says otherwise:

- `Decisions.base`'s **All** view already carries the `reviewed` column. Only the
  **Needs review** queue omits it, so the control exists but not where triage
  happens.
- The tick *is* the write. Obsidian's checkbox sets `reviewed: true` in the
  note's frontmatter; the queue filters `reviewed != true`, so a ticked decision
  leaves the queue immediately.
- Nothing downstream reads any other decision review field. `updatequeue`
  gates on **meetings'** `review_status`; decision `reviewed` is read by
  `decision.list_decisions` for reporting and by that one Base filter.

A fold for meetings exists because `review_status` is a second, pipeline-read
field that a checkbox cannot set — the fold translates human intent into
pipeline state. Decisions have no such field, so a decision fold would have to
invent one to have something to write. Two candidates were considered and
rejected: a `reviewed-on` date stamp (an audit trail nothing reads, plus a
migration) and a full `review_status` enum for decisions (a second state to
keep in sync, gating nothing). Both are YAGNI.

**Decision:** the decision review loop closes at the tick. Part 1 is a Base
column, and the asymmetry with Meetings gets written down in the ontology so
the next reader does not file it again as a bug.

## Decision summary

1. **A9** — add `reviewed` to `Decisions.base`'s **Needs review** view. No code,
   no new field, no fold path for decisions.
2. **A8** — reorder `Decisions.base`'s views so **Needs review** is first;
   Obsidian opens the first view in the file.
3. **F6** — retire `needs-attention` and key the clobber guard on the
   `conflicts-with` edge that already carries exactly that meaning.
4. **F5** — rewrite every summary line in both sync skills that requires source
   access to decode, including the two lines #62 added an hour before this work
   started.

## Part 1 — the decision checkbox

`template/30-projects/Decisions.base`, **Needs review** view: `reviewed` joins
`order:`. Its `properties:` entry is shared by every view in the file, so
renaming its `displayName` from `Reviewed` to `✓ Reviewed` — matching Meetings,
and reading as the control it is — also relabels the column in **All**. That is
the intent. **Active** gains no column: status, not review, is what that view
is for.

The ontology's Decision section gains the rationale: the tick is the whole
confirm act, there is no fold, and that differs from Meeting deliberately.

Acceptance criterion 1 in the issue ("next sync/evening run flips it to reviewed
state on disk") is restated in the PR as **ticking in the queue view drops the
row from the queue**, which is the behaviour that exists and the one a human
tests. Both halves are already or newly pinned: the existing row-set expectation
proves a `reviewed: true` decision is absent from the queue, and a new assertion
proves the control is present to tick.

## Part 2 — triage-first default view

View order becomes **Needs review** → **Active** → **All**, matching Meetings'
Triage-first posture. A new test asserts `views[0]["name"]` for both files
(`"Needs review"`, `"Triage"`) so the posture cannot drift silently — row-set
tests would not catch a reordering.

## Part 3 — retiring `needs-attention`

`needs-attention` is a legacy status from the original busdev vault. It is
load-bearing in exactly one place: `meeting.py` marks the `-v{n}` sibling it
writes rather than overwrite a `confirmed` note, and `reconcile_reviews`
refuses to auto-confirm a tick on such a note. That refusal fired three times
in the E2E run and must survive.

**The signal moves to a field that already means it.** `conflicts-with` is
written only on a `confirmed-target` sibling — the stem-collision path writes
`None` — and `test_fixtures_ontology.py` already asserts that exclusivity. A
new `conflict:` enum field would make two fields encode one fact.

| Touch point | Change |
|---|---|
| `meeting.py` `_resolve_target` | the `confirmed-target` branch returns `needs-review`; the `conflicts-with` edge it already writes is now the signal |
| `syncjob.reconcile_reviews` | guard keys on `conflicts-with` presence instead of the status; result key `needs_attention_ticks` → `conflict_ticks` |
| `ontology.md` | `review_status: [needs-review, confirmed]`; `conflicts-with` prose states that it blocks the fold while present |
| `schema.json` | regenerated by `scripts/compile_ontology.py` |
| `Meetings.base` | the Triage `or:` collapses to one term; `conflicts-with` joins the Triage columns as `⚠ Duplicate of` |
| fixtures | `12-06-26-jordan-1on1-v2.md` → `needs-review`; the `2026-06-12` daily note loses the status name from its prose |
| skills | `sync-recordings` §1 and §6 prose, `evening-sync` Stage 6 watch-items list |
| `migrations/README.md` | the pending structure-version-2 note gains: rewrite `needs-attention` → `needs-review` (those notes already carry `conflicts-with`) |

**Fold order in `reconcile_reviews`.** `reviewed is True` → `review_status ==
"needs-review"` (else skip) → `conflicts-with` present, so report and skip →
otherwise flip to `confirmed`. Checking the status before the edge means a
`confirmed` note with a stale edge is silently skipped rather than reported
every run; a note that cannot fold stays `needs-review` and keeps being
reported, which is accurate — it is unresolved.

**The escape hatch, which `needs-attention` did not really have.** Clearing or
deleting the `conflicts-with` value is the act of saying "I merged or deleted
the duplicate", and the next run folds the tick normally. An emptied value
counts as cleared: a falsy read is treated as resolved, which also means the
property panel is a valid way to do it. This goes in the skill prose, because
under the old design the only way out was hand-editing an enum.

A stem-collision (`-{n}`) sibling carries no `conflicts-with` and so folds like
any ordinary note. That is unchanged, and correct: nothing was at risk.

## Part 4 — plain-speech summary lines

| Now | Becomes |
|---|---|
| `**Reviewed ticks folded:** {N} confirmed` | `**Meetings you ticked as reviewed:** {N} now confirmed` |
| `**Needs attention:** {N} (would have overwritten confirmed notes)` | `**Possible duplicates:** {N} (kept as separate notes — each would have overwritten a confirmed meeting)` |
| `— {M} decisions written (reviewed: false), {K} candidates skipped` | `— {M} decisions captured for review, {K} candidates skipped` |
| `plaud ok \| REFUSED (account-mismatch \| no-account-hint)` | `plaud ok \| REFUSED — signed in as a different account (account-mismatch) \| REFUSED — no account bound to this vault yet (no-account-hint)` |
| `calendar REFUSED (account-mismatch \| no-account-hint)` | same treatment, in `**Tomorrow's note:**` |

The last two lines arrived with #62 and are in scope because F5's acceptance
criterion is stated over summary lines, not over one line: `no-account-hint` is
a result code from `config.verify_account`, unreadable without the source. The
code stays in parentheses as a trace for whoever greps for it; the plain
sentence leads.

`reviewed: false` in a summary is the same failure in a different shape — a
frontmatter value quoted at a human — so it goes too.

## Testing

- `test_bases_views.py` — Decisions row sets are unchanged (the new column
  changes no filter); add the default-view assertions and a column assertion
  that `reviewed` is in the **Needs review** view's `order:`.
- `test_basesim.py` — `test_or_inside_and_matches_meetings_triage_shape` mirrors
  a shipped filter that no longer has an `or`. Keep the evaluator coverage
  (`or` is a real Bases feature a future view may use), rename it, and retarget
  its corpus off the retired enum value.
- `test_fixtures_ontology.py` — the `conflicts-with` invariant becomes: the note
  is not `confirmed`, and the edge resolves to an existing meeting note.
- `test_vaultlib_meeting.py` — the `confirmed-target` case expects
  `needs-review` plus the edge, not `needs-attention`.
- `test_vaultlib_syncjob.py` — a ticked note carrying `conflicts-with` is not
  folded and is reported under `conflict_ticks`; a ticked note whose edge was
  cleared *is* folded (the escape hatch, pinned).
- `python scripts/lint_plugin.py`, `python scripts/validate_template.py`,
  `python -m pytest scripts/tests -q` all green, and `compile_ontology.py`'s
  regeneration test proves `schema.json` is not stale.

## Out of scope

No `reviewed-on` field, no decision `review_status`, no migration *runner*
(the format is still designed together with `/upgrade-vault`). No change to
`archived`, and no change to which meetings drive metrics.

## Housekeeping

Plugin version 0.5.0 → 0.5.1. One `CHANGELOG.md` line under `Unreleased`: the
client-visible facts are the decision queue becoming actionable and opening
first, duplicate captures being labelled as duplicates instead of "needs
attention", and summaries that read as sentences.
