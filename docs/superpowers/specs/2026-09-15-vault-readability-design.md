# Vault readability: daily note v2 and project index v2

**Date:** 2026-09-15 · **Status:** design, awaiting Michael's review
**Issue:** none yet (this spec is the issue) · **Spin-offs:** #183 (project matching learns from triage), #184 (entity dossier sync)

## 1. Problem

The evening run writes content that is excellent for the model to read back and exhausting for the vault owner to scan. Observed on DryRunVault, 2026-09-16 daily note and the Imagine More project index:

- The recap is a wall of prose: an "At a glance" line with comma-delimited lists, theme bullets of 60+ words, a project pulse whose links do not open anything.
- The catch-up banner appears twice (the CLI prepends it and the model also writes it).
- "Watch" mixes content risks (no owner for DEME programme management) with sync mechanics (duplicate ledger bug, fetch error, out-of-reach transcript).
- Meeting prep is one line with three `·`-separated facts.
- `[[deme-supply-chain-transformation]]` and `[[deme]]` are unresolved in Obsidian: projects and entities are folders (`<slug>/index.md`, `<slug>/dossier.md`) and Obsidian resolves a bare `[[name]]` by file name only, never by alias. Clicking one creates an empty note in the vault root (three exist in DryRunVault).
- The project index `Now` callout has grown to bullets of 600+ words; `Open Items` is four bullets that each run for a screen. The skill says "exactly 5 bullets" and puts no cap on a bullet, so prose instructions did not bind.

Michael reviewed five hand-built mock-ups rendered in Obsidian (`80-thoughts-ideas/readability-proposals/` in DryRunVault, throwaway) and picked **daily note B (progressive disclosure)** with two tweaks, and **project index A (brief, then background)**.

## 2. Design principles

1. **Formatting is code, content is judgment.** The CLI renders every machine region from a structured payload; the model supplies facts and phrasing. This is how caps (bullet count, word count, row count) and link hygiene become enforceable instead of aspirational. It is the daily-note contract extended to the recap's interior and to the project index body.
2. **Progressive disclosure.** Headlines visible, detail behind a fold. Folded callouts (`[!type]-`) are native and durable; nothing here needs a plugin beyond what ships.
3. **Human areas are never regenerated.** Notes and Actions under each meeting, End of day, anything outside markers.
4. **Every identity link opens the object.** Entities and projects are always written as path links with the vault's display name; the CLI normalises, the model does not have to remember.
5. **No new wall time in the evening run.** Structured payloads replace prose the model already writes; the project-state subagent returns JSON instead of editing Markdown, which is less work, not more.

## 3. Daily note v2

### 3.1 Rendered shape

```markdown
---
date: 2026-09-16
type: daily-note
---

# 2026-09-16 · Wednesday

## Recap
<!-- evening-sync:recap:begin inputs=… -->
> [!warning] Catch-up note                      ← CLI, only on a catch-up
> Covers … — 2 business days without an evening run. …

> [!glance] At a glance
> **19 meetings** Friday–Tuesday · 5 organisations · 4 themes · 0 decisions logged
> - **Needs your hand:** DEME programme management has no owner past Thursday
> - **Moved:** AI Hive has a named pilot (Metal Union)
> - **New:** Delifrance/Van de Moortel RFP, due 4 November
> - **Touched:** [[40-entities/delaware/dossier|delaware]] · [[40-entities/deme/dossier|DEME]] · …

**Themes**

> [!theme]- DEME programme management needs a hand before Thursday
> Body, 2–4 sentences.
>
> Sources: [[15-09-26-deme-status-en-resourceplanning|DEME status & resourceplanning]] · …

(one folded theme callout per theme, 2–4 of them)

**Project pulse**

| | Project | What moved |
|:-:|---|---|
| 🔴 | [[30-projects/deme-supply-chain-transformation/index\|Supply Chain Transformation]] · [[40-entities/deme/dossier\|DEME]] | one or two sentences |
| 🟢 | … | … |

🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet

**Decisions logged**
- [[2026-09-15-metal-union-confirmed-as-ai-hive-pilot|Metal Union confirmed as the AI Hive pilot]] · Imagine More
(or: **Decisions logged** — none this run; every meeting in the window is still in the review queue.)

> [!hot] Watch
> - content risks only, one line each

> [!quote]- Carried forward — your jottings
> - …

> [!sync]- Sync notes — 4 items, also in the run log
> - duplicates, deferred cross-source matches, fetch errors, out-of-reach transcripts, SELF-CHECK lines
<!-- evening-sync:recap:end -->

## Meetings

### 14:00 — Go over structure for AI fluency training · [[40-entities/la-lorraine/dossier|La Lorraine]]
#### Prep
<!-- evening-sync:prep:begin -->
**Attendees** — Matthias Danneel (organizer), Xander Verplancke, Michael
**Last meeting** — [[10-09-26-la-lorraine-exco-enablement-walkthrough|10 September — ExCo enablement walkthrough]] · one-liner
**Context** — [[30-projects/la-lorraine-ai-exco-enablement/index|La Lorraine AI ExCo Enablement]] · one line from the project's state
<!-- evening-sync:prep:end -->

#### Notes
- 

#### Actions
- [ ] 

## End of day
- 
```

Rendering facts verified on Obsidian 1.13.7 with Minimal 9: single newlines inside the prep block render as line breaks; H4 sub-headings fold in Live Preview and Reading view (Minimal `folding: true` is already in the shipped settings); `- [ ]` renders as a checkbox in both views; custom callout types fall back to the default look when the snippet is absent. Headings cannot be folded *by default* in Obsidian, so Prep opens expanded; that is accepted.

### 3.2 Payload v2

`daily-note write` accepts a structured `recap` object and a structured `prep` object. The v1 string forms stay accepted, so existing tests and any older caller keep working, but the skill switches to v2 and the skill-contract test pins the v2 example.

```json
{
  "date": "2026-09-16",
  "recap_window": {"from": "2026-09-11", "to": "2026-09-15"},
  "recap": {
    "glance": {
      "entities": ["delaware", "bta", "deme"],
      "headlines": [
        {"label": "Needs your hand", "text": "DEME programme management has no owner past Thursday"},
        {"label": "Moved", "text": "AI Hive has a named pilot (Metal Union)"}
      ]
    },
    "themes": [
      {"headline": "DEME programme management needs a hand before Thursday",
       "body": "2–4 sentences.",
       "sources": [{"stem": "15-09-26-deme-status-en-resourceplanning", "label": "DEME status & resourceplanning"}]}
    ],
    "pulse": [
      {"project": "deme-supply-chain-transformation", "signal": "red", "text": "one or two sentences"}
    ],
    "decisions": ["2026-09-15-metal-union-confirmed-as-ai-hive-pilot"],
    "watch": ["content risk, one line"],
    "carried_forward": ["…"],
    "sync_notes": ["mechanical item, one line"]
  },
  "meetings": [
    {"time": "14:00", "subject": "Go over structure for AI fluency training", "entity": "la-lorraine",
     "prep": {"attendees": "…", "last_meeting": "…", "context": "…"}}
  ]
}
```

Rules the CLI enforces (each a `DailyNoteError` naming the field, so one retry fixes everything, as today):

| Field | Rule |
|---|---|
| glance first line | computed by the CLI, never supplied: meeting count = meeting notes dated inside `recap_window` (the same set the fingerprint hashes), window label from the window's day names, theme and decision counts from the payload |
| `glance.headlines` | 1–4 items; `label` from a fixed set (`Needs your hand`, `Moved`, `New`, `Decided`, `Quiet`); `text` ≤ 20 words |
| `glance.entities` | entity slugs; the CLI renders the **Touched** line as path links with `entity-name`; the line is omitted when empty |
| `themes` | 0–4; `headline` ≤ 12 words; `body` ≤ 80 words; `sources` are meeting or daily-note stems that resolve; `label` is free prose |
| `pulse` | project slugs that resolve; `signal` ∈ `red|amber|green|quiet`; `text` ≤ 40 words; rendered as the table with the project's `project-name` and its entity's `entity-name`; the legend line is emitted when the table has ≥ 1 row |
| `decisions` | decision stems that resolve; the CLI renders `[[stem\|summary]] · project-name` from the decision's frontmatter |
| `watch`, `carried_forward`, `sync_notes` | lists of one-line strings, each ≤ 40 words; empty lists render the "none" phrasing (`watch`) or omit the block (`carried_forward`, `sync_notes`) |
| `prep` | three required string fields, each one line; wikilinks inside are checked exactly as today |
| catch-up banner | a recap string (v1) that opens with `> [!warning] Catch-up note` has that callout stripped and a warning returned; v2 has no place to put one |

Link normalisation applies to every free-text field: a `[[slug]]` or `[[slug|Name]]` whose target is an entity or project is rewritten to `[[<path>|<display-name>]]`; a supplied alias that disagrees with the vault is still refused (decision 19 unchanged). Meeting, decision and daily-note links are checked for existence only, as today. The meeting heading's entity suffix is rendered by the CLI as `· [[40-entities/<slug>/dossier|<entity-name>]]`; `_HEADING_RE` and the merge comparison accept both the v1 bare form and the v2 path form so a note written by v1 can still be region-merged by v2.

### 3.3 Regions, merge, read

- The `recap` region and one `prep` region per meeting are unchanged as *regions*. The prep region now sits under `#### Prep`; `#### Notes` and `#### Actions` with their empty affordances are written **once**, on note creation, and never touched again. The heading match (`### …` above each prep region) is unchanged; `_heading_above` already skips `####` lines.
- A v1 note (prep region directly under the `###`, a bare `- ` jot line) merges exactly as today. The Notes/Actions sub-headings are not retro-fitted into existing notes; they appear from the first note written by v2.
- `daily-note read` returns, per meeting, `notes[]` (bullets under `#### Notes`, plus any bullets directly under the `###` heading for v1 notes), `actions[]` as `{text, done}` from `- [ ]` / `- [x]` under `#### Actions`, and keeps `jottings[]` as the union for callers that do not care. `end_of_day` is unchanged. Stage 2 of the skill reads both; actions are context for the recap and decision capture in this version, nothing routes them yet.
- The recap fingerprint is unchanged in meaning; the rendered banner stays inside the digest.

### 3.4 Skill changes (`evening-sync/SKILL.md`)

- Stage 5 builds the prep as three fields, not one `·`-joined line.
- Stage 6 composes the v2 payload. The shape rules move from prose into the payload description; the prose keeps the judgment: what is a theme, how to assign a signal (**red** = needs the owner's hand this week · **amber** = a risk building, nothing to do yet · **green** = moved forward · **quiet** = no activity in the window), and a hard rule that **Watch is content only** and every conflict, duplicate, fetch error, refusal and `SELF-CHECK` line goes to `sync_notes`.
- The catch-up banner sentence ("the CLI writes it; you do not") gets a second sentence: a banner in the payload is stripped, not honoured.
- Stage 2 reads `notes` and `actions`.

`Start here.md` (template) describes the note's parts; it gains one sentence on Notes and Actions under each meeting. The ontology's daily-note section is updated to the v2 shape.

## 4. Project index v2

### 4.1 Rendered shape

```markdown
---
(frontmatter unchanged; project touch still owns it)
---

# Imagine More

> [!summary] Where it stands — 15 September
> - **Stage** — one or two sentences.
> - **Hot potato** — 🔴 one sentence.
> - **Hot potato** — 🟠 one sentence.
> - **Insight** — one sentence.
> - **Defining decision** — [[2026-09-15-metal-union-confirmed-as-ai-hive-pilot|Metal Union confirmed as the AI Hive pilot]] (15 Sept)

## Coming up

| When | What |
|---|---|
| Wed 16 Sept | Munich AI-budget presentation to leadership |
| … | … |

## Recent meetings

```dataview
TABLE WITHOUT ID link(file.path, dateformat(date, "ccc dd-MM")) AS "Date", calendar-subject AS "Subject", slice(attendees, 0, 3) AS "With", recording-duration AS "Min"
FROM "20-meetings" WHERE econtains(projects, this.slug) SORT date DESC LIMIT 10
```

## Recent decisions

```dataview
TABLE WITHOUT ID link(file.path, dateformat(date, "dd-MM")) AS "Date", summary AS "Decision", status AS "Status"
FROM "30-projects/<slug>/decisions" SORT date DESC LIMIT 10
```

## Background

Reference material for the evening run and for when you need the detail. Folded by default.

> [!todo]- 📤 Owe — by owner
> - **Michael Bulthé**
>   - one item per bullet
> - **Laura Debrock**
>   - …

> [!info]- 👤 Awaiting
> - …

> [!question]- ❓ Open questions
> - …

> [!note]- ⏳ Pending
> - …

> [!warning]- Watch list
> - …

> [!info]- Context
> - **Contacts** — …
> - **Source** — …
```

`dateformat` uses Luxon tokens; `ccc` is the weekday abbreviation (`ddd` is not a token and rendered literally in the first mock-up).

### 4.2 `project state write` (new CLI subcommand)

The stage-4 subagent stops editing Markdown. It returns a JSON state and the CLI renders the body:

```json
{
  "as_of": "2026-09-15",
  "stage": "one or two sentences",
  "hot_potatoes": [{"signal": "red", "text": "one sentence"}],
  "insights": ["one sentence"],
  "defining_decision": "2026-09-15-metal-union-confirmed-as-ai-hive-pilot",
  "coming_up": [{"when": "Wed 16 Sept", "what": "…", "date": "2026-09-16"}],
  "owe": [{"owner": "Michael Bulthé", "items": ["…"]}],
  "awaiting": ["…"], "questions": ["…"], "pending": ["…"], "watch": ["…"],
  "context": {"contacts": "…", "source": "…"},
  "next_milestone": {"text": "…", "date": "2026-09-18"}
}
```

Caps: `stage` ≤ 60 words; `hot_potatoes` ≤ 3, each ≤ 30 words, `signal` ∈ `red|amber`; `insights` ≤ 2, each ≤ 30 words; `coming_up` ≤ 10 rows, sorted by `date` when present, undated rows last; every list item ≤ 40 words; `owe` grouped by owner, one item per bullet (the `;`-joined mega-line is refused). `defining_decision` must resolve under the project's `decisions/`. Link normalisation as in §3.2. The writer replaces the body between the H1 and the end of `## Background`; a `## Notes` section after Background, if the owner ever adds one, is preserved verbatim — the one human area on an otherwise machine-owned page. `next_milestone` is passed through to the same frontmatter update `project touch` performs today, so one call replaces two.

`project scaffold` renders the same shape with placeholders. `new-project`'s prose ("Now callout", "Open Items") is updated.

### 4.3 Migration 002 → structure-version 3

For every `30-projects/*/index.md` that still has `## Decisions` / `## Open Items` / `## Related Meetings`:

- `Now` → `Where it stands`: **Stage** and **Defining decision** kept; **Next event** becomes the first `Coming up` row(s) (split on `;`, undated); **Owe** and **Watch** move into Background as `📤 Owe` and `Watch list` (split on ` · ` and `;`, one item per bullet; owner detected from a leading `📤 Name:` when present, else grouped under "Unassigned").
- `Open Items` four bullets → the four Background callouts, split the same way.
- `Context` callout → Background `Context`.
- Dataview blocks replaced by the two v2 blocks with `LIMIT 10`.

`LOSSY = None`: text is moved and re-bulleted, never dropped. `verify` checks the four v2 H2s are present and the three v1 ones are gone. Idempotent by construction (a v2 index has no v1 headings). The next evening run then regenerates each active project's state through `project state write`, which is where the prose gets short; the migration only reshapes. Issue #145 (project → area rename) planned to be structure-version 3; it becomes 4.

`body_sections` in the ontology becomes `[Coming up, Recent meetings, Recent decisions, Background]`; `compile_ontology` and `schema.json` follow; the five `fixtures/demo-vault` indexes are rewritten to v2; `test_fixtures_ontology` and `test_dataview_refs` keep passing.

## 5. CSS snippet

`sb-accelerator.css` gains four callout types, each `--callout-color` plus a Lucide `--callout-icon`: `glance` (sky, eye), `theme` (violet, git-merge), `hot` (red, flame), `sync` (slate, wrench, slightly muted). The snippet is a `MANAGED_SILENT` template file, so `/upgrade-vault`'s template refresh carries it to existing vaults without consent friction. No `cssclasses` helpers are needed for these two notes; the `kv` table style from the mock-ups is dropped.

## 6. Not in scope

- The homepage (#32) — it will reuse the callout types and, likely, Bases embeds.
- Swapping the Dataview blocks for Bases embeds. Bases can filter on the embedding note (`this.file`), but the Dataview blocks work today and the swap is a separate, visually-verified change.
- Routing captured Actions into project `Owe` lists. This version harvests them as context only.
- Person display names in the Dataview `With` column (slugs today).
- Renaming `index.md`/`dossier.md` to folder notes so bare `[[slug]]` resolves. It is the cleaner long-term fix for link resolution and belongs with #145's structure change; path links solve the user-visible problem now.
- Pulse signals on people or entities; #183; #184.

## 7. Testing

- `test_vaultlib_dailynote.py`: v2 render (golden string), every cap and enum refusal, banner strip with warning, link normalisation for entity/project/`[[slug|Wrong Name]]`, v1 payload still rendering byte-identically, v1 note merging under v2, `read` returning `notes`/`actions` with `done`, v1 note read still yielding `jottings`.
- `test_vaultlib_project.py`: `state write` render, caps, `## Notes` preservation, `next_milestone` frontmatter update; scaffold golden.
- `test_migration_002.py`: on the demo fixtures and on a synthetic index shaped like DryRunVault's Imagine More (long `·`/`;` lines); idempotency; verify failure when a v1 heading survives.
- `test_skill_contracts.py`: the SKILL.md payload examples parse and pass validation.
- Lint, `validate_template`, full pytest; `compile_ontology` regeneration test.
- **Visual tier (mandatory, UI-impacting):** `/visual-check` tour on a fresh test vault, plus screenshots of a v2 daily note and a v2 project index at 1440×900 in Reading view and Live Preview, checked for: custom callout icons present, table pulse legible, Prep/Notes/Actions fold, no unresolved-link styling on entity/project links, Dataview tables render with `ccc` weekdays.

## 8. Rollout

1. One PR on `main`; plugin version bump; CHANGELOG line under Unreleased (a client notices this).
2. DryRunVault: `/upgrade-vault` (migration 002 + template refresh), delete the three stray root notes and the `readability-proposals` folder plus its snippet, run `/evening-sync` once interactively, read the note and the Imagine More index in Obsidian.
3. Registry `plugin_version` bump for dryrun as usual.
