#!/usr/bin/env bash
# Version guard: a PR that touches plugin/ (except plugin/CLAUDE.md) must bump
# plugin/.claude-plugin/plugin.json to a version that is (a) different from the
# target branch's and (b) not already released.
#
# "Released" today = tag plugin-v<version> exists on origin (sb-dist doesn't
# exist yet; the release-pipeline issue moves this check there).
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
