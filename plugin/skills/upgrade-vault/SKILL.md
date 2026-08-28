---
name: upgrade-vault
description: Snapshot the vault, then apply and verify every pending structure migration in order, with an explicit confirmation gate before anything lossy runs. Triggers when the user invokes /upgrade-vault.
user_invocable: true
origin: net-new
---

# Upgrade Vault

Vault structure migrations ship inside the plugin and ride the marketplace
update channel — a new plugin version can require a structure the vault
does not have yet. This skill is the only sanctioned way to move a
vault forward: snapshot, apply, verify, log, one migration at a time, never
unattended.

## Audience

**Consultant-run, at a tune-up, after `claude plugin update`.** This is not
something to hand the vault owner or their EA to run alone — a migration can
be lossy, and reading the plan and giving the explicit go-ahead is the
consultant's job at that visit. Run it once right after the plugin update,
before touching anything else that visit.

## Requirements

Running migrations needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say
so plainly rather than trying to snapshot or edit anything by hand.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution (`python3`, then `python`,
then `py -3`) are documented in the plugin's `CLAUDE.md`. Read `ok` on every
call; on failure surface `error` and `hint` **verbatim** — this is the one
skill where paraphrasing that pair could send the consultant to the wrong
file.

## Usage

```
/upgrade-vault
```

No arguments needed.

## 1. Check what's pending

```bash
python3 "$VAULTLIB" migrate status --vault "$VAULT"
```

The result carries `structure_version` (current), `expected_version` (what
the vault would be at once every pending migration lands), and `pending[]`
— each entry has `number`, `slug`, `target_version`, and `lossy`.

If `pending` is empty: say so plainly. State the current version (which
equals the expected version) and stop here — there is nothing to run.

## 2. Present the plan

If migrations are pending, walk the consultant through the whole chain
before touching anything:

- Each pending migration, in order: its number, slug, and the
  structure-version it produces.
- **Any `lossy` line, shown prominently, before anything else about that
  migration.** A migration whose `lossy` is `null` only adds or reshapes
  data; one with a `lossy` string drops something a human might want back
  — read that string out in full, not summarized, so the consultant knows
  exactly what will not survive the run.
- That a full vault snapshot is taken first, automatically, before the
  first migration applies — a zip under
  `99-workflow-config/snapshots/`, with only the three most recent
  snapshots kept.
- That every attempt — success or failure — gets one line in
  `99-workflow-config/migration-log.md`.

## 3. Explicit confirmation gate

Do not run anything until the consultant says go, to the plan exactly as
presented — a vague "sure" earlier in the conversation, or agreement to
"upgrade the vault" in the abstract, is not approval of *this* chain with
*these* lossy steps. If the consultant declines, stop; nothing has been
touched yet at this point (`migrate status` is read-only).

## 4. Run it

```bash
python3 "$VAULTLIB" migrate run --vault "$VAULT"
```

This snapshots, then applies and verifies each pending migration in order,
bumping `structure-version` only after both steps succeed for that
migration. It stops at the first failure — later migrations do not run.

### On `ok: true`

The result carries `snapshot` (the new snapshot's vault-relative path),
`applied[]` (one entry per migration that landed — `number`, `slug`,
`target_version`, its `apply` report, its `verify` report), and the new
`structure_version`.

Report each migration's outcome briefly, then **read out every
`needs_human` item across all the applied migrations' `apply` reports as
the consultant's follow-up list** — these are the files a migration could
not touch deterministically (unparseable frontmatter, a shape it would not
guess at) and left byte-identical on purpose. An empty `needs_human` for
every migration means there is nothing to hand off; say so.

### On `ok: false`

The envelope's `error` names which migration failed and the snapshot it
ran under; `hint` carries the human-fixable file list (when the failing
migration's `apply` produced one) plus the standing instruction to restore
from that snapshot. **Read both `error` and `hint` out verbatim** — do not
summarize or reword either, since the snapshot name and the file list are
exactly what the consultant needs next and nothing here should be
retyped from memory.

Then walk the consultant through the restore by hand:

1. Close Obsidian on the vault entirely.
2. Unzip the named snapshot from `99-workflow-config/snapshots/` over the
   vault root, overwriting in place.
3. Reopen Obsidian.

**Never attempt an automatic restore.** This skill has no unzip-and-verify
path of its own — the CLI stopped the chain and named the way back
precisely so a human decides when and whether to use it, not so an agent
unzips it unattended on top of a vault that might still have uncommitted
edits from the vault owner sitting outside the snapshot's scope.

## 5. After a successful run — fill in what migration 001 left null

Migration 001 writes `99-workflow-config/config.json` from the template
default on a vault that had none. A vault provisioned before the config
existed ends the run with a config file, but a *default* one — timezone,
owner, and connector account hints all `null` until someone fills
them in. Check for that at the same visit rather than leaving it for a
separate one:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

On a config left at the template default, `missing` is exactly
`["owner", "timezone"]` — an `account_hint` only joins the list once its
adapter is `enabled`, so unbound connectors show up as `enabled: false` in
`config` and never in `missing`. Walk the consultant through resolving every
entry that is there, plus any connector this deployment is meant to use,
either with `config write` directly:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field timezone --value "Europe/Brussels"
```

(one call per field; `--field` takes any of the writable fields, `--value`
the new value, or `--null` to unset a nullable one) — or by handing off to
`/setup-my-brain`, whichever the consultant prefers for that visit. Either
way, do not leave the vault with a `missing` list unresolved at the end of
the visit that just ran the migration that created it.

## 6. Close out

Recommend the vault owner (or EA) restart Obsidian once the visit's changes are
in — a migration can rewrite the vault's ontology, config, or note bodies,
and a running Obsidian instance may still be holding stale copies of files
this run just replaced.

## Hard rules

1. **Never run `migrate run` without the explicit confirmation gate in
   step 3**, even when `pending` shows nothing lossy — the consultant sees
   the whole plan every time, not just the times something would be lost.
2. **Never paraphrase `error` or `hint` on a failed run.** The snapshot
   name and the file list are exact values a consultant acts on, not prose
   to summarize.
3. **Never attempt to restore a snapshot automatically.** Name it, then
   walk through the manual close-unzip-reopen sequence — restoring is
   always a human decision made with Obsidian closed.
4. **Never run this against a vault the owner or EA is actively using.**
   This is a consultant-run, attended operation at a tune-up, not a
   background task.
