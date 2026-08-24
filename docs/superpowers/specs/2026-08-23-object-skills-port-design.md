# Object Skills Port — Design

**Date:** 2026-08-23 · **Parent issue:** #2 · **Provenance:** `busdev@ccc27b8`

Ports the object-writing skills from the lab vault into the plugin, and
establishes the conventions every later skill port follows. `plugin/skills/`
is empty before this work, so nothing here is a local change to an existing
pattern — it *is* the pattern.

Covers issues **#17** (new opportunity), **#18** (projects), **#19**
(dossiers), **#20** (decision notes) and **#36** (decision capture skill),
split across two PRs.

Authoritative product design: `2026-08-22-second-brain-accelerator-design.md`.
Template/ontology provenance: `2026-08-22-template-extraction-design.md`.

## Source mapping (verified against the lab vault, not assumed)

| Issue | Lab source | Notes |
|---|---|---|
| #17 | `new-opportunity` (204 L) | ~70% overlap with `new-project`; its dossier branch duplicates `update-dossier`'s template wholesale |
| #18 | `new-project` (170 L) | The "project index pattern" is Step 4 of this skill, not a separate artifact |
| #19 | `update-dossier` (224 L) | |
| #20 | `_decision-template.md` + ontology §Decision | Confirmed **not a skill** upstream |
| #36 | `evening-sync` step 2b | Decision writing is currently a side effect of the nightly job |

## Decisions

1. **One `/new-project`, no separate opportunity path.** #17 and #18 collapse.
   Context gathering (paste text, point at a file, or describe it) is offered
   on *every* project rather than gated on a project type or entity status.
2. **`project-type` narrows to two values: `initiative | area-of-responsibility`** —
   a single axis, timeboxed vs ongoing. The four-value enum
   (`presales | delivery | internal | area-of-responsibility`) conflated
   lifecycle with counterparty, and counterparty is already carried by the
   project's `entity` → `entity-type`. Free to change now (`registry.yaml` is
   `clients: []`); a structure migration after the pilot.
3. **`/update-dossier` becomes `/update-entity`.** The skill maintains an
   entity's context; "dossier" is the artifact, not the act. The file stays
   `dossier.md` — an established vault noun that `Entities.base` filters on.
4. **The dossier gets a six-section body schema**, genericized off the lab's:
   Context · Stakeholders · Relationship History · Meeting Log ·
   Sensitivities · Engagements. ("Company Context" → "Context" and
   "Opportunity Summary" → "Engagements" so it serves partners, suppliers and
   business units, not only prospects.)
5. **Project `owner` defaults to the executive**, whose person note the skill
   creates if absent (name from `99-workflow-config/context/identity.md`,
   `relationship: null` so People.base surfaces it as uncurated). `owner` is
   required and joins to a Person; a fresh vault must not produce an owner
   that resolves to nothing. Same convention as the lab vault, which does
   carry a person note for its executive.
6. **Decision `tags` are dropped for v1.** Decisions are retrieved by project
   (the index's Decisions view), by recency (Decisions.base), or by asking in
   words — cross-project tag faceting is thin at 20–50 notes, and a
   controlled vocabulary is the same archetype-portability liability that
   `project-type` just was. Reversible for one ontology line; shipping the
   wrong vocabulary and re-tagging live vaults is a migration.
7. **Decision capture becomes its own skill (#36), not a side effect of the
   nightly job.** Otherwise #20 ships a pattern with no producer.
8. **Skills delegate every write to a deterministic CLI.** The model decides;
   the script writes. Consequence: **object writes require Cowork or Claude
   Code.** See below.
9. **Project index bodies keep their Dataview blocks** (a project-scoped
   Decisions table and a Related Meetings table). Dataview is already a
   pinned plugin; an index without them is a stub rather than a hub.

## Runtime and surfaces

The deterministic-script design rests on which surface can execute code.
Three surfaces, with materially different capabilities:

| Surface | Shell | Object writes |
|---|---|---|
| Chat (web/mobile) + filesystem access or Obsidian MCP | none | **not supported** |
| Cowork (Claude Desktop, macOS or Windows host) | Linux VM | supported |
| Claude Code CLI on the host | host OS | supported |

**Cowork does not run on the host OS.** Anthropic's Cowork architecture
documentation states that shell commands and any code Claude writes execute
inside "a dedicated Linux VM" — Apple Virtualization.framework on macOS,
Hyper-V on Windows. So a Windows-host assistant and a macOS-host assistant
get the same Linux environment, and host-OS portability largely dissolves on
the surface that carries operational volume.

A January 2026 third-party teardown observed Ubuntu 22.04 ARM64 with Python
3.10, Node 22, bash and git, with connected folders shared via VirtioFS under
`/sessions/<name>/mnt/`. That is unofficial and version-specific: treat the
base interpreter as dependable and the package set as not.

**Design rules that follow:**

- **Python stdlib only at runtime.** PyYAML's presence in the Cowork VM is
  unverified, and the lab vault has no precedent to borrow (its scripts
  hard-import `yaml`). Hence the compiled schema below.
- **Target Python 3.10 as the floor.** Repo CI runs 3.13; 3.11+ syntax would
  fail only on the client machine.
- **The vault root is always a parameter**, never derived from a path shape —
  under Cowork it is a mount point, not `/Users/...` or `C:\...`.
- **Case-insensitive collision checks.** Linux inside the VM will create
  `Foo/` and `foo/` happily; the APFS or NTFS host underneath collides them.
- **Cap generated filename length** (Windows' 260-character path limit; the
  lab vault already truncates decision filenames, so make the rule explicit)
  and reject Windows reserved stems (`CON`, `NUL`, `COM1`…).
- **Writes use `newline="\n"` and explicit UTF-8**, so a Windows-side write
  never injects CRLF into markdown that syncs to a Mac.

**Chat remains a first-class read surface.** It needs no skill: plain
markdown with YAML frontmatter is what makes "what did we decide on X"
answerable there. Object *creation* is an operational act, and it belongs
where the vault is mounted. In chat, these skills decline with a one-line
pointer to Cowork rather than hand-writing frontmatter that a machine
contract governs.

Two related facts, both confirmed 2026-08-23:

- **Plugins do not load in Chat at all**, so the surface boundary above is a
  platform constraint rather than a design choice.
- **Cowork does read the vault's `CLAUDE.md`** as folder instructions by
  default (it appears in Cowork's context panel as "Instructions ·
  CLAUDE.md"), so the template's behavioural layer applies there without
  mirroring. This was an open question at design time; it is settled and adds
  no deliverable.

Delivery mechanics, the five paths, and the pre-flight consequences live in
`playbooks/plugin-distribution.md` and `playbooks/pre-flight-checklist.md`
(PR #37).

**New pre-flight checklist items** (playbook, delaware-side): Windows Cowork
requires the `VirtualMachinePlatform` optional feature and administrator
privileges at install — without admin, Cowork is unavailable. Anthropic also
documents that "virtual machines and VDI environments without nested
virtualization aren't supported", which is a real risk on enterprise VDI
fleets. Whether Windows Home qualifies is not stated officially; verify on
the client's actual image.

## Architecture: the deterministic CLI

The lab vault already converged on this pattern where it had scripts at all.
Its recorder-sync helper states the principle outright: "The skill's
orchestrator (Claude) calls these subcommands via Bash. Each subcommand is a
single deterministic action — no LLM parsing of ledgers or filenames, no
fuzzy string matching." Its evening-job data layer exists specifically to own
"the deterministic, bug-prone parts", and documents the three bug classes it
was written to kill.

The object skills are prose-only upstream. This design extends the pattern to
them, for a reason particular to this repo: the ontology is machine truth
with a conformance guard, but that guard only checks **fixtures**. Moving the
write into a script puts the same contract on the write path in the client's
vault.

```
plugin/lib/vaultlib/            # shared, stdlib-only
  cli.py                        # single entry point, subcommands
  schema.json                   # COMPILED from ontology.md, checked in
  frontmatter.py                # read/write preserving key order
  slugs.py                      # derivation + collision/length/reserved rules
  vault.py                      # atomic writes, path resolution
scripts/compile_ontology.py     # ontology.md -> schema.json
```

Skills invoke it as
`python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" <subcommand> --vault "$VAULT" ...`,
and every subcommand returns JSON on stdout.

**Why compile the schema.** A hand-rolled YAML parser at runtime would be a
second parser obliged to agree with CI's PyYAML one — a silent-divergence bug
class, not a solution. Instead `ontology.md` stays the single human-editable
source, `compile_ontology.py` derives `schema.json`, and a CI test
regenerates and diffs it, so editing the ontology without regenerating fails
the build. Runtime reads JSON from the stdlib. This is strictly better than
the lab vault's hand-maintained "change a schema → update these four things
in the same commit" protocol, which nothing enforces.

`test_fixtures_ontology.py` keeps loading `ontology.md` directly (CI has
PyYAML). Two consumers, one of them provably derived from the other.

**Division of labour.** The model owns judgment: turning a project name into
a good slug, extracting topic/contacts/source/timeline from pasted material,
writing the "Now" callout prose, deciding which dossier section a sentence
belongs in. The script owns everything mechanical: validation against the
schema, collision detection, frontmatter emission, markdown table merges,
date stamping, atomic writes.

One structural constraint discovered: `lint_plugin.py` requires a `SKILL.md`
in every directory under `plugin/skills/`, so shared code cannot live at
`plugin/skills/_lib/`. Hence `plugin/lib/`.

## Ontology changes

In `template/99-workflow-config/reference/ontology.md`:

- **`project-type` enum** → `[initiative, area-of-responsibility]`.
- **New `body_sections` key** on the `project` and `entity` blocks, making
  body structure machine truth the same way frontmatter already is:

  ```yaml
  object: entity
  required: [type, entity-name, slug, status]
  optional: [entity-type, industry, owner, created, last-updated]
  enums: { ... }
  body_sections: [Context, Stakeholders, Relationship History,
                  Meeting Log, Sensitivities, Engagements]
  ```

  `test_fixtures_ontology.py` loads it exactly as it already loads the
  decision `tags` key, and a new test asserts every project and entity
  fixture carries those H2s. The existing well-formedness test ignores
  unknown keys, so nothing breaks. Project sections are
  `[Decisions, Open Items, Related Meetings]`; the two callouts above them are
  skill-level template detail, not schema.
- **§Entity gains the six-section body schema** — section order, the
  stakeholder table's columns (Name · Title · Role in Decision · Stance ·
  Notes), the Engagements table's columns, and the append/prepend rules per
  section. This is the shared contract for `/new-project`'s baseline dossier
  and `/update-entity`'s merge, rather than the copy-paste the lab vault has
  between its two skills.
- **§Decision** (P1b): the note template as a fenced block, and the
  two-sided supersession procedure. `tags` removed.

**No new frontmatter fields.** Every field these skills write is already in
the blocks. `cssclasses` is dropped (no CSS snippet ships) and `opportunity`
is dropped (superseded by decision 1). The ~21-key meeting frontmatter with
`confidence` / `confidence-reasons` and recorder provenance described in
issue #2's standing requirement belongs to the recorder sync — that is the
daily-loop PR's ontology debt, not this one's.

Also in `template/`: **`Decisions.base` gains `file.inFolder("30-projects")`.**
It currently filters on `type == "decision"` with no folder scope, unlike
Meetings.base and Projects.base which both scope by folder — so any
decision-typed file anywhere in the vault lands in the client's decision
table. This is why #20's note template ships as a fenced block rather than as
a file with live frontmatter.

## D1 — `/new-project`

```
/new-project
/new-project "Yard Automation Program"
/new-project "Pipeline Governance" --type area-of-responsibility --entity commercial-operations
```

1. **Gather.** Name · type (default `initiative`) · entity (list
   `40-entities/*/`, plus "create new") · parent (initiatives only) ·
   optional context: paste text, point at a file (an inbox capture, an
   exported email, a document), or describe it.
2. **Extract** topic, contacts, source and timeline hints from any supplied
   context — model judgment, feeding the Context callout.
3. **Resolve owner.** Read identity.md, derive the slug, ensure the person
   note exists.
4. **Scaffold** via `cli.py project scaffold`: validate against the schema,
   check collisions case-insensitively, write `index.md`, create
   `decisions/`.
5. **Link into the entity dossier** — add or update the row in
   `## Engagements`. Non-blocking: a dossier failure never fails the project
   creation, it degrades to a note in the summary.
6. **Summary** of what was created and where.

Constraints carried over: slug must be unique; a parent must exist and must
not itself be parented (maximum two levels); areas of responsibility are
always top-level.

**Index body:**

```markdown
# {Project Name}

> [!summary]+ **Now** — as of {DD-MM-YY}
> - **Stage** — · **Defining decision** — · **Next event** — · **Owe** — · **Watch** —

> [!info]- **Context**
> - **Contacts** — · **Source** —

## Decisions            (dataview over 30-projects/{slug}/decisions)
## Open Items           Owe · Awaiting · Question · Pending
## Related Meetings     (dataview over 20-meetings where projects contains this.slug)
```

Two porting notes: the upstream Related Meetings query filters the executive
out of the attendee list *by display name*, which cannot ship (clean-room)
and would not work regardless, since our `attendees` are slugs — the
self-filter is **dropped**, the three-attendee slice kept. And the `FROM`
folder changes from the lab's meetings folder to `20-meetings`.

## D2 — `/update-entity`

Validate or create the entity directory → read the dossier, or create it per
ontology §Entity → prompt for free-form input → route each piece to a section
→ merge under that section's rules → bump `last-updated` → write → summarise
every change, naming contradictions explicitly.

`cli.py entity read` returns the dossier parsed into sections as JSON;
`cli.py entity write` takes section edits as JSON and performs the merge.
Markdown table merging is exactly the fiddly, deterministic work a script
should own; *routing* stays with the model.

Genericization against #19's strip list: `account-owner` → `owner`; "why it
matters for delaware" → "why it matters"; `Opportunity Summary` →
`Engagements`, linking `../../30-projects/{slug}/index.md` (the upstream link
target is stale even upstream); the routing signal table reworded off BD
vocabulary ("budget signals", "pipeline status") toward exec-neutral cues.

Two upstream mechanisms are **kept** against the instinct to strip them: the
`> [!unvalidated]` banner with per-section `<!-- unvalidated -->` markers, and
`<!-- needs-review -->` on auto-added stakeholders. They exist upstream to
mark web-researched company context, which v1 has no skill for — but they are
the template's "be epistemically honest" golden rule made mechanical, and
`/setup-my-brain` will seed dossiers from conversation. Cheap to keep, awkward
to retrofit.

The hard rule survives verbatim: **never remove existing content.** Add or
update only; call out contradictions in the summary.

## D3 — decision notes (#20) and capture (#36)

#20 is a pattern port by its own definition. Already present: the ontology
§Decision block, `Decisions.base`, and the template's Decision Notes section.
What lands: the note template as a fenced block, the two-sided supersession
procedure (set `supersedes:` on the new note **and** flip the prior note to
`status: superseded` — stated nowhere today, only demonstrated in fixtures),
a body-structure statement, and the `tags` removal.

#36 is `/log-decision`, in two modes. **Foreground:** read a source (a meeting
note, an inbox transcript, a pasted paragraph), propose candidate decisions,
let the user validate or edit each inline, then write — setting both sides of
any supersession edge. **Background:** the same extraction without prompts,
marked for later audit; this is what the evening brief calls. Writes go
through `cli.py decision write`.

Note that decision bodies use bold markers (`**Decision**` / `**Why**` /
`**Implications**`) rather than H2s, so `body_sections` does not apply; the
guard checks the `**Decision**` marker instead.

## Fixture enrichment

Per the standing requirement on issue #2, fixtures move to the skills' real
output shape rather than a guessed one.

- **5 project indexes** — bodies rewritten to `/new-project`'s actual output
  with per-project content; `project-type` re-tagged (4 × `initiative`,
  1 × `area-of-responsibility`, so the enum-coverage test still passes).
- **3 dossiers** — rewritten to the six sections: stakeholder tables with
  stances, meeting-log entries cross-referencing the meeting fixtures,
  sensitivities, and Engagements tables listing the projects.
- **The executive's person note** — new; the `owner` join has to resolve.
  Takes people from 9 to 10 against a minimum of 8.
- **One context-portfolio sentence** still says "presales".
- **4 decision fixtures** (P1b) — `tags` stripped.

**Deliberate boundary:** the executive is *not* added to the meeting
fixtures' `attendees` in this batch. It would be more realistic — the lab's
self-filter proves the executive is in its attendee lists — but meeting shape
belongs to the recorder sync, and touching all eight meeting notes buys this
PR nothing. It lands with the `confidence` and provenance work.

## Verification

Local, matching CI: `lint_plugin.py` (first real exercise of the skill
frontmatter linter and of the `upstreamed-from: busdev@<sha>` exemption) ·
`validate_template.py` · `pytest scripts/tests -q`.

New tests: schema regenerate-and-diff · slug rules (collision, length,
reserved stems) · frontmatter round-trip preserving key order · both
subcommands against a temporary vault · `body_sections` conformance for
project and entity fixtures.

**Two new CI jobs, both non-required.** Matrixing the existing `plugin` job
would rename its check context to `plugin (skill lint + tests) (ubuntu-latest)`,
and the `main-ci` ruleset requires the current names exactly — that blocks
every merge, as ci.yml's own header comment warns. So:

- `runtime floor (python 3.10)` — the Cowork interpreter version. More
  valuable than the Windows job: 3.11+ syntax would otherwise fail only on a
  client machine.
- `cross-platform (windows)` — keeps the portability claim honest for the
  Claude Code CLI surface and the consultant-side scripts.

Both are promotable to required via the ruleset later.

**Hand-test:** `make_test_vault.py /tmp/port-vault --with-plugins`, then run
each skill against the fixture vault — create a project with context pasted
from a fixture inbox capture, update a dossier from free-form notes — and
review the actual files produced. Quality is judged on real output.

**Marketplace manifest.** This PR adds `.claude-plugin/marketplace.json` at
the repo root, because without one the repo is not installable as a
marketplace at all — and `--plugin-dir` is a **Claude Code** flag, so it is
not a way to hand-test in Cowork. The client-facing marketplace remains
`sb-dist`, written by the release pipeline (issue #10, not yet built); this
manifest is for internal development and Cowork hand-testing, and its `name`
should say so. Whether a *private* repo can be added as a user-level
marketplace in Cowork is not documented either way — the hand-test
establishes it. It works in Claude Code regardless, via
`/plugin marketplace add`.

## Scope: three PRs

| PR | Contents | Closes | Version |
|---|---|---|---|
| **P1a** | `/new-project`, `/update-entity`, `plugin/lib/vaultlib`, schema compilation, ontology changes, fixture enrichment, `Decisions.base` folder filter, marketplace manifest, two CI jobs | #17, #18, #19 | 0.1.0 |
| **P1b** | `/log-decision`, decision note template, supersession procedure, tags removal, decision fixture pass | #20, #36 | 0.2.0 |
| **P2** | daily loop — its own brainstorm | #14, #15, #16 | |

P1a and P1b both land before P2, since the evening brief depends on #36.

## Parked

**The evening job is not a brief generator.** Issue #16 names `evening-sync`
as its source, but upstream that skill re-syncs recordings, fans out
subagents to rewrite every project index, and maintains a decision knowledge
graph, backed by roughly 1,560 lines of Python across two modules. Whether
that engine is in scope, and whether the two briefs ship as one skill with a
mode flag (the upstream shape) or two, is the daily-loop brainstorm's first
question.

**Also parked:** an archetype-configurable vocabulary for `project-type` (the
product design puts the archetype library in Phase 2; the goal here is a
vocabulary generic enough that a second archetype needs no change, not a
mechanism for changing it) · Projects.base views split by type · a
`conformance` subcommand for `/health-check`.
