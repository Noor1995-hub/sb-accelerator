# Provisioning runbook

Setup day, on the client's machines. delaware-side material; never ships.

Work through `pre-flight-checklist.md` first — every item there is either
qualifying or a precondition for a step below. This runbook assumes it came
back green and you are now sitting at the exec's machine with the accelerator
repo checked out.

Do the whole sequence on the exec's machine, then repeat steps 1–5 on the
assistant's. There is no shortcut: Obsidian Sync moves the vault's *content*
between machines, not its plugin binaries or its symlink.

## 1. Instantiate the vault

Copy the contents of `template/` — **including the hidden `.obsidian/`
directory** — into the vault location you agreed with the client.

Do not initialise git in the vault. The vault has no git by design; Obsidian
Sync's version history and the client's own backups cover recovery, and a
`.git` directory inside a synced folder causes more problems than it solves.

Check that `.obsidian/` arrived. A copy that silently skipped it produces a
vault that opens with none of the layout, none of the tables, and no obvious
reason why — the single most common provisioning mistake.

## 2. Provision the Obsidian plugins and theme

From the accelerator repo:

```bash
python scripts/provision_plugins.py <vault>
```

That installs the pinned, checksum-verified releases listed in
`scripts/plugin-pins.json` into the vault's `.obsidian/plugins/` and
`.obsidian/themes/Minimal/`. The vault's first open then needs only the one
**"trust author and enable plugins"** click — turning off Restricted Mode is
the one step that can never ship as files.

**If the client machine has no repo checkout**, install by hand from within
Obsidian. The list the vault expects is in its own
`.obsidian/community-plugins.json`, so you do not need this runbook in front
of you to recover it: Dataview, Minimal Theme Settings, Style Settings,
Notebook Navigator — plus the **Minimal** theme via Settings → Appearance.

## 3. Create the `.claude → claude` symlink

Obsidian hides dot-folders, so the vault keeps Claude Code's home as a visible
`claude/` directory and points `.claude` at it. Claude Code reads `.claude/`;
the exec browses the same files as `claude/`.

In the vault root:

```bash
ln -s claude .claude
```

On Windows: `mklink /D .claude claude`, from an elevated shell or with
Developer Mode enabled — Windows restricts symlink creation otherwise.

The symlink is not a checked-in file on purpose: symlinks do not survive naive
copies, and they do not survive Windows checkouts without symlink privileges.

If it cannot be created on a given machine, point Claude Code at the `claude/`
directory directly. The vault still works; only the dot-path convenience is
lost. Say so out loud rather than leaving it as a silent difference between the
exec's machine and the assistant's.

## 4. Set the Obsidian Sync exclusions

Exclude two paths from sync:

| Path | Why |
|---|---|
| `95-private/` | The exec-private folder. The assistant must never see it, and sync is how it would leak. |
| `_heavy-assets/` | Generated binaries. Excluded for size, not secrecy. |

## 5. Connect Obsidian Sync, then verify the exclusions again

Sign in and connect Sync on this machine.

Then re-check both exclusions **on this machine specifically**. Sync
exclusions are a per-device setting, not a vault setting — setting them on the
exec's machine does nothing for the assistant's. Getting this wrong on the
second machine is how `95-private/` ends up shared, and nothing in the vault
will tell you it happened.

## 6. Hand over

Open the vault and leave the exec on **`Start here`** — their own orientation
note, written for them. Do not walk them through this runbook; none of it is
theirs.

Record the deployment in `registry.yaml` before you leave.
