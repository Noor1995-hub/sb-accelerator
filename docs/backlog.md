# Backlog & Issue Tracking — SB Accelerator

GitHub-native: plain GitHub Issues organized by an org Projects v2 board. Everything is driven
from the `gh` CLI, so it works from the terminal and from Claude Code.

## Where it lives

| Surface | Link |
|---|---|
| Issues | <https://github.com/DLW-INT-BTA-BELUX/sb-accelerator/issues> |
| Board ("SB Accelerator Backlog") | <https://github.com/orgs/DLW-INT-BTA-BELUX/projects/2> |

## The model — four axes

| Axis | Tool | Per issue | Answers |
|---|---|---|---|
| **What kind of work** | `type:` **label** | many | feature / infra / chore (bug = built-in `bug`) |
| **Which part of the product** | `area:` **label** | many | plugin / template / playbooks / migrations / dist |
| **When it ships** | **Milestone** | one | Wave 1–4 / Unscheduled |
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

Sequenced as waves toward the first client deployment (re-planned 2026-08-31; the earlier
`v0.1`/`v0.2`/`v1.0` milestones are closed). Waves are strictly ordered: a wave starts when
the previous one exits clean.

| Milestone | Theme |
|---|---|
| `Wave 1 — critical fixes` | Nothing silently wrong before re-testing: P0s, silent data loss, broken first instruction |
| `Wave 2 — DryRun migration + E2E` | Migrate the internal DryRun vault via `/upgrade-vault` + full-loop rehearsal (#107), plus probe/test-infra fixes |
| `Wave 3 — provisioning` | sb-dist + release pipeline, per-client provisioning, Session-1 playbooks |
| `Wave 4 — field test` | Internal dry run with a delaware colleague as fake client (#9) |
| `Unscheduled` | Default for new inflow until triage assigns a wave |

## How to add work

Requires `gh` v2.94.0+ (native `--parent` for sub-issues) and a token with `repo` + `project`
scopes (`gh auth refresh -s project` for the board).

```bash
REPO=DLW-INT-BTA-BELUX/sb-accelerator

gh issue create -R $REPO --title "…" --body "…" \
  --milestone "Unscheduled" --label "area:plugin" --label "type:feature"

# Sub-issue under a parent
gh issue create -R $REPO --title "…" --body "…" --parent <N> \
  --label "area:plugin" --label "type:feature"
```

Close issues from commits with `Closes #<N>` in the PR — the squash merge links and closes them.

## Views (web UI only — not scriptable)

The board ships with a Table view. Add in the UI (**+ New view**): a **Board** view grouped by
**Status** (kanban) and a **Roadmap** view laid out by **Milestone** (timeline).
