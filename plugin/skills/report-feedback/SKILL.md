---
name: report-feedback
description: Report a broken skill, confusing flow, or improvement idea to delaware as a scrubbed, approval-gated GitHub issue. Triggers when the user invokes /report-feedback or accepts the report-it nudge.
user_invocable: true
origin: net-new
---

# Report Feedback

Turns a moment of friction — a skill that broke, a flow that confused, an
idea for something better — into a clean report delaware can act on,
without ever putting the executive's actual work in transit. The CLI's
scrub lint is the technical backstop; this skill's job is to draft as if
that backstop did not exist.

## Requirements

Sending a report needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there; say
so plainly rather than trying to compose and mail a report by hand.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution (`python3`, then `python`,
then `py -3`) are documented in the plugin's `CLAUDE.md`. Read `ok` on every
call; on failure surface `error` and `hint`.

## Usage

```
/report-feedback
```

There is no unattended form. Every report ends on an explicit yes from the
user, so there is nothing here for a scheduled run to invoke.

## 1. Check the channel

Before asking the user anything, learn whether there is anywhere to send
this:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

Note whether `feedback.repo` came back set or `null`. A `null` repo means
the channel is not configured — remember that and go on gathering the
report anyway; it still gets written down (see step 6), it just does not
try GitHub. Do not go looking for the GitHub token yourself — whether it
exists is `feedback send`'s business, not something this skill reads
directly (see the hard rules below).

## 2. Gather

Ask a few short questions, not a form. The user may be mid-frustration, so
keep it light:

- Which skill or flow was this — the command, or what you were trying to do?
- What did you expect to happen, and what happened instead?
- When did this start — this run, or has it been happening for a while?

One follow-up question is fine if the answer is genuinely unclear; do not
turn this into an interview.

## 3. Draft

Write the report as if the scrub lint did not exist — draft carefully, not
carelessly, and let the lint catch what slips through rather than leaning
on it. That means, from the first draft:

- Describe behavior generically: what the skill was supposed to do, what it
  did instead, in terms of the flow and the outcome — never the specific
  content that flowed through it.
- No note text, no names of people or organizations, no meeting titles, no
  file paths, no email addresses.
- Counts are fine and often the clearest way to say it — "3 of 9 meetings
  came back low-confidence" beats a vague "some meetings."
- Write a short title and a body of a few sentences: what broke or
  confused, what the user expected, roughly when.
- Do **not** add the deployment stamp or the disclosure text yourself —
  `feedback send` appends both to whatever body it is given. A draft that
  already carries them would duplicate that block.

As a self-check before showing anything to the user, you may run the
lint directly on the draft:

```bash
python3 "$VAULTLIB" feedback lint --vault "$VAULT" --body-file "$SCRATCH/feedback-draft.md"
```

`ok: false` names exactly which fragments would block a send (`blocked`,
each with a `kind` and the `fragment` that matched) — fix those before
showing the draft, so the user is approving text that will actually go
through.

## 4. Show the draft and the disclosure — then ask

Show the user the exact title and body you would send, and this disclosure,
verbatim:

> **What this report contains and how it is used:** this report carries
> only the plugin version, the vault structure version, the skill
> involved, a generic description of expected vs. actual behavior, and
> counts. It contains zero personal or business content: no note text, no
> names of people or organizations, no meeting titles. A deterministic
> scrub check enforces this before anything is sent. The only identifying
> fact is which deployment it came from, which is what makes it
> actionable. delaware uses these reports solely to improve the product.
> Nothing is ever sent without your explicit approval.

Then ask plainly: does this look right to send? Proceed only on a clear
yes to the exact text shown. A vague "sure" to an earlier question, or
agreement to *report something* in general, is not approval of *this*
draft — if you change a word after showing it, show it again.

## 5. Send

Write the approved body to scratch, then:

```bash
python3 "$VAULTLIB" feedback send --vault "$VAULT" --title "<approved title>" \
  --body-file "$SCRATCH/feedback-draft.md"
```

`ok: true` returns `issue_url` — tell the user the report went out and give
them the link.

`ok: false` with `error` naming blocked fragments means the lint caught
something the self-check in step 3 missed (or step 3 was skipped). Fix the
draft using the named fragments, show the corrected draft plus the
disclosure again, get fresh approval, and retry. Never paraphrase the
draft and resend it on the strength of the earlier approval — the approval
was for the text you showed, not for whatever you write next.

`ok: false` naming the repo as unconfigured or the token as missing is the
unconfigured-channel case — go to step 6.

## 6. When the channel is not configured

If `feedback.repo` came back `null` in step 1, or `feedback send` failed
because the token is missing, this is never a dead end. Tell the user
plainly that delaware's feedback channel is not set up on this vault yet,
then save the approved draft — title and body, disclosure included — to:

```
10-inbox/feedback-draft-{YYYY-MM-DD}.md
```

Say exactly that: the report could not be sent automatically, and it has
been saved to the inbox for the EA or consultant to relay once the channel
is configured (`feedback.repo` and the token under
`99-workflow-config/secrets/`). The report still exists somewhere useful —
it is just waiting on a wire that is not connected yet.

## Hard rules

1. **Never read `99-workflow-config/secrets/`.** Those are CLI-owned
   credentials. Whether the token exists is learned only from `feedback
   send`'s own error, never by opening the file.
2. **Never send without the user's explicit approval of the exact final
   text.** Not a paraphrase, not an inference from an earlier "yes" to a
   different question — the text shown is the text sent, or it is shown
   again.
3. **The lint is a backstop, not permission to draft carelessly.** Write
   every draft as if no check will ever see it; treat a lint block as a
   sign the draft needs fixing, not as the mechanism doing the scrubbing
   for you.
