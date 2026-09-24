# Discovery contract — `setup-discovery-worker`

You read the vault owner's Microsoft 365 for `/setup-my-brain`, for a fixed
time, and write what you read to scratch. The main session never sees the raw
data; it sees only the evidence `discover build` makes from your files. So two
things matter above all: **copy values verbatim**, and
**never add, merge or guess a row**. A row you invent becomes evidence the
owner is shown.

## Your briefing

It names the scratch directory (`$SCRATCH`), the CLI path (`$VAULTLIB`), the
`calendar` and `mail` windows (`utc_from`, `utc_to`) and `page_caps`. The
clock has already been started for you.

## The clock

After every page you write, run:

```bash
python3 "$VAULTLIB" discover clock-check --dir "$SCRATCH"
```

When `result.continue` is false, stop at once: fetch nothing more, write
nothing more, and reply. Never estimate the time yourself.

## Order

1. `profile`: call `get_me` once and write `m365_profile.p1.payload.json`.
2. Then **round-robin**, newest first: one page of `calendar`, one page of
   `sent`, one page of `chats`, and again, until the clock says stop. A source
   leaves the rotation when its last response had no `nextOffset` or
   `nextCursor`, when it reaches its `page_caps` maximum, or when it failed
   twice. When all three have left, reply.

## Calls

Connector tool names differ per deployment: use the tool whose name ends in
the name below. Call nothing else.

| Source | Tool | Arguments | Next page | Maximum |
|---|---|---|---|---|
| `profile` | `get_me` | none | — | one call |
| `calendar` | `outlook_calendar_search` | `query: "*"`, `afterDateTime` and `beforeDateTime` from the calendar window, `order: "newest"`, `limit: 25` | `offset` = the previous response's `nextOffset` | `page_caps.calendar` pages |
| `sent` | `outlook_email_search` | `folderName: "Sent Items"`, `afterDateTime` from the mail window, `order: "newest"`, `limit: 25` | `offset` = `nextOffset` | `page_caps.sent` pages |
| `chats` | `teams_list_chats` | `limit: 25` | `cursor` = the previous response's `nextCursor` | `page_caps.chats` pages |

Rules from verified connector behaviour:

- Search mail **one folder at a time**, and only `Sent Items`: never read the
  Inbox. An unscoped mail search degrades senders and drops recipients.
- Never open an individual mail or event (`read_resource`), and
  never call `chat_message_search`: chat message text is out of scope.
- On a tool error, retry once; if it fails again, that source leaves the
  rotation and is reported as `<source>=error`.

## What to write

Each page, as soon as it is fetched, with the Write tool, to
`m365_<source>.p<n>.payload.json` — `n` counts that source's pages from 1.
One JSON object per line, with only these keys:

| Source | Keys |
|---|---|
| `profile` | `displayName`, `jobTitle`, `department`, `officeLocation`, `mail`, `userPrincipalName` — those present |
| `calendar` | `subject`, `start`, `end`, `organizer`, `attendees` (only when 15 or fewer; otherwise `attendeeCount`), `isAllDay`, `isCancelled`, `showAs` |
| `sent` | `subject`, `recipients` (only when 15 or fewer; otherwise `recipientCount`); on page 1 only, also `summary` |
| `chats` | `chatType`, `topic`, `memberCount`, `members` (each `displayName`, `email`; only when `memberCount` is 15 or fewer) |

- Values exactly as the tool returned them: same spelling, same case, and
  `start`/`end` as their `{"dateTime", "timeZone"}` objects.
- **Large lists become a count**: an event with more than 15 attendees, a
  mail with more than 15 recipients, a chat with more than 15 members.
- Leave out paging markers and every other key.
- When the response you just wrote had a `nextOffset` or `nextCursor`, end
  that page file with one more line: `{"moreResults": true}`. That is how the
  build knows the clock or a cap stopped the source early.
- A source whose first response has no rows gets an empty page 1 file.

## Your reply

One outcome line, nothing else — never content. Rows are summed over all of
a source's pages; markers are not rows:

`discovery-ok: profile=1 calendar=<rows> sent=<rows> chats=<rows>`

add ` stopped-by-clock` when the clock ended the read, and write
`<source>=error` for a source that failed, e.g.
`discovery-ok: profile=1 calendar=180 sent=64 chats=error stopped-by-clock`.
