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
           source-drive-id, source-filename, reviewed, archived]
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update]
  review_status: [needs-review, confirmed, needs-attention]
```

- `date` is an ISO datetime (e.g. `2026-05-05T14:37`).
- `attendee-emails`, `organizer`, `location`, `recurring`, `start-time`
  appear on calendar-matched meetings only. `source-drive-id`,
  `source-filename` are recorder provenance.
- **Triage checkboxes (booleans, edited in Meetings.base):** `reviewed` —
  one-click confirm; `archived` — hides the row from triage views (noise
  disposal; the file stays).
- Write-once; only triage fields (`attendees`, `projects`, `review_status`,
  `reviewed`, `archived`) are edited later.
- The `1:1` type value must stay **quoted** in frontmatter and in the block
  above — unquoted YAML parses `1:1` as the integer 61.
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
  project-type: [presales, delivery, internal, area-of-responsibility]
```

- **Edges:** `parent` (project slug) · `stakeholders[]` (person slugs).
- **Auto-maintained:** `meetings-7d`, `meetings-30d`, `key-people`.
  **Index extras:** `next-milestone`, `next-milestone-date`.
- `entity` is a slug string joining to an Entity's `slug` (and folder name).
- Example: `30-projects/acme-industries-operating-model/index.md`

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

### Decision — `30-projects/{slug}/decisions/YYYY-MM-DD-{summary}.md` · Base: `Decisions.base`

```yaml
object: decision
required: [type, project, date, status, summary]
optional: [supersedes, source, tags]
enums:
  type: [decision]
  status: [active, superseded, withdrawn]
tags:
  vocabulary: [scope, platform, staffing, methodology, commercial, timing,
               stakeholder]
  max: 2
```

- **Edges:** `supersedes` (`[[decision]]` / null) · `source` (`[[meeting]]`).
- Never deleted — status flips only. Supersession is a wikilink edge.
- Example: `30-projects/acme-industries-operating-model/decisions/2026-05-20-single-vendor-strategy-adopted.md`

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
