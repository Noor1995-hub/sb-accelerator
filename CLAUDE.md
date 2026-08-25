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

## Visual verification (UI-impacting changes)

The vault is the UI, and CI cannot see it: a renamed property silently empties
a Base table, an inert `displayName` silently renders a raw column name. Both
shipped. `python -m pytest scripts/tests -q` going green does **not** mean a
rendering change is verified.

A change is **UI-impacting** when it touches any of:

- `template/.obsidian/**` — theme, Minimal Theme Settings, CSS snippets, navigator
- any `*.base` or `*.canvas`
- `fixtures/demo-vault/**` — it changes what renders
- `template/99-workflow-config/reference/ontology.md` — property renames empty views
- `plugin/lib/vaultlib/markdown.py` — it emits the bodies that render

For those, run `/visual-check` (or the loop in `docs/visual-verification.md`)
and report the evidence — the assertions **and** what the screenshots show —
before calling the change done. A `PostToolUse` hook prints a reminder, but the
obligation is here, not in the hook.

This tier is local-only by construction and never becomes a CI check: it needs
a licensed macOS GUI app and a Restricted Mode dialog that cannot ship as
files.

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
- `CHANGELOG.md` is client-facing release notes, not a work log: a PR gets a
  line under `Unreleased` (ending with its PR number) only if a client would
  notice — plugin behavior, a skill, the template, a migration. Internal
  changes stay out; git history is that record. Not CI-enforced.
- Backlog model (labels, milestones, board): `docs/backlog.md`.
