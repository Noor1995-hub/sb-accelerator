# Migrations

Versioned vault-structure migrations, consumed by the `/upgrade-vault` skill
on client machines (snapshot → migrate → verify → log). Migration format is
designed together with `/upgrade-vault` — tracked in the backlog (area:migrations
via the /upgrade-vault issue). Every migration must be idempotent.
