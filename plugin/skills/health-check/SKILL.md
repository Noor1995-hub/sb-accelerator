---
name: health-check
description: Run the vault's content-free hypercare health check — meeting cadence, review backlog, daily-note coverage, staleness — and optionally share the numbers with delaware. Triggers when the user invokes /health-check, or the vault owner wants a weekly hypercare pulse or a pre-tune-up read.
user_invocable: true
origin: net-new
---

# Health Check

Answers "is the machinery running" in counts, rates, and ages — never in
titles, names, or filenames. The CLI's `health report` is content-free by
construction; this skill's job is to read those numbers out loud and, only
on explicit request, offer to send them to delaware.

## Requirements

Running the report and writing it to the vault needs a shell, so this skill
runs in **Cowork** or **Claude Code**. It cannot run in Chat — plugins are
not loaded there; say so plainly rather than trying to compute or write
anything by hand.

Set `VAULT` to the vault root, and:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution (`python3`, then `python`,
then `py -3`) are documented in the plugin's `CLAUDE.md`. Read `ok` on every
call; on failure surface `error` and `hint`.

## Usage

```
/health-check
```

No arguments needed. Runs unattended just as well as interactively — there
is nothing here that blocks on a question until the sharing offer at the
end.

## 1. Run the report

```bash
python3 "$VAULTLIB" health report --vault "$VAULT" --write
```

`--write` renders the report to
`99-workflow-config/health-reports/{date}.md` and adds `written` (the
vault-relative path) to the result. Every value in the result is a count, a
rate, an age, a date, or a version string — the CLI folds anything
out-of-enum to `"unknown"` before it can reach you, so there is nothing here
that names a project, an entity, or a person.

## 2. Present the numbers

Read the numbers out loud with judgment on top of them — say what looks
healthy and what looks stale — but **quote only the numbers**. Never name
which project is stale, which entity has gone quiet, or any other vault
object; the counts carry the whole story:

- Meetings in the window, and how many still have no project linked.
- Daily-note coverage over working days in the window.
- Inbox items pending and the skip-list size.
- Projects and entities with no meeting reference in the last 30 days —
  as a count ("2 of 7 projects"), not by name.
- Decisions by status, and how many frontmatter reads failed to parse
  (`unparsed`) — a sign worth a mention if it is not zero.
- `provenance.plugin_drift`: `behind` means a tune-up is pending — this
  machine's plugin is newer than what last provisioned or upgraded the
  vault, so `/upgrade-vault` has something to check; `ahead` means the
  opposite — this machine's own plugin cache is older than what last wrote
  the vault, which is itself worth a mention (a stale local install);
  `matches` means nothing to flag; `unknown` means the vault has no
  provenance record yet (it predates this feature) or the record could not
  be read. Never read out the version numbers or dates behind this as vault
  content — the state (`behind`/`ahead`/`matches`/`unknown`) is the whole
  story here.
- `claude_link`: `is_symlink: false` with `state: directory` is the
  OneDrive-copy case — a sync client materialised `.claude` as a real
  directory copy instead of preserving the symlink, which silently breaks
  the vault-local Claude Code files. Flag that one by name; hand it to the
  consultant rather than trying to repair it — this skill never touches
  the filesystem to fix it.
- `template`: `.base` views, `.obsidian` settings, and the other
  plugin-owned template files, as counts only — never a filename. Read out
  `managed` against `current` (how many already match what this plugin
  ships), and separately flag `needs_consent` and `missing` if either is
  non-zero — that's what `/upgrade-vault`'s template-refresh step (5) would
  act on at the next visit. `baseline: "unknown"` means this vault predates
  the feature entirely, so every managed file will need consent the first
  time someone runs a refresh.
- `messages`, only when `enabled` is true (skip it entirely when the feed
  is off): read out `days_at_limit` against `logs_in_window`. Days at the
  limit means a day had more mail and chat than the safety limit; a few are
  fine, many mean the limit should be raised.

Then name the report file so the user can open it themselves:

```
99-workflow-config/health-reports/{generated}.md
```

(`{generated}` is the `generated` date the result returned, the same one
`--write` used to name the file.)

## 3. Offer to share with delaware — never auto-run

Sharing is always the user's call, never something this skill does on its
own initiative. Ask only after the numbers are already shown: does this
look like something worth sending to delaware?

Learn the channel state first, quietly:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

A `null` `feedback.repo` means the channel is not configured — remember
that and still make the offer; the report still gets filed for later (see
below), it just does not try GitHub. Do not go looking for the GitHub token
yourself — whether it exists is `feedback send`'s business, exactly as in
`/report-feedback`.

If the user wants to share, show this disclosure verbatim before asking for
final approval — the same text `/report-feedback` shows, because it is the
same `feedback send` path underneath:

> **What this report contains and how it is used:** this report carries
> only the plugin version, the vault structure version, the skill
> involved, a generic description of expected vs. actual behavior, and
> counts. It contains zero personal or business content: no note text, no
> names of people or organizations, no meeting titles. A deterministic
> scrub check enforces this before anything is sent. The only identifying
> fact is which deployment it came from, which is what makes it
> actionable. delaware uses these reports solely to improve the product.
> Nothing is ever sent without your explicit approval.

Then ask plainly: send this health report to delaware? Proceed only on a
clear yes — a vague "sure" earlier in the conversation is not approval of
this send.

On a clear yes:

```bash
python3 "$VAULTLIB" feedback send --vault "$VAULT" \
  --title "Health report {generated}" \
  --body-file "$VAULT/99-workflow-config/health-reports/{generated}.md"
```

`feedback send` runs its own scrub lint on the file before it sends
anything — the report should never trip it, since `health report` never
writes a title, a name, or a filename into it, but if `ok: false` names
blocked fragments, stop and tell the user rather than retrying with the
same file. `ok: true` returns `issue_url` — tell the user it went out and
give them the link.

## 4. When the channel is not configured

If `feedback.repo` came back `null` in step 3, or `feedback send` failed
because the token is missing, this is never a dead end. Tell the user
plainly that delaware's feedback channel is not set up on this vault yet,
then save a copy of the approved title, the report body, and the
disclosure to:

```
10-inbox/feedback-draft-{generated}.md
```

Say exactly that: the report could not be sent automatically, and it has
been saved to the inbox for the consultant to relay once the channel
is configured (`feedback.repo` and the token under
`99-workflow-config/secrets/`). The health report itself already exists at
`99-workflow-config/health-reports/{generated}.md` regardless of whether
sharing happened — running this skill is never wasted even offline.

## Cadence

Run this weekly during hypercare (weeks 2–4), and again before each
tune-up — that cadence is what turns "is anything drifting" from a guess
into a read of the same six numbers each time.

## Hard rules

1. **Never read `99-workflow-config/secrets/`.** Those are CLI-owned
   credentials. Whether the token exists is learned only from `feedback
   send`'s own error, never by opening the file.
2. **Never send without the user's explicit approval of the exact report
   being sent.** Not a paraphrase, not an inference from an earlier "yes"
   to a different question.
3. **Never name a vault object when presenting the numbers.** Counts,
   rates, and ages only — the same content-free contract `health report`
   itself keeps.
