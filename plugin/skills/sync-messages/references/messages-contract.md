# Messages contract

You are dispatched by the /sync-messages skill for one night. Inputs in your briefing:
`$VAULT`, `$SCRATCH`, `$VAULTLIB`, `TIMEZONE` (IANA name), `OWNER_ADDRESSES`
(one or more), `SINCE` (UTC ISO), `NOW` (UTC ISO), `GAPS` (a list of
`{id, source, from, to}`, possibly empty).

Every file you write goes to `$SCRATCH` and matches `msg_*.payload.json`; the
skill sweeps them at the end.

## 1. Fetch

Fetch newest first. After each page, write it straight away to scratch, one
JSON object per line, keeping only these keys, values verbatim:

| Source | File | Keys kept |
|---|---|---|
| Teams feed | `msg_teams.p<n>.payload.json` | `id`, `chatId`, `createdDateTime`, `from` (`displayName`, `email`), `summary`, `channelUri` |
| Chat list | `msg_chats.p<n>.payload.json` | `id`, `chatType`, `topic`, `members` (`displayName`, `email`) |
| Inbox | `msg_inbox.p<n>.payload.json` | `id`, `subject`, `sender`, `recipients`, `receivedDateTime`, `summary` |
| Sent Items | `msg_sent.p<n>.payload.json` | the same as Inbox |

`<n>` counts from 1 per source. Every paging loop below also stops when the
connector returns no next offset or cursor. Never write a page file with no rows; if a call
returns nothing, write no file. The one exception is a gap (below) whose fetch
returns no rows at all: write `msg_<source>.gap<id>.p1.payload.json` holding
exactly `{"moreResults": false}`, so the CLI knows the gap was read and closes
it. When you stop a source at its page limit while
the connector still reported more, append one line `{"moreResults": true}` to
that source's last page.

**Teams.** Call `chat_message_search` with `query: "*"`, `limit: 25`, starting at
`offset: 0`, then the returned `nextOffset`. If the first page (`offset: 0`)
comes back with no results at all, the search index is down, not your chats
quiet: write no Teams page, treat Teams as failed (pass `--failed teams` to
build) and go on with mail. A page may hold fewer rows than the
`limit` you asked for (Teams pages hold 19); never assume a page size, and
page by `nextOffset`. Never pass a date filter to `chat_message_search`: with
one it scans chat by chat and is throttled. Keep paging while every result on
the page is newer than `SINCE`; stop at the first result at or before `SINCE`,
keeping only the newer ones. At most 20 pages. Then call `teams_list_chats`
with `limit: 25` and page with `nextCursor` until every `chatId` you saw in the
feed is resolved by a chat in the list, or 4 pages are read. The CLI drops the
Teams rows of a chat that stays unresolved.

**Mail.** Call `outlook_email_search` with `folderName` `"Inbox"`,
`afterDateTime` = `SINCE`, `order` `"newest"`, `limit: 25`, then the same with
`folderName` `"Sent Items"`. Page with `nextOffset`, at most 8 pages per
folder. Never search mail without `folderName`: the sender degrades and the
recipients disappear. Never call `read_resource` on a mail; the `summary` is
enough.

**Long chat messages.** A Teams `summary` ending in `...` was cut off. For at
most 5 of those per night, the longest first, call `read_resource` on
`teams:///chats/{chatId}/messages/{messageId}` and put the full text in that
row's `summary` before writing the page.

**Gaps.** For each gap in `GAPS`, after the normal fetch: for mail, call the same
search with `afterDateTime` = gap `from` and `beforeDateTime` = gap `to`; for
Teams, continue the feed from the offset where the normal fetch stopped: skip
results newer than the gap's `to`, keep results within `from` to `to`, and stop
at the first result at or before the gap's `from`. Stay within the shared
20-page limit and only while `offset` stays below 1000. Write these pages as
`msg_<source>.gap<id>.p<n>.payload.json`. The page limits above are shared:
stop a gap when its source's limit is reached.

A tool error: retry once with the same arguments; then leave that source and go
on with the others. Pass every source you gave up on as `--failed <source>` to
`messages build` (`teams`, `inbox` or `sent`), so the CLI records it as a gap,
and name it in your outcome line.

## 2. Build

```bash
python3 "$VAULTLIB" messages build --vault "$VAULT" --dir "$SCRATCH" \
  --now "$NOW" --timezone "$TIMEZONE" --since "$SINCE" --consume \
  --owner-address a@example.com --owner-address b@example.com   [--gap <id> ...] [--failed <source> ...]
```

Flags repeat: repeat `--owner-address` once per address; repeat `--gap` once per open gap id;
repeat `--failed` once per failed source. The example shows two owner
addresses. Every CLI step returns JSON: read `ok`. When it is false, reply
`fetch-error: <build|check|write>: <error>` and stop.

## 3. Condense

Read `$SCRATCH/msg_groups.payload.json`. For each group in `groups`, write 1 to 4
points: what was said, asked, agreed or decided, in the owner's note language,
each a short sentence, "you" meaning the owner. Every point cites the ids of
the messages it rests on. Use only names, numbers, dates and titles that appear
in those messages; write numbers as digits. Set `needs_owner: true` only when a
message asks the owner for something or is waiting on them.

If build's `groups` is 0 (an empty night), write
`{"groups": []}` to the condensed file, still run check and write (they advance
the cursor and the gap bookkeeping), and reply `nothing-new`.

Write `$SCRATCH/msg_condensed.payload.json`:

```json
{"groups": [{"gid": "<gid>", "needs_owner": false,
             "points": [{"text": "<sentence>", "cites": ["<message id>"]}]}]}
```

## 4. Check, then write

```bash
python3 "$VAULTLIB" messages check --dir "$SCRATCH"
python3 "$VAULTLIB" messages write --vault "$VAULT" --dir "$SCRATCH" --now "$NOW" --timezone "$TIMEZONE"
```

Never rewrite a dropped point to make it pass. A log in `refused` was edited
by hand: leave it, and name it in your outcome line.

## 5. The outcome line (your entire reply)

| Line | When |
|---|---|
| `written: <n> logs, <m> groups, <d> dropped points[, at-limit][, refused: <stems>][, failed: <sources>]` | `messages write` returned `ok` |
| `nothing-new[, failed: <sources>]` | build's `groups` is 0 (after check and write ran on the empty file); add `failed:` when a source could not be read |
| `fetch-error: <what>` | a step failed and nothing was written |
| `auth-error` | the connector refused the account |

Fields of the `written` line, all taken from CLI output:

- `<n>`: the number of entries in write's `written`.
- `<m>`: build's `groups`.
- `<d>`: the number of entries in check's `dropped`.
- `at-limit`: present when build's `at_limit` is true.
- `refused: <stems>`: the `stem` of each entry in write's `refused`.
- `failed: <sources>`: the sources you passed as `--failed`.

Never include message content, names or subjects in the outcome line.
