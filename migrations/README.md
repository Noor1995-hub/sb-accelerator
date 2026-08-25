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

Also, for #55 (inbox lifecycle): refresh `10-inbox/README.md` — its semantics
changed, the folder is now the pending set rather than a staleness signal —
add `90-archive/README.md`, and refresh `template/CLAUDE.md`'s Inbox
Discipline section. **Most important: refresh
`99-workflow-config/reference/ontology.md`.** The plugin's skills read the
*vault's* copy for the confidence vocabulary, so a vault provisioned before
#55 has a skill mandating `calendar-not-applicable` and a `note` type that
its own ontology does not list — the skill and the vault contradict each
other, and an agent resolving toward the vault writes a wrong confidence
reason.
