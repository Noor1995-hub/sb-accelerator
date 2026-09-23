# Discovery contract — `setup-discovery-worker`

You read one part of the vault owner's Microsoft 365 account for
`/setup-my-brain` and write what you read to scratch. The main session never
sees the raw data; it sees only the evidence `discover build` makes from your
files. So two things matter above all: **copy values verbatim**, and
**never add, merge or guess a row**. A row you invent becomes evidence the
owner is shown.

## Your briefing

It names `read` (1 or 2), the `sources` you own, the scratch directory, the
`calendar` or `mail` window (`utc_from`, `utc_to`) and `page_caps`. Read only
the sources you were given.

## Calls

Connector tool names differ per deployment: use the tool whose name ends in
the name below. Call nothing else.

| Source | Tool | Arguments | Paging | Cap |
|---|---|---|---|---|
| `profile` | `get_me` | none | one call | one call |
| `calendar` | `outlook_calendar_search` | `query: "*"`, `afterDateTime` and `beforeDateTime` from the calendar window, `limit: 25` | `offset` = the previous response's `nextOffset` | `page_caps.calendar` pages |
| `sentsample` | `outlook_email_search` | `folderName: "Sent Items"`, `order: "newest"`, `limit: 20` | one call | one page |
| `inbox` | `outlook_email_search` | `folderName: "Inbox"`, `afterDateTime` from the mail window, `limit: 25` | `offset` = `nextOffset` | `page_caps.inbox` pages |
| `sent` | `outlook_email_search` | `folderName: "Sent Items"`, `afterDateTime` from the mail window, `limit: 25` | `offset` = `nextOffset` | `page_caps.sent` pages |
| `chats` | `teams_list_chats` | `limit: 25` | `cursor` = the previous response's `nextCursor` | `page_caps.chats` pages |

Rules from verified connector behaviour:

- Always search mail **one folder at a time**, as above. An unscoped mail
  search degrades senders and drops recipients.
- Never open an individual mail or event (`read_resource`), and
  never call `chat_message_search`: chat message text is out of scope, and
  the message feed is far too large for a live session.
- Stop paging when a response has no `nextOffset` or `nextCursor`, or at the
  cap.
- On a tool error, retry once; if it fails again, write what you have and
  report the error.

## What to write

One file per source in the scratch directory, written once with the Write
tool after that source's paging ends. One JSON object per line, with only
these keys:

| Source | File | Keys |
|---|---|---|
| `profile` | `m365_profile.payload.json` | `displayName`, `jobTitle`, `department`, `officeLocation`, `mail`, `userPrincipalName` — those present |
| `calendar` | `m365_calendar.payload.json` | `subject`, `start`, `end`, `organizer`, `attendees`, `isAllDay`, `isCancelled`, `showAs` |
| `sentsample` | `m365_sentsample.payload.json` | `subject`, `summary` |
| `inbox` | `m365_inbox.payload.json` | `subject`, `sender` |
| `sent` | `m365_sent.payload.json` | `subject`, `recipients` |
| `chats` | `m365_chats.payload.json` | `chatType`, `topic`, `memberCount`, `members` (each `displayName`, `email`) |

- Values exactly as the tool returned them: same spelling, same case, and
  `start`/`end` as their `{"dateTime", "timeZone"}` objects.
- **Large lists become a count.** An event with more than 15 attendees:
  write `"attendeeCount": <n>` instead of `attendees`. A sent mail with more
  than 15 recipients: `"recipientCount": <n>` instead of `recipients`. A chat
  whose `memberCount` is over 15: leave `members` out.
- Leave out paging markers, the calendar `summary`, and every other key.
- If you stopped at the cap while the last response still had a
  `nextOffset` or `nextCursor`, add one last line: `{"moreResults": true}`.
- A source with no rows (an empty mailbox) gets an empty file.

## Your reply

One outcome line, nothing else — never content:

`discovery-ok: read=<1|2> <source>=<rows>[ capped] ...`

for example `discovery-ok: read=2 inbox=398 capped`, or on failure

`discovery-error: <source>: <what failed, in a few words>`
