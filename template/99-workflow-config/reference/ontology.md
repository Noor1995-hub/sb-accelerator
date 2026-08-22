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

## 1. Object catalog

### Meeting — `20-meetings/{DD-MM-YY-slug}.md` · Base: `Meetings.base`

- **Required:** `date` (ISO datetime, e.g. `2026-05-05T14:37`), `type`,
  `calendar-subject`, `calendar_match`, `attendees`, `projects`,
  `review_status`, `recording-duration`, `source`, `processed`
- **Calendar-matched only:** `attendee-emails`, `organizer`, `location`,
  `recurring`, `start-time`
- **Recorder provenance (optional):** `source-drive-id`, `source-filename`
- **Triage checkboxes (booleans, edited in Meetings.base):** `reviewed` —
  one-click confirm; `archived` — hides the row from triage views (noise
  disposal; the file stays)
- **Enums:** `type` = meeting | 1:1 | steerco | workshop | brainstorm |
  status-update · `review_status` = needs-review | confirmed | needs-attention
- Write-once; only triage fields (`attendees`, `projects`, `review_status`,
  `reviewed`, `archived`) are edited later.
- Example: `20-meetings/05-05-26-quarterly-portfolio-review.md`

### Project — `30-projects/{slug}/index.md` · Base: `Projects.base`

- **Required:** `project-name`, `slug`, `status`, `project-type`, `entity`,
  `owner`, `created`, `last-updated`
- **Edges:** `parent` (project slug) · `stakeholders[]` (person slugs)
- **Auto-maintained:** `meetings-7d`, `meetings-30d`, `key-people`
- **Index extras:** `next-milestone`, `next-milestone-date`
- **Enums:** `status` = active | paused | completed | cancelled ·
  `project-type` = presales | delivery | internal | area-of-responsibility
- `entity` is a slug string joining to an Entity's `slug` (and folder name).
- Example: `30-projects/acme-industries-operating-model/index.md`

### Person — `50-people/{slug}.md` · Base: `People.base`

- **Fields:** `person-name`, `slug`, `email`, `relationship`, `company`,
  `role`, `projects[]`, `created`, `last-updated`, `meetings-7d`,
  `meetings-30d`
- **Enum:** `relationship` = colleague | direct-report | external
  (null = uncurated)
- Auto-created from meeting attendees; enriched manually via People Base.
- Example: `50-people/jordan-reyes.md`

### Decision — `30-projects/{slug}/decisions/YYYY-MM-DD-{summary}.md` · Base: `Decisions.base`

- **Required:** `type: decision`, `project`, `date` (ISO), `status`, `summary`
- **Edges:** `supersedes` (`[[decision]]` / null), `source` (`[[meeting]]`)
- **Optional:** `tags` (0–2)
- **Enums:** `status` = active | superseded | withdrawn · `tags` from the
  controlled vocabulary: scope, platform, staffing, methodology, commercial,
  timing, stakeholder
- Never deleted — status flips only. Supersession is a wikilink edge.
- Example: `30-projects/acme-industries-operating-model/decisions/2026-05-20-single-vendor-strategy-adopted.md`

### Entity — `40-entities/{slug}/dossier.md` · Base: `Entities.base`

An entity is any organization the executive maintains a working relationship
with: a client, a business unit, a partner, a supplier.

```yaml
type: entity
entity-name: "Acme Industries"
slug: acme-industries        # MUST equal the folder name AND the entity: value on projects (join key)
entity-type: client          # client | business-unit | partner | supplier | other
status: active               # prospect | active | dormant
industry: "Industrial manufacturing"
owner: jordan-reyes
created: 2026-02-07
last-updated: 2026-04-01
```

- **Required:** `type`, `entity-name`, `slug`, `status`.
  **Optional:** `entity-type`, `industry`, `owner`, `created`, `last-updated`.
- **Enums:** `status` = prospect | active | dormant · `entity-type`
  (suggested vocabulary) = client | business-unit | partner | supplier | other
- Dates written **unquoted ISO** (`2026-02-07`) — quoted dates silently break
  Bases/Dataview date handling.
- Per-entity project lists come free by grouping `Projects.base` on `entity`.

## 2. Relationship graph

- `Meeting —projects[]→ Project`
- `Meeting —attendees[]→ Person`
- `Project —entity→ Entity`
- `Decision —project→ Project`
- `Decision —source→ Meeting`
- `Decision —supersedes→ Decision`
