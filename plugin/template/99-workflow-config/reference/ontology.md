---
tags: [meta, reference, ontology]
---

# Vault Ontology — Authoritative Object Model

> **Single source of truth for the vault's object types, fields, and
> controlled vocabularies.** Edit here; never let the schema live in prose
> elsewhere.

Seven object types: **Meeting · Project · Person · Decision · Entity · Daily note · Message log**.
Relationships live in YAML frontmatter (wikilinks / slug joins), not folder
hierarchy. Curation happens in Bases, not by browsing folders.

## How to read this file

Each object type below carries a fenced `yaml` block with an `object:` key.
That block is the **normative schema** — required fields, optional fields,
enums, controlled vocabularies. Machines load these blocks directly: the
repo's conformance tests validate fixture frontmatter against them, and
skills consult them before writing any object frontmatter. The prose around
each block carries the rationale and conventions the YAML cannot. Editing a
block IS editing the ontology — there is no second copy to keep in sync.

**`type` is not a single axis across objects — decided, not an oversight
(#44).** `decision.type` is pinned to `[decision]` and `entity.type` /
`project.type` are now pinned to `[entity]` / `[project]`: on those three
objects `type` **is** the object discriminator. `meeting.type` is a different
axis entirely — the meeting *kind* (`steerco`, `workshop`, `1:1`, …), never
the discriminator — and `person` carries no `type` field at all. The
canonical way to map a note to its object type is **folder shape**, not the
`type` field: see `scripts/dqlrefs.py`'s `_PATH_TYPES` and
`folder_object_type()` for the reference implementation. Anything that needs
to resolve "what object is this note" must use path shape, not `type`.

## 1. Object catalog

### Meeting — `20-meetings/{DD-MM-YY-slug}.md` · Base: `Meetings.base`

```yaml
object: meeting
required: [date, type, calendar-subject, calendar_match, attendees, projects,
           review_status, recording-duration, source, processed]
optional: [attendee-emails, organizer, location, recurring, start-time,
           source-recording-id, source-filename, conflicts-with,
           confidence, confidence-reasons, reviewed, archived, entities,
           confirmed-at]
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update, note]
  review_status: [needs-review, confirmed]
  source: [teams, recorder, manual, email]
  confidence: [high, medium, low]
confidence_reasons:
  calendar: [calendar-match-high, calendar-match-medium, calendar-match-low,
             no-calendar-match, calendar-tool-unavailable,
             calendar-not-applicable]
  project-link: [entity-domain-match, calendar-subject-match,
                 content-keyword-match, no-project-match]
  attendees: [all-attendees-known]
```

- `date` is an ISO datetime (e.g. `2026-05-05T14:37`).
- `attendee-emails`, `organizer`, `location`, `recurring`, `start-time`
  appear on calendar-matched meetings only. `source-recording-id`,
  `source-filename` are recorder provenance.
- **Triage checkboxes (booleans, edited in Meetings.base):** `reviewed` —
  one-click confirm; `archived` — hides the row from triage views (noise
  disposal; the file stays).
- Write-once; only triage fields (`attendees`, `projects`, `review_status`,
  `reviewed`, `archived`) are edited later — plus `confirmed-at`, which
  `sync reconcile-reviews` stamps (ISO to the minute) on the note when it
  folds a tick into `review_status: confirmed`. The evening run's update
  queue compares a project's `state-updated` against the later of a
  meeting's `date` and this stamp, so a meeting ticked *after* its project's
  last state update still queues however old the meeting is. Notes confirmed
  before the stamp existed carry no field and compare on `date` alone.
- **`projects[]` and `attendees[]` hold bare slugs, never wikilinks.** A
  hand-typed `[[slug]]` dangles (the project is a folder, so the link
  resolves to nothing and clicking it spawns a stray note in the vault
  root) and blocks the entity derivation below. The evening fold's
  `sync rederive-entities` unwraps a wikilink whose target resolves and
  repairs the note; one that still doesn't resolve is reported, not fixed.
  Click-through in `Meetings.base` is the read-only `↗ Project` formula
  column, not the editable `projects` cells.
- `entities[]` holds entity slugs: the organizations the meeting was
  **about** — not only the ones in the room. An internal 1:1 reviewing a
  client account carries that client, the same way the daily note's prep
  heading labels it `### {HH:MM} — 1:1 — {Name} · [[entity]]`. "About" rather
  than "with" is deliberate: the account 1:1s are part of the account's
  record, a `business-unit` entity has no external meetings at all, and every
  meeting *with* an entity is also about it, so the narrower reading only
  loses rows. Omitted entirely when no entity is in scope.
- **Ownership: machine-derived once a project is assigned, hand-set only on
  a project-less meeting.** Whenever `projects[]` is non-empty, `entities[]`
  is computed — never typed — from each project's `entity:` field (deduped
  across every project the meeting carries) at write time; passing `entities`
  yourself alongside a non-empty `projects[]` is refused. A project-less
  meeting that is still about an entity (an intro call with a prospect that
  has no project yet) is the one case you set `entities[]` by hand.
- **Why the field exists at all**, given that `projects[]` already implies it
  (each project names its `entity`): Dataview cannot follow that second hop.
  A query filtering `20-meetings` sees only what the meeting notes themselves
  say, and a note naming its projects does not name the organizations behind
  them. With `entities[]`, an entity dossier joins directly —
  `WHERE econtains(entities, this.slug)`, the same shape a project index
  already uses for `projects`. A meeting with an empty `projects[]` still
  reaches its dossier this way, provided `entities[]` was set by hand.
- **Drift and its repair.** A project reassigned by hand during triage
  *after* the meeting was written no longer updates `entities[]` on its
  own — the evening sync's fold stage re-derives `entities[]` from
  `projects[]` on every meeting each run and repairs any note left stale, so
  drift is transient rather than permanent, but it is not instantaneous.
- The `1:1` type value must stay **quoted** in frontmatter and in the block
  above — unquoted YAML parses `1:1` as the integer 61.
- `source` is the capture channel: `teams` (platform transcript), `recorder`
  (device capture), `manual` (typed notes), `email` (an emailed summary or
  transcript). `recording-duration` is `0` when nothing was recorded
  (`manual`, `email`).
- **`type: note` is a capture that is not a record of an interaction** —
  forwarded correspondence, a voice memo, pasted context. It lives here
  because `20-meetings/` is the vault's capture ledger, not because an email
  is a meeting. A `note` carries `calendar_match: false`,
  `recording-duration: 0`, and **may carry empty `attendees`** — it is the
  one type for which an empty attendee list is valid. Its `calendar-subject`
  is a descriptive subject drawn from the item itself — a forwarded email's
  own `Subject:` line, a voice memo's short title — and is never empty; a
  required field with an empty value fails schema validation, and
  `calendar_match: false` alone records that no calendar corroborated it.
  `type` and `source` are orthogonal: a forwarded email is `type: note` +
  `source: email`, while an emailed *meeting summary* is `type: meeting` +
  `source: email`.
- `calendar-not-applicable` means the calendar was never consulted **because
  the item is not a meeting**. It is a third distinct fact alongside
  `no-calendar-match` (searched, found nothing) and
  `calendar-tool-unavailable` (could not search). Never collapse the three.
  A `note` with empty `attendees` still carries `all-attendees-known`: the
  attendees vocabulary stays closed, and with nobody named there is nobody
  unknown.
- `source-recording-id` is the sync ledger: a namespaced id
  (`plaud:{id}`, `m365:{id}`, `inbox:{content-hash}`) written by
  `/sync-recordings`. A recording whose id appears in any meeting note is
  never synced twice. Notes that predate the sync, or were written by hand,
  simply omit it.
- **Confidence stamp.** `confidence` and `confidence-reasons` travel
  together and record how sure the sync pipeline was about its routing:
  exactly one reason from each `confidence_reasons` group above — the
  `attendees` group also admits the parameterized form `new-attendees:{N}`
  (N ≥ 1). `calendar-tool-unavailable` means the calendar was never
  searched; `no-calendar-match` means it was searched and held nothing.
  These are different facts — never collapse them.
- `conflicts-with` (`[[meeting]]`, quoted) appears only on a `-v{n}` sibling
  written because its target would have overwritten a `confirmed` meeting. It
  is the clobber-risk signal: while it is present, `sync reconcile-reviews`
  reports a `reviewed` tick on that note instead of confirming it, because one
  meeting now has two notes and a human has to decide which survives. Clearing
  or deleting the field says the duplicate is resolved, and the next run folds
  the tick normally.
- Example: `20-meetings/05-05-26-quarterly-portfolio-review.md`

### Project — `30-projects/{slug}/index.md` · Base: `Projects.base`

```yaml
object: project
required: [project-name, slug, status, project-type, entity, owner, created,
           last-updated]
optional: [type, parent, stakeholders, meetings-7d, meetings-30d, key-people,
           next-milestone, next-milestone-date, state-updated, keywords]
enums:
  status: [active, paused, completed, cancelled]
  project-type: [initiative, area-of-responsibility]
  type: [project]
body_sections: [Coming up, Recent meetings, Recent decisions, Background]
```

- **Body is machine-rendered** by `project state write` from a state object:
  a `> [!summary] Where it stands — {d Month}` card (Stage · up to three
  Hot potatoes 🔴/🟠 · up to two Insights · Defining decision), `## Coming up`
  (a When/What table, ≤ 10 rows), `## Recent meetings` and
  `## Recent decisions` (Dataview, `LIMIT 10`), and `## Background` — folded
  callouts for 📤 Owe (grouped by owner, one item per bullet), 👤 Awaiting,
  ❓ Open questions, ⏳ Pending, Watch list and Context. A trailing
  `## Notes` section, if the owner adds one, is the single human area and
  is preserved verbatim.
- **Edges:** `parent` (project slug) · `stakeholders[]` (person slugs).
- **Auto-maintained:** `meetings-7d`, `meetings-30d`, `key-people`,
  `state-updated`.
  **Index extras:** `next-milestone`, `next-milestone-date`.
- `entity` is a slug string joining to an Entity's `slug` (and folder name).
- `keywords` — optional list of strings (project codes, nicknames, client terms) the message feed routes on; added by `project keywords add`, never by hand.
- **Slug convention: `{entity}-{name-slug}`**, composed by `project scaffold`
  (never re-prefixed when the name already starts with the entity; explicit
  `--slug` overrides). `project-name` stays entity-free — the Projects base
  shows `entity` as its own column — but the slug carries it, so slugs are
  unique across entities and typing one during meeting triage selects entity
  and project in a single gesture.
- Example: `30-projects/acme-industries-operating-model/index.md`
- `state-updated` is a full ISO timestamp (`YYYY-MM-DDTHH:MM`) written by
  `project touch` alongside `last-updated`. `last-updated` stays the
  human-facing day; `state-updated` is what the evening run's update queue
  compares each meeting's activity moment against — its `date`, or its
  `confirmed-at` stamp when that is later — so a meeting confirmed after
  the state was last written still queues. Projects that predate the field
  fall back to a day-granularity comparison that errs toward queuing until
  their first touch.
- **`project-type` is one axis: timeboxed vs ongoing.** `initiative` is
  bounded work with an end; `area-of-responsibility` is a standing
  responsibility with no end date. Counterparty is deliberately *not*
  encoded here — a project's `entity` joins to an Entity whose `entity-type`
  already says whether the work faces a client, a partner, a supplier, or
  your own business unit. Areas of responsibility are always top-level: they
  never carry a `parent`.

### Person — `50-people/{slug}.md` · Base: `People.base`

```yaml
object: person
required: [person-name, slug]
keys_present: [relationship]
optional: [email, company, role, projects, created, last-updated,
           meetings-7d, meetings-30d, last-met, messages-7d, messages-30d]
enums:
  relationship: [colleague, direct-report, external, null]
```

- `relationship: null` (key present, value empty) = **uncurated** — that is
  what People.base's "Uncurated" view filters on. `keys_present` means the
  key itself must exist even when its value is null.
- `relationship: direct-report` is what places a person in People.base's
  "Direct reports" view. `company` and `role` are expected to be filled for a
  direct report — the sync creates people with all three empty, so that view
  stays empty until someone curates.
- Optional body convention for direct-report notes: a `## Development`
  section with `### Feedback History` (a dated table) and `### Growth Areas`.
  Nothing in the plugin reads or writes it; it is a place, not a pipeline.
- Auto-created from meeting attendees; enriched manually via People Base.
- **Auto-maintained** by the evening run's metrics step, from confirmed
  meetings only (never a `type: note` capture): `meetings-7d`,
  `meetings-30d`, `last-met` (ISO date of the latest such meeting the person
  attended; emptied when there is none) and `projects` — **add-only**: a
  project from a confirmed meeting is appended, a hand-entered one is never
  removed.
- `messages-7d`, `messages-30d` are auto-maintained by `sync update-queue` from message logs, next to the meeting counters.
- `email` is stored when the M365 sync (or the message feed) creates the
  person, and filled into an existing note whose `email` is empty; a set
  email is never overwritten.
- `relationship`, `company` and `role` stay hand-curated — nothing writes
  them. `last-updated` is the creation day and is not a recency signal; sort
  on `last-met` for that.
- Example: `50-people/jordan-reyes.md`

### Decision — `30-projects/{slug}/decisions/YYYY-MM-DD-{title}.md` · Base: `Decisions.base`

```yaml
object: decision
required: [type, project, date, status, summary]
optional: [supersedes, source, archived]
keys_present: [reviewed]
enums:
  type: [decision]
  status: [active, superseded, withdrawn]
```

- **Edges:** `supersedes` (`[[decision]]` / null) · `source` (`[[meeting]]` / `[[message log]]`).
- Never deleted — status flips only. Supersession is a wikilink edge.
- `archived: true` is the owner's **Dismiss** tick (#247): the capture was
  not a real decision. Same field and meaning as on a meeting; the file
  stays. A dismissed decision leaves `Decisions.base`'s *To review* and
  *Active* views and the project page's Recent decisions, shows as
  *Dismissed* in *All*, is never a project's defining decision and is never
  superseded. `decision list` still returns it, flagged `dismissed`, so the
  evening run's dedup does not capture it again. It is not `withdrawn`: a
  withdrawn decision was real and later reversed.
- `date` is the date the decision was **made**, not the date it was written
  down. It is what orders the decision log.
- `summary` is one full sentence — it is the Decision column in
  `Decisions.base`. The filename carries a *short* kebab label instead, because
  a slug of the summary sentence is a truncated paragraph.
- `reviewed` is the triage marker: `true` when a human validated the note as it
  was written, `false` when it was captured unattended. It is in
  `keys_present`, so the key always exists — `Decisions.base`'s **To review**
  view filters on `reviewed != true`, and a missing key would make that view
  silently incomplete. Same one-click convention as Meeting's `reviewed`, and
  that view carries the checkbox, so the queue is worked where it is read.
- **There is no second status behind the tick.** Nothing gates on a decision's
  review state the way project metrics gate on a meeting's `review_status`, so
  ticking the box *is* the confirmation and no sync step folds it further. The
  asymmetry with Meeting is deliberate, not a missing feature.
- `source` names a note in `20-meetings/` or a message log in `_messages/`. A decision drawn from an inbox
  transcript, a pasted paragraph or dictation carries no `source`; its
  provenance goes in the **Why** text.
- Example: `30-projects/acme-industries-operating-model/decisions/2026-05-20-single-vendor-strategy-adopted.md`

### Decision note template

Three bold markers, not H2 sections — so this object has no `body_sections`,
and the conformance guard checks the markers instead. One paragraph per marker.

```markdown
---
type: decision
project: acme-industries-operating-model
date: 2026-05-20
status: active
summary: "One sentence stating what was decided, specific enough to be useful without opening the note."
supersedes: "[[2026-03-10-prior-decision-stem]]"
source: "[[20-05-26-vendor-strategy-brainstorm]]"
reviewed: true
---

**Decision** — What was decided.

**Why** — The reasoning, including what was traded away.

**Implications** — What changes as a result: scope, dates, who does what.
```

Quoting `supersedes` and `source` is required, not house style: unquoted,
`[[x]]` is a nested YAML list, and the note's edges stop resolving silently.
Leave `supersedes:` empty (no value) when there is nothing superseded.

### Supersession procedure

A decision is superseded when a later decision **replaces** it — stated in
words, not inferred because two notes look inconsistent. One operation, three
effects, applied together:

1. The **new** note carries `supersedes: "[[{prior-stem}]]"`.
2. The **prior** note's `status` flips `active` → `superseded`. Nothing else in
   its frontmatter changes.
3. The **prior** note gains a footer, appended — never replacing prose:

   `**Superseded** — {YYYY-MM-DD} · replaced by [[{new-stem}]].`

   The date is the new decision's date. The footer exists so a reader of the old
   note can see what replaced it without running a query.

Only an `active` decision can be superseded: `superseded` and `withdrawn`
decisions were not in force, so replacing one is a category error — and in
practice that is what a stale or mistyped stem looks like. A decision also
cannot supersede one dated after it — the edge always points backward in
time. A decision that was reversed rather than replaced is written
`withdrawn` instead. **Never delete a decision note** — the trace is the
point.

### Entity — `40-entities/{slug}/dossier.md` · Base: `Entities.base`

An entity is any organization the vault owner maintains a working relationship
with: a client, a business unit, a partner, a supplier.

```yaml
object: entity
required: [type, entity-name, slug, status]
optional: [entity-type, industry, owner, created, last-updated]
enums:
  status: [prospect, active, dormant]
  entity-type: [client, business-unit, partner, supplier, other]
  type: [entity]
body_sections: [Context, Stakeholders, Relationship History, Meeting Log,
                Sensitivities, Engagements]
```

A filled dossier's frontmatter looks like this (an example, not the schema):

```yaml
type: entity
entity-name: "Acme Industries"
slug: acme-industries        # MUST equal the folder name AND the entity: value on projects (join key)
entity-type: client
status: active
industry: "Industrial manufacturing"
owner: jordan-reyes
created: 2026-02-07
last-updated: 2026-04-01
```

### Entity body structure

The body opens with `# {entity-name}` — every dossier file is named
`dossier.md`, so without it the only title Obsidian shows is the word
"dossier" — and then carries exactly the six H2 sections in `body_sections`
above, in that order. Two skills write it — `/new-project` creates a
baseline, `/update-entity` maintains it — so this is the shared contract, not
a per-skill template.

| Section | Shape | Merge rule |
|---|---|---|
| `## Context` | `> [!info]+ **Standing context**` callout holding `> - **{Label}:** {fact} — {why it matters}` | Update the bullet with a matching label; otherwise append inside the callout. Maximum 8 bullets; consolidate the least important rather than exceeding it. |
| `## Stakeholders` | Table: Name · Title · Role in Decision · Stance · Notes | Match on name, case-insensitive. Update only fields carrying new information; never overwrite specific data with vaguer data. Never remove a row. New rows get `<!-- needs-review -->` in Notes. |
| `## Relationship History` | `- **{YYYY-MM-DD}:** {what happened} — {significance}` | Insert in date order. Never modify or remove an existing entry. |
| `## Meeting Log` | A Dataview index of the entity's meetings, then `### Dynamics` holding `- **{YYYY-MM-DD} — {Topic}:** {the read of the room}` | The table is a query — nothing writes it, and it needs no maintenance. Dynamics bullets are append-only, newest first. Never modify or remove an existing bullet. |
| `## Sensitivities` | `> [!warning]+ **Handle with care**` callout holding `> - **{topic}:** {detail} — {implications}` | Update a matching topic; otherwise append inside the callout. Never remove. |
| `## Engagements` | Table: Project · Status · One-liner | Match on project slug. Update status and one-liner. Never remove. Link `[{slug}](../../30-projects/{slug}/index.md)`. |

Empty sections carry `*No entries yet.*` — replaced on first real entry.

**Two sections are callouts, and that is part of the contract, not styling.**
`## Context` and `## Sensitivities` render as Obsidian callouts so a dossier
carries the same visual weight as a project index, which opens with
`> [!summary] Where it stands` and `> [!info]- **Context**`. The consequence for
writers: every bullet in those two sections is prefixed `> `, and the merge
matches the bullet label *after* stripping that prefix. A bullet appended
without the prefix lands outside the callout and renders as loose text below
a box — which looks like a rendering bug and is really a write-path bug.

**The Meeting Log is a hybrid, deliberately.** The table is the always-current
index; the `### Dynamics` bullets are the only part a human writes. Attendees,
outcomes and follow-ups are *not* duplicated here — they live in the meeting
note's own `## Notes` and `## Action items`, and a copy in the dossier goes
stale the moment the note is corrected. "Dynamics" is the read of the room
("exploratory throughout; no commitment asked for or offered"), which is
synthesis no query can reproduce, so it is the one thing worth keeping.

The table selects `FROM "20-meetings"` and joins on
`WHERE econtains(entities, this.slug)`, showing Date · Subject · Projects,
newest first. The query text itself is not reproduced here — `entity.py`
emits it and every dossier carries a copy, so a second copy in prose would
be one more thing to keep in sync. A meeting note that predates `entities[]`,
or was written by hand without it, is absent from the table until the field
is added: the query has no other way to reach it. See §Meeting for why the
field exists rather than the join being computed from `projects[]`.

**Role in Decision** vocabulary: sponsor · champion · evaluator · influencer
· blocker. **Stance** vocabulary: champion · neutral · blocker.

**Unvalidated marking.** Content that was generated rather than confirmed by
a human carries `<!-- unvalidated -->` directly under its section header, and
the file carries a top banner:

```
> [!unvalidated] Generated context — verify before relying on details.
```

When a human supplies content for a section, drop that section's marker. When
the last marker goes, drop the banner. This is the vault's "be epistemically
honest" rule made mechanical; keep it even where no skill currently generates
context, because `/setup-my-brain` will.

- `slug` MUST equal the folder name AND the `entity:` value on its projects —
  it is the join key.
- Dates written **unquoted ISO** (`2026-02-07`) — quoted dates silently break
  Bases/Dataview date handling. This convention applies to every object type.
- Per-entity project lists come free by grouping `Projects.base` on `entity`.

### Daily note — `60-daily-notes/{YYYY-MM-DD}.md` · no Base

One note per working day, written the evening before by `/evening-sync`,
jotted in by hand during the day, harvested (read-only) that evening. It is
the day's canvas and its archive — deliberately the thinnest object type.

```yaml
object: daily-note
required: [date, type]
optional: []
enums:
  type: [daily-note]
body_sections: [Recap, Meetings, End of day]
```

- `date` is an unquoted ISO date and MUST equal the filename stem.
- **Machine regions are marker-fenced.** Inside the body, machine-written
  content sits between `<!-- evening-sync:{region}:begin -->` and
  `<!-- evening-sync:{region}:end -->` markers — one `recap` region under
  `## Recap`, one `prep` region per meeting under `## Meetings` (or a single
  prep region carrying `*No meetings scheduled.*` on an empty calendar).
  `daily-note write` regenerates marked regions wholesale on any re-run and
  is forbidden from touching a byte outside them. One writer class per
  region.
- **Review block**: a fresh note opens with `> [!review] Waiting for you`,
  above `## Recap` — the embedded Meetings `Triage` and Decisions
  `To review` views, written once at creation, collapsed by the CSS snippet
  when both are empty. It is not a region and holds no state.
- **Everything outside the markers is human territory**: jotting bullets
  under each meeting heading, `## End of day`, anything else. The evening
  harvest reads jottings as input; nothing ever edits or routes them in v1.
- **Recap v2 is rendered from fields**: `[!glance]` (first line computed by
  the CLI: meeting count, window, theme and decision counts; then 1–4
  labelled headlines and the entities touched), folded `[!theme]-` callouts
  (≤ 4, headline ≤ 12 words, body ≤ 80), a Project pulse table with a
  🔴/🟠/🟢/⚪ signal per project, Decisions logged as `[[stem|summary]]`,
  `[!hot] Watch` (content risks only), folded `[!quote]- Carried forward`
  and folded `[!sync]- Sync notes` (mechanics: duplicates, fetch errors,
  refusals, SELF-CHECK lines). A `[!warning] Catch-up note` callout is the
  CLI's; one supplied in a payload is stripped.
- **Meeting blocks v2**: `### {HH:MM} — {Subject}[ · [[40-entities/{slug}/dossier|{Entity name}]]]`,
  then `#### Prep` holding the prep region (three lines: **Attendees**,
  **Last meeting**, **Context**), then `#### Your notes` (`- `) and
  `#### Your actions` (`- [ ] `) — `#### Notes`/`#### Actions` on notes
  written before 0.12.11. Notes and Actions are written once at creation and never
  regenerated; the harvest returns them separately, actions with done state.
- **Identity links are path links.** Entities and projects are folders, and
  Obsidian resolves `[[name]]` by file name only, so writers emit
  `[[40-entities/{slug}/dossier|{Name}]]` / `[[30-projects/{slug}/index|{Name}]]`;
  the CLI normalises a bare `[[slug]]` to that form.
- A note is never deleted or rewritten by a later day's run. Times are the
  vault owner's local timezone.

A day in the life of a daily note:

```markdown
### 10:00 — 1:1 — Jordan Vance · [[nordbridge-components]]
<!-- evening-sync:prep:begin -->
**Attendees:** Jordan Vance · **Last meeting:** 2026-03-02 — intro call · **Context:** …
<!-- evening-sync:prep:end -->
- proposal on track for September submission   ← hand jotting, untouchable
```

### Message log — `_messages/{YYYY-MM-DD}-messages.md` · no Base

```yaml
object: message-log
required: [type, date, updated-at]
keys_present: [projects, people, messages-read]
optional: [projects-weak, entities, window-from, window-to, skipped,
           at-limit, gaps]
enums:
  type: [message-log]
```

- One per calendar day of mail and Teams chat, written only by
  `messages write`. Machine material: hidden from the file list and search;
  sessions and the evening run read it, the owner meets it only through a
  "from mail" link.
- `projects[]` holds every linked project; `projects-weak[]` the subset that
  never queues a project-state update. `people[]` and `entities[]` follow the
  Meeting pattern.
- `projects`, `people` and `messages-read` are `keys_present`: the keys must
  exist, but `[]` and `0` are legitimate on a quiet day.
- The body is rendered from the `%% log-data … %%` block at its end; never
  edit either by hand.
- **Update-queue exception:** a log counts as project activity without a
  review tick (strong links only), unlike meetings.

## 2. Relationship graph

- `Meeting —projects[]→ Project`
- `Meeting —attendees[]→ Person`
- `Meeting —entities[]→ Entity`
- `Project —entity→ Entity`
- `Decision —project→ Project`
- `Decision —source→ Meeting`
- `Decision —source→ Message log`
- `Decision —supersedes→ Decision`
- `Message log —projects[]→ Project`
- `Message log —people[]→ Person`
