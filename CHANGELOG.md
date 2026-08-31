# Changelog

**Client-visible change only** — what the plugin, a skill, the vault template, or a migration
does differently for the vault owner and their EA. Internal work (CI, validators, fixtures, delaware-side
docs and tooling, repo plumbing) is deliberately absent: git history and the PR list already are
that record, in more detail and without drift.

Written for the consultant preparing a quarterly tune-up. Every line should be something you
would say out loud to the vault owner, or something that changes what you do at the visit. This file
ships to `sb-dist` with each release, so the client can read it — they cannot read this repo.

Entries accumulate under `Unreleased`. At release, that block becomes a
`## v<version> — <date>` section: the release notes, and the agenda for the tune-up that
delivers them.

## Unreleased

- `/sync-recordings` now fetches each transcript inside its per-recording worker instead of the main session — long-context cost and latency drop sharply on multi-recording syncs, and recordings process in parallel (#PR)
- **M365 calendar searches now reach the whole window, not just the first
  25 events.** The three skills that search the calendar (recording sync,
  evening sync, onboarding) now call the connector with its real window
  parameters — `afterDateTime`/`beforeDateTime` — and page past the
  connector's 25-events-per-call cap. Before, a busy week synced only a
  first page of meetings and the rest silently never appeared. (#125)
- **Recording sync is cheaper and harder to fool.** Extraction always runs
  in per-recording workers, Plaud transcripts are validated against the
  recorder's own duration so a partial transcript can no longer become a
  meeting note, and calendar listings are trimmed to the four fields the
  sync reads. (#126)
- **Syncing a calendar full of transcript-less meetings is now far cheaper
  and faster.** The recording sync now settles whether a Teams transcript
  actually exists — and records the answer — before handing any meeting to
  an extraction worker, instead of after. A run that used to spin up a
  worker per calendar event and come back empty now spins up workers only
  for meetings with a real transcript. Meetings whose transcript belongs to
  another organization's tenant — a permission refusal that never changes —
  are now remembered and never retried, instead of being re-checked on
  every run. (#123)
- **The Projects list now fits a 13-inch laptop.** On a 1440×900 window the
  Active view used to hide the `Updated` column off the right edge — the
  wide project-type values ate the row's width first. The column order now
  puts type (already shown in the group header) last, and a render check
  pins `Updated` staying on screen. (#115)
- **A pipe you type into a dossier table cell no longer deletes the rest of
  the cell.** Previously, writing `wants a | b comparison` by hand into a
  Stakeholders or Engagements cell made the next `/update-entity` write
  silently drop everything after the `|`, while the table looked fine in
  Obsidian. Hand-edits like that — a raw pipe, a deleted separator row, a note
  starting with `|` — are now repaired instead: nothing is lost, the file is
  tidied on the next write, and the skill tells you what was repaired.
  Sections you add to a dossier yourself are now visible to the skills too.
  Malformed *generated* updates — a misspelled field, a non-text value, a date
  that isn't `YYYY-MM-DD` — are now refused with a clear error instead of
  writing something wrong. (#114)
- **Routine syncs stop re-downloading meetings they already know about, and
  the vault never looks before its own start date.** The Microsoft 365 sync
  now remembers, per meeting occurrence, whether it was written, skipped, or
  had no transcript — so each run fetches only what is genuinely new (a
  transcript-less meeting is re-checked for 48 hours, then left alone). The
  vault also gains a start date, written at provisioning: no sync ever pulls
  in meetings from before the vault existed, which recurring calendar series
  used to do. Pre-existing vaults get the start date added at the next
  tune-up; until then they behave as before. (#116)
- **Same-day meetings now trigger an evening project-state update.** A meeting
  confirmed on the same day a project's state was last written used to be
  silently dropped from the update queue forever — the queue compared days,
  not times. Projects now carry a `state-updated` timestamp written by the
  evening run; on an existing vault the first run after upgrading may queue a
  few projects one extra time while the new stamp settles, then behavior
  converges. (#112)
- **The triage checkboxes now fit a 13-inch laptop.** On a 1440×900 window
  the Meetings triage view used to hide ✓ Reviewed, ⚠ Duplicate of and
  🗑 Archive off the right edge — the columns are reordered so the controls
  come right after the subject, and a render check now pins them there. (#113)
- **An evening run with several unrecognised names no longer loses tomorrow's note.**
  The link check now reports every unresolvable name at once, so the run's
  single retry can fix them all — previously two bad names meant no note,
  discovered the next morning. (#111)
- **A hand-edited `type` on an entity or project is now caught by
  validation.** `type: entity` and `type: project` are pinned in the
  ontology, so a stray value can no longer pass conformance silently. (#109)
- **A new `/provision-vault` skill sets up a client machine with zero repo
  checkout.** Previously, provisioning a new vault owner or EA's machine
  meant the consultant had this repo checked out on it. The skill now
  instantiates the vault, installs the pinned Obsidian plugins and theme,
  and attempts the `.claude` symlink straight from the plugin's own cache —
  the one thing every client machine already has once the plugin is
  installed. The full manual provisioning path still works as a fallback.
  (#106)
- **The vault template now ships inside the plugin.** No behavior change for
  the vault owner or their EA — every skill, `.base` view, and piece of
  onboarding prose instantiates exactly as before. The template's home in
  the repo moved from `template/` to `plugin/template/` so the whole product
  can be published as a single marketplace plugin. (#105)
- **The product's word for the person the vault serves is now "vault owner."**
  "Exec"/"executive" is gone from the skills, template, and prose — the first
  customers are executives, but not every vault owner will be one. The config
  key and CLI flag also renamed: `executive` → `owner`, `--executive` →
  `--owner`. No migration ships with this change; any existing test vault's
  `99-workflow-config/config.json` needs its `executive` key renamed to
  `owner` by hand. (#104)
- **You no longer maintain the entity on each meeting — it follows the
  project.** Once a meeting is assigned a project, its `entities` field is
  set automatically from that project's organization and kept that way; you
  only set it by hand for a meeting that has no project yet but is still
  about an entity, like an early prospect call. If a project gets
  re-triaged onto a meeting later, the evening sync now catches up any
  meeting whose entity had gone stale and fixes it quietly. (#103)
- **A dossier's "unvalidated" banner now only clears when someone actually
  reviews it.** Recording a fact into a client or partner dossier used to
  quietly remove the banner as a side effect of the write — so a dossier
  built entirely from unreviewed transcript extraction could read as
  human-verified after the first update. The banner now survives every
  content write; clearing it is a separate, explicit step. Setting or fixing
  a field on an entity that already exists — its owner, most often — also no
  longer silently does nothing: it applies the change and says so. (#100)
- **Evening and morning syncs no longer go silent.** The one step every
  unattended run always hits — clearing session scratch files — used to be
  able to stall the whole run for close to an hour waiting on a permission
  prompt with nobody there to answer it; it now runs through the vault's own
  tooling instead of a raw shell command, so one approval at setup covers
  the routine end to end. Every run, including a quiet night with nothing to
  sync, now leaves one line in a log you can check without opening the
  vault, and the nightly run no longer burns idle time — and budget —
  polling while it waits on its own subagents. (#101)
- **Your evening note now has a time.** Session 1 ends by setting up the
  standing evening run itself — you pick the hour, and the vault prepares
  tomorrow from then on, every working evening the machine is on and Claude
  is open. If it cannot be scheduled on the spot, you are told so plainly,
  along with who is setting it up and by when — instead of being promised a
  routine that was never created. `/schedule-daily-loop` moves it, or stops
  it, whenever the answer changes. (#83)
- **The Session-1 interview explains itself.** Every term is introduced the
  first time it is used, the questions start with your company rather than
  your job title, and the ones that were unanswerable or alarming are gone.
  Connectors are now offered the way you would think about them — *"shall I
  pull in your recordings and Teams meetings?"* — before any machinery
  appears. Optionally, and only if you say yes, it can read a sample of your
  own sent mail and draft your writing style from how you actually write
  rather than how you would describe it; the sample is deleted the moment the
  draft is on screen. The session now closes with what your vault can do and
  what to go and look at, not with a list of what was written. (#83)
- **Long recordings are no longer cut short.** The recorder connector hands
  over a transcript in pages, and the sync was only ever reading the first
  one — so a half-hour meeting became a note written from its first ten
  minutes, with the length to match. It now reads every page, and refuses to
  write a note at all if one is missing rather than writing a thin one. If
  you have meetings that felt oddly shallow, they are worth a second look.
  (#87)
- **Recordings sync on the first attempt.** Two mismatches inside the
  pipeline made every recording fail once and retry: a timestamp the writer
  would not accept, and a meeting type the sync had to guess at. Both are
  fixed, and the first sync of an evening is noticeably quicker for it. (#87)
- **No more permission pop-up mid-sync.** A large transcript could make the
  sync ask for access to a system folder — alarming, and never necessary.
  It no longer goes near that folder, not even to tidy up after itself.
  (#87, #96)
- **The evening run costs less.** The helpers that read your recordings and
  update your projects now run on a smaller model. Same output, materially
  cheaper per evening — which matters most for the runs you schedule and
  never watch. (#87)
- **Tomorrow's note says "tomorrow" about the right day.** The recap is
  written the evening before but read the next morning, and it used to speak
  from the wrong day. It now reads correctly on the morning you open it.
  (#87)
- **`Start here` now describes the vault you actually have.** The orientation
  note named a morning command that does not exist — the evening run writes
  tomorrow's note, so there is nothing to type in the morning — and it never
  mentioned the things you can ask for: syncing recordings, logging a decision,
  starting a project, updating a dossier, or reporting a broken flow to
  delaware. All of that is in the note now, with the plain-language phrasing
  beside each command, and it says plainly what the feedback channel does and
  does not send. (#89)
- **Teams meetings now sync themselves.** With the Microsoft 365 connector
  bound to the vault, /sync-recordings finds the past week's Teams meetings
  on your calendar, pulls their transcripts, and writes the same meeting
  notes the recorder path does — attendees and subject taken from the
  calendar invitation itself. A meeting without a transcript is simply
  reported, and when the recorder already captured the same conversation,
  the sync flags the pair for you instead of writing the meeting twice. (#80)
- **`/setup-my-brain` — the Session-1 interview now exists.** One guided
  conversation fills your context, binds your accounts with an on-screen
  yes before anything connects, seeds your first entities, projects and
  people, and ends with tomorrow's note already on screen. (#81)
- **`/upgrade-vault` — the tune-up upgrade now protects itself.** It
  snapshots the vault before it changes anything, verifies the result
  after, and logs what ran. Anything that drops content along the way is
  announced before it happens, never discovered after. (#81)
- **`/health-check` — a numbers-only health report the EA can run.** Meeting
  volume, daily-note coverage, what's gone stale — no names, no content —
  and only with your explicit approval, share it with delaware. (#81)
- **`/report-feedback` — report a broken or clumsy flow to delaware.** A
  deterministic check guarantees the report carries no names or content,
  and nothing sends without your approval of the exact text. (#81)
- **Tomorrow's note tells you when it is catching up.** After missed evenings —
  a holiday, travel, a laptop that stayed shut — the recap used to quietly cover
  the whole gap and look like any other day. It now opens by naming the window
  it covers, how many working days went without a run, and the fact that the
  skipped days are not written up separately: one note covers the stretch. Past
  a week, it recaps the recent days properly and counts the rest rather than
  compressing two months into one summary. (#56)
- **Re-running the evening sync no longer rewrites a recap you have read.** A
  second run on the same day used to regenerate the recap from scratch, which
  could quietly replace a real takeaway with a worse line. It now leaves the
  recap exactly as it was unless the meetings or your jottings actually changed.
  Company, people and project names in the recap are also read from the vault
  instead of recalled, so a near-miss like the wrong middle word in a client's
  name cannot reach the note. (#57)
- **A parked file now says why it was parked.** When the sync decides
  something you dropped in `10-inbox/` isn't a capture at all — a whitepaper, a
  deck, a stray file — it moves it to `90-archive/inbox/` and leaves a short
  note beside it: what it was, why nothing was written for it, and how to have
  it processed after all. The never-propose-again list records the reason and
  the original filename too, instead of just a content hash. Previously the
  reason existed only in that evening's run summary, so a decision made in
  August was unexplainable by November. (#73)

- **The inbox empties itself, and context that isn't a meeting is captured
  honestly.** Files you drop in `10-inbox/` now move to `90-archive/inbox/`
  once they've been handled, so what's left in the folder is exactly what's
  still outstanding — you can answer "what hasn't been processed?" by
  looking, without running anything. And an item that carries context but
  isn't a meeting — a forwarded email, a voice memo — is now written as a
  capture (`type: note`) instead of being filed as a meeting that never
  happened. It shows up in the same review queue, feeds the same project
  updates, and no longer inflates your meeting counts. Anything that isn't a
  capture at all, like a report or a deck, is parked with the reason given
  rather than forced into a note. (#55)
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
- **An entity dossier now lists its meetings by itself, and always
  correctly.** The Meeting Log used to be typed out by hand, so it was
  accurate on the day it was written and drifting from then on. It is now a
  live table — every meeting held about that organization, newest first, with
  no maintenance. What stays hand-written is the one thing a table cannot
  hold: the read of the room, under **Dynamics**. Attendees, outcomes and
  follow-ups are no longer copied into the dossier; they live in the meeting
  note, where corrections actually land. **At the tune-up:** the table only
  finds meetings tagged with the organization, so meeting notes written
  before this release need that tag added — the upgrade does it. (#60)
- **Dossiers read like project pages now.** The organization's name at the
  top (every dossier file is called "dossier", so before this the page had no
  title), background facts in a boxed summary, and sensitivities in a box that
  looks like a warning, because that is what they are. (#60)

- **Connectors are now bound to the vault, and refuse to sync anyone else's
  account.** Each vault carries a deployment config
  (`99-workflow-config/config.json`) naming its timezone, its vault owner, and
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
