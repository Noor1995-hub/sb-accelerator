# Template Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `template/` with the L0 vault skeleton — folders, markers, `.obsidian` config, ontology, context portfolio, and `.base` views — per the approved design.

**Architecture:** Pure content authoring inside `template/`; no code changes. Every file's content is pinned in this plan, so implementers work entirely from the plan + spec. Validation is the repo's existing three checks.

**Tech Stack:** Markdown, Obsidian `.base` YAML, Obsidian `.obsidian/*.json` config, existing Python validators.

**Spec:** `docs/superpowers/specs/2026-08-22-template-extraction-design.md`

## Global Constraints

- **Clean-room (hard rule):** the case-insensitive substrings `michael`, `bulthe`, `bulthé`, `busdev` must not appear anywhere under `template/`. Refer to the source vault only as "the upstream lab vault" — and only in repo docs, never in template content. All examples are invented (`acme-industries`, `jordan-reyes`).
- **Isolation:** implementers do NOT read any files outside this repository. Everything needed is in this plan and the spec. This is a process-level clean-room guarantee.
- **Entity rename is binding:** object type `entity`, folder `40-entities/`, join field `entity:` on projects. Never `client` as a type/field/folder (the word may appear inside an enum vocabulary value `client` for `entity-type`, and in prose about client deployments in `template/README.md` — those are the only permitted uses).
- **No `plugin/` changes** in any task → no plugin version bump.
- Every commit message ends with the exact trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`
- Validation commands (run from repo root):
  `python3 scripts/lint_plugin.py` · `python3 scripts/validate_template.py` · `python3 -m pytest scripts/tests -q`
- Dates in any YAML frontmatter examples are unquoted ISO (`2026-02-07`), never quoted.

---

### Task 1: Folder skeleton, markers, `.obsidian` config, READMEs

**Files:**
- Create: `template/structure-version`
- Create: `template/10-inbox/README.md`
- Create: `template/.obsidian/app.json`, `template/.obsidian/appearance.json`, `template/.obsidian/community-plugins.json`, `template/.obsidian/core-plugins.json`, `template/.obsidian/daily-notes.json`
- Create: `.gitkeep` in: `template/20-meetings/`, `template/30-projects/`, `template/40-entities/`, `template/50-people/`, `template/60-daily-notes/`, `template/70-resources/attachments/`, `template/80-thoughts-ideas/`, `template/90-archive/`, `template/95-private/`, `template/99-workflow-config/context/`, `template/99-workflow-config/reference/`, `template/_heavy-assets/`
- Modify: `template/README.md` (full replacement, content below)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: the folder tree all later tasks write into; `structure-version` marker; sync-exclusion + provisioning documentation in `template/README.md`

- [ ] **Step 1: Observe the pre-state (this task's "failing test")**

Run: `python3 scripts/validate_template.py; echo "exit=$?"`
Expected: no output, `exit=0` (unpopulated skeleton is the valid bootstrap state).

- [ ] **Step 2: Create the folders and `.gitkeep` files**

```bash
cd template
mkdir -p 10-inbox 20-meetings 30-projects 40-entities 50-people 60-daily-notes \
  70-resources/attachments 80-thoughts-ideas 90-archive 95-private \
  99-workflow-config/context 99-workflow-config/reference _heavy-assets .obsidian
for d in 20-meetings 30-projects 40-entities 50-people 60-daily-notes \
  70-resources/attachments 80-thoughts-ideas 90-archive 95-private \
  99-workflow-config/context 99-workflow-config/reference _heavy-assets; do
  touch "$d/.gitkeep"
done
```

- [ ] **Step 3: Write `template/structure-version`**

File content (exactly one line):

```
1
```

- [ ] **Step 4: Write the five `.obsidian` config files**

`template/.obsidian/app.json`:

```json
{
  "attachmentFolderPath": "70-resources/attachments",
  "alwaysUpdateLinks": true
}
```

`template/.obsidian/appearance.json`:

```json
{
  "cssTheme": "Minimal"
}
```

`template/.obsidian/community-plugins.json`:

```json
[
  "dataview",
  "obsidian-minimal-settings",
  "obsidian-style-settings",
  "notebook-navigator"
]
```

`template/.obsidian/core-plugins.json`:

```json
{
  "file-explorer": true,
  "global-search": true,
  "switcher": true,
  "graph": true,
  "backlink": true,
  "canvas": false,
  "outgoing-link": true,
  "tag-pane": true,
  "footnotes": false,
  "properties": true,
  "page-preview": true,
  "daily-notes": true,
  "templates": false,
  "note-composer": true,
  "command-palette": true,
  "slash-command": true,
  "editor-status": true,
  "bookmarks": true,
  "markdown-importer": false,
  "zk-prefixer": false,
  "random-note": false,
  "outline": true,
  "word-count": true,
  "slides": false,
  "audio-recorder": false,
  "workspaces": false,
  "file-recovery": true,
  "publish": false,
  "sync": true,
  "bases": true,
  "webviewer": false
}
```

`template/.obsidian/daily-notes.json`:

```json
{
  "folder": "60-daily-notes"
}
```

- [ ] **Step 5: Write `template/10-inbox/README.md`**

```markdown
# Inbox

The landing zone for anything not yet processed into a vault object: meeting
transcripts, voice memos, forwarded emails, recorder exports, documents to file.

Rules:

- **Everything unprocessed lands here first.** Drop files in; don't sort them.
- **Processing skills consume from here** and produce meeting notes, project
  updates, or dossier entries in their proper folders.
- **Nothing lives here.** A file still in the inbox after a few days means
  processing is overdue — the assistant sweeps this folder as part of the
  daily rhythm.
- Skills never leave their outputs in this folder.
```

- [ ] **Step 6: Replace `template/README.md`**

```markdown
# Vault template

The L0 vault skeleton, instantiated once per client deployment: folder
structure, `.obsidian/` configuration, `.base` views, vault instructions
(`CLAUDE.md`), a context portfolio with guided placeholder slots, and a
`structure-version` marker consumed by `/upgrade-vault`.

## Instantiating

Copy the contents of this directory (including `.obsidian/`) into the new
vault location on the client machine. Do not initialize git in the vault —
the vault has no git by design; snapshots and sync history cover recovery.

## Provisioning steps that cannot ship as files

Obsidian Sync requires a signed-in account, so the consultant configures
these by hand at provisioning (see the pre-flight checklist playbook):

1. **Install community plugins** listed in `.obsidian/community-plugins.json`
   (Dataview, Minimal Theme Settings, Style Settings, Notebook Navigator) and
   the **Minimal** theme.
2. **Exclude from Obsidian Sync:** `95-private/` (exec-private folder) and
   `_heavy-assets/` (generated binaries).
3. Connect Obsidian Sync on both machines (exec + assistant) and verify the
   exclusions on each.

## Markers

- `structure-version` — plain integer, bumped only by structure migrations
  under `migrations/`; read by `/upgrade-vault`.
```

- [ ] **Step 7: Verify the expected intermediate state**

Run: `python3 scripts/validate_template.py; echo "exit=$?"`
Expected output (exactly):

```
populated template/ is missing CLAUDE.md
exit=1
```

This failure is **correct at this point** — `CLAUDE.md` is Task 2's deliverable. Also run:

Run: `python3 scripts/lint_plugin.py && python3 -c "import json,glob; [json.load(open(p)) for p in glob.glob('template/.obsidian/*.json')]; print('json ok')"`
Expected: `json ok` (lint prints nothing on success).

- [ ] **Step 8: Commit**

```bash
git add template/
git commit -m "feat(template): folder skeleton, structure-version, .obsidian config, READMEs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Template `CLAUDE.md`

**Files:**
- Create: `template/CLAUDE.md`

**Interfaces:**
- Consumes: folder tree from Task 1
- Produces: the vault's behavioral instructions; references `99-workflow-config/reference/ontology.md` (created in Task 3 — forward reference is intended) and `99-workflow-config/reference/lessons.md` (Task 3)

- [ ] **Step 1: Write `template/CLAUDE.md`**

Exact content:

```markdown
# Vault Instructions

## What This Vault Is

An Obsidian-based second brain for one executive, operated jointly with their
assistant. The assistant runs capture and processing (transcripts, voice
memos, dossiers, briefs); the executive consumes briefs, asks questions, and
browses. Claude is the working interface to everything in here.

## Golden Rules

1. **Understand before acting** — when context is missing, ask; don't fill
   gaps with guesses. Exception: trivial fixes.
2. **Human in the loop** — nothing generated here goes to external parties
   without the executive's or assistant's explicit review.
3. **Be epistemically honest** — state what you know, what you infer, and
   what you guess. Never present a guess as a fact.
4. **Build on what exists** — check for existing notes, dossiers, and prior
   work before creating anything new.
5. **One file, one purpose** — never create files "just in case."

## Vault Structure

| Folder | Holds |
|---|---|
| `10-inbox/` | Unprocessed capture — transcripts, voice memos, forwarded emails. See its README |
| `20-meetings/` | Meeting notes (one file per meeting) |
| `30-projects/{slug}/` | Projects and initiatives — `index.md` hub + `decisions/` log |
| `40-entities/{slug}/` | Dossiers on organizations you work with — `dossier.md` per entity |
| `50-people/` | People you work with — one note per person |
| `60-daily-notes/` | Daily canvas; morning and evening briefs land here |
| `70-resources/` | Guides, source material, attachments |
| `80-thoughts-ideas/` | Idea seeds and drafts |
| `90-archive/` | Completed and historical items |
| `95-private/` | Executive-private notes — excluded from sync, invisible to the assistant |
| `99-workflow-config/` | Context portfolio, object model reference, lessons log |
| `_heavy-assets/` | Generated binaries (.pptx/.xlsx/.pdf/…) — excluded from sync |

## Object Model

Five object types: **Meeting · Project · Person · Decision · Entity**.
Relationships live in YAML frontmatter (wikilinks and slug joins), not folder
hierarchy; curation happens in the `.base` views, not by browsing folders.
The authoritative schemas, enums, and join keys are in
`99-workflow-config/reference/ontology.md` — consult it before writing any
object frontmatter.

## Key Patterns

### Slugs

Lowercase, hyphenated: `acme-industries`, `jordan-reyes`. An entity's slug
MUST equal its folder name AND the `entity:` value on its projects — it is
the join key.

### Decision Notes

Each material decision on a project is an atomic note at
`30-projects/{slug}/decisions/YYYY-MM-DD-{kebab-summary}.md`. Body:
`**Decision** — / **Why** — / **Implications**`. Supersession is a wikilink
edge (`supersedes: [[YYYY-MM-DD-prior]]`). **Never delete a decision** —
status flips only (`active` → `superseded` / `withdrawn`). The trace is
permanent.

### Heavy Assets

Generated binaries (`.pptx`, `.xlsx`, `.pdf`, `.docx`, `.zip`) go to
`_heavy-assets/` with a descriptive, project-prefixed filename — never into
content folders. Add a stub link under `## Deliverables` in the source
project's `index.md`.

### Inbox Discipline

Unprocessed capture lands in `10-inbox/` and only there. Processing skills
consume from the inbox and write results to the proper object folders. Skill
outputs never land in the inbox.

## Self-Improvement Loop

After any correction or pushback from the executive or assistant:

1. **Log it** — append the pattern to
   `99-workflow-config/reference/lessons.md` with date, what went wrong, and
   the rule that prevents it.
2. **Apply immediately** — follow the new rule for the rest of the session.
3. **Promote when recurring** — a pattern appearing 2–3 times graduates into
   this file or the relevant context-portfolio file; mark it `[graduated]`.

At session start, scan `lessons.md` for ungraduated patterns relevant to the
task at hand.
```

- [ ] **Step 2: Verify validators go green**

Run: `python3 scripts/validate_template.py && python3 scripts/lint_plugin.py && echo ALL_GREEN`
Expected: `ALL_GREEN` (both silent on success).

- [ ] **Step 3: Commit**

```bash
git add template/CLAUDE.md
git commit -m "feat(template): de-personalized vault CLAUDE.md

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Ontology and lessons scaffold

**Files:**
- Create: `template/99-workflow-config/reference/ontology.md`
- Create: `template/99-workflow-config/reference/lessons.md`
- Delete: `template/99-workflow-config/reference/.gitkeep`

**Interfaces:**
- Consumes: folder tree from Task 1
- Produces: the authoritative schemas Task 5's `.base` views filter on — field names `entity-name`, `entity`, `review_status`, `reviewed`, `archived`, `project-type`, `relationship`, `status`, `summary` are binding for Task 5

- [ ] **Step 1: Write `template/99-workflow-config/reference/ontology.md`**

Exact content:

```markdown
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
```

- [ ] **Step 2: Write `template/99-workflow-config/reference/lessons.md`**

```markdown
# Lessons & Corrections Log

Append-only log of corrections and pushback, written by the self-improvement
loop in `CLAUDE.md`. One entry per pattern:

- **YYYY-MM-DD — what went wrong:** one line. **Rule:** the rule that
  prevents it. Mark `[graduated]` once promoted to a permanent file.

<!-- entries below this line -->
```

- [ ] **Step 3: Remove the placeholder keep-file and verify**

```bash
git rm --quiet template/99-workflow-config/reference/.gitkeep
python3 scripts/validate_template.py && python3 scripts/lint_plugin.py && echo ALL_GREEN
```

Expected: `ALL_GREEN`.

- [ ] **Step 4: Commit**

```bash
git add template/99-workflow-config/reference/
git commit -m "feat(template): ontology (entity object model) + lessons scaffold

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Context portfolio — five guided placeholder files

**Files:**
- Create: `template/99-workflow-config/context/identity.md`
- Create: `template/99-workflow-config/context/role-and-responsibilities.md`
- Create: `template/99-workflow-config/context/communication-style.md`
- Create: `template/99-workflow-config/context/tools-and-systems.md`
- Create: `template/99-workflow-config/context/preferences-and-constraints.md`
- Delete: `template/99-workflow-config/context/.gitkeep`

**Interfaces:**
- Consumes: folder tree from Task 1
- Produces: the interview target for `/setup-my-brain` (issue #3). Every file follows the same three-part shape: **Purpose** (one paragraph: what belongs here, who reads it), **Interview questions** (the exact questions below), **Content slot** (an HTML comment marker pair the onboarding skill writes between)

Each file uses this skeleton (shown once; repeat per file with its own content):

```markdown
# <Title>

> **Placeholder.** Filled by the onboarding interview (`/setup-my-brain`).
> Until then, Claude treats this file as empty context.

## Purpose

<purpose paragraph>

## Interview questions

<question list>

## Content

<!-- setup-my-brain:begin -->
<!-- setup-my-brain:end -->
```

- [ ] **Step 1: Write the five files**

Per-file titles, purpose paragraphs, and question lists (use these verbatim inside the skeleton above):

**`identity.md` — "Identity"**
Purpose: Who the executive is, in their own words. Read by every skill that writes on their behalf or addresses them; keep it short and factual.
Questions:
- What is your full name, and what do people actually call you?
- What is your role title and company?
- Which languages do you work in, and which do you prefer for briefs?
- What is your time zone and typical working window?

**`role-and-responsibilities.md` — "Role & Responsibilities"**
Purpose: What the executive owns and is accountable for. Read by briefing and processing skills to judge relevance — what deserves attention versus noise.
Questions:
- What areas, functions, or units do you own?
- What are the 3–5 metrics or outcomes you are judged on?
- Who reports to you directly?
- Which recurring forums (boards, steercos, councils) are you accountable in?
- What decisions are yours alone, and which do you share or delegate?

**`communication-style.md` — "Communication Style"**
Purpose: How Claude should sound when writing as or to the executive. Read by every skill that drafts prose.
Questions:
- Do you prefer bullets or narrative prose in briefs?
- How formal should drafts in your name be?
- Any words, phrases, or tones to avoid?
- How direct should pushback be when Claude disagrees with you?
- Which language(s) for which audiences?

**`tools-and-systems.md` — "Tools & Systems"**
Purpose: The systems around the vault. Read by capture and sync skills to know where information comes from and where outputs must land.
Questions:
- Calendar and mail platform (tenant, shared mailboxes)?
- Meeting platform(s), and is transcription enabled?
- Which recorder do you use for non-platform meetings?
- Where do heavy files live (drive, sites)?
- Which business systems matter for context (CRM, ERP, BI)?
- What tooling does your assistant run daily?

**`preferences-and-constraints.md` — "Preferences & Constraints"**
Purpose: Boundaries and rhythm. Read by every skill; constraints here override convenience everywhere else.
Questions:
- What kinds of content must go to `95-private/` (invisible to your assistant)?
- What must never leave the vault without your explicit review?
- What is your assistant allowed to see, do, and sign off on?
- When do you want your morning brief and evening digest?
- Any confidentiality rules from your company that Claude must enforce?

- [ ] **Step 2: Remove the keep-file and verify**

```bash
git rm --quiet template/99-workflow-config/context/.gitkeep
python3 scripts/validate_template.py && python3 scripts/lint_plugin.py && echo ALL_GREEN
```

Expected: `ALL_GREEN`.

- [ ] **Step 3: Commit**

```bash
git add template/99-workflow-config/context/
git commit -m "feat(template): context portfolio with guided placeholder slots

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: The five `.base` views

**Files:**
- Create: `template/20-meetings/Meetings.base`
- Create: `template/30-projects/Projects.base`
- Create: `template/30-projects/Decisions.base`
- Create: `template/40-entities/Entities.base`
- Create: `template/50-people/People.base`
- Delete: the `.gitkeep` in `template/20-meetings/`, `template/30-projects/`, `template/40-entities/`, `template/50-people/`

**Interfaces:**
- Consumes: field names and enums exactly as defined in Task 3's ontology (`review_status`, `reviewed`, `archived`, `entity-name`, `entity-type`, `project-type`, `relationship`, `summary`)
- Produces: the curation surface referenced by template `CLAUDE.md` ("curation happens in Bases")

- [ ] **Step 1: Write `template/20-meetings/Meetings.base`**

```yaml
filters:
  and:
    - file.inFolder("20-meetings")
    - file.ext == "md"
formulas:
  open: link(file.path, "→")
properties:
  formula.open:
    displayName: " "
  date:
    displayName: Date
  calendar-subject:
    displayName: Subject
  calendar_match:
    displayName: Cal
  attendees:
    displayName: Attendees
  projects:
    displayName: Projects
  review_status:
    displayName: Review Status
  reviewed:
    displayName: ✓ Reviewed
  archived:
    displayName: 🗑 Archive
  recording-duration:
    displayName: Duration
views:
  - type: table
    name: Triage
    filters:
      and:
        - or:
            - review_status == "needs-review"
            - review_status == "needs-attention"
        - reviewed != true
        - archived != true
    order:
      - formula.open
      - date
      - calendar-subject
      - calendar_match
      - attendees
      - projects
      - reviewed
      - archived
      - recording-duration
      - source
      - type
    sort:
      - property: date
        direction: DESC
    rowHeight: medium
  - type: table
    name: All Meetings
    order:
      - formula.open
      - date
      - calendar-subject
      - type
      - attendees
      - projects
      - review_status
      - recording-duration
    sort:
      - property: date
        direction: DESC
```

- [ ] **Step 2: Write `template/30-projects/Projects.base`**

```yaml
filters:
  and:
    - file.inFolder("30-projects")
    - file.name == "index"
formulas:
  open: link(file.path, "→")
properties:
  formula.open:
    displayName: " "
  project-name:
    displayName: Project
  status:
    displayName: Status
  project-type:
    displayName: Type
  entity:
    displayName: Entity
  owner:
    displayName: Owner
  next-milestone:
    displayName: Next Milestone
  next-milestone-date:
    displayName: Due
  last-updated:
    displayName: Updated
views:
  - type: table
    name: Active
    filters:
      and:
        - status == "active"
    order:
      - formula.open
      - project-name
      - project-type
      - entity
      - next-milestone
      - next-milestone-date
      - last-updated
    sort:
      - property: last-updated
        direction: DESC
  - type: table
    name: All
    order:
      - formula.open
      - project-name
      - status
      - project-type
      - entity
      - owner
      - last-updated
    sort:
      - property: last-updated
        direction: DESC
```

- [ ] **Step 3: Write `template/30-projects/Decisions.base`**

```yaml
filters:
  and:
    - type == "decision"
formulas:
  open: link(file.path, "→")
properties:
  formula.open:
    displayName: " "
  summary:
    displayName: Decision
  project:
    displayName: Project
  date:
    displayName: Date
  status:
    displayName: Status
  tags:
    displayName: Tags
  supersedes:
    displayName: Supersedes
views:
  - type: table
    name: Active
    filters:
      and:
        - status == "active"
    order:
      - formula.open
      - summary
      - project
      - date
      - tags
    sort:
      - property: date
        direction: DESC
  - type: table
    name: All
    order:
      - formula.open
      - summary
      - project
      - date
      - status
      - tags
      - supersedes
    sort:
      - property: date
        direction: DESC
```

- [ ] **Step 4: Write `template/40-entities/Entities.base`**

```yaml
filters:
  and:
    - file.name == "dossier"
    - type == "entity"
formulas:
  open: link(file.path, "→")
properties:
  formula.open:
    displayName: " "
  entity-name:
    displayName: Entity
  entity-type:
    displayName: Type
  status:
    displayName: Status
  industry:
    displayName: Industry
  owner:
    displayName: Owner
  last-updated:
    displayName: Updated
views:
  - type: table
    name: All
    order:
      - formula.open
      - entity-name
      - entity-type
      - status
      - industry
      - owner
      - last-updated
    sort:
      - property: last-updated
        direction: DESC
  - type: table
    name: Active
    filters:
      and:
        - status == "active"
    order:
      - formula.open
      - entity-name
      - entity-type
      - industry
      - owner
      - last-updated
    sort:
      - property: last-updated
        direction: DESC
  - type: table
    name: Prospects
    filters:
      and:
        - status == "prospect"
    order:
      - formula.open
      - entity-name
      - industry
      - last-updated
    sort:
      - property: last-updated
        direction: DESC
```

- [ ] **Step 5: Write `template/50-people/People.base`**

```yaml
filters:
  and:
    - file.inFolder("50-people")
    - file.ext == "md"
    - person-name != null
formulas:
  open: link(file.path, "→")
properties:
  formula.open:
    displayName: " "
  person-name:
    displayName: Name
  relationship:
    displayName: Relationship
  company:
    displayName: Company
  role:
    displayName: Role
  projects:
    displayName: Projects
  meetings-30d:
    displayName: Meetings (30d)
  last-updated:
    displayName: Updated
views:
  - type: table
    name: All
    order:
      - formula.open
      - person-name
      - relationship
      - company
      - role
      - projects
      - meetings-30d
      - last-updated
    sort:
      - property: last-updated
        direction: DESC
  - type: table
    name: Uncurated
    filters:
      and:
        - relationship == null
    order:
      - formula.open
      - person-name
      - company
      - role
      - meetings-30d
    sort:
      - property: meetings-30d
        direction: DESC
```

- [ ] **Step 6: Remove keep-files, verify YAML parses, run all validators**

```bash
git rm --quiet template/20-meetings/.gitkeep template/30-projects/.gitkeep \
  template/40-entities/.gitkeep template/50-people/.gitkeep
python3 -c "
import yaml, glob
for p in glob.glob('template/**/*.base', recursive=True):
    yaml.safe_load(open(p))
print('yaml ok')"
python3 scripts/validate_template.py && python3 scripts/lint_plugin.py \
  && python3 -m pytest scripts/tests -q
```

Expected: `yaml ok`, then silent validators, then pytest all passing.

- [ ] **Step 7: Commit**

```bash
git add template/
git commit -m "feat(template): the five object .base views

Co-Authored-By: Claude <noreply@anthropic.com>"
```
