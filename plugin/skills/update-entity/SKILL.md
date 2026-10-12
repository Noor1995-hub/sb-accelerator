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

Ask which `entity-type` and `status` fit rather than guessing. If the entity
already exists and the user gives you a field that is missing or wrong on the
dossier (an `--owner` never set, say), running `entity ensure` again with
that flag is the fix — it applies whichever fields you pass to an existing
dossier instead of silently dropping them, and the envelope's `changed` /
`updated` tell you whether it actually took.

**A team or department of an entity** (Finance at Acme, Yard Operations at
Meridian) is its own entity under its parent — pass `--parent <entity slug>`
and `--type business-unit`, with the slug `{parent}-{team}` so two companies'
Finance teams never collide:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" \
  --slug acme-finance --name "Finance" --type business-unit --status active --parent acme
```

The CLI writes **Part of** on the team's dossier and adds a **Teams** section to
the parent's. `--parent` on an existing entity attaches it as a team. Teams go
one level deep only: a team cannot be a parent, and an entity that already
has teams cannot become one — the refusal says which. Meetings still reach the
parent by email domain and a team through its projects, so put a team's work
on a project whose entity is the team.

### 2. Read the current dossier

```bash
python3 "$VAULTLIB" entity read --vault "$VAULT" --slug <slug>
```

You get the frontmatter, all six sections, which sections are still marked
unvalidated, and whether the banner is present. **Read this before routing** —
knowing what is already recorded is what lets you update rather than duplicate,
and lets you notice a contradiction.

Any section the user added themselves comes back separately under
`extra_sections` — read it before routing, but route new content only into the
six managed sections, because `entity write` has no key for the others.

The banner (`> [!unvalidated] Generated context — verify before relying on
details.`) survives `entity write` unconditionally now — writing content
never clears it as a side effect. Clearing it is a separate, explicit act:
`entity validate --slug <slug>`. Do not call it as part of routine routing;
it is for a human's actual review of the dossier's content, the same
discipline as rule 4 below for the stakeholder `needs-review` marker.

One reading note: cells in the Stakeholders and Engagements tables come back
with any pipe escaped as `\|`, because that is how they are stored. If you
carry text from a cell into your payload, strip the backslash first — the write
path escapes pipes again, so passing the stored form back doubles the escape.

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
| A meeting's *read of the room* — the tone, who held back, what went unsaid | `meeting_log` |
| Political dynamics, sore points, topics to avoid, competitor ties | `sensitivities` |
| Milestones in the relationship — trust earned or lost, turning points | `relationship_history` |
| Projects and their status | `engagements` |

Judgment calls worth getting right:

- **`meeting_log` holds only the read of the room.** The section is a
  Dataview index of the entity's meetings plus a `### Dynamics` bullet per
  meeting, and the CLI **refuses** `attendees`, `outcomes` and `followups`.
  That is not a formatting rule: attendees are the meeting note's own
  frontmatter, outcomes are its `## Notes`, follow-ups are its
  `## Action items`, and a copy here goes stale the moment the note is
  corrected. What no query can reproduce is "exploratory throughout; no
  commitment asked for or offered" — write that, and nothing else.
- **A meeting that revealed a dynamic** goes in *both* `meeting_log` and
  `sensitivities`. Do not make the user choose.
- **`relationship_history` is for turning points**, not every interaction. If
  it would read as noise in a year, it belongs in `meeting_log` only.
- **For the meeting to appear in the table at all**, its note needs
  `entities: [<slug>]` in frontmatter — the query joins on that field and
  nothing else. A note written before the field existed, or by hand without
  it, is simply absent. If the user is looking for a meeting that is not
  listed, that is the first thing to check.
- **`context` is capped at eight bullets** and the CLI enforces it. Prefer
  updating an existing label to adding a ninth.
- **Vocabularies are closed.** Role in decision: sponsor · champion ·
  evaluator · influencer · blocker. Stance: champion · neutral · blocker. The
  CLI refuses anything else, so pick the nearest rather than inventing.
- **Always pass a stakeholder's plain display name.** The CLI matches on a
  slug derived from the name, so "Leo Marchetti" updates an existing row
  whether that row stores `Leo Marchetti`, `[[leo-marchetti]]` or
  `[[leo-marchetti|Leo Marchetti]]`. Do not copy a dossier's link syntax back
  into the payload to make it match, and do not introduce a wikilink for a
  person note that may not exist.

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

Every *section* key is optional; send only the sections you have something for.
Within an entry the fields are not: `context` needs all of `label`, `fact` and
`why`, `stakeholders` needs `name`, `meeting_log` needs `date`, `topic` and
`dynamics`,
`sensitivities` needs `topic`, `detail` and `implications`,
`relationship_history` needs `date`, `what` and `significance`, and
`engagements` needs `project` — as the project's **slug**, not its display
name. The CLI refuses an incomplete entry rather than rendering a half-empty
bullet. Dates are ISO `YYYY-MM-DD`.

### 6. Summarise

Report what changed, section by section, from the CLI's `changes` list. Then
two things the list cannot tell you:

- **Contradictions, explicitly.** "Updated Leo Marchetti's title: COO →
  Group COO" — never silently overwrite a fact the user may care about.
- **What you deliberately did not record**, if you dropped something as too
  thin or too speculative to be worth a permanent entry.

If the envelope's `repairs` list is not empty, say what the CLI repaired — it
tidied up a hand-edit in the dossier (a raw `|` inside a table cell, a deleted
separator row, a note starting with a pipe). Nothing was lost, but the user
wrote those bytes and should hear that they changed.

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
7. **The `[!unvalidated]` banner clears only through `entity validate`,
   never as a side effect of routing content.** Do not call `entity validate`
   on the user's behalf just because a write succeeded — it is the same
   explicit-review discipline as rule 4, applied to the whole dossier instead
   of one stakeholder row.
