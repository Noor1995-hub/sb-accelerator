# Message feed: mail and Teams into the vault, every evening

**Date:** 2026-09-30 · **Status:** design, awaiting Matthias's review
**Issue:** #236 (lessons and prior work in its first comment)

Every choice below is a decision taken in the brainstorm of 2026-09-30 (§2).

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
- **Nothing invented.** Every fact in a digest traces to a message that was read.
- **End users are not technical.** They never edit config or JSON, and the
  vault stays readable to them (#235).

**Success criteria**

1. After one evening run, a session asked about a project can answer from the
   vault what was said about it in mail and chat that day.
2. Excluded people, domains, chats and words never appear in the vault.
3. A missed evening, a cap that is hit or a failing source never leaves a
   silent gap: it is recorded with the command that fills it.
4. The nightly cost is measured on a real account before release (§9).

## 2. Decisions (Matthias, 2026-09-30)

| # | Decision |
|---|---|
| 1 | Purpose is ambient context for later sessions (§1) |
| 2 | **One digest per day** with all of that day's mail and chat, linked to projects, people and decisions. No note per thread, no copy per message. Follows the colleague's `m365-daily-capture` |
| 3 | Why not per thread: the mail search carries no `conversationId` (verified 2026-09-30; only a single-mail read returns it, with the full HTML body), and a Teams chat is not a thread. Multi-day topics are followed through the project and person links |
| 4 | **Review:** the digest and its links flow in without review. Only **decisions** found in mail or chat are written `reviewed: false` and land in Decisions.base's Needs review queue |
| 5 | **Read:** Teams 1:1, group and meeting chats (message text from the feed); Inbox and Sent Items (the ~250-character summary). **Not read:** Teams channels, full mails, attachments. At most 5 long chat messages per night are opened in full |
| 6 | **Exclusions** are in the first version: person, domain, chat, word (§6) |
| 7 | A **person** exclusion drops their mails and the 1:1 chat; in group chats only their own messages are dropped (option A). A **chat** exclusion drops a whole group chat |
| 8 | **Placement:** its own skill, `/sync-messages`, run by `/evening-sync` as a stage. One scheduled task. Also runnable on request |
| 9 | **Cost:** page caps per night plus a measured baseline before release; no fixed amount |
| 10 | **Off by default.** Switched on in `/setup-my-brain` after M365 is connected, or by asking in any session, with an explicit consent question. Switched off the same way |
| 11 | **No automatic backfill.** The first run starts at yesterday 00:00; "catch up on last week" runs only on request |
| 12 | Digests are **machine material, not reading material**: the owner reads mail in Outlook and chat in Teams, and sees the digests' effect, not the digests. They live in **`_messages/`** (the underscore convention of `_heavy-assets/`), hidden from the file list, search and graph. No Base, no project-note section. A new object type and a structure-version bump |
| 13 | Digests are **kept** like meeting notes. When an exclusion is added later, older digests are cleaned up **only on request**, after the owner confirms |
| 14 | **New person notes** only for real working relationships: 1:1 chat partners, and direct recipients (To, not CC) of the owner's sent mail with at most 5 recipients. Everyone else is linked only when a note already exists, so People.base's Uncurated view does not flood |
| 15 | **Digests feed project-state updates without review**, with two guards: only **strong** links queue a project (organisation domain, project name in subject or topic), and everything stage 4 takes from a digest is marked as coming from mail or chat, with a link to the digest |
| 16 | **Person notes:** backlinks, plus auto-maintained `messages-7d` / `messages-30d` counters next to the meeting counters. No body writes. A written per-person summary belongs with #184 |
| 17 | A run crossing midnight adds late items to the previous day's digest, never duplicating one |
| 18 | **The owner can teach the routing:** a project carries optional `keywords` (codes, nicknames, client terms), added by asking. The colleague's learning loop, without a table to maintain: what lands in *Not linked to a project* shows which keyword is missing |

## 3. Prior work this builds on

- **`m365-daily-capture`** (the colleague's, in daily use). Kept: *the model reads,
  code routes and writes*; the **cursor from data, not the clock**; the noise
  list; the verified tool behaviour (#236 comment). Not kept: the hand-kept
  routing table (replaced by the vault's own projects and people, §7); writing
  into `10-inbox/` (the digest needs no triage, decision 4); hardcoded paths.
- **Setup discovery (#229).** Kept: page files in scratch, the CLI builds and
  deletes them, the worker keeps raw content out of the main conversation;
  counts from files, not typed by the model; the proposal check against
  invented names; plain-language consent.

## 4. What the owner experiences

### 4.1 Switching it on

In `/setup-my-brain`, right after Microsoft 365 is connected and proven, or
when the owner says something like "start reading my mail and Teams":

1. **Consent**, in plain words: *"May I read your mail and Teams chats every
   evening, to keep your second brain up to date? I read only short summaries,
   never attachments or Teams channels, and I skip anything you tell me to."*
   No means nothing is switched on and the question is not repeated in this
   session.
2. **Exclusions**, as tick boxes built from the 1:1 and group chats in the chat
   list (`teams_list_chats`, names only), plus *Something else* for a person,
   domain or word in their own words. *"Nothing to exclude"* is a valid answer.
3. **Read back:** what will be read, what is excluded, from when (*"from
   tonight, starting with today's messages"*). Written through `config write`
   with the consent date and the exact scope (§8.3).

### 4.2 Every evening

Nothing visible. `/evening-sync` runs `/sync-messages` as a stage (§5.1). The
next morning:

- A project's **Where it stands** reflects what happened in mail and chat, each
  such item marked as coming from mail or chat with a link to its source. That
  link is the only way the owner meets a digest, and only when they want the
  source.
- Decisions found in mail or chat appear in Decisions.base's **Needs review**.
- A session asked about a project or a person already knows what was said.
- The digest itself (`_messages/2026-09-30.md`) is out of sight.
- The daily note's run summary gets one line: *"Mail and Teams: 34 messages
  read, 6 linked to 3 projects, 5 not linked."* Gaps and failures are named
  there too. The *Not linked* count is the owner's cue to teach a keyword
  (§4.3).

### 4.3 On request

| The owner says | What happens |
|---|---|
| "catch up on my mail from last week" | One run over that window, one digest per calendar day, within the night's caps; what does not fit is recorded as a gap with the command that fills it |
| "don't read my chats with Jordan anymore" | Exclusion added; read back: *"From tonight, mails to or from jordan@… and your 1:1 chat with Jordan are skipped. In group chats, only Jordan's own messages are skipped."* Then: *"I found 4 older digests that mention Jordan. Shall I remove those lines?"* Nothing changes without a yes |
| "link mails about P-2317 to the operating-model project" | Keyword added to that project; read back: *"From tonight, mails and chats with 'P-2317' in the subject or chat name are linked to Operating model."* Earlier digests are not re-linked |
| "what don't you read?" | The scope and every exclusion, in plain words |
| "stop reading my mail and Teams" | Switched off; existing digests stay; read back |

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
| `plugin/lib/vaultlib/messages.py` | new module | cursor, window, noise and exclusion filters, grouping, routing, digest render, scrub |
| `plugin/lib/vaultlib/cli.py` | changed | `messages cursor`, `messages build`, `messages check`, `messages write`, `messages exclude add/remove/list`, `messages scrub` |
| `plugin/skills/evening-sync/SKILL.md` | changed | stage 3b; the summary line |
| `plugin/skills/setup-my-brain/SKILL.md` | changed | the switch-on step (§4.1) |
| `plugin/lib/vaultlib/updatequeue.py` | changed | strong digest links count as project activity; `messages-7d/30d` person counters (§7.2) |
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
4. **Condense** (worker). Per group: 1–4 key points, and decisions if any, as
   claims citing the group's message ids. Kept in the worker; the main
   conversation never sees message content.
5. **Check** (CLI). `messages check` applies the `discover check` token rule:
   every name, number, address, domain and quoted title in a point must occur
   in the cited messages. A failing point is dropped, never rewritten.
6. **Write** (CLI). `messages write` renders the digest (§5.5), writes decision
   candidates through the existing decision writer with `reviewed: false` and
   `source: "[[<digest>]]"`, and advances the cursor to the newest item seen.
7. **Report.** The worker replies with one outcome line of counts; the skill
   sweeps scratch and hands the summary line to `/evening-sync`.

### 5.4 Kept fields

| Source | Keys kept |
|---|---|
| Teams feed | `id`, `chatId`, `createdDateTime`, `from` (`displayName`, `email`), `summary`, `channelUri` (presence only, for the drop test) |
| Chat list | `id`, `chatType`, `topic`, `members` (`displayName`, `email`) |
| Mail | `id`, `subject`, `sender`, `recipients`, `receivedDateTime`, `summary` |

### 5.5 The digest

`_messages/YYYY-MM-DD.md`, one per calendar day of messages. Its readers are
Claude sessions and the stage-4 project update; its properties are how a
session finds what was said about a project or a person, and it is the
evidence every mail- or chat-derived line elsewhere traces back to:

```markdown
---
object: digest
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
- A run's window can cross midnight; items go to the digest of their own date.
  Appending to an existing digest is a CLI merge that never duplicates an item
  (the item ids are recorded in the digest's `ids` block, hidden from reading
  view). Decision 17.
- `gaps` names any uncovered interval and the command that fills it.

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

`messages scrub --exclusion <id>` lists the lines in existing digests that
match the new exclusion (by address, chat name or word) for the owner to
confirm; only confirmed lines are removed.

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
   well.
3. **Several projects match:** the group is linked to all of them and shown
   under the first. **None match:** *Not linked to a project*, still linked to
   its people.

### 7.2 What the rest of the vault does with a digest

- **Project notes:** no new section (decision 12). Mail and chat reach a
  project note only through its state update, below.
- **Project-state updates (decision 15):** the update queue today counts
  **confirmed meetings only** ("triage is the quality gate"). Digests count
  **without** confirmation, a deliberate exception recorded in the ontology,
  with two guards:
  - only a **strong** link queues: a digest whose `projects[]` minus
    `projects-weak[]` names a project, dated after its `state-updated`;
  - stage 4 gets that project's digest section as input next to its meetings,
    and every item it takes from it (a Hot potato, an Owe, an Awaiting, a
    closed action) is marked as coming from mail or chat and links the digest,
    so the owner always sees the source.
- **Person notes (decision 16):** no body writes; the digest shows in the
  person's backlinks (backlinks work into a hidden folder). `messages-7d` and `messages-30d` are auto-maintained next
  to `meetings-7d` / `meetings-30d` by the same metrics pass, counting the
  digest groups the person is linked in, so People.base can sort by who the
  owner actually talks to. A written per-person summary is left to #184.
- **Decisions:** `source` may name a digest as well as a meeting (ontology
  change, §8.1). `reviewed: false`, so they queue in Needs review.
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
- Ontology: a **Digest** object (`object: digest`, required `date`,
  `projects`, `people`, `counts`; optional `projects-weak`, `entities`, `gaps`,
  `window-from`, `window-to`); Decision's `source` may name a digest; Person
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

- **Caps per night:** Teams feed 20 pages (the colleague's; a busy day is 5–8),
  mail 2 pages per folder, 5 full-message reads. A cap that is hit still
  advances the cursor to the newest item seen and records the uncovered
  interval as a gap, with `/sync-messages since <time>` to fill it.
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
| Cap hit | Cursor advances, gap recorded (§9) |
| Worker fails before `messages write` | Cursor does not move; next run covers the window again |
| A missed evening | The cursor still points at the last item seen, so the next run covers it, within the caps |
| Condensed point fails the check | Dropped, counted in the outcome line |

## 11. Testing

1. **Unit tests** on made-up fixtures, never real data: noise rules; each
   exclusion kind including the group-chat rule of decision 7; grouping per
   calendar day across midnight; routing rules and their order; the
   person-creation rule (1:1 and direct To with ≤5 recipients create, CC and
   incoming never); keyword matching (word boundary, case, subject vs
   summary); weak links never queue a project; `messages-7d/30d`
   counts; cursor
   advance and non-advance; gap recording; digest render and merge without
   duplicates; `--consume` deletes exactly the pages read; scrub matching.
2. **CLI tests** for every new subcommand's envelope.
3. **Skill contract tests** pinning: no date filter on the Teams feed, mail
   always folder-scoped, never a full-mail read, the caps, stage 3b's place.
4. **Migration test** for 003 on a structure-3 fixture vault, including hide settings the owner already had (merged, not replaced).
5. **Cowork run** on a consultant's own account from the dryrun channel, with
   the cost baseline of §9, before anything reaches `sb-dist`.

## 12. Open points

- **Executive volume is unmeasured**; the caps come from a consultant's
  account. Tune after the first real run.
- **Mail volume vs the 2-page cap:** a busy inbox may pass 50 mails a day.
  Measure in the Cowork run before raising it.
- **Language of the digest:** follows the owner's configured note language.
- **Routing quality is unmeasured.** Check in the Cowork run how many groups
  land in *Not linked to a project* and how many strong links are wrong; tune
  the rules from that.
