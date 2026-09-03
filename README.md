# Second Brain Accelerator

Product monorepo for the **Second Brain Accelerator**: a personal AI operating
system for a client executive and their EA — the vault owner and their
assistant — deployed by delaware consultants inside AI transformation
engagements and maintained as a versioned product.

Full product design: `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md`.
Engineering conventions and the bootstrap rationale:
`docs/superpowers/specs/2026-08-22-sb-accelerator-bootstrap-brief.md`.

## Structure

| Path | What it is |
|---|---|
| `plugin/` | Claude Code plugin: skills, hooks, agents. Ships to clients via `sb-dist`. |
| `plugin/template/` | Vault skeleton: folders, `.obsidian/`, `.base` views, CLAUDE.md + context-portfolio slots. Instantiated once per client. |
| `migrations/` | Versioned structure migrations, consumed by `/upgrade-vault`. |
| `playbooks/` | Onboarding interview, pre-flight checklist, provisioning runbook, hypercare, EA training. Never ships. |
| `docs/` | Architecture, backlog model, local setup, builder onboarding. |
| `registry.yaml` | Client deployment registry (v1: file; later Airtable). |
| `scripts/dist/` | The dist-tree template (`README.md.tmpl`) `scripts/build_dist.py` renders for each release channel. Never ships itself. |

## The four layers (what ships, what doesn't)

- **L0** ontology & taxonomy → ships (template)
- **L1** automation → ships (plugin), de-personalized
- **L2** delaware company knowledge → **never ships** (separate overlay, later)
- **L3** personal context → generated per user at onboarding, never in this repo

**Hard rule:** nothing in `plugin/` — which now includes the template at
`plugin/template/` — references delaware clients, Michael, or busdev content.
CI lints this (`scripts/lint_plugin.py`).

## Contributing

See `CONTRIBUTING.md` (protected main, PRs, three CI checks) and
`docs/backlog.md` (labels, milestones, board).
