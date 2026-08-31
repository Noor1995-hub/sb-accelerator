---
name: setup-my-brain
description: The Session-1 onboarding interview — fills the context portfolio, connects the accounts the vault syncs from, seeds entities/projects/people, and ends with the vault owner's first daily note and a scheduled evening run. Triggers when the user invokes /setup-my-brain.
user_invocable: true
origin: net-new
---

# Set Up My Brain

Session 1 of the onboarding journey, run **live**: the delaware consultant and
the vault owner together, roughly two hours, vault open on screen. By the end
the vault knows who its owner is, which connector accounts belong to this
engagement, what they work on and with whom — it has written them tomorrow's
daily note while they watch, and that note has a standing time it arrives.

**Precondition: a provisioned vault.** This skill *fills*; it never scaffolds.
The vault template does not ship inside the plugin, so there is nothing here
to instantiate from — pointed at an ordinary folder, phase 0 stops and points
at the provisioning runbook. That is the correct outcome, not a gap to work
around by creating folders by hand.

## Tone — this is an interview, not a form

The vault owner is watching every prompt. Four things carry the session:

- **Conversational, one topic at a time.** Ask a question, listen, follow the
  thread it opens. Never paste a whole question list and wait.
- **Introduce every term the first time you use it, in one breath.** "Your
  brief — the note the vault writes you each evening." "A connector — the
  link that lets me read your recordings." "An entity — an organization the
  vault keeps a page on." Nobody in this session should have to decide
  between asking what a word means and pretending they know. This applies to
  vocabulary from this skill, from the vault, and from Claude itself; if a
  word would make a competent person feel behind, it gets its half-sentence.
- **Their words over your summary.** When they describe how they want pushback
  handled, the block should read like them, not like a consultant's write-up.
  Compress and organize; do not re-voice.
- **Read back before writing.** Every block is shown and approved before it
  lands in the vault. "Here's what I've got — does that sound like you?"

Where the answer is one of a known set — which connectors to use, what type an
organization is, what time the evening run should fire — use
**AskUserQuestion** rather than open prose. It is faster for them, it removes
the "what am I supposed to say here" pause, and it is the difference between
an interview and an exam. Keep it for genuine choices: a question with one
obvious answer is a statement, and an open question about their own work
should stay open.

Silence and thinking time are fine. Filling them with a polished paragraph the
owner did not say is not.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say so
plainly rather than conducting an interview whose answers go nowhere.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

`$SCRATCH` below is the session scratch directory — draft blocks and raw
connector payloads land there, never in the vault. The JSON envelope and
interpreter resolution are documented in the plugin's `CLAUDE.md`. Read `ok`
on every call; on failure surface `error` and `hint`.

Scratch cleanup is one mechanism, the same one the sync routines use:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

It deletes a fixed, built-in pattern list directly inside `--dir`, never
recursing, and it is the only deletion this skill performs. Every scratch
name this skill tells you to write matches one of its patterns —
`plaud.whoami.json`, `m365.whoami.json`, `sentmail.sample.json`,
`calendar.*.json`, `*.block.md` — so use those exact names, and give any
other raw file you write a name matching a pattern too (`m365_*.json`,
`*.payload.json`). Two consequences: one sweep call always catches
everything the session wrote, and a sweep takes *everything* matching, not
one file — so a draft still on its way into the vault must never be sitting
in `$SCRATCH` when one runs.

## Usage

```
/setup-my-brain
```

No arguments, and **no unattended mode**. Every phase has a human in it by
construction: there is nothing here to schedule.

## Phase 0 — preflight

Two read-only checks, both before a single question is asked.

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

- **`ok: false`** — there is no `99-workflow-config/config.json`, which means
  this folder is not a provisioned vault (or the vault root is wrong). Stop.
  Surface `error` and `hint`, say plainly that this skill fills a provisioned
  vault and does not create one, and point the consultant at
  `playbooks/provisioning-runbook.md`. Do not offer to write the missing
  files.
- **`ok: true`** — carry `config` and `missing` forward. On a fresh vault
  `missing` is exactly `["owner", "sync.start-date", "timezone"]`; that is
  the honest state, not an error — this skill fills all three, the start
  date right after owner and timezone below. An account hint only joins the
  list once its adapter is enabled, so both connectors being unbound shows
  up as `enabled: false` in `config`, never in `missing` — phase 2 reads
  the adapter entries, not this list.

```bash
python3 "$VAULTLIB" migrate status --vault "$VAULT"
```

If `pending` is non-empty, **stop** and hand off to `/upgrade-vault`. Say why
in one line: interviewing into a stale structure writes today's answers into
a shape the plugin is about to migrate, and the vault owner's first impression
should not be a repair job. Come back to `/setup-my-brain` once the upgrade
is done — nothing is lost, nothing has been asked yet.

### Fresh run or re-run

A config whose `timezone` and `owner` are null is a **fresh run**: work
straight through the phases below.

Anything already filled means **re-run mode** — a tune-up, a second session,
or a restart after an interrupted one. In re-run mode every phase below
starts by *showing what is already there* and asking whether to revise it:
the current block from `context read`, the current config values, the
entities/projects/people already seeded. Revising is cheap and repeating is
harmless — a marker-fenced `context write` replaces its block, `config write`
sets a field, and `person ensure` / `entity ensure` return `created: false` on
an object that already exists. `entity ensure` on an existing dossier also
applies whichever of `--name`/`--type`/`--status`/`--owner` you pass this
time — it does not just re-affirm creation — and its envelope reports
`changed` plus `updated: [...]` so you can tell a real edit from a no-op.
`person ensure` never rewrites an existing note (curation added through
People.base must survive), but if the `--name` you pass differs from the
note's own, the envelope reports it under `ignored` rather than dropping it
silently.

`project scaffold` is the exception: it **refuses** a slug that already has a
folder rather than touching a project that has been accumulating decisions and
meeting links since the last session. That refusal is a no-op outcome, not a
failure — acknowledge it in one line ("that one's already there"), do not
retry it under a different name, and move on. Skipping a phase the vault owner
is happy with is the normal case; say what you skipped in the closing summary.

## Phase 1 — the interview

### Open by saying what this is for

Before the first question, one plain sentence about where the answers go —
because "we'll fill in your context files" means nothing to someone who has
never seen one:

> *Everything you tell me in the next hour becomes the way this vault writes
> for you. Who you are and what you own is how it decides what matters in your
> calendar and what to leave out; how you like to be written to is how your
> notes and drafts will sound. This is the part that stops it sounding like a
> consultant and starts it sounding like you.*

Then say how long it takes and that it is a conversation, not a form.

### Start with the company

Ask what company they work for and what it does, **before** anything else —
it is the easiest question in the session, and every later one lands better
once you know the answer. A CCO at a 1,400-person logistics group and a CFO at
a listed bank need different follow-ups about forums, regulators and rhythm.

Then offer, once, in one line: *"Want me to take two minutes to read up on
them publicly, so I don't ask you things I could have looked up?"* On yes, do
a light public read and **use it to shape questions, not to fill blocks** —
anything that ends up in the vault is still something they said and approved.
On no, or with no research tool available, carry on; this is a nicety, and
the interview does not depend on it.

### The five files

Five files, **in this fixed order** — each one gives the next its vocabulary:

| # | Stem | What it holds |
|---|---|---|
| 1 | `identity` | Who they are, in their own words |
| 2 | `role-and-responsibilities` | What they own and are judged on |
| 3 | `communication-style` | How drafts in their name should read |
| 4 | `preferences-and-constraints` | Privacy, the EA's remit, confidentiality |
| 5 | `tools-and-systems` | Calendar, recorder, where the files live |

**The questions live in the vault, not in this skill.** Each file carries its
own `## Interview questions` section, so an archetype can tune them per
deployment without a plugin release. For each file, in order:

1. **Read `99-workflow-config/context/<stem>.md`** with the Read tool and take
   its `## Interview questions` bullets as your script. Ask them one at a
   time, conversationally, following what the vault owner opens up. Skip a question
   they have already answered under an earlier file rather than asking twice.
2. In re-run mode, show what is there first:

   ```bash
   python3 "$VAULTLIB" context read --vault "$VAULT" --file <stem>
   ```

3. **Draft the content block** — markdown prose and bullets, short and
   factual, no marker comments (the CLI owns those and refuses content that
   carries them). Write the draft to `$SCRATCH/<stem>.block.md`.
4. **Read it back for approval.** Show the block, ask, amend until they say
   yes. Do not write an unapproved block "to save time" — this file is what
   every later skill speaks in their name from.
5. Write it:

   ```bash
   python3 "$VAULTLIB" context write --vault "$VAULT" --file <stem> --content "$SCRATCH/<stem>.block.md"
   ```

`replaced: true` in the result means an earlier block was overwritten —
expected on a re-run, worth a raised eyebrow on a fresh one.

**Use what they already told you.** File 2's questions land better when the
follow-ups are built from file 1's answers — the company, the size, the role.
Asking "what areas do you own?" cold, to someone who has just spent five
minutes describing their remit, teaches them that nothing they say is being
listened to.

### Immediately after the first file: the vault owner's own record

The first file establishes their full name and their working day. Turn both
into machine facts before moving on to the second file:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Alex Rivera"
```

Take `slug` from the result — never slugify the name yourself — and record it
as the join key every later skill uses for "the vault owner":

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field owner --value alex-rivera
```

Then the timezone. **Propose, then confirm** — from what they just said about
where they sit and when they work, offer the IANA name ("You're in Brussels,
so `Europe/Brussels`?") rather than asking the vault owner to produce a
timezone identifier:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field timezone --value "Europe/Brussels"
```

Both values are what phases 4 and 4b need to run at all. If either write
fails, resolve it now rather than discovering it at the close of the session.

Then, if `config read` reported `sync.start-date` in `missing`, stamp the
vault's horizon with today's date — no question to ask, this is the
provisioning date by definition:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field sync.start-date --value <today, YYYY-MM-DD>
```

From here on, no sync ever considers a meeting dated before it — recurring
calendar series otherwise expose occurrences from long before the vault
existed. If the vault owner asks for older meetings, that is a deliberate,
interactive backfill run later, never a reason to backdate this value.

### File 2 — areas of responsibility are not projects

The role file is the longest one in a live session, and most of the drag comes
from one blur: people answer "what do you own?" with a mix of standing
responsibilities and things currently in flight. Both are useful; they are not
the same object, and phase 3b needs to tell them apart.

Say the distinction once, in their language, the first time it comes up:

> *A responsibility is something that is always yours — pricing, the yard
> network, the commercial team. A project is something that ends — this year's
> tender, the new depot. I want both, but I'll keep them apart.*

Then keep them apart as they talk, and carry both lists forward. Phase 3b
opens with these named back, not with a blank question — the vault owner should
never have to describe their own portfolio twice.

### File 3 — ask the questions, and take a note of one answer

Nobody can describe how they write. They can describe how they *want* to
sound, which is a different and less useful thing, and it is why this file
takes three minutes and produces the thinnest block in the set.

The file's first question offers a way out of that: reading a sample of their
own sent mail and drafting the block from how they actually write. **Ask it,
and record the answer — but do not read anything yet.** Their mail account has
not been connected at this point in the session, and nothing in this plugin
reads a mailbox before it knows whose mailbox it is. Say that, in one line:
*"If you'd like that, I'll come back to it in a few minutes, once your
Microsoft account is connected."*

Then ask the rest of the file's questions and write the block as usual. It is
a complete, valid block on its own; the sent-mail pass in phase 2 revises it
if they said yes and the connection goes through.

## Phase 2 — connecting the accounts

Two questions, in this order, and the first one is theirs:

> *Do you want me to pull your recordings and meetings in automatically —
> from Plaud, from Microsoft Teams, or both?*

Use **AskUserQuestion**: Plaud, Microsoft 365, both, neither. Explain each in
one breath as you go — Plaud is the pocket recorder, Microsoft 365 is the
calendar and Teams meetings — and say what "neither" means rather than
treating it as a mistake (the degradation table at the bottom of this file is
the script for that).

*Then*, for each one they chose, check whether that connector is actually
live in this session. If it is, confirm the account with them and connect it.
If it is not, explain what has to be switched on and by whom, and move on
without treating it as a failure. Same outcome as before; the vault owner is
asked what they want before being shown machinery.

**Connecting is per-vault, and that is the point.** A connector signs in at
the *user* level; tying the signed-in account to *this* vault is why a laptop
holding two engagements never syncs one into the other. Worth one sentence to
the consultant; worth none to the vault owner unless they ask.

**The rule, and it has no exceptions: never ask anyone to type an email
address.** Apple and Google sign-ins often give a connector a synthetic
address, so the address the vault owner knows may never appear in the payload at
all — and a display name is rejected by the CLI outright. The hint is copied
**verbatim from the whoami payload**, character for character, or the
connection does not happen.

### Plaud

With the vault owner signed in, call `mcp__plaud__get_current_user`. Write the raw
JSON to `$SCRATCH/plaud.whoami.json` with the Write tool — never echo a large
payload through Bash.

Show them the **human-recognizable nickname** from the payload (the account
name, the device name) and ask one question: *"Is this your account?"* Wait
for an explicit yes. A shrug is not a yes; an unrecognized account means the
wrong one is signed in, and the fix is to sign in again, not to connect it
anyway.

On yes, take the `id` or `email` field **verbatim from the payload**:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.account_hint --value "<verbatim from the payload>"
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.enabled --value true
```

Then prove it, in that order — hint first, enable second, verify third:

```bash
python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter plaud --identity "$SCRATCH/plaud.whoami.json"
```

`match: true` is the only acceptable result. Anything else means the value you
wrote is not in the payload — re-copy it, do not retype it from memory, and
never "fix" it by loosening the hint.

**If the mismatch cannot be resolved in this session, put the adapter back the
way you found it before moving on** — an adapter left `enabled: true` behind a
hint that matches nothing is refused by every later sync and evening run, and
the vault owner loses their calendar prep without ever being told why:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.enabled --value false
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.plaud.account_hint --null
```

That is the declined path from the subsection below, reached late — say so out
loud, and say what the vault does without this connector. Then **sweep the
payload immediately**:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

Immediately means before the next question, not at the end of the session.

### Microsoft 365

Identical steps, three substitutions: the whoami tool is `get_me`, the hint
comes from `mail` or `userPrincipalName`, and the adapter is `m365`.

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.account_hint --value "<verbatim from the payload>"
python3 "$VAULTLIB" config write --vault "$VAULT" --field adapters.m365.enabled --value true
python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter m365 --identity "$SCRATCH/m365.whoami.json"
```

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

Read `match` before you sweep — the payload is the only place the correct
hint exists, and on a mismatch you re-copy from it rather than retyping.
Sweep once the connection is settled, whichever way it went. An unresolved
mismatch unwinds the same way as Plaud's, with `adapters.m365`: `enabled` back
to `false`, `account_hint` back to `--null`. This connection is what phases
3b, 3c and 4 read the calendar through, so say out loud that it just became
live.

#### The sent-mail read, if they asked for it in file 3

**Only here, and only on all four of these**: they said yes in file 3,
`adapters.m365.enabled` is true, `outlook_email_search` exists, and
`verify-account` returned `match: true` on the line above. That last one is
the whole point of doing this after the connection instead of during the
interview — until it passes, the signed-in mailbox may belong to the
consultant or to a previous engagement, and a writing style abstracted from a
stranger's prose is not something a read-back can catch. `plugin/CLAUDE.md`
states the rule this obeys: only `match: true` may proceed to listing content,
and a mailbox search is listing content.

1. Search their **own sent mail**, a recent sample, and write the raw result
   to `$SCRATCH/sentmail.sample.json` with the Write tool — never echo a large
   payload through Bash.
2. Draft a revised `communication-style` block from it: length, register, how
   they open and close, bullets versus prose, the words they actually use.
   Keep this draft in the conversation — do not write it to `$SCRATCH` yet.
   The sweep on the next step takes `*.block.md` too, and an in-flight draft
   must not be sitting there when it runs.
3. **Sweep the sample immediately** — before the read-back, not at the end of
   the session:

   ```bash
   python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
   ```

4. Read the draft back like any other block, alongside what they told you in
   file 3. Only once they approve, write it to
   `$SCRATCH/communication-style.block.md` and land it with
   `context write --file communication-style`. Expect corrections: a draft
   built from mail to their board is not how they write to their team, and
   that correction is itself the most valuable line in the file.

If any of the four conditions fails — they declined, the connection did not
happen, the tool is absent, the search returns nothing usable — the block
written in file 3 stands and is perfectly good. Say which it was, in one line,
and move on. A declined offer needs no commentary.

**The mail is engagement data.** It never lands in the vault, it never appears
in a summary, and the only thing that survives the read is the block they
approved.

### When a connector is unavailable or declined

Missing tool, failed sign-in, or a vault owner who would rather not connect it
today: **skip it with an explicit line**, leave `enabled` false, and say what
still works without it. Never enable an adapter you could not verify, and
never present a skipped connector as merely "not set up yet" without saying
what the vault loses until it is.

## Phase 3 — seeding

Three steps, in this order. The order is the point: entities give projects
something to hang on, and both give the people list its meaning.

### Say two things before you start

First, the shape of the next stretch, so nobody sits watching a cursor
wondering whether it is their turn:

> *I'm going to set things up now — about ten to twenty minutes. I'll ask you
> to confirm a few lists as I go, but there's nothing to prepare. Just keep
> the session open.*

Second, the reassurance, **once, up front, covering everything that follows** —
not buried in the projects step where it currently lives:

> *Whatever we don't put in today can be added in under a minute later, any
> time. So let's seed one or two of each and stop there — a short list you
> recognize beats a long one you have to maintain.*

That sentence is what makes a small list feel deliberate rather than
incomplete, and it applies to organizations, projects and people alike.

### 3a — Entities, from conversation only

Start by explaining what an entity *is*, in one breath: **a group of people,
organized together, that they deal with** — and the vault keeps one page per
group, so everything said about it collects in one place. Give the range
concretely, because most people hear "entity" and think only of customers:

- a client, or a prospect
- a partner or a supplier
- a regulator, an auditor, an industry body
- **their own company** — the one most people forget
- **a department or business unit inside their own company** — Finance, the
  factory in Ghent, the shared-services centre. If they deal with it as a
  counterpart, it is one of these.

The last two go in as `business-unit`, and their own organization has to exist
because 3b needs something to hang an internal responsibility on.

Then ask them to name theirs. Follow up on what they say ("you mentioned the
regulator earlier — is that one you'd want a page on?"), but keep the list to
groups that matter to their work, not every logo they have met.

**Entities are never derived from the calendar.** A recurring invite is not
evidence that an organization matters to this vault owner; only they can say
that, and a calendar-scraped list of vendors is exactly the kind of noise that
makes an owner stop trusting the vault in week two.

For each confirmed entity:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" --slug meridian-freight-holdings \
  --name "Meridian Freight Holdings" --type client --status active --owner alex-rivera
```

`--type` is one of `client`, `business-unit`, `partner`, `supplier`, `other` —
an AskUserQuestion where it is not obvious from what they said. `--status
active` for the ones they work with today; `--owner` is the vault owner's slug
from phase 1.

### 3b — Projects, suggested prudently

Open with **their own words from file 2**: the responsibilities and the
in-flight things they already described, read back as two short lists. Add,
when m365 is connected, the recurring subjects on their calendar over the next
and last two weeks (`outlook_calendar_search`, with the query window computed
deterministically by `dates window` rather than by hand). Then let the vault
owner cut.

The distinction from file 2 is what decides `--type`:

- a standing responsibility — "pricing", "the yard network" — is an
  `area-of-responsibility`
- something with an end — "this year's tender" — is an `initiative`
- a task — "finish the November board pack" — is neither, and does not become
  an object at all

Keeping those apart is what stops a vault filling with dead one-week folders.

**Aim for three or four.** More is worse: an owner who watches ten thin project
folders appear learns that the vault is a filing cabinet they now have to
maintain. The reassurance was already given up front; if they hesitate, repeat
the specific half — `/new-project` adds one in under a minute.

For each confirmed project:

```bash
python3 "$VAULTLIB" project scaffold --vault "$VAULT" --name "Yard Automation Program" \
  --type initiative --entity meridian-freight-holdings --owner alex-rivera
```

`--entity` is required and joins to 3a: an internal area of responsibility
links to the vault owner's **own organization** entity — or to the business
unit it sits in — which is exactly why those had to be created in 3a. Optional
`--stage`, `--contacts` and `--source` each take one line and are worth
passing when the vault owner has just said something that fits.

### 3c — People, one list from both sources

When m365 is connected, pull attendees from the ±2-week calendar window and
merge them with the names the vault owner mentioned during the interview into
**one confirm/reject list**. One list, not two passes — the vault owner should
not be asked about the same person twice with different framing, and the merged list is
also how you catch that the person they described as "my chief of staff" is
the same name that appears in every Monday invite.

Walk it with them. Drop everyone they do not confirm, and do not argue for a
name because the calendar is confident about it: attendance is not
relationship. For each confirmed person:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "Priya Nathan"
```

Reading the calendar out loud tends to produce observations the interview did
not — a standing forum nobody mentioned, a rhythm ("you're in back-to-back
externals every Thursday"). **If the vault owner agrees the observation is real**,
fold it into the relevant block and re-run `context write` for that file;
those two are usually `role-and-responsibilities` and
`preferences-and-constraints`. If they do not agree, drop it. A pattern in a
calendar is a hypothesis, and this is the one moment in the deployment where
the person who can confirm it is sitting right there.

## Phase 4 — the first daily note

The close, and the moment the vault stops being a folder structure.

**Invoke the `/evening-sync` skill now, in this session** — follow
`${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/SKILL.md` in interactive mode. It
reads the config you just filled (timezone, owner slug, the m365
connection) and writes **tomorrow's** daily note: a prep section per real
calendar meeting, naming the entities, projects and people seeded twenty
minutes earlier. It is a pipeline run, not a CLI call — do not assemble a note
by hand, and do not reimplement any of its stages here.

Then **open `60-daily-notes/{tomorrow}.md` on screen** and walk through it
with them, section by section — naming what they are looking at as you go
("this is your recap of today", "this is the prep for tomorrow's steerco").

If the calendar was never connected, the note still gets written and carries
the no-meetings line. Walk through it anyway; the recap and the structure are
what you are showing them.

## Phase 4b — the standing evening run

The note they are looking at was written because someone ran a skill. Nothing
yet makes it happen again. **Do not say it arrives every evening until it
does.**

**Invoke `/schedule-daily-loop` now, in this session** — follow
`${CLAUDE_PLUGIN_ROOT}/skills/schedule-daily-loop/SKILL.md`. It asks what time
they want their evenings prepared, creates the scheduled task, starts it once
by hand, and states the condition the routine depends on. Do not compose a
schedule by hand here and do not reimplement its steps.

Budget a few minutes for it, and keep the vault owner in the room: that first manual
run is what grants the routine permission to reach their connectors, and it is
the only chance they get to watch it work before they are asked to trust it.

It ends one of two ways, and either is a fine end to Session 1:

- **Scheduled** — say when the first automatic run is, as a day and a time,
  and what it depends on (the machine awake, Claude open). *That* is the
  sentence that used to be an overclaim and is now true.
- **Handed off** — the scheduler was not available. Say plainly that the
  routine does not exist yet, who is setting it up and by when, and that
  `/evening-sync` run on demand writes the same note meanwhile.

What must not happen is a session that ends implying a routine nobody created.

## Phase 5 — close

### Sweep first

**Raw connector JSON is engagement data.** It must not outlive the session.
Nothing persists from this run except what the vault owner confirmed into the
vault; everything else was working material.

Delete every scratch file this session wrote — whoami payloads and any mail
sample (already swept at the point of use, but check), calendar results, and
the draft blocks:

```bash
python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
```

One call is the whole cleanup, because every scratch name this skill writes
matches the sweep's built-in pattern list — that contract is stated up top,
under Requirements. If a raw connector file somehow got a name outside the
list, that is the naming bug to notice here; rename it to match a pattern
and sweep again.

### Then close from their side of the table

The last thing they hear should be about their vault, not about your run. Not
*"5 context files written, 2 adapters bound, 6/4/20 objects created"* — that
is a deployment log with a person sitting in front of it.

Close with, in this order:

1. **What is true now** — *"You're set up. The vault knows who you are, how
   you like to be written to, and what you're working on."*
2. **What to go and look at**, by name and in the app — tomorrow's note first,
   then one project page and one organization page, so they see the shape.
3. **What happens next, and when** — the first automatic evening run as a day
   and a time, or the hand-off from phase 4b.
4. **What to do when something is missing** — `/new-project` and
   `/update-entity` in one line each, framed as "you'll notice something's
   missing in week two; here's what you do then".
5. **Anything still owed**, named: connectors not switched on and who does it,
   a routine not yet scheduled, a phase skipped on a re-run.

Then, and only then, **one line of counts for the consultant's own record** —
files filled, connectors live, entities/projects/people seeded. One line, at
the end, clearly the operator's footnote rather than the vault owner's summary.

## Degradation

Every phase degrades to something honest. The interview alone still produces a
valid vault.

| Missing | File 3 | 3b projects | 3c people | Phase 4 | Phase 4b |
|---|---|---|---|---|---|
| **m365** | offer recorded, never acted on — the file-3 block stands | interview mentions only | interview-mentioned names only | note is written; it carries the no-meetings line | unaffected |
| **Plaud** | unaffected | unaffected | unaffected | unaffected — `/sync-recordings` still runs its inbox adapter over `10-inbox/` | unaffected |
| **both** | offer recorded, never acted on — the file-3 block stands | interview mentions only | interview-mentioned names only | note is written from the interview and the seeding alone | unaffected |
| **scheduler** | unaffected | unaffected | unaffected | unaffected | routine is handed off in writing, never implied |

With no connectors at all the vault is complete and usable: the portfolio is
filled, entities, projects and people exist, and files dropped into
`10-inbox/` sync as meetings. Say which connectors the EA is expected to set
up afterwards, and that re-running `/setup-my-brain` later picks the
connection step back up exactly where this session left it.

## Hard rules

1. **Fill, never scaffold.** A folder that is not a provisioned vault ends the
   run at phase 0 with a pointer to the runbook — never with a folder this
   skill created.
2. **Pending migrations stop the session.** Interviewing into a stale
   structure is not a smaller problem than rescheduling the session.
3. **Nobody types an email address, and nothing is read before the account is
   proven.** Every account hint is copied verbatim from a whoami payload, and
   `config verify-account` must return `match: true` before any content is
   listed through that adapter — calendar, recordings or mail alike.
4. **A whoami payload — or a mail sample — is deleted the moment it has been
   used**, not at the end of the session.
5. **Entities come from the vault owner, never from the calendar.**
6. **Every block is read back and approved before it is written**, including
   one drafted from their own sent mail.
7. **Every write goes through the CLI.** Context blocks, config fields,
   people, entities and projects each have their subcommand; nothing here
   edits a vault file directly.
8. **Prefer fewer, confirmed objects to more, inferred ones.** Three projects
   the vault owner named beat ten the calendar suggested, and `/new-project`,
   `/update-entity` and the next session all exist.
9. **The evening run is scheduled or explicitly handed off.** The session
   never ends describing a routine that does not exist.
