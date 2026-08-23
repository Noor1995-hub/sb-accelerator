---
name: update-entity
description: Record relationship context about an organisation — people, meetings, company facts, sensitivities, engagements — into its dossier. Triggers when the user invokes /update-entity or asks to update, capture, or record context on a client, partner, supplier, or business unit.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Update Entity

Route free-form notes into the right sections of an entity's dossier. You
decide what belongs where; the CLI does the merging.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there. Say so
plainly rather than hand-editing the dossier.

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure, show the `error` and `hint`
to the user rather than retrying blind or editing the dossier by hand.

## Usage

```
/update-entity
/update-entity meridian-freight-holdings
```

## Workflow

### 1. Identify the entity

If no slug was given, list what exists and ask:

```bash
ls "$VAULT/40-entities"
```

If it does not exist yet, create it before routing anything:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" \
  --slug <slug> --name "<Display Name>" --type client --status prospect
```

Ask which `entity-type` and `status` fit rather than guessing.

### 2. Read the current dossier

```bash
python3 "$VAULTLIB" entity read --vault "$VAULT" --slug <slug>
```

You get the frontmatter, all six sections, which sections are still marked
unvalidated, and whether the banner is present. **Read this before routing** —
knowing what is already recorded is what lets you update rather than duplicate,
and lets you notice a contradiction.

### 3. Get the input

If the user has not already provided it:

> What do you want to record about {Display Name}? Paste meeting notes,
> observations, an email, or point me at a file.

### 4. Route it

Decide which section each piece belongs to. A single paragraph about a meeting
routinely produces three entries: the meeting itself, a new person, and a
political dynamic worth remembering.

| What you are looking at | Section |
|---|---|
| Company facts — industry, size, systems, strategy, recent news | `context` |
| People — names, titles, who decides, where they stand | `stakeholders` |
| A meeting — who was there, what came out of it, what is owed | `meeting_log` |
| Political dynamics, sore points, topics to avoid, competitor ties | `sensitivities` |
| Milestones in the relationship — trust earned or lost, turning points | `relationship_history` |
| Projects and their status | `engagements` |

Judgment calls worth getting right:

- **A meeting that revealed a dynamic** goes in *both* `meeting_log` and
  `sensitivities`. Do not make the user choose.
- **`relationship_history` is for turning points**, not every interaction. If
  it would read as noise in a year, it belongs in `meeting_log` only.
- **`context` is capped at eight bullets** and the CLI enforces it. Prefer
  updating an existing label to adding a ninth.
- **Vocabularies are closed.** Role in decision: sponsor · champion ·
  evaluator · influencer · blocker. Stance: champion · neutral · blocker. The
  CLI refuses anything else, so pick the nearest rather than inventing.

**If nothing qualifies, write nothing.** Some input is genuinely not worth a
permanent entry — a scheduling exchange, a pleasantry, a detail already
recorded verbatim. `entity write` refuses an empty payload, so do not call it
with nothing: say what you read, say why none of it earned a place in the
dossier, and stop. An empty dossier update is a valid outcome, and a
fabricated entry to justify the call is not.

### 5. Write it

Build the payload as a file — never inline, where quoting mangles apostrophes
and em dashes:

```bash
cat > /tmp/entity-edits.json <<'JSON'
{
  "context": [
    {"label": "Fleet", "fact": "three yards, 240 trailers",
     "why": "sets the automation scope"}
  ],
  "stakeholders": [
    {"name": "Leo Marchetti", "title": "COO", "role": "sponsor",
     "stance": "champion", "notes": "wants numbers, not narrative"}
  ],
  "meeting_log": [
    {"date": "2026-08-21", "topic": "Renewal planning",
     "attendees": "Leo Marchetti, Renee Castillo",
     "outcomes": "Renewal in principle; scope revisit in September",
     "followups": "Send revised scope by 2026-09-05",
     "dynamics": "Warm; Renee quieter than usual on integration"}
  ],
  "sensitivities": [
    {"topic": "Incumbent integrator", "detail": "long relationship with the yard-1 vendor",
     "implications": "frame consolidation as additive, not a replacement"}
  ]
}
JSON
python3 "$VAULTLIB" entity write --vault "$VAULT" \
  --slug meridian-freight-holdings --edits /tmp/entity-edits.json
```

Every key is optional; send only the sections you have something for. Dates
are ISO `YYYY-MM-DD`.

### 6. Summarise

Report what changed, section by section, from the CLI's `changes` list. Then
two things the list cannot tell you:

- **Contradictions, explicitly.** "Updated Leo Marchetti's title: COO →
  Group COO" — never silently overwrite a fact the user may care about.
- **What you deliberately did not record**, if you dropped something as too
  thin or too speculative to be worth a permanent entry.

## Rules

1. **Never remove existing content.** The CLI enforces this, and you should
   not try to work around it. Dossiers are cumulative.
2. **Never hand-edit the dossier.** Every change goes through
   `entity write`.
3. **Read before you write.** Routing without reading produces duplicates.
4. **New stakeholders are flagged `needs-review` automatically.** Leave the
   marker for a human to clear; do not remove it on the user's behalf.
5. **Do not infer facts.** "Probably reports to the CFO" is not a fact. If it
   matters, ask.
6. **Do not touch `status` or `entity-type`** unless the user asks. Those are
   relationship-level judgments.
