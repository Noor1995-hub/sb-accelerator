# Meeting-note payload contract (extraction workers only)

You are the worker for exactly one recording. This file defines the payload
`meeting write` accepts; your fetch, write and reply mechanics are in
`worker-contract.md`, which your prompt also names. You draft the payload to
your scratch path and call `meeting write` yourself, and your reply is one
outcome line — never the payload, transcript, or blob text. The routing
fields (projects, attendees, confidence, calendar fields, source, ids, and —
when the prompt names one — entities) were decided for you and arrive in
your prompt: copy them in unchanged. **Exception — M365 only:**
`attendees`, `confidence`, and the `confidence-reasons` attendees-group
entry are not in your prompt; you derive them yourself from your own
`person ensure` calls, per `worker-contract.md`'s Attendees and confidence
section. Every other routing field — including the `confidence-reasons`
calendar-group and project-link-group entries — still arrives in your
prompt and still copies unchanged. `date` and `recording-duration` come
from your own `reassemble` result — except for inbox items and captures,
where the prompt carries them. Your job is the content fields: `title`,
`type` (unless the prompt says this is a `type: note` capture, in which case
that too is decided for you), `takeaways`, `debrief`, `action-items` — from
the transcript; enrichment summaries are supporting context only, never the
source of record.

When your prompt carries a `calendar-context` line (an unmatched recording
made during a calendar event), open the `debrief` with it verbatim, in
italics, on its own line — it tells the reviewer where the call happened.

```json
{
  "title": "vendor strategy walk-through",
  "date": "2026-05-20T11:03",
  "type": "brainstorm",
  "calendar-subject": "Vendor strategy — working session",
  "calendar_match": false,
  "attendees": ["priya-nathan", "morgan-ellery"],
  "projects": ["meridian-yard-automation-program"],
  "recording-duration": 40,
  "source": "recorder",
  "source-recording-id": "plaud:rec_42",
  "source-filename": "Vendor strategy walk-through",
  "confidence": "low",
  "confidence-reasons": ["calendar-tool-unavailable", "content-keyword-match", "all-attendees-known"],
  "takeaways": ["Consolidating on a single automation vendor.", "Yard 2 commissioning slips ~6 weeks."],
  "debrief": "### Vendor strategy\nWhat was argued, by whom, and what shifted.",
  "action-items": ["**Priya Nathan** — circulate the revised schedule"]
}
```

No `entities` key here on purpose: `projects` is non-empty, so `meeting
write` derives `entities` from `meridian-yard-automation-program`'s `entity:`
field itself. Passing `entities` alongside a non-empty `projects` is refused.

Payload rules the CLI enforces (so get them right the first time):

- `title` is a short kebab-able label — the filename becomes
  `{DD-MM-YY}-{title-slug}.md`. `date` is ISO, the recording's local start —
  for a Plaud or Teams recording that is `recorded_local` unchanged.
- `type` is a closed enum and nothing else is accepted: **`meeting` · `1:1` ·
  `steerco` · `workshop` · `brainstorm` · `status-update` · `note`**. A plain
  conversation is `meeting`; there is no `call`, no `review`, no `sync`. When
  none of the others clearly fits, `meeting` is the right answer.
- `source` is a closed enum too: **`teams` · `recorder` · `manual` ·
  `email`** — the channel the item arrived by, not the tool that made it.
- `attendees`/`projects`/`entities` are slugs and must resolve (person notes,
  project folders, `40-entities/<slug>/dossier.md`). `attendees` must be
  non-empty — except on a `type: note` capture, which may pass `[]` when the
  item names nobody. `projects` may be empty (triage catches unassigned
  meetings). `entities` is optional, machine-derived from `projects` whenever
  `projects` is non-empty, and omitted from the file when there is nothing to
  write — it is a routing value like the rest of them: when the orchestrator's
  prompt includes it (only possible when `projects` is empty), copy it in
  unchanged; never add it yourself, and never alongside a non-empty
  `projects` (refused). Optional `people` (slug list) renders a
  `## People` wikilink section. `takeaways` is 1–5 strings. `type` values
  with a colon (`"1:1"`) are handled by the CLI — pass them as plain strings.
- Do NOT pass `review_status`, `reviewed`, `archived`, or `processed` — the
  CLI sets them.
- `source-recording-id` is **required** on every write — it IS the dedup
  ledger. For inbox files it is the `recording_id` from `sync scan`; for
  Plaud and Microsoft 365 it comes from `plaud reassemble` /
  `m365 reassemble`. The CLI stores it in canonical form — Plaud's `of_`
  object prefix stripped — so a note carries `plaud:<hex>` for a recording
  the connector lists as `of_<hex>`; both spellings dedup as one.
