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

**Not** a migration candidate, recorded so nobody writes one: the skip list
`99-workflow-config/sync-state/skipped-recordings.txt` gained two optional
tab-separated fields (reason, original filename). A bare id line is still a
valid record, read as "reason unknown" — which is the truth, since no reason
was captured when it was written. There is nothing to backfill.

Pending migration (entity dossier contract, v0.6.2 — #60). Two changes, and
the first one is the only migration in the list so far that a vault silently
*needs*: without it a shipped view goes from wrong-but-populated to empty.

1. **Meeting notes need `entities: [<slug>]`.** The dossier's Meeting Log is
   now a Dataview query joining on that field, and no existing note has it, so
   every dossier shows an empty table until it is backfilled. Derive it: for
   each note in `20-meetings/`, map each `projects[]` slug to that project's
   `entity:` field, dedupe, write the list. A note with an empty `projects[]`
   cannot be derived and needs a human read (or is legitimately entity-less).
   The field means the entities a meeting was *about*, so an internal 1:1
   reviewing a client account carries that client — derivation from
   `projects[]` already gets that right.
2. **Dossier bodies need restructuring** in `40-entities/*/dossier.md`: add
   `# {entity-name}` above the first section; wrap the `## Context` and
   `## Sensitivities` bullets in their callouts (`> [!info]+ **Standing
   context**`, `> [!warning]+ **Handle with care**`) — every bullet gains a
   `> ` prefix, and the write path matches on the label *after* stripping it,
   so a half-converted section still merges; and replace the `## Meeting Log`
   body with the Dataview block plus a `### Dynamics` list, carrying each old
   `### {date} — {Topic}` block's **Dynamics** line across as
   `- **{date} — {Topic}:** {dynamics}`, newest first. The Attendees, Key
   outcomes and Follow-ups lines are dropped — that content is in the meeting
   note. Dropping them is the one lossy step here, so snapshot before running
   and say so in the log.

This one also needs the vault's own
`99-workflow-config/reference/ontology.md` refreshed, for the reason the #55
entry above gives: `entities` is a new Meeting field, so a vault provisioned
before this release has `/sync-recordings` telling an agent to write a field
the vault's ontology does not list.

Idempotency for both: skip a meeting note that already has `entities`, and a
dossier whose Meeting Log already contains the Dataview block.
