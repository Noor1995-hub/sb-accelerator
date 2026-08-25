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

- **The decision queue is now something you can work.** `Decisions.base` opens
  on **Needs review**, and that view carries the ✓ Reviewed checkbox — so a
  decision captured overnight gets validated where you read it, in one click.
  A duplicate capture now says what it is: when the sync keeps a recording as
  a separate note rather than overwrite a meeting you had already confirmed,
  Meetings triage flags it under **⚠ Duplicate of**, and clearing that field is
  how you tell the next run the duplicate is settled. The old
  "needs-attention" status is gone — a vault set up before this release may
  still hold a few meeting notes carrying it, and those stay out of the
  triage queue until the pending vault migration runs, so check for them at
  the next visit. Sync and evening summaries read as sentences instead of
  field names. (#58)

- **The vault no longer carries its own installation notes.** Three notes that
  explained how the vault is *set up* — a `README` at the root and two under
  `claude/` — were visible in your file tree and in search, alongside your own
  notes. They have moved out of the vault into delaware's deployment
  documentation. `Start here` is now the only orientation note, and it also
  explains the `claude` folder, which was visible but unexplained. (#68)

- **Connectors are now bound to the vault, and refuse to sync anyone else's
  account.** Each vault carries a deployment config
  (`99-workflow-config/config.json`) naming its timezone, its executive, and
  which capture channels are on. A connector (Plaud, Microsoft 365) only
  lists content after the signed-in account matches the account written in
  the config — a mismatch is refused outright, and an unattended run raises
  an alert instead of syncing. Raw connector data is wiped from the work
  area at the end of every run. (#54)
- **The vault looks the way it was meant to.** Table columns now show their
  intended headings — "Subject", "Review Status", "Duration" — instead of the
  raw property names every shipped vault had been showing. Headings are
  colour-coded by level, pages are wider and more readable, and the bookkeeping
  markers the evening routine writes into daily notes are no longer visible
  while you type. (#60)
- **A "Start here" note, pinned first in the sidebar.** A fresh vault used to
  open on a blank tab with nothing explaining the daily loop, the five tables,
  or what a review tick means. Now it opens on a page that does. (#60)
- **Editing properties in Obsidian no longer risks corrupting a note.** Obsidian
  rewrites a note's whole property block on any edit — quotes disappear, lists
  change shape — and a later plugin write over that rewritten form could leave
  the note unreadable, silently dropping the project from metrics and views.
  Plugin writes now handle every rewritten form, repair the known corruption
  shape where possible, and explain exactly what to fix when they cannot. (#53)
- **`/evening-sync` — the vault maintains itself overnight.** One run syncs the
  day's recordings, folds review ticks into confirmations, refreshes each
  project's meeting metrics, updates the state of projects with new confirmed
  meetings, captures decisions for review, and writes tomorrow's daily note: a
  recap of today plus a prepared section per upcoming calendar meeting. Runs
  unattended on whatever schedule the engagement chooses, or by hand after a
  missed evening. (#16)
- **Daily notes become the one daily artifact.** Each day gets a single note in
  `60-daily-notes/`, written the evening before: recap on top, one section per
  meeting with prep, room to jot underneath. Jot freely — the machine only ever
  rewrites its own marked regions, and the evening run reads your jottings back
  into the recap and decision capture. If tomorrow's calendar changes after the
  note is written, the next run says so and leaves the note alone rather than
  re-filing prep under the old meeting headings. The separate morning brief is
  gone on purpose: tomorrow's note *is* the morning brief. (#15)
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
