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

## After changing the ontology

```bash
python3 scripts/compile_ontology.py
python3 -m pytest scripts/tests -q
```

The regeneration test fails if `schema.json` is stale. That is the only thing
keeping the runtime contract and the ontology doc in agreement.
