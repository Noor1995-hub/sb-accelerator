# Template Extraction — Design (Issue #1)

**Date:** 2026-08-22
**Status:** Approved in brainstorm, pending final review
**Parent spec:** `2026-08-22-second-brain-accelerator-design.md` (v1 BOM item 1)
**Scope:** Populate `template/` with the L0 vault skeleton — clean-room, no busdev copy-paste.

## Decisions made in brainstorm

| Decision | Choice | Rationale |
|---|---|---|
| Ontology generalization | `Client` object → `Entity` | Only role-specific object of the five; "entity" covers clients, business units, partners, suppliers. Rename now is free; post-deployment it's a consultant-run migration |
| Folder numbering | Fresh decimal scheme (10–99), not busdev's | Busdev numbering carries accidents (two 11-prefixes). Ports are clean-room rewrites anyway, so paths get retyped regardless; a path map (below) keeps the mapping authoritative |
| Inbox | `10-inbox/` landing zone **in front of** meetings, not replacing them | Meeting stays a first-class object with its own home; the inbox holds *unprocessed* capture (GTD/PARA pattern). Skills read from it, never leave outputs in it |
| Obsidian plugins | Dataview + reading comfort (minimal-settings, style-settings, notebook-navigator, Minimal theme) — **config files only, no binaries** | Binaries rot and raise license questions; consultant installs at provisioning (pre-flight checklist, issue #8) |
| `/report-feedback` nudge rule in CLAUDE.md | Deferred to issue #7 | Rule must not ship before the skill it invokes |
| Client-side git | None — template CLAUDE.md has **no git section** | Parent spec decision; busdev's CLAUDE.md is git-heavy, so this is a deliberate subtraction |
| Lab-only machinery | Confidence shadow-mode / calibration fields omitted from product ontology | Lab experiment, not product. Recorder provenance fields stay (generic, optional) |

## Folder skeleton

```
template/
├── 10-inbox/                  # unprocessed capture: transcripts, voice memos, forwarded
│   └── README.md              #   emails, recorder dumps. EA triage zone. Skills consume
│                              #   from here; processed outputs never land here
├── 20-meetings/               # Meeting objects (flat)
│   └── Meetings.base
├── 30-projects/               # Project objects: {slug}/index.md + {slug}/decisions/
│   ├── Projects.base
│   └── Decisions.base
├── 40-entities/               # Entity objects: {slug}/dossier.md
│   └── Entities.base
├── 50-people/                 # Person objects: {slug}.md
│   └── People.base
├── 60-daily-notes/            # daily canvas; morning/evening briefs land here
├── 70-resources/              # guides, source material
├── 80-thoughts-ideas/         # idea seeds, drafts
├── 90-archive/                # completed/historical items
├── 95-private/                # exec-private; excluded from Obsidian Sync (provisioning step)
├── 99-workflow-config/
│   ├── context/               # context portfolio — five guided placeholder files (below)
│   └── reference/
│       ├── ontology.md        # authoritative object model (clean-room rewrite)
│       └── lessons.md         # self-improvement log scaffold (headers + usage note, no entries)
├── _heavy-assets/             # generated binaries (.pptx/.xlsx/.pdf/...); sync-excluded
├── .obsidian/                 # config files only — see below
├── CLAUDE.md                  # vault instructions (de-personalized rewrite)
├── README.md                  # what this template is + instantiation/provisioning notes
└── structure-version          # plain text file containing: 1
```

- Folders that would otherwise be empty in git carry a `.gitkeep`.
- The 90s band is system space (archive / private / config), per Johnny Decimal convention.
- `_heavy-assets/` stays underscore-prefixed: deliberately outside the numbered taxonomy, sorts to top.

## Path map (busdev → template)

The single authoritative mapping. Every port task (issues 12–20) and `/process-upstream`
(issue #6) rewrites paths against this table — no per-task improvisation.

| busdev | template | Notes |
|---|---|---|
| — (no equivalent) | `10-inbox/` | net-new landing zone |
| `10-meetings/` | `20-meetings/` | |
| `11-clients/{slug}/dossier.md` | `40-entities/{slug}/dossier.md` | object type `client` → `entity` |
| `11-daily-notes/` | `60-daily-notes/` | |
| `20-projects/{slug}/` | `30-projects/{slug}/` | `decisions/` subfolder pattern unchanged |
| `21-people/` | `50-people/` | |
| `40-resources/` | `70-resources/` | |
| `50-thoughts-ideas/` | `80-thoughts-ideas/` | |
| `90-archive/` | `90-archive/` | unchanged |
| `92-private/` | `95-private/` | |
| `99-workflow-config/` | `99-workflow-config/` | unchanged; only `context/` and `reference/` ship |
| `_heavy-assets/` | `_heavy-assets/` | unchanged |
| frontmatter `client:` (on Project) | `entity:` | join key rename |
| `Clients.base` | `Entities.base` | |
| `12-boardroom/`, `30-knowledge/`, `Snipd/`, `91-Clippings/`, `Excalidraw/` | — | do not ship (out of v1 / L2 / personal tooling) |

## Ontology (`99-workflow-config/reference/ontology.md`)

Five objects: **Meeting · Project · Person · Decision · Entity**. Relationships live in
YAML frontmatter (wikilinks / slug joins), not folder hierarchy; curation happens in Bases.
The template's ontology.md is a clean-room rewrite: same object model as busdev's, with the
renames above applied, lab-only fields dropped, and **all examples invented** (e.g.
`acme-industries`) — zero real client, person, or busdev references.

Schemas ship as busdev's ontology defines them, with these deltas:

**Entity** — `40-entities/{slug}/dossier.md` · `Entities.base`
- Required: `type: entity`, `entity-name`, `slug` (= folder name = `entity:` value on projects), `status`
- Optional: `entity-type`, `industry`, `owner`, `created`, `last-updated`
- Enums: `status` = prospect | active | dormant · `entity-type` (suggested vocab) = client | business-unit | partner | supplier | other. The commercial-leader archetype narrows the working vocabulary to client-first; the enum itself stays generic.
- Dates unquoted ISO (quoted dates silently break Bases/Dataview).

**Project** — `30-projects/{slug}/index.md`: `client` field becomes `entity` (slug join to Entity). All other fields and enums as busdev (`project-type` keeps `presales | delivery | internal | area-of-responsibility`).

**Meeting** — `20-meetings/`: required/triage/enum fields as busdev. Recorder provenance fields (`source-drive-id`, `source-filename`) documented as optional. Confidence shadow-mode fields (`confidence`, `confidence-reasons`) and the calibration machinery are **omitted** — lab-only.

**Person, Decision** — as busdev, with template paths.

## Bases

Five `.base` views, one per object, living in their object folders (locations in the
skeleton above). Rewritten for template paths and the entity rename — view/filter/column
*structure* mirrors busdev's, content clean-roomed. Meetings.base keeps the triage views
(`needs-review`, checkbox confirm) since ported capture skills depend on that flow.

## Context portfolio (`99-workflow-config/context/`)

Five guided placeholder files: `identity.md`, `role-and-responsibilities.md`,
`communication-style.md`, `tools-and-systems.md`, `preferences-and-constraints.md`.
Each file contains: (a) one paragraph on what belongs in it and who reads it, (b) the
interview questions that fill it, (c) a clearly marked empty slot section. These are the
defined target for `/setup-my-brain` (issue #3) — the interview writes into these slots.

## Template CLAUDE.md

De-personalized rewrite (never a trimmed copy). Sections:

1. **What this vault is** — personal AI operating system for the exec, operated with the EA
2. **Golden rules** — generic forms of: understand before building, human in the loop for external output, epistemic honesty, build on what exists
3. **Vault structure** — the skeleton table
4. **Ontology pointer** — objects live in `99-workflow-config/reference/ontology.md`
5. **Key patterns** — slug conventions (lowercase-hyphenated; entity slugs = folder = join key), decision-note pattern (atomic notes, supersession edges, never delete), heavy-assets rule (generated binaries → `_heavy-assets/`, stub link in source project)
6. **Inbox discipline** — what lands in `10-inbox/`, EA triage rhythm, skills consume from it
7. **Self-improvement loop** — corrections logged to `reference/lessons.md`, recurring patterns promoted

Explicitly absent: git workflow (no client-side git), the `/report-feedback` nudge (issue #7),
delaware-internal references, any personal or client content.

## `.obsidian/` config

Files shipped: `community-plugins.json` (dataview, obsidian-minimal-settings,
obsidian-style-settings, notebook-navigator), `appearance.json` (Minimal theme named),
`core-plugins.json` (Bases + daily notes enabled), `daily-notes.json` (folder →
`60-daily-notes/`), `app.json` (two settings: `attachmentFolderPath` →
`70-resources/attachments` so pasted images never litter the vault root, and
`alwaysUpdateLinks: true` so file renames keep links intact). **No
plugin/theme binaries, no `workspace.json`, no sync credentials.**

Obsidian Sync exclusions (`95-private/`, `_heavy-assets/`) cannot be preconfigured in
files (Sync requires login); they are a documented provisioning step in the template
README and the pre-flight checklist (issue #8).

## Validation & constraints

- `python scripts/lint_plugin.py` — clean-room lint passes over `template/`
- `python scripts/validate_template.py` — populated template must carry `CLAUDE.md` + `structure-version`
- Clean-room hard rule: no delaware clients, no people names, no busdev paths/content anywhere in `template/`. Vendor name "delaware" permitted but used sparingly (README only)
- No `plugin/` changes in this issue → no plugin version bump required

## Out of scope (this issue)

Skills (issues 3–7, 12–20), playbooks (#8), migrations tooling (#4), the `/report-feedback`
nudge rule (#7), archetype docs beyond the enum note above, `sb-dist` packaging (#10).

## Impact on later issues

- **Ports (2, 12–20):** rewrite against the path map and the `entity` rename. Briefs for
  port tasks must reference this spec's path map table.
- **`/setup-my-brain` (#3):** fills the context portfolio slots defined here.
- **`/upgrade-vault` (#4):** consumes `structure-version`; migration log location is that
  issue's decision.
- **Playbooks (#8):** provisioning checklist owns plugin installation + sync exclusions.
