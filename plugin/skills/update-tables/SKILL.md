---
name: update-tables
description: Fill in, update or add people, projects or entities in bulk through an Excel the owner fills in, built from their own table and written back by script. Triggers when the user invokes /update-tables or asks to fill in, update or add to their People, Projects or Entities table, or to do it in Excel.
user_invocable: true
origin: net-new
---

# Update tables

The owner fills in an Excel built from their own table; the CLI writes it
back. You never edit the notes yourself: export, show the plan, wait for the
owner's OK, apply.

## Requirements

Runs in **Cowork** or **Claude Code** (needs a shell). Set `VAULT` to the
vault root and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Read `ok` on every call; on failure surface `error` and `hint`. Get `today`
once: the `today` field of
`python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <config.timezone>`
(`config read` gives the timezone). Never compute a date.

## Workflow

### 1. Which table

People, Projects or Entities. Not clear → ask once. The owner may name a
view ("the Active view"); otherwise the table's first view is used.

### 2. Export

```bash
python3 "$VAULTLIB" table export --vault "$VAULT" --table people --today <today>
```

Say, in two lines: where the file is (`path`), that only the yellow cells and
new rows at the bottom matter, and to save it and say "done" when finished.
Warnings (e.g. the table's columns could not be read): say them in one line.

### 3. Plan

When the owner says it is done:

```bash
python3 "$VAULTLIB" table import --vault "$VAULT" --file "<path>"
```

Show the plan in a few lines: counts first, then each conflict, refusal and
unknown name, one line each. For an unknown entity name: *"LLBG is not an
entity: create it, or keep it as text?"* Create → `entity ensure` with that
name (as `/update-entity` step 1 does), then run the plan again. A refused
row: say why, and that it can be fixed in the Excel and imported again.
Wait for the owner's OK.

### 4. Apply

```bash
python3 "$VAULTLIB" table import --vault "$VAULT" --file "<path>" --apply --today <today>
```

Summarize: written, created, failed (with the reason). "Another run is busy"
→ say so; nothing was written; try again in a few minutes.
