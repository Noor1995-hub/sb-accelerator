# Distribution channels

Two repositories carry releases out of this one. This page is the orientation:
what each channel is, what makes it move, and who reads it. The step-by-step
release procedure lives in `CONTRIBUTING.md` § "Cutting a release"; the
client-side delivery paths (how a client's machine reaches a marketplace at
all) live in `playbooks/plugin-distribution.md`. This page is the layer that
ties them together.

## The two channels

| | dryrun | client |
|---|---|---|
| Repository | `DLW-INT-BTA-BELUX/sb-dist-dryrun` | `DLW-INT-BTA-BELUX/sb-dist` |
| Marketplace name | `sb-accelerator-dryrun` | `sb-accelerator` |
| What moves it | pushing a `plugin-v*` tag | a manual `workflow_dispatch` |
| Who reads it | delaware contributors, on their own vaults | client deployments |
| Gets every release? | yes, automatically | no — only what someone promotes |

Both channels are built by the same job in `.github/workflows/release.yml`,
from the same commit, by the same `scripts/build_dist.py`. The published
`plugin/` trees are **byte-identical**. The channels differ in exactly three
things: which repository they land in, the `name` in `marketplace.json`, and a
"this is a dry run" notice added to the dryrun README.

This matters when reasoning about a bug report: "it works on dryrun but not on
client" is never a channel difference. It is a version difference.

## What triggers a publish to `sb-dist-dryrun`

**Trigger: a git tag push. Automatic from there.**

```
release PR merged (CHANGELOG Unreleased → dated section)
    ↓
scripts/cut_release.sh          ← a human runs this, on main
    ↓ creates and pushes tag plugin-v<version>
GitHub Actions: release.yml fires on the tag push
    ↓ channel is forced to "dryrun" — see below
sb-dist-dryrun updated  +  GitHub Release created (zip + sha256)
```

The channel is not a choice here. `release.yml`'s `resolve` job hardcodes it:

```yaml
if [ "${{ github.event_name }}" = "push" ]; then
  tag="${GITHUB_REF#refs/tags/}"
  channel="dryrun"
```

A tag push **cannot** reach the client channel, however the tag is spelled.
That is the safety property the whole arrangement rests on: cutting a release
is never, by itself, a client-visible act.

Merging a PR to `main` publishes nothing at all. Only a tag does.

## What triggers a publish to `sb-dist`

**Trigger: a person deliberately dispatching the workflow. Never automatic.**

```bash
gh workflow run release.yml -f tag=plugin-v<version> -f channel=client
```

Or on github.com: **Actions → Release → Run workflow**, enter the tag, pick
`client` from the channel dropdown.

The tag must already exist. The workflow re-runs the *same* build against the
*same* commit and publishes it to `sb-dist`, verifying the result by reading it
back through the GitHub API rather than trusting its own push.

Two consequences worth holding on to:

- **The promotion is not enforced to follow a green dryrun run.** Nothing stops
  dispatching `channel=client` for a tag that never ran on dryrun, or ran and
  failed. Verifying dryrun first is a human obligation, not a gate.
- **The GitHub Release belongs to the tag, not the channel.** It is created
  once, on the original tag push. Promoting to client adds no new Release and
  no new zip — Path E consumers download the asset the dryrun run attached.

## Why the two channels exist

So that a delaware contributor can run a real release on a real vault before
any client sees it. The dryrun channel is the rehearsal; the client channel is
the performance.

That only works if someone is actually rehearsing. A dryrun channel nobody
consumes is ceremony — it receives releases that are never looked at, and the
promotion step becomes a rubber stamp on an unverified build. Hence the
contributor rule below.

## Contributor rule: run your own vault on the dryrun channel

**If you work on this repo, your own second brain points at
`sb-accelerator-dryrun`, not at `sb-accelerator`.**

You are the reason the dryrun channel is worth having. Pointing your vault at
the client channel means you find out a release is broken at the same moment a
client does.

First-time setup:

```bash
claude plugin marketplace add DLW-INT-BTA-BELUX/sb-dist-dryrun
claude plugin install second-brain@sb-accelerator-dryrun
```

Pulling a new release after a tag push:

```bash
claude plugin marketplace update sb-accelerator-dryrun
claude plugin update second-brain@sb-accelerator-dryrun
```

`claude plugin update` needs a restart to take effect. Skills are then live on
next use — they are just files the model reads at invocation time.

**Vault structure and Obsidian changes are not live.** A new plugin version can
ship `.base` views, `.obsidian` settings, CSS snippets, or a structure
migration, and none of those reach an already-provisioned vault until someone
runs `/upgrade-vault`. Run it after every plugin update, even when no migration
is pending — its step 5 (template refresh) is where UI changes actually land,
and a release that only fixes a rendering bug has nothing else in it. See the
skill itself and `docs/visual-verification.md`.

## Checking where things stand

Neither channel's version is inferable from `main`. Read them:

```bash
for r in sb-dist sb-dist-dryrun; do
  v=$(gh api "repos/DLW-INT-BTA-BELUX/$r/contents/plugin/.claude-plugin/plugin.json" \
        --jq '.content' | base64 -d \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])")
  echo "$r: $v"
done
```

A gap between the two is normal and expected — it means releases have been cut
but not yet promoted. A gap that has been sitting for several versions means
the promotion step is being forgotten, which is the failure mode this
arrangement is prone to. `registry.yaml`'s `plugin_version` records what each
deployment was last *confirmed* on; it is hand-stamped at tune-ups and lags
reality, so do not read it as live state.

## Rollback

Dispatch the previous tag at the client channel:

```bash
gh workflow run release.yml -f tag=<previous-tag> -f channel=client
```

The build is deterministic — no timestamps are written anywhere — so re-cutting
a tag reproduces a byte-identical tree. Republishing a tag/channel pair that is
already published is a no-op, not a duplicate commit: the publish job checks
`git diff --cached --quiet` before committing.

Rolling the *plugin* back does not roll the *vault* back. A structure migration
that has already run stays run; `/upgrade-vault` snapshots before each
migration precisely so that path exists, and it is a manual restore.

## Related

- `CONTRIBUTING.md` § "Cutting a release" — the procedure, step by step.
- `playbooks/plugin-distribution.md` — delivery paths A–E, the owner-only setup
  (`DIST_PUSH_TOKEN` and its expiry), and platform constraints. Never ships.
- `docs/architecture.md` § "Update policy" — why the cadence is what it is.
- `.github/workflows/release.yml` — the authority for everything on this page.
