# Changelog

**Client-visible change only** — what the plugin, a skill, the vault template, or a migration
does differently for the exec and their EA. Internal work (CI, validators, fixtures, delaware-side
docs and tooling, repo plumbing) is deliberately absent: git history and the PR list already are
that record, in more detail and without drift.

Written for the consultant preparing a quarterly tune-up. Every line should be something you
would say out loud to the exec, or something that changes what you do at the visit. This file
ships to `sb-dist` with each release, so the client can read it — they cannot read this repo.

Entries accumulate under `Unreleased`. At release, that block becomes a
`## v<version> — <date>` section: the release notes, and the agenda for the tune-up that
delivers them.

## Unreleased

- **`/sync-recordings` — transcripts become meeting notes.** Drop a
  transcript in the inbox (or connect a Plaud recorder) and the sync turns
  it into a structured meeting note: takeaways, debrief, action items,
  attendees, and a link to the right project. Every note lands in the
  Meetings review queue with an honest confidence stamp saying how sure the
  routing is — nothing is auto-confirmed, and nothing is ever synced twice.
  Ticking "reviewed" in the Meetings base now confirms the note. (#14)
- **`/log-decision` — the decision log gets a producer.** Point it at a meeting
  note, a transcript, or just describe what was decided, and it proposes the
  decisions it found, one at a time, for you to confirm or correct before
  anything is written. Each one becomes its own dated note in the project's
  `decisions/` folder. When a decision replaces an earlier one it maintains both
  ends: the new note records what it supersedes, and the old note is marked
  superseded with a pointer forward — never deleted, so the trail of how the
  engagement changed its mind stays readable. It can also run unattended;
  everything written that way is flagged for review in the Decisions base, so
  nothing stays in the record unreviewed. (#46)
- **Decisions no longer carry tags.** A seven-word tag vocabulary was thin at
  the volume a decision log actually reaches, and decisions are found by project,
  by recency, or by asking. One less field to fill in. (#46)
- **Two skills that build and maintain the vault's objects.** `/new-project` creates a
  project — its index note, its decision log, and the link into the entity it belongs to —
  from a description, a pasted brief, or a file you point it at. `/update-entity` files
  free-form notes about a client, partner or business unit into the right sections of that
  entity's dossier: people, meetings, company facts, sensitivities, engagements. Both write
  through a script rather than typing markdown, so naming, frontmatter and cross-links are
  consistent every time, and a note you edited by hand is never overwritten — an update fills
  gaps and adds rows, it does not replace what is already there. Runs in Claude Code or
  Cowork; plugins do not load in Chat. (#39)
- **A project is now an initiative or an area of responsibility** — timeboxed with an end, or
  ongoing. The four previous types mixed the lifecycle question with who the project was for,
  and who it is for already lives on the project's entity. One axis, asked once. (#39)
- **Vault UX defaults.** Notebook Navigator ships preconfigured: shortcuts to the five object
  Bases (Meetings, Projects, Entities, People, Decisions) plus `60-daily-notes`, rainbow folder
  colors, all file types visible. Claude's home is also browsable in Obsidian — the vault carries
  a visible `claude/` folder (Obsidian hides dot-folders) with a `.claude → claude` symlink
  created at provisioning; on Windows without symlink privileges it degrades to a warning and the
  folder still works, Claude Code just doesn't see it. (#35)
- **Obsidian plugins and theme are provisioned, not hand-installed.** Dataview, Minimal Theme
  Settings, Style Settings, Notebook Navigator and the Minimal theme install from pinned official
  releases, each asset sha256-verified before it lands; re-running repairs a tampered or partial
  install. Vault setup collapses to Obsidian's single "trust and enable" dialog. Manual install
  stays documented for client machines without repo access. (#29)
- **Ontology reference restructured.** In-vault ontology
  (`99-workflow-config/reference/ontology.md`) now carries each object type's schema — required
  fields, enums, vocabularies — as a labelled YAML block, with the prose keeping the rationale.
  No schema change: same fields, same enums. Skills read these blocks to emit conformant
  frontmatter, so a vault edited by hand and a vault edited by Claude stay consistent. (#28)
- **The vault itself** — `structure-version` 1: folder tree with a `10-inbox/` capture landing
  zone, the five object `.base` views, ontology and lessons reference, `CLAUDE.md` behavioral
  rules, and the five context-portfolio files that `/setup-my-brain` fills during the onboarding
  interview. Objects are Meetings, Projects, Entities, People, Decisions — `Entity` covers
  clients, business units, partners and suppliers alike. (#23)
