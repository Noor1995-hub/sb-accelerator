# Setup that proposes: discover → propose → confirm for `/setup-my-brain`

**Date:** 2026-09-23 · **Status:** design, awaiting Matthias's review
**Issue:** none yet (this spec is the issue)

## 1. Problem

`/setup-my-brain` takes 60–90 minutes. For the executive committee of La
Lorraine Bakery Group that is too long. The time goes to 26 open interview
questions (the five context files hold 6 + 6 + 6 + 3 + 5), asked one at a time
**before** any account is connected. The skill already proposes in a few
places (timezone, a sent-mail style draft, ±2 weeks of calendar for projects
and people), but only after the long question round, and hard rule 5 forbids
proposing organisations from the calendar at all.

A second fact changes the skill's premise: the vault owner runs the session
**alone**. The current text assumes a delaware consultant beside them. Nobody
but the owner sees their content.

## 2. Goals, non-goals, success

**Goals**

- A session of about **30 minutes**, from connecting accounts to the scheduled
  evening run.
- Setup reads the owner's Microsoft 365 first and comes with **proposals** the
  owner accepts, changes or skips, instead of open questions.
- **No invented proposals.** Every fact shown traces to something that was
  read, or to something the owner said, and a deterministic check enforces it.
- Written for the owner alone, in plain, non-technical language.
- Discovery reads **only what feeds a part of the second brain**.

**Non-goals**

- The colleague's daily mail and chat capture (`m365-daily-capture`) and
  seeding its routing table. A follow-up, see §13.
- A template or structure-version change. Existing vaults keep working without
  `/upgrade-vault` (§9.3).
- A consultant-led mode. One skill, self-serve for every deployment.

**Success criteria**

1. A run with Microsoft 365 connected completes in ~30 minutes.
2. `discover check` blocks every proposal that names, counts or quotes
   something absent from its cited evidence, proven by unit tests (§12).
3. The owner never sees an evidence id, a CLI term, or raw mail or chat
   content in a proposal.
4. Without Microsoft 365 the skill still completes, falling back to the
   current interview questions.

## 3. Decisions taken

| # | Decision | By |
|---|---|---|
| 1 | Organisations may be *proposed* from calendar and mail; only the owner confirms | Matthias |
| 2 | Everything in M365 may be read: calendar, mail summaries, Teams chats, sent mail | Matthias |
| 3 | Discovery runs live, inside the session | Matthias |
| 4 | The goal is a shorter session (~30 min) | Matthias |
| 5 | One self-serve skill replaces the consultant-led one for all deployments | Matthias |
| 6 | Approach: numbered evidence, cited proposals, deterministic checker | Matthias |
| 7 | Two reads: a quick one before "About you", everything else at once | Matthias |
| 8 | Teams chats are read as the chat list only (members, topic), never message text | Matthias |

## 4. Session flow

| # | Step | Target time | What the owner experiences |
|---|---|---|---|
| 0 | Preflight | 0 | Nothing visible: `config read`, `migrate status`, as today. |
| 1 | Welcome and connect | ~3 min | One plain sentence on what happens next. They pick what to connect (Microsoft 365, Plaud). "Is this your account?" Then, **before anything is read**: "Does your company have rules about where information like this may be kept?" Then one consent line naming what will be read, that Claude reads it in this session, and that nothing is kept except what they approve. |
| 2 | Read 1 | ~45 s | "Reading your profile and calendar…" then "done". |
| 3 | About you | ~5 min | Proposals: name, role, language, working day. Open questions asked here: which company (proposed from the mail domain when one is obvious), where they are based (the time zone is then suggested from the answer and confirmed as a choice), what people call you, a short background line. The profile carries no location, so location is never proposed. |
| 4 | Read 2 | ~1.5–2 min | "Reading your last four weeks of mail and chats…" then "done". |
| 5 | Proposals, rest | ~12 min | In order: your organisations, your work (standing responsibilities, things in flight, forums, direct reports), your people, how you write, your systems. Open questions where they fit: metrics you are judged on, how direct pushback should be, what must never leave the vault, what lands on your desk that is not yours. |
| 6 | First daily note | ~4 min | `/evening-sync` writes tomorrow's note; it is opened on screen. Unchanged. |
| 7 | Evening run | ~3 min | `/schedule-daily-loop`. Unchanged. |
| 8 | Close | 1 min | What is true now, what to look at, what happens tonight. |

The order inside step 5 is fixed because each topic gives the next its
vocabulary: organisations before work (projects join to an organisation),
work before people.

**Why two reads and not one or three.** "About you" needs only the profile,
the calendar and a few sent mails; nothing else improves it. Every later topic
benefits from all sources together (a project shows up in calendar subjects,
mail threads and chat topics at once), so the second read fetches everything
remaining before any of them is proposed. Nothing is proposed twice.

**Why not in the background.** Tested in Cowork on 2026-09-23: a subagent call
blocks the conversation until it returns, including `isolation: "remote"`.
Background overlap is not available on the surface executives use (§11).

**Re-run mode** is kept: every step first shows what is already in the vault
and offers to revise it, and step 1 offers to read the accounts again.

**Without Microsoft 365** steps 2 and 4 are skipped and every topic falls back
to the context files' own interview questions, which is today's interview.

## 5. Discovery

### 5.1 Scope: only what the second brain uses

Every source has a named destination. Anything without one is not fetched.

| Source (M365 tool) | Read | Not read | Feeds |
|---|---|---|---|
| Profile (`get_me`) | `displayName`, `jobTitle`, `mail`, `userPrincipalName`; `department` and `officeLocation` only if the tenant returns them (verified 2026-09-23: the connector returns the first four only, and `jobTitle` may be null) | anything else | About you, the owner's own addresses |
| Calendar (`outlook_calendar_search`), 4 weeks back, 2 forward | subject, start, end, organizer, attendees, `isAllDay`, `isCancelled`, `showAs` | invite bodies: the listing carries a `summary` excerpt, which `discover build` discards; `read_resource` on events is never called | working day, forums, projects, people, organisations, evening-run time |
| Mail, `Inbox` and `Sent Items` (`outlook_email_search`), 4 weeks | subject, sender, recipients, received time, the ~250-character `summary` | full mails, attachments, other folders | organisations, projects, people, language, systems |
| Teams chat list (`teams_list_chats`) | chat type, topic, members | message text, channel messages | people, projects, organisations |
| Sent-mail sample (`outlook_email_search`, `Sent Items`) | subject and `summary` of the ~20 newest | full mails | how you write, language |

Explicitly out: Teams channel messages, attachments, SharePoint and OneDrive
content, anything older than 4 weeks, anyone else's mailbox or calendar.

### 5.2 The two reads

| Read | Sources | Payload files (scratch) |
|---|---|---|
| 1 | profile, calendar, sent-mail sample | `m365_profile.payload.json`, `m365_calendar.payload.json`, `m365_sentsample.payload.json` |
| 2 | Inbox, Sent Items, chat list | `m365_inbox.payload.json`, `m365_sent.payload.json`, `m365_chats.payload.json` |

All names match the existing `scratch sweep` patterns (`m365_*.json`,
`*.payload.json`), so the sweep needs no change.

**Trimmed rows, not raw pages.** A worker can only put connector data on disk
by writing it out itself, token by token. Copying raw pages would mean
re-emitting everything, including invite excerpts, mail summaries and
40-address attendee lists: about 250 KB for one consultant's four weeks,
far too slow for a live session. So each payload file holds **one JSON
object per line, with the connector's own field names, only the fields listed
below, values copied verbatim**:

| File | Keys kept |
|---|---|
| `m365_profile.payload.json` | `displayName`, `jobTitle`, `department`, `officeLocation`, `mail`, `userPrincipalName` (those returned) |
| `m365_calendar.payload.json` | `subject`, `start`, `end`, `organizer`, `attendees` (only when 15 or fewer; otherwise `attendeeCount`), `isAllDay`, `isCancelled`, `showAs` |
| `m365_sentsample.payload.json` | `subject`, `summary` |
| `m365_inbox.payload.json` | `subject`, `sender` |
| `m365_sent.payload.json` | `subject`, `recipients` (only when 15 or fewer; otherwise `recipientCount`) |
| `m365_chats.payload.json` | `chatType`, `topic`, `memberCount`, `members` (`displayName`, `email`; only when `memberCount` is 15 or fewer) |

When a worker stops at its page cap while the connector still reported more,
it appends one line `{"moreResults": true}` so the build can record the cap.

This is also data minimisation: fields the second brain does not use never
leave the tool result. **It moves one trust point.** The evidence is now what
the worker transcribed, not the raw payload. The worker is told to copy
verbatim and never to add a row, and its reported row counts are passed to
`discover build --expect`: a source whose count does not match, or that the
worker reported as failed, is recorded with an `error` and not ingested.
That is a strong
guard, not a proof. §7's check guarantees that proposals are faithful to the
evidence; the evidence being faithful to Microsoft 365 rests on the worker.

**Read 2 runs as three workers dispatched in one message** (inbox, sent, chat
list), each writing its own file. If the surface runs parallel tool calls
concurrently, read 2 takes as long as the inbox alone; if not, the total is
the same as one worker. Nothing depends on which.

**Raw payloads are consumed by the build, not by the sweep.** The sweep takes
everything matching its patterns, which would include the evidence file still
in use. So `discover build --consume` deletes exactly the raw payload files it
has just read, by name, once the evidence file is written. It is a narrow
second deletion path, limited to the six names above. `scratch sweep` stays the
cleanup at close and catches the evidence, answer and proposal files.

Read 2's build **merges** into the evidence written by read 1: existing entry
ids stay stable, per-source counts are added to the `facts` of existing
`person` and `domain` entries (each entry keeps counts per source for exactly
this reason), and new entries are appended with the next free id.

### 5.3 Caps

Each source has a page cap, a constant in `discover.py` so it can be tuned from
measurement without touching the skill. Initial values (25 results per page):

| Source | Cap | Basis |
|---|---|---|
| Calendar | 12 pages (300 events) | 106 events in 6 weeks on a consultant's account |
| Inbox | 20 pages (500 mails) | 399 in 4 weeks |
| Sent Items | 8 pages (200 mails) | 81 in 4 weeks |
| Chat list | 4 pages (~100 chats) | 63 chats active in ~3 weeks |
| Sent sample | 1 page (20 mails) | enough for style |

A cap that is hit is recorded in the evidence (`capped: true`; trimmed rows
carry no dates, so no oldest date is recorded), and proposals built on it say "in your most recent…"
rather than "in the last four weeks".

### 5.4 The discovery worker

A new agent, `plugin/agents/setup-discovery-worker.md`, modelled on
`sync-worker-m365`. Its briefing names the read (1 or 2), the scratch
directory, and the window from `dates window`. It:

- follows the verified M365 tool behaviour from the colleague's capture skill:
  mail is always searched one folder at a time (an unscoped search degrades
  sender and nulls recipients), `summary` is used and individual mails are
  never read, chats come from `teams_list_chats` and not the message feed;
- writes each source's trimmed rows to its payload file with the Write tool,
  once per source after paging ends;
- reports back only row counts per source, caps hit and errors, never
  content.

The worker follows a contract file,
`plugin/skills/setup-my-brain/references/discovery-contract.md`, the same
split as the sync workers: a thin agent definition, the mechanics in a
reference the tests can pin.

The worker keeps raw mail and chat content out of the main conversation. The
main session only ever sees the evidence list.

## 6. The evidence list

`discover build` reads the payload files present and writes
`m365_evidence.payload.json`. It is pure and deterministic: no model involved.

```json
{
  "schema": 1,
  "window": {"from": "2026-08-26", "to": "2026-10-07", "timezone": "Europe/Brussels"},
  "sources": {"calendar": {"items": 106, "capped": false}, "inbox": {"items": 399, "capped": false}},
  "entries": [
    {"id": "E1", "kind": "profile", "text": "Job title: Chief Commercial Officer",
     "facts": {"field": "jobTitle", "value": "Chief Commercial Officer"}},
    {"id": "E12", "kind": "recurring-meeting",
     "text": "Recurring meeting \"Weekly exco\", 9 times in 4 weeks, organised from llbg.com",
     "facts": {"subject": "Weekly exco", "count": 9, "organizer_domain": "llbg.com"}}
  ]
}
```

Entry kinds, each with deterministic rules:

| Kind | Built from | Rule |
|---|---|---|
| `profile` | profile | one entry per non-empty field in §5.1 |
| `working-day` | calendar | median first start and last end on weekdays with at least one busy or tentative, non-all-day event; local time via `dates.utc_to_local`; needs ≥3 such days |
| `recurring-meeting` | calendar | same normalised subject, ≥3 non-all-day occurrences in the window |
| `domain` | calendar, mail, chats | an address domain outside `home_domains` and the owner's own domains, with counts per source; ranked by total |
| `person` | calendar, mail, chats | an address plus counts per source, ranked by total. The name comes from a chat member's `displayName` when one was seen; otherwise it is derived from a `first.last@` address and marked `name_source: address`; otherwise the address itself is shown. Calendar attendees are bare addresses (verified 2026-09-23). |
| `mail-subject` | mail | subject with `Re:`/`FW:` stripped, thread count, domains |
| `chat` | chat list | type, topic, member count |
| `system-sender` | mail | a sender that looks like a notification system (e.g. `azuredevops@…`, `…@salesforce.com`), count |
| `language` | sent sample, mail | share of summaries per detected language |
| `sent-mail` | sent sample | subject plus `summary`, for style evidence |

Noise dropped before counting: meeting responses (`Accepted:`, `Declined:`,
`Tentative`), `Automatic reply:`, `Following:`, bot senders
(`@teams.microsoft.com`), and the owner's own address as a person. Broadcast
items, meaning calendar events or chats with more than 15 attendees or
members (all-hands, facility notices, distribution lists), do not count
towards people or organisations.

The query window comes from a new `discover window` command, not from `dates
window`: on a fresh vault `sync.start-date` is setup day, and `dates window
--vault` would clamp a four-week look-back to nothing. Discovery is not a sync
(it creates no meetings), so the start-date floor does not apply to it.

Owner answers are evidence too. `discover answer --text "<verbatim>"
--question "<question>"` appends an entry `{"id": "A3", "kind": "owner-said",
"text": "..."}` to `m365_answers.payload.json` and returns the id, so prose can
cite what the owner said and is never flagged for it.

## 7. Proposals and the check

### 7.1 Proposal format

The model writes one proposal file per topic, `m365_<topic>.payload.json`:

```json
{
  "topic": "about-you",
  "items": [
    {"kind": "claim", "text": "You're Chief Commercial Officer at La Lorraine Bakery Group.",
     "cites": ["E1", "E2"]},
    {"kind": "pick", "ref": "E31"}
  ]
}
```

- A **claim** is prose plus the entries it relies on.
- A **pick** is a list item (an organisation, a person, a forum). It carries
  only an entry id. Its display name and its "based on" line are taken **from
  the entry by the CLI**, never from the model, so list items cannot be
  invented at all.

### 7.2 What `discover check` enforces

`discover check --proposal <file>` reads the proposal, the evidence and the
answers and returns `{"passed": [...], "dropped": [{"item": ..., "reasons": [...]}]}`.

For a **pick**: `ref` must exist and be of a kind valid for the topic.

For a **claim**:

1. `cites` is non-empty and every id exists (E- or A-entry).
2. Every *checkable token* in `text` appears, case-insensitively and
   whitespace-normalised, in the `text` or `facts` of at least one cited
   entry. Checkable tokens are: numbers (the digits of `9am` or `12th` too, and English
   number words, so proposals write numbers as digits), email addresses, domains,
   quoted strings (plain or curly, double or single quotes), and runs of
   capitalised words (proper nouns, with a trailing possessive `'s` ignored). A
   short stop-list covers sentence-initial words and generic capitalised terms.
3. A claim that fails either rule is **dropped**, with the reason. It is never
   softened or rewritten into something plausible.

If a topic has nothing left after the check, that topic falls back to its
interview questions.

The final context block goes through the same token rule (`discover check
--block <file>`) against the whole evidence list and every owner answer before
it is read back, so nothing can be slipped into the final prose between
approval and writing, returning `{"passed": bool, "unsupported": [...]}`.
When the owner changes a proposal, their wording is
recorded with `discover answer` first, so their own words always pass.

The first word of a sentence or bullet is not checked on its own (it is
capitalised for grammar, not because it is a name); a capitalised run of two
or more words is still checked from its second word. Segments are sentences
and lines only: a clause after a colon, semicolon, dash or table pipe is
checked from its first word. A period after an abbreviation such as "e.g."
or "etc." does not end a sentence, and a word preceded by a bracket or quote
is never treated as sentence-initial.

### 7.3 What the check cannot prove

It proves that the facts exist. It cannot prove that an **interpretation** is
right: "this is something with an end date", "you chair this forum", a
proposed time zone derived from an office location, or a style observation
without a quoted phrase. These are never stated as facts:

- Types are always the owner's choice: organisation type (`client`,
  `business-unit`, `partner`, `supplier`, `other`), project type
  (`area-of-responsibility`, `initiative`), time zone. Shown as a question with
  a suggested default, e.g. "Looks like something with an end date, is that
  right?"
- Lowercase names, and a single-word name that opens a sentence, would escape
  the proper-noun rule. This is the check's known gap; picks close it for
  every list, and read-back closes it for prose.

## 8. What the owner sees

- **No evidence ids, no CLI or plugin terms.** Every proposal comes with a
  "Based on…" line in plain words: *"Based on 9 'Weekly exco' meetings in the
  last four weeks."*
- Prose blocks: **Accept / Change / Skip**.
- Lists: tick boxes with the evidence under each name (AskUserQuestion,
  `multiSelect`). The picker holds at most 4 options per question and 4
  questions per screen, so the top ~12 candidates fit on one screen; "Other"
  adds anyone missing.
- Plain words: "organisation", not "entity"; "your evening note", not
  "daily note"; "accounts", not "connectors" or "adapters". Every other term is
  introduced in half a sentence, as the current skill already requires.
- Waits are announced before they start, with what is being read, and end with
  a one-line "done".

## 9. Changes to the skill

### 9.1 `plugin/skills/setup-my-brain/SKILL.md`

Rewritten for the owner running it alone, with the flow in §4, the two reads,
the proposal and check loop, and the degradation table in §9.4. Phases 4 and
4b (first daily note, evening run) and phase 5 (close) are kept; only their
wording changes from consultant-present to self-serve. The existing
consultant-facing footnote ("one line of counts for the consultant's record")
is dropped: there is no consultant in the room.

### 9.2 Hard rules

| Rule | Change |
|---|---|
| 1 Fill, never scaffold | unchanged |
| 2 Pending migrations stop the session | unchanged |
| 3 Nobody types an email; nothing is read before the account is proven | unchanged, and it now gates both reads |
| 4 A whoami payload or mail sample is deleted the moment it has been used | extended: every raw payload is deleted by `discover build --consume` the moment it has been built into evidence; the evidence, answers and proposals are swept at close |
| 5 Entities come from the owner, never from the calendar | **replaced:** organisations may be proposed from calendar and mail; only the owner confirms |
| 6 Every block is read back and approved before it is written | unchanged |
| 7 Every write goes through the CLI | unchanged |
| 8 Prefer fewer, confirmed objects | unchanged; picks are pre-ranked and capped at the top candidates |
| 9 The evening run is scheduled or explicitly handed off | unchanged |
| new | Nothing is shown to the owner that `discover check` did not pass |
| new | Chat message text is never read |
| new | The company-rules question is asked before either read, and a "no" stops discovery |

### 9.3 Interview questions stay in the vault

The context files keep their `## Interview questions` sections unchanged: no
template edit, no structure-version bump, no migration, and already
provisioned vaults (La Lorraine's included) work as they are. For each
question the skill decides whether an **accepted** proposal already answers
it. If so it is skipped; if not, or if unsure, it is asked. Without M365 every
question is asked, which is today's interview.

### 9.4 Degradation

| Missing | Read 1 | Read 2 | Topics |
|---|---|---|---|
| M365 | skipped | skipped | interview questions only |
| Plaud | unaffected | unaffected | unaffected |
| Company rules forbid reading | skipped | skipped | interview questions only |
| A source errors or is empty | recorded in the evidence | recorded | topics without evidence fall back to their questions |
| A cap is hit | recorded | recorded | proposals say "most recent…" |
| Scheduler | unaffected | unaffected | evening run handed off, as today |

## 10. Components

| Unit | Kind | Does | Depends on |
|---|---|---|---|
| `plugin/lib/vaultlib/discover.py` | new module | `window`, `build` (with merge and `--consume`), `answer`, `check`; entry rules, caps, noise filters, token extraction | `dates.py`, `m365.load_listing`, `config.m365_home_domains` |
| `plugin/lib/vaultlib/cli.py` | changed | adds `discover window`, `discover build`, `discover answer`, `discover check` with the usual JSON envelope | `discover.py` |
| `plugin/agents/setup-discovery-worker.md` | new agent | fetches the sources its briefing names into trimmed payload files, reports counts only | M365 connector tools, Write |
| `plugin/skills/setup-my-brain/references/discovery-contract.md` | new reference | the worker's calls, paging, caps, kept keys and outcome line | |
| `plugin/skills/setup-my-brain/SKILL.md` | rewritten | the flow in §4 | all of the above, existing CLI writes |
| `plugin/.claude-plugin/plugin.json` | changed | version bump | |
| `CHANGELOG.md` | changed | one client-facing line under `Unreleased` | |

## 11. Measurements behind this design (2026-09-23)

Taken on a delaware consultant's account, a stand-in for an executive's volume,
not a substitute for it. Out-of-office until 2026-08-27 lowers the figures
slightly.

| Measure | Result |
|---|---|
| Inbox, 4 weeks | 399 mails (~16 pages) |
| Sent Items, 4 weeks | 81 mails (~4 pages) |
| Calendar, 4 weeks back + 2 forward | 106 events (~5 pages) |
| Teams message feed, 1 week | ~656 messages, 35 pages of 19 results |
| Teams message feed, 4 weeks | would need ~140 pages; the tool stops at offset 1000, reached after ~3 weeks |
| Teams feed, 92 calls by a worker | ~11 minutes, ~840k tokens |
| Throttling (HTTP 429), with and without a date filter | none observed |
| Cowork, background subagent | not available; the call blocks the conversation (~29 s for 4 calls) |

The Teams figures are why chats come from the chat list (decision 8). The
Cowork result is why the reads are sequential (decision 7).

## 12. Testing

1. **Unit tests** (`scripts/tests/test_vaultlib_discover.py`) on made-up
   payload fixtures, never real data:
   - `build`: each entry kind, noise filters, `home_domains` exclusion, caps
     recorded, missing payload files tolerated; read 2 merges into read 1's
     evidence with stable ids; `--consume` deletes exactly the files it read
     and nothing else;
   - `check`: a claim with an uncited proper noun is dropped; a number absent
     from the evidence is dropped; an unknown cite is dropped; a pick with an
     unknown ref is dropped; an owner answer makes a claim pass; a block with a
     smuggled name is dropped.
2. **CLI tests** in `test_vaultlib_cli.py` for the three subcommands and their
   envelopes.
3. **Skill contract tests** (`test_skill_contracts.py`) updated for the new
   hard rules and flow.
4. **Scratch-vault run** in Claude Code on a consultant's own account, timing
   each read and the whole session against the 30-minute target.
5. **Cowork run** from the dryrun channel before anything is promoted to
   `sb-dist`.

## 13. Open points and follow-ups

- **Executive volume is unmeasured.** The caps in §5.3 come from a
  consultant's account; tune them after the first real run.
- **Read 2's duration is the biggest risk to the 30-minute target.** About
  80 KB of trimmed rows for one consultant's four weeks is roughly 20k output
  tokens across the three workers. Measure it in the scratch-vault run
  (§12.4); if it is too slow, lower the Inbox cap first, since it is the
  largest source.
- **`teams_list_chats` ordering** is resolved: the tool's own description says
  results are ordered by most recent message first, and that
  `lastUpdatedDateTime` is rename or membership time, not activity. The chat
  list therefore cannot be cut at exactly four weeks; the page cap bounds it.
- **Language detection** in `discover build` must stay deterministic; a small
  stop-word heuristic for Dutch, French and English is enough for a proposal
  the owner confirms.
- **Follow-up:** port the colleague's daily mail and chat capture, and seed
  its routing table (keywords, attendees, project slug) from the projects and
  people confirmed here.
