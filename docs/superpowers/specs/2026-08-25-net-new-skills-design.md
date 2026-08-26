# Net-new skills batch (#3–#7) — design

**Issues:** #3 `/setup-my-brain` · #4 `/upgrade-vault` · #5 `/health-check` ·
#6 `/process-upstream` · #7 `/report-feedback`
**Date:** 2026-08-25 · **Status:** approved in brainstorm with Michael
**Milestone:** v0.1 walking skeleton (the last five open v0.1 build items
besides playbooks #8, dry run #9, and sb-dist #10)

One combined design per the batching strategy: one spec, one plan, one
branch, one PR closing all five (`Closes #3, #4, #5, #6, #7`), one plugin
version bump. Per-issue rigor is preserved by one implementer subagent +
review per task inside the batch.

## Cross-cutting architecture

Every skill follows the established repo pattern: SKILL.md carries judgment
and conversation; every byte written to disk goes through a deterministic
`vaultlib` subcommand (stdlib-only, Python 3.10 floor, runs in the Cowork
VM).

### New and extended CLI groups

| CLI | Serves | What it does |
|---|---|---|
| `config write` | #3 | Field-level sets on `99-workflow-config/config.json`: `timezone`, `executive`, `adapters.<name>.enabled`, `adapters.<name>.account_hint`, `feedback.repo`. Validates against the same shape rules as `config read` — a display-name hint (no `@`, no digit) is rejected at write time, unknown fields are refused. |
| `context write` | #3 | Generalizes the existing `identity show` marker machinery (`vault.py` `<!-- setup-my-brain:begin/end -->`) to read/write the fenced block of **all five** context-portfolio files. Replaces the block atomically; forbidden from touching a byte outside the markers. Re-run = replace, so the interview is idempotent by construction. |
| `migrate` group | #4 | `migrate status` and `migrate run` — see /upgrade-vault below. |
| `health report` | #5 | Content-free metrics, computed deterministically; builds on the metrics join `sync update-queue` already owns. |
| `feedback` group | #7 | `feedback lint` (deterministic scrub check) and `feedback send` (lint + POST via stdlib `urllib` to the GitHub API — no `gh` on client machines; `send` runs the lint itself, atomically — no code path posts an unlinted draft). |

### What ships where

- `plugin/skills/`: `setup-my-brain`, `upgrade-vault`, `health-check`,
  `report-feedback` (all `user_invocable: true`, clean-room rules apply).
- `.claude/commands/process-upstream.md`: delaware-internal, next to
  `visual-check.md`. Never enters the plugin; clean-room does not constrain
  it (but the *rewrites it produces* must pass the clean-room lint).
- **Migrations move to `plugin/migrations/`** so they ride the marketplace
  update channel — the consultant updates the plugin at the tune-up and the
  new migration is simply there; plugin version ↔ available migrations is
  deterministic. Top-level `migrations/README.md` becomes a pointer to the
  new location (its content moves with the files).

### Config additions (still `config-version: 1` — additive, null defaults)

- `"feedback": {"repo": null}` — the `sb-client-<slug>` repo name, set at
  provisioning or by `/setup-my-brain`'s consultant.
- The feedback **token** never enters `config.json`: it lives in its own
  file `99-workflow-config/secrets/feedback-token` (one line, placed at
  provisioning, synced to both machines by Obsidian Sync like everything
  else). Read only by `feedback send` — from file, never argv, so it never
  reaches shell history, process lists, or `config read` output (which
  skills paste into model context).

## Privacy & trust posture

The headline stays intact: **nothing phones home.** After handover delaware
sees exactly two things, both human-gated — a `/report-feedback` issue the
exec/EA explicitly approved, and a `/health-check` report the EA chooses to
share. No telemetry, no auto-send code path anywhere.

Deterministic controls (technical, not prompt discipline):

1. **`feedback lint` blocks on real vault data:** every person/entity/
   project name, slug, and alias in the vault; every meeting-note title;
   the executive's name and identifiers from `config.json`; any email
   address; any wikilink or vault content path (implementation note,
   recorded at build time: the identity context block is deliberately
   **not** parsed — it is free prose with no deterministic extraction
   point, unlike `config.json`'s fixed keys. The exec's name is covered
   instead by their person note, which `/setup-my-brain` seeds immediately
   after the identity file is written, and their email is still caught by
   the email regex regardless of which file it sits in. The known residual
   window is an interrupted Session 1 between those two writes — identity
   file present, person note not yet seeded). A block names the offending
   fragment locally so the draft can be fixed; `feedback send` refuses to
   post on any block.
2. **A fixed disclosure block** is shown at every share nudge (in
   `/report-feedback`, in `/health-check`'s share offer, and in the
   template `CLAUDE.md` nudge rule): what is included (plugin +
   structure-version, skill involved, expected vs. actual, counts), what is
   structurally excluded (all personal and business content), that the data
   is used **solely to improve the product**, and that nothing is ever sent
   without explicit approval.
3. **The CLI stamps the disclosure into every posted issue body** — each
   issue delaware receives carries its own audit trail of what the sender
   was promised.
4. `health report` is content-free **by construction**: it has no code path
   that outputs a note title or a name — only counts, rates, ages, and
   version strings.

Wording rule (deliberate precision, do not overclaim): the channel is
per-client by design — `sb-client-<slug>` identifies *which deployment* a
report came from, which is what makes it actionable. So the disclosure says
"the content carries zero personal or business data; the only identifying
fact is which deployment it came from" — never "fully anonymized".

Residual risks, accepted with mitigations:

- **The token file is readable by anything with vault access.** Bounded by
  blast radius: the token must be minted **fine-grained, `issues:read` +
  `issues:write` on that client's `sb-client-<slug>` only, no `contents`
  scope** (provisioning-runbook requirement). Worst case of a leak is
  filing issues on the client's own feedback repo; rotatable at any
  tune-up. Belt and suspenders: a template `CLAUDE.md` rule — never read or
  display files under `99-workflow-config/secrets/`.
- **Session-1 scratch is engagement data.** #54's scratch-hygiene rule
  extends verbatim to `/setup-my-brain`: connector whoami payloads deleted
  immediately after the bind; calendar-scan JSON deleted at end of session;
  nothing from the scan persists except objects the exec confirmed.
- **The exec's identifier (email/id) sits in `config.json`.** Deliberate
  and non-secret — their own address in their own vault; it is what makes
  the binding gate work. One line in the data-flow one-pager.

## `/setup-my-brain` (#3)

Runs live in Cowork, consultant + exec, Session 1 of the onboarding
journey. **Precondition: a provisioned template vault — the skill fills,
never scaffolds.** The template does not ship inside the plugin, so there
is nothing on the client machine to instantiate from; pointed at a
non-vault folder, `vault.resolve()` fails loudly and the error points at
the provisioning runbook.

**Phase 0 — preflight.** `config read` establishes state. Fresh vault
(nulls everywhere) proceeds; a filled config means **re-run mode** — every
phase becomes "show current, offer to revise" (marker-fenced context writes
and `config write` make re-runs idempotent). Structure-version mismatch →
stop and point at `/upgrade-vault`.

**Phase 1 — the interview.** Walk the five context files in fixed order:
identity → role-and-responsibilities → communication-style →
preferences-and-constraints → tools-and-systems. The questions are the
"Interview questions" sections already shipped **in the template files** —
they live in the vault, not the skill, so archetypes can tune them later.
Conversational, one topic at a time; after each file the skill drafts the
content block, reads it back for approval, then writes via `context write`.
During this phase:

- the exec's own person note is seeded (`person ensure`) and
  `config write executive <slug>` records the join key;
- timezone is confirmed with the exec and written (`config write timezone`).

**Phase 2 — binding ceremony** (per the #54 hint-shape rule, requirement
recorded on issue #3). For each connector adapter the deployment uses
(consultant decides which): call the connector's whoami
(`mcp__plaud__get_current_user`, M365 `get_me`) with the exec's account
signed in, show the human-recognizable nickname for recognition, get an
explicit yes, then write the `id`/`email` **verbatim from the whoami
payload** into `adapters.<name>.account_hint` via `config write`, and set
`enabled: true`. Never ask anyone to type an email — for Apple/Google
sign-ins the sign-up email never appears in the whoami, and display names
are rejected by validation. Identity payload deleted from scratch
immediately after each bind.

**Phase 3 — seeding, three separate steps in this order:**

- **3a. Entities — conversation-driven.** Explain what an entity is (an
  organization the exec deals with — client, partner, supplier — the thing
  a dossier is kept on), then ask the exec to name theirs. Entities are
  **not** derived from the calendar. Confirmed entities are written via
  `entity ensure`.
- **3b. Projects — suggested, prudently.** Candidates from interview
  mentions + recurring calendar subjects, explicitly framed as "areas of
  responsibility". Aim for **3–4**; reassure that `/new-project` exists so
  more can be added the moment one is missed. Confirmed projects written
  via `project scaffold`, linked to an entity where applicable.
- **3c. People — calendar + interview.** `outlook_calendar_search` over
  ±2 weeks plus recurring series; attendees + interview-mentioned names
  form one confirm/reject list walked through with the exec; only confirmed
  people are written via `person ensure`. Meeting-rhythm observations feed
  the role/preferences context blocks.

Calendar only in v0.1 (decided 2026-08-25). Mail/Teams **corroboration**
(targeted per-candidate frequency checks to rank key people — never open
discovery) is a v1.x extension of the re-run path. Seeding is re-runnable
later with a wider window.

**Phase 4 — the wow.** Invoke the `/evening-sync` pipeline against the
now-seeded vault: the m365 calendar gate passes (it was just bound),
tomorrow's daily note is written with a prep section per real meeting,
referencing the entities and people seeded twenty minutes earlier. Open it
on screen. Sweep scratch. Done.

**Error handling:** every phase degrades gracefully — connector missing or
refused → the phase is skipped with an explicit line and the skill says
what still works. The interview alone still produces a valid vault.

## `/upgrade-vault` (#4)

Consultant-run at tune-ups, right after the plugin update.

**Migration format** (this issue defines it): each migration is
`plugin/migrations/NNN-<slug>/migrate.py` implementing a small contract —

- `TARGET_VERSION: int` — the structure-version it upgrades **to**
  (migration NNN applies only when the vault is at `TARGET_VERSION - 1`);
- `LOSSY: str | None` — names anything dropped, surfaced before running;
- `apply(root: Path) -> dict` — idempotent; returns a report (counts,
  skipped items, items needing a human read);
- `verify(root: Path) -> dict` — idempotent post-conditions check.

Migrations are plain stdlib Python, reviewed in PR, unit-tested in CI
against fixture vaults, and reach client machines pinned to the same
40-character commit SHA as the rest of the plugin — the same trust level
and audit trail as any skill.

**CLI:**

- `migrate status --vault V` — vault's `structure-version` file vs. the
  chain the installed plugin carries; lists pending migrations with their
  `LOSSY` notes.
- `migrate run --vault V` — snapshot first → apply pending in order →
  `verify` after each → bump `structure-version` → append the log entry.
  Any `apply`/`verify` failure stops the chain with the snapshot name in
  hand.

**Snapshot:** zip of the vault into `99-workflow-config/snapshots/`
(`vault-YYYY-MM-DD-HHMMSS.zip`), keep last 3 (oldest deleted). Inside the
vault because in Cowork the vault mount is the only writable host path;
the snapshots folder is excluded from the zip itself. Its Obsidian Sync
exclusion is a **provisioning-runbook step**, not a shipped file —
corrected at plan time: Obsidian Sync exclusions are account/device-level
settings (the existing `95-private` exclusion is configured the same way);
`template/.obsidian` carries no sync config and is untouched by this
batch.

**Log:** append-only `99-workflow-config/migration-log.md` — date,
from→to structure-version, plugin version, snapshot name, outcome.

**Skill flow:** confirm the plugin was updated → `migrate status` → show
the plan including `LOSSY` warnings → explicit consultant confirmation →
`migrate run` → report per-migration verify results → list anything
needing a human read.

**Migration 001 ships in this batch** — the structure-version 2 bundle
already specified in `migrations/README.md`: add `config.json` from the
template default; decision notes drop `tags`, gain `reviewed: true`;
rewrite `review_status: needs-attention` → `needs-review`; refresh
`10-inbox/README.md`, add `90-archive/README.md`, refresh the Inbox
Discipline section of the vault `CLAUDE.md`; **refresh the vault's
`ontology.md`**; backfill `entities:` on meeting notes (derived
`projects[]` → project → `entity:`; empty `projects[]` → reported for a
human read); restructure dossier bodies (title, callouts, Dataview Meeting
Log + Dynamics carry-over — the lossy step, declared in `LOSSY`).
Idempotency per the README: skip notes that already have `entities`, skip
dossiers already carrying the Dataview block. This is the proof of the
format and the heaviest task in the batch.

## `/health-check` (#5)

EA-run during hypercare (and at tune-ups).

**CLI:** `health report --vault V [--window 28]` emits, by construction,
only counts, rates, ages, and version strings:

- meeting-note volume per week, by source adapter (`plaud:`/`m365:`/
  `inbox:` prefixes of `source-recording-id`);
- daily-note coverage over working days in the window — the honest proxy
  for "brief success rate" (a machine-written region present = the evening
  run succeeded);
- inbox pending count; skip-list size;
- stale projects (no meeting in 30d — reuses the `updatequeue` metrics
  join); entities without a recent Meeting Log entry;
- meetings-without-projects count (implementation note, recorded at build
  time: this replaces the originally-specified "update-queue warning
  count" — `sync update-queue` writes metrics into notes, and health is
  read-only by contract); decision-note counts by `status` (the field
  decision notes actually carry), out-of-enum values folded to `unknown`
  so no vault content can ride a count's key;
- plugin version + structure-version.

**Skill flow:** run the CLI → render the report → write it to
`99-workflow-config/health-reports/YYYY-MM-DD.md` (local history for
tune-ups) → **offer** to share with delaware over the #7 channel, showing
the disclosure block — approval-gated, passed through `feedback lint` like
everything outbound (trivially, since it is numbers). Never auto-sends.

## `/process-upstream` (#6)

Delaware-internal: `.claude/commands/process-upstream.md`, runs on a
consultant machine where `gh` and the busdev checkout exist.

Flow for `/process-upstream <issue#>`:

1. `gh issue view` — accepts `upstream-proposal` and `field-proposal`
   issues (same funnel).
2. For upstream proposals: read the referenced busdev vault files; **flag
   drift** if the vault moved past the recorded sha (show the diff, human
   decides whether to proceed against HEAD or the recorded sha).
3. Perform the genericization rewrite following the clean-room rule —
   rewrite, never copy-paste-then-trim; `scripts/lint_plugin.py` is the
   net, not the rule.
4. Record `upstreamed-from: busdev@<sha>` in the ported skill's
   frontmatter.
5. Branch, commit, open a PR referencing the issue, following this repo's
   own conventions (version bump, CHANGELOG judgment call, three green
   checks).

## `/report-feedback` (#7)

In the plugin. Flow:

1. Gather context: which skill was involved, expected vs. actual, plugin
   version (the CLI reads its own `plugin.json` relative to `__file__`)
   and the vault's `structure-version`.
2. Draft against a fixed template — generic behavior description only.
3. Show the draft **plus the disclosure block**; explicit approval
   required. Never auto-sent.
4. `feedback send --vault V --title … --body-file …` — runs `feedback
   lint`; any block refuses the post and names the fragment locally. On
   pass: POST to the GitHub API (`repos/<owner>/<feedback.repo>/issues`)
   with the token from `99-workflow-config/secrets/feedback-token`,
   disclosure stamped into the body.
5. **Unconfigured channel** (null `feedback.repo` or missing token file):
   the skill says so and saves the approved draft to `10-inbox/` for the
   EA/consultant to relay — never a dead end.

**Proactive nudge rule** in `template/CLAUDE.md`: when Claude on a client
machine hits a broken skill, a confusing flow, or repeated friction, it
offers "want me to report this to delaware?" with the disclosure shown; on
yes it runs `/report-feedback` with a prefilled draft. Never auto-runs.

**Provisioning requirements** (runbook additions): create
`sb-client-<slug>`; mint the token fine-grained, `issues:read+write` on
that repo only, **no `contents` scope**; place the token file; set
`feedback.repo` in `config.json`.

## Testing

- `config write`: validation matrix (field allowlist, hint shape rule,
  type checks, unknown adapter, round-trip with `config read`).
- `context write`: marker safety (byte-identical outside the fence,
  replace-idempotency, all five files, missing markers → error).
- `migrate`: status/run ordering, idempotent re-run, snapshot rotation
  (keep 3), log append, failure-stops-chain; **migration 001 applied to
  the demo fixture** and verified (entities backfill, dossier
  restructure, ontology refresh).
- `health report`: metric correctness on fixtures; a grep-style assertion
  that the report contains no fixture titles/names.
- `feedback lint`: block/pass matrix (names, slugs, aliases, meeting
  titles, emails, wikilinks, paths; clean drafts pass).
- `feedback send`: mocked HTTP (no network in CI), lint-refusal path,
  token/repo-missing paths, disclosure stamping.
- Skill-contract tests in the established style: each skill must name its
  CLI gates; no skill instructs reading machine decisions from prose.
- `validate_template.py` extended: `secrets/` README present, disclosure
  text present in the template `CLAUDE.md` nudge rule, `feedback` section
  shape in `config.json`, `structure-version` content matches the version
  the shipped migrations expect.
- `scripts/lint_plugin.py` still passes over the four new plugin skills
  and `plugin/migrations/` (clean-room).
- **Visual check** only if a UI-impacting path ends up touched
  (`template/.obsidian/**`, `*.base`/`*.canvas`, `fixtures/demo-vault/**`,
  `ontology.md`, `markdown.py`); none is planned in this batch — corrected
  at plan time, see the snapshot paragraph.

## Rollout

- One branch, one PR: `Closes #3, closes #4, closes #5, closes #6,
  closes #7`.
- `plugin/.claude-plugin/plugin.json`: 0.6.3 → **0.8.0**. (Planned as 0.7.0;
  the m365 adapter (#80) merged first and consumed that number, so this batch
  rebased onto it and took the next one.)
- CHANGELOG (`Unreleased`): lines for #3, #4, #5, #7 (client-noticeable);
  #6 stays out (internal).
- Execution: writing-plans → subagent-driven development, one implementer
  subagent + review per task, per the batching strategy.

## Alternatives considered

- **Migration format:** declarative JSON ops + interpreter — rejected: the
  already-pending migrations (entities backfill, dossier restructure)
  exceed any sane op vocabulary; the interpreter becomes a worse
  programming language. Model-executed prose migrations — rejected:
  non-deterministic fuzzy writes across hundreds of notes is what the
  CLI-owns-writes architecture forbids.
- **Migrations stay top-level, copied at release** — rejected: invents
  release tooling now (#10 doesn't exist yet) and until it exists
  `/upgrade-vault` has nothing to consume.
- **Token outside the vault (per-machine dotfile)** — rejected: Cowork's
  VM/permission layer may not expose the host home dir, two manual
  placements, drift risk. Vault-resident with minimal scope is bounded
  and rotatable.
- **Mail/Teams in Session-1 seeding** — deferred to v1.x as targeted
  corroboration only (rank candidates already surfaced); open mail/Teams
  discovery live in front of the exec is slow, noisy, and the
  anti-wow — decided 2026-08-25.
- **Dedicated first-brief renderer for the wow** — rejected: a second
  brief writer to keep consistent with the engine; the real
  `/evening-sync` run is the honest demo of what ships.
- **`/setup-my-brain` scaffolds an empty folder** — rejected: the
  template doesn't ship inside the plugin; provisioning owns
  instantiation (pinned version, sync setup, `.obsidian` config).

## Deferred / recorded

- Mail/Teams corroboration pass on the seeding re-run path (v1.x).
- `/health-check` conformance/auto-fix subcommand stays parked (P1a
  design); v1 surfaces drift as warnings only.
- `sb-dist` (#10) is still unbuilt; until then plugin+migration delivery
  to real clients is manual ZIP, as already recorded in the design doc.
