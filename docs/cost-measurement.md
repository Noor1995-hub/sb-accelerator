# Cost measurement for a session

`scripts/cost_report.py` prices a Claude Code session export at list rate,
per agent — the tool used to sanity-check a routine run (e.g.
`/sync-recordings`) against, and reconcile against, what the app's own
session-cost card shows.

## Why the app card under-counts

The transcript repeats the same assistant message once per content block,
and each repeat carries its own partial `usage` snapshot for that message
id — `output_tokens` climbs as the model keeps generating, and the
cache-read/cache-write counts can still be mid-flight too. The app's
session-cost card takes the **first** usage record it sees per message id.
`cost_report.py` takes the **max** per key across every repeat — the true
total for that message. On subagent-heavy runs (many short dispatches,
each with only a handful of content blocks) this gap compounds: the card
is a real under-count, not rounding noise.

## Export a session

Use `mcp__ccd_session_mgmt__export_transcript` on the session to cost. It
writes:

```
transcript.jsonl                                — main session
<session-uuid>/subagents/agent-<id>.jsonl        — one subagent's transcript
<session-uuid>/subagents/agent-<id>.meta.json    — that subagent's agentType/description
metadata.json                                    — session metadata
```

either as a `.zip` or already extracted — `cost_report.py` accepts either
and locates `transcript.jsonl` itself.

## Run the report

```
python scripts/cost_report.py path/to/export.zip
python scripts/cost_report.py path/to/extracted-dir/ --json
python scripts/cost_report.py path/to/export.zip --pricing my-prices.json
```

`--pricing` points at a JSON file that overrides the default per-MTok list
prices for one or more model buckets, e.g.:

```json
{"sonnet": {"out": 14.00}}
```

`--json` prints a machine-readable report (rows, by-`agentType` totals,
grand total, warnings) after the table.

## Reading the table

One row per agent: the main session (`agentType: main`) plus one row per
`agent-<id>.jsonl` subagent, carrying that subagent's `.meta.json`
`agentType` and `description`. Columns are requests (distinct
`message.id` count), output tokens, cache-read tokens, cache-write
tokens, and cost at list price — there is no input-tokens column, though
input tokens do feed the cost math. Below the table: a total per
`agentType`, then a grand total.

An unrecognized `message.model` (not matching `sonnet`/`haiku`/`opus` by
substring) is priced as sonnet and reported as a warning on stderr — check
those before trusting the total on a run that used a new model name.
