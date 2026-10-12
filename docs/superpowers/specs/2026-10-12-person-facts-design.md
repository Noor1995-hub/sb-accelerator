# Facts about people: "What I know" (#273 piece 4)

## Problem

Person notes hold frontmatter and a meeting list, but no facts about the
person: *"trying to sell her house"*, *"having a hard time with this
topic"*, *"wants numbers, not narrative"*. `person.py` keeps the body empty
on purpose, and the only person-page text today is `## Notes from <entity>`,
created by migration 013 (moved Stakeholders notes) and written by
`/update-entity`. The owner wants the brain to keep these facts, current,
without asking.

Builds on #277 (shared processing part `evening-sync/references/process.md`)
and #282 (section D: entity pages update themselves, `entity write
--automatic`, source markers enforced). Starts from main 0.13.17,
structure 14.

## Decisions (vault owner, 2026-10-12)

- **Privacy rule 1:** facts about people never appear in anything that
  leaves the vault (prep notes, briefs, emails, feedback reports).
- **Privacy rule 2:** the run records only what the person said about
  themselves; never what others said about them, never Claude's reading of
  them.
- **Sources:** meetings, mail/Teams and sessions, like entity pages.
- **Whose facts:** everyone with a person note — clients, partners,
  colleagues and direct reports.
- **Review:** none. Lines appear with their source; the owner deletes a
  wrong one.
- **Daily note:** shows nothing from it. Facts live only on the person page.
- **Existing `## Notes from <entity>`:** merged into `## What I know`.
- **Kind of fact:** personal and working facts alike — anything the person
  said about themselves that helps the owner work with them.
- **Approach B:** one subagent per piece of material (meeting, day log), not
  per person.
- **No look-back:** the first run reads nothing older than the upgrade.

## Design

### The section

Every person page may carry `## What I know`, placed directly after the
`# {person-name}` heading:

```markdown
# Dana Whitfield

## What I know

- 2026-10-08 — Is selling her house, wants to move closer to Ghent. (meeting · [[08-10-26-nordbridge-weekly]])
- 2026-10-10 — Prefers a written business case over a call. (mail · <link>)
- Straight about constraints. (moved from the Nordbridge Components page, 2026-10-12)
- Has two kids at the same school as mine.
```

- Automatic line: `- <YYYY-MM-DD> — <fact> (<marker>)`. The date is the
  material's own date (meeting date, message date, session date), not the
  run date. Markers are piece 3's: `(meeting · [[stem]])`, `(mail · <link>)`,
  `(chat · <link>)`, `(session · [[path|title]])`, `(note · <title>)`.
- New lines are appended at the bottom of the section (oldest → newest).
- Any line the owner writes is the owner's, dated or not. Other sections
  (`## Context`, `## Recent Meetings`, `## Development`, …) are never touched.
- Removing a fact = deleting the line. The `person-updated` stamp keeps the
  same material from being read again; the fact returns only if it is said
  again in later material.

### Writer: `person write` and `person touch`

`python3 "$VAULTLIB" person write --vault V --slug S --automatic --facts F.json`

Payload: `{"facts": [{"date": "YYYY-MM-DD", "fact": "… (meeting · [[…]])"}]}`.

- Appends only. Never edits, reorders or removes an existing line.
- Refuses an item whose `fact` does not end in a source marker (piece 3's
  `_SOURCE_MARKER_RE`, shared, not copied): not written, listed in
  `skipped` with the reason.
- Refuses an invalid date or an empty fact the same way.
- Skips an exact duplicate (same date, fact text and marker already present
  in the section) and lists it in `duplicates`.
- Creates `## What I know` after the H1 when missing; when the page has no
  H1, at the top of the body.
- Frontmatter: only `last-updated` changes. A CRLF file is read correctly
  and written back with LF, like every vault writer. Unknown slug → error
  naming the slug.
- `--automatic` is required (the flag states intent; there is no manual
  mode — the owner edits by hand).
- Result JSON: `{"slug", "written", "skipped": [...], "duplicates": [...]}`.

`python3 "$VAULTLIB" person touch --vault V --slug S --timestamp <ISO>`
sets `person-updated` (idempotent, like `entity touch`).

### Queue: `update-queue` gains `peopleNeedingUpdate` and `peopleWork`

A person P is queued when material newer than P's start point names P:

| Source | Names P when | Activity time |
|---|---|---|
| Confirmed meeting, incl. `type: note` | `P ∈ attendees[]` | as for the entity queue |
| Mail/Teams day log group | `P ∈` the group's `people` | the log's `updated-at`, as for the entity queue (a later rewrite of the day re-reads its groups; exact duplicates are skipped) |

- Start point: `person-updated`; when absent, `created` at 00:00; when both
  are absent (a page made by hand), today at 00:00 — section E's stamp takes
  over from the first run, and no warning repeats every night.
- Session records are **not** a source here — session facts are written on
  the spot (see `/add`), so reading them again would write them twice.
- The vault owner's own person note is never queued.
- `peopleNeedingUpdate`: `[{slug, path, personName}]`.
- `peopleWork`: one item per meeting and one per day log that names at least
  one queued person: `{kind: "meeting"|"log", path, date, people: [slug…]}`
  (for a log, `groups` carries the ids of the groups that name queued
  people). The grouping is computed in code, not by the model.
- Material older than a person's start point is not listed for that person,
  even when the same meeting is listed for another.

### Section E in `process.md` (after D)

Runs wherever D runs: every evening, `/sync-recordings` step 9 and `/add`
step 6. `peopleWork` empty → record "no people pages to update" and go on.

One Sonnet subagent per `peopleWork` item, blocking batches of at most 3
(C's rule, unchanged), no cap. Each subagent:

1. Reads the material end to end and each listed person's current
   `## What I know` (reading the person file directly).
2. Keeps only what **that person said about themselves** — personal or
   working. Not what others said about them, not an interpretation of tone
   or mood, nothing invented, nothing already on the page. Writing nothing
   is a valid outcome.
3. Writes per person with `person write --automatic`, marker per piece 3.
4. Returns `{"path", "written": {slug: N}, "skipped", "notes"}`.

After all items return, every queued person whose items all succeeded gets
`person touch --timestamp <queuedAt>` — also when nothing was written. A
person with a failed item is not stamped and retries next run.

Run summary: counts only ("People: 4 facts added for 3 people"). The daily
note gets nothing.

### `/update-entity` and `/add`

- `/update-entity`: a note about a person goes through `person write
  --automatic` with a `(session · …)` marker, into `## What I know`, instead
  of `## Notes from <entity name>`.
- `/add`: when the owner states a fact about a person, it is written at once
  with `person write --automatic` and
  `(session · [[<session record path>|<title>]])`, applying rule 2's
  wording (the owner relaying what the person said counts as the person
  saying it).

### Migration 014 → structure 15

For every `50-people/*.md`:

- Moves every line under every `## Notes from <X>` heading (bullets and any
  other text, in order, markers untouched) into `## What I know`, creating
  it after the H1 when missing; removes the emptied `Notes from` headings.
- Sets `person-updated: <upgrade time>` on every person page (the
  no-look-back start point), including pages with nothing to move.
- Idempotent; unreadable file → `needs_human`; owner text elsewhere kept
  byte-for-byte.
- The usual structure-bump chain: `plugin/template/structure-version`,
  `EXPECTED_STRUCTURE_VERSION` in `scripts/validate_template.py` and
  `plugin/lib/instantiate_vault.py`, "chain ends at" assertions in
  `scripts/tests/test_migration_0*.py`, `test_validate_template.py`,
  `test_vaultlib_provenance.py`, and the demo fixture migrated.

### Ontology and privacy guard

- Ontology, Person: `person-updated` (optional, ISO datetime);
  `## What I know` described (format, markers, append-only, owner lines);
  privacy rules 1 and 2 stated. The direct-report `## Development`
  convention stays. Then `python scripts/compile_ontology.py`.
- Vault `CLAUDE.md` template: one rule — `## What I know` on person pages is
  never used in anything meant for someone else.
- `person.py` docstring updated: the body is no longer always empty.

## Testing

Test-first for every CLI part.

- `person write`: append; section creation (after H1, no-H1 case); marker
  refusal → `skipped`; bad date/empty fact refused; exact duplicate →
  `duplicates`; owner lines and other sections unchanged byte-for-byte;
  CRLF input handled; frontmatter only `last-updated`; unknown slug error.
- `person touch`: sets, idempotent, rejects a malformed timestamp.
- `update-queue`: meeting and `type: note` attendees; log group `people`;
  stamp excludes older material; `created` fallback; neither → today;
  owner excluded; sessions excluded; `peopleWork` grouping with per-person
  start points.
- Migration 014: one and several `Notes from` sections; non-bullet text
  kept; pre-existing `## What I know` appended to; stamp on every page;
  idempotent; unreadable → `needs_human`; chain assertions bumped.
- Contracts: section E carries rule 2's wording and the no-daily-note rule;
  `/update-entity` and `/add` use `person write`; People export from
  `/update-tables` carries no body text; feedback scrub refuses a draft
  containing a `What I know` line.

Review: a separate reviewer on `person write` and migration 014 (they
rewrite owner notes); one final whole-branch review on the most capable
model, Critical/Important fixed test-first.

## Delivery

One PR off main: plugin 0.13.18 (`plugin.json` and
`test_marketplace_manifest.py`), structure 15, CHANGELOG under
`## Unreleased` ending `(#273, #<PR>)`. A demo vault is built for the owner
to check one person page in Obsidian.

## Out of scope

- A review queue for facts (owner chose none).
- Showing facts in the daily note or meeting prep.
- Using session records as a queue source for people.
- A "plain-language what updates when" section in Start here (next piece).
