# Message feed: mail and Teams into the vault, every evening

**Date:** 2026-09-30, revised 2026-10-01 · **Status:** design, awaiting Matthias's review
**Issue:** #236 (lessons and prior work in its first comment)

Every choice below is a decision taken in the brainstorm of 2026-09-30, or in
the revision of 2026-10-01 after an end-user review of the first draft (§2).

## 1. Problem and goal

The second brain takes work off its owner: it keeps notes structured and the
daily note guides the day. It knows what happened in **meetings** (Plaud, Teams
transcripts, inbox drops) and in the **calendar**, but not what happened in
**mail and Teams chat**, where much of the owner's work actually lives.

**Goal: more context, not more tasks.** When the owner opens a session and talks
about anything, what went on in mail and chat is already in the vault, so the
session does not have to ask or search M365. Follow-ups and project updates are
welcome side effects.

**Constraints**

- **Cowork first.** Everything must work in Cowork, unattended, from the one
  scheduled evening run.
- **Separate from setup.** `/setup-my-brain` only switches it on (§4.1); the
  feature itself runs with the evening sync.
- **Nothing invented.** Every fact in a message log traces to a message that was read.
- **End users are not technical.** They never edit config or JSON, and the
  vault stays readable to them (#235).

**Success criteria**

1. After one evening run, a session asked about a project can answer from the
   vault what was said about it in mail and chat that day.
2. Excluded people, domains, chats and words never appear in the vault.
3. Nothing is lost silently: a missed evening or a failing source is caught up
   automatically for up to 7 days, and the owner is told in plain words only
   when it lasts or cannot be caught up (§9).
4. The owner can see the benefit every morning without opening anything
   extra, and is asked to act only when something needs them (§4.2).
5. The nightly cost is measured on a real account before release (§9).

## 2. Decisions (Matthias, 2026-09-30)

| # | Decision |
|---|---|
| 1 | Purpose is ambient context for later sessions (§1) |
| 2 | **One message log per day** with all of that day's mail and chat, linked to projects, people and decisions. No note per thread, no copy per message. Follows the colleague's `m365-daily-capture` |
| 3 | Why not per thread: the mail search carries no `conversationId` (verified 2026-09-30; only a single-mail read returns it, with the full HTML body), and a Teams chat is not a thread. Multi-day topics are followed through the project and person links |
| 4 | **Review:** the message log and its links flow in without review. **Decisions** from mail and chat are treated exactly like decisions from meetings: the stage-4 project update applies the same material-decision test (`/log-decision`: commits the engagement *and* changes a stakeholder's behaviour; writing nothing is valid), writes `reviewed: false`, and they are triaged in Decisions.base's Needs review. The daily note only points there (revised 2026-10-01) |
| 5 | **Read:** Teams 1:1, group and meeting chats (message text from the feed); Inbox and Sent Items (the ~250-character summary). **Not read:** Teams channels, full mails, attachments. At most 5 long chat messages per night are opened in full |
| 6 | **Exclusions** are in the first version: person, domain, chat, word (§6) |
| 7 | A **person** exclusion drops their mails and the 1:1 chat; in group chats only their own messages are dropped (option A). A **chat** exclusion drops a whole group chat |
| 8 | **Placement:** its own skill, `/sync-messages`, run by `/evening-sync` as a stage. One scheduled task. Also runnable on request |
| 9 | **Cost:** page caps per night plus a measured baseline before release; no fixed amount |
| 10 | **Off by default.** Switched on in `/setup-my-brain` after M365 is connected, or by asking in any session, with an explicit consent question. Switched off the same way |
| 11 | **No automatic backfill.** The first run starts at yesterday 00:00; "catch up on last week" runs only on request |
| 12 | Message logs are **machine material, not reading material**: the owner reads mail in Outlook and chat in Teams, and sees the message logs' effect, not the message logs. They live in **`_messages/`** (the underscore convention of `_heavy-assets/`), hidden from the file list, search and graph. No Base, no project-note section. A new object type and a structure-version bump |
| 13 | Message logs are **kept** like meeting notes. Removal only on request, after the owner confirms: when an exclusion is added, with "forget what you saved about X" at any time, and when switching off ("keep or delete what I saved?") (revised 2026-10-01) |
| 14 | **New person notes** only for real working relationships: 1:1 chat partners, and direct recipients (To, not CC) of the owner's sent mail with at most 5 recipients. Everyone else is linked only when a note already exists, so People.base's Uncurated view does not flood |
| 15 | **Message logs feed project-state updates without review**, with three guards: only **strong** links queue a project (organisation domain matching exactly one project, project name or keyword in subject or topic); everything stage 4 takes from a message log is marked as coming from mail or chat, with a link to the message log; and "that's not about this project" in a session removes the link and the item (revised 2026-10-01) |
| 16 | **Person notes:** backlinks, plus auto-maintained `messages-7d` / `messages-30d` counters next to the meeting counters. No body writes. A written per-person summary belongs with #184 |
| 17 | A run crossing midnight adds late items to the previous day's message log, never duplicating one |
| 18 | **The routing learns keywords:** a project carries optional `keywords` (codes, nicknames, client terms). Claude **proposes** them, at most once a week, from words that recur in unlinked messages; the owner only says yes. Adding one by asking still works. The colleague's learning loop, without a table to maintain (revised 2026-10-01) |
| 19 | **Honest consent** that names what is read, that short notes are **kept** in the vault, and that they hold other people's words; and that the owner can skip, stop and delete at any time (§4.1) |
| 20 | **The cap is a safety limit, not the normal coverage.** One fixed limit, set generously above a busy executive's day (Teams 20 pages, mail 8 pages per folder; checked in real use through `/health-check`, not measured up front), so a normal day is read in full and only an extreme day hits it. A day that hits it is read **most important first** and the rest of that day is skipped, not owed: no backlog. Catching up happens only after a missed evening or a failing source, for at most 7 days back; anything older is closed with one plain line in the daily note (revised 2026-10-01, replacing "gaps fill themselves") |
| 21 | **A visible moment every morning:** a short *Mail and Teams* block in the daily note, direct, with a clear call to action only when something needs the owner (§4.2). No counts and no internal terms |
| 22 | **Exclusions at setup** default to *nothing to exclude*: one short open question plus "you can tell me any time", not a list of chats |
| 23 | **The first morning** says once that mail and Teams are now included. Asked about mail from before switching on, or from an excluded person, Claude says plainly it has not read it and offers a live Outlook search |

## 3. Prior work this builds on

- **`m365-daily-capture`** (the colleague's, in daily use). Kept: *the model reads,
  code routes and writes*; the **cursor from data, not the clock**; the noise
  list; the verified tool behaviour (#236 comment). Not kept: the hand-kept
  routing table (replaced by the vault's own projects and people, §7); writing
  into `10-inbox/` (the message log needs no triage, decision 4); hardcoded paths.
- **Setup discovery (#229).** Kept: page files in scratch, the CLI builds and
  deletes them, the worker keeps raw content out of the main conversation;
  counts from files, not typed by the model; the proposal check against
  invented names; plain-language consent.

## 4. What the owner experiences

### 4.1 Switching it on

In `/setup-my-brain`, right after Microsoft 365 is connected and proven, or
when the owner says something like "start reading my mail and Teams":

1. **Consent** (decision 19), in plain words: *"Each evening I can look through
   your inbox, your sent mail and your Teams chats (not Teams channels, not
   attachments). I read the opening lines of each mail and your chat messages,
   and save short notes on what was said in your second brain, which only you
   can see. I keep them like your meeting notes; they include what other people
   wrote to you. You can tell me at any time to skip a person, a company or a
   topic, or to stop and delete everything. Shall I start?"* No means nothing is
   switched on and the question is not repeated in this session.
2. **Exclusions** (decision 22): *"Is there anyone or anything I should never
   read? For example HR matters or a private chat. You can also tell me later."*
   Open answer; no answer means nothing is excluded.
3. **Read back:** what will be read, what is excluded, from when (*"from
   tonight, starting with today's messages"*). Written through `config write`
   with the consent date and the exact scope (§8.3).

### 4.2 Every evening

Nothing to do in the evening. `/evening-sync` runs `/sync-messages` as a stage
(§5.1). The next morning, the daily note has a short block (decision 21):

```markdown
### Mail and Teams
- **Needs you:** Sam is waiting for your budget figures (mail, Tuesday).
- Operating model: Jordan moved workshop 2 to 14 Oct; you agreed.
- Acme rollout: the supplier confirmed the new delivery date in the project chat.
- **1 decision from mail to confirm** → [[Decisions.base#Needs review]]
```

- At most 5 lines. Lines that need the owner come first, marked **Needs you**,
  each with one concrete action; lines that are only context follow, one per
  project. No counts, no "linked", no internal terms.
- **Needs you** is used only when a message asks the owner for something or
  waits on them; a quiet day has none. Every line cites its message log group and
  passes the same check as the message log itself (§5.3 step 5).
- Decisions are triaged in the Base, never in the note: the note only points
  there, and only when one is waiting (decision 4).
- Once a week at most, a keyword proposal (decision 18): *"Mails about
  'P-2317' seem to be about Operating model. Say 'link P-2317' to me and I'll
  link them from now on."*
- When something is wrong for more than 2 nights (decision 20): *"I'm two days
  behind on your mail; I'll catch up tonight."* Otherwise, nothing about the
  machinery.
- The first morning after switching on (decision 23): *"From today, this note
  also covers your mail and Teams."*

Elsewhere, without the owner opening anything:

- A project's **Where it stands** reflects what happened in mail and chat, each
  such item marked as coming from mail or chat with a link to its source. That
  link is the only way the owner meets a message log, and only when they want the
  source.
- A session asked about a project or a person already knows what was said.
- The message log itself (`_messages/2026-09-30-messages.md`) is out of sight.

### 4.3 On request

| The owner says | What happens |
|---|---|
| "catch up on my mail from last week" | One run over that window, one message log per calendar day, within the cap, most important first; at most 7 days back (decision 20) |
| "don't read my chats with Jordan anymore" | Exclusion added; read back: *"From tonight, mails to or from jordan@… and your 1:1 chat with Jordan are skipped. In group chats, only Jordan's own messages are skipped."* Then: *"I found 4 older notes that mention Jordan. Shall I remove those lines?"* Nothing changes without a yes |
| "forget what you saved about the reorganisation" | The lines in message logs that match are shown in plain words; only the confirmed ones are removed (decision 13) |
| "link P-2317 to Operating model", or yes to a proposal | Keyword added to that project; read back: *"From tonight, mails and chats with 'P-2317' in the subject or chat name are linked to Operating model."* Earlier message logs are not re-linked |
| "that mail isn't about Operating model" | The link is removed from that message log group, and the project is queued so tonight's update drops the item (decision 15) |
| "what did Jordan mail me in August?" (before switching on, or excluded) | *"I haven't read that, because [it was before you switched this on / you asked me to skip Jordan]. Shall I search Outlook for it now?"* (decision 23) |
| "what don't you read?" | The scope and every exclusion, in plain words |
| "stop reading my mail and Teams" | *"Shall I keep what I saved so far, or delete it?"* Then switched off; read back (decision 13) |

## 5. Architecture

### 5.1 Where it runs

`/evening-sync` stage 3 runs `/sync-recordings` today. **Stage 3b** runs
`/sync-messages` right after it, before stage 4 (project-state updates), so
tonight's project updates and tomorrow's note can use today's messages. Stages
stay failure-isolated: a failing message stage is recorded and the evening
continues. The stage is skipped, with one line in the summary, when the feature
is off, M365 is not connected or the account proof fails.

### 5.2 Components

| Unit | Kind | Does |
|---|---|---|
| `plugin/skills/sync-messages/SKILL.md` | new skill | orchestrates one run; interactive mode for on-request runs, unattended under `/evening-sync` |
| `plugin/skills/sync-messages/references/messages-contract.md` | new reference | the worker's calls, paging, caps, kept keys, outcome line |
| `plugin/agents/sync-messages-worker.md` | new agent | fetches, condenses, writes through the CLI; replies with counts only |
| `plugin/lib/vaultlib/messages.py` | new module | cursor, window, noise and exclusion filters, grouping, routing, message log render, scrub |
| `plugin/lib/vaultlib/cli.py` | changed | `messages cursor`, `messages build`, `messages check`, `messages write`, `messages exclude add/remove/list`, `messages scrub`, `messages unlink`, `messages forget`, `messages keywords-propose` |
| `plugin/skills/evening-sync/SKILL.md` | changed | stage 3b; stage 4 reads message log sections and applies the decision test to them; stage 6 writes the *Mail and Teams* block |
| `plugin/lib/vaultlib/dailynote.py` | changed | renders the *Mail and Teams* block (§4.2) from a payload whose lines cite message log groups |
| `plugin/skills/setup-my-brain/SKILL.md` | changed | the switch-on step (§4.1) |
| `plugin/lib/vaultlib/health.py`, `/health-check` | changed | one content-free number: days that hit the limit (§9) |
| `plugin/lib/vaultlib/updatequeue.py` | changed | strong message log links count as project activity; `messages-7d/30d` person counters (§7.2) |
| `plugin/lib/vaultlib/project.py`, `cli.py` | changed | `project keywords add/remove/list`, writing the optional `keywords` field (decision 18) |
| template (`_messages/`, hide settings), ontology, migration 003 | changed/new | §8 |

### 5.3 Data flow of one run

1. **Window.** `messages cursor --vault` returns `since`: the newest item the
   last successful run saw, or yesterday 00:00 on the first run, or the start
   the owner gave. Dates come from the CLI, never from the shell.
2. **Fetch** (worker). The three sources, newest first, stopping at `since` or
   at the cap:
   - Teams: `chat_message_search(query="*")`, **no date filter**, filtered on
     `createdDateTime` locally; `teams_list_chats` to resolve chat type, topic
     and members.
   - Mail: `outlook_email_search` with `folderName` `Inbox`, then `Sent Items`,
     `afterDateTime` `since`, `order` `newest`. Never unscoped.
   - Each page is written as it arrives to `msg_<source>.p<n>.payload.json` in
     scratch, keeping only the fields in §5.4, values verbatim.
3. **Build** (CLI, deterministic). `messages build --consume` reads the page
   files, drops noise (§6.2) and exclusions (§6.1), removes duplicates by id,
   groups by chat (Teams) and by normalised subject (mail) **per calendar day**,
   routes every group (§7.1), counts from the files, records gaps, writes
   `msg_groups.payload.json`, and deletes the raw pages it read.
4. **Condense** (worker). Per group: 1–4 key points as claims citing the
   group's message ids, and a `needs-owner` flag when a message asks the owner
   for something or waits on them (it feeds **Needs you**, §4.2). No decision
   extraction here: decisions are found in stage 4 (§7.2). Kept in the worker;
   the main conversation never sees message content.
5. **Check** (CLI). `messages check` applies the `discover check` token rule:
   every name, number, address, domain and quoted title in a point must occur
   in the cited messages. A failing point is dropped, never rewritten.
6. **Write** (CLI). `messages write` renders the message log (§5.5), records any
   gap, and advances the cursor to the newest item seen.
7. **Report.** The worker replies with one outcome line of counts; the skill
   sweeps scratch and hands the summary line to `/evening-sync`.

### 5.4 Kept fields

| Source | Keys kept |
|---|---|
| Teams feed | `id`, `chatId`, `createdDateTime`, `from` (`displayName`, `email`), `summary`, `channelUri` (presence only, for the drop test) |
| Chat list | `id`, `chatType`, `topic`, `members` (`displayName`, `email`) |
| Mail | `id`, `subject`, `sender`, `recipients`, `receivedDateTime`, `summary` |

### 5.5 The message log

`_messages/YYYY-MM-DD-messages.md`, one per calendar day of messages. Its readers are
Claude sessions and the stage-4 project update; its properties are how a
session finds what was said about a project or a person, and it is the
evidence every mail- or chat-derived line elsewhere traces back to:

```markdown
---
object: message-log
date: 2026-09-30
window-from: 2026-09-29T18:47Z
window-to: 2026-09-30T18:47Z
projects: ["[[acme-industries-operating-model]]"]
projects-weak: []
people: ["[[jordan-reyes]]"]
entities: ["[[acme-industries]]"]
counts: {teams: 88, inbox: 31, sent: 9, dropped-noise: 22, linked: 6}
gaps: []
---
## Acme Industries · operating model
- **Mail "Workshop 2 agenda"** with [[jordan-reyes]]: Jordan asks to move the
  workshop to 14 Oct; you agreed.

## Not linked to a project
- **Teams 1:1 with [[sam-lee]]**: …
```

- Frontmatter follows the Meeting pattern (`projects[]`, `people[]`,
  `entities[]`), so existing joins and Bases work unchanged. `projects[]` holds
  every linked project; `projects-weak[]` is the subset linked only through a
  stakeholder or a keyword in the message text (§7.1 rules c and d), which the
  update queue ignores (decision 15).
- Sections per project, then *Not linked to a project*. The owner's own
  messages are included; "you" means the owner.
- A run's window can cross midnight; items go to the message log of their own date.
  Appending to an existing message log is a CLI merge that never duplicates an item
  (the item ids are recorded in the message log's `ids` block, hidden from reading
  view). Decision 17.
- `gaps` names a missed interval still to catch up (after a missed evening or a
  failing source); the CLI keeps open gaps in vault state, at most 7 days
  back (§9).

## 6. Privacy

### 6.1 Exclusions

| Kind | Stored as | Drops |
|---|---|---|
| person | email address | mails from or to them; the 1:1 chat; their own messages in group chats |
| domain | domain | every mail from or to that domain |
| chat | `chatId`, with its display name at the time | that chat, entirely |
| word | lowercase word or phrase | mails with it in the subject; chats with it in their topic |

Applied in `messages build`, before anything is condensed or stored. **What
this guarantees and what it does not:** the fetching worker does see excluded
items in the raw pages (the feed and the search return everything); they are
never condensed, never written to the vault, never shown in the main
conversation, and their page files are deleted by the build.

`messages scrub --exclusion <id>` lists the lines in existing message logs that
match the new exclusion (by address, chat name or word) for the owner to
confirm; only confirmed lines are removed. `messages forget --text "<what>"`
does the same for anything the owner names, at any time, and
`messages forget --all` backs "delete everything" when switching off. Removing
a message log line also queues the projects it was linked to, so their next state
update drops what came from it.

### 6.2 Noise, dropped before routing

Channel messages (`channelUri` present); bots (`@teams.microsoft.com`); empty
messages (reactions, bare images); meeting responses (`Accepted:`, `Declined:`,
`Tentative`); `Automatic reply:`; `Following:`; notification senders (a
maintained list in `messages.py`, starting from the colleague's:
`azuredevops@microsoft.com`, `notifications@github.com`, desk booking,
billing). The count is reported, the content is not.

## 7. Linking

### 7.1 Routing a group to projects and people

Deterministic, in `messages build`, from what the vault already knows, instead
of a hand-kept table:

1. **People (decision 14):** every sender, recipient and chat member whose
   address matches an existing person note's `email` is linked. A **new**
   person note (created the way meeting attendees are, `relationship` empty) is
   made only for the partner of a 1:1 chat, and for a direct `To` recipient of
   a mail the owner sent with at most 5 recipients. CC, group-chat members and
   senders of incoming mail are never created, only linked when they exist.
2. **Project, strongest first:** (a) an address domain matches a project's
   entity, the same rule as meetings' `entity-domain-match`; (b) the subject or
   chat topic contains the project name or one of its `keywords`
   (case-insensitive, word-boundary matched, as in the colleague's table);
   (c) a message summary contains one of those `keywords`; (d) a linked person
   is a stakeholder or key person of exactly one active project. (a) and (b)
   are **strong** links; (c) and (d) are **weak** and go to `projects-weak[]` as
   well. **A domain that matches more than one active project** (a client with
   several projects) makes (a) weak for all of them; only (b) can then make a
   link strong.
3. **Several projects match:** the group is linked to all of them and shown
   under the first. **None match:** *Not linked to a project*, still linked to
   its people.
4. **Keyword proposals (decision 18):** `messages keywords-propose` counts, over
   the last 7 days, words and codes that recur in subjects and chat topics of
   unlinked groups and co-occur with one project's people or domain. The top
   candidate, if any, becomes the weekly proposal in §4.2. Deterministic; the
   owner's yes is the only write.
5. **Corrections (decision 15):** `messages unlink --message log <d> --group <g>
   --project <slug>` removes one link and queues the project. Learning from
   corrections is left to #183.

### 7.2 What the rest of the vault does with a message log

- **Project notes:** no new section (decision 12). Mail and chat reach a
  project note only through its state update, below.
- **Project-state updates (decision 15):** the update queue today counts
  **confirmed meetings only** ("triage is the quality gate"). Message logs count
  **without** confirmation, a deliberate exception recorded in the ontology,
  with two guards:
  - only a **strong** link queues: a message log whose `projects[]` minus
    `projects-weak[]` names a project, dated after its `state-updated`;
  - stage 4 gets that project's message log section as input next to its meetings,
    and every item it takes from it (a Hot potato, an Owe, an Awaiting, a
    closed action) is marked as coming from mail or chat and links the message log,
    so the owner always sees the source.
- **Person notes (decision 16):** no body writes; the message log shows in the
  person's backlinks (backlinks work into a hidden folder). `messages-7d` and `messages-30d` are auto-maintained next
  to `meetings-7d` / `meetings-30d` by the same metrics pass, counting the
  message log groups the person is linked in, so People.base can sort by who the
  owner actually talks to. A written per-person summary is left to #184.
- **Decisions (decision 4):** the stage-4 agent of a queued project already runs
  decision capture over its new meetings via `/log-decision --background`. It
  now gives that the project's message log sections too, with the rules unchanged:
  the material-decision test (commits the engagement *and* changes a
  stakeholder's behaviour; tasks, opinions, scheduling and preferences are not
  decisions), dedup against `existingDecisions`, supersession only on explicit
  conflict language, never delete, writing nothing is valid. Decisions land with
  `reviewed: false` in Needs review and `source` naming the message log (ontology
  change, §8.1). A wrong one is `withdrawn`, as today. Stage 6 adds the pointer
  line to the daily note when one was written.
- **Organisation dossiers:** not written; #184 stays its own issue.

## 8. Vault changes

### 8.1 Structure version 4

- New folder `_messages/`, hidden in two places:
  - the file list: Notebook Navigator's `hiddenFolders` in the template's
    `.obsidian/plugins/notebook-navigator/data.json` (the setting exists and is
    empty today);
  - search, graph and quick switcher: Obsidian's excluded files
    (`userIgnoreFilters` in `.obsidian/app.json`).

  Wikilinks and backlinks into the folder keep working, and Claude reads it
  like any other folder. No Base.
- Ontology: a **Message log** object (`object: message-log`, required `date`,
  `projects`, `people`, `counts`; optional `projects-weak`, `entities`, `gaps`,
  `window-from`, `window-to`); Decision's `source` may name a message log; Person
  gains optional `messages-7d`, `messages-30d`; the update-queue exception of
  §7.2; Project gains optional `keywords` (a list of strings; absent means
  none, so existing projects need no migration).
- The vault's `CLAUDE.md` folder table gains the row.

### 8.2 Migration `003-structure-version-4`

Creates the folder, adds it to both hide settings (merging into whatever the
owner already has there, never replacing it), updates the ontology and
`CLAUDE.md` rows. Moves nothing, lossless, so `/upgrade-vault` needs no
confirmation gate.

### 8.3 Config

```json
"messages": {
  "enabled": true,
  "consented-at": "2026-09-30T20:14",
  "scope": ["teams-chats", "inbox", "sent-items"],
  "exclusions": [
    {"id": "x1", "kind": "person", "value": "jordan@acme.example", "label": "Jordan Reyes", "added": "2026-09-30"}
  ]
}
```

Written only through `config write` and `messages exclude`, never by hand. The
cursor lives in vault state beside `lastsync`, not in config.

## 9. Cost and limits

- **The cap is a safety limit (decision 20).** It exists so that one extreme
  day (a mailing-list flood, a paging loop) cannot make the evening run take
  hours or spend the owner's usage. It is **fixed**, and set well above a busy
  executive's day: a normal day never reaches it and is read in full. Values:
  **Teams feed 20 pages** (the colleague's; his busy days take 5–8), **mail 8
  pages per folder** (200 mails a day each for Inbox and Sent Items), **5
  full-message reads**. No measurement before release: real use tells whether
  they are high enough (below). They do not move at run time.
- **Learning from real use.** The message log counts what a capped day skipped, and
  `/health-check` gains one content-free number, *days that hit the limit*,
  shared with delaware the way its other numbers are. If it shows up on real
  accounts, the limit is raised in a release.
- **A day that hits the cap** is read most important first, and what is left
  is skipped for good, counted in the message log's `counts` as `skipped`; it is
  never owed to a later night, so no backlog can build up. The order:
  1. Sent Items;
  2. 1:1 chats, and group chats the owner wrote in;
  3. mail with the owner in `To`;
  4. mail with the owner only in CC, then group chats the owner did not write in.
- **Catching up after a missed evening** (laptop off, a failing source): the
  next run covers the newest messages first, then the missed interval, within
  the same cap. Mail is fetched for exactly that interval (`afterDateTime` /
  `beforeDateTime` on one folder); Teams is reached by paging past newer
  messages, within the feed's 1000-offset limit. At most **7 days** back; an
  older gap is closed with one plain line in the daily note: *"I couldn't catch
  up on your mail from 3 to 5 October."*
- **What the owner hears:** nothing, unless a missed interval is still open
  after 2 nights or is closed unread; then one plain line (§4.2). No commands.
- **Where the cost is:** the model's writing, not the reading. The worker
  writes trimmed page files and condensed points only; it never retypes whole
  messages.
- **Model:** the worker runs on Sonnet (the noise/keep and condense judgment is
  real, as in the colleague's capture); fetch-only could move to Haiku once
  measured.
- **Baseline before release:** one real evening in Cowork on a consultant's
  account, costed with `scripts/cost_report.py`, reported as tokens and list
  price (subscription users feel it as usage, not dollars).

## 10. Failure handling

| Case | Behaviour |
|---|---|
| Feature off, no M365, account proof fails | Stage skipped, one line in the summary |
| A source errors | Retry once; then that source is recorded as a gap, the others continue |
| Teams feed page 1 empty (search index down) | Recorded as a gap; no fallback to per-chat reads in v1 (they throttle and cap at 20 messages) |
| Cap hit | That day is read most important first; the rest is counted as skipped, never owed (§9) |
| Worker fails before `messages write` | Cursor does not move; next run covers the window again |
| A missed evening or a week with the laptop off | The cursor still points at the last item seen; the next run covers the newest messages and the rest is filled as gaps on later nights |
| Condensed point fails the check | Dropped, counted in the outcome line |
| A wrong project link | The item shows "from mail" with its source; "that's not about this project" removes it (§4.3) |
| Something sensitive was saved | "Forget what you saved about X" at any time (§6.1) |

## 11. Testing

1. **Unit tests** on made-up fixtures, never real data: noise rules; each
   exclusion kind including the group-chat rule of decision 7; grouping per
   calendar day across midnight; routing rules and their order; the
   person-creation rule (1:1 and direct To with ≤5 recipients create, CC and
   incoming never); keyword matching (word boundary, case, subject vs
   summary); weak links never queue a project; `messages-7d/30d`
   counts; cursor
   advance and non-advance; a capped day read in priority order with the rest
   counted as skipped and never owed; catch-up after a missed evening (mail
   exact, Teams within the offset limit, at most 7 days, older closed once); a domain matching several
   projects is weak; message log render and merge without duplicates; `--consume`
   deletes exactly the pages read; scrub, forget and unlink each queue the
   affected projects; keyword proposals; the *Mail and Teams* block (at most 5
   lines, Needs-you first, no counts, the decision pointer only when one was
   written).
2. **CLI tests** for every new subcommand's envelope.
3. **Skill contract tests** pinning: no date filter on the Teams feed, mail
   always folder-scoped, never a full-mail read, the caps, stage 3b's place.
4. **Migration test** for 003 on a structure-3 fixture vault, including hide settings the owner already had (merged, not replaced).
5. **Cowork run** on a consultant's own account from the dryrun channel, with
   the cost baseline of §9, before anything reaches `sb-dist`.

## 12. Open points

- **Executive volume is unmeasured.** The limits are set generously instead
  (§9) and checked through `/health-check`'s *days that hit the limit*.
- **Sensitivity labels.** Skipping mail marked Private or Confidential would be
  a strong default, but the connector returned no sensitivity field in the
  2026-09-30 test (neither in search results nor in a full read). Re-check
  before release; if it is exposed, add it as a default exclusion.
- **Decision volume from mail** is expected to be low under the material test;
  measure it in the Cowork run.
- **Delegated mailboxes** (an assistant sending on the owner's behalf) are out of
  scope for v1.
- **Two machines running the evening sync on one synced vault:** relies on the
  evening sync's existing guard against a second run; verify the cursor and
  gap state survive it.
- **Language of the message log:** follows the owner's configured note language.
- **Routing quality is unmeasured.** Check in the Cowork run how many groups
  land in *Not linked to a project* and how many strong links are wrong; tune
  the rules from that.

## 13. Clarifications from planning (2026-10-01)

Found while mapping the spec onto the code; each keeps the spec's intent.

| # | Found | Resolution |
|---|---|---|
| C1 | Message log stems `YYYY-MM-DD` would collide with daily-note stems: Obsidian resolves links by file name, and a decision's `source` is a bare stem | Message logs are named `YYYY-MM-DD-messages.md` |
| C2 | Entities store no email domains, so rule §7.1 (a) had nothing to match | The CLI derives an entity's domains from the `attendee-emails` of meetings linked to it (directly or through its projects), outside `home_domains`, seen in at least 2 meetings. No schema change, nothing for the owner to fill |
| C3 | Person notes are created from names and never carry an email, so matching by address would find no one | Each run fills a missing `email` on an existing person note from Teams chat members (display name and address arrive together), never overwriting one. New person notes from the feed are created with their address |
| C4 | The mail search returns one flat `recipients` list, no To/CC split (verified 2026-09-30) | "Direct" means at most 5 recipients, in decision 14 and in the priority order of §9 |
| C5 | The page caps bound fetching; what costs is condensing | The fixed safety limit has two parts: the page caps (fetch) and at most 40 message groups condensed per day (cost). The priority order of §9 decides which groups are condensed when a day has more; the rest are counted as skipped |
| C6 | Project-state items refuse links to unknown note kinds | `links` learns the `log` kind, so a "from mail" marker can link its message log |
| C7 | The daily note has no slot for a new block | The *Mail and Teams* block is a new optional `messages` field of the v2 recap, rendered right after *At a glance*; message logs join the recap's fingerprint inputs. Status lines (behind, first morning) and the keyword proposal are produced by the CLI, never composed |
| C8 | `/setup-my-brain`'s hard rule "chat text and the Inbox are never read" | Scoped to setup's own 5-minute read; the nightly feed has its own consent |
| C9 | A message log's body must survive merge, forget and unlink | The body is rendered from a structured block kept at the end of the note as an Obsidian comment (`%% … %%`, hidden in reading view); every change edits the data and re-renders |
