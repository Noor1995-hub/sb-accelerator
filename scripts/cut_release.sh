#!/usr/bin/env bash
# Cut a plugin release: tag plugin/.claude-plugin/plugin.json's version and
# push the tag, which kicks off .github/workflows/release.yml on the dryrun
# channel (a tag push always implies channel=dryrun — see the workflow).
#
# Owner-run, not part of CI. Promote a tag to the client channel afterwards
# with:
#   gh workflow run release.yml -f tag=plugin-v<version> -f channel=client
#
# Usage: scripts/cut_release.sh [--dry-run]
set -euo pipefail

dry_run=false
if [ "${1:-}" = "--dry-run" ]; then
  dry_run=true
fi

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

if [ -n "$(git status --porcelain)" ]; then
  echo "cut_release: working tree is not clean — commit or stash first." >&2
  exit 1
fi

branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" != "main" ]; then
  echo "cut_release: must be run on main (currently on '$branch')." >&2
  exit 1
fi

git fetch origin main --quiet
local_head=$(git rev-parse HEAD)
remote_head=$(git rev-parse origin/main)
if [ "$local_head" != "$remote_head" ]; then
  echo "cut_release: local main ($local_head) is not origin/main ($remote_head) — pull or push first." >&2
  exit 1
fi

version=$(python3 -c "import json; print(json.load(open('plugin/.claude-plugin/plugin.json'))['version'])")
tag="plugin-v${version}"

if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  echo "cut_release: $tag already exists on origin — bump plugin.json's version first." >&2
  exit 1
fi

# The release PR is expected to have already turned "## Unreleased" into a
# dated version heading before this script runs. Refuse with a clear
# next-step instead of a bare grep failure — this is exactly the state the
# very first tag is cut from, since no release has ever done that rewrite
# yet.
version_re=$(printf '%s' "$version" | sed 's/[.]/\\./g')
if ! grep -qE "^## v${version_re} — " CHANGELOG.md; then
  cat >&2 <<EOF
cut_release: CHANGELOG.md has no "## v${version} — <date>" section yet.

Before tagging, the release PR must turn the "## Unreleased" heading into a
dated version heading (moving its bullets down with it), and leave a fresh
empty Unreleased section for the next round of entries:

  ## Unreleased

  ## v${version} — $(date +%F)

  <the bullets that were under Unreleased>

Edit CHANGELOG.md, commit, merge to main, then re-run this script.

If this is the project's very first release, that section has never existed
before — that is expected, not a bug. Do the rewrite above once, then run
this script; scripts/build_dist.py's \`notes\` command falls back to
Unreleased with a warning if a tag is ever pushed before this rewrite lands,
so a skipped rewrite degrades rather than breaking the pipeline.
EOF
  exit 1
fi

echo "Tagging $tag on $local_head."

origin_slug() {
  if command -v gh >/dev/null 2>&1; then
    slug=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) && [ -n "$slug" ] && { echo "$slug"; return 0; }
  fi
  git remote get-url origin | sed -E 's#^git@github\.com:##; s#^https://github\.com/##; s#\.git$##'
}

if $dry_run; then
  echo "[dry-run] git tag -a $tag -m \"plugin $version\""
  echo "[dry-run] git push origin $tag"
  exit 0
fi

git tag -a "$tag" -m "plugin $version"
git push origin "$tag"

slug=$(origin_slug)
echo "Pushed $tag. This always runs the dryrun channel first — watch it here:"
echo "  https://github.com/${slug}/actions/workflows/release.yml"
echo
echo "Once the dryrun run is green and you've verified it, promote to client:"
echo "  gh workflow run release.yml -f tag=$tag -f channel=client"
