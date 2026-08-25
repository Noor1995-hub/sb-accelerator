# Inbox lifecycle — design

**Issue:** #55 (E2E-3), milestone "fix after first testing round"
**Date:** 2026-08-25 · **Plugin version at design time:** 0.5.0 → ships as 0.6.0
**Baseline:** `ea1aac7` — this design is written **on top of** #54 / PR #62
(connector↔vault binding + `99-workflow-config/config.json`), which the issue
anticipated it would consume.
**Origin:** E2E test 2026-08-24/25, findings F1 (S2), F2 (S2), F10 (S2), F0 (S3).

## Problem

Three defects that read as separate bugs but share one root: `10-inbox/` has
no lifecycle. Files arrive, one skill reads them, and nothing ever says a file
is done.

**F1 — no processed-state, and the check is O(everything).**
`syncjob.known_recording_ids()` parses every `20-meetings/*.md` and
`syncjob.content_id()` SHA-256 hashes every inbox file on every run. Fine at 9
meetings; real cost at 2,000 meetings plus large recorder exports. There is no
way to see, in Obsidian, which inbox files are already processed — and Obsidian
Bases index *notes*, so a `.txt` cannot appear in a Base or carry properties.

**F2/F10 — one consumer, one output type.** `/sync-recordings` is the only
reader of `10-inbox/`, and `meeting write` is its only output. The E2E fixture
`2026-08-21-forwarded-email-meridian-renewal.txt` — an email carrying project
context, not a meeting — was written as `21-08-26-meridian-renewal-terms-heads-up.md`
with `type: status-update`, asserting a meeting that never happened.

**F0 — the README promises a sweep that does not exist.**
`10-inbox/README.md` ships "the assistant sweeps this folder as part of the
daily rhythm" and "nothing lives here". No code moves, archives, or deletes an
inbox file; `/evening-sync` never touches the folder.

## Decisions

Recorded with their reasoning, because each was a live option at design time.

1. **Non-meeting captures go to `20-meetings/`, not to a new folder.** The
   dedup ledger is derived solely from `source-recording-id` in
   `20-meetings/*.md` frontmatter. An item filed to `70-resources/` or
   `80-thoughts-ideas/` leaves no trace and reappears as a candidate on every
   subsequent run, so a second destination means a second ledger. Routing into
   the existing folder also keeps **one triage surface** (`Meetings.base`) and
   inherits `/evening-sync` consumption for free. The ontology already
   anticipated this: `source: email` is an existing enum member and the prose
   already states `recording-duration` is `0` when nothing was recorded.

2. **`type: note` is the honest label — one new enum member, not two.** The
   E2E failure was not the destination, it was `type: status-update` claiming a
   meeting occurred. `type` and `source` are orthogonal axes and both are kept:
   a forwarded email is `type: note` + `source: email`; an emailed *meeting
   summary* is `type: meeting` + `source: email`. A `type: email` member would
   collide confusingly with `source: email` and conflate the two axes.

3. **Three outcomes, and ambiguity resolves toward writing.** Capture-shaped
   items become notes; things that are not captures at all (a whitepaper, a
   deck, a spreadsheet, an image) are **parked**, not filed into
   `70-resources/`. The sync's job is capture, not librarianship. When the
   classification is uncertain, write the `note` rather than park: a wrongly
   written note sits in Triage and is one click from `archived: true`, while a
   wrongly parked file is invisible and on a "never propose again" list. The
   error direction matters more than the error rate.

4. **The sweep dissolves the visibility problem.** If processed *and* parked
   files both move to `90-archive/inbox/`, then `10-inbox/` contains exactly
   the items awaiting processing — the folder itself answers "what is not yet
   processed?", with no index note, no Inbox Base, and no state file. The
   README's "nothing lives here" becomes true rather than aspirational.

5. **Sweep on successful write, not on review-confirm and not after N days.**
   A grace period requires a per-file "when was this processed" timestamp,
   which reintroduces exactly the sync-state file the current design avoids.
   Sweeping only after `reviewed` is ticked leaves the inbox holding two
   different states, so the folder stops answering the question cleanly, and an
   unattended-only deployment never empties it.

6. **The scan cache is a cache, never a ledger.** The vault remains the source
   of truth. The cache is keyed on `(mtime_ns, size)` and is rebuilt silently
   when missing, corrupt, or version-mismatched; deleting it is always safe.
   This preserves the property the `syncjob` docstring was protecting — "a
   failed item wrote nothing and retries naturally" — while removing the
   full-parse cost.

7. **`updatequeue`'s identical full-parse is out of scope.** Different
   subcommand (refresh stage, not scan), different fields, and wiring it in
   widens the blast radius for no acceptance-criterion gain. The cache module
   is written general enough to serve it later.

8. **No new migration, but one addition to the pending list.** Adding an enum
   member and a confidence reason is backward-compatible — no existing note
   becomes non-conformant — and `90-archive/inbox/` and `scan-cache.json` are
   both created on demand. The one thing an already-deployed vault *cannot*
   get by itself is the rewritten `10-inbox/README.md`: it was instantiated
   from the template at provisioning, so a live vault keeps the false "the
   assistant sweeps this folder" promise until something replaces it. Same
   class of problem `config.json` has. Handled the same way #54 handled it —
   appended to the structure-version 2 candidate list in `migrations/README.md`,
   not written as a migration now.

9. **The inbox path stays behind the #54 adapter gate.** `config.json`'s
   `adapters.inbox.enabled` already governs whether `10-inbox/` is read at
   all. Classification and the sweep sit inside that gate: a deployment with
   the inbox adapter disabled scans nothing and therefore sweeps nothing. This
   is correct — sweeping a folder the deployment declared it does not use would
   be the plugin moving files it was told to ignore.

## Design

### 1. Ontology and schema

`template/99-workflow-config/reference/ontology.md`, Meeting block:

- `enums.type` gains `note`.
- `confidence_reasons.calendar` gains `calendar-not-applicable`.

Prose added under the Meeting section:

- `note` is a dated capture that is **not** a record of an interaction —
  forwarded correspondence, a voice memo, pasted context. It lives in
  `20-meetings/` because that folder is the vault's capture ledger, not
  because an email is a meeting.
- A `note` carries `calendar_match: false`, `recording-duration: 0`, and
  **may carry empty `attendees`**. Its `calendar-subject` is a descriptive
  subject drawn from the item itself — a forwarded email's own `Subject:`
  line, a voice memo's short title — and is **never empty**:
  `schema.validate()` rejects `""` for any required field, and the vault
  already treats `calendar-subject` as the subject a capture is filed
  under, with `calendar_match` alone saying whether a calendar
  corroborated it (see the `calendar_match: false` fixtures, which carry
  subjects like `"1:1 — Priya Nathan"`). It is also the Subject column in
  `Meetings.base`, so an empty value would render a blank Triage row.
- `calendar-not-applicable` means the calendar was never consulted *because
  the item is not a meeting*. It is a third distinct fact alongside
  `no-calendar-match` (searched, found nothing) and `calendar-tool-unavailable`
  (could not search). Never collapse the three.

Then regenerate the compiled schema:

```bash
python scripts/compile_ontology.py
```

`plugin/lib/vaultlib/schema.json` is generated, never hand-edited;
`test_compile_ontology.py` fails on staleness.

### 2. `meeting.py` — one relaxation

`plugin/lib/vaultlib/meeting.py:202` currently reads:

```python
attendees = _require_slug_list(payload, "attendees", allow_empty=False)
```

becomes:

```python
attendees = _require_slug_list(
    payload, "attendees", allow_empty=(payload["type"] == "note"))
```

Nothing else in the module changes. `_validate_confidence()` reads its
vocabulary from the compiled schema, so `calendar-not-applicable` is accepted
once the ontology carries it. `calendar-subject` has no non-empty check, so
`""` already validates. `recording-duration: 0` already validates
(`isinstance(int) and >= 0`). Collision guards, the write-time ledger re-check
in `_resolve_target()`, body rendering, and `processed: True` are untouched.

### 3. `syncjob.archive` — the sweep

New function in `plugin/lib/vaultlib/syncjob.py`:

```python
def archive(root: Path, relpath: str, today: str) -> dict
```

- Target: `90-archive/inbox/{YYYY-MM}/{name}`, where `{YYYY-MM}` comes from
  `today` — the run date, passed in. Date arithmetic is never derived inside
  the module (existing house rule: `cli.py dates` is authoritative). `--today`
  is optional and falls back to `vault.today_iso(None)`, the same convention
  `entity write` uses. The bucket is deliberately *not* timezone-aware:
  `config.timezone` can shift a month boundary by hours, and an archive
  folder is a filing convenience, not a fact anything joins on.
- Move via `shutil.move` (stdlib). Same filesystem in practice; `shutil.move`
  degrades to copy+unlink if not.
- Collision: `{stem}-2{suffix}`, incrementing, matching the `-{n}` convention
  `meeting.py` already uses for note stems.
- Refuses to move `README.md` or a dotfile — the same `_IGNORED_NAMES` and
  `startswith(".")` guard `scan()` uses.
- Refuses a `relpath` outside `10-inbox/`, and refuses a path that is not a
  regular file.
- Returns `{"from": "10-inbox/x.txt", "to": "90-archive/inbox/2026-08/x.txt"}`.
- Idempotent in the practical sense: archiving an already-moved file raises a
  clear `SyncError` naming the destination, rather than half-succeeding.

New CLI surface in `plugin/lib/vaultlib/cli.py`, alongside the existing
`sync scan` / `dedup` / `skip` / `reconcile-reviews`:

```
sync archive --vault <path> --path 10-inbox/<name> [--today <ISO>]
```

One JSON object on stdout, per the house rule.

### 4. `scancache.py` — the cost fix

New module `plugin/lib/vaultlib/scancache.py`, roughly 80 lines, stdlib only.
State file: `99-workflow-config/sync-state/scan-cache.json`, beside the
existing `skipped-recordings.txt`.

Shape:

```json
{
  "version": 1,
  "ledger": {
    "20-meetings/10-03-26-meridian-steerco-01.md": {
      "mtime_ns": 1756100000000000000,
      "size": 2841,
      "recording_id": "inbox:9f2c1a...",
      "warning": null
    }
  },
  "inbox": {
    "10-inbox/2026-08-26-voice-memo.txt": {
      "mtime_ns": 1756200000000000000,
      "size": 512000,
      "content_id": "inbox:3b7e44..."
    }
  }
}
```

Behaviour:

- `known_recording_ids()` stats every `20-meetings/*.md` (~5 ms at 2,000
  files), reuses the cached `recording_id` where `(mtime_ns, size)` match,
  parses only new or changed files, and drops entries for deleted files.
- An unparseable meeting caches `recording_id: null` plus its `warning` string,
  which is **replayed** on subsequent runs. Without this, a mangled note is
  re-read on every run and the warning list stays correct only by accident.
- `content_id()` short-circuits on unchanged `(mtime_ns, size)`. This is what
  stops a large recorder export being re-hashed on every run while it sits
  pending across several runs.
- Missing, unreadable, malformed, or `version`-mismatched cache → rebuilt from
  scratch, silently. No warning: a cold cache is a normal state, not a fault.
- Written through `vault.atomic_write`, and only when something changed.

The `syncjob` module docstring currently promises "There is no second state
file to reconcile." It is amended to say the cache is a derived index of the
vault, safe to delete at any time, and never consulted as an authority.

### 5. `/sync-recordings` — classification and reporting

`plugin/skills/sync-recordings/SKILL.md`, as it stands after PR #62. The
**Inbox** paragraph of `### 1. Scan and dedup` (SKILL.md:109–119) is the edit
site, and its closing sentence is the exact prose F0 falsified:

> Report `already_synced` files so the user can archive them (inbox
> discipline: nothing lives there).

That sentence asks the *user* to do a thing the plugin promised to do and
never did. It is replaced by an actual `sync archive` call, not reworded.

Step 1 gains a classification pass over `scan()`'s `candidates`. Read the head
of each file, then choose:

| Shape | Outcome |
|---|---|
| A record of an interaction — transcript, meeting recording, meeting notes | meeting note, existing path, unchanged |
| Carries context about people, projects, or entities but is not a meeting — forwarded correspondence, a voice memo, pasted context | `type: note` capture in `20-meetings/` |
| Not a capture at all — whitepaper, deck, spreadsheet, image, stray binary | **park**: `sync skip --id`, then `sync archive` |

Payload shape for a `type: note`:

- `type: note`, `calendar_match: false`, `recording-duration: 0`, and a
  descriptive non-empty `calendar-subject` taken from the item (an email's
  `Subject:` line, a memo's title)
- `source` is the arrival channel, unchanged semantics (`email` for a
  forwarded mail, `recorder` for a voice memo, `manual` for pasted text)
- `attendees` are the people named in it, resolved through `person ensure` as
  usual; empty is permitted when the item names nobody
- `confidence` carries `calendar-not-applicable` as its calendar reason,
  plus the usual one reason each from the project-link and attendees
  groups. **The rating needs its own rule**, because the existing table
  gates `high` and `medium` on a calendar match a capture can never have —
  left as-is, every capture would be `low` and the `medium` option would be
  dead prose. For a `type: note` the calendar axis is not applicable, so
  the rating comes from the other two axes: **`medium`** when the project
  link is strong (`entity-domain-match`) *and* `all-attendees-known`;
  **`low`** otherwise. `high` is unreachable for a capture by construction
  and that is correct — nothing corroborated it. **A `note` with empty
  `attendees` still carries `all-attendees-known`** — `_validate_confidence()` requires exactly one
  reason from each of the three groups, and with nobody named there is
  nobody unknown. Do not invent a fourth attendees reason for this case;
  the vocabulary stays closed.
- `takeaways` and `debrief` carry the same meaning they always did: what this
  says, and what it means. Both remain required.

Ambiguity rule, written into the skill body: **when unsure between `note` and
park, write the `note`.**

Both modes decide all three outcomes. `--unattended` does not defer — that is
the point of routing captures into the pipeline.

Sweep calls, all after verification against disk:

- after a `meeting write` whose returned `path` exists → `sync archive` the
  source file
- after a `sync skip` → `sync archive`
- for every file `scan()` reports in `already_synced` → `sync archive`, and
  report it as such (a file dropped back in, or a pre-sweep leftover)

The Step 7 summary template gains three lines. Shown against the **post-#62**
block, whose `Adapters:` line already carries the refuse-and-alert vocabulary
and must not be reverted:

````markdown
## Sync Complete
**Processed:** {N} → `20-meetings/` ({stems})
**Captures:** {N} → `20-meetings/` as `type: note` ({stems})
**Parked:** {N} → `90-archive/inbox/` ({filenames, each with why it was not a capture})
**Inbox swept:** {N} files → `90-archive/inbox/{YYYY-MM}/` · {N} left pending in `10-inbox/`
**New people:** {N} created in `50-people/`
**Reviewed ticks folded:** {N} confirmed
**Needs attention:** {N} (would have overwritten confirmed notes)
**Skipped / errors:** {N} (will retry next run)
**Adapters:** inbox ok · plaud ok | REFUSED (account-mismatch | no-account-hint) | disabled | unavailable · m365 disabled | not yet supported
**Calendar enrichment:** ok | UNAVAILABLE
````

`Inbox swept` counts every file moved this run — processed captures and parked
items together — and reports the pending remainder, which is the number the
exec actually cares about. `Parked` itemises its subset separately because a
parked file is a decision, not a throughput number. Together these satisfy the
acceptance criterion that the routing decision is surfaced in the summary.

Two interactions with #62 worth stating so a reviewer does not have to work
them out:

- **Scratch hygiene is unaffected.** Classification reads the head of vault
  files in `10-inbox/`. That is vault content, not connector data, so nothing
  new lands in `$SCRATCH` and the `rm -f` contract line needs no new entry.
- **The contract test bans prose config.** `test_skill_contracts.py` now
  fails any SKILL.md that references `identity.md` or `tools-and-systems`.
  The edits here introduce neither; the new `sync archive` invocation gets
  pinned by the same test in the same way `config read` is.

`/evening-sync` needs no change: stage 3 delegates to `/sync-recordings`
wholesale, so the sweep and the capture routing arrive with it — including the
adapter gating, since a disabled inbox adapter short-circuits before any of it.

### 6. `updatequeue` — the metrics/queue divergence

`plugin/lib/vaultlib/updatequeue.py:70` — `_index_meetings()` globs
`20-meetings/*.md` with no type filter, and its result feeds two different
consumers that must now diverge:

- **Metrics arithmetic** — `meetings-7d`, `meetings-30d` on projects and
  people, and `key-people` — must **exclude** `type: note`. Counting an email
  as a meeting is the quiet kind of falsehood the vault's third golden rule
  forbids, and the metric feeds `Projects.base`.
- **The project-state queue** and its `existingDecisions` projection must
  **include** `type: note`. Feeding the Meridian email into project state and
  decision capture is the reason for this whole design.

Implementation: `_index_meetings()` records `type` on each indexed entry; the
metrics passes filter `entry["type"] != "note"`; the queue pass does not. The
self-check keeps seeing the unfiltered list.

This is the subtlest change in the batch and the one most likely to regress
silently — it gets a dedicated test asserting both halves at once.

### 7. Template, Base, and docs

- `template/20-meetings/Meetings.base` — in the **Triage** view's `order`,
  `type` moves from last to immediately after `date`, so a `note` reads at a
  glance without horizontal scrolling. No new view, no filter change, no new
  property. (A dedicated **Captures** view filtered `type == "note"` is a
  one-row addition to `test_bases_views.py`'s expectation table if triage later
  wants it; deliberately not shipped now.)
- `template/10-inbox/README.md` — rewritten to describe the actual lifecycle:
  drop a file, the sync classifies it, a note is written, the file moves to
  `90-archive/inbox/{YYYY-MM}/`. What remains in `10-inbox/` is what is still
  pending. The claim "the assistant sweeps this folder" becomes accurate.
- `template/90-archive/README.md` — new, short. `90-archive/` is now a
  destination the plugin writes to, so it says what lands there and that
  nothing reads from it.
- `template/CLAUDE.md`, "Inbox Discipline" — one sentence that the inbox is
  swept on processing, so its contents are always the pending set.
- `fixtures/demo-vault/10-inbox/` — the Meridian email stays as the reference
  case for the `type: note` branch. One non-capture fixture is added so the
  park branch is demonstrable in the demo vault.
- `migrations/README.md` — append to the structure-version 2 candidate list:
  refresh `10-inbox/README.md` and add `90-archive/README.md` in already-
  provisioned vaults. Per decision 8, noted as a candidate, not written now.
- `plugin/.claude-plugin/plugin.json` — `0.5.0` → `0.6.0` (new behaviour, not
  a fix; #54 already took `0.5.0`).
- `CHANGELOG.md` — one line under `Unreleased`, client-facing: the inbox now
  empties itself, and context that is not a meeting is captured honestly
  instead of being filed as one.

## Testing

| File | Adds |
|---|---|
| `scripts/tests/test_vaultlib_syncjob.py` | `archive()` moves to the right `{YYYY-MM}`; collision suffixing; `README.md` and dotfiles refused; paths outside `10-inbox/` refused; archiving an already-moved file errors clearly. Cache: cold build, warm hit, `(mtime_ns, size)` change forces a re-parse, deleted file drops from cache, corrupt/version-mismatched cache rebuilds silently, unparseable-meeting warning is replayed from cache. |
| `scripts/tests/test_vaultlib_syncjob.py` (perf) | Synthetic 2,000-meeting vault: the second `scan()` reads at most a small constant number of files. Asserted by counting file reads (monkeypatched `Path.read_text`), **not** wall-clock — timing assertions are flaky in CI. |
| `scripts/tests/test_vaultlib_meeting.py` | `type: note` accepted; empty `attendees` accepted for `note` and still refused for every other type; `calendar-not-applicable` accepted in `confidence-reasons`. |
| `scripts/tests/test_vaultlib_updatequeue.py` | A `type: note` note does **not** move `meetings-7d` / `meetings-30d` / `key-people`, and **does** put its project on the state queue. Both halves in one test, so a future refactor cannot satisfy one and drop the other. |
| `scripts/tests/test_vaultlib_cli.py` | `sync archive` argument surface and JSON output. |
| `scripts/tests/test_compile_ontology.py` | Passes with the regenerated `schema.json` (staleness guard). |
| `scripts/tests/test_bases_views.py` | Passes with the reordered Triage columns. |
| `scripts/tests/test_skill_contracts.py` | The new `sync archive` invocation in `SKILL.md` matches the CLI, and the #62 ban on `identity.md` / `tools-and-systems` references still passes. |
| `scripts/tests/test_validate_template.py` | Passes unchanged — `check_config()`'s pins are untouched by this work. |
| `scripts/tests/test_fixtures_ontology.py` | Passes with the new inbox fixture. |

Local gate, the same three things CI runs:

```bash
python scripts/lint_plugin.py
python scripts/validate_template.py
python -m pytest scripts/tests -q
```

## Acceptance, mapped

| Issue criterion | Satisfied by |
|---|---|
| A user can answer "what in my inbox is not yet processed?" in Obsidian without running anything | §3 — the sweep makes `10-inbox/` contain exactly the pending set; the folder is the view |
| Scan cost no longer re-hashes/re-parses the world on every run (measured on a synthetic 2k-meeting vault) | §4 — `scancache.py`, with the 2k-vault read-count test |
| A non-meeting inbox item ends up somewhere defensible, with the routing decision surfaced in the sync summary | §1, §2, §5 — `type: note` in `20-meetings/`, three-outcome classification, three new summary lines |
| README describes only behavior that exists | §7 — `10-inbox/README.md` rewritten against the implemented sweep |

## Out of scope

- `updatequeue`'s own full-parse cost (decision 7).
- Routing anything into `70-resources/` or `80-thoughts-ideas/` (decision 3).
  Those folders stay unwritten-to by any skill.
- A **Captures** view in `Meetings.base` (§7).
- The `m365` adapter, still without a producer.
- Re-syncing an edited inbox file. Ids are content-hashed, so editing a file
  mints a new id and it re-syncs as a new item. Archiving does not change this
  — an archived file keeps its hash and stays deduped. Called out here because
  it surprised a reader of the issue, not because this design alters it.
