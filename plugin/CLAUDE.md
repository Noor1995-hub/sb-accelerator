# Plugin internals

Instructions for working *on* this plugin. Not shipped guidance for the
vault owner — that lives in the vault's own `CLAUDE.md`. Excluded from the
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

A raw `|` a human typed straight into a cell in Obsidian is repaired on the
next write — re-joined into the column it belongs to, stored escaped — and
reported in the result's `repairs` list.

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

### A park cannot be reasonless, by argparse

`sync park` is the only way an inbox file gets suppressed, and `--reason` is
required with no default. Parking is two writes that must not come apart —
the file leaves `10-inbox/`, its content hash joins the never-propose-again
list — and neither is legible later without the reason. The earlier shape
(`sync skip` then `sync archive`) let both happen with nothing recorded, so
the vault owner found a bare file in `90-archive/inbox/` and a bare hash in
the skip list with no way to tell a deliberate call from a mistake. `sync
skip` keeps an *optional* `--reason` for adapter ids (`plaud:`, `m365:`),
which have no inbox file to move.

The reason is written in two places on purpose, because the readers differ:
`skipped-recordings.txt` answers "what has this vault suppressed, and why?",
and the `{filename}.parked.md` sidecar answers "why is this file in my
archive?" for someone browsing the folder who will never open a config
directory. The sidecar carries no frontmatter — it explains a file, it is not
a vault object, and no ontology check should ever try to validate it.

The skip list is `id[\treason[\tfilename]]`, and a bare id line stays valid
forever: that is all the format held before reasons were recorded, so every
already-deployed vault reads correctly with nothing to migrate. Trailing
empty fields are omitted rather than written as bare tabs, whitespace inside
a reason is collapsed (a tab would invent a field, a newline a record), and
`read_skip_list()` returns the id set from either line shape — that contract
is what `scan()` and `dedup()` filter against and it does not change.
Re-parking an id already on the list annotates a bare line in place, but
never revises a reason already recorded: the first explanation is the one a
human would have read. That run's sidecar carries the recorded reason too,
not the one it was called with — otherwise the list would say why an item was
parked in August while a September sidecar for the same id asserted something
else, and the vault would be telling two stories about one decision. The
sidecar says which of the three cases it is, because a re-park of an id
suppressed before reasons existed writes a reason that is genuinely new.

### Recording ids are compared in canonical form

Plaud listed a recording as its bare 32-hex hash until 2026-09-15 and as
`of_<hex>` from then on; the bare form now 404s on every Plaud endpoint.
Both spell one recording, and an exact-match ledger wrote it twice. Every
id comparison and every write — `known_recording_ids`, the skip list,
`sync dedup`, `meeting write`, `plaud reassemble` — goes through
`syncjob.canonical_id()`, which strips that prefix for the `plaud`
namespace only. Stored ids converge on the bare hash (what every deployed
vault already holds); `sync dedup` answers in the caller's own spelling so
the orchestrator can match `new` ids back to listing entries. The `of_` id
the connector emitted stays in the scratch meta file and the blob filename
— that is what `get_transcript` needs, and it is never reconstructed from
the stored form.

### The mode flag decides an audit field

`decision write` requires exactly one of `--foreground` or `--background`, and
it has no default. Foreground writes `reviewed: true` — a claim that a human
validated the note as it was written. Background writes `reviewed: false`, which
is what `Decisions.base`'s **To review** view queues up. A default here would
write a lie into the audit trail, which is why argparse is made to refuse the
call instead.

## Deployment config is CLI-owned JSON

Machine decisions — adapter enablement, timezone, the vault owner's person
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

`${CLAUDE_PLUGIN_ROOT}` is substituted inline into skill text at load time;
it is exported to the environment only for hook subprocesses, so
`echo $CLAUDE_PLUGIN_ROOT` in a skill's Bash is empty by design (source:
code.claude.com/docs/en/plugins.md).

## Surfaces

| Surface | Skills load | Shell | Object writes |
|---|---|---|---|
| Chat + filesystem or Obsidian MCP | no | none | not supported |
| Cowork | yes | Linux VM | yes |
| Cowork cloud session ("Run new tasks in the cloud") | yes | Anthropic sandbox | not supported — the vault is not a filesystem there |
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

Two payload forms are accepted. **v1** — `recap` and every `prep` are
Markdown strings — renders byte-identically to earlier versions (pinned by
test). **v2** — `recap` is an object (`recap.validate`/`render`) and every
`prep` is `{attendees, last_meeting, context}` — renders the recap as
callouts and a pulse table, and each meeting as `### heading` → `#### Prep`
(region) → `#### Your notes` → `#### Your to do's` (`#### Notes`/`#### Actions`
before 0.12.11; the reader goes by position, so both read). A fresh note
opens with the static `REVIEW_BLOCK` callout above `## Recap` (#238), which
the reader skips. Mixing prep forms in one payload
is refused. A v2 payload merges into a v1 note (regions only; the
sub-headings are never retro-fitted), and headings are compared as
`(time, subject, entity)` so the v1 `· [[slug]]` and v2 `· [[path|Name]]`
forms match. A v1 recap that opens with a `Catch-up note` callout has it
stripped with a warning — the CLI writes the banner. `daily-note read`
returns `notes[]` and `actions[] = {text, done}` per meeting; `jottings[]`
is their union for older callers.

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

Region markers may carry CLI-owned `key=value` attributes, and exactly one
is defined: `<!-- evening-sync:recap:begin inputs=<16 hex> -->`. That digest
fingerprints what the recap region's machine-generated content is composed
*from* — the catch-up banner the CLI renders, the window's meeting notes,
the daily notes holding its jottings, and any decision notes written inside
it. The banner enters as its rendered text, not as the raw window bounds: a
Saturday run over an untouched vault has a wider window than Friday's but
the same banner and the same files, and hashing the bounds made that look
like a change and regenerated a recap the vault owner had already read. Hashing
the rendered banner also brings `detailed_from` inside the digest, which
the bounds did not cover. `daily-note write` recomputes it whenever the
payload carries `recap_window`, and when it matches the stamp already on the
note the recap region is skipped outright: bytes untouched,
`recap_skipped: true`, prep regions still merged. That is what stops a
re-run replacing a recap the vault owner already read with a
differently-worded, occasionally worse one.

What the stamp does **not** cover is project indexes, and the recap does
read from them (the recap's `pulse` text is composed by the model from each
project's *Where it stands* card). The tradeoff is deliberate: stage 4
touches `last-updated` on every project it visits, so hashing the indexes
would churn the digest on essentially every run and the guard would never
fire. So read the stamp as *"the window's meetings, jottings and decisions
are unchanged"*, not *"nothing anywhere changed"*. The visible consequence:
a re-run whose stage 4 rewrote a project index but wrote no new decision —
a valid outcome — skips the recap, leaving project pulse one revision
behind. A guard that holds beats a guard that covers everything and fires
always.

The stamp lives on the marker line rather than in frontmatter (which a merge
may never touch) or a sidecar file (which the design rules out), and a
payload with no `recap_window` *strips* any stamp it finds — leaving one
above a recap whose inputs nobody verified would make the marker lie, and a
lying stamp causes a skip, which is the one failure mode that silently does
nothing. An unknown attribute is an error, not an ignore: guessing at a
marker is how a note gets mis-merged.

### Wikilinks in region content resolve, or the write fails

Every `[[target]]` in a `daily-note write` payload — recap, prep,
`meetings_note` — must resolve to a vault object: an entity dossier, a
person note, a project index, a meeting note, a decision note, or a daily
note. `#heading` is stripped first; embeds count.

**Resolving here is not the same as resolving in Obsidian.** This check asks
whether the object exists where the vault's layout puts it. Obsidian resolves
a `[[link]]` by note name, and two of these kinds are folders — an entity is
`<slug>/dossier.md`, a project is `<slug>/index.md` — so
`[[acme-industries]]` passes this check and still renders as an unresolved
link in the app. That is vault layout, it predates this rule, and it is
tracked separately; what the rule buys is that the *name* was looked up,
which is the failure it exists to stop. People, meetings, decisions and daily
notes are single notes and resolve in both senses.

Where the link carries an alias and the target is an *identity* object
(entity, person, project), the alias must equal that object's `entity-name`
/ `person-name` / `project-name` exactly, and the error names the real one
so a caller can fix it without a second lookup. Meetings, decisions and
daily notes must resolve but their aliases are free prose — "Friday's Acme
sync" is a reference, not a claim about what something is called.

This is the same boundary lesson as the two above it. There, a caller that
re-sends what it read corrupts the value; here, a caller that writes a name
it *remembers* instead of one it looked up publishes a plausible fiction
into the vault owner's daily note. An unreadable dossier is a warning rather
than a refusal: one mangled file must not cost the vault owner their note.

### Project index body is CLI-rendered

`project state write` replaces everything between the `# {name}` heading and
the end of `## Background` with a rendering of the JSON state it is given —
skills and subagents never hand-edit a project index. A trailing `## Notes`
section, if the note has one, is preserved verbatim: that is the one part of
the body that belongs to the owner. The call also stamps `last-updated` and
`state-updated` itself, so it calls `project touch` internally — a caller
never runs `project touch` separately after a `state write`.

## After changing the ontology

```bash
python3 scripts/compile_ontology.py
python3 -m pytest scripts/tests -q
```

The regeneration test fails if `schema.json` is stale. That is the only thing
keeping the runtime contract and the ontology doc in agreement.
