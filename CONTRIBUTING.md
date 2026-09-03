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
- **Changelog — only if a client would notice.** If this PR changes the plugin's behavior, a
  skill, the vault template, or a migration, add a line under `Unreleased` in `CHANGELOG.md`,
  ending with your PR number. Write it for the consultant explaining the update at a client
  tune-up. If the change is internal — CI, validators, fixtures, delaware-side docs, tooling —
  leave the changelog alone: git history is that record, and a changelog that repeats it is
  just a worse copy.
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

## Cutting a release

Owner-run, not part of the normal PR flow — repo secrets and tag-push access
aren't given to every contributor. Mechanics: `playbooks/plugin-distribution.md`.
Steps, on `main`:

1. Open a release PR that turns `CHANGELOG.md`'s `## Unreleased` heading into
   a dated `## v<version> —` section (moving its bullets down with it) and
   leaves a fresh empty `Unreleased` behind. Merge it like any other PR.
2. Run `scripts/cut_release.sh`. It tags `plugin-v<version>` (read from
   `plugin/.claude-plugin/plugin.json`) and pushes the tag — refusing with a
   concrete next step if the tree isn't clean, isn't `main` and up to date
   with `origin/main`, the tag already exists, or step 1 didn't happen.
3. The tag push runs `.github/workflows/release.yml` on `channel=dryrun`
   automatically: it re-verifies the tag, builds the dist tree with
   `scripts/build_dist.py` (running the clean-room linter on the *built*
   tree, not just the source), publishes it, and cuts the GitHub Release.
4. Once the dryrun run is green and verified, promote to the client channel:
   `gh workflow run release.yml -f tag=plugin-v<version> -f channel=client`.

`scripts/build_dist.py` and `scripts/cut_release.sh` are covered by
`scripts/tests/test_build_dist.py` and can be exercised locally — the
workflow YAML itself cannot be run outside Actions, so review it by reading.

## Branch protection

`main` is protected by two GitHub rulesets:

- **`main-ci`** — requires a pull request and the three `CI` workflow checks to pass, with
  **no bypass** (applies to everyone, admins included — you cannot merge a red build).
- **`main-review`** — requires **1 approving review**, bypassed by repo admins/owners.

Direct pushes and force-pushes to `main` are blocked for everyone.
