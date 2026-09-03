#!/usr/bin/env bash
# Version guard: a PR that touches plugin/ (except plugin/CLAUDE.md) must bump
# plugin/.claude-plugin/plugin.json to a version that is (a) different from the
# target branch's and (b) not already released.
#
# "Released" = tag plugin-v<version> exists on origin. The tag check stays
# exactly this, even now that the release pipeline (#10) and sb-dist exist:
# a tag IS the release event — cut_release.sh only ever creates one after a
# version bump has merged — while sb-dist deliberately lags main between
# quarterly publishes. Checking sb-dist's own plugin.json here would make
# this guard pass or fail depending on when the last release happened to
# ship, rather than on whether the version has been claimed.
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
