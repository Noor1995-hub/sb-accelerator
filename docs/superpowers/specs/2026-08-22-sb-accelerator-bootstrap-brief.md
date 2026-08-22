# SB Accelerator — Repo Bootstrap Brief

**Date:** 2026-08-22
**Purpose:** Self-contained instructions for the first Claude Code session in the new `sb-accelerator` repo. Hand this file + `2026-08-22-second-brain-accelerator-design.md` to that session. Engineering conventions are modeled on `bta-agents-portal` (local checkout: `~/Documents/Dev/bta-agents-portal`, remote: `DLW-INT-BTA-BELUX/bta-agents-portal`) — copy-adapt from there, don't reinvent.

## Repos to create

| Repo | Org | Visibility | Purpose |
|---|---|---|---|
| `sb-accelerator` | `DLW-INT-BTA-BELUX` *(assumption — confirm with Michael)* | Private | Product monorepo, source of truth |
| `sb-dist` | same | Private, per-client read access | Marketplace artifact — created later (design doc step 8), not at bootstrap |

## Human actions required (Michael / org admin — Claude cannot do these)

1. Create `sb-accelerator` in the org (or confirm Michael's `gh` account can)
2. Branch protection on `main`: PRs required, CI check required, 1 approval for non-admins, squash-merge only
3. Install the Claude GitHub App on the new repo (powers `claude.yml` + `claude-code-review.yml`) and set its auth secret the same way `bta-agents-portal` does
4. Create the org Projects v2 board ("SB Accelerator Backlog") + `PROJECTS_TOKEN` secret for the auto-triage workflow
5. Later, at dist time: Claude admin console marketplace connection (see `bta-agents-portal/docs/it-request-plugin-distribution.md` for the exact IT ask pattern)

## Bootstrap checklist (first session, in order)

### 1. Skeleton

```
sb-accelerator/
├── plugin/          # Claude Code plugin: skills/, hooks/, agents/, .claude-plugin/plugin.json
├── template/        # vault skeleton (folders, .obsidian/, .base views, CLAUDE.md + context-portfolio slots)
├── migrations/      # consumed by /upgrade-vault
├── playbooks/       # onboarding interview, pre-flight checklist, hypercare, EA training
├── docs/            # architecture.md, backlog.md, local-setup.md, onboarding-new-builder.md
│   └── superpowers/ # specs/ (copy the design doc here), lessons.md
├── registry.yaml
├── CLAUDE.md · CONTRIBUTING.md · SECURITY.md · README.md · CHANGELOG.md
└── .github/         # workflows + PR template + issue templates
```

### 2. Copy-adapt from bta-agents-portal

- **`CONTRIBUTING.md`** — take as-is, swap CI check names. Keep: protected main, branch naming `<type>/<short-description>`, Conventional Commits **with the mandatory trailer line** (copy the exact trailer), squash merge, 1-approval rule.
- **`.github/pull_request_template.md`** — keep the What & why / Checklist / Linked issue shape; replace the checklist items with this repo's: skills lint passes, template validates, no secrets, plugin version bumped if `plugin/` changed, migration is idempotent if `migrations/` changed.
- **`.github/workflows/claude.yml`** — near verbatim (@claude on issues/PR comments).
- **`.github/workflows/claude-code-review.yml`** — near verbatim, including the cost decisions encoded in its comments (no `synchronize` trigger, `ready_for_review` load-bearing, on-demand `/review`, `--allowedTools` config).
- **`.github/workflows/issue-backlog-defaults.yml`** — swap the project URL to the new board.
- **`.github/workflows/ci.yml`** — new content, same shape: named status checks. v1 checks: `plugin (skill lint + tests)`, `template (structure validation)`, `plugin version (not already released)` (port this check's logic from bta ci.yml).
- **`SECURITY.md`** — adapt.
- **`docs/backlog.md`** — same four-axis model (type label / area label / milestone / board Priority+Status), new labels below.
- **`.claude/settings.json`** — port the worktree/skill setup; skip portal-specific bits. Do **not** port the vault's heavy-assets hooks (no vault content here); add a pre-commit-style hook later only if a real need appears (no speculative hooks).

### 3. Labels & milestones

- `area:plugin` · `area:template` · `area:playbooks` · `area:migrations` · `area:dist`
- `type:feature` · `type:infra` · `type:chore` (+ built-in `bug`)
- `upstream-proposal` (from busdev `/propose-upstream`) · `field-proposal` (from engagements)
- Milestones: `v0.1 walking skeleton` · `v0.2 internal dry run` · `v1.0 pilot`

### 4. CLAUDE.md for the new repo

Model on bta's: what the project is (2 paragraphs + link to design doc in `docs/superpowers/specs/`), structure, how to test locally (instantiate template into a scratch vault + run plugin against it), conventions (skill format — port `99-workflow-config/reference/skill-format.md` from busdev as the starting standard), pointers to CONTRIBUTING and backlog docs. Include the **clean-room rule** as a hard rule: *nothing in `plugin/` or `template/` may reference delaware clients, Michael, or busdev content — CI-lintable later, discipline first.*

### 5. Seed the backlog

Create issues from the design doc's v1 BOM and next steps, roughly:
1. Template extraction from busdev (L0 clean-room) — `area:template`
2. Parent issue "Port core 10 skills" with one **sub-issue per skill** — `area:plugin`
3. `/setup-my-brain` onboarding skill — `area:plugin`
4. `/upgrade-vault` (snapshot + migrate + log) — `area:plugin`
5. `/health-check` — `area:plugin`
6. `/process-upstream` — `area:plugin` (its busdev twin `/propose-upstream` is a busdev-repo task, not here)
7. `/report-feedback` — `area:plugin`: scrubbed (zero vault content/names), approval-gated issue creation to the client's `sb-client-<slug>` repo, plus the proactive "want me to report this?" rule in the template `CLAUDE.md`
8. Playbooks: interview script + pre-flight checklist — `area:playbooks`
9. Internal dry-run engagement — milestone `v0.2`
10. `sb-dist` + release pipeline — `area:dist`, milestone `v1.0`
11. Per-client provisioning script: `sb-client-<slug>` repo + fine-grained token (`issues:write` on it, `contents:read` on `sb-dist`) — `area:dist`, milestone `v1.0`

## Distribution mechanism (discovery from bta-agents-portal — refines the design doc)

Anthropic natively supports org plugin marketplaces: a Claude org admin connects a GitHub repo as a marketplace and Claude **syncs the plugin to selected user groups across web, Desktop, Cowork, and Claude Code** (`docs/it-request-plugin-distribution.md` in bta repo is the proven IT-request template). Implications:

- This is how the plugin reaches an exec's **Cowork** surface — no manual per-machine installs.
- Per client: *their* Claude org admin connects `sb-dist` (delaware provides read credentials) — one item on the pre-flight IT checklist.
- **Consultant-applied update policy is implemented by publishing cadence, not by manual installs:** `sb-dist` only receives a release when clients should get it (quarterly, around tune-up visits). Marketplace sync then delivers it. Structure migrations remain consultant-run via `/upgrade-vault`; a plugin/vault structure-version mismatch check makes skills degrade gracefully until the consultant migrates.

## Feeds into this repo

- **From busdev:** `/propose-upstream` (to be built in busdev) opens `upstream-proposal` issues here; `/process-upstream` (built here) turns them into PRs with `upstreamed-from: busdev@<sha>` provenance.
- **From clients:** `/report-feedback` on exec/EA machines (approval-gated, content-scrubbed) opens issues on the client's own `sb-client-<slug>` repo — never on a shared repo (cross-client visibility). delaware triages those (notifications + at each tune-up) and promotes real ones here as `field-proposal` issues, with a human reply on the client issue.
- **Reference material available on Michael's machine:** busdev vault at `~/Documents/Dev/Vault/BusDev` (the lab — read for porting, never referenced in shipped content), bta-agents-portal at `~/Documents/Dev/bta-agents-portal` (engineering conventions + dist precedent).
