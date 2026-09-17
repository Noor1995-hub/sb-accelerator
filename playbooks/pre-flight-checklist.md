# Pre-flight checklist

Run before committing to an engagement. delaware-side material; never ships.

The items marked **qualifying** can disqualify a client outright or force a
degraded deployment — establish them in the first technical conversation,
not on setup day. Everything else is a setup task.

Platform requirements verified against Anthropic's documentation on
2026-08-23; re-verify each engagement, since these move.

## 1. Claude entitlement — qualifying

- [ ] **Paid plan with Cowork available.** Cowork requires a paid plan; the
      org-managed plugin path requires **Team or Enterprise**.
- [ ] **Both Cowork *and* Skills enabled** for the org. Two separate admin
      toggles; plugin provisioning needs both.
- [ ] **A named Claude administrator** who can connect a plugin marketplace
      and set installation preferences. Without one, delivery falls back to
      each user installing by hand.
- [ ] Seats for the vault owner **and** the assistant. The assistant runs the
      operational surface; an owner-only seat means owner-as-operator.
- [ ] **Cloud sessions disabled for the deployment's users at org level, or
      both users keep the cloud toggle off.** v1 runs local only, because the
      vault is a local folder — a Cowork cloud session ("Run new tasks in the
      cloud") cannot see it.

## 2. Device capability — qualifying

Cowork runs its shell and any code inside a **dedicated Linux VM** (Apple
Virtualization.framework on macOS, Hyper-V on Windows). Both machines need to
be able to run that VM.

- [ ] **macOS:** macOS 11 or later.
- [ ] **Windows:** the `VirtualMachinePlatform` optional feature enabled —
      `Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All`.
- [ ] **Windows: administrator privileges at install.** A standard user can
      install Claude Desktop but **Cowork will not be available**. This is
      the single most common blocker on a managed fleet.
- [ ] **Not a VDI or nested-VM fleet.** Anthropic states that "virtual
      machines and VDI environments without nested virtualization aren't
      supported." A client whose knowledge workers live in Citrix or AVD
      without nested virtualisation **cannot run Cowork**. Establish this
      early — it is the one finding that can end a qualification
      conversation.
- [ ] Hardware virtualisation enabled in firmware (usually is; check if the
      VM fails to start).
- [ ] **git on the device baseline** *if* using a git-sourced marketplace
      (Git for Windows; Xcode Command Line Tools on macOS). Otherwise choose
      the HTTPS or ZIP delivery path — see `plugin-distribution.md`.

Windows edition: Anthropic's docs do not state whether Home is excluded.
`VirtualMachinePlatform` is the same feature WSL2 uses and Home does have it,
so Home is *probably* fine — but verify on the client's actual image rather
than reasoning about it.

## 3. Vault and sync

The setup-day steps themselves live in `provisioning-runbook.md`. These are
the questions to settle before you get that far.

- [ ] Device/MDM policy permits **Obsidian** and **Claude Desktop**.
- [ ] Obsidian Sync account available (or an agreed alternative), signed in
      on both machines.
- [ ] Sync exclusions agreed: `95-private/` and `_heavy-assets/`. Applying
      them is per-machine, not per-vault — runbook §4–5.
- [ ] The `.claude → claude` symlink **can** be created on both machines. On
      Windows this needs `mklink /D` from an elevated shell or Developer
      Mode; if that is off the table the vault still works on a degraded
      path — runbook §3.
- [ ] **Not** a prerequisite: network egress from Cowork, or reachability
      of GitHub releases. The pinned Obsidian plugins and theme ship inside
      the plugin itself (`plugin/vendor/obsidian/`) and
      `plugin/lib/provision_plugins.py` installs them from there — offline,
      checksum-verified. Do not ask the client's IT to enable Cowork's
      *Allow network egress* for provisioning; it is an org-wide admin
      setting their console flags as a security risk, and it would not help
      (GitHub's release-asset host is blocked even with it on). The by-hand
      install remains the fallback if the script itself fails — runbook §2.
- [ ] Vault folder connected in Cowork on both machines. Confirm Cowork
      picks up the vault's `CLAUDE.md` as folder instructions — it does so by
      default, and it should appear in Cowork's context panel as
      "Instructions · CLAUDE.md".
- [ ] **Vault folder created before the Cowork session is started**, on each
      machine. Cowork's VM mounts the connected folder at session boot, so a
      folder created mid-session is invisible to the shell even after you
      pick it — provisioning cannot write there until the session is
      restarted. Order matters: create the empty folder, *then* start the
      session — runbook §0.

## 4. Plugin delivery

- [ ] Delivery path chosen and agreed with client IT — see
      `plugin-distribution.md` for the five options and their trade-offs.
- [ ] For the private-GitHub path: decided **how** the client's admin gets
      repository access (read-only outside collaborator on the delaware repo,
      or a client-owned mirror we push to), and the Claude GitHub App
      installed on whichever repo they connect.
- [ ] Installation preference set to **Required** so the plugin cannot drift
      off a machine.
- [ ] Plugin version recorded in `registry.yaml`.

## 5. Capture inflows

- [ ] M365 tenant consent for the connector (Teams transcripts, calendar,
      mail).
- [ ] Teams admin has enabled **Transcript API access — Microsoft Graph
      access** for the tenant (Microsoft switched it off by default in late
      July 2026). Without it every Teams transcript read answers 403 and the
      product looks broken on day one.
- [ ] The client's own email domains listed (seed for
      `adapters.m365.home_domains`; all of them, including subsidiaries and
      legacy domains). Meetings hosted by anyone outside those domains are
      recorder territory by design — say so to the vault owner before the
      first sync.
- [ ] Recorder hardware ordered and account provisioned.
- [ ] **Recording-consent legal check** — jurisdiction plus client policy.
      The client's legal function decides; we do not advise on it. Blocking
      for any recorder-based capture.
- [ ] Email-forwarding address into the inbox agreed, if used.
- [ ] Note that end users **cannot add remote MCP servers themselves** under
      any configuration. Any connector the skills need must be bundled in the
      plugin's `.mcp.json` or provisioned by the admin.

## 6. People and trust boundary

- [ ] **Assistant scope conversation held.** The assistant sees everything
      outside `95-private/`. Name what that includes out loud, with the vault
      owner, before any content lands.
- [ ] Data-flow one-pager signed off by whoever owns information security.
- [ ] Confirm the client org's conversation retention setting with their
      Claude admin (Anthropic default is 6 years for Cowork session
      transcripts) and record it in the data-flow one-pager.
- [ ] Feedback repo created (`sb-client-<slug>`, or `sb-internal-<slug>` for
      an internal deployment); the vault owner can raise issues into it via
      `/report-feedback`.
- [ ] Deployment registered in `registry.yaml`.

## Degradation ladder

When an item above fails, the honest fallback rather than a silent downgrade:

| Failure | Consequence |
|---|---|
| No Cowork (VDI, no admin rights) | No operational surface. Claude Code on a permitted machine, or decline the engagement. |
| No Team/Enterprise | No org-managed plugin. Per-user install by hand; drift is now your problem. |
| No client GitHub access | ZIP upload path; quarterly updates become a manual handover. |
| No assistant seat | Owner-as-operator. Materially worse; say so before selling it. |
| No recording consent | Capture narrows to Teams transcripts, forwarded mail, and typed input. |
| No Obsidian permitted | Vault still works through Cowork and Chat; the browse tier is gone. |
| Cloud sessions cannot be disabled org-wide | Agree the toggle-off norm with both users instead; a cloud session that opens the vault anyway sees a missing-path error, not silent corruption. |
