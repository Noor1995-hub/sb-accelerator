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

## Verification below CI

One tier exists that CI never runs: `scripts/obsidian_probe.py` drives a real
Obsidian and `scripts/tests/test_obsidian_render.py` asserts what it rendered.
It needs a licensed macOS GUI app and a Restricted Mode dialog that cannot ship
as files, so it runs on a builder's machine before a PR — never as a status
check. The test module skips itself when no capture is present, which is what
the Ubuntu runners see. See `docs/visual-verification.md`.
