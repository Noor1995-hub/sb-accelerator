# Migrations

Versioned vault-structure migrations, consumed by the `/upgrade-vault` skill
on client machines (snapshot → migrate → verify → log). Migration format is
designed together with `/upgrade-vault` — tracked in the backlog (area:migrations
via the /upgrade-vault issue). Every migration must be idempotent.

Pending migration (structure-version 2 candidate): decision notes — drop
`tags`, add `reviewed: true` to existing notes (v0.2.0 removed tags and made
the reviewed key mandatory).
