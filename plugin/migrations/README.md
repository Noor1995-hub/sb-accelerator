# Migrations

Vault structure migrations, applied by the `migrate` CLI group
(`vaultlib.migrate`) and run through the `/upgrade-vault` skill on a
consultant's own machine — never unattended. Every run snapshots the vault
first, then applies pending migrations in order, verifying each one before
moving to the next.

## Directory format

One directory per migration, directly under this folder:

```
plugin/migrations/
  001-some-change/
    migrate.py
  002-another-change/
    migrate.py
    assets/          (optional — see below)
```

The directory name must match `NNN-slug`: a three-digit, zero-padded number
followed by a lowercase, hyphenated slug (`001-add-config-json`). The number
is the migration's position in the chain, not the structure-version it
produces — `structure_version` is `TARGET_VERSION` below.

## Module contract

`migrate.py` inside each directory must define:

- `TARGET_VERSION: int` — the structure-version this migration produces once
  applied. The chain must be consecutive: the first migration's
  `TARGET_VERSION` is `current + 1`, and each one after that is one more than
  the last. A gap is refused rather than silently skipped.
- `LOSSY: str | None` — `None` if the migration only adds or reshapes data
  without discarding anything a human might want back; otherwise a short
  human-readable description of what it drops (e.g. `"drops the Attendees,
  Key outcomes and Follow-ups lines — that content now lives on the meeting
  note"`). Shown to the consultant before they confirm the run.
- `apply(root: Path) -> dict` — makes the change. Returns a small
  JSON-serializable dict describing what happened (counts, paths touched),
  logged alongside the migration.
- `verify(root: Path) -> dict` — checks the change actually landed. Returns a
  JSON-serializable dict on success; **raises** (any exception) on failure.
  A raised exception stops the chain — later migrations do not run, and the
  vault's `structure-version` stays at the last one that both applied and
  verified cleanly.

### Idempotency

Every migration must be safe to run twice. A vault can legitimately see the
same migration attempted more than once (a prior run failed partway through
a later migration and the consultant re-runs after fixing the cause). `apply`
should detect already-migrated state and skip it — a meeting note that
already carries the field a migration adds, a dossier section that already
contains the block a migration inserts — rather than re-applying it or
duplicating content.

### Assets convention

A migration that needs supporting files (a template snippet, a lookup table)
keeps them in an `assets/` subdirectory next to its `migrate.py`, and reads
them relative to its own directory (`Path(__file__).parent / "assets"`) —
never relative to the vault root or the current working directory.

## What the framework does around each migration

- **Snapshot first, once per run.** Before the first pending migration
  applies, the whole vault is zipped into
  `99-workflow-config/snapshots/vault-<timestamp>.zip` (excluding the
  snapshots folder itself). Only the three most recent snapshots are kept.
- **Apply, then verify, then bump.** For each pending migration in order:
  `apply` runs, then `verify` runs against the result, and only then does
  the vault-root `structure-version` file advance to that migration's
  `TARGET_VERSION`.
- **Log every attempt.** `99-workflow-config/migration-log.md` gets one line
  per migration attempt — the date, the version transition (`v1→v2`), the
  plugin version, the snapshot it ran under, and the outcome (`ok` or
  `FAILED: <error>`).
- **Stop on the first failure.** If `apply` or `verify` raises, the chain
  stops there. The snapshot taken at the start of the run is the way back to
  the pre-migration state; the log line names it.

## Interaction with the template refresh (#117)

`vaultlib/template.py`'s managed-file tiers (`plugin/lib/vaultlib/template.py`)
diff a vault's copy against `provenance.json`'s recorded baseline, not
against the *previous* shipped template — so a migration that edits a
managed file in place (rewriting `ontology.md`, say, or a `.base` file's
frontmatter) leaves that file's vault-recorded digest stale. The next
`template status` reports it as `needs-consent` / `locally-edited` even
though nothing a consultant did caused the drift; it will read that way
until the vault is next rebaselined (a `template refresh` naming that
file with `--consent` folds it back to `current`, whether or not the
refresh actually rewrites its bytes). A migration that touches a managed
file should say so in its own module doc, so the consultant is not
surprised by a "locally-edited" reason with no local edit behind it.
