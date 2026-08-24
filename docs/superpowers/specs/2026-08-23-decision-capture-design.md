# Decision Capture — Design (P1b)

**Date:** 2026-08-23 · **Parent issue:** #2 · **Closes:** #20, #36 ·
**Provenance:** `busdev@ccc27b8`

Lands the decision-note **pattern** (#20) and its **producer**, `/log-decision`
(#36). Second of the three PRs scoped in
`2026-08-23-object-skills-port-design.md` — read that first; its §D3 is the
brief this spec resolves, its architecture (the model decides, the script
writes) is the architecture here, and its runtime rules (stdlib only, Python
3.10 floor, vault root as a parameter, LF + UTF-8) apply unchanged.

P2 (the daily loop, #14/#15/#16) consumes this. Its design
(`2026-08-23-daily-loop-port-design.md`, branch
`claude/daily-loop-skill-ports-d83122`) commits to two things this spec must
honour: the evening run "hands decision candidates (from meetings AND harvest)
to `/log-decision` background mode", and there is **no sidecar JSON** — the
engine renders what the call returned, in the same run. So background mode's
return value is an interface, not a courtesy.

## What #20 asked for, and what was already there

#20 is a pattern port by its own definition: ontology §Decision, the note
template, the supersession procedure, `Decisions.base`. P1a already shipped the
§Decision yaml block and gave `Decisions.base` its `file.inFolder("30-projects")`
filter. What is left is the part that was never written down — only demonstrated
in fixtures — plus the `tags` removal decided in P1a (decision 6).

## Decisions

1. **The audit marker is a queryable frontmatter field: `reviewed`.**
   #36 requires background writes to carry "a marker for later audit". An HTML
   comment in the body (the dossier's `<!-- unvalidated -->` convention) is
   invisible to every `.base` view, which makes the audit unperformable — nobody
   finds the notes that need checking. Meeting already solves this exact problem
   with a `reviewed` boolean triaged in `Meetings.base`; Decision reuses it,
   verbatim, and `Decisions.base` gains a **Needs review** view. Obsidian renders
   a boolean property as a one-click checkbox, so clearing the marker is the
   gesture the EA already knows.

   It lands in `keys_present`, not `optional`. `keys_present` is the ontology's
   existing device for "the key must exist even when the value is empty"
   (Person's `relationship`). With `optional`, absence becomes a third state
   whose meaning depends on how Obsidian Bases compares a missing property to
   `false` — semantics this repo cannot verify from source. Making the key
   mandatory removes the question: every decision note says, in one field,
   whether a human has looked at it.

2. **The mode is one word, end to end: `foreground` | `background`.**
   `/log-decision --background` and
   `cli.py decision write … --background` are the same flag name, and
   `--foreground` is its required counterpart (mutually exclusive, no default —
   a caller must state which, because the wrong default writes a lie into the
   audit field). Foreground → `reviewed: true`; background → `reviewed: false`.

   One vocabulary, because two names for one concept is the cognitive shape of
   the defect class this PR is guarding against. P2's `/sync-recordings
   --unattended` is a different skill's flag for a different job; noted, not
   unified here.

3. **Wikilink syntax never crosses the CLI boundary.**
   `supersedes` and `source` are passed in and returned as **bare note stems**
   (`2026-03-10-phased-regional-rollout-adopted`). The `[[…]]` wrapping and the
   surrounding quotes exist only inside the file.

   This is the direct countermeasure to P1a's signature defect — a value
   transformed on write, then matched on read by a pattern blind to the
   transformation (see `plugin/CLAUDE.md` on pipe-escaped table cells, and
   follow-ups #40–#42). A wikilink is the same shape: wrap on write, and any
   reader that hands the stored form back gets `[[[[…]]]]`. The fix is not
   documentation — it is that **the value that comes out is the value that goes
   back in**. `decision list` unwraps; `decision write` normalizes its input
   (strips `[[…]]`, a trailing `.md`, an `|alias` tail) to the same canonical
   stem before either resolving a path or emitting frontmatter. One
   transformation, one place.

   Quoting those two fields is a correctness requirement, not house style: an
   unquoted `supersedes: [[x]]` is a nested YAML list. PyYAML reads `[['x']]`;
   this repo's stdlib parser reads the string `"[x]"`. That is a silent
   divergence between the two parsers the design deliberately keeps in
   agreement, so both fields join `DECISION_QUOTE_KEYS`, guarded by a test that
   re-parses real CLI output with PyYAML and asserts a `str`.

4. **Supersession is one operation with three deterministic effects.**
   The new note carries `supersedes: "[[prior-stem]]"`; the prior note's
   `status` flips to `superseded`; the prior note gains an appended footer:

   ```
   **Superseded** — 2026-05-20 · replaced by [[2026-05-20-single-vendor-strategy-adopted]].
   ```

   The CLI never rewrites the prior note's prose — the footer is append-only,
   which is the vault's "never remove existing content" rule made mechanical.
   The footer exists because the forward edge alone leaves a reader of the old
   note with no way to see what replaced it without running a query.

   Preconditions are all checked **before any write**: the prior note exists in
   *this project's* `decisions/` folder, its status is `active`, and its
   `status:` line is actually replaceable. Then the new note is written, then the
   flip. That order is deliberate — a failed flip leaves a recoverable one-sided
   edge that the result reports honestly, whereas flipping first and failing to
   write leaves a superseded decision with no successor, which no reader can
   diagnose.

5. **Refuse to write a note directly as `superseded`.** It is a consequence of
   another note's write, never an initial state. `active` (the default) and
   `withdrawn` are writable — the withdrawn-on-day-one case is real and already
   in the fixtures.

   Equally, refuse to supersede a note that is not `active`. A `superseded` or
   `withdrawn` decision was not in force, so replacing it is a category error —
   and in practice this is what a stale or mistyped stem looks like. It also
   makes "supersede the same decision twice" impossible.

6. **One decision per `decision write` call — not a batch.** A batch whose
   third entry fails leaves a half-applied state the caller has to reason
   about, and it invites intra-batch supersession ordering. Per-call writes make
   every failure locally attributable and every result directly renderable,
   which is what P2's no-sidecar decision needs. Volume is 0–3 decisions per
   project per day; the loop is free.

7. **The filename slug comes from a short `title`, not from `summary`.**
   `summary` is a full sentence — it is the Decision column in
   `Decisions.base`. Slugifying it yields a 60-character truncation of prose
   (`consolidate-on-a-single-automation-vendor-across-all-three`). The model
   supplies both: `title` for the filename, `summary` for the field. Naming is
   judgment, which is where the division of labour puts it.

8. **`source` resolves against `20-meetings/`, or is omitted.** The ontology
   types the edge as `[[meeting]]`, and a `source` pointing at nothing is a
   silent data-quality defect, so the CLI verifies the target exists. The
   consequence is deliberate and worth stating plainly: for the other three
   inputs #36 names — an inbox transcript, a pasted paragraph, dictation —
   `source` stays empty and the provenance goes in the `why` prose. Widening
   the edge to any vault note is an ontology change plus a `Decisions.base`
   column change; parked, and flagged to P2, whose harvested-jotting candidates
   land in exactly this case.

9. **Decision bodies keep bold markers, so no `body_sections`.**
   `**Decision**` / `**Why**` / `**Implications**` are not H2s, so the H2
   conformance guard does not apply; the guard checks the `**Decision**` marker
   instead. Body prose is collapsed to one paragraph per marker and wrapped at
   76 columns — the shape every fixture and template file in this repo already
   has, and a plain-text editor is where these get hand-edited. The SKILL says
   one paragraph per marker, so a list sent in a body field predictably becomes
   one paragraph rather than triggering a second code path.

10. **No `decision withdraw` subcommand.** Writing a note with
    `status: withdrawn` covers the case the fixtures show. Flipping an existing
    *active* decision to withdrawn is a real operation and a plausible next
    skill, but it is not in #36 and it is not needed by #16. Parked.

## The CLI

Two subcommands, alongside `identity` / `person` / `project` / `entity`:

| Subcommand | Owns |
|---|---|
| `decision list --vault V --project SLUG` | Every decision on a project as JSON: stem, path, date, status, summary, `supersedes`/`source` as **bare stems**, `reviewed`. Sorted newest first; a project with no `decisions/` folder yet returns an empty list rather than an error. An unparseable note is reported as an entry carrying `unreadable`, never an exception — one hand-mangled file must not make the skill unusable on that project. |
| `decision write --vault V --project SLUG [--date D] --note FILE (--foreground \| --background)` | Derive the filename from `--date` + `title`, refuse a case-insensitive collision, validate the payload and the frontmatter against the compiled schema, render the body, write, and apply both sides of a supersession edge. Both subcommands refuse a project with no `30-projects/{slug}/index.md`, naming `/new-project` in the hint. |

`--note` takes a path or `-` for stdin, exactly like `entity write --edits`, and
for the same reason: prose passed as shell arguments loses apostrophes and em
dashes. Scalars stay flags (`--project`, `--date`); content goes in the payload.

```json
{
  "title": "single vendor strategy adopted",
  "summary": "Consolidate on a single automation vendor across all three yards to simplify integration and reduce total cost of ownership.",
  "decision": "Consolidate on a single automation vendor across all three yards.",
  "why": "Running three vendors' PLC and control software in parallel was creating integration overhead that outweighed the site-pacing benefit of the phased approach.",
  "implications": "The Phase 0 pilot vendor stays for yard 1; yards 2-3 re-scope onto the same platform, pushing final commissioning out roughly six weeks.",
  "status": "active",
  "source": "20-05-26-meridian-vendor-strategy-brainstorm",
  "supersedes": "2026-03-10-phased-regional-rollout-adopted"
}
```

`title`, `summary`, `decision`, `why`, `implications` are required; `status`
(default `active`), `source`, `supersedes` are optional. An unknown key is
refused rather than ignored — a typo'd `implication` that silently dropped a
paragraph is the kind of failure nobody notices until a client reads the note.

The result names both sides of what happened, so a caller can render it without
re-reading the vault:

```json
{"ok": true, "result": {
  "stem": "2026-05-20-single-vendor-strategy-adopted",
  "path": "30-projects/…/decisions/2026-05-20-single-vendor-strategy-adopted.md",
  "project": "meridian-yard-automation-program",
  "date": "2026-05-20", "status": "active", "reviewed": true,
  "supersession": {"stem": "2026-03-10-phased-regional-rollout-adopted",
                   "path": "30-projects/…/decisions/2026-03-10-….md",
                   "status_flipped": true, "footer_added": true}}}
```

`supersession` is `null` when there is no edge.

Frontmatter key order, matching the fixtures with `reviewed` appended:
`type · project · date · status · summary · supersedes · source · reviewed`.
Quoted: `summary`, `supersedes`, `source`.

## `/log-decision`

```
/log-decision                              # ask which project, then which source
/log-decision meridian-yard-automation-program
/log-decision <project> --background       # no prompts; called by the evening run
```

**Foreground.** Identify the project → read the source (pasted text, a file, or
a spoken description) → `decision list` to see what is already recorded →
extract candidates → present each one and let the user confirm, edit or drop it
→ `decision write --foreground` per accepted candidate → summarise, including
what was deliberately not recorded.

**Background.** The same extraction with no prompts, applied more
conservatively, then `decision write --background`. Two rules carried from the
lab's production experience, both recorded in P2's design as the failures they
came from:

- **Never block on a prompt.** An unattended run that asks a question exits
  having done nothing. Ambiguity means skip and report, never ask.
- **Verify against disk, not the run's own narrative.** A lab sync once
  reported "Processed: 0" while having correctly written a meeting note. The
  summary is built from what `decision write` returned and what is on disk.

**The material-decision test**, shared by both modes and the thing that keeps
the decision log worth reading: a candidate qualifies only if it **commits the
engagement** *and* **would change a stakeholder's behaviour**. A task, an
opinion, a scheduling choice, a preference, or a restatement of a decision
already in `decision list` is not a decision. Writing nothing is a valid
outcome and the skill says so — a fabricated entry to justify the invocation is
the failure mode.

**Supersession only on explicit conflict.** A new decision supersedes a prior
one when the source says it replaces it, not when the model judges them
inconsistent. Absent that, both notes stay `active` and the summary flags the
tension for a human.

**`--date` is the date the decision was made**, read out of the source — a
steerco on the 12th logged on the 14th is dated the 12th. Today is the fallback,
not the default answer, because the date is what orders the decision log and
what a reader uses to reconstruct a sequence.

## Ontology and template

`template/99-workflow-config/reference/ontology.md`, §Decision:

- `optional: [supersedes, source]` — `tags` removed (P1a decision 6).
- the `tags:` vocabulary block removed.
- `keys_present: [reviewed]` added.
- the note template added as a fenced block.
- the supersession procedure written down — three effects, both sides,
  preconditions, never delete.
- a body-structure statement: bold markers, not H2s; hence no `body_sections`.
- `source` documented as resolving to a note in `20-meetings/`.

Recompiled to `plugin/lib/vaultlib/schema.json` by `scripts/compile_ontology.py`
(CI has a freshness check). `"tags"` also leaves `CARRIED_KEYS` there: with no
block using it, it is a key that compiles into the runtime schema and affects
nothing, which is the silent-divergence shape the compiler exists to prevent.

`template/30-projects/Decisions.base`: drop the `tags` property and its two
`order` entries, add `reviewed`, add a **Needs review** view filtering
`reviewed == false`.

`template/CLAUDE.md` §Decision Notes: state the two-sided supersession rule and
the `reviewed` marker. Two lines — the behavioural layer points at the pattern;
the ontology owns the schema.

`plugin/CLAUDE.md`: the mode → `reviewed` mapping, and the bare-stem boundary
rule from decision 3, next to the existing pipe-escaping note. Those two
paragraphs are the same lesson twice, which is the point.

## Fixtures

The four decision fixtures move to the CLI's real output shape:

- `tags` stripped from all four.
- `reviewed` added to all four — three `true`, and one `false` so the new
  **Needs review** view has something to show and the background path is
  demonstrated rather than described.
- `2026-03-10-phased-regional-rollout-adopted` loses the hand-written "superseded
  … see [[…]]" clause from its Implications and gains the deterministic
  `**Superseded**` footer instead. As written it is a note no skill could have
  produced; that is a fixture that lies about the pipeline.

## Verification

Local, matching CI: `lint_plugin.py` · `validate_template.py` ·
`compile_ontology.py --check` · `pytest scripts/tests -q`.

New guards, and specifically the ones that would have caught P1a's defect class:

- **The round trip.** Write A, write B superseding A using the stem
  `decision list` returned, then feed that same returned value back into a third
  write and assert it fails with *"already superseded"* — not with a mangled-path
  error. That is the assertion that the value coming out is the value going in.
- **The PyYAML cross-check.** Parse a written note with PyYAML (the independent
  parser; the runtime module never imports it) and assert `supersedes` is a
  `str`, not a nested list.
- Normalization: `[[stem]]`, `stem.md` and `stem|alias` all resolve to the same
  note; a stem containing `/` is refused.
- Both sides of the edge: A's status flipped, A's footer appended, A's prose
  otherwise byte-identical.
- Preconditions: superseding a missing note, a `superseded` note, a `withdrawn`
  note, a note in another project, and itself.
- `status: superseded` refused on write; filename collisions refused
  case-insensitively; an unknown payload key refused; a malformed payload
  produces the JSON envelope rather than a traceback.
- Fixture conformance: every decision carries `reviewed` and a `**Decision**`
  marker; every `supersedes` resolves to a real note in the same project whose
  status is `superseded` and which carries the footer.

**Hand-test:** `make_test_vault.py`, then `/log-decision` in both modes against
the fixture vault, reading the actual notes produced. Quality is judged on real
output.

## Scope

One PR. `plugin/.claude-plugin/plugin.json` → **0.2.0** (new skill, new CLI
group). `CHANGELOG.md` gets one client-facing entry under `Unreleased`.

No file overlap with P2's branch, which so far carries only its design doc.

## Parked

- **Typing `source` as any vault note** (inbox captures, daily notes) —
  ontology edge change plus a `Decisions.base` column; P2's harvested candidates
  are the forcing case.
- **`decision withdraw`** — flipping an existing active decision to
  `withdrawn`.
- **Cross-project `decision list`** — `sync update-queue` already carries the
  per-project `existingDecisions` projection P2 needs.
- **Decision-graph drift repair** — already parked in P1a toward the
  `/health-check` conformance subcommand; unchanged here.
