# Migrations

**Migrations live in `plugin/migrations/` and ship with the plugin**, so that
plugin version ↔ available migrations is deterministic on a client machine.
The format contract — directory naming, the `TARGET_VERSION` / `apply` /
`verify` / `LOSSY` module interface, and the snapshot → migrate → verify → log
run order — is `plugin/migrations/README.md`. Every migration must be
idempotent.

This directory stays as the place a *candidate* is written down before it has
a home in the chain. The candidate list that used to live here — the
accumulated v0.2.0 → v0.6.2 vault changes — moved into the migration that
implements it, quoted verbatim in the docstring of
`plugin/migrations/001-structure-version-2/migrate.py`. Read it there.

The version a freshly instantiated vault ships at is `plugin/template/structure-version`,
and `scripts/validate_template.py` pins it to the last migration's
`TARGET_VERSION`: a migration that lands without that bump ships new vaults at
the old version, and `/upgrade-vault` opens by proposing a migration with
nothing to do.

**Not** a migration candidate, recorded so nobody writes one: the skip list
`99-workflow-config/sync-state/skipped-recordings.txt` gained two optional
tab-separated fields (reason, original filename). A bare id line is still a
valid record, read as "reason unknown" — which is the truth, since no reason
was captured when it was written. There is nothing to backfill.
