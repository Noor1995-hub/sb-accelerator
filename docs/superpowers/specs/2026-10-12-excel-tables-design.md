# Fill in and add people, projects and entities in Excel (#272)

## Problem

Obsidian's tables are hard to use for bulk work: adding twenty people,
filling in the missing role and company for forty, or setting the owner on
every project means clicking cell by cell. The owner wants to say *"I want to
fill in / update / add to People"* and get an Excel, fill it in, hand it
back, and have the vault updated: correctly, and the same way every time.

## Decisions (vault owner, 2026-10-12)

- **Round trip through Excel.** Claude exports an `.xlsx` built from **the
  owner's own table** (their `.base`: its columns, order and names). The
  owner fills it in. A script writes it back. Export and import are
  **deterministic CLI code**, never improvised by Claude.
- **Only columns the owner can change** appear. No calculated, system or
  evening-run columns; they would be there for nothing.
- **First version: People, Projects, Entities.** To Do's is a later
  extension (same design). Meetings and Decisions are out.
- **Row identity:** a hidden key column (the note's path). The slug is never
  editable.
- **New rows** go through the existing creators (`person ensure`,
  `entity ensure`, `project scaffold`), so they are identical to objects made
  any other way. A row missing a required field is refused with the reason;
  the other rows still go through.
- **Excel must not damage values:** every cell is text; fixed choices and
  links to other objects are dropdowns.
- **Only what the owner changed is written:** the workbook carries a hidden
  copy of the exported values. A cell that also changed in the vault since
  the export is a conflict, reported and never overwritten.
- **Deleting a row deletes nothing.**
- **Preview first**, then write after the owner's OK.
- **Stdlib only** (the plugin rule): `.xlsx` is written and read with
  `zipfile` + `xml.etree`. A spike (2026-10-12) confirmed it. Excel opens the
  file cleanly and shows the hidden key column, the frozen header, the
  coloured empty cells and the list dropdown. After the owner edited and
  saved in Excel, the reader got every value back: `007`, `1/2` and a typed
  `14/10` stayed text, Excel's shared-strings format was read, a new row came
  through with an empty key, and the hidden original sheet was untouched.
- **Company** is a dropdown of the vault's entities, but stays **text**; a
  value that is not an entity is accepted. Turning company into a real link
  to an entity belongs to #273 (comment added there).

## Design

### Which columns go in the Excel

Per object type, the CLI holds a fixed list of **owner-editable
properties**. It is product truth, not inferred:

| Object | Editable | Kind |
|---|---|---|
| Person | `person-name` | text (required) |
| | `relationship` | choice: colleague, direct-report, external |
| | `company` | entity name or free text (dropdown of entities) |
| | `role`, `email` | text |
| | `projects` | list of projects |
| Project | `project-name` | text (required) |
| | `status` | choice: active, paused, completed, cancelled |
| | `project-type` | choice: initiative, area-of-responsibility |
| | `entity` | one entity (required; **new rows only**) |
| | `owner` | one person (required) |
| | `parent` | one project |
| | `stakeholders` | list of people |
| Entity | `entity-name` | text (required) |
| | `status` | choice: prospect, active, dormant |
| | `entity-type` | choice: client, business-unit, partner, supplier, other |
| | `industry` | text |
| | `owner` | one person |
| | `parent` | one entity |

Never editable: the slug, `type`, `created`, `last-updated`, every
evening-run field (`meetings-7d/30d`, `messages-7d/30d`, `last-met`,
`key-people`, `state-updated`, `next-milestone`, `next-milestone-date`) and
`keywords` (managed by `project keywords`). Moving an existing project to
another entity is refused: its slug carries the entity.

**From the owner's table:** the CLI reads the object's `.base` (People.base,
Projects.base, Entities.base, wherever the owner keeps them) and takes the
view's `order`: the first view, or the one the owner names. For each column:

- `note.<x>` or a bare `<x>` with `x` editable → a column for `x`.
- `formula.<f>` → read the formula's expression; if it references **exactly
  one** editable property (as `note["x"]`, `note.x` or a bare identifier),
  the column is that property. Examples from the template: `state` → status,
  `kind` → project-type, `entity-link` → entity, `owner-name` → owner,
  `project-names` → projects, `part-of` → parent.
- Anything else (no editable property, or several) → left out.

The column header is the `displayName` the owner gave it. When two columns
map to the same property (Entities: `note.entity-name` and `formula.name`),
the first one wins. Editable properties that the view does not show are
appended after the view's columns, under their plain property name, so a
"fill in everything" pass can still reach them.

If the `.base` cannot be read (a hand-edit the parser does not understand),
the export falls back to the editable list's own order and says so.

**Reading `.base` without YAML:** a small, purpose-built reader for the
subset the export needs: `formulas:` (name → expression), `properties:`
(key → `displayName`) and `views:` (`name`, `order`). It is not a general
YAML parser. Anything outside that subset is ignored, never guessed.

### What the cells hold

- **Names instead of codes** for links: an entity's `entity-name`, a
  person's `person-name`, a project's `project-name`. On import, a name maps
  back to the slug, case-insensitively and exactly. A name that matches no
  object or two objects is not written; the preview lists it.
- **Lists** in one cell, separated by `; `.
- **Fixed choices** as their stored values (`active`, `direct-report`).
- **Empty** = no value. Clearing a cell that had a value clears the property
  (shown in the preview as a removal), except a required field, which is
  refused.

### The workbook

One sheet named after the table. Every cell is text (number format `@`);
the header row is bold and frozen; empty editable cells are light yellow.
Column A is the hidden key (`50-people/jan-peeters.md`); empty on a new row.
A dropdown on every choice and link column comes from a hidden `_lists`
sheet: one column per list, so long lists work. Choice columns refuse other
values. Link columns warn but accept other values, because the target may
not exist yet. A `veryHidden` `_original` sheet holds the exported values,
and a `_meta` sheet holds the table, view, object type, export time and the
format version. File: `_heavy-assets/<table>-update-<date>.xlsx`. The owner
fills it in there.

### Import

`table import --vault V --file F` reads the workbook and compares, per cell,
the owner's value, the `_original` value and the vault's current value:

| Owner vs original | Vault vs original | Result |
|---|---|---|
| same | any | nothing (the owner did not touch it) |
| changed | same | **write** |
| changed | changed, equal to the owner's | nothing (already so) |
| changed | changed, different | **conflict**: reported, not written |

A row with an empty key is **new**. Its required fields must be filled
(person: name; entity: name, status; project: name, entity, owner,
project-type, status). It is created through the existing creator, then its
remaining cells are written like an update. A row whose key no longer
exists in the vault (renamed or removed since the export) is reported and
skipped. A key row missing from the sheet is ignored: nothing is deleted.

Without `--apply` the import is a **dry run**: it returns the plan (counts,
then each change, conflict, refusal and unknown name) and writes nothing.
`--apply` writes exactly that plan, re-checked against the vault at write
time.

**Writes:** updates use the byte-preserving frontmatter edits
(`markdown.upsert_scalar_field`), lists as `[a, b]`. A changed name also
updates the note's `# H1` when the H1 still equals the old name (people,
entities; a project's body is machine-rendered, so only `project-name`).
Each write stamps nothing else; `last-updated` keeps its existing meaning.

### The skill

A small skill (name: `/update-tables`; triggers: "fill in my People table",
"add projects in Excel", "update my entities"):

1. Ask which table (People / Projects / Entities) if it isn't clear.
   Optionally which view.
2. `table export`, then say where the file is and that only the yellow cells
   and new rows matter.
3. When the owner says it's done: `table import` (dry run), then show the
   preview in a few lines. For unknown names: *"LLBG is not an entity: create
   it, or keep it as text?"* (create = `entity ensure` first, then import
   again). Wait for OK.
4. `table import --apply`, then a short summary.

### Not running twice

The import takes the `runlock` (#277) for its write step, routine
`update-tables`, so it never writes while the evening run or an on-demand
sync is processing.

## Testing

- **Spike → fixtures:** keep one workbook as Excel saved it (shared strings,
  theme, docProps) as a test fixture, so the reader is tested against the real
  Excel format, not only against our own writer.
- **Export:** columns follow the view's order and display names; formula
  columns map to their one property; non-editable and multi-property columns
  are left out; unshown editable properties are appended; a `.base` the
  reader cannot parse falls back with a warning; names instead of slugs;
  `_original`, `_lists` and `_meta` are present; all cells are text.
- **Import:** the four rows of the comparison table; a new person, entity
  and project each through its creator; a new project without an entity is
  refused; an unknown and an ambiguous name; clearing a required field is
  refused; an existing project's entity change is refused; a deleted row
  deletes nothing; a stale key; a dry run writes nothing; `--apply` writes the
  same plan; a modified `.base` with an extra editable column round-trips.
- **Skill contract:** dry run before `--apply`, the OK in between, `runlock`
  around the write, and nothing written by the model itself.

## Out of scope

- To Do's, Meetings and Decisions tables.
- Company as a real link to an entity (#273).
- Body content (only frontmatter).
- Deleting objects.

## Release

New CLI (`table export`, `table import`), new module(s), new skill, tests.
No vault structure change, no migration. CHANGELOG entry; Start here gets
one line. Version bump.
