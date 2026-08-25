# Deployment config + connector↔vault binding — design

**Issue:** #54 (E2E-2, S1) · **Date:** 2026-08-25 · **Status:** implemented via
`docs/superpowers/plans/2026-08-25-deployment-config.md`

## Problem

The 2026-08-24/25 E2E test surfaced an S1: `/sync-recordings` in a fictional
demo vault called the user-level Plaud MCP and received ~110 recordings from a
real, unrelated delaware engagement as sync candidates. Per-run model judgment
caught it, but nothing *binds* a connector account to a vault, `--unattended`
has no human to flag to, and raw connector JSON persists in session scratch
after a run against the wrong account. Separately, machine decisions (adapter
enablement, timezone, executive person slug) are read from prose context
files, which is non-deterministic and unbindable.

## Decision summary

One CLI-owned JSON config per vault, a deterministic account-verification
gate that runs *before any content is listed*, and a scratch-hygiene rule in
both sync skills. Skills stop reading machine decisions from prose.

## The config file

`99-workflow-config/config.json`, shipped in the template as a commented-by-
convention default:

```json
{
  "_readme": [
    "Machine-read deployment config — owned by the CLI and /setup-my-brain.",
    "Edit as text (never via Obsidian's property panel; this is not frontmatter).",
    "account_hint: an identifier (email preferred) of the connector account",
    "that IS this vault's account. A connector whose signed-in account does",
    "not match its hint is refused before any content is listed."
  ],
  "config-version": 1,
  "timezone": null,
  "executive": null,
  "adapters": {
    "inbox": {"enabled": true},
    "plaud": {"enabled": false, "account_hint": null},
    "m365": {"enabled": false, "account_hint": null}
  }
}
```

- **JSON, not YAML** — stdlib-only runtime (plugin `CLAUDE.md`); PyYAML is
  unverified in the Cowork VM. JSON has no comments, so a `_readme` string
  array carries the human explanation; the reader ignores every key starting
  with `_`.
- **Not frontmatter** — deliberately outside Obsidian's property panel, which
  is the frontmatter-corruption surface of #53.
- `timezone` is an IANA name or null. Structural validation only — resolution
  stays with `dates`/`plaud` subcommands, which already own the
  `--utc-offset` fallback for hosts without tzdata.
- `executive` is the executive's **person slug** (the join key
  `sync update-queue` already takes), or null before onboarding.
- `inbox` has no account, hence no hint. `plaud`/`m365` are connector
  adapters: `enabled` + `account_hint`. One `m365` entry governs both
  calendar *enrichment* (implemented) and mail/calendar *retrieval* (still a
  stub) — the binding requirement is identical, and finding G6 showed
  enrichment needs it too.
- `config-version` gates future shape changes; readers reject a version they
  do not know.
- Null values are a valid, honest pre-onboarding state — `config read`
  reports them as `missing`, it does not fail. `/setup-my-brain` (#3) becomes
  the writer of real values; until it exists, the consultant edits the file
  as text. A fictional-vault test binds the real account by writing that
  account into `account_hint` — a conscious act, exactly as the acceptance
  criteria require.

## CLI: new `config` group (`vaultlib/config.py`)

### `config read --vault V`

Returns the parsed config plus a completeness report:

```json
{"ok": true, "result": {"config": {...}, "missing": ["timezone", "adapters.plaud.account_hint"]}}
```

- Missing file → `ok: false` with a hint naming the template default (the
  file is a structure-version 2 candidate; pre-config vaults are regenerated
  or get the default copied in).
- Malformed JSON, wrong types, unknown adapter keys, or an unknown
  `config-version` → `ok: false` naming the exact violation. Strict on shape:
  a typo'd key must fail loudly, not silently disable a guard.
- `missing` lists nulls among `timezone`, `executive`, and `account_hint`
  for every *enabled* connector adapter.

### `config verify-account --vault V --adapter plaud|m365 --identity FILE|-`

The deterministic binding gate. `--identity` is the raw JSON the connector's
whoami tool returned (`mcp__plaud__get_current_user`, M365 `get_me`), written
to scratch and passed as a file — never echoed through Bash.

Match rule: collect every string scalar in the identity JSON (recursive,
shape-agnostic — neither connector's response shape is a contract we own),
casefold and strip both sides, then:

- hint equals a value → match;
- hint contains `@` and appears as a substring of a value → match (an email
  is specific enough that substring cannot false-positive; bare names are
  not, so they get exact-match only).

Result never echoes the connected account's values (they are exactly the
engagement-sensitive data this feature exists to contain):

```json
{"ok": true, "result": {"match": false, "reason": "account-mismatch", "values_checked": 12}}
```

`reason` ∈ `matched` · `account-mismatch` · `no-account-hint` (enabled but
unbound — the original hazard, refused) · `adapter-disabled`. Only
`match: true` lets a skill proceed. An unreadable/empty identity payload is
an error, not a mismatch — "could not check" must not report as "checked".

**Hint shape rule** (added after E2E round 2, 2026-08-25): a hint with no
`@` and no digit is rejected at `config read` time as a display name.
Plaud's whoami carries `nickname` as a string scalar, and for Apple/Google
sign-ins its `email` is a synthetic `…@plaud.ai` address — the email the
user signed up with never appears. So hints must be copied verbatim from
the connector's whoami (Plaud: `id` or `email`; M365: `mail` or
`userPrincipalName`), and a name like "Michael" — which would exact-match
any account with that nickname — fails loudly at bind time instead of
false-accepting at sync time.

## Skill changes

**`/sync-recordings`**
- Step 0 becomes `config read`; the adapter table is driven by
  `adapters.*.enabled` instead of `tools-and-systems.md` prose. Declared-but-
  unavailable stays an explicit skip line.
- Plaud: before `list_files`, call `get_current_user`, write raw JSON to
  scratch, run `config verify-account`. `match: false` → the adapter is
  **refused, in both modes** — never sync; interactive tells the user how to
  bind (edit `account_hint`), unattended writes a refuse-and-alert line in
  the summary. Nothing is listed on a refusal.
- Calendar enrichment: gated the same way via `get_me` against
  `adapters.m365`. Refusal or disabled stamps `calendar-tool-unavailable`
  (semantically exact: the calendar was never consulted — no ontology
  vocabulary change) and the summary carries the explicit cause line.
- Timezone comes from config (`plaud reassemble`, `dates window`).
- **Scratch hygiene rule:** raw connector JSON in scratch is engagement data.
  Delete it at the end of the run; on an account-mismatch refusal, delete the
  identity payload immediately. (Mismatch refusal happens before listing, so
  no listing ever reaches disk.)

**`/evening-sync`**
- Stage 1 reads timezone and the executive slug from `config read` — no more
  identity-prose parsing and name→slug resolution.
- Stage 5 calendar pull is gated by the same m365 verification.
- Same scratch-hygiene rule.

**`/new-project`**
- Owner default resolves from `config.executive` (a slug, used directly).
  Null → ask the user (interactive skill). `identity show` stays in the CLI
  for prose context but is no longer the machine path for the owner default.

Language/depth of recap prose stays in
`preferences-and-constraints.md` — style is judgment, not machine config.
`tools-and-systems.md` keeps its narrative role; a one-line note points
machine enablement at `config.json`.

## Template, validation, migration

- Template ships the default `config.json` above.
- `validate_template.py` gains a check: file exists, parses, carries
  `config-version: 1`, the three adapters with correct shapes, `inbox`
  enabled, connectors disabled with null hints (the safe shipping state).
- `migrations/README.md` adds `99-workflow-config/config.json` to the
  structure-version 2 candidate list (migration format still pending
  /upgrade-vault, per existing policy).

## Testing

- `scripts/tests/test_vaultlib_config.py`: read validation matrix (missing
  file, bad JSON, wrong types, unknown version, missing-list correctness)
  and the verify-account matrix (exact match, casefold, email substring,
  bare-name substring rejected, mismatch, no hint, disabled adapter, nested
  shapes, non-string scalars, empty payload → error).
- CLI envelope tests for both subcommands in `test_vaultlib_cli.py` style.
- `test_validate_template.py` / `test_template_config.py` coverage for the
  shipped default.
- Skill-contract tests: sync skills must name `config read` and
  `config verify-account`; no `SKILL.md` may instruct reading timezone or
  adapter enablement from `identity.md`/`tools-and-systems.md`.

## Acceptance (from #54)

1. No skill reads timezone/exec-slug/adapter enablement from prose. ✅ skill
   rewrites + contract tests.
2. Mismatched connector account refused deterministically (tested); unattended
   alerts instead of syncing. ✅ `verify-account` + skill rules + unit tests.
3. Fictional-vault testing works by pointing `account_hint` at the real
   account explicitly. ✅ null-by-default hints; binding is an edit.
4. Template ships a commented default config; `validate_template.py` checks
   it. ✅ `_readme` convention + validator check.

## Alternatives considered

- **Config in markdown frontmatter** — rejected by the issue itself (#53
  corruption surface).
- **Per-adapter enum in the ontology for the mismatch reason** — rejected:
  `calendar-tool-unavailable` already means "never consulted", and widening a
  closed vocabulary for a cause the summary line carries anyway is blast
  radius without payoff.
- **Model extracts the account string, CLI compares** — rejected: keeps
  judgment inside the gate. Shape-agnostic scalar scan keeps the whole gate
  deterministic.
- **`config write` subcommand now** — deferred to #3 (/setup-my-brain), the
  actual writer. Until then the file is edited as text; nothing round-trips
  it, so the corruption class from #53 does not apply.
