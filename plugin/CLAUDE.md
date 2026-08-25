# Plugin internals

Instructions for working *on* this plugin. Not shipped guidance for the
executive — that lives in the vault's own `CLAUDE.md`. Excluded from the
version-bump requirement (see the repo's root `CLAUDE.md`).

## Where writes happen

Skills do not author object frontmatter. Every write goes through the
deterministic CLI:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" <group> <action> --vault "$VAULT" ...
```

Each run prints exactly one JSON object and signals through its exit code:

```json
{"ok": true,  "result": {...}}
{"ok": false, "error": "...", "hint": "..."}
```

Read `ok` before anything else. On failure, the `error` names the constraint
and `hint` says what to do — surface both to the user rather than retrying
blind or working around the CLI by writing files directly.

### Table cells are stored with the pipe escaped

A markdown table row is delimited by `|`, so `entity write` escapes any pipe
inside a cell as `\|` before storing it. That escape is part of the stored
form, and `entity read` returns cells exactly as stored — a note the user
dictated as `wants numbers | not narrative` comes back as
`wants numbers \| not narrative`.

There is no inverse. A caller that read a cell and wants to send text back
must send the **unescaped** form, because the write path re-escapes every
cell it is given. Passing the stored form straight back through
`entity write` accumulates backslashes on each round trip. This applies only
to the two table sections, Stakeholders and Engagements; bullet and heading
sections store free text as given.

### Wikilink fields cross the boundary as bare stems

`decision write` takes `supersedes` and `source` as bare note stems
(`2026-03-10-phased-rollout-adopted`) and `decision list` returns them the same
way. The `[[...]]` wrapping — and the quoting that keeps YAML from reading it as
a nested list — exists only inside the file.

So the value that comes out is the value that goes back in. This is deliberately
*not* the table-cell situation above: there, the stored escape is what a reader
gets and the caller has to strip it. Here the CLI owns both directions, because
a caller that re-wraps a stem it just read produces `[[[[...]]]]`, and the write
succeeds while the edge silently resolves to nothing.

### The mode flag decides an audit field

`decision write` requires exactly one of `--foreground` or `--background`, and
it has no default. Foreground writes `reviewed: true` — a claim that a human
validated the note as it was written. Background writes `reviewed: false`, which
is what `Decisions.base`'s **Needs review** view queues up. A default here would
write a lie into the audit trail, which is why argparse is made to refuse the
call instead.

## Deployment config is CLI-owned JSON

Machine decisions — adapter enablement, timezone, the executive's person
slug, connector account binding — live in `99-workflow-config/config.json`,
read via `config read`. It is deliberately JSON and deliberately not
frontmatter: nothing about it should be editable from Obsidian's property
panel. Keys starting with `_` are human commentary and are ignored. Null
values are the honest pre-onboarding state and come back in `missing`
rather than failing the read.

`config verify-account` is the binding gate: it takes the raw whoami JSON a
connector returned (Plaud `get_current_user`, M365 `get_me`) and reports
whether the signed-in account matches the adapter's `account_hint`. Only
`match: true` may proceed to listing content. The result never echoes the
connected account's values — a mismatch means those values belong to an
unrelated engagement, and they must not propagate further than the raw
scratch file, which the skill deletes.

Style and narrative (language, recap depth, identity prose) stay in
`99-workflow-config/context/*.md` — judgment, not machine config.

## Interpreter resolution

Never hardcode one interpreter name. Try in order, using the first that
works:

1. `python3` — correct on the Cowork Linux VM and on a developer Mac
2. `python` — the usual name on Windows
3. `py -3` — the Python Launcher, the most reliable invocation on Windows

Why this matters: a clean Mac has no real `python3` (the stub triggers an
Xcode Command Line Tools prompt), and on Windows `python3` frequently
resolves to a Microsoft Store alias that opens the Store instead of running.

## Runtime constraints for `lib/`

- **Stdlib only.** PyYAML's presence in the Cowork VM is unverified. The
  ontology is compiled to `lib/vaultlib/schema.json` by
  `scripts/compile_ontology.py` precisely so nothing parses YAML at runtime.
- **Python 3.10 is the syntax floor.** Cowork ships 3.10; repo CI runs 3.13.
  A 3.11+ construct fails only on the client machine, which is the worst
  place to discover it.
- **The vault root is always a parameter.** Under Cowork it is a VirtioFS
  mount point, not `/Users/...` or `C:\...`.
- **Writes are UTF-8 with `newline="\n"`.** A write from a Windows host must
  not inject CRLF into markdown that syncs to a Mac.

## Surfaces

| Surface | Skills load | Shell | Object writes |
|---|---|---|---|
| Chat + filesystem or Obsidian MCP | no | none | not supported |
| Cowork | yes | Linux VM | yes |
| Claude Code CLI | yes | host OS | yes |

Plugins are not used in Chat, so a skill cannot run there at all. Every
object-writing skill states this in its own body so the user gets an
explanation rather than a silent absence.

## Daily-note regions

`daily-note write` owns the machine half of a daily note. The payload carries
region *content* only — never the `<!-- evening-sync:{region}:begin/end -->`
markers, which the CLI writes and refuses to accept inside content. On an
existing note, region interiors are replaced in place and every byte outside
the markers is preserved exactly; jottings are the user's, permanently. The
region structure must match the payload (one recap; one prep per meeting, or
a single no-meetings prep) — if the meeting set changed since the note was
written, the write fails with a structural-change error instead of guessing,
because by then the note may hold human text that outranks the calendar.
Surface that error; do not delete the note to force a rewrite unless the user
says so.

Matching counts are not enough, so the `### {HH:MM} — {Subject}[ · [[entity]]]`
headings are compared too: they sit *outside* the markers, nothing regenerates
them, and a calendar that swapped one meeting for another between runs would
otherwise file fresh prep under a stale heading. That comparison searches
*upward* from each region rather than reading only the line directly above —
the gap between a heading and its marker belongs to the user, and a blank line
from an Obsidian formatter must not read as "no heading here" and refuse every
run from then on.

`daily-note read` returns the mirror image: `meetings[]` for prep filed under
a `### ` heading, and `meetings_note` for a prep region with no heading above
it (the no-meetings line, or whatever `meetings_note` the last write passed).
Unparseable frontmatter is a warning, not a failure — the jottings the harvest
needs live in the body, so `frontmatter` comes back empty and the run goes on.

## After changing the ontology

```bash
python3 scripts/compile_ontology.py
python3 -m pytest scripts/tests -q
```

The regeneration test fails if `schema.json` is stale. That is the only thing
keeping the runtime contract and the ontology doc in agreement.
