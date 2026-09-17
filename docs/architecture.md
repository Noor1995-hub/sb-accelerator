# Architecture

Authoritative product design: `superpowers/specs/2026-08-22-second-brain-accelerator-design.md`.
This page is the short orientation.

## Repo topology

busdev (lab) —/propose-upstream→ issues here —/process-upstream→ PR here.
This repo is the source of truth. Releases publish to `sb-dist`
(client-facing marketplace repo, created at design-doc step 8); clients'
Claude org admins connect `sb-dist` as a native plugin marketplace, which
syncs the plugin to exec + EA across Desktop, Cowork, and Claude Code.
Feedback lands on one repo per deployment (`sb-client-<slug>`, or
`sb-internal-<slug>` for an internal one), never on shared repos.

## Update policy

Consultant-applied, implemented by publishing cadence: `sb-dist` only receives
a release when clients should get it (quarterly, around tune-ups). Structure
migrations are consultant-run via `/upgrade-vault`; a plugin/vault
structure-version mismatch check makes skills degrade gracefully until migrated.

A release is cut, not merged directly: `scripts/cut_release.sh` tags
`plugin-v<version>` on `main` after a release PR has dated the CHANGELOG's
`Unreleased` section, and `.github/workflows/release.yml` does the rest —
verify the tag, build the dist tree (`scripts/build_dist.py`, which re-runs
the clean-room linter on the *built* tree), publish it, and cut the GitHub
Release. A tag push always publishes to the internal `sb-dist-dryrun` first;
promoting a verified tag to the client-facing `sb-dist` is a separate,
explicit `workflow_dispatch`. See `docs/distribution-channels.md` for what the
two channels are and the contributor rule that makes the dryrun one worth
having, `CONTRIBUTING.md`'s "Cutting a release" for the procedure, and
`playbooks/plugin-distribution.md` for the client-side delivery paths and the
owner-only setup (`sb-dist`, `DIST_PUSH_TOKEN`) it depends on.

The vault's own marker is `plugin/template/structure-version` — a plain integer,
bumped only by a migration under `migrations/`, read by `/upgrade-vault`.

## The vault's `claude/` directory

Obsidian hides dot-folders, so the vault keeps Claude Code's home as a visible
`claude/` directory with `.claude` symlinked to it: Claude Code reads
`.claude/`, the exec browses the same files as `claude/`. The symlink is
created at provisioning — `make_test_vault.py` does it for test vaults,
`playbooks/provisioning-runbook.md` §3 covers client machines — and is
deliberately not a checked-in file, since symlinks survive neither naive
copies nor Windows checkouts without symlink privileges.

`claude/skills/` holds vault-local skills (per-deployment customisations) and
they load **only in Claude Code**. Cowork does not read skills from a
connected folder at all; it loads them from installed plugins and the user's
own skill store. That is why the product's core skills ship in `plugin/`
rather than in the template — a platform constraint, not a preference.
Anything placed in `claude/skills/` is invisible to Cowork.

## CI

Three required checks on every PR (see `.github/workflows/ci.yml`):

- `plugin (skill lint + tests)` — skill frontmatter + clean-room lint + pytest over `scripts/tests/`
- `template (structure validation)` — template skeleton invariants
- `plugin version (not already released)` — plugin/ changes require a version bump; bumped version must not be already tagged

`.github/workflows/release.yml` is separate and not a PR status check — it
runs on a `plugin-v*` tag push or an owner's `workflow_dispatch`, never on a
pull request. See "Update policy" above.

## Verification below CI

One tier exists that CI never runs: `scripts/obsidian_probe.py` drives a real
Obsidian and `scripts/tests/test_obsidian_render.py` asserts what it rendered.
It needs a licensed macOS GUI app and a Restricted Mode dialog that cannot ship
as files, so it runs on a builder's machine before a PR — never as a status
check. The test module skips itself when no capture is present, which is what
the Ubuntu runners see. See `docs/visual-verification.md`.
