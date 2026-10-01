---
name: sync-messages
description: Read the owner's Outlook mail and Teams chats into hidden day logs, and handle switching the feed on or off, exclusions, forgetting and corrections. Triggers when /evening-sync runs its stage 3b, when the user invokes /sync-messages, or asks to start or stop reading their mail and Teams, to skip or forget someone or something, to link a code to a project, or to catch up on mail.
user_invocable: true
origin: net-new
---

# Sync Messages

Keeps the second brain aware of what happens in mail and Teams chat, so a
session already knows. The owner reads mail in Outlook and chat in Teams; they
meet the result, not the logs (`_messages/`, hidden).

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat.

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Read `ok` on every call; on failure surface `error` and `hint`.

## Speaking to the owner

Plain words, no internal terms: "your mail and Teams", "what I saved", never
"log", "group", "cursor" or "exclusion". Read back every change in one
sentence.

## Switching on

Only with Microsoft 365 connected and its account proven
(`config verify-account --adapter m365` returns `match: true`; call `get_me`,
write the raw JSON to `$SCRATCH/m365.whoami.json` and pass it as `--identity`).
On `match: false`, tell the owner plainly that the connected account is not
theirs, and switch nothing on.

1. Ask, verbatim: *"Each evening I can look through your inbox, your sent mail
   and your Teams chats (not Teams channels, not attachments). I read the
   opening lines of each mail and your chat messages, and save short notes on
   what was said in your second brain, which only you can see. I keep them like
   your meeting notes; they include what other people wrote to you. You can
   tell me at any time to skip a person, a company or a topic, or to stop and
   delete everything. Shall I start?"* No is a complete answer: change nothing
   and do not ask again this session.
2. On yes:
   ```bash
   python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.enabled --value true
   python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.consented-at --value "<now, YYYY-MM-DDTHH:MM local>"
   python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.scope --value "teams-chats,inbox,sent-items"
   ```
3. Ask: *"Is there anyone or anything I should never read? For example HR
   matters or a private chat. You can also tell me later."* For each answer,
   resolve it and add it as under **What to skip** (below). No answer means
   none.
4. Read back: *"From tonight I'll read your mail and Teams, starting with
   today's messages."* plus the read-back of each exclusion from **What to
   skip**.

## Switching off

Ask: *"Shall I keep what I saved so far, or delete it?"* Then:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.enabled --value false
python3 "$VAULTLIB" messages forget --vault "$VAULT" --all   # only if they said delete
```

Read back what happened.

## What the owner can ask

Every command below is `python3 "$VAULTLIB" <group> <action> --vault "$VAULT" …`;
the table abbreviates it to `<group> <action> …`. Full examples:

```bash
python3 "$VAULTLIB" messages exclude add --vault "$VAULT" --kind person --value "jo@example.com" --label "Jo"
python3 "$VAULTLIB" messages forget --vault "$VAULT" --text "X"                       # find only
python3 "$VAULTLIB" messages forget --vault "$VAULT" --text "X" --apply <ref1> --apply <ref2>
python3 "$VAULTLIB" messages forget --vault "$VAULT" --exclusion <id> --apply <ref1>
python3 "$VAULTLIB" project keywords add --vault "$VAULT" --slug <slug> --keyword "P-2317"
python3 "$VAULTLIB" messages for-project --vault "$VAULT" --slug <slug> --logs <stem1>,<stem2>
python3 "$VAULTLIB" messages unlink --vault "$VAULT" --log <stem> --gid <gid> --project <slug>
python3 "$VAULTLIB" messages cursor --vault "$VAULT" --now "<now UTC>" --timezone "<timezone>" --since "<start>"
```

`--text` and `--exclusion` only find without `--apply`. To remove, repeat the
same target flag and add `--apply <ref>` once per ref the owner confirmed.
`--all` deletes every saved note at once and is used only when switching off
after the owner said delete; never combine it with `--apply`. `--logs` stems are the file names in `_messages/` without
`.md`, most recent first.

| They say | Do |
|---|---|
| "don't read X anymore" | Resolve X to an exact value first (**What to skip**, below); if it cannot be resolved, say so and add nothing. Then `messages exclude add --kind person\|domain\|chat\|word --value <resolved value> --label "<X in their words>"` and read back exactly what is skipped, in the words below. Then find with `messages forget --exclusion <id>` and offer what it found: *"I found N older notes about X. Shall I remove those lines?"* Only on yes, repeat `messages forget --exclusion <id> --apply <ref1> --apply <ref2>`, one `--apply` per confirmed ref |
| "read X again" | `messages exclude list` to find it, then `messages exclude remove --id <id>`; read back |
| "forget what you saved about X" | find with `messages forget --text "X"`; show the found lines in plain words; on yes repeat `messages forget --text "X" --apply <ref1> --apply <ref2>` with exactly the confirmed refs |
| "link P-2317 to <project>", or yes to the weekly proposal | `project keywords add --slug <slug> --keyword "P-2317"`; read back |
| "that mail isn't about <project>" | find the group with `messages for-project --slug <slug> --logs <recent stems>`; `messages unlink --log … --gid … --project <slug>`; read back that tonight's update drops it |
| "catch up on my mail from last week" | run the workflow below with `--since <start>` on `messages cursor` |
| about mail from before switching on, or from someone excluded | say plainly you have not read it and why; offer a live search in Outlook |
| "what don't you read?" | `messages exclude list`, plus the fixed scope: channels and attachments are never read |

### What to skip

The feed skips exact values only, so turn the owner's words into one before
adding anything. The CLI refuses a value of the wrong shape (a name where an
address belongs, a chat name where its id belongs); on that refusal, resolve
again, never retry with a guess.

| They name | Kind and value | Read back |
|---|---|---|
| a person | `person`: the `email` of their note in `50-people/`, when it is set; otherwise ask the owner for the address | *"I won't read mail with <name> or your 1:1 chat with them, and in group chats I skip what they write and leave them out."* |
| a chat | `chat`: call `teams_list_chats` and look only at chat names and members, never message text; match by topic or by members, confirm by name (*"The chat 'Rollout' with Sam Lee and Jordan Reyes?"*), then use that chat's `id` | *"I won't read the chat <name>."* |
| a company | `domain`: its email domain, like `acme.example`; ask when it is unclear | *"I won't read mail with anyone at <domain> or your 1:1 chats with them, and in group chats I skip what they write and leave them out."* |
| a topic | `word`: one word or code | *"I won't read mail whose subject, or chats whose name, holds '<word>'."* |

If X cannot be resolved (no address, no matching chat, an unclear company),
say so in one plain sentence and add nothing.

## Workflow (one run)

1. **Preflight.** `config read`: stop with one line if `messages.enabled` is
   false, M365 is disabled, or `timezone`/`owner` are missing. Call `get_me`,
   write the raw JSON to scratch and run:
   ```bash
   python3 "$VAULTLIB" config verify-account --vault "$VAULT" --adapter m365 --identity "$SCRATCH/m365.whoami.json"
   ```
   Stop on anything but `match: true`. Collect the owner's addresses: the m365
   `account_hint`, and from `get_me` its `mail` and `userPrincipalName`.
2. **Where to start.**
   ```bash
   python3 "$VAULTLIB" messages cursor --vault "$VAULT" --now "<now UTC>" --timezone "<timezone>" [--since "<owner's start>"]
   ```
   Keep `since`, `first_run` and `gaps`.
3. **Dispatch the worker**, blocking, one call:
   `subagent_type: second-brain:sync-messages-worker`. Pass paths and values,
   never content: the contract path
   `${CLAUDE_PLUGIN_ROOT}/skills/sync-messages/references/messages-contract.md`,
   `$VAULT`, `$SCRATCH`, `$VAULTLIB`, `TIMEZONE`, `OWNER_ADDRESSES`, `SINCE`,
   `NOW`, `GAPS`. You read neither the contract nor the worker's files yourself.
4. **Record the outcome line** for the evening summary, verbatim as the worker
   returned it. A `nothing-new` outcome may carry `, failed: <sources>`; keep
   that suffix, it tells the owner a source could not be read. Under
   `/evening-sync`, hand back: the outcome line and, when `first_run` was true,
   `since` (stage 6 passes it to `messages status --first-run-since`). On
   `fetch-error: …` or `auth-error`: record the line verbatim for the evening
   summary, change nothing, and never retry in the same run.
5. **Scratch hygiene.**
   ```bash
   python3 "$VAULTLIB" scratch sweep --dir "$SCRATCH"
   ```

## Unattended mode

Under `/evening-sync` unattended: never ask a question, never switch on or
off, never add or remove an exclusion, never forget anything. Run the workflow
and report. A failed run moves nothing: the next run starts from the same
place.

## Hard rules

1. Nothing is read before the owner's yes to the consent question.
2. Every vault write goes through `$VAULTLIB`.
3. Nothing is removed without the owner's yes to the exact lines found.
4. Message content never appears in the main conversation, the run log or a
   summary line.
