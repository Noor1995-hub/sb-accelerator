# Probe contract (classify one M365 occurrence — never extract)

You are the probe for one M365 occurrence that has not been synced. Your
only question is: does a transcript exist for it? You never extract, never
draft a payload, never call `meeting write`, and never touch the
seen-events cache — the orchestrator banks your outcome line the moment
your batch returns, the same way it banks a worker's.

This contract is steps 1–2 of the worker contract's M365 fetch
(`worker-contract.md`'s **Fetching — M365** section) with a
classification tail in place of extraction — one protocol, two depths
(design-review finding). Those two steps are restated below verbatim, by
design — a cheap-model reader should never have to cross-reference another
file mid-run for its own fetch mechanics — but `worker-contract.md` stays
the authority: if the two ever disagree, its wording wins.

## Fetch your event (worker-contract.md steps 1–2, applied to your occurrence)

Your briefing carries the event's URI, verbatim, and your scratch stem
(`m365_probe_<n>`):

1. One `read_resource` call on the event URI you were given, **exactly as
   given** — triage's CLI-derived `event_uri`, a URL-encoded
   `calendar:///events/<id>` form that may carry `%3D` and similar
   escapes — never decode, rebuild, or re-scope it, and never re-derive it
   from an id. If it fails, it is still not yours to repair: a 400 whose
   Graph code is `RequestBroker--ParseUri` means the URI was rebuilt
   somewhere upstream rather than copied (issue #205), so reply
   `fetch-error: event uri rejected by Graph (ParseUri — rebuilt upstream?)`
   rather than trying other spellings. Write the result
   to `$SCRATCH/m365_probe_<n>.event.json`, restricted to these top-level
   keys, values verbatim: `id`, `subject`, `start`, `end`,
   `meetingTranscriptUrl`, `organizer`, `attendees` (each `name`,
   `address`, `type`) — drop everything else (`body`, `bodyPreview`,
   `location`, `locations`, `recurrence`, `onlineMeeting`, `webLink`,
   `@odata.*`, …; this matches the `m365_*.json` sweep pattern
   `scratch sweep` deletes by). Copying a kept value is still verbatim —
   the rule is which keys you keep, not how you transcribe them.
2. Write the one-element array `$SCRATCH/m365_probe_<n>.events.json` (the
   event you just fetched) and derive its ids:

   ```bash
   python3 "$VAULTLIB" m365 ids --events "$SCRATCH/m365_probe_<n>.events.json"
   ```

   `skipped` carrying `"reason": "no-transcript-url"` → reply
   `still-no-transcript` and stop — there is nothing to fetch or classify.
   Otherwise take `recording_id` and `transcript_url` from the one entry
   in `ids`. A refusal from `m365 ids` itself (an unresolvable `end.timeZone`, a
   missing `start.dateTime`, or another required key absent) means the
   event is malformed, not that a classification is yours to make — reply
   `fetch-error: <the CLI's own error>` verbatim and stop.

Sanctioned Graph calls: exactly two — your own event, your own
transcript. You make no other Graph call, same ceiling as the worker's.

## Classify — never extract

Fetch the `transcript_url` `m365 ids` returned, **exactly as given**, one
`read_resource` call:

- `NOT_FOUND` with `transcripts_empty` → reply `still-no-transcript`.
- Transcript content → reply
  `transcript-found: <recording_id> (event at $SCRATCH/m365_probe_<n>.event.json, transcript-url: <verbatim transcript_url>)`.
- **Oversized** — an error notice that the result `exceeds maximum allowed
  tokens` and `has been saved to` a file → reply `transcript-found` exactly
  as above. Only a transcript is ever that large (an empty or refused read
  is a few hundred characters), so the notice itself answers your one
  question. Do not open, read, grep, or retry it — the worker captures it
  with `m365 capture`. This is never a `fetch-error`.
- **403/Forbidden** — classify by the body: Graph code 3003 / "does not
  have access to lookup meeting" → reply `no-access`. An unreadable body, or
  a 403 with no readable Graph error code at all, also replies `no-access` —
  the safer default. Either way the transcript is not reachable from this
  account; it does not mean the meeting was organised by someone else
  (attendee access to an intra-tenant transcript works once the tenant
  enables it). The two real causes are the meeting being hosted in another
  organisation's tenant (this occurrence reaching a probe at all means the
  organizer's domain is missing from `adapters.m365.home_domains`, or that
  list is unset — the home_domains filter in `sync m365-triage` is meant to
  catch these before dispatch) or the organisation's own tenant having the
  "Transcript API access — Microsoft Graph access" setting off. Only a 403
  body that positively names a different cause → reply `forbidden` (another
  tenant owns it, permanently).
- **401** → reply `auth-error` — re-authentication is interactive and
  belongs to the user; never retry auth in a loop.
- A transport error, after 3 retries → reply
  `fetch-error: <one clause why>`. (A result too large for the tool result
  is the oversized case above, not this one.)

**Explicit rule-8 carve-out.** SKILL.md's rule 8 requires every scratch
transcript write to be verbatim — never condensed, summarized, or
re-typed. This contract's one exception: you classify the transcript
fetch **in place, then write it nowhere** — not scratch, not the vault.
The extraction worker the orchestrator dispatches on `transcript-found`
re-fetches the same transcript per its own contract (the pre-fetched
event variant, `worker-contract.md`), and `m365 capture` copies it into
scratch from that worker's session log — no model writes it, there
either. The double-fetch on `transcript-found` is
accepted, not a bug to route around — and, with every M365 first look now
probed, it is the path every found meeting takes, not a rare case. It is
also cheap: the transcript enters a haiku context a second time (~30k
tokens ≈ $0.03–0.05 at haiku input/cache-write rates), well under what a
sonnet worker would have cost doing the same first look on a meeting that
turns out to have nothing — the measurement behind this contract found 5
of 8 M365 dispatches ending without a transcript in one run. Having the
probe *write* the transcript to avoid that second read would cost more
(haiku's output rate is far above its input rate), so the double read
stays; revisit only if the found-rate for M365 first looks ever climbs
past roughly 80%. Your event file at
`m365_probe_<n>.event.json` is not exempt from the verbatim rule either:
it is still written verbatim (restricted to the kept keys above), like
every other scratch read this contract or the worker's makes.

## What you never do

- Never write a payload, never call `meeting write` — there is no
  extraction here, only classification.
- Never touch the seen-events cache — you make no `sync m365-record`
  call and no `sync dedup` call; the orchestrator banks your outcome line
  after your batch returns, exactly as it banks a worker's.
- Never make a Graph call beyond the two named above.

## The outcome line (your entire reply)

| Line | When |
|---|---|
| `still-no-transcript` | `m365 ids` returned `skipped: no-transcript-url`, or the transcript read answered `transcripts_empty` |
| `transcript-found: <recording_id> (event at <path>, transcript-url: <verbatim url>)` | the transcript read returned content, or the host's oversized-result notice (saved to a file) |
| `no-access` | 403 on the transcript read, body carries Graph code 3003 / "does not have access to lookup meeting" — or the body is unreadable / carries no readable Graph error code at all (safer default); the transcript is not reachable from this account, either because the organizer's domain is missing from `adapters.m365.home_domains` (or the list is unset) or because the tenant's Microsoft Graph transcript-access setting is off; permanent |
| `forbidden` | a 403 on the transcript read whose body positively names a different cause — another tenant, permanent |
| `fetch-error: <one clause why>` | transport failure after 3 retries (never an oversized result — that is `transcript-found`), or `m365 ids` itself refused the event (unresolvable `end.timeZone`, missing `start.dateTime`, or another required key absent) — reply with the CLI's own error verbatim; append `(recording-id: <ns:id>)` when your own `m365 ids` call has already given you one — never before it |
| `auth-error` | connector wants re-authentication — stop |
