---
name: new-project
description: Create a project or area of responsibility with a structured index, and link it into its entity's dossier. Triggers when the user invokes /new-project or asks to start a new project, initiative, engagement, opportunity, or area of responsibility.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# New Project

Create `30-projects/{slug}/` with a queryable `index.md` and an empty
`decisions/` log, then link the project into its entity's dossier.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there. If you
find yourself without a shell, say so plainly and point the user at Cowork
rather than hand-writing the files.

Set `VAULT` to the vault root and `VAULTLIB` once at the start:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Interpreter resolution and the JSON envelope are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure show the `error` and `hint`
instead of retrying blind.

## Usage

```
/new-project
/new-project "Yard Automation Program"
/new-project "Pipeline Governance" --type area-of-responsibility
```

## Workflow

### 1. Gather what you need

Ask only for what is missing, one question at a time.

- **Name** — the human-readable project name. Keep the entity out of it: the
  `entity` field already carries that, and the Projects base shows it as its
  own column. "Yard Automation Program", not "Meridian — Yard Automation".
- **Type** — `initiative` (timeboxed work with an end) or
  `area-of-responsibility` (standing, no end date). Default to `initiative`
  without asking when the name plainly describes bounded work.
- **Entity** — which organisation this belongs to. List what exists:

  ```bash
  ls "$VAULT/40-entities"
  ```

  If the right entity is not there, create it first:

  ```bash
  python3 "$VAULTLIB" entity ensure --vault "$VAULT" \
    --slug <slug> --name "<Display Name>" --type client --status prospect
  ```

  Ask which `--type` and `--status` fit rather than guessing: `prospect` for
  something being pursued, `active` for a live relationship. `entity ensure`
  is safe to run again even if the entity already exists: on an existing
  dossier it applies whichever fields you pass (`--name`, `--type`,
  `--status`, `--owner`) rather than silently ignoring them, and its envelope
  reports `changed` plus `updated: [...]` so you know whether anything
  actually moved. It never claims a plain success for a field it did not
  apply.
- **Parent** — only for initiatives, and only if the user implies one.
  Maximum two levels; areas of responsibility are always top-level. The CLI
  enforces both.

### 2. Offer to gather context

Ask once, for every project:

> Anything to seed this with? Paste an email or notes, point me at a file, or
> just describe it — or skip and we'll create it bare.

Accept any of three forms:

- **Pasted text** — read it directly.
- **A file** — read it. Inbox captures live in `10-inbox/`; a path anywhere
  in the vault is fine.
- **A spoken description** — treat it as the same material.

From whatever you get, extract only what is actually there. Do not invent:

| Extract | Into |
|---|---|
| One line on where this stands right now | `--stage` |
| Named people and their roles | `--contacts` |
| How this arrived — referral, inbound mail, a meeting | `--source` |
| Deadlines or urgency signals | mention in your summary; the index has no field for it yet |

If the user skips, omit the flags — the index falls back to placeholders.

### 3. Resolve the owner

The owner is a person slug, and it must resolve to a real person note.
Default to the executive:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

`executive` in the result is the executive's person slug — use it as
`--owner` directly. If it is in `missing`, ask the user who owns this
project (never guess), then make sure the note exists:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<Full Name>"
```

Use the returned `slug` as `--owner`.

If the user names a different owner, `person ensure` them instead — the same
call handles both cases and never touches an existing note.

### 4. Scaffold

```bash
python3 "$VAULTLIB" project scaffold --vault "$VAULT" \
  --name "Yard Automation Program" \
  --type initiative \
  --entity meridian-freight-holdings \
  --owner morgan-ellery \
  --stage "Vendor shortlist agreed; contract drafting" \
  --contacts "Leo Marchetti (COO), Renee Castillo (IT Director)" \
  --source "Forwarded renewal email, 2026-08-21"
```

The CLI derives the slug, refuses collisions, checks the entity exists,
validates the frontmatter against the ontology, writes `index.md`, and creates
`decisions/`. If it refuses, relay the reason — several of its errors name the
exact command that fixes them.

### 5. Link it into the dossier

Add the project to its entity's `Engagements` table. Write the edits to a file
and pass it, so quoting cannot mangle the payload:

```bash
cat > /tmp/engagement.json <<'JSON'
{"engagements": [{"project": "yard-automation-program",
                  "status": "Active",
                  "one_liner": "Three-yard automation rollout"}]}
JSON
python3 "$VAULTLIB" entity write --vault "$VAULT" \
  --slug meridian-freight-holdings --edits /tmp/engagement.json
```

The one-liner is one sentence, drawn from the context you gathered.

**This step is non-blocking.** If it fails, the project still exists — say
"dossier link skipped" in your summary and move on. Never unwind the project
because the dossier update failed.

### 6. Summarise

Report, briefly:

- name, slug, type, entity, owner
- the path to `index.md`
- what you extracted from the supplied context, and what you could not find
- whether the dossier link succeeded
- one suggested next step — usually recording the first decision, or feeding a
  transcript in

## Rules

1. **Never hand-write the files.** Every write goes through the CLI. It
   validates against the ontology; you do not.
2. **One folder per project.** `index.md` is the queryable object; artifacts
   sit beside it.
3. **Do not invent context.** A placeholder is better than a plausible
   fabrication — this vault is read as a record.
4. **Do not put the entity name in the project name.** It is already a field
   and a column.
5. **Dossier failures never fail the project.**
