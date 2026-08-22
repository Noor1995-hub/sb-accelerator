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
