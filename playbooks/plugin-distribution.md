# Plugin distribution

How the accelerator plugin actually reaches a client machine. delaware-side
material; never ships.

Verified against Anthropic's documentation on 2026-08-23. Re-verify at each
release — this is platform behaviour, not our code, and it moves.

## Precedent — read this first

**The client-facing IT request already exists and is field-tested:**
`bta-agents-portal/docs/it-request-plugin-distribution.md`. It is the
structure to reuse when asking a client's IT to connect a marketplace —
three scoped one-time asks, an explicitly bounded repository scope,
verification steps to run together afterwards, and a stated fallback if
declined. Adapt it per engagement; do not rewrite it.

This playbook is the layer underneath: the mechanics and the decision of
*which* delivery path an engagement uses. The two are complements.

Related: the tag-triggered release pipeline (`.github/workflows/release.yml`,
`scripts/build_dist.py`, `scripts/cut_release.sh`) shipped in #10, milestone
v1.0. **Both channels are live as of 2026-09-03** — the owner setup it
depends on is done:

- `sb-dist-dryrun` and `sb-dist` both exist, private, default branch `main`,
  no push-blocking ruleset (the release bot pushes straight to them).
- The `DIST_PUSH_TOKEN` secret is set on this repo: one fine-grained PAT,
  resource owner the org, repository access scoped to those two repos,
  Contents read/write. Minted 2026-09-03 — **check its expiry before the
  next quarterly release**; the `DIST_PUSH_TOKEN` check in the `publish` job
  is presence-only, so an expired-but-still-set token slips past it and
  fails opaquely on the next line's `git clone` with a generic git auth
  error ("Repository not found" / "Authentication failed"), with no
  annotation pointing back here. A `publish` job that dies at the clone step
  means the token, not the dist repo.
- 0.10.28 was the first version published to the client channel
  (`sb-dist@05d5e8e`), the same day the dryrun channel got it.

One optional hardening step is still **not** in place: a ruleset restricting
who can push a `refs/tags/plugin-v*` tag to admins. Anyone who can push to
this repo can therefore start a dryrun release train. The client promotion
is still a separate deliberate `workflow_dispatch`, so this is a nuisance,
not an exposure.

**One limitation carried over from the bta deployment, verified there
2026-07-31:** a plugin cannot deliver an MCP connector to the *chat*
surfaces. Claude renders the connector entry but its Install button never
activates, and adding connectors is in any case gated to Organization Owners
on delaware's org. Plan any connector the skills need as
admin-provisioned, not plugin-delivered — this will matter for the recorder
sync.

## The one fact everything else follows from

**Plugins load in Cowork and Claude Code. They do not load in Chat.** And
neither surface loads skills from a folder you connect: Cowork reads skills
from installed plugins and from the user's own skill store (Customize →
Skills), never from a `.claude/skills/` directory inside a mounted vault.

Two consequences:

- A vault-local `claude/skills/` directory is a **Claude Code** convenience
  only. It is not a delivery channel. Do not hand a client a vault with
  skills in it and expect Cowork to see them.
- Object-writing skills are unavailable in Chat by construction. Chat over a
  vault (filesystem access or an Obsidian MCP server) stays a read-and-ask
  surface, which is what plain markdown plus YAML frontmatter is for.

## What a marketplace is

A marketplace is a Git repository (or an HTTPS file host) carrying
`.claude-plugin/marketplace.json` at its root, listing one or more plugins:

```json
{
  "name": "sb-accelerator",
  "owner": { "name": "delaware" },
  "plugins": [
    { "name": "second-brain", "source": "./plugin", "description": "…" }
  ]
}
```

`source` must be a **relative path inside the same repository**. A plugin
whose source points at a different repo is listed in the user's Organization
tab but is never fetched or auto-installed — so a marketplace that merely
references our repo does not work; the plugin content has to live alongside
the manifest.

The manifest `name` must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` and must
not be `unknown`, `org`, or `org-provisioned`.

Platform limits, none of which we are near: 200 MB uncompressed per plugin,
5,000 files per plugin, 512 MB marketplace archive, 500 plugins per
marketplace, 25 marketplaces per user.

**Size, since #164.** The plugin vendors the pinned Obsidian plugins and
theme (`plugin/vendor/obsidian/`, about 7.7 MB uncompressed, 1.9 MB zipped —
notebook-navigator's and dataview's `main.js` are most of it) so
`/provision-vault` step 2 runs offline. That puts the plugin at roughly
9.5 MB against the 200 MB platform limit and the path-E zip at about 2 MB
against its 50 MB cap. The cost that does accrue is history: every pin bump
rewrites those blobs, so each one adds ~8 MB to the `sb-dist*` repos' git
history. `release.yml` already clones them `--depth 1`, and a consultant's
marketplace sync fetches a tree, not history, so this is accepted — but bump
pins when there is a reason to, not on a schedule.

## Two plugin stores: pick one surface

**Cowork and Claude Code install plugins in entirely different places, and
neither one reports the other's version.** Use one surface per deployment, or
keep the two deliberately in sync. Assuming they match is the mistake, and it
is an easy one: the same plugin name sits in both, at different versions,
with no warning anywhere.

- **Claude Code** (CLI, and the desktop app's Code tab): `~/.claude/plugins`,
  driven by `claude plugin list` / `marketplace update` / `update`.
- **Cowork**: the plugin attached to the Claude account, under
  **Home → Customize → Plugins**.

Two rules follow. Verify the deployed version on the surface the vault owner
actually uses, which for a client executive is Cowork, and its Customize →
Plugins header states it. And after any update, restart and open a **new**
session: a session answers from the plugin it loaded at startup, including
its migration set, so a stale session will report a stale vault as up to date.

## Choosing a delivery path

Pick per engagement, in this order of preference.

### Path A — org-managed private GitHub marketplace (claude.ai Team/Enterprise)

The default for a client on a standard Claude Team or Enterprise plan.

The client's Claude administrator connects a private GitHub repository under
**Organization settings → Plugins**. Authentication is *not* a token we
issue: the admin's own GitHub token is verified to confirm they have access,
after which Cowork uses its GitHub App installation token for sync. **The
Claude GitHub App must be installed on the connected repository.**

Per-plugin distribution control:

| Setting | Behaviour |
|---|---|
| Required | Auto-installed, cannot be uninstalled by the user |
| Installed by default | Auto-installed, user may remove it |
| Available for install | Appears in the catalogue; user opts in |
| Not available | Hidden entirely |

Use **Required** for a client deployment. Changes take effect on each
member's next session or plugin refresh.

Requires Team or Enterprise **with both Cowork and Skills enabled**.

**The cross-organisation problem.** The client's admin has to be able to
reach the repository. In the bta precedent both sides were inside delaware's
own EMU tenant, so this did not arise; for a client org it does. Options:
add their admin as a read-only outside collaborator on `sb-dist`, or give the
client their own private mirror we push releases into. Decide at provisioning
and record it in `registry.yaml`. Do not assume the client has usable GitHub
access at all — many owner/EA environments do not.

**On the per-client read token** the design spec describes: that model works
on path B below, where `credentialKind: credentialHelper` can supply a
per-client token. It is *not* how the claude.ai console path authenticates —
there the admin's own GitHub access is verified and the Claude GitHub App
installation token does the sync. So the spec is not wrong, it is
path-specific; say which path an engagement uses rather than assuming the
token.

### Path B — managed configuration (Claude Desktop on third-party inference)

For a client running Claude Desktop against Bedrock, Vertex, or an inference
gateway, admins provision through managed configuration rather than the
claude.ai console: the `allowedPluginMarketplaces` key, delivered by MDM
profile on macOS or the `HKLM\SOFTWARE\Policies\Claude` registry key on
Windows.

```json
[{"source":"github","repo":"<org>/<repo>",
  "ref":"<full-40-char-commit-sha>",
  "credentialKind":"userGit",
  "installationPreference":"required"}]
```

**`auto_install` and `required` demand a full 40-character commit SHA.**
Claude Desktop refuses to auto-install from a branch or tag name. This is a
feature for us, not friction — see the release train below.

`credentialKind` options: `anonymous` (public repos), `userGit` (the git
credential helper already configured for the signed-in OS user),
`credentialHelper` (an executable printing a token to stdout), or
`inferenceCredential` for an HTTPS marketplace served from the deployment's
own gateway origin.

Note that the marketplace fetch happens **on the host, outside the Cowork
VM** — the credential never enters the VM or reaches the model, and the
marketplace host does not need to be on the Cowork egress allowlist. It does
need git on the device baseline (Git for Windows; Xcode Command Line Tools on
macOS).

### Path C — HTTPS-hosted marketplace (no git on the device)

Serve `marketplace.json` over HTTPS with each plugin as a zip archive **on
the same origin**, each carrying a `sha256`. Archives on any other origin are
listed but never fetched. For `auto_install`/`required`, configuration must
also pin `manifestSha256` to the digest of the exact manifest bytes.

Use when the client's device image has no git, or when they already run an
artefact repository.

### Path D — system-wide directory (air-gapped or no reachable host)

Drop plugin directories into `/Library/Application Support/Claude/org-plugins/`
(macOS) or `C:\Program Files\Claude\org-plugins\` (Windows) via the same
software-distribution channel as the app. Each directory needs
`.claude-plugin/plugin.json`; a `version.json` string change triggers
re-sync on next launch. `installationPreference` goes in the plugin manifest
here rather than in marketplace configuration.

Last resort — it means pushing files to every device instead of changing one
configuration value.

### Path E — manual ZIP upload

An admin can upload plugin ZIPs directly (50 MB each, up to 100 plugins per
marketplace) under Organization settings → Plugins. No git, no HTTPS host, no
MDM. Perfectly viable for a single-owner engagement, and the honest fallback
when a client's IT will not connect anything to a delaware repository.

The release pipeline's `github_release` job attaches exactly the artifact
this path needs to every tag pushed to `main`: download `plugin-<version>.zip`
and `plugin-<version>.zip.sha256` from the tag's GitHub Release, check the
sha256 matches (`shasum -a 256 -c plugin-<version>.zip.sha256`), then upload
the zip as-is. It's built with `.claude-plugin/plugin.json` at the zip
root (not nested under a `plugin/` folder) on the reasoning that a
single-plugin ZIP upload expects the package rooted there.

**The layout is verified: upload the release zip as-is.** The zip root is
correct, so no repacking, no nesting and no manifest edit. Uploading a new
version over an existing plugin replaces that entry in place rather than
adding a second one. And the upload needs no org admin: the same mechanism
exists per-account under Home → Customize → Plugins, which is what makes
path E usable for an internal test before anything is published org-wide.

## The release train, concretely

The quarterly care-package update starts with one command and ends with a
one-line change per client, rather than a per-machine visit:

1. **Cut the release.** On `main`, after the release PR has turned
   `## Unreleased` into a dated `## v<version> —` section and merged:
   `scripts/cut_release.sh`. It tags `plugin-v<version>` and pushes the tag —
   refusing first if the tree isn't clean, isn't `main`, the tag already
   exists, or the CHANGELOG rewrite above didn't happen.
2. **Dryrun, automatically.** A tag push always runs
   `.github/workflows/release.yml` with `channel=dryrun`: it re-verifies the
   tag against the three CI checks, builds the dryrun dist tree, publishes it
   to `sb-dist-dryrun`, reads the push back via the GitHub API, and attaches
   the GitHub Release (notes extracted from the CHANGELOG section, plus the
   zip and its sha256).
3. **Verify locally**, the same way as an E2E round: refresh the dryrun
   marketplace (`claude plugin marketplace update sb-accelerator-dryrun`,
   `claude plugin update second-brain@sb-accelerator-dryrun`) and confirm the
   version lands.
4. **Dispatch to the client channel** once satisfied:
   `gh workflow run release.yml -f tag=plugin-v<version> -f channel=client`.
   This re-runs the same build against `sb-dist` — a distinct commit and
   marketplace name, verified by its own API read-back — and does **not**
   recreate the GitHub Release (that only happens on the original tag push).
   Dryrun-before-client is procedural, not enforced by the workflow itself —
   nothing stops dispatching `channel=client` for a tag that skipped step 3;
   verifying dryrun first is on whoever runs this step.
5. **Roll out per client**, by delivery path:
   **Path A:** the marketplace re-syncs; users pick it up on their next
   session or plugin refresh.
   **Path B/C:** update `ref` (or `manifestSha256`) in managed configuration
   and redistribute it. Devices sync on next app launch or periodic re-fetch.
   **Path D:** push the files and bump `version.json`.
   **Path E:** download the tag's Release zip and sha256 (the one step 2
   attached — the Release belongs to the tag, not the channel, so the
   `channel=client` dispatch in step 4 adds no new asset), verify the
   checksum, upload it by hand.
6. Verify the deployed version in the client's Customize → Plugins view, and
   record it in `registry.yaml` (`plugin_version`) from a checkout at the tag
   you just shipped:

   ```bash
   python scripts/provision_client.py <slug> --update --register-only
   ```

   That restamps both version numbers and touches nothing else — no flags to
   restate, no dates moved.

Rollback is `gh workflow run release.yml -f tag=<previous-tag> -f
channel=client` — the same dispatch with the prior tag, which rebuilds and
republishes it verbatim (the build is deterministic; re-cutting the same tag
twice produces a byte-identical dist tree). Because `required` and
`auto_install` refuse unpinned refs on paths B/C, every deployed state is
deterministic and auditable — which is exactly what the "backward
compatibility within a structure-version" rule needs to be checkable.

Removing a marketplace entry uninstalls its plugins on the next sync. Worth
knowing before a client offboards: their skills disappear, the vault does
not.

## Hardened client images

Two admin switches matter, and both are survivable:

- **`skillCreationEnabled: false`** stops users creating or uploading their
  own skills. Skills from organisation plugins keep working — so plugin
  delivery survives a lockdown that would kill any
  save-it-into-Customize workaround.
- **`isLocalDevMcpEnabled: false`** stops users adding local MCP servers.
  Relevant once the recorder sync needs one: it would have to come through
  the plugin's own `.mcp.json` or through admin-provisioned
  `managedMcpServers`, not by asking the EA to add it.

End users cannot add remote MCP servers themselves under any configuration.
Plan connectors as plugin-bundled or admin-provisioned from the start.

## Sources

- [Install plugins](https://claude.com/docs/cowork/guide/plugins)
- [MCP, plugins, skills, and hooks — administrator provisioning](https://claude.com/docs/cowork/3p/extensions)
- [Manage plugins for your organization](https://support.claude.com/en/articles/13837433-manage-plugins-for-your-organization)
- [Claude Cowork architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)
