# Migrations

Versioned vault-structure migrations, consumed by the `/upgrade-vault` skill
on client machines (snapshot → migrate → verify → log). Migration format is
designed together with `/upgrade-vault` — tracked in the backlog (area:migrations
via the /upgrade-vault issue). Every migration must be idempotent.

Pending migration (structure-version 2 candidate): decision notes — drop
`tags`, add `reviewed: true` to existing notes (v0.2.0 removed tags and made
the reviewed key mandatory). Also: add `99-workflow-config/config.json`
(template default, then fill timezone/executive/adapters from the vault's
prose context — #54 moved machine decisions out of prose).
Also: rewrite `review_status: needs-attention` → `needs-review` on existing
meeting notes (v0.5.1 retired the status; those notes already carry the
`conflicts-with` edge that now carries the clobber-risk signal, so nothing
else has to be written). Until it runs, those notes are absent from the
Triage view and a review tick on one cannot fold, so they stay invisible to
the queue.
