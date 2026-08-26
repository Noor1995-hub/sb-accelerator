# Provisioning runbook

Setup day, on the client's machines. delaware-side material; never ships.

Work through `pre-flight-checklist.md` first — every item there is either
qualifying or a precondition for a step below. This runbook assumes it came
back green and you are now sitting at the exec's machine with the accelerator
repo checked out.

Do the whole sequence on the exec's machine, then repeat steps 1–5 on the
assistant's. There is no shortcut: Obsidian Sync moves the vault's *content*
between machines, not its plugin binaries or its symlink. Steps 6–7 happen
once, after both machines are provisioned. Step 8 is not a step at all — it is
what Session 1 does about scheduling, and what you should know before it does.

## 1. Instantiate the vault

Copy the contents of `template/` — **including the hidden `.obsidian/`
directory** — into the vault location you agreed with the client.

Do not initialise git in the vault. The vault has no git by design; Obsidian
Sync's version history and the client's own backups cover recovery, and a
`.git` directory inside a synced folder causes more problems than it solves.

Check that `.obsidian/` arrived. A copy that silently skipped it produces a
vault that opens with none of the layout, none of the tables, and no obvious
reason why — the single most common provisioning mistake.

**Note for the data-flow one-pager:** once `/setup-my-brain` binds the exec's
accounts, `99-workflow-config/config.json` holds their connector identifier
(email or account id) as the binding hint — deliberately non-secret, since
it is what a later `config verify-account` check compares the signed-in
account against. If whoever owns information security wants it named, that
is the one line to give them.

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

Exclude three paths from sync:

| Path | Why |
|---|---|
| `95-private/` | The exec-private folder. The assistant must never see it, and sync is how it would leak. |
| `_heavy-assets/` | Generated binaries. Excluded for size, not secrecy. |
| `99-workflow-config/snapshots/` | The full-vault zips `/upgrade-vault` takes before each migration run. Excluded for size and because a snapshot is only ever needed for restore on the machine that made it — there is nothing for the second machine to gain from carrying it. |

All three are account/device-level Obsidian Sync settings, configured on
each machine at provisioning — none of this ships as files, and
`template/.obsidian` carries no sync configuration to skip that step.

## 5. Connect Obsidian Sync, then verify the exclusions again

Sign in and connect Sync on this machine.

Then re-check all three exclusions **on this machine specifically**. Sync
exclusions are a per-device setting, not a vault setting — setting them on the
exec's machine does nothing for the assistant's. Getting this wrong on the
second machine is how `95-private/` ends up shared, and nothing in the vault
will tell you it happened.

## 6. Create the feedback channel

One-time, not per-machine: the token file lands inside the vault and reaches
the assistant's machine the same way everything else does, over Sync.

1. Create a delaware-owned `sb-client-<slug>` GitHub repo for this client.
   `/report-feedback` and `/health-check` only ever open issues on it; feedback
   never lands on a repo shared across clients.
2. Mint a token scoped **fine-grained**, **`issues: read` + `issues: write` on
   that repo only — **no `contents` scope**. This is the leak blast-radius
   control: the token file lives inside the vault, readable by anything with
   vault access, so the worst case of a leak has to stay "someone can file or
   read issues on this client's own feedback repo" — a `contents` scope would
   turn the same leak into read or write access to a repo's actual files, which
   is a materially worse failure than the one this channel is meant to allow.
3. Place the token, and nothing else, at
   `99-workflow-config/secrets/feedback-token` in the instantiated vault — one
   line, no surrounding commentary.
4. Point the vault at the repo:

   ```bash
   python3 <plugin-path>/lib/vaultlib/cli.py config write --vault <vault> \
     --field feedback.repo --value <owner>/sb-client-<slug>
   ```

5. Rotate the token at any tune-up — swap the file's contents; the repo name
   in `config.json` doesn't change, so there is nothing to re-run `config
   write` for.
6. Vault snapshots (`99-workflow-config/snapshots/`) are full-vault zips, so
   they include the token file too — treat a snapshot copied off the machine
   as carrying a live credential, and rotate the token if one ever leaves the
   machine.

## 7. Hand over

Open the vault and leave the exec on **`Start here`** — their own orientation
note, written for them. Do not walk them through this runbook; none of it is
theirs.

Record the deployment in `registry.yaml` before you leave.

## 8. The standing evening run — know what Session 1 will do

Provisioning does not schedule anything. **Session 1 does**, at its close:
`/setup-my-brain` phase 4b invokes `/schedule-daily-loop`, which asks the exec
what time they want tomorrow prepared and creates a Claude scheduled task on
that machine. Nothing here needs doing on setup day — but three things about
it are yours to know before you are asked, because you will be:

1. **It runs where it was created.** The task is machine-local. If the evening
   run is meant to happen on the assistant's machine rather than the exec's,
   it has to be created there, from a session that can see the vault — Session
   1 scheduling it on the exec's laptop does not put it on the EA's.
2. **The machine has to be awake with Claude open.** A task due while the app
   is closed fires at next launch instead. `/evening-sync` recovers on its own
   (the recap window widens and the note says so), but there is no version of
   this that runs on a closed laptop. The vault is a local folder, so a
   cloud-scheduled run has nothing to read.
3. **Its first run happens with the exec in the room, on purpose.** Tool
   permissions are granted per task, during a run — so a routine that has
   never been started by hand stops at a permission prompt the first night it
   tries to reach Plaud or Microsoft 365, unattended, with nobody watching.
   `/schedule-daily-loop` starts it once for exactly this reason. If you are
   ever setting one of these up outside Session 1, do the same.
4. **Say it in those terms, not as a promise.** "Your note is prepared each
   evening the laptop is on" is true and survives contact with a week of
   travel. "Your note arrives every evening" does not, and it is the first
   thing the exec will notice is false.

If the scheduler is unavailable on the client's machine, `/schedule-daily-loop`
hands the job over in writing instead — what, where, who, by when. Make sure
the "who" is you or the EA by name before you leave, and put it in the
registry note for the deployment.
