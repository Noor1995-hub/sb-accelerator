# One source instead of copies: people and projects feed the entity page (#273, piece 2)

## Problem

An entity's dossier holds two typed tables that nothing keeps current:

- **Stakeholders** (Name · Title · Role in Decision · Stance · Notes). It is
  written by `/update-entity` and never updated after. A person newly linked
  to the entity does not appear; a changed title stays old.
- **Engagements** (Project · Status · One-liner). One row is written by
  `/new-project` at creation and never updated. A finished project still says
  "Active"; projects made by `/setup-my-brain` or `/update-tables` are
  missing.

At the same time a person's employer is free text (`company: "Acme"`), so
nothing can join a person to their entity.

#273 is split into four pieces: (1) small fixes, PR #280; (2) **this spec**;
(3) automatic entity and team updates (#184); (4) facts about people. Piece 2
comes first because it decides where pieces 3 and 4 write.

## Decisions (vault owner, 2026-10-12)

- **Stakeholder information lives on the person** (option A). It is one
  source, fillable through `/update-tables` too. A person has one stance, not
  one per entity; a person in the vault almost always belongs to one entity.
- **A person links to an entity** with `entity:` (a slug), replacing the
  free-text `company`. The link may point at a team (two tiers); a team's
  people then also appear on the parent entity's Stakeholders.
- **Upgrade, company with no matching entity:** the text stays (as
  `company`) and the upgrade summary lists it; the owner resolves it, for
  instance in bulk with `/update-tables` (option A).
- **Engagements' third column** is the project's current state: the "Where
  it stands" stage sentence the project update already writes, now also
  stored as a property. It sits next to the next milestone. Existing
  one-liners move into the project page's `## Notes` section.
- **Both tables become live queries**, like the Meeting Log.

## Design

### Person: new and changed properties

| Property | Values | Notes |
|---|---|---|
| `entity` | entity slug, or empty | replaces `company`; may be a team |
| `company` | free text | kept **only** for a value the upgrade could not match; no longer written by anything new |
| `role` | text | exists; shown as "Title" |
| `decision-role` | sponsor · champion · evaluator · influencer · blocker | closed vocabulary (unchanged from today's Stakeholders) |
| `stance` | champion · neutral · blocker | closed vocabulary |

Ontology (`ontology.md`, Person) gains `entity`, `decision-role`, `stance` as
optional keys with those enums; `company` is documented as legacy. The schema
(`schema.json`) is regenerated.

`person ensure` gains an optional `--entity <slug>`: it sets the link on a
new note, and on an existing note only when `entity` is empty, the same
fill-if-empty rule as email. A new `person set --slug S [--entity E]
[--role R] [--decision-role D] [--stance X]` writes those properties on an
existing person. It validates enums and that the entity exists, and it is
byte-preserving.

### Project: `stage`

`project state write` already renders the card's Stage sentence. It now
also writes it to frontmatter as `stage` (quoted, single line, the state's
`stage` string). It is machine-maintained; the ontology lists it next to
`state-updated`. Nothing else writes it.

### Entity page: two live sections

Both are Dataview queries, slug-free like the Meeting Log and the Teams
section (every dossier carries the same bytes; `this.slug` resolves at render
time).

**Stakeholders**: people whose `entity` is this entity or one of its teams:

```dataview
TABLE WITHOUT ID
  link(file.path, person-name) AS "Name",
  choice(entity = this.slug, "", link("40-entities/" + entity + "/dossier").entity-name) AS "Team",
  role AS "Title",
  decision-role AS "Role in decision",
  stance AS "Stance"
FROM "50-people"
WHERE entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug
SORT person-name ASC
```

**Engagements**: projects whose `entity` is this entity or one of its teams:

```dataview
TABLE WITHOUT ID
  link(file.path, project-name) AS "Project",
  upper(substring(status, 0, 1)) + substring(status, 1) AS "Status",
  stage AS "Where it stands",
  next-milestone AS "Next milestone"
FROM "30-projects"
WHERE type = "project" AND (entity = this.slug OR link("40-entities/" + entity + "/dossier").parent = this.slug)
SORT status ASC, project-name ASC
```

The Teams section keeps its first query (the teams) and **drops its second**
(the teams' projects): Engagements now lists them, with a Team column only
where it matters. (The plan checks whether Dataview renders `choice()` with
a link inside; if not, the Team column uses the same `link(…).entity-name`
form the Teams section already uses.)

`entity.py`: the dossier template renders these two sections. `entity write`
no longer accepts `stakeholders` or `engagements` edits; they are refused
with a pointer ("stakeholders live on the person: person set …"). Reading a
dossier treats both sections as live: never parsed, never rewritten.

### Skills

- `/update-entity`: the Stakeholders route becomes `person ensure` (if
  needed) + `person set --entity <this> --role … --decision-role … --stance
  …`. Notes about a person go to the person's page; until piece 4 they go
  under `## Notes from <entity>` (below). The Engagements route is removed.
- `/new-project`: step 5 (the Engagements row) is removed; the project shows
  up on its own.
- `/sync-recordings` and the message feed: `person ensure` for a new attendee
  passes `--entity` when routing already knows the attendee's entity (an email
  domain match). Never a guess; empty otherwise.
- `/setup-my-brain`: the people step passes `--entity` when the owner said
  where someone works.

### `/update-tables` rework (#279)

People spec in `tables.py`: `company` (kind `company`) → `entity` (kind
`entity`, a dropdown of entity names, strict as a link: an unknown name is
refused and listed). `decision-role` and `stance` are added as choice kinds.
A new person row may name an entity. The People.base template column
"Company" becomes "Entity" (a formula over `entity`, names over codes, as on
Projects), so the export's header follows. Entities and Projects tables are
unchanged (`stage` is machine-maintained, so not editable).

### People.base

The `company` column becomes an `entity-name` formula
(`if(entity, link("40-entities/" + entity + "/dossier.md", …entity-name), company)`).
It shows the legacy text for an unmatched person, so nothing disappears.
`decision-role` and `stance` are added to the All view after Role.

### Upgrade (migration 013 → structure version 14)

Runs inside `/upgrade-vault` (snapshot first, as always). Deterministic, in
this order:

1. **Company → entity.** For each person with `company` and no `entity`:
   match the text case-insensitively against every `entity-name` (and slug).
   Exactly one match → set `entity`, remove `company`. Zero or several →
   leave `company`, list it ("12 people linked; 3 not matched: LLBG (2),
   Acme nv (1)").
2. **Stakeholders rows → people.** For each dossier, each row of the typed
   Stakeholders table:
   - Find the person: the Name cell's wikilink slug, else the name matched
     against `person-name`. None found → create the person (`person ensure
     --name`), since the owner named them as a stakeholder.
   - Fill `role` ← Title, `decision-role` ← Role in Decision, `stance` ←
     Stance, each only when the person's own value is empty. A different
     existing value is kept, and the clash is listed. An out-of-vocabulary
     value is listed, not written.
   - Set `entity` to this dossier's slug when the person has none.
   - Notes (not empty, and not only the `<!-- needs-review -->` marker) →
     appended to the person's page under `## Notes from <Entity name>`, one
     bullet per row, with the date of the upgrade.
3. **Engagements rows → projects.** Each row with a non-empty One-liner whose
   project resolves → appended to the project's `## Notes` section (created
   if missing, which the state writer preserves): `- Engagement note (moved
   from <Entity> page, <date>): <one-liner>`. A row whose project does not
   resolve → listed.
4. **Sections replaced.** Each dossier's typed Stakeholders and Engagements
   tables are replaced by the two live sections. The Teams section loses its
   project query. Text the owner wrote around a table (a preamble or a line
   below it) is kept above the live query.
5. **Report.** Counts plus every unmatched value, clash and unresolved row,
   one line each, ending with *"Resolve the unmatched companies with
   /update-tables (People)."*

Idempotent: a second run finds no typed tables and no `company` it can
match, and changes nothing.

### What the owner sees

- An entity page always lists its people and projects, current, however
  they were made.
- People has an Entity column (names), plus Role in decision and Stance.
- `/update-tables` People offers Entity, Role in decision and Stance as
  dropdowns.

## Testing

- **CLI:** `person set` (each field, enum refusal, unknown entity refusal,
  byte-preserving), `person ensure --entity` (fill-if-empty), `project state
  write` stores `stage`, `entity write` refuses stakeholder/engagement edits
  with the pointer, and the dossier template carries the two live queries.
- **Dataview:** the query text is checked by the repo's `dqlrefs` model (the
  fields used exist in the ontology; `link(...).field` lookups resolve), as
  existing dossier queries are.
- **Migration 013:** fixtures with:
  - a matched company, an unmatched company and an ambiguous one;
  - a Stakeholders row by wikilink, by plain name, and for a missing person;
  - a clashing role and an out-of-vocabulary stance;
  - a Notes cell holding only `<!-- needs-review -->`;
  - an Engagements one-liner for an existing and a missing project;
  - owner text around a table;
  - a second run that changes nothing;
  - a vault with no dossiers.
- **`/update-tables`:** the People export has Entity (names), Role in
  decision and Stance with dropdowns; import maps names to the slug, and an
  unknown entity is refused.
- **Skill contracts:** `/update-entity` no longer writes stakeholder or
  engagement rows and calls `person set`; `/new-project` has no Engagements
  step.
- **Demo fixture:** the demo vault is migrated, so its dossiers show the live
  sections and its people carry entity, decision-role and stance.

## Out of scope

- Automatic entity/team page updates (piece 3, #184).
- The "What I know" section and its rules (piece 4). This spec only moves
  existing Notes to `## Notes from <entity>`.
- One stance per entity (several entities per person).
- Renaming `Dismissed` in the Meetings table (#273 piece 1 decision: leave it).

## Release

Structure version 14 (migration 013), template changes (People.base,
dossier template, ontology), CLI, skills, `/update-tables` rework, tests,
demo fixture. CHANGELOG entry: "needs `/upgrade-vault` (structure 14)".
Version bump.
