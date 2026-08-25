# Catch-up Visibility and Recap Integrity — Design

**Date:** 2026-08-25 · **Issues:** #56, #57 · **Extends:**
`2026-08-23-daily-loop-port-design.md` (decisions 1–14 there; this spec
continues that numbering at 15) · **Builds on:**
`2026-08-25-deployment-config-design.md` (merged as #62 — `config.json`
now supplies the timezone and executive slug that stage 1 used to read
from prose, and its rule "machine decisions come from `config read`" is
Rule 9 of the skill this spec edits)

Two findings from the 2026-08-24/25 end-to-end test of plugin 0.4.0 at
`3c91b70`, fixed together because they are the same defect seen twice: the
evening run makes a consequential choice and does not say so.

- **#56 (G1, G7-catch-up).** A 67-day recap window rendered
  indistinguishable from a normal daily run. `dates plan` widens the window
  correctly — that half works and stays — but nothing reports *that* it
  widened, nothing bounds it, and the decision not to back-fill the skipped
  days was never written down anywhere.
- **#57 (H2, G7-quality).** Re-running `/evening-sync` for the same day
  regenerates the recap with model variance: a real takeaway
  ("procurement now wants a total-cost-of-ownership comparison added")
  degraded to plumbing ("synced from Teams transcript"), and *Meridian
  Freight Holdings* came back as *Meridian **Industrial** Holdings*. A
  re-run can silently overwrite a recap the exec already read with a worse,
  subtly wrong one.

What the same test proved *works* and must not regress: region
byte-preservation and jotting survival (H1/H3), free-text-to-slug resolution
in the harvest path (`Taylor` → `[[taylor-brooks]]`), and the self-widening
window itself (decision 9). The capability to look a name up already exists;
it is simply not mandated where the prose is composed.

## Decisions

15. **The gap is a reported fact, not an inference — and the fact is read
    off disk.** `dates plan` returns `business_days_missed`: the number of
    business days `D` in `[recap_from, recap_to)` for which **no** daily note
    dated `next_business_day(D)` exists in `60-daily-notes/`. A run on
    business day `D` writes the note for `next_business_day(D)`, so that note
    existing is exactly the proof that the run happened. Existence is checked
    against every ISO-named note on disk, **future-dated ones included** — a
    future-dated note is not "the last daily note" for the window
    (`recap_from` deliberately ignores it), but it is precisely the proof
    this count needs.

    The first version of this decision counted business days in the window
    outright, justified by "a note dated `recap_from` on disk proves the run
    on the evening before it completed." That reasoning fails whenever today
    is not a business day: on a Saturday the newest note on or before today
    is Friday's, which proves *Thursday's* run, while the proof of Friday's
    run is Monday's note — the one the window logic excludes for being
    future-dated. A healthy vault therefore reported a missed run on every
    Saturday and every Sunday, two nights in seven for an unattended
    schedule, and the banner said so in the note. The corrected count is 0
    for a healthy vault on any day of the week.

    No holiday calendar ships: a public holiday reads as a missed day, which
    is literally true ("no run happened") and is the honest reading rather
    than a silent one.

16. **Skipped days are never back-filled, and the note says so.** One
    catch-up note covers the whole window; three missed days do not become
    three notes. Fabricating past daily notes would invent days that have no
    jottings, and the daily note is the archive of a day that was actually
    lived. This was already the behaviour; decision 16 is that it is now
    *stated* — in the note the exec reads, not only in a skill file.

17. **Above a bound, breadth yields to usefulness.** A recap window wider
    than `catchup_threshold` business days (default 5) is detailed only from
    `recap_detail_from` onward; earlier business days are counted, not
    recapped. Handing a model two months of meetings for one summary
    produces mush, and mush in the exec's brief is worse than an honest
    count. Interactive mode may ask once to override; unattended mode caps
    and flags for human review, never composes the mega-recap.

18. **An unchanged input set leaves the recap alone.** `daily-note write`
    stamps a content fingerprint of the recap's *inputs* onto the recap
    region's begin marker. A later run over an unchanged input set skips the
    recap region entirely — bytes untouched — and still merges prep. LLM
    variance can no longer degrade a recap the exec has already read. The
    fingerprint lives on the marker line, which is already CLI-owned, so
    decision 10 (never touch a byte outside the markers) and decision 11
    (no sidecar JSON) both hold unchanged.

19. **A name in a machine region is looked up or it is not written.** Every
    `[[wikilink]]` in payload content must resolve to a vault object, or the
    write fails. Where the link carries an alias and the target is an
    *identity* object — entity, person, project — the alias must equal that
    object's `entity-name` / `person-name` / `project-name` exactly. This is
    the determinism principle (frontmatter is never model-authored) extended
    to the one place prose makes a factual claim: what something is called.
    Event objects — meeting, decision, daily note — must resolve but their
    aliases are free prose, because "Friday's Acme sync" is a reference, not
    a name claim.

## D1 — `dates plan`: the gap becomes a fact

`dates.business_days(start, end) -> int` counts Mon–Fri in `[start, end)`.
Calendar arithmetic only — it measures the *width* of a span, which is what
`business_days_not_detailed` and the banner's detail line need.

`dates.missed_runs(root, recap_from, recap_to) -> int` is the count of runs
that did not happen, per decision 15: business days `D` in
`[recap_from, recap_to)` with no note dated `next_business_day(D)` on disk.
Module-level and public beside `business_days`, because `dates.plan` and
`dailynote` both need it and a second implementation of the same rule is how
the banner and the plan block come to disagree. `dates.next_business_day(day)`
is factored out of `plan` for the same reason.

`dates.plan(root, today, *, timezone, utc_offset, catchup_threshold=5)`
keeps every existing key and adds five:

| Key | Type | Meaning |
|---|---|---|
| `business_days_missed` | int | `missed_runs(root, recap_from, recap_to)` — business days in the window whose run left no note behind |
| `is_catchup` | bool | `business_days_missed > 0` |
| `catchup_threshold` | int | the bound in force (CLI default 5) |
| `over_threshold` | bool | `business_days_missed > catchup_threshold` |
| `recap_detail_from` | ISO date | where detailed recapping starts; `== recap_from` unless `over_threshold` |
| `business_days_not_detailed` | int | business days in `[recap_from, recap_detail_from)`; 0 unless `over_threshold` |

`recap_detail_from` when `over_threshold`: walk back from `recap_to`,
counting business days inclusively, until `max(catchup_threshold, 1)` of
them are counted; clamp to `recap_from`. A `recap_to` that falls on a
weekend simply contributes nothing to the count. Threshold 0 is legal and
means "detail only the final business day" — the `max(…, 1)` keeps the
window from collapsing to nothing.

The two derived keys exist so the skill performs **zero** arithmetic: it
copies integers and dates into prose. That is the same reason `dates plan`
exists at all.

Worked example — the E2E case, `--today 2026-08-21` with the last note
dated `2026-06-15`:

```json
{
  "today": "2026-08-21", "today_day_name": "Friday",
  "next_business_day": "2026-08-24", "next_day_name": "Monday",
  "recap_from": "2026-06-15", "recap_to": "2026-08-21",
  "business_days_missed": 49,
  "is_catchup": true,
  "catchup_threshold": 5,
  "over_threshold": true,
  "recap_detail_from": "2026-08-17",
  "business_days_not_detailed": 45
}
```

CLI: `dates plan` gains `--catchup-threshold` (int, default 5). A negative
value is a `DatesError`.

The threshold stays a CLI default rather than becoming a `config.json` key.
Rule 9 ("machine decisions come from `config read`") targets decisions a
skill would otherwise read out of *prose*; a defaulted CLI flag is already
deterministic, and `config.py` validates a closed key set — so adding a key
costs a `config-version` bump, a template change, and a `/setup-my-brain`
writer that does not exist yet. Parked, with the trigger written down: the
first engagement that actually wants a different bound.

## D2 — the catch-up banner is rendered, not remembered

`daily-note write`'s payload gains one optional object:

```json
"recap_window": {"from": "2026-06-15", "to": "2026-08-21",
                 "detailed_from": "2026-08-17"}
```

`from` and `to` are `recap_from` / `recap_to` copied verbatim from
`dates plan`. `detailed_from` is optional and is `recap_detail_from` — the
caller passes it only when it actually capped, so the note never claims a
cap that did not happen (interactive mode may have been told to go full).

Validation: `from` and `to` are required together, both ISO, `from <= to`,
and **`to` strictly before the note's own `date`** — true in every
legitimate call (`to` is today, the note is the next business day) and it
closes the self-reference hazard in D3. `detailed_from`, when present, must
be within `[from, to]`.

When `dates.missed_runs(root, from, to) > 0` — the decision-15 count, read
off disk, not the width of the window — the CLI prepends to the recap region
interior, above the model's prose, separated by one blank line:

```markdown
> [!warning] Catch-up note
> Covers 2026-06-15 → 2026-08-21 — 49 business days without an evening run. Skipped days are not back-filled: this is the only note for that window.
> Detailed from 2026-08-17; the 45 earlier business days are counted, not recapped in detail.
```

The third line appears only when `detailed_from` is present and later than
`from`. Its count is `business_days(from, detailed_from)` — the *width* of
the span that was not detailed, which is a length rather than a count of
failures, so `business_days` is right there. When 0 runs were missed — every
healthy run, weekend runs included — there is no banner and the rendered
bytes are identical to today's output.

`recap_window` is optional so that existing callers keep working. The
consequence is that a skill which forgets it silently loses both the banner
and the D3 guard, which is why a skill-contract test asserts the SKILL.md
payload example carries it.

## D3 — recap idempotence: `inputs=` on the begin marker

**Marker grammar.** Begin/end markers may carry space-separated
`key=value` attributes:

```markdown
<!-- evening-sync:recap:begin inputs=a1b2c3d4e5f6a7b8 -->
```

Only `inputs` on `recap:begin` is known. Any other attribute, or an
attribute anywhere else, is a `DailyNoteError` naming the attribute and
saying the note may have been written by a newer plugin version — never a
silent ignore. `_clean_region_text` continues to reject `evening-sync:` in
payload content, so a payload cannot forge a marker.

**The fingerprint** is computed by the CLI from the vault. It is never
supplied by the caller, because a model-supplied hash is a model-supplied
fact. Inputs, given `recap_window` `from`..`to`:

- `20-meetings/<stem>.md` where the stem's date falls in `[from, to]`.
  **Meeting stems are `DD-MM-YY-title`, not ISO** — `meeting._date_prefix`
  renders `date` through `%d-%m-%y`. So this needs the inverse:
  `meeting.date_from_stem(stem) -> date | None`, parsing `stem[:8]` with
  `%d-%m-%y` and returning None for anything that does not parse (a
  hand-named note is simply not in the window). It lands directly beside
  `_date_prefix`, because a round-trip pair that drifts apart is the exact
  failure `plugin/CLAUDE.md` already documents twice (table-cell escaping,
  bare wikilink stems).
- `60-daily-notes/<date>.md` where `date` is in `[from, to]` — this is the
  jottings input (the note being written is dated after `to`, so it can
  never hash itself). Daily-note stems *are* ISO.
- `30-projects/*/decisions/<stem>.md` where `stem[:10]` is an ISO date in
  `[from, to]` — decision stems *are* ISO-prefixed
  (`2026-06-12-phase-1-site-nomination-deferred`), so a stage-4 retry that
  finally wrote a decision is not skipped as "unchanged"

Project indexes are deliberately **not** inputs, even though D5's project
pulse reads from them: stage 4 touches `last-updated` on every project it
visits, so hashing them would churn the digest on nearly every run and the
guard would never fire. The stamp therefore means "meetings, jottings and
decisions are unchanged", not "nothing anywhere changed" — recorded in
`plugin/CLAUDE.md` so the next reader of the code finds it.

Canonical form, then SHA-256, then the first 16 hex characters (the
convention `syncjob.content_id` already uses):

```
banner\t{sha256-hex of the rendered banner, or of "" when there is none}
{relpath}\t{sha256-hex}          # one line per input path, sorted by relpath
```

The first line is the **rendered banner**, not the raw `from`/`to` bounds:
the digest must cover exactly what determines the region's machine-generated
content, which is the banner plus the input files. Hashing the bounds made a
weekend run over an untouched vault look changed — Saturday's window is
`08-21..08-22` where Friday's was `08-21..08-21` — and regenerate a recap the
exec had already read, which is the defect the fingerprint exists to prevent.
It also left `detailed_from` outside the digest even though it changes the
rendered banner, so a run that moved only its detail bound kept a stamp
describing a banner the note no longer carried. Hashing the banner closes
both.

Dropping the bounds is safe: if they move enough to change what the recap is
built from, the input *file set* moves with them and the digest follows. If
they move without changing either the banner or the file set, the rendered
region is byte-identical and skipping it is the correct answer.

**Write behaviour.**

| Note state | Payload | Recap region |
|---|---|---|
| absent | any | rendered; stamped when `recap_window` present |
| exists, marker `inputs=X` | `recap_window` present, digest `== X` | **skipped** — interior and marker byte-identical; prep regions still merge |
| exists, marker `inputs=X` | digest `!= X` | interior replaced, marker restamped |
| exists, no attribute | `recap_window` present | interior replaced, marker stamped |
| exists, any | no `recap_window` | interior replaced, any existing stamp **stripped** |

Stripping on the no-window path is deliberate: leaving a stamp above a
recap whose inputs nobody verified would make the marker lie, and a lying
stamp causes a *skip* — the one failure mode that silently does nothing.

Existing notes in the field carry no attribute, so they regenerate once and
are stamped from then on. No migration ships.

**Result envelope.** `daily-note write` adds `recap_skipped` (bool),
`recap_inputs` (the 16-hex digest or null) and `warnings` (list of strings,
usually empty). `regions_replaced` no longer counts a skipped recap.
`daily-note read` adds `recap_inputs` so a test — or a human debugging a
stuck recap — can see the stamp without parsing markers by hand.

## D4 — names by lookup, enforced on every region

The check runs over every piece of content the payload carries: `recap`,
each meeting's `prep`, and `meetings_note`. One rule with no exceptions
beats a rule plus a list of places it does not apply — and prep lines name
entities exactly as recap prose does.

Wikilinks are matched in both plain and embed form (`[[t]]`, `![[t]]`), with
an optional `#heading` (stripped before resolution) and an optional
`|alias`. Resolution, in this order:

| Kind | Path | Display name | Alias rule |
|---|---|---|---|
| entity | `40-entities/<t>/dossier.md` | `entity-name` | must match exactly |
| person | `50-people/<t>.md` | `person-name` | must match exactly |
| project | `30-projects/<t>/index.md` | `project-name` | must match exactly |
| meeting | `20-meetings/<t>.md` | — | free prose |
| decision | `30-projects/*/decisions/<t>.md` | — | free prose |
| daily note | `60-daily-notes/<t>.md` | — | free prose |

Identity kinds are checked first, so a slug that is both a person note and a
project directory resolves as the person — documented, deterministic, and in
practice a naming collision the vault should not have.

**Unresolvable target** → `DailyNoteError`:

> `recap: [[meridian-industrial-holdings]] resolves to no vault object — link only to objects that exist (create one with /update-entity or /new-project first), or leave the name out.`

**Alias mismatch on an identity object** → `DailyNoteError` naming the
truth, so the caller can fix it in one retry without another lookup:

> `recap: [[meridian-freight-holdings|Meridian Industrial Holdings]] — that entity is called "Meridian Freight Holdings". Display names come from the vault.`

**Unparseable frontmatter on a resolved target** → the link resolves, the
alias check is skipped, and a line lands in the result's `warnings`. One
mangled dossier must not cost the exec their daily note; the existing
`daily-note read` precedent (unparseable frontmatter is a warning) is the
same judgement.

What this cannot catch: a name written as plain prose with no wikilink.
Nothing deterministic can. Hence the skill mandates the wikilink form for
every entity, person, and project mention in a machine region, and a
skill-contract test asserts that mandate is present.

## D5 — recap composition: a required shape

Stage 6 currently *hints* at themes. It gets a shape, in this order, and
the shape is what the skill checks its own output against:

1. `> [!info] At a glance` — N meetings · entities touched · themes, one line.
2. **Themes** — when the window holds ≥2 meetings, 2–4 bullets, each a
   pattern *across* meetings, each naming the meetings or entities it draws
   on. With one meeting: what it means, not that it happened.
3. **Project pulse** — one line per project touched: where it stands (from
   the project's `Now` callout) and what moved this window.
4. **Decisions logged** — from stage 4, wikilinked.
5. **Watch** — conflicts, needs-attention flags, `SELF-CHECK` warnings.
6. **Carried forward** — jottings from the harvest worth carrying.

Stated prohibition: *a flat list of meetings is not a recap.* Open items
stay on projects and are linked, never duplicated (decision 14).

Above the bound, the two modes diverge exactly once:

- **Interactive** asks a single question at stage 1 — detail the last
  `catchup_threshold` business days (default), or the whole window. There is
  precedent for exactly one prompt in this pipeline (the sync stage), and
  stage 1 is before any work is done, so a slow answer costs nothing.
- **Unattended** always caps, and puts the catch-up window in the summary's
  Warnings block. Rule 1 of unattended mode is that it never asks; capping
  is the "prefer under-doing to wrong-doing" branch of rule 3.

Stage 7's summary line gains the catch-up state, so a scheduled run's
transcript shows it:

```
**Recap window:** 2026-06-15 → 2026-08-21 (catch-up: 49 business days missed; detailed from 2026-08-17) | 2026-08-21 (current)
**Recap:** regenerated | unchanged since the last run (inputs identical)
```

## Contracts changed

| Contract | Change | Compatibility |
|---|---|---|
| `dates plan` result | +6 keys | additive |
| `dates plan` CLI | `--catchup-threshold` | additive, defaulted |
| `daily-note write` payload | `recap_window` object | additive, optional |
| `daily-note write` result | `recap_skipped`, `recap_inputs`, `warnings` | additive |
| `daily-note write` validation | wikilinks resolve; identity aliases match | **breaking for a payload that names things that do not exist** — which is the point |
| `daily-note read` result | `recap_inputs` | additive |
| region marker grammar | optional `key=value` attributes | notes without attributes parse unchanged |
| `meeting` module | `date_from_stem` becomes public | additive |

Version: **0.5.0 → 0.6.0** (#62 took 0.5.0). New behaviour plus one
intentionally breaking validation rule.

## Documentation

- `plugin/CLAUDE.md` — the `inputs=` attribute and the skip rule inside the
  existing *Daily-note regions* section; a new subsection for the
  resolve-or-fail wikilink contract, sitting with the pipe-escaping and
  bare-stem rules it belongs beside (all three are "what crosses the CLI
  boundary" lessons).
- `plugin/skills/evening-sync/SKILL.md` — stages 1, 6, 7, the unattended
  section, and **Rules 10 and 11** (#62 took the list to 9). Stage 1's
  edits build on its post-#62 form: `config read` first, then
  `dates plan --timezone <config.timezone>`. No new text may name
  `identity.md` or `tools-and-systems.md` — a contract test from #62
  forbids it.
- `CHANGELOG.md` under `Unreleased` — two client-visible lines: the note now
  tells you when it is catching up, and a re-run no longer rewrites a recap
  you already read.

## Verification

Local, matching CI: `lint_plugin.py` · `validate_template.py` ·
`pytest scripts/tests -q`.

New tests in `test_vaultlib_dates.py`:

- `business_days` over a normal week, across a weekend, an empty interval,
  and a reversed interval (0, not negative)
- `business_days_missed`: 0 on a healthy run · 1 for a skipped Friday
  followed by a Monday run · the weekend-spanning gap · the 2-month E2E case
  pinned at 49 · fresh vault with no notes at all (0, not a catch-up)
- `over_threshold`, `recap_detail_from` and `business_days_not_detailed` at
  the boundary (exactly `catchup_threshold` missed → not over), with a
  custom `--catchup-threshold`, with threshold 0, and with `recap_to` on a
  weekend
- CLI envelope carries the new keys

New tests in `test_vaultlib_dailynote.py`:

- **The H2 repro:** write with `recap_window`, then write again with a
  different `recap` string and the same inputs → the file is byte-identical
  and `recap_skipped` is true
- touch a meeting note inside the window → the digest changes and the recap
  is replaced; touch one outside the window → it does not
- append a jotting to a daily note in the window → digest changes
- write a decision note inside the window → digest changes
- prep regions still merge on a run whose recap is skipped
- no `recap_window` → recap always replaced and an existing stamp is stripped
- an unknown marker attribute is refused, naming it
- banner: absent at 0 missed days (byte-comparison against the current
  rendering) · present with the window and count · the `detailed_from` line
  appears only when it should · singular/plural forms
- `recap_window.to` on or after the note's `date` is refused
- link validation: unresolvable target refused · alias mismatch on entity,
  person and project refused with the real name in the message · matching
  alias accepted · bare link accepted · `#heading` stripped before
  resolution · free alias on a meeting link accepted · unparseable dossier
  frontmatter yields a warning and a successful write · a link inside a
  `prep` and inside `meetings_note` is checked too
- `daily-note read` returns `recap_inputs`, and null for an unstamped note

Preconditions verified against the fixture vault before writing any of
this, so D4 is known not to break the two fixture-conformance tests: every
wikilink in `fixtures/demo-vault/60-daily-notes/*.md` and in
`FRESH_FIXTURE_PAYLOAD` resolves (entities, `DD-MM-YY` meeting stems, ISO
decision stems), and not one carries an alias. The fixture notes stay
*unstamped* — they legitimately represent the "exists, no attribute" row of
D3's table, and stamping them would pin a digest that changes every time a
fixture changes.

New tests in `test_skill_contracts.py`:

- `/evening-sync` states the no-back-fill rule and the catch-up threshold
- its stage-6 payload example carries `recap_window` (the guard against
  silently losing the idempotence guard)
- it mandates wikilinks for entity/person/project mentions
- it states unattended catch-up behaviour (caps, never asks, flags)

Hand-test, in the dated local vault (`test-vaults/`, made with
`make_test_vault.py --with-plugins`, never a worktree):

1. `/evening-sync --today 2026-08-21` against the demo fixtures pinned at
   2026-06-15 → read the catch-up banner in Obsidian, confirm it names the
   window and the no-back-fill rule.
2. Re-run the same command → the recap region is byte-identical; the
   summary says the inputs were unchanged.
3. Jot into today's note by hand, re-run → the recap regenerates and the
   jotting survives.
4. A normal run (no gap) → no banner, and the recap reads as themes and
   project pulse rather than a meeting list.

## Scope

One PR, closing **#56** and **#57**, version **0.5.0 → 0.6.0**. They share
`dailynote.py`, the same payload object, and the same skill stage; splitting
them would mean two passes over the same 40 lines and a half-written
`recap_window` contract in between.

## Parked

- **A holiday calendar.** `business_days_missed` counts a public holiday as
  missed. Fixing it needs a per-deployment holiday source, which is
  configuration work, not this fix.
- **`catchup-threshold` as a `config.json` key.** The trigger is the first
  engagement that wants a bound other than 5. It arrives with a
  `config-version` bump (the validator's key set is closed), a template
  default, and `/setup-my-brain` (#3) as its writer — none of which exists
  to hang it on today.
- **Per-day back-fill.** Decision 16 says one catch-up note, deliberately.
  If an engagement ever wants real per-day notes, the lever is repeated
  `--today` runs, and a `/backfill` skill would be its own design.
- **Alias verification for event objects.** A meeting link's alias is free
  prose today. Checking it against the meeting's `title` would break
  readable references for no observed defect.
- **Plain-prose name validation.** Not deterministically possible. The skill
  mandate plus the resolve-or-fail rule is the whole defence.
- **Forcing a recap regeneration.** No `force_recap` flag ships: a changed
  input set is the trigger, and deleting the note is the escape hatch. If a
  plugin upgrade ever needs to invalidate every stamp, the fingerprint
  gains a version prefix then.
