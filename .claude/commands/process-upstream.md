---
description: Turn an upstream/field-proposal issue into a clean-room PR against main
---

Process a busdev-to-product proposal issue into a PR. delaware-internal: runs
where `gh` is authenticated against this repo and, for upstream proposals, the
busdev checkout is present on disk.

**Usage:** `/process-upstream <issue-number>`

1. **Read the issue:**

   ```bash
   gh issue view <issue-number> --json title,body,labels,comments
   ```

   Accept labels `upstream-proposal` and `field-proposal`. Anything else —
   stop and say why (name the label(s) actually present, or that none of the
   accepted labels are).

2. **For `upstream-proposal` — locate the busdev checkout and check drift.**
   The issue body records the vault files being ported and a busdev commit
   sha. Find the checkout path: the issue body or its comments may name one
   explicitly; otherwise default to `~/Documents/Dev/Vault/BusDev`.

   Compare the recorded sha against the checkout's current `HEAD`:

   ```bash
   git -C <busdev> rev-parse HEAD
   ```

   If it differs from the recorded sha, show the drift before touching
   anything:

   ```bash
   git -C <busdev> diff <recorded-sha> HEAD -- <files>
   ```

   Present that diff and let the human decide whether to proceed against
   current `HEAD` or against the originally recorded sha. Do not choose
   silently.

3. **Genericize — the clean-room rule, verbatim:**
   - Rewrite, never copy-paste-then-trim.
   - Strip client names, people names, busdev paths, and personal
     calibrations.
   - Replace them with archetype-neutral equivalents.
   - The ported skill's frontmatter records provenance: `upstreamed-from:
     busdev@<sha>` (the sha decided in step 2 for upstream proposals).

4. **Branch and implement**, following this repo's own conventions
   (`CLAUDE.md`, `CONTRIBUTING.md`):

   ```bash
   git switch main
   git pull
   git checkout -b upstream/<issue-number>-<slug>
   ```

   - If the change touches `plugin/` (other than `plugin/CLAUDE.md`), bump
     the version in `plugin/.claude-plugin/plugin.json` — CI's version guard
     enforces this.
   - `CHANGELOG.md` is a judgment call: add a line under `Unreleased` (ending
     with the PR number) only if a client would notice — plugin behavior, a
     skill, the template, a migration. Leave it alone for internal-only
     changes.
   - Run the three local checks before opening the PR:

     ```bash
     python scripts/lint_plugin.py
     python scripts/validate_template.py
     python -m pytest scripts/tests -q
     ```

   - Every commit message ends with the exact trailer:
     `Co-Authored-By: Claude <noreply@anthropic.com>`

5. **Open the PR:**

   ```bash
   gh pr create --fill
   ```

   The body must include `Closes #<issue-number>`, the recorded busdev sha,
   and — if step 2 found drift — which option was chosen (current `HEAD` or
   the recorded sha) and why. `main` is protected: branch → PR → three green
   checks (`plugin`, `template`, `plugin version`) → squash merge.
