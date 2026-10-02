# Changelog

**Client-visible change only** — what the plugin, a skill, the vault template, or a migration
does differently for the vault owner. Internal work (CI, validators, fixtures, delaware-side
docs and tooling, repo plumbing) is deliberately absent: git history and the PR list already are
that record, in more detail and without drift.

Written for the consultant preparing a quarterly tune-up. Every line should be something you
would say out loud to the vault owner, or something that changes what you do at the visit. This file
ships to `sb-dist` with each release, so the client can read it — they cannot read this repo.

Entries accumulate under `Unreleased`. At release, that block becomes a
`## v<version> — <date>` section: the release notes, and the agenda for the tune-up that
delivers them.

## Unreleased

- Long Teams meetings sync again. A transcript of roughly an hour or more is too large to come back from the Microsoft 365 connector in one piece, so the evening run used to report it as a fetch error, retry it every night, and park it after three days, leaving no meeting note. The full transcript was there all along: the host saves an oversized result to a file, and the sync now copies that file into its scratch space instead of giving up, then reads the whole meeting before writing the note. A transcript that is cut off is refused rather than turned into a half note. Meetings already parked for this reason come back with `sync unskip` (the run summary names the command). (#255)

- Decisions get a **Dismiss** tick, like meetings. When the evening run captured something that was not really a decision, tick Dismiss in *To review* — or in **Waiting for you** at the top of the daily note — and it leaves the queue, the *Active* view and the project page's recent decisions at once. The note stays in the vault and shows as *Dismissed* in *All*, and the evening run will not capture the same thing again. Use it for a capture that was never a decision; a real decision that was later reversed is still *Withdrawn*. A vault whose Decisions table was never edited picks this up at the next `/upgrade-vault`; project pages show it the next time the evening run updates them. (#252)

- The vault opens on today's daily note, and the note opens with what needs your eye. **Waiting for you**, at the top, holds the live review queues — meetings still to keep or dismiss, decisions still to keep — and you tick them right there; a row leaves the moment you do, and on a day with nothing waiting the block isn't shown at all. The tables use the full width of the page, and their rows are taller so every attendee is readable. Under each meeting, **Your notes** and **Your actions** (were Notes and Actions) say whose they are. In the recap, the colour legend now sits above the project pulse table it explains, and a run without new decisions says **No new decisions** instead of "none this run", which read as if none existed. Existing vaults get the opening behaviour at the next `/upgrade-vault` (structure version 5); notes written before it keep their layout, and the next note the evening run writes has the new one. (#251)

- The sidebar is one menu. Its shortcuts now read **Daily notes, Meetings, Projects, People, Organisations, Decisions**, without the position numbers, and Recent files, Tags and Properties are gone from it. The assistant's own folders (`claude`, `99-workflow-config`) and `CLAUDE.md` are hidden (Notebook Navigator's show-hidden toggle still reaches them), and archive, private and heavy assets sit at the bottom of the folder tree. The sidebar keeps one layout — menu above, file list below — instead of switching between the two when it gets narrow, and it is narrower, so pages and tables get more room. The ribbon keeps two icons, today's daily note and the quick switcher; graph view and the command palette are still there through Ctrl/Cmd+P. Notebook Navigator no longer announces updates. Existing vaults get this at the next `/upgrade-vault` (structure version 4), which merges these settings in and leaves the rest of the sidebar's state alone; shortcuts you added yourself are kept. Close Obsidian before the upgrade runs. (#246, #248)
- People fill themselves in from your meetings. After each evening run, everyone you met in a kept meeting shows **Last met** (the date of the latest one) and gains the projects of those meetings — projects you added by hand are never removed. People synced from Teams also get their email address, including people already in the vault whose email was still empty. The People table now opens **A–Z by name**, with a new *Recently met* view for who you have seen lately; the *Updated* column, which only ever showed the day a person was created, is gone. Relationship, company and role are still yours to fill in. Existing people catch up at the next evening run. (#245, #248)
- The Meetings and Decisions tables say what they mean and read left to right. Both open on their review queue with the same shape: what identifies the row (date, subject or decision, project), then the tick, then the detail. In Meetings, the triage ticks are now **Keep** and **Dismiss** (was ✅ Keep / 🗑 Archive), **Cal** reads **Calendar match** and sits after the ticks with **⚠ Duplicate of**, which now fits on a 13" laptop; the **↗** column reads **Open project** and is only in All Meetings. All Meetings has a **Status** column that changes the moment you tick — *To review*, then *Kept* — where the old Review Status kept saying needs-review until the evening run. Dismissed meetings now leave All Meetings as well as Triage (the file stays), and the Duration column is gone from All Meetings and from each project page's meeting list. In Decisions, the queue is called **To review**, its tick reads **Keep** (was ✓ Reviewed), **Supersedes** reads **Replaces**, and Status shows *Active*, *Replaced* or *Withdrawn*; *Start here* explains what To review holds. Nothing about how ticks are stored or folded changed. A vault whose tables were never edited picks this up at the next `/upgrade-vault`; one where a header was renamed or a column resized is asked first, and saying yes resets those to the new layout. Project pages lose the Duration column the next time the evening run updates them. (#244)
- A project's next milestone no longer goes stale. When the evening run found nothing to replace it, the old milestone stayed in the Projects table after its date had passed, while the project page said "none scheduled". The milestone is still the next significant event, not just the next meeting, but it is now taken from the events marked as milestones in the page's *Coming up* list, and it is cleared when none of them is still ahead, so the table, the page and the daily note agree. Each project picks this up the next time the evening run updates it. (#243)

## v0.12.6 — 2026-09-29

- Teams meetings now sync, and tomorrow's meetings are prepped in the daily note, for a mailbox set to its own time zone. Outlook answers such a mailbox's calendar in local time ("Romance Standard Time" for Brussels) instead of UTC, and the plugin used to refuse every event it could not read as UTC, so the M365 sync and calendar prep never ran. It now converts Windows and IANA time zone names; a zone it cannot identify is still refused rather than guessed. (#233)

## v0.12.5 — 2026-09-25

- The Meetings *Triage* view's two checkboxes now say what they do: **✅ Keep** (was ✓ Reviewed) confirms a note, **🗑 Archive** takes noise out of the queue while the file stays. They sit side by side right after Projects, so you check a row first and then decide, and both headers are readable in full on a 13" laptop. Only the labels and layout changed: ticks work exactly as before. A vault whose Meetings view was never customised picks this up at the next `/upgrade-vault`; a customised one is asked first. (#230)

- `/setup-my-brain` is now a short self-serve session the vault owner runs on their own, instead of a 60–90 minute interview led by a consultant. It asks only what the owner alone knows (name, role, working hours, time zone), then, with their explicit consent, reads their calendar, sent mail and Teams chat list for up to 5 minutes. It never reads the Inbox or chat text. From that read it suggests their organisations, people and current work as tick boxes to accept, change or skip. Every suggestion is checked against what was actually read before the owner sees it, so nothing invented reaches them, and raw reads are deleted as soon as they have been used. Weekly and monthly meetings are asked rather than guessed. Text to approve is shown right beside the question, and every long step is announced in the chat as it runs. Vaults already set up need nothing: this changes only how a first setup, or a re-run, goes. (#229)

## v0.11.10 — 2026-09-21

- Tomorrow's daily note now shows each meeting at the vault owner's local time. The calendar connector reports starts in UTC, and one evening run copied that clock straight into the headings, so every meeting appeared two hours early; the conversion, filtering and sorting now happen in the CLI (`m365 agenda`) instead of being left to the run. If a daily note written before this release shows the wrong times, shift its headings by hand — the prep underneath is right. (#223)

## v0.11.9 — 2026-09-21

- `/provision-vault`'s feedback-token step now explains itself before asking anything — what the token is for, and that every report is scrubbed before it reaches delaware — instead of a bare yes/no question with no context. Either the vault owner or the consultant can now be the one running the skill; it no longer says "never hand this to the vault owner." (#201, #221)

## v0.11.8 — 2026-09-17

- The vault's own `CLAUDE.md`, `Start here`, and skill prose no longer describe a second human operator (an EA) sharing the vault over Obsidian Sync — the product is single-operator only, for the vault owner. If a deployment already trained a second operator on the old model, say so at the next tune-up; nothing about how the vault itself behaves changes for them today. (#212)
- Teams meetings already captured by the recorder are skipped automatically in scheduled runs instead of being re-checked every run; the collision check now runs before the transcript is fetched. (#216)
- Teams meetings are first checked by a lightweight probe; the full sync worker runs only when a transcript exists. Scheduled runs on days with untranscribed meetings cost a fraction of before. (#217)
- A recording that fails to fetch on three different days is parked with its reason instead of being retried at every run; the run summary names the command that brings it back. (#218)

## v0.11.3 — 2026-09-16

- Teams meetings no longer go missing from the vault because of a mangled calendar link. A meeting whose internal Outlook id contained certain characters could fail to pull its transcript on every run, with nothing to show for it but a count in the run log — the evening sync now builds that link itself instead of retyping it. Meetings affected before this release sync on the next run; nothing needs re-running by hand. (#207)
- The daily note's recap cards get their colour back: **At a glance** is blue, each theme violet, **Watch** red, and the sync notes a muted grey. They shipped in v0.11.0 with their icons but no colour coding at all, because the snippet wrote the accent colour in a form current Obsidian no longer reads. Run `/upgrade-vault` — or just reinstall the plugin — to pick it up. (#206)
- On a Windows-hosted vault, the evening run no longer rewrites a recap you have already read: the fingerprint that decides whether the recap needs regenerating was sensitive to line endings, so a Windows host recomputed a different value for identical content every run. Vaults on macOS, Linux or Cowork were never affected and see no change. (#206)

## v0.11.1 — 2026-09-16

- The structure-version 3 upgrade now files every existing Owe / Awaiting / Question / Pending bullet into the project page's Background callouts, whatever spelling the evening run used for it, instead of carrying them to the Notes tail. (#192)

## v0.11.0 — 2026-09-16

- **The daily note and project pages are rewritten for reading, not just for the model.** The recap opens with an at-a-glance card, themes fold behind a headline, the project pulse is a table with a 🔴🟠🟢⚪ signal, Watch holds only real risks and the sync mechanics fold away; each meeting now has a **Prep** block plus **Notes** and **Actions** lists for you. Project pages lead with a *Where it stands* card, a dated *Coming up* table and the last ten meetings and decisions, with everything else folded under *Background*. Links to projects and organisations now open the right page. Run `/upgrade-vault` to reshape existing project pages (structure-version 3). (#189)

## v0.10.36 — 2026-09-15

- A meeting you tick as reviewed *after* its project's evening update no longer slips past the next run: the tick is stamped `confirmed-at`, the update queue treats that moment as when the meeting became new to the project, and the evening pipeline folds ticks once more right before building the queue. Meetings confirmed before this release are unaffected. (#185)

## v0.10.35 — 2026-09-15

- A Plaud recording is no longer synced twice when the connector changes how it spells the recording's id: `plaud:of_<hash>` and `plaud:<hash>` now count as one recording in the ledger, the skip list and every meeting write, and new notes store the id in one canonical form. (#180)

## v0.10.34 — 2026-09-15

- The People base gains a **Direct reports** view; set `relationship: direct-report` on a person to show them there. (#177)

## v0.10.33 — 2026-09-07

- Meetings hosted by another organisation are now recognised from the organizer's email domain before any fetch, listed per event in the sync summary as recorder territory, and never cost a worker; the sync's 403 guidance now names the two real causes (a missing home domain, or the tenant's Microsoft Graph transcript-access setting) and how to re-check after the fix; `/setup-my-brain` seeds the organisation's domains from the connected account. (#124, #174)

## v0.10.32 — 2026-09-04

- **`/provision-vault` can be re-run to finish the feedback channel later.** The channel's token often arrives days after setup, and the skill previously could not be re-run at all — its first step refuses a non-empty target — so binding it afterwards meant a consultant reconstructing two raw commands from memory. Run it again on a vault that already exists and it now recognises it, says which plugin version provisioned it, skips instantiation entirely, and offers only the feedback-channel step. (Refreshing an already-provisioned vault's *files* remains `/upgrade-vault`'s job.) (#162, #169)
- **The feedback-channel question is no longer asked before the vault exists.** It asks whether the token file has been placed inside the vault — impossible to answer honestly on a surface that renders the opening questions as a single form, which silently forced "skip" for the whole run. It is now asked after the vault is created, as a second question (#162, #169)
- A vault path the tooling cannot reach now explains both Cowork causes: a folder created after the session started (never mounted — restart with it connected; re-picking it does not remount), or a cloud session where the vault is not a filesystem. The message previously named only the second, sending a consultant to a setting that was already off (#162, #169)
- `/provision-vault` now states the Cowork precondition up front: **create the vault folder on the machine before starting the Cowork session.** Cowork's shell only sees folders that were connected when the session booted, so a folder created mid-session stays invisible to provisioning even after you pick it in the folder picker — the session has to be restarted. Claude Code is unaffected (#168)

## v0.10.30 — 2026-09-03

- `/provision-vault` step 2 now installs the Obsidian plugins and Minimal theme from copies that ship inside the plugin itself, verified against the same pinned checksums as before — so provisioning works on a machine with no network access to GitHub (Cowork's sandbox blocks release downloads by default), and the consultant no longer needs to ask a client's IT to open network egress. The by-hand fallback stays, now with the explicit instruction to pick Dataview 0.5.68 (#164, #166)
- `/provision-vault` no longer hands over a vault nobody can write into. Provisioning from Cowork (or any machine whose plugin cache is read-only) used to copy the cache's read-only permissions onto every file and folder of the new vault, reporting success with two soft warnings while the client could not add a single note; the copy is now made writable before anything else is written, and a vault location that still refuses writes fails provisioning with a clear error and hint instead (#165)

## v0.10.28 — 2026-09-03

- The vault opens cleaner: every note's Properties block starts collapsed (click the heading to expand; a note you expanded stays that way), the Meetings **Triage** view carries the new default layout — Date, Cal, Subject, Attendees, ✓, Projects, then a narrow ↗ arrow that opens the project — Decisions sits directly under Projects in the sidebar shortcuts, and decision notes plus *Start here* now use the same reading width as every other note instead of wrapping at a fixed column (#158)

## v0.10.27 — 2026-09-03

- Meetings organised by someone else no longer vanish silently from the sync: the run says which ones the connector could not read and why, and once IT grants access a consultant can force a re-check without waiting for the cache to age out (#152)
- `/upgrade-vault` now also refreshes `.base` views, `.obsidian` settings, and other plugin-owned template files on an already-deployed vault — previously only a structure migration could reach these, so a fixed Bases view or a corrected theme setting shipped in a plugin update never landed on an existing vault. Files the consultant may have hand-edited (like `CLAUDE.md`) always ask first, a refresh backs up whatever it replaces, and a refreshed `.base` view loses any column widths saved in Obsidian (they rebuild from defaults on next open) (#154)
- Every vault now keeps a provenance record of how it was set up and updated — plugin version and structure version at each provisioning and upgrade — and `/health-check` reads out whether this machine's plugin is behind or ahead of what last wrote the vault, plus whether the `.claude` shortcut is still a real link (a OneDrive-style copy silently breaks it) (#151)
- The evening sync and recording sync now dispatch their parallel workers in strict blocking batches — the idle polling that could dominate a scheduled run's cost is structurally gone (#143)
- A meeting captured by two sources in the same sync run (a Plaud recording plus the same meeting's Teams transcript) can no longer overwrite itself: the second copy is kept as a flagged sibling note that triage shows under **⚠ Duplicate of**, for you to merge or drop — previously the two could silently collapse into one note, losing the other (#142)
- The sync pipeline no longer writes off a slow worker on a flat clock: patience now scales with the recording's length (a 42-minute meeting is allowed more extraction time than a 5-minute capture), and a worker genuinely given up on is reported as a warning with its recording id so the next run retries it deliberately — long recordings can no longer be silently dropped by an impatient run (#141)
- **A decision can no longer land on the wrong project when the evening sync updates several projects at once.** Concurrent per-project workers shared one scratch filename for decision payloads, so two simultaneous writes could publish one project's decision — misattributed — into another project's log (with two clients' projects in flight, a confidentiality risk). Payload files are now named per project, and the end-of-run scratch sweep clears the new names too (#140)
- **A missed evening run can now be caught up the next morning without losing the day.** When the laptop was closed for the scheduled run, triggering `/evening-sync` the morning after used to write *tomorrow's* note — today never got one and its meetings were never prepped. The pipeline now detects the missing note: run interactively it asks whether to write today's note or tomorrow's (recommending today before noon); a scheduled run decides the same way silently (#140)
- The Projects view's Active tab now shows each project's meeting counts — last 30 days and last 7 days — as default columns, sized so they stay on screen on a 13" laptop. The counts are the ones the evening sync maintains; a project with a silent month is now visible at a glance (#139)
- Project slugs now carry the entity: `/new-project` composes them as `{entity}-{name-slug}` (the project *name* stays entity-free), so typing a slug during meeting triage picks entity and project in one gesture, and two clients can each have an "AI Transformation" project without colliding — `--slug` overrides when needed (#138)
- The meeting triage and All Meetings views gain a read-only **↗ Project** column that links straight to each assigned project's index — the editable Projects column stays the typing surface (#138)
- The evening sync now repairs a `projects:` entry hand-written as a `[[wikilink]]` instead of a bare slug — the link form dangles in Obsidian and hid the meeting from its entity's dossier; unwrappable entries are fixed in place, unresolvable ones reported (#138)
- `/sync-recordings` re-checks untranscribed Teams meetings with a lightweight probe instead of a full sync worker — the recurring cost of silent meetings drops to a fraction (#137)
- `/sync-recordings` starts minutes faster: each Teams recording's worker now fetches its own meeting data (and resolves its own attendees), and routing reads a compact vault digest instead of every project file — the main session no longer re-types calendar payloads (#136)
- `/sync-recordings` now scans only since its last successful run (2-day floor, 7-day cap after a gap) instead of re-listing a full week daily, and auto-skips Plaud clips under 60 seconds with the reason recorded (#135)
- `/sync-recordings` no longer re-checks an untranscribed Teams meeting more than once per 6 hours — repeated same-day runs stop paying a full worker per silent meeting (#134)
- `/sync-recordings` no longer trips over future meetings: the discovery window is computed by the CLI (the trailing 7 days, ending now — never reaching forward), and a meeting that hasn't ended yet is deferred until after it happens instead of being fetched — a run can no longer draft notes for meetings that haven't taken place (#131)
- `/sync-recordings` workers now run as the plugin's own lightweight agent type with the model pinned — each worker starts from a fraction of the session's context, so multi-recording syncs cost noticeably less (#128)
- `/sync-recordings` now fetches each transcript inside its per-recording worker instead of the main session — long-context cost and latency drop sharply on multi-recording syncs, and recordings process in parallel (#127)
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
