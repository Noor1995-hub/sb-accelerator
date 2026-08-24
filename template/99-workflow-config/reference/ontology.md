---
tags: [meta, reference, ontology]
---

# Vault Ontology — Authoritative Object Model

> **Single source of truth for the vault's object types, fields, and
> controlled vocabularies.** Edit here; never let the schema live in prose
> elsewhere.

Five object types: **Meeting · Project · Person · Decision · Entity**.
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

## 1. Object catalog

### Meeting — `20-meetings/{DD-MM-YY-slug}.md` · Base: `Meetings.base`

```yaml
object: meeting
required: [date, type, calendar-subject, calendar_match, attendees, projects,
           review_status, recording-duration, source, processed]
optional: [attendee-emails, organizer, location, recurring, start-time,
           source-recording-id, source-filename, conflicts-with,
           confidence, confidence-reasons, reviewed, archived]
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update]
  review_status: [needs-review, confirmed, needs-attention]
  source: [teams, recorder, manual, email]
  confidence: [high, medium, low]
confidence_reasons:
  calendar: [calendar-match-high, calendar-match-medium, calendar-match-low,
             no-calendar-match, calendar-tool-unavailable]
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
  `reviewed`, `archived`) are edited later.
- The `1:1` type value must stay **quoted** in frontmatter and in the block
  above — unquoted YAML parses `1:1` as the integer 61.
- `source` is the capture channel: `teams` (platform transcript), `recorder`
  (device capture), `manual` (typed notes), `email` (an emailed summary or
  transcript). `recording-duration` is `0` when nothing was recorded
  (`manual`, `email`).
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
- `conflicts-with` (`[[meeting]]`, quoted) appears only on a
  `needs-attention` sibling written because its target would have
  overwritten a `confirmed` meeting.
- Example: `20-meetings/05-05-26-quarterly-portfolio-review.md`

### Project — `30-projects/{slug}/index.md` · Base: `Projects.base`

```yaml
object: project
required: [project-name, slug, status, project-type, entity, owner, created,
           last-updated]
optional: [type, parent, stakeholders, meetings-7d, meetings-30d, key-people,
           next-milestone, next-milestone-date]
enums:
  status: [active, paused, completed, cancelled]
  project-type: [initiative, area-of-responsibility]
body_sections: [Decisions, Open Items, Related Meetings]
```

- **Edges:** `parent` (project slug) · `stakeholders[]` (person slugs).
- **Auto-maintained:** `meetings-7d`, `meetings-30d`, `key-people`.
  **Index extras:** `next-milestone`, `next-milestone-date`.
- `entity` is a slug string joining to an Entity's `slug` (and folder name).
- Example: `30-projects/acme-industries-operating-model/index.md`
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
           meetings-7d, meetings-30d]
enums:
  relationship: [colleague, direct-report, external, null]
```

- `relationship: null` (key present, value empty) = **uncurated** — that is
  what People.base's "Uncurated" view filters on. `keys_present` means the
  key itself must exist even when its value is null.
- Auto-created from meeting attendees; enriched manually via People Base.
- Example: `50-people/jordan-reyes.md`

### Decision — `30-projects/{slug}/decisions/YYYY-MM-DD-{title}.md` · Base: `Decisions.base`

```yaml
object: decision
required: [type, project, date, status, summary]
optional: [supersedes, source]
keys_present: [reviewed]
enums:
  type: [decision]
  status: [active, superseded, withdrawn]
```

- **Edges:** `supersedes` (`[[decision]]` / null) · `source` (`[[meeting]]`).
- Never deleted — status flips only. Supersession is a wikilink edge.
- `date` is the date the decision was **made**, not the date it was written
  down. It is what orders the decision log.
- `summary` is one full sentence — it is the Decision column in
  `Decisions.base`. The filename carries a *short* kebab label instead, because
  a slug of the summary sentence is a truncated paragraph.
- `reviewed` is the triage marker: `true` when a human validated the note as it
  was written, `false` when it was captured unattended. It is in
  `keys_present`, so the key always exists — `Decisions.base`'s **Needs review**
  view filters on `reviewed == false`, and a missing key would make that view
  silently incomplete. Same one-click convention as Meeting's `reviewed`.
- `source` names a note in `20-meetings/`. A decision drawn from an inbox
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

An entity is any organization the executive maintains a working relationship
with: a client, a business unit, a partner, a supplier.

```yaml
object: entity
required: [type, entity-name, slug, status]
optional: [entity-type, industry, owner, created, last-updated]
enums:
  status: [prospect, active, dormant]
  entity-type: [client, business-unit, partner, supplier, other]
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

The dossier body carries exactly the six H2 sections in `body_sections`
above, in that order. Two skills write it — `/new-project` creates a
baseline, `/update-entity` maintains it — so this is the shared contract, not
a per-skill template.

| Section | Shape | Merge rule |
|---|---|---|
| `## Context` | `- **{Label}:** {fact} — {why it matters}` | Update the bullet with a matching label; otherwise append. Maximum 8 bullets; consolidate the least important rather than exceeding it. |
| `## Stakeholders` | Table: Name · Title · Role in Decision · Stance · Notes | Match on name, case-insensitive. Update only fields carrying new information; never overwrite specific data with vaguer data. Never remove a row. New rows get `<!-- needs-review -->` in Notes. |
| `## Relationship History` | `- **{YYYY-MM-DD}:** {what happened} — {significance}` | Insert in date order. Never modify or remove an existing entry. |
| `## Meeting Log` | `### {YYYY-MM-DD} — {Topic}` then Attendees / Key outcomes / Follow-ups / Dynamics bullets | Append-only, newest first (prepend). Never modify an existing entry. |
| `## Sensitivities` | `- **{topic}:** {detail} — {implications}` | Update a matching topic; otherwise append. Never remove. |
| `## Engagements` | Table: Project · Status · One-liner | Match on project slug. Update status and one-liner. Never remove. Link `[{slug}](../../30-projects/{slug}/index.md)`. |

Empty sections carry `*No entries yet.*` — replaced on first real entry.

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

## 2. Relationship graph

- `Meeting —projects[]→ Project`
- `Meeting —attendees[]→ Person`
- `Project —entity→ Entity`
- `Decision —project→ Project`
- `Decision —source→ Meeting`
- `Decision —supersedes→ Decision`
