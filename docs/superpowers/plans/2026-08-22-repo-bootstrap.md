# sb-accelerator Repo Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap `DLW-INT-BTA-BELUX/sb-accelerator` as a working product monorepo — skeleton, conventions, CI, GitHub plumbing, seed backlog — plus the `/propose-upstream` skill in busdev, closing busdev issue #2.

**Architecture:** Copy-adapt engineering conventions from `~/Documents/Dev/bta-agents-portal` (protected main, named CI checks, Claude workflows, four-axis backlog). New content only where bta has no equivalent: the three v1 CI validators (skill lint, template validation, plugin version guard) and the repo's own docs. Everything lands directly on `main` until Task 7 applies branch protection; after that, all changes go through PRs.

**Tech Stack:** GitHub CLI (`gh`) + GitHub Actions; Python 3.13 + pytest + PyYAML for the validators; plain bash for the version guard.

**Spec:** `docs/superpowers/specs/2026-08-22-sb-accelerator-bootstrap-brief.md` (primary — the checklist this plan implements) and `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md` (product context, v1 BOM). Both already committed at repo root `/Users/bulthem/Documents/Dev/sb-accelerator`.

## Global Constraints

- **Repo roots:** sb-accelerator work happens in `/Users/bulthem/Documents/Dev/sb-accelerator` (Tasks 1–7, 9). Task 8 happens in the busdev worktree `/Users/bulthem/Documents/Dev/Vault/BusDev/claude/worktrees/knbp-parkwind-ai-opportunity-aefeea` (branch `claude/git-issue-2-b2dee0`).
- **Clean-room rule (hard):** nothing in `plugin/` or `template/` may reference delaware *clients*, Michael, or busdev content. The word "delaware" itself (the vendor) is allowed. Denylist terms for the linter: `michael`, `bulthe`, `busdev` (case-insensitive).
- **Commits in sb-accelerator:** Conventional Commits (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`), every message ends with the exact trailer `Co-Authored-By: Claude <noreply@anthropic.com>` (copied from bta CONTRIBUTING — this is the repo convention, use it verbatim).
- **Commits in busdev (Task 8):** trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (busdev harness convention).
- **CI job names are load-bearing:** `plugin (skill lint + tests)`, `template (structure validation)`, `plugin version (not already released)` — Task 7's ruleset requires these exact contexts; renaming one blocks every merge.
- **Anti-slop:** no speculative files, no filler sections. Every file created below is named in the bootstrap brief or required by a CI check.
- **Direct pushes to `main` are allowed and expected through Task 6.** Task 7 turns protection on; Tasks 9's verification PR and everything after go through PRs.
- **Source repo for copy-adapt:** `~/Documents/Dev/bta-agents-portal` (absolute: `/Users/bulthem/Documents/Dev/bta-agents-portal`). Read the named source file before adapting it.

---

### Task 1: Skeleton, top-level docs, plugin manifest

**Files:**
- Create: `.gitignore`, `README.md`, `CHANGELOG.md`, `registry.yaml`
- Create: `plugin/.claude-plugin/plugin.json`, `plugin/skills/README.md`
- Create: `template/README.md`, `migrations/README.md`, `playbooks/README.md`
- Create: `docs/architecture.md`, `docs/local-setup.md`, `docs/onboarding-new-builder.md`, `docs/superpowers/lessons.md`

**Interfaces:**
- Produces: `plugin/.claude-plugin/plugin.json` with `version` field — read by Task 3's version guard and named in Task 2's PR template. Directory layout consumed by every later task.

- [ ] **Step 1: Write `.gitignore`**

```gitignore
.sdd/
.DS_Store
__pycache__/
*.pyc
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Second Brain Accelerator

Product monorepo for the **Second Brain Accelerator**: a personal AI operating
system for client executives (exec + EA), deployed by delaware consultants
inside AI transformation engagements and maintained as a versioned product.

Full product design: `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md`.
Engineering conventions and the bootstrap rationale:
`docs/superpowers/specs/2026-08-22-sb-accelerator-bootstrap-brief.md`.

## Structure

| Path | What it is |
|---|---|
| `plugin/` | Claude Code plugin: skills, hooks, agents. Ships to clients via `sb-dist`. |
| `template/` | Vault skeleton: folders, `.obsidian/`, `.base` views, CLAUDE.md + context-portfolio slots. Instantiated once per client. |
| `migrations/` | Versioned structure migrations, consumed by `/upgrade-vault`. |
| `playbooks/` | Onboarding interview, pre-flight checklist, hypercare, EA training. Never ships. |
| `docs/` | Architecture, backlog model, local setup, builder onboarding. |
| `registry.yaml` | Client deployment registry (v1: file; later Airtable). |

## The four layers (what ships, what doesn't)

- **L0** ontology & taxonomy → ships (template)
- **L1** automation → ships (plugin), de-personalized
- **L2** delaware company knowledge → **never ships** (separate overlay, later)
- **L3** personal context → generated per user at onboarding, never in this repo

**Hard rule:** nothing in `plugin/` or `template/` references delaware clients,
Michael, or busdev content. CI lints this (`scripts/lint_plugin.py`).

## Contributing

See `CONTRIBUTING.md` (protected main, PRs, three CI checks) and
`docs/backlog.md` (labels, milestones, board).
```

- [ ] **Step 3: Write `CHANGELOG.md`**

```markdown
# Changelog

## 2026-08-22

- Repo bootstrapped from the busdev handover
  (busdev `delawareBusDevWorkflow#2`): skeleton, conventions
  copy-adapted from bta-agents-portal, three CI checks, labels +
  milestones + org board, seed backlog, branch protection.
```

- [ ] **Step 4: Write `registry.yaml`**

```yaml
# Client deployment registry — one entry per deployed engagement.
# v1 is this file; moves to Airtable when client count justifies it (design doc, Phase 2).
# Entry shape:
#   - client: <client-slug>
#     exec: <name or initials>
#     plugin_version: <semver deployed>
#     structure_version: <template structure-version deployed>
#     archetype: commercial-leader
#     care_package: active | lapsed | none
#     notes: ""
clients: []
```

- [ ] **Step 5: Write `plugin/.claude-plugin/plugin.json`**

```json
{
  "name": "second-brain",
  "version": "0.0.1",
  "description": "Second Brain Accelerator plugin — skills, hooks, and agents for a client executive's personal AI operating system."
}
```

- [ ] **Step 6: Write the four directory READMEs**

`plugin/skills/README.md`:

```markdown
# Skills

One directory per skill: `<skill-name>/SKILL.md` with YAML frontmatter
(`name`, `description`, `user_invocable: true`). Format spec: root `CLAUDE.md`
→ "Skill format". Ported skills record provenance in frontmatter:
`upstreamed-from: busdev@<sha>`.

Clean-room rule applies to everything in this tree — see root `CLAUDE.md`.
```

`template/README.md`:

```markdown
# Vault template

The L0 vault skeleton instantiated once per client: folder structure,
`.obsidian/` config (incl. sync exclusions for the exec-private folder),
`.base` views, a de-personalized `CLAUDE.md`, context-portfolio files with
guided placeholder slots, and a `structure-version` marker consumed by
`/upgrade-vault`.

Not yet populated — extraction from busdev is tracked in the backlog
(area:template). Once populated, `scripts/validate_template.py` requires
`template/CLAUDE.md` and `template/structure-version` to exist.
```

`migrations/README.md`:

```markdown
# Migrations

Versioned vault-structure migrations, consumed by the `/upgrade-vault` skill
on client machines (snapshot → migrate → verify → log). Migration format is
designed together with `/upgrade-vault` — tracked in the backlog (area:migrations
via the /upgrade-vault issue). Every migration must be idempotent.
```

`playbooks/README.md`:

```markdown
# Playbooks

delaware-side delivery material: onboarding interview script, pre-flight
IT checklist, hypercare guide, EA operator training outline. This directory
never ships to clients — it is part of the structural IP that stays home.
```

- [ ] **Step 7: Write `docs/architecture.md`**

```markdown
# Architecture

Authoritative product design: `superpowers/specs/2026-08-22-second-brain-accelerator-design.md`.
This page is the short orientation.

## Repo topology

busdev (lab) —/propose-upstream→ issues here —/process-upstream→ PR here.
This repo is the source of truth. Releases publish to `sb-dist`
(client-facing marketplace repo, created at design-doc step 8); clients'
Claude org admins connect `sb-dist` as a native plugin marketplace, which
syncs the plugin to exec + EA across Desktop, Cowork, and Claude Code.
Per-client feedback lands on `sb-client-<slug>` repos, never on shared repos.

## Update policy

Consultant-applied, implemented by publishing cadence: `sb-dist` only receives
a release when clients should get it (quarterly, around tune-ups). Structure
migrations are consultant-run via `/upgrade-vault`; a plugin/vault
structure-version mismatch check makes skills degrade gracefully until migrated.

## CI

Three required checks on every PR (see `.github/workflows/ci.yml`):

- `plugin (skill lint + tests)` — skill frontmatter + clean-room lint + pytest over `scripts/tests/`
- `template (structure validation)` — template skeleton invariants
- `plugin version (not already released)` — plugin/ changes require a version bump; bumped version must not be already tagged
```

- [ ] **Step 8: Write `docs/local-setup.md`**

```markdown
# Local setup

No app to run — this repo is a plugin + template + docs. You need:

- `gh` CLI, authenticated with access to `DLW-INT-BTA-BELUX`
- Python 3.13 with `pytest` and `pyyaml` (`pip install pytest pyyaml`)

## Run what CI runs

```bash
python scripts/lint_plugin.py
python scripts/validate_template.py
python -m pytest scripts/tests -q
```

## Test the plugin against a scratch vault

Instantiate the template into a throwaway directory and point Claude Code at it:

```bash
cp -R template /tmp/scratch-vault
cd /tmp/scratch-vault && claude
```

(While `template/` is unpopulated this is a no-op; the template-extraction
issue makes it real.)
```

- [ ] **Step 9: Write `docs/onboarding-new-builder.md`**

```markdown
# Onboarding a new builder

1. Read the root `CLAUDE.md` — what this is, the clean-room rule, skill format.
2. Read `CONTRIBUTING.md` — protected main, the three CI checks, commit trailer.
3. Read `docs/backlog.md` — labels, milestones, the org board.
4. Read the product design spec in `docs/superpowers/specs/` before touching
   `plugin/` or `template/` — the four-layer model decides where things go.

Repo admin today: Michael Bulthé (`bulthem_dlwr`). Security concerns go to the
admin directly, not a public issue — see `SECURITY.md`.
```

- [ ] **Step 10: Write `docs/superpowers/lessons.md`**

```markdown
# Lessons

Pitfalls agent sessions in this repo have hit. Append entries as they happen
(date, what went wrong, the rule that prevents it). Patterns that recur get
promoted into `CLAUDE.md`.

*(none yet)*
```

- [ ] **Step 11: Commit**

```bash
cd /Users/bulthem/Documents/Dev/sb-accelerator
git add -A
git commit -m "feat: repo skeleton — layout, plugin manifest, registry, orientation docs

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
```

---

### Task 2: Conventions docs — CLAUDE.md, CONTRIBUTING, SECURITY, PR template, backlog doc

**Files:**
- Create: `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/backlog.md`, `.github/pull_request_template.md`
- Read first: `/Users/bulthem/Documents/Dev/bta-agents-portal/CONTRIBUTING.md`, `/Users/bulthem/Documents/Dev/bta-agents-portal/.github/pull_request_template.md`, `/Users/bulthem/Documents/Dev/bta-agents-portal/SECURITY.md`, `/Users/bulthem/Documents/Dev/bta-agents-portal/docs/backlog.md`

**Interfaces:**
- Consumes: directory layout + plugin.json from Task 1.
- Produces: the named check list (`plugin (skill lint + tests)`, `template (structure validation)`, `plugin version (not already released)`) that Task 5's ci.yml and Task 7's ruleset must match exactly.

- [ ] **Step 1: Write `CLAUDE.md`**

```markdown
# CLAUDE.md — project conventions for Claude Code

Conventions for working in the **sb-accelerator** repo. Read before making changes.
Pitfalls prior agent sessions hit: `docs/superpowers/lessons.md`.

## What this project is

The product monorepo for the **Second Brain Accelerator**: a personal AI
operating system for client executives (exec + EA), deployed by delaware
consultants inside AI transformation engagements and maintained as a versioned
product — a Claude Code plugin (`plugin/`), a vault template (`template/`),
and structure migrations (`migrations/`), plus the delaware-side playbooks
(`playbooks/`) that never ship.

Authoritative design: `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md`.
Bootstrap rationale and conventions provenance (modeled on bta-agents-portal):
`docs/superpowers/specs/2026-08-22-sb-accelerator-bootstrap-brief.md`.

## The clean-room rule (hard rule)

**Nothing in `plugin/` or `template/` may reference delaware clients, Michael,
or busdev content.** These two trees ship to clients (source-available).
"delaware" as the vendor name is fine; client names, people names, and busdev
paths/content are not. `scripts/lint_plugin.py` greps for a denylist
(`scripts/cleanroom-denylist.txt`) in CI — but the lint is a net, not the rule.
When porting from busdev, rewrite; never copy-paste-then-trim.

## Structure

See `README.md` for the directory table. Quick rules:

- Ported skills record provenance in frontmatter: `upstreamed-from: busdev@<sha>`.
- `plugin/CLAUDE.md` (if added) is internal instructions — excluded from the
  version-bump requirement, like bta's.
- Client registry: `registry.yaml`. One entry per deployment. No secrets in it.

## Skill format

Each skill: `plugin/skills/<skill-name>/SKILL.md` with YAML frontmatter:

```yaml
---
name: skill-name            # command name without the /
description: What it does. Triggers when user invokes /skill-name.
user_invocable: true
---
```

`name` must match the directory name. `scripts/lint_plugin.py` enforces this.

## How to test locally

```bash
python scripts/lint_plugin.py        # skill frontmatter + clean-room lint
python scripts/validate_template.py  # template skeleton invariants
python -m pytest scripts/tests -q    # validator unit tests
```

Same three things CI runs. To exercise the plugin against a vault, instantiate
`template/` into a scratch directory (`docs/local-setup.md`).

## Git & CI

- `main` is protected: branch → PR → three green checks → squash merge.
  Full flow: `CONTRIBUTING.md`.
- Every commit message ends with the exact trailer:
  `Co-Authored-By: Claude <noreply@anthropic.com>`
- Any PR touching `plugin/` (except `plugin/CLAUDE.md`) must bump the version
  in `plugin/.claude-plugin/plugin.json` — CI's version guard enforces it.
- Backlog model (labels, milestones, board): `docs/backlog.md`.
```

- [ ] **Step 2: Write `CONTRIBUTING.md`** — adapted from bta's (read it first). Keep the golden rule, branch naming, small commits, squash merge, admin review exemption, `/review` rationing. Swap the check names and local commands. Full content:

```markdown
# Contributing

This repo is built by a team that includes people who are not full-time engineers. The rules
below keep `main` always working and every change validated by CI. They are simple on purpose.

## The golden rule: never commit straight to `main`

`main` is **protected** — you cannot push to it directly. All changes go through:

**branch → commit → open a pull request → pass the three CI checks → (contributors: get 1
approval) → merge.**

## Step by step

**1. Make a branch** off the latest `main`:
```bash
git switch main
git pull
git switch -c <type>/<short-description>
```
Use a `<type>` of `feat`, `fix`, `chore`, `docs`, `refactor`, or `test`. Example:
`git switch -c feat/setup-my-brain-skill`.

**2. Work in small commits.** Commit often, with small, self-contained changes — it makes review
and rollback easy.

**3. Push your branch:**
```bash
git push -u origin HEAD
```

**4. Open a pull request:**
```bash
gh pr create --fill
```

**5. Wait for the checks** — the GitHub Actions `CI` workflow (`.github/workflows/ci.yml`) runs
automatically and posts three status checks onto your PR: `plugin (skill lint + tests)`,
`template (structure validation)` and `plugin version (not already released)`. All three must
be green to merge.

**6. Get a review, unless you're a repo admin.** Non-admin contributors need 1 approving review
before merge; repo admins/owners are exempt from the review requirement (but never from the
green checks — see `main-ci` below). Once your PR is approved (or you're exempt) and the checks
are green, merge via the GitHub UI (squash merge) or:
```bash
gh pr merge --squash --delete-branch
```

## Commit message conventions (Conventional Commits)

Format: `<type>: <imperative summary>`. Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`.

Examples:

- `feat: add /upgrade-vault snapshot step`
- `fix: lint skill names against directory names`
- `docs: explain the structure-version marker`

**Every commit message MUST end with this exact trailer line:**
```
Co-Authored-By: Claude <noreply@anthropic.com>
```

## Before you open a PR

- `python scripts/lint_plugin.py` passes (skill frontmatter + clean-room lint).
- `python scripts/validate_template.py` passes.
- `python -m pytest scripts/tests -q` passes.
- If you touched `plugin/` (other than `plugin/CLAUDE.md`): bump the version in
  `plugin/.claude-plugin/plugin.json` — the version guard fails PRs that touch the plugin
  without a bump, or bump to an already-released version.
- You did not commit any secret, client name, or vault content.

## Automated code review (`claude-review`)

Opening a non-draft PR also triggers `claude-review`, which posts findings as inline comments
(or a one-line "No issues found"). Two things to know:

- **It reviews the commit you opened the PR with, and does not re-run when you push.** The
  check then disappears from the rollup rather than going stale — which looks identical to
  "nothing to report".
- **To re-review, comment `/review` — but don't do it after every fix.** A re-review costs the
  same as the original (full diff), so ration it: re-run when your fix created code the first
  review never saw — you implemented something *different* from what a finding suggested, or
  the fix added a branch or error path, or grew into a redesign. Skip it when you applied a
  suggestion literally, changed only docs/comments/tests, or the fixed path is now covered by
  a test you added.

## Branch protection

`main` is protected by two GitHub rulesets:

- **`main-ci`** — requires a pull request and the three `CI` workflow checks to pass, with
  **no bypass** (applies to everyone, admins included — you cannot merge a red build).
- **`main-review`** — requires **1 approving review**, bypassed by repo admins/owners.

Direct pushes and force-pushes to `main` are blocked for everyone.
```

- [ ] **Step 3: Write `SECURITY.md`**

```markdown
# Security

## Secrets this project uses

| Secret | What it's for | Where it lives |
|---|---|---|
| `ANTHROPIC_API_KEY` | The `claude.yml` assistant and `claude-code-review.yml` workflows | GitHub Actions secret on this repo |
| `PROJECTS_TOKEN` | `issue-backlog-defaults.yml` adds new issues to the org board | GitHub Actions secret on this repo (PAT with `project` scope) |
| `DIST_REPO_TOKEN` | Publishing releases to `sb-dist` (later — design-doc step 8) | GitHub Actions secret, created with the release pipeline |
| Per-client tokens | `issues:write` on that client's `sb-client-<slug>` + `contents:read` on `sb-dist` | Minted at provisioning; never stored in this repo |

**The rule:** no secret value ever appears in this repo — not in a file, an issue, a PR
description, or a workflow log. If you ever think "I'll just paste the key for a second" — don't.

## What must never be in this repo at all

- Client vault content, client names in `plugin/` or `template/` (clean-room rule — root
  `CLAUDE.md`), or anything from a client engagement beyond `registry.yaml`'s deployment rows.
- Personal content from the busdev lab. Porting is a rewrite, not a copy.

## Rotate on handovers

If the repo, a token, or the org changes hands, rotate `PROJECTS_TOKEN`, `ANTHROPIC_API_KEY`,
and any `DIST_REPO_TOKEN` / per-client tokens involved. Rotating costs minutes; a stale token
in the wrong hands does not.

## Reporting a concern

Internal delaware repo, no external users. Raise security issues directly with the repo
admin(s) — `docs/onboarding-new-builder.md` says who that is — rather than filing a public issue.
```

- [ ] **Step 4: Write `.github/pull_request_template.md`**

```markdown
## What & why

<!-- What does this change do, and why? -->

## Checklist

- [ ] Skill lint passes locally: `python scripts/lint_plugin.py`
- [ ] Template validates locally: `python scripts/validate_template.py`
- [ ] Validator tests pass locally: `python -m pytest scripts/tests -q`
- [ ] No secret, client name, or vault content is committed (clean-room rule — root `CLAUDE.md`).
- [ ] **Plugin version:** if this PR touches `plugin/` (other than `plugin/CLAUDE.md`), the version in `plugin/.claude-plugin/plugin.json` is bumped.
- [ ] **Migrations:** any new migration in `migrations/` is idempotent (safe to run twice).

## Linked issue

Closes #

---

<!--
Claude review: runs on open / ready-for-review / reopen — NOT on push. After pushing fixes the
`claude-review` check goes *absent* (which looks like "nothing to report").

Comment `/review` to re-run — but don't do it after every fix. A re-review costs the same as the
original (full diff). Re-run when your fix created code the first review never saw. Skip it when
you applied a suggestion literally or changed only docs/comments/tests.
-->
```

- [ ] **Step 5: Write `docs/backlog.md`** — same four-axis model as bta's (read it first), new labels/milestones/board. Full content:

```markdown
# Backlog & Issue Tracking — SB Accelerator

GitHub-native: plain GitHub Issues organized by an org Projects v2 board. Everything is driven
from the `gh` CLI, so it works from the terminal and from Claude Code.

## Where it lives

| Surface | Link |
|---|---|
| Issues | <https://github.com/DLW-INT-BTA-BELUX/sb-accelerator/issues> |
| Board ("SB Accelerator Backlog") | *(org project — URL in `.github/workflows/issue-backlog-defaults.yml`)* |

## The model — four axes

| Axis | Tool | Per issue | Answers |
|---|---|---|---|
| **What kind of work** | `type:` **label** | many | feature / infra / chore (bug = built-in `bug`) |
| **Which part of the product** | `area:` **label** | many | plugin / template / playbooks / migrations / dist |
| **When it ships** | **Milestone** | one | v0.1 / v0.2 / v1.0 / Unscheduled |
| **How urgent / what state** | Board **Priority** + **Status** fields | one each | High·Med·Low / Todo·In Progress·Done |

Large items break down with native **sub-issues** (parent shows an auto progress bar) — e.g.
the "Port core skills" parent has one sub-issue per skill.

## Conventions

**Labels**

- `area:plugin` · `area:template` · `area:playbooks` · `area:migrations` · `area:dist`
- `type:feature` · `type:infra` · `type:chore` (+ built-in `bug`)
- **Inflow labels:** `upstream-proposal` (from busdev `/propose-upstream`) ·
  `field-proposal` (from consultant engagements and triaged client feedback)

**Milestones**

| Milestone | Theme |
|---|---|
| `v0.1 walking skeleton` | Template extraction + core skills ported + net-new skills |
| `v0.2 internal dry run` | Playbooks + full runbook rehearsal on a delaware colleague |
| `v1.0 pilot` | sb-dist + release pipeline + provisioning + first client |
| `Unscheduled` | Default for new inflow until triage assigns a real milestone |

## How to add work

Requires `gh` v2.94.0+ (native `--parent` for sub-issues) and a token with `repo` + `project`
scopes (`gh auth refresh -s project` for the board).

```bash
REPO=DLW-INT-BTA-BELUX/sb-accelerator

gh issue create -R $REPO --title "…" --body "…" \
  --milestone "v0.1 walking skeleton" --label "area:plugin" --label "type:feature"

# Sub-issue under a parent
gh issue create -R $REPO --title "…" --body "…" --parent <N> \
  --label "area:plugin" --label "type:feature"
```

Close issues from commits with `Closes #<N>` in the PR — the squash merge links and closes them.

## Views (web UI only — not scriptable)

The board ships with a Table view. Add in the UI (**+ New view**): a **Board** view grouped by
**Status** (kanban) and a **Roadmap** view laid out by **Milestone** (timeline).
```

- [ ] **Step 6: Commit**

```bash
cd /Users/bulthem/Documents/Dev/sb-accelerator
git add -A
git commit -m "docs: conventions — CLAUDE.md (clean-room rule, skill format), CONTRIBUTING, SECURITY, PR template, backlog model

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
```

---

### Task 3: Validation scripts (TDD) — skill lint, template validation, version guard

**Files:**
- Create: `scripts/lint_plugin.py`, `scripts/validate_template.py`, `scripts/check-plugin-version.sh`, `scripts/cleanroom-denylist.txt`
- Test: `scripts/tests/test_lint_plugin.py`, `scripts/tests/test_validate_template.py`

**Interfaces:**
- Consumes: `plugin/.claude-plugin/plugin.json` (Task 1), directory layout.
- Produces: `lint_plugin.py` and `validate_template.py`, each exposing `main(root: Path) -> list[str]` (returns list of problem strings, empty = pass; the `if __name__` block prints problems and exits 1 if any). `check-plugin-version.sh [--baseline <ver>]` exits non-zero on violation. Task 5's ci.yml calls all three.

- [ ] **Step 1: Write `scripts/cleanroom-denylist.txt`**

```
# Clean-room denylist — case-insensitive substrings that must not appear
# anywhere under plugin/ or template/. Lines starting with # are comments.
# Add client slugs here as engagements begin. "delaware" (the vendor) is allowed.
michael
bulthe
busdev
```

- [ ] **Step 2: Write the failing tests for `lint_plugin.py`**

`scripts/tests/test_lint_plugin.py`:

```python
"""Tests build a fake repo tree in tmp_path and run the linter's main() against it."""
from pathlib import Path

from lint_plugin import main


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "plugin" / "skills").mkdir(parents=True)
    (tmp_path / "template").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "cleanroom-denylist.txt").write_text(
        "# comment\nmichael\nbusdev\n", encoding="utf-8"
    )
    return tmp_path


def write_skill(root: Path, dirname: str, frontmatter: str, body: str = "Body.") -> None:
    d = root / "plugin" / "skills" / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}---\n\n{body}\n", encoding="utf-8")


def test_empty_plugin_passes(tmp_path):
    assert main(make_repo(tmp_path)) == []


def test_valid_skill_passes(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\ndescription: Checks vault health. Triggers when user invokes /health-check.\nuser_invocable: true\n")
    assert main(root) == []


def test_missing_frontmatter_fails(tmp_path):
    root = make_repo(tmp_path)
    d = root / "plugin" / "skills" / "broken"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("No frontmatter here.\n", encoding="utf-8")
    problems = main(root)
    assert any("broken" in p and "frontmatter" in p for p in problems)


def test_name_mismatch_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: wrong-name\ndescription: X.\nuser_invocable: true\n")
    problems = main(root)
    assert any("name" in p for p in problems)


def test_missing_description_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\nuser_invocable: true\n")
    problems = main(root)
    assert any("description" in p for p in problems)


def test_cleanroom_violation_in_plugin_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\ndescription: X.\nuser_invocable: true\n", body="Ping Michael when done.")
    problems = main(root)
    assert any("michael" in p.lower() for p in problems)


def test_cleanroom_violation_in_template_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "template" / "CLAUDE.md").write_text("Sync with busdev daily.\n", encoding="utf-8")
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


def test_cleanroom_scan_skips_binary_and_comments(tmp_path):
    root = make_repo(tmp_path)
    (root / "plugin" / "logo.png").write_bytes(b"\x89PNG\x00michael\x00")
    assert main(root) == []
```

`scripts/tests/test_validate_template.py`:

```python
from pathlib import Path

from validate_template import main


def test_missing_template_dir_fails(tmp_path):
    problems = main(tmp_path)
    assert any("template" in p for p in problems)


def test_readme_only_template_passes(tmp_path):
    (tmp_path / "template").mkdir()
    (tmp_path / "template" / "README.md").write_text("stub", encoding="utf-8")
    assert main(tmp_path) == []


def test_populated_template_requires_markers(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    problems = main(tmp_path)
    assert any("CLAUDE.md" in p for p in problems)
    assert any("structure-version" in p for p in problems)


def test_populated_template_with_markers_passes(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    (t / "CLAUDE.md").write_text("vault instructions", encoding="utf-8")
    (t / "structure-version").write_text("1\n", encoding="utf-8")
    assert main(tmp_path) == []
```

Also create `scripts/tests/conftest.py` so the tests can import the scripts:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/bulthem/Documents/Dev/sb-accelerator && python3 -m pytest scripts/tests -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lint_plugin'` (and `validate_template`). If `pytest`/`yaml` are missing locally, `pip3 install pytest pyyaml` first.

- [ ] **Step 4: Write `scripts/lint_plugin.py`**

```python
#!/usr/bin/env python3
"""Skill frontmatter lint + clean-room scan for plugin/ and template/.

Two jobs:
1. Every plugin/skills/*/SKILL.md has YAML frontmatter with name (matching its
   directory), description, and user_invocable: true.
2. No denylisted term (scripts/cleanroom-denylist.txt, case-insensitive
   substrings) appears in any text file under plugin/ or template/ — the
   clean-room rule from CLAUDE.md. These trees ship to clients.

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import sys
from pathlib import Path

import yaml


def load_denylist(root: Path) -> list[str]:
    path = root / "scripts" / "cleanroom-denylist.txt"
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def lint_skills(root: Path) -> list[str]:
    problems = []
    skills_dir = root / "plugin" / "skills"
    if not skills_dir.is_dir():
        return problems
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        rel = skill_md.relative_to(root)
        if not skill_md.is_file():
            problems.append(f"{d.relative_to(root)}: missing SKILL.md")
            continue
        fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if fm is None:
            problems.append(f"{rel}: missing or unparseable YAML frontmatter")
            continue
        if fm.get("name") != d.name:
            problems.append(f"{rel}: frontmatter name {fm.get('name')!r} != directory name {d.name!r}")
        if not fm.get("description"):
            problems.append(f"{rel}: frontmatter missing description")
        if fm.get("user_invocable") is not True:
            problems.append(f"{rel}: frontmatter missing user_invocable: true")
    return problems


def scan_cleanroom(root: Path, terms: list[str]) -> list[str]:
    problems = []
    for tree in ("plugin", "template"):
        base = root / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue  # binary — filenames are still checked below
            lower = text.lower()
            for term in terms:
                if term in lower:
                    for i, line in enumerate(lower.splitlines(), 1):
                        if term in line:
                            problems.append(
                                f"{path.relative_to(root)}:{i}: clean-room violation: {term!r}"
                            )
            for term in terms:
                if term in path.name.lower():
                    problems.append(f"{path.relative_to(root)}: clean-room violation in filename: {term!r}")
    return problems


def main(root: Path) -> list[str]:
    return lint_skills(root) + scan_cleanroom(root, load_denylist(root))


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
```

- [ ] **Step 5: Write `scripts/validate_template.py`**

```python
#!/usr/bin/env python3
"""Template skeleton invariants.

While template/ holds only its README, that's the valid bootstrap state.
The moment anything else exists (the template-extraction issue), the template
must carry its two markers: CLAUDE.md (vault instructions) and
structure-version (consumed by /upgrade-vault).

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import sys
from pathlib import Path


def main(root: Path) -> list[str]:
    template = root / "template"
    if not template.is_dir():
        return ["template/ directory is missing"]
    entries = [p for p in template.rglob("*") if p.name != ".gitkeep"]
    non_readme = [p for p in entries if p.relative_to(template) != Path("README.md")]
    if not non_readme:
        return []  # unpopulated skeleton — valid bootstrap state
    problems = []
    if not (template / "CLAUDE.md").is_file():
        problems.append("populated template/ is missing CLAUDE.md")
    if not (template / "structure-version").is_file():
        problems.append("populated template/ is missing the structure-version marker")
    return problems


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/bulthem/Documents/Dev/sb-accelerator && python3 -m pytest scripts/tests -q`
Expected: all PASS.

- [ ] **Step 7: Write `scripts/check-plugin-version.sh`** — port of bta's version-guard logic (bta ci.yml `plugin_version_guard` job + `release-plugin.sh --check-only`), self-contained because sb-dist doesn't exist yet: released = a `plugin-v<version>` tag on *this* repo. When sb-dist + the release pipeline land (backlog, area:dist), point the tag check there instead.

```bash
#!/usr/bin/env bash
# Version guard: a PR that touches plugin/ (except plugin/CLAUDE.md) must bump
# plugin/.claude-plugin/plugin.json to a version that is (a) different from the
# target branch's and (b) not already released.
#
# "Released" today = tag plugin-v<version> exists on origin (sb-dist doesn't
# exist yet; the release-pipeline issue moves this check there).
#
# Usage: check-plugin-version.sh [--baseline <version>]
# Called from CI with the target branch's version as --baseline; the diff
# HEAD~1..HEAD is the PR's net change (merge-commit checkout, fetch-depth: 2).
set -euo pipefail

baseline=""
if [ "${1:-}" = "--baseline" ]; then
  baseline="${2:-}"
fi

if ! changed=$(git diff --name-only HEAD~1 HEAD 2>/dev/null) || [ -z "$changed" ]; then
  # Fail-open on an unknown diff: "current version already released" is the
  # normal state between bumps, so guessing would fail every unrelated PR.
  echo "::warning::Could not diff HEAD~1..HEAD - skipping the plugin version guard."
  exit 0
fi

plugin_changed=$(printf '%s\n' "$changed" | grep -E '^plugin/' | grep -vx 'plugin/CLAUDE.md' || true)
if [ -z "$plugin_changed" ]; then
  echo "This PR does not touch plugin/ (ignoring plugin/CLAUDE.md) - nothing to check."
  exit 0
fi
echo "This PR touches plugin/:"
printf '%s\n' "$plugin_changed"

version=$(python3 -c "import json; print(json.load(open('plugin/.claude-plugin/plugin.json'))['version'])")
echo "plugin.json version: $version (target branch: ${baseline:-<none>})"

if [ -n "$baseline" ] && [ "$version" = "$baseline" ]; then
  echo "::error::plugin/ changed but the version ($version) equals the target branch's - bump it."
  exit 1
fi

if git ls-remote --exit-code --tags origin "refs/tags/plugin-v$version" >/dev/null 2>&1; then
  echo "::error::version $version is already released (tag plugin-v$version exists)."
  exit 1
fi

echo "Version guard OK."
```

- [ ] **Step 8: Make it executable and smoke-test it**

Run:
```bash
cd /Users/bulthem/Documents/Dev/sb-accelerator
chmod +x scripts/check-plugin-version.sh
./scripts/check-plugin-version.sh
```
Expected: either the fail-open warning (single-commit history) or "does not touch plugin/" — exit 0 both ways.

- [ ] **Step 9: Run both validators against the real repo**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && echo VALIDATORS-OK`
Expected: `VALIDATORS-OK` (empty plugin passes vacuously; README-only template passes).

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: CI validators - skill lint + clean-room scan, template invariants, plugin version guard

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
```

---

### Task 4: GitHub plumbing — labels, milestones, org Projects board

**Files:** none (all `gh` calls against `DLW-INT-BTA-BELUX/sb-accelerator` and the org).

**Interfaces:**
- Produces: labels + milestones consumed by Task 6's seed issues; the board URL + number consumed by Task 5's `issue-backlog-defaults.yml` and Task 6's `gh project item-add`. **Record the board number and URL in the task report.**

- [ ] **Step 1: Create labels**

```bash
REPO=DLW-INT-BTA-BELUX/sb-accelerator
for l in "area:plugin" "area:template" "area:playbooks" "area:migrations" "area:dist"; do
  gh label create "$l" -R $REPO --color 0E8A16; done
for l in "type:feature" "type:infra" "type:chore"; do
  gh label create "$l" -R $REPO --color 1D76DB; done
gh label create "upstream-proposal" -R $REPO --color D93F0B --description "From busdev /propose-upstream"
gh label create "field-proposal" -R $REPO --color FBCA04 --description "From consultant engagements / triaged client feedback"
```

- [ ] **Step 2: Create milestones**

```bash
for m in "v0.1 walking skeleton" "v0.2 internal dry run" "v1.0 pilot" "Unscheduled"; do
  gh api "repos/$REPO/milestones" -f title="$m"; done
```

- [ ] **Step 3: Create the org Projects v2 board + Priority field**

```bash
gh project create --owner DLW-INT-BTA-BELUX --title "SB Accelerator Backlog" --format json
# note the "number" and "url" from the output, then:
gh project field-create <NUMBER> --owner DLW-INT-BTA-BELUX \
  --name "Priority" --data-type SINGLE_SELECT \
  --single-select-options "High,Medium,Low"
```

- [ ] **Step 4: Verify**

```bash
gh label list -R $REPO | sort
gh api "repos/$REPO/milestones" --jq '.[].title'
gh project list --owner DLW-INT-BTA-BELUX
```
Expected: 10 labels, 4 milestones, board listed with its number.

- [ ] **Step 5: Update `docs/backlog.md`** — replace the board-link placeholder row with the real URL from Step 3. Commit:

```bash
git add docs/backlog.md
git commit -m "docs: record the SB Accelerator Backlog board URL

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
```

---

### Task 5: Workflows, issue templates, .claude/settings.json

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/claude.yml`, `.github/workflows/claude-code-review.yml`, `.github/workflows/issue-backlog-defaults.yml`
- Create: `.github/ISSUE_TEMPLATE/upstream-proposal.md`, `.github/ISSUE_TEMPLATE/field-proposal.md`
- Create: `.claude/settings.json`
- Read first: all four workflow files + `.claude/settings.json` in `/Users/bulthem/Documents/Dev/bta-agents-portal`

**Interfaces:**
- Consumes: validator scripts (Task 3), board URL (Task 4).
- Produces: the three CI check contexts Task 7's ruleset requires, exactly as named in Global Constraints.

- [ ] **Step 1: Write `.github/workflows/ci.yml`** — new content, bta's shape (named jobs = status-check contexts, concurrency cancel for PRs):

```yaml
# CI - the three required status checks (the `main-ci` ruleset requires the
# three job names below as contexts, so renaming a job here without updating
# the ruleset blocks every merge).
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

# Superseded PR pushes cancel their in-flight run; main runs never cancel.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  plugin:
    name: plugin (skill lint + tests)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: install deps
        run: pip install pytest pyyaml
      - name: skill lint + clean-room scan
        run: python scripts/lint_plugin.py
      - name: validator unit tests
        run: python -m pytest scripts/tests -q

  template:
    name: template (structure validation)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: template structure validation
        run: python scripts/validate_template.py

  plugin_version_guard:
    name: plugin version (not already released)
    # PR builds only, same rationale as bta's guard: on main the steady state
    # right after a release is "current version already tagged", which would
    # red-X every later push.
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # Merge-commit checkout: HEAD~1 is the target-branch tip, so
          # HEAD~1..HEAD is the PR's net change.
          fetch-depth: 2
          # persist-credentials stays ON (the checkout default) - unlike bta,
          # the tag check runs against THIS repo, so GITHUB_TOKEN is exactly
          # the credential git ls-remote needs.
      - name: fail if plugin.json version is unbumped or already released
        run: |
          set -euo pipefail
          baseline=$(git show HEAD~1:plugin/.claude-plugin/plugin.json 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])" 2>/dev/null) || baseline=""
          scripts/check-plugin-version.sh ${baseline:+--baseline "$baseline"}
```

- [ ] **Step 2: Copy `.github/workflows/claude.yml`** from bta near-verbatim (read the source; it is generic — @claude on issues/PR comments, `anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}`). No adaptations needed.

- [ ] **Step 3: Adapt `.github/workflows/claude-code-review.yml`** from bta. Keep verbatim: the trigger block **with its cost-decision comments** (no `synchronize`; `ready_for_review` load-bearing; `/review` on-demand job with the write-access gate), the job `if:`, permissions, `PR_NUMBER` env, checkout with `fetch-depth: 0` + the PR-head `ref:` expression, the plugin invocation (`plugin_marketplaces`, `plugins: 'code-review@claude-code-plugins'`, `--comment` and its comment, `track_progress: false` and its comment, `display_report: true`), and headless-constraint prompt items 1 and 2. Change only:
  - **Delete** the four test-environment steps (`Set up Python 3.13`, `Set up Node 22`, `Install gateway deps`, `Install frontend deps`) — this repo has no gateway/frontend; the reviewer needs no pre-installed deps beyond `pip install pytest pyyaml`, so replace the four steps with a single step named `install validator deps` running `pip install pytest pyyaml`.
  - **Prompt constraint 3** — replace the bta sentence about pre-run suites with: `The test suites are NOT pre-run here; ci.yml runs them as required checks on this PR (plugin lint+tests, template validation, version guard). Read their outcomes with gh api repos/{owner}/{repo}/commits/<sha>/check-runs (NOT gh pr checks). Run targeted tests yourself only when checking a specific hypothesis: python -m pytest scripts/tests -q, python scripts/lint_plugin.py, python scripts/validate_template.py.`
  - **`--allowedTools` list** — keep `Task,Read,Glob,Grep,mcp__github_inline_comment__create_inline_comment` and all `Bash(gh …)` / `Bash(git …)` entries; replace the three bta test entries (`python -m pytest`, both `npm --prefix frontend …`) with `Bash(python -m pytest:*),Bash(python scripts/lint_plugin.py:*),Bash(python scripts/validate_template.py:*)`.

- [ ] **Step 4: Adapt `.github/workflows/issue-backlog-defaults.yml`** from bta: copy verbatim, change the board name in the comment/job name to "SB Accelerator Backlog" and `project-url` to the URL recorded in Task 4 (shape: `https://github.com/orgs/DLW-INT-BTA-BELUX/projects/<NUMBER>`). Keep the pinned `actions/add-to-project` SHA, `${{ secrets.PROJECTS_TOKEN }}`, and the "Unscheduled"-milestone default job exactly as in bta.

- [ ] **Step 5: Write the two issue templates**

`.github/ISSUE_TEMPLATE/upstream-proposal.md`:

```markdown
---
name: Upstream proposal (from busdev)
about: A busdev lab pattern proven product-worthy — filed by /propose-upstream
labels: upstream-proposal
---

## What it does

<!-- 2-3 sentences -->

## Files involved (busdev paths)

## Vault sha

`busdev@<sha>`

## Usage evidence

<!-- how often used, example outcomes -->

## Couplings to strip

<!-- delaware/client/personal references the genericization rewrite must remove -->
```

`.github/ISSUE_TEMPLATE/field-proposal.md`:

```markdown
---
name: Field proposal (from an engagement)
about: Consultant field feedback or a triaged client feedback item worth productizing
labels: field-proposal
---

## What happened / what's needed

## Engagement context

<!-- which deployment, plugin + structure version (registry.yaml row) -->

## Proposed change

<!-- which area: plugin / template / playbooks / migrations / dist -->
```

- [ ] **Step 6: Write `.claude/settings.json`** — port from bta: keep `$schema`, `extraKnownMarketplaces` + `enabledPlugins` (superpowers), and the **first** SessionStart hook (the git-freshness check — copy its `command` string byte-for-byte; it is repo-agnostic). Drop the second SessionStart hook (worktree-deps — no deps here). Replace `permissions` with:

```json
"permissions": {
  "allow": [
    "Bash(python -m pytest:*)",
    "Bash(python3 -m pytest:*)",
    "Bash(python scripts/lint_plugin.py:*)",
    "Bash(python scripts/validate_template.py:*)",
    "Bash(python3 scripts/lint_plugin.py:*)",
    "Bash(python3 scripts/validate_template.py:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr list:*)",
    "Bash(gh issue view:*)",
    "Bash(gh issue list:*)"
  ],
  "ask": [
    "Bash(git push --force:*)",
    "Bash(git push * main)",
    "Bash(git push *:main)"
  ]
}
```

- [ ] **Step 7: Validate YAML locally**

Run: `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('YAML-OK')"`
Expected: `YAML-OK`.

- [ ] **Step 8: Commit and verify CI runs**

```bash
git add -A
git commit -m "feat: CI + Claude workflows, issue templates, Claude Code settings

Co-Authored-By: Claude <noreply@anthropic.com>"
git push
sleep 30 && gh run list -R DLW-INT-BTA-BELUX/sb-accelerator --limit 3
```
Expected: a `CI` run on main; wait for it (`gh run watch <id> -R …` or poll) and confirm the `plugin` and `template` jobs succeed (the version guard is PR-only and won't run). If a job fails, read its log (`gh run view <id> --log-failed -R …`) and fix before proceeding.

---

### Task 6: Seed the backlog (11 issues + 9 sub-issues, board-add)

**Files:** none (all `gh`). **Read first:** the seed-backlog section of the bootstrap brief spec and the v1 BOM section of the design spec (both in `docs/superpowers/specs/`).

**Interfaces:**
- Consumes: labels + milestones + board number (Task 4). Requires `gh --version` ≥ 2.94 for `--parent`; if older, create the child issue plainly, then link with the GraphQL fallback given in Step 3.
- Produces: issue numbers — **record the mapping (title → #) in the task report**; the busdev issue-#2 close-out comment (Task 9) links the parent skill issue.

- [ ] **Step 1: Create the 11 top-level issues**

Milestones: items 1–7 → `v0.1 walking skeleton`; item 8–9 → `v0.2 internal dry run`; items 10–11 → `v1.0 pilot`. Every body cites the spec section it comes from. Run (one `gh issue create` per item):

```bash
REPO=DLW-INT-BTA-BELUX/sb-accelerator
S="docs/superpowers/specs"

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:template" --label "type:feature" \
  --title "Template extraction from busdev (L0, clean-room)" \
  --body "Extract the L0 vault skeleton from busdev as the client template: folders, .obsidian/ config incl. sync exclusions (exec-private folder), .base views, de-personalized CLAUDE.md, context portfolio with guided placeholder slots, and the structure-version marker. Clean-room rewrite, not a copy (root CLAUDE.md hard rule). Spec: $S/2026-08-22-second-brain-accelerator-design.md → v1 BOM item 1. Once populated, scripts/validate_template.py requires template/CLAUDE.md + template/structure-version."

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:plugin" --label "type:feature" \
  --title "Port core skills from busdev (parent)" \
  --body "Parent for the genericization rewrite of the core busdev skills (v1 BOM item 2, ~10 skills; /health-check and /report-feedback are tracked as their own issues). One sub-issue per skill. Each port records provenance in frontmatter: upstreamed-from: busdev@<sha>. Spec: $S/2026-08-22-second-brain-accelerator-design.md → v1 Bill of Materials."

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:plugin" --label "type:feature" \
  --title "/setup-my-brain — onboarding interview skill (net-new)" \
  --body "Runs live in Cowork during onboarding Session 1: role, priorities, key people, active projects, meeting rhythm, briefing preferences. Generates the context portfolio + seeds vault objects from conversation + calendar/mail via the M365 connector. Must end with the live wow: the first morning brief about the exec's actual tomorrow. Spec: design doc → Onboarding journey + v1 BOM item 3."

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:plugin" --label "area:migrations" --label "type:feature" \
  --title "/upgrade-vault — snapshot + migrate + log (net-new)" \
  --body "Consultant-run at tune-ups. Takes a timestamped local vault snapshot (zip, keep last 3, excluded from sync), applies pending migrations from migrations/ (idempotent), verifies, appends to a migration log (structure-version, date, plugin version, outcome) in the vault config folder. Defines the migration format together with this skill. Spec: design doc → Client-Side Architecture (no client-side git) + v1 BOM item 4."

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:plugin" --label "type:feature" \
  --title "/health-check — content-free metrics report (net-new)" \
  --body "Run/shared by the EA during hypercare: capture volume, brief success rate, stale objects. Strictly content-free — no vault content, no names — the consultant cannot read the vault after handover by design. Spec: design doc → Onboarding journey (weeks 2-4 hypercare) + v1 BOM item 2."

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:plugin" --label "type:feature" \
  --title "/process-upstream — turn upstream-proposal issues into PRs (net-new)" \
  --body "Reads an upstream-proposal issue (filed from busdev by /propose-upstream — that twin lives in the busdev repo, not here), reads the referenced vault files (flags drift if the vault moved past the recorded sha), performs the genericization rewrite, opens a PR referencing the issue, records upstreamed-from: busdev@<sha> in skill frontmatter. Also consumes field-proposal issues — same funnel. Spec: design doc → Upstream flow + v1 BOM item 5."

gh issue create -R $REPO --milestone "v0.1 walking skeleton" --label "area:plugin" --label "type:feature" \
  --title "/report-feedback — scrubbed, approval-gated client feedback (net-new)" \
  --body "Exec/EA reports breakage or improvement ideas from inside their workflow. Hard scrubbing rule: draft carries plugin version, structure-version, skill involved, expected-vs-actual — zero vault content, client names, or people names. Always shown for approval before sending; never auto-sent. Files an issue on the client's own sb-client-<slug> repo (issues:write token). Includes the proactive nudge rule in the template CLAUDE.md (offer to report on broken skill / repeated friction). Spec: design doc → Feedback loop + v1 BOM item 2."

gh issue create -R $REPO --milestone "v0.2 internal dry run" --label "area:playbooks" --label "type:feature" \
  --title "Playbooks: onboarding interview script + pre-flight checklist" \
  --body "The delaware-side delivery material for v1: the Session-1 interview script and the pre-flight IT checklist (Claude Team/Enterprise seat, MDM allows Obsidian + Claude Desktop, M365 tenant consent, data-flow one-pager, recording-consent legal check, recorder provisioning, EA scope conversation). Hypercare guide + EA training outline follow as needed. Spec: design doc → delaware-Side Operations + v1 BOM items 6-7."

gh issue create -R $REPO --milestone "v0.2 internal dry run" --label "type:chore" \
  --title "Internal dry run: deploy to a delaware colleague + assistant as fake client" \
  --body "Full runbook rehearsal — pre-flight, provision, Session 1 + 1b + 2, hypercare with /health-check — against a friendly internal exec+EA pair before any client sees this. Exit criteria: the runbook runs end-to-end without improvisation. Spec: design doc → Next Steps item 7."

gh issue create -R $REPO --milestone "v1.0 pilot" --label "area:dist" --label "type:infra" \
  --title "sb-dist + release pipeline (tag-triggered publish)" \
  --body "Create the client-facing sb-dist repo (marketplace.json + released plugin/template versions, written exclusively by the release pipeline on tag). Publishing cadence IS the update policy: sb-dist only receives a release when clients should get it (quarterly, around tune-ups). Also: move scripts/check-plugin-version.sh's released-tag check from this repo's plugin-v* tags to sb-dist. Distribution precedent: bta-agents-portal/docs/it-request-plugin-distribution.md. Spec: design doc → Repo Topology + Next Steps item 8."

gh issue create -R $REPO --milestone "v1.0 pilot" --label "area:dist" --label "type:infra" \
  --title "Per-client provisioning script: sb-client-<slug> repo + fine-grained token" \
  --body "At provisioning: create the delaware-owned sb-client-<slug> feedback repo, mint the client's fine-grained token (issues:write on their sb-client repo, contents:read on sb-dist), register the deployment in registry.yaml. Feedback must never land on shared repos (cross-client visibility). Spec: design doc → Feedback loop + delaware-Side Operations step 2."
```

- [ ] **Step 2: Note the number of the parent issue** ("Port core skills from busdev (parent)") from Step 1's output — call it `PARENT` below.

- [ ] **Step 3: Create the 9 sub-issues under `PARENT`**

Each: `--label "area:plugin" --label "type:feature"`, milestone `v0.1 walking skeleton`, title `Port: <name>`, body naming the busdev source + the couplings to strip. The nine (busdev source in parens): meeting capture/processing (`process-intake` + meeting-brief pattern), voice processing (`process-voice`), recorder transcript sync (`sync-plaud`, genericized off Plaud specifics where possible), morning brief (`morning-brief`), evening brief (`evening-sync`), new opportunity (`new-opportunity`), projects (`new-project` + project index pattern), dossiers (`update-dossier`), decision notes (the decision-note pattern from busdev CLAUDE.md/ontology — a pattern port, not a skill port).

```bash
gh issue create -R $REPO --parent $PARENT --milestone "v0.1 walking skeleton" \
  --label "area:plugin" --label "type:feature" \
  --title "Port: meeting capture/processing" \
  --body "busdev source: process-intake + the meeting-brief pattern. Strip: delaware knowledge-base references, client slugs, personal voice rules. upstreamed-from: busdev@<sha> in frontmatter."
# …repeat for the other 8 with their source + strip notes.
```

If `gh --version` < 2.94 (`--parent` unsupported): create without `--parent`, then link each with

```bash
gh api graphql -f query='mutation($p:ID!,$c:ID!){addSubIssue(input:{issueId:$p,subIssueId:$c}){issue{number}}}' \
  -f p=$(gh api repos/$REPO/issues/$PARENT --jq .node_id) \
  -f c=$(gh api repos/$REPO/issues/<CHILD> --jq .node_id)
```

- [ ] **Step 4: Add all 20 issues to the board**

```bash
for n in $(gh issue list -R $REPO --limit 50 --json number --jq '.[].number'); do
  gh project item-add <BOARD_NUMBER> --owner DLW-INT-BTA-BELUX \
    --url "https://github.com/$REPO/issues/$n"; done
```

(The `issue-backlog-defaults.yml` workflow won't have done this — `PROJECTS_TOKEN` isn't set yet; that's a listed human action.)

- [ ] **Step 5: Verify**

```bash
gh issue list -R $REPO --limit 50
gh issue view $PARENT -R $REPO
```
Expected: 20 open issues; parent shows 9 sub-issues.

---

### Task 7: Branch protection rulesets + end-to-end verification PR

**Files:**
- Create (transient, in the session scratchpad — not committed): `main-ci.json`, `main-review.json`
- Modify (in the verification PR): `CHANGELOG.md`

**Interfaces:**
- Consumes: the three CI contexts from Task 5, exactly as named in Global Constraints.
- Produces: protected `main`. **After this task, no direct pushes — everything via PR.**

- [ ] **Step 1: Create the `main-ci` ruleset** (PR required, three checks, squash-only, no bypass):

Write `main-ci.json`:

```json
{
  "name": "main-ci",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["squash"] } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          { "context": "plugin (skill lint + tests)" },
          { "context": "template (structure validation)" },
          { "context": "plugin version (not already released)" } ] } }
  ],
  "bypass_actors": []
}
```

Run: `gh api repos/DLW-INT-BTA-BELUX/sb-accelerator/rulesets --method POST --input main-ci.json`

- [ ] **Step 2: Create the `main-review` ruleset** (1 approval, admin bypass):

Write `main-review.json`:

```json
{
  "name": "main-review",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["squash"] } }
  ],
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ]
}
```

Run: `gh api repos/DLW-INT-BTA-BELUX/sb-accelerator/rulesets --method POST --input main-review.json`
(`actor_id: 5` = the built-in Repository admin role.)

- [ ] **Step 3: Verify protection bites**

```bash
gh api repos/DLW-INT-BTA-BELUX/sb-accelerator/rulesets --jq '.[].name'
cd /Users/bulthem/Documents/Dev/sb-accelerator
git commit --allow-empty -m "test: protection probe

Co-Authored-By: Claude <noreply@anthropic.com>"
git push  # EXPECTED TO FAIL (rejected by ruleset)
git reset --hard origin/main
```
Expected: push rejected with a ruleset message. The reset drops the probe commit.

- [ ] **Step 4: End-to-end verification PR** — proves the whole chain (checks fire as required contexts, review workflow runs, admin squash-merge works):

```bash
git switch -c chore/bootstrap-verification
# Append one line under CHANGELOG.md's 2026-08-22 entry:
#   - Branch protection verified end-to-end (this PR).
git add CHANGELOG.md
git commit -m "chore: verify protected-main PR flow end to end

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin HEAD
gh pr create --fill
```

Then wait for checks: `gh pr checks --watch` (or poll `gh pr checks`). Expected: all three contexts green. `claude-review` may fail or not appear if `ANTHROPIC_API_KEY` isn't set yet — that is a listed human action, not a blocker; note it in the task report.

- [ ] **Step 5: Merge and clean up**

```bash
gh pr merge --squash --delete-branch
git switch main && git pull
```
Expected: merge succeeds via the admin bypass on `main-review` (no approval needed) with all `main-ci` checks green.

---

### Task 8: `/propose-upstream` skill in busdev

**Files (all in the busdev worktree `/Users/bulthem/Documents/Dev/Vault/BusDev/claude/worktrees/knbp-parkwind-ai-opportunity-aefeea`, branch `claude/git-issue-2-b2dee0`):**
- Create: `claude/skills/propose-upstream/SKILL.md`  *(note: busdev skills live under `claude/skills/`, tracked in git; `.claude` is a symlink to `claude/`)*
- Modify: `99-workflow-config/reference/workflow-commands.md` (add one row), `CHANGELOG.md` (add entry)

**Interfaces:**
- Consumes: the `upstream-proposal` label and issue template on sb-accelerator (Tasks 4–5).
- Produces: the busdev half of the upstream flow; sb-accelerator's `/process-upstream` (backlog issue) consumes the issues it files.

- [ ] **Step 1: Verify the skills directory convention**

Run: `ls /Users/bulthem/Documents/Dev/Vault/BusDev/claude/worktrees/knbp-parkwind-ai-opportunity-aefeea/claude/skills/ | head -5`
Expected: existing skill directories (e.g. `sync-plaud`, `morning-brief`). Place the new skill beside them.

- [ ] **Step 2: Write `claude/skills/propose-upstream/SKILL.md`**

```markdown
---
name: propose-upstream
description: Propose a busdev pattern for productization in sb-accelerator. Gathers what it does, files involved, vault sha, usage evidence, and couplings to strip, then opens an upstream-proposal issue on DLW-INT-BTA-BELUX/sb-accelerator. Triggers when user invokes /propose-upstream.
user_invocable: true
---

# Propose Upstream

Capture-then-process, ~30 seconds: this skill only *captures* a proposal as a
GitHub issue on the product repo. The genericization rewrite happens later, in
sb-accelerator, via its `/process-upstream` skill.

## Inputs

Michael names the candidate (a skill, hook, pattern, or behavior that just
proved product-worthy), usually right after using it. If the candidate is
ambiguous, ask one clarifying question — otherwise proceed.

## Steps

1. **Identify the candidate's files.** For a skill: its directory under
   `claude/skills/`. For a pattern: the CLAUDE.md section, reference doc, or
   template that defines it. List exact repo-relative paths.
2. **Record the vault sha:** `git rev-parse HEAD` in the vault repo.
3. **Gather usage evidence** from the session context and the vault: how often
   it runs, what it produced lately, why it earned its keep. 2-3 concrete
   sentences — no vault content beyond what the evidence needs.
4. **Find couplings to strip:** grep the candidate's files (case-insensitive)
   for delaware clients, people names, busdev-specific paths, and personal
   context references. List each with file:line.
5. **Compose the issue** using the upstream-proposal template sections
   (What it does / Files involved / Vault sha / Usage evidence / Couplings to
   strip). Title: `upstream: <candidate-name>`.
6. **Show the draft to Michael.** On OK:

   ```bash
   gh issue create -R DLW-INT-BTA-BELUX/sb-accelerator \
     --title "upstream: <candidate-name>" \
     --label "upstream-proposal" \
     --body "<the composed body>"
   ```

7. Report the issue URL. Done — no vault files change.

## Rules

- **Capture only.** Never start the genericization rewrite here; that is
  sb-accelerator work with its own clean-room discipline.
- The issue body may name busdev paths and describe couplings (the product
  repo is delaware-internal) but must not paste client vault content.
- If `gh` cannot reach the repo, save the composed body to the scratchpad,
  show it, and tell Michael to file it manually — do not fail silently.
```

- [ ] **Step 3: Add the row to `99-workflow-config/reference/workflow-commands.md`** — read the file, match its table format, add `/propose-upstream` with a one-line description ("Propose a busdev pattern for productization — files an upstream-proposal issue on sb-accelerator").

- [ ] **Step 4: Add a `CHANGELOG.md` entry** — read the file's entry format first, then add under today (2026-08-22): `/propose-upstream` skill — busdev half of the busdev→sb-accelerator upstream flow (issue #2).

- [ ] **Step 5: Verify the skill loads**

Run: `python3 -c "
import yaml, pathlib
t = pathlib.Path('claude/skills/propose-upstream/SKILL.md').read_text()
fm = yaml.safe_load(t.split('---')[1])
assert fm['name'] == 'propose-upstream' and fm['user_invocable'] is True and fm['description']
print('SKILL-FRONTMATTER-OK')"`
Expected: `SKILL-FRONTMATTER-OK`.

- [ ] **Step 6: Commit, push, PR, squash-merge** (busdev trailer):

```bash
cd /Users/bulthem/Documents/Dev/Vault/BusDev/claude/worktrees/knbp-parkwind-ai-opportunity-aefeea
git add claude/skills/propose-upstream 99-workflow-config/reference/workflow-commands.md CHANGELOG.md
git commit -m "feat(skills): /propose-upstream — file upstream-proposal issues on sb-accelerator

The busdev half of the busdev→accelerator upstream flow (issue #2):
capture a product-worthy pattern as a structured issue in ~30s;
the genericization rewrite happens in sb-accelerator via /process-upstream.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin HEAD
gh pr create --base main --title "feat(skills): /propose-upstream — busdev half of the upstream flow" --body "Builds the only issue-#2 item that lives in busdev. Part of #2.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh pr merge --squash --delete-branch
```

---

### Task 9: Close busdev issue #2

**Files:** none.

**Interfaces:**
- Consumes: everything above — the close-out comment reports what exists now. Use the real issue numbers and board URL recorded in Tasks 4/6.

- [ ] **Step 1: Verify every checklist item in busdev issue #2 is done**

Run: `gh issue view 2 -R <busdev-repo>` and check each box's item against reality (docs merged; repo exists with specs in `docs/superpowers/specs/`; bootstrap checklist done; protection + board live; `/propose-upstream` merged). Any gap → stop and fix before closing.

- [ ] **Step 2: Close with a summary comment**

```bash
gh issue close 2 --comment "Bootstrap done. sb-accelerator is live: skeleton + conventions (copy-adapted from bta-agents-portal), three required CI checks, labels/milestones/org board, 20 seeded backlog issues (incl. the port-core-skills parent), main protected (main-ci no-bypass + main-review admin-bypass), end-to-end PR flow verified. /propose-upstream merged here in busdev. Remaining human actions: install the Claude GitHub App on sb-accelerator, set ANTHROPIC_API_KEY + PROJECTS_TOKEN secrets, add the Board/Roadmap views in the UI. Further product work: https://github.com/DLW-INT-BTA-BELUX/sb-accelerator"
```

---

## Human actions after the plan completes (Michael — Claude cannot do these)

1. **Install the Claude GitHub App** on `DLW-INT-BTA-BELUX/sb-accelerator` (GitHub UI) — powers `claude.yml` + `claude-code-review.yml`.
2. **Set the `ANTHROPIC_API_KEY` Actions secret** on the repo (same pattern as bta-agents-portal).
3. **Create `PROJECTS_TOKEN`** (PAT with `project` scope) as an Actions secret — powers `issue-backlog-defaults.yml`'s board-add.
4. **Add the board views** in the web UI: Board grouped by Status, Roadmap by Milestone.
5. Later, at dist time: the Claude admin-console marketplace connection (bta's `docs/it-request-plugin-distribution.md` is the IT-ask template).
