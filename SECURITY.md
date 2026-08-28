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

- Client vault content, client names in `plugin/` (which now includes the
  vault template at `plugin/template/`) (clean-room rule — root `CLAUDE.md`),
  or anything from a client engagement beyond `registry.yaml`'s deployment rows.
- Personal content from the busdev lab. Porting is a rewrite, not a copy.

## Rotate on handovers

If the repo, a token, or the org changes hands, rotate `PROJECTS_TOKEN`, `ANTHROPIC_API_KEY`,
and any `DIST_REPO_TOKEN` / per-client tokens involved. Rotating costs minutes; a stale token
in the wrong hands does not.

## Reporting a concern

Internal delaware repo, no external users. Raise security issues directly with the repo
admin(s) — `docs/onboarding-new-builder.md` says who that is — rather than filing a public issue.
