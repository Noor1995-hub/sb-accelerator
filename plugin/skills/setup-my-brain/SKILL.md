---
name: setup-my-brain
description: The Session-1 setup, run by the vault owner on their own — connects their accounts, asks who they are, reads their calendar, sent mail and Teams chat list for up to five minutes with their consent, proposes their organisations, people and work for them to accept, change or skip, and ends with their first evening note and a scheduled evening run. Triggers when the user invokes /setup-my-brain.
user_invocable: true
origin: net-new
---

# Set Up My Brain

Session 1, run by the **vault owner on their own**. Nobody from delaware is in
the room, and nobody but the owner sees what is read. By the end the vault
knows who its owner is, which accounts belong to it, what they work on and
with whom; it has written tomorrow's evening note while they watch, and that
note has a standing time it arrives.

What only the owner knows — who they are, when they work, what they are
working on — is **asked**. What their accounts show better than memory —
the organisations and people they deal with, the forums they sit in — is
**read** for up to 5 minutes, with their consent, and **proposed**. Every
proposal is checked against what was actually read before they see it — see
"How every proposal works".

**Precondition: a provisioned vault.** This skill *fills*; it never
scaffolds and never provisions. Provisioning is delaware's step, done with
`/provision-vault` before this session. Pointed at an ordinary folder, step 0
stops — that is the correct outcome, not a gap to work around.

## Speaking to the owner

The owner is a busy executive, not a technologist, and they are alone with
this. Everything they read must make sense without help.

- **Plain words.** Say "organisation", not entity; "your evening note", not
  daily note; "your accounts", not connectors or adapters; "project" or
  "responsibility", not initiative or area of responsibility. Any other term
  gets half a sentence the first time: "your evening note — the page the
  vault writes you each evening for the next day".
- **Never show machinery.** No evidence ids, file names, commands, JSON,
  error text, or raw mail, chat or calendar content. If something fails, say
  what it means for them in one sentence ("I couldn't read your chats, so
  I'll ask about the people you work with instead").
- **One topic at a time.** A proposal, their answer, then the next. Never a
  wall of questions.
- **Choices as choices.** Use **AskUserQuestion** for anything with known
  options: Accept / Change / Skip on a proposal, tick boxes for lists, the
  type of an organisation, a time. It shows at most four options per question
  and four questions per screen, and it needs those fixed options: it fails on
  a question without them. An open question goes in plain text, in the chat —
  several short ones may share one message.
- **Announce every long step** before it starts, and say "done" when it ends.
  Never guess a duration: the only one you may give is "up to 5 minutes" for
  the read, because a clock enforces it.
- **Their words over your summary.** When they change a proposal, use what
  they typed. Compress and organise; do not re-voice.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say so
plainly rather than starting a setup whose answers go nowhere.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

`$SCRATCH` is the session scratch directory: raw reads, the evidence list,
the owner's recorded answers, proposals and draft blocks live there, never in
the vault. The JSON envelope and interpreter resolution are documented in the
plugin's `CLAUDE.md`. Read `ok` on every call; on failure act on `error` and
`hint` yourself, and tell the owner only what it means for them.

Every file this skill or its worker write in `$SCRATCH` has a name the
scratch sweep catches: `plaud.whoami.json`, `m365.whoami.json`, the
`m365_*.payload.json` discovery files (page files, the clock, answers,
evidence, proposals), and `*.block.md` drafts. Two deletion paths exist and
no others: `discover build --consume` deletes exactly the page files it has
just turned into evidence, and the sweep takes everything else:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

A sweep takes *everything* matching, so it runs only where this skill says:
after connecting accounts (before any discovery file exists) and at the
close.

## Usage

```
/setup-my-brain
```

No arguments, and **no unattended mode**: every step has the owner in it.

## Step 0 — preflight

Two read-only checks, before anything is said.

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

- **`ok: false`** — there is no `99-workflow-config/config.json`: this folder
  is not a provisioned vault, or the vault root is wrong. **Stop the session
  here.** Never run `/provision-vault`, never create `99-workflow-config/` or
  any other folder or file in this folder — not even when it is empty, not
  even when it would be quicker. Tell the owner in one line that their vault
  has not been set up yet and that delaware sets it up before this session
  (`playbooks/provisioning-runbook.md` is the reference for whoever does it).
- **`ok: true`** — carry `config` and `missing` forward. On a fresh vault
  `missing` is exactly `["owner", "sync.start-date", "timezone"]`; that is
  the honest state, not an error — this skill fills all three. Account
  bindings show up as `enabled: false` under `adapters` in `config`, never in
  `missing`.

```bash
python3 "$VAULTLIB" migrate status --vault "$VAULT"
```

If `pending` is non-empty, **stop** and hand off to `/upgrade-vault`, in one
plain line: the vault needs an update before setup, and nothing has been
asked yet. Come back once the upgrade is done.

### Fresh run or re-run

A config whose `timezone` and `owner` are null is a **fresh run**.

Anything already filled means **re-run mode** — a second session, or a
restart after an interrupted one. In re-run mode every topic starts by
*showing what is already there* (the current block from `context read`, the
current config values, the organisations, projects and people already in the
vault) and asking whether to revise it; step 2 also offers to read their
accounts again. Revising is cheap and repeating is harmless: `context write`
replaces its block, `config write` sets a field, `person ensure` and `entity
ensure` return `created: false` on an object that exists (`entity ensure`
also applies any `--name`, `--type`, `--status` or `--owner` you pass and
reports `changed` and `updated`; `person ensure` never rewrites a note and
reports a differing `--name` under `ignored`). `project scaffold` **refuses**
a slug that already has a folder: acknowledge it in one line ("that one's
already there") and move on.

## Step 1 — welcome and connect

Open with one plain sentence about what happens and why:

> *Let's set up your second brain. I'll ask you a few
> things only you know, look through your recent calendar, mail and chats if
> you allow it, suggest who and what you work with, and you tell me what's
> right. Nothing is kept except what you approve.*

### Which accounts

Ask with **AskUserQuestion**: Microsoft 365 (calendar, mail, Teams), Plaud
(the pocket recorder), both, or neither. Say what each is in one breath, and
what "neither" means (the degradation table at the bottom is the script).
Then, for each one chosen, check whether it is live in this session. If it
is not, say who needs to switch it on and move on without treating it as a
failure.

Connect accounts only here, before step 2. An account switched on later in
the session waits for the next run of /setup-my-brain: reconnecting now
would sweep away the answers already recorded.

**Nobody types an email address — no exceptions.** The account hint is
copied **verbatim from the whoami payload**, character for character, or the
connection does not happen.

#### Plaud

With the owner signed in, call `get_current_user` on the Plaud connector and
write the raw JSON to `$SCRATCH/plaud.whoami.json` with the Write tool —
never echo a large payload through Bash. Show the account name and device
name from it and ask *"Is this your account?"* Wait for an explicit yes. On
yes, take `id` or `email` verbatim from the payload:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.account_hint --value "<verbatim from the payload>"
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.enabled --value true
python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter plaud --identity "$SCRATCH/plaud.whoami.json"
```

`match: true` is the only acceptable result. Anything else: re-copy from the
payload, never retype it, never loosen the hint. If it cannot be resolved,
put the adapter back before moving on:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.enabled --value false
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.account_hint --null
```

Then sweep the payload:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

#### Microsoft 365

Identical steps: the whoami tool is `get_me`, written to
`$SCRATCH/m365.whoami.json`; the hint comes from `mail` or
`userPrincipalName`; the adapter is `m365`. Note the `displayName` shown in
the payload now — step 2 offers it as their name.

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.account_hint --value "<verbatim from the payload>"
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.enabled --value true
python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter m365 --identity "$SCRATCH/m365.whoami.json"
```

Once `match: true`, take the domains after the `@` in `mail` and
`userPrincipalName` (deduplicated) and write them. They are the
organisation's own domains, which is how the vault tells colleagues from
outside organisations:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.home_domains --value "<domain>[,<domain>]"
```

Ask whether their organisation uses other email domains (subsidiaries, older
names) and, if so, append them to the same `--value` (the write replaces the
whole list). An unresolved mismatch unwinds exactly like Plaud's, with
`adapters.m365`. Then sweep the payload:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

## Step 2 — what only they know

Everything here is asked; nothing here is read from their accounts. Record
each answer verbatim as you get it — later proposals and blocks may cite
only what was read or what they said:

```bash
python3 "$VAULTLIB" discover answer --dir "$SCRATCH" --question "<the question>" --text "<their words>"
```

In this order:

1. **Company rules.** *"Does your company have rules about where information
   like this may be kept?"* Their answer feeds
   `preferences-and-constraints`. If it rules out reading their mail or
   chats, there is no read: say so, and skip the consent question below.
2. **About them.** One choice first: their name, with the `displayName` from
   step 1 as the first option and "Other" for a different one. The language
   of their evening note is a choice too. Everything else is open, asked in
   plain text in one message: what people call them, the company they work
   for, their role, one line of background, and their working hours (start
   and end of a normal day). Record the company as they name it — their mail
   domain is not a company name, and never infer one from it.
3. **Where they are based.** Offer the time zone as a choice ("You're in
   Brussels, so Brussels time?") rather than asking for an identifier, and
   write it:

   ```bash
   python3 "$VAULTLIB" config write --vault "$VAULT" --field timezone --value "Europe/Brussels"
   ```

   Record their answer as the words of the option they chose ("Brussels
   time"), not as "Yes", so the identity block can say it.

Write the `identity` block from these answers through step 7 of "How every
proposal works" (the check needs no read for a block made of their own
words). Then make the owner's own record with the name they gave:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Alex Rivera"
```

Take `slug` from the result — never slugify the name yourself — and record
it as the join key every later skill uses for "the vault owner":

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field owner --value alex-rivera
```

If `config read` reported `sync.start-date` in `missing`, stamp today. There
is no question to ask: this is the vault's start by definition.

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field sync.start-date --value <today, YYYY-MM-DD>
```

No sync ever considers a meeting dated before it. The read below is not a
sync — it writes no meetings — which is why it has its own window.

### The consent question

With Microsoft 365 connected and no company rule against
it, ask with **AskUserQuestion** (Yes / No):

> *May I look through your calendar, your sent mail and your list of Teams
> chats for up to 5 minutes? I read the newest first, I never read the
> text of your chats or your inbox, and I keep only what you approve.*

**No** is a complete answer: skip step 3 and use "Without Microsoft 365"
for every topic. Do not ask again, and do not argue.

## Step 3 — the read (up to 5 minutes)

Only after a yes. Say it now: *"I'll look through them for up to 5 minutes —
you'll hear from me when I'm done."* Then:

```bash
python3 "$VAULTLIB" discover window --timezone <tz>
python3 "$VAULTLIB" discover clock-start --dir "$SCRATCH" --budget 300
```

Dispatch **one** `setup-discovery-worker` agent. Its briefing names the
contract path
`${CLAUDE_PLUGIN_ROOT}/skills/setup-my-brain/references/discovery-contract.md`,
`$SCRATCH`, `$VAULTLIB`, the `calendar` and `mail` windows and `page_caps`
from the window result. Its whole reply is one outcome line of row counts.

Then build the evidence and delete the page files in the same call:

```bash
python3 "$VAULTLIB" discover build --vault "$VAULT" --dir "$SCRATCH" --expect "<source>=<rows>,..." --consume
```

> If the build itself fails (`ok: false`), never open or edit a page file:
> treat the whole read as failed and use "Without Microsoft 365" for every
> topic.

`--expect` carries the row counts from the worker's outcome line
(`profile=1,chats=62,sent=40,calendar=30`); pass `<source>=error` and
`<source>=unread` through as they are. The build records any source whose
count does not match, or that failed, with an `error` and skips it.

Take only the `<source>=<rows>` pairs from the reply: drop the
`discovery-ok:` prefix, the ` stopped-by-clock` flag and the `elapsed=`
timings. Keep the whole reply line in mind: if the owner asks how the read
went, show it to them as it is — the one exception to "never show
machinery", because they asked for it. If the reply is not
a `discovery-ok:` line at all — a `discovery-error:` line, or nothing
usable — treat the whole read as failed: do not run the build, and use
"Without Microsoft 365" for every topic.

A source whose entry under `sources` carries an `error` is treated as empty:
its topics fall back to their questions. A source marked `capped` was cut
short, or never reached, by the clock: proposals from it speak of "your most
recent" meetings, mails or chats. Say "done", and tell the owner only what
any gap means for them ("I couldn't read your calendar, so I'll ask about
your meetings instead").

The result's `entries` (id, kind, label, detail, text) are the **only**
material any later proposal may use.

## How every proposal works

This loop is the same for every topic below.

1. **Draft only from `entries`** and the owner's recorded answers. Never
   from memory, from the raw rows, from public knowledge, or from what people
   in this role usually do.
2. **Write the proposal** to `$SCRATCH/m365_<topic>.payload.json`, where the
   topic is one of `about-you`, `organisations`, `work`, `people`, `style`,
   `systems`:

   ```
   {"topic": "work", "items": [
     {"kind": "pick", "ref": "E7"},
     {"kind": "claim", "text": "You meet your leadership team in the \"Weekly exco\".", "cites": ["E7"]}
   ]}
   ```

   A **pick** is one list item — an organisation, a person, a forum, a
   thread — and carries only the entry id; its name and evidence come from
   the entry, never from you. A **claim** is prose: every name, number,
   domain, email address and quoted title in it must appear in the entries or
   answers it cites. Put meeting and thread titles in double quotes. Write
   numbers as digits. Copy times exactly as the evidence or their answer
   shows them. Never start a line of a claim with a name: lists go through
   picks.
3. **Check it:**

   ```bash
   python3 "$VAULTLIB" discover check --dir "$SCRATCH" --proposal "$SCRATCH/m365_work.payload.json"
   ```

   **Show only what is under `passed`.** A dropped item is gone: never
   reword it until it passes, never mention it. If nothing passed, ask that
   topic's own interview questions instead (see "Without Microsoft 365").
4. **Show it plainly.** A claim is shown with a "Based on:" line that
   repeats its `based_on` texts exactly as returned — never reworded or
   summarised (you may translate only the words "Based on"). A pick becomes
   an AskUserQuestion option: its `label` as the option, its `detail` as the
   description. A person entry with a `note` has a name derived from their
   email address: show the address too, and ask them to confirm the name.
5. **Accept / Change / Skip.** On a change, record their words first, then
   use them:

   ```bash
   python3 "$VAULTLIB" discover answer --dir "$SCRATCH" --question "<what you proposed>" --text "<their words, verbatim>"
   ```

   Their words become an `A…` entry that a claim may cite.
6. **Interpretations are questions, never claims.** Whether something is a
   standing responsibility or a project with an end, what type an
   organisation is, which time zone, what time the evening run fires: offer
   the likely answer as the first option of a choice, never state it.
7. **Writing a context block.** Assemble it from accepted claims and the
   owner's answers only — markdown prose and bullets, short and factual, no
   marker comments. Write it to `$SCRATCH/<stem>.block.md` only now, check
   it, read it back, and write it on approval:

   ```bash
   python3 "$VAULTLIB" discover check --dir "$SCRATCH" --block "$SCRATCH/identity.block.md"
   python3 "$VAULTLIB" context write --vault "$VAULT" --file identity --content "$SCRATCH/identity.block.md"
   ```

   `passed: false` in the check's `result` lists the `unsupported` words:
   take them out, or ask the owner and record their answer, then check again.
   Never write a block that did not pass.

For each context file, read `99-workflow-config/context/<stem>.md` with the
Read tool first. Its `## Interview questions` are the full set for that
file: skip a question only when an accepted proposal or a recorded answer
already answers it; ask it when not, or when you are unsure.

## Step 4 — your organisations

Explain once: *an organisation is any group you deal with — a client, a
partner, a supplier, a regulator, your own company, or a department inside
it.* Propose from the `domain` entries as tick boxes, top first, plus their
own company from step 2. For each ticked organisation, ask its type as a
choice — `client`, `business-unit`, `partner`, `supplier`, `other` (their own
company and its departments are `business-unit`) — and its name as they say
it:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" --slug meridian-freight-holdings \
  --name "Meridian Freight Holdings" --type client --status active --owner alex-rivera
```

The slug is the name they gave, lowercase and hyphenated
(`meridian-freight-holdings`).

## Step 5 — your work

This is where their own words matter most; the read only offers suggestions.

1. **Forums.** Propose the `recurring-meeting` entries as tick boxes: the
   meetings they sit in regularly.
2. **Standing responsibilities.** Ask openly what is always theirs — the
   things that will still be theirs next year.
3. **Projects.** Ask openly what they are working on right now that has an
   end. Then offer the `mail-subject`, `chat` and remaining
   `recurring-meeting` entries as tick-box suggestions ("anything here you'd
   add?"). For every project they name or tick, ask for one line on what it
   is, in their words, and record it.
4. Ask openly: the three to five outcomes they are judged on, who reports to
   them, and what lands on their desk that is not really theirs.

Write the `role-and-responsibilities` block through the loop. Then create
**three or four** projects at most — a short list they recognise beats a
long one they have to maintain, and `/new-project` adds one any time:

```bash
python3 "$VAULTLIB" project scaffold --vault "$VAULT" --name "Yard Automation Program" \
  --type initiative --entity meridian-freight-holdings --owner alex-rivera
```

`--type` is `area-of-responsibility` for "always theirs" and `initiative` for
"something that ends" — ask it as a choice. `--entity` joins to an
organisation created above; an internal responsibility links to their own
company or department.

## Step 6 — your people

Propose from the `person` entries as tick boxes, top first, with each
person's `detail` as the evidence. Attendance is not relationship: drop
everyone they do not tick, and do not argue for a name. "Other" adds anyone
missing. For each ticked person:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Priya Nathan"
```

## Step 7 — how you write

Propose from the `sent-mail` entries: length, how they open and close,
bullets or prose, formality. Each observation is a claim citing the mails it
comes from, with their own phrases in double quotes. Ask openly how direct
pushback should be, and which language for which audience. Expect corrections
— how they write to their board is not how they write to their team — and use
their words. Write the `communication-style` block.

## Step 8 — your systems and boundaries

Ask openly which business systems matter for their work, whether they use
shared mailboxes, and where their files live; with what step 1 established
(Microsoft 365, Plaud), write the `tools-and-systems` block.

Ask openly what must never leave the vault without them reading it first.
Offer the evening-run time as a choice built from the end of the working day
they gave in step 2 ("your day usually ends at 18:00 — have the note ready by
19:00?"). With the company-rules answer from step 2, write the
`preferences-and-constraints` block.

## Step 9 — the first evening note

Say it before you start: *"I'll now write tomorrow's note — you'll hear
from me when it's done."* Then **invoke the `/evening-sync` skill, in this
session** — follow `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/SKILL.md` in
interactive mode. It reads the config just filled and writes **tomorrow's**
note, naming the organisations, projects and people seeded minutes earlier.
Do not assemble a note by hand and do not reimplement any of its stages.

Say "done", open `60-daily-notes/{tomorrow}.md` on screen and walk them
through it, naming each part ("this is your recap of today", "this is the
prep for tomorrow's steerco"). Without a calendar the note carries the
no-meetings line; walk through it anyway.

## Step 10 — the standing evening run

**Invoke `/schedule-daily-loop` now, in this session** — follow
`${CLAUDE_PLUGIN_ROOT}/skills/schedule-daily-loop/SKILL.md`. Do not compose a
schedule by hand. They already chose the time in step 8: when
`/schedule-daily-loop` asks for it, confirm that time with them rather than
asking afresh. Its first manual run is what grants the routine access to
their accounts; keep them in the room for it, and say before it starts that
it runs once now.

It ends **scheduled** — say the first automatic run as a day and a time, and
what it depends on (the machine awake, Claude open) — or **handed off** — say
plainly that the routine does not exist yet and that `/evening-sync` run on
demand writes the same note meanwhile. Never end implying a routine nobody
created.

## Step 11 — close

Sweep first. Nothing read in this session outlives it except what they
approved into the vault:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

Then close from their side of the table, in this order:

1. **What is true now** — *"You're set up. The vault knows who you are, how
   you write, and what you're working on."*
2. **What to look at** — tomorrow's note first, then one project page and
   one organisation page.
3. **What happens next, and when** — the first automatic evening run, or the
   hand-off from step 10.
4. **When something is missing** — `/new-project` and `/update-entity`, one
   line each: "you'll notice something missing in week two; here's what you
   do then".
5. **Anything still owed** — an account not switched on and who does it, a
   routine not yet scheduled, a topic skipped.

## Without Microsoft 365

When Microsoft 365 is not connected, the company rules forbid reading, they
declined the consent question, or a topic's proposals all failed the check,
that topic becomes a short interview: read
`99-workflow-config/context/<stem>.md` with the Read tool and ask its
`## Interview questions` one at a time, conversationally, building each
follow-up from what they already said. Record their answers with
`discover answer`, draft the block from them, check it, read it back, write
it. Organisations, projects and people then come from what they named.

## Degradation

| Missing | Read | Topics | Evening note | Evening run |
|---|---|---|---|---|
| **Microsoft 365** | skipped | interview questions only | written, with the no-meetings line | unaffected |
| **Plaud** | unaffected | unaffected | unaffected — `/sync-recordings` still reads `10-inbox/` | unaffected |
| **Consent declined, or company rules forbid reading** | skipped | interview questions only | unaffected | unaffected |
| **A source errors, is empty or mismatches** | recorded | that source's topics fall back to questions | unaffected | unaffected |
| **The clock stopped a source** | recorded as `capped` | proposals say "your most recent…" | unaffected | unaffected |
| **Scheduler** | unaffected | unaffected | unaffected | handed off in writing, never implied |

With no accounts at all the vault is still complete and usable. Say which
accounts still need connecting, and that running `/setup-my-brain` again
later picks the connection step up where this session left it.

## Hard rules

1. **Fill, never scaffold — and never provision.** A folder that is not a
   provisioned vault ends the session at step 0. Never run
   `/provision-vault`, never create `99-workflow-config/`, never write a file
   into an unprovisioned folder.
2. **Pending migrations stop the session.**
3. **Nobody types an email address, and nothing is read before the account
   is proven.** Every hint is copied verbatim from a whoami payload, and
   `config verify-account` must return `match: true` before the read.
4. **Nothing is read without their explicit yes to the consent question**,
   and the company-rules question comes first: a rule against reading means
   no read.
5. **The read stops at its time budget** — the clock decides, not you.
6. **Raw reads are deleted the moment they are built into evidence**
   (`discover build --consume`); everything else in scratch is swept at the
   close.
7. **Organisations may be proposed from calendar and mail; only the owner
   confirms.**
8. **Nothing is shown to the owner that `discover check` did not pass.**
9. **Chat message text is never read, and neither is the Inbox.** Chats are
   read as a list: who is in them and what they are called.
10. **Every block is read back and approved before it is written.**
11. **Every write goes through the CLI.**
12. **Prefer fewer, confirmed objects to more, inferred ones.**
13. **The evening run is scheduled or explicitly handed off.**
