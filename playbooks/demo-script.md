# Demo script

A 12-minute live demo of the vault for a client executive team, run before
an engagement exists. delaware-side material; never ships.

This is the awareness artifact — it sits before `pre-flight-checklist.md` in
the sequence. Its job is to make one claim credible: *this is how it actually
works*, not *look what AI can do*. Everything below runs against the demo
vault. Nothing is mocked, and the two places where the product visibly cannot
do something are shown rather than skipped.

## The shape

Five beats. One thread — a contract renewal that arrives by email and has no
home — runs through all of them, so the room watches one thing move rather
than five unrelated tricks.

| # | Beat | Runs | Minutes |
|---|---|---|---|
| — | The vault | nothing — you browse | 1½ |
| 1 | Start | `/new-project` | 1½ |
| 2·3 | Capture & sync | `/sync-recordings` | 2½ |
| 4 | Prepare | `/evening-sync` | 3½ |
| 5 | Ask | nothing — you type questions | 2½ |
| — | What it takes | nothing — you say it out loud | 1 |

Twelve and a half minutes with no interruptions. In practice, budget fifteen.

## Before the room

Work through all of this the day before, not on the morning. Steps 3 and 4
are the ones that bite.

1. **Instantiate a fresh demo vault.** `python3 scripts/make_test_vault.py
   <target>` — template plus the demo fixtures. Never demo from a vault a
   previous demo already wrote into; `/evening-sync` is idempotent and will
   skip the recap it already wrote, which reads on stage as "nothing
   happened".
2. **Confirm the config is onboarded.** `config read` must return `"missing":
   []`. The demo fixture carries `executive` and `timezone`; if either comes
   back null you are on an older fixture and `/evening-sync` will halt at
   Stage 1.
3. **Re-date the inbox to the last two business days.** The fixture's five
   inbox files are dated across a fixed week. The recap window only reaches
   back five business days before it trips the catch-up banner, so items
   older than that fall outside the window and the recap comes back empty.
   Change both the filename date and the `Recorded:` / `Date:` line inside
   each file.
4. **Add a daily note dated the previous business day.** Frontmatter only is
   enough — `date`, `type: daily-note`, a heading. Without it the last daily
   note in the fixture is months old and tomorrow's note opens with a
   warning callout counting the business days you missed. Verify with `dates
   plan`: you want `over_threshold: false` and a `recap_from` on or before
   your oldest re-dated inbox item.
5. **Delete the project you are about to create.** If you have rehearsed,
   `30-projects/contract-renewal/` already exists and beat 1 will collide.
6. **Rehearse beat 4 once end to end** and time it. It is a seven-stage
   pipeline and it is the slowest thing in the demo.

Steps 3 and 4 are mechanical and should not be manual — see the open issue on
re-dating the demo vault at instantiation.

## The beats

### The vault — 1½ min

Open the vault in Obsidian. Show three things and stop:

- the folder tree — meetings, projects, entities, people, daily notes
- one project index, and specifically its **Now** callout: stage, defining
  decision, next event, what you owe, what to watch
- one person note

Say: this is a folder of text files on a laptop. There is no new system to log
into, and if the engagement ended tomorrow the notes would still open.

Do not tour the plugin, the skills, or the architecture. They did not ask.

### 1 — Start — 1½ min

Open `10-inbox/` and read the forwarded renewal email out loud, or paraphrase
it: Meridian's board wants a three-year term instead of two, in exchange for a
volume commitment somewhere in the low single-digit millions, and they want a
term sheet before their board meets in October — a quarterly board, so missing
the window costs a quarter.

Then show `30-projects/`. There is no renewal project. That is the honest
state of most inboxes.

Run `/new-project` — Contract Renewal, an initiative, on Meridian Freight
Holdings. It creates the folder, an index, an empty decisions log, and links
the project into Meridian's dossier.

Open the new index. Every slot in the **Now** callout reads `_none yet_`.
Leave it on screen for a beat. That emptiness is the setup for beat 4.

Say: one minute, once. Everything that follows attaches to it without you
filing anything.

### 2·3 — Capture & sync — 2½ min

Back to `10-inbox/`. Five things that arrived without anyone filing them: a
dictated voice memo from a site visit, the forwarded renewal email, two Teams
transcripts, an industry report.

Run `/sync-recordings`.

Open two of the results — the renewal email note and the voice memo note. Show
the frontmatter: entity, projects, attendees. The renewal note is filed against
the project that did not exist four minutes ago.

The voice memo is worth opening for a different reason: it is genuinely messy
dictation, opens with a complaint about the parking, and the note still comes
out structured. Say that out loud — it is the difference between a demo and a
product.

Say: you filed nothing.

### 4 — Prepare — 3½ min

One command: `/evening-sync`.

It is a seven-stage pipeline and it will take a moment. Talk while it runs —
this is the right place to explain that it reads the window since your last
run, not "everything", so it is the same command whether you ran it yesterday
or on Friday.

Then show two things, in this order:

1. **The renewal project's Now callout.** The slots that read `_none yet_` in
   beat 1 are filled — stage, what is owed, what to watch — from a meeting note
   that was an email in your inbox six minutes ago. This is the payoff. Give
   it room.
2. **Tomorrow's daily note.** A recap at the top: at a glance, themes across
   the week's meetings, project pulse, anything logged, anything to watch.

**Then show the part that does not work.** The Meetings section will read
`*Calendar unavailable — meetings could not be prepped.*` Do not skip past it.
Say: this vault has no calendar connected, so it cannot prep tomorrow's
meetings. With a calendar connected, every meeting gets a block underneath it
— who is attending, when you last met them, what was decided since.

If you want to show what that looks like, have a note from a connected vault
open in a second tab and say plainly that it came from a different vault.
Never imply the run you just did produced it.

This is a better moment than it looks. An executive team that has sat through
three AI demos this quarter will notice that you showed them the hole.

### 5 — Ask — 2½ min

No skill, no command. Type questions into Claude with the vault open.

Three that work against the demo vault:

- what is open with Nordbridge?
- who have I not spoken to in six weeks?
- why did we drop the shared spares pool?

The third one is the point. It reaches a decision that was made in March,
superseded later, and recorded with a date and a reason. Nothing in their
current stack answers it.

Say: the answers cite notes with dates on them. Beats 1 through 4 are what
makes that possible — the structure is the product, not the chat box.

### What it takes — 1 min

Say all four, plainly, and do not soften them:

- two hours with a consultant to set it up, live, together
- someone has to actually record the meetings — the vault knows nothing about
  a conversation nobody captured
- roughly ten minutes a day of triage, usually the assistant's
- it is maintained as a versioned product, so it changes under them, and the
  upgrade is consultant-run

Then stop. Do not close with a summary of the benefits.

## Known constraints

Three things this demo cannot currently do. Say them if asked; do not
volunteer the second and third.

1. **No calendar means no meeting prep.** Stage 5 of `/evening-sync` is gated
   on the M365 connector. Without it the prep section renders the
   calendar-unavailable line and the note is still written. There is no local
   or file-based calendar source yet.
2. **The demo vault's dates are fixed**, so the pre-demo re-dating in steps 3
   and 4 above is mandatory and manual.
3. **The demo vault binds to no connector account.** Never enable an adapter
   against your own Microsoft account to make beat 4 look better — that puts
   your real calendar, and other clients' meetings, on a screen in front of a
   client.

## If it breaks

- **`/evening-sync` halts at Stage 1** — `timezone` or `executive` is null in
  `99-workflow-config/config.json`. Pre-flight step 2.
- **Tomorrow's note opens with a catch-up warning** — the last daily note is
  too old. Pre-flight step 4. You cannot fix this mid-demo; carry on and
  ignore it, it is a warning and not an error.
- **The recap is empty** — the inbox items fell outside the recap window.
  Pre-flight step 3.
- **`/new-project` collides** — a rehearsal left the folder behind.
  Pre-flight step 5.
- **The pipeline errors mid-run** — stages are failure-isolated and the
  summary names the stage that failed. Read it out. A product that says which
  part broke is a better demo than one that pretends nothing did.
