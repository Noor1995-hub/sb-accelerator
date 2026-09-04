# Provisioning runbook

Setup day, on the client's machines. delaware-side material; never ships.

Work through `pre-flight-checklist.md` first — every item there is either
qualifying or a precondition for a step below. This runbook assumes it came
back green and you are now sitting at the vault owner's machine with Claude
Code or Cowork open and the plugin installed. Steps 1–3 run through the
`/provision-vault` skill — no accelerator repo checkout needed, since the
vault template and the provisioning scripts ship inside the plugin itself
(#86). A repo checkout is still a valid fallback (below each step), for a
machine where the plugin cache is unavailable or you are recovering from a
broken install.

Do the whole sequence on the vault owner's machine, then repeat §0 and steps
1–5 on the assistant's. There is no shortcut: Obsidian Sync moves the vault's *content*
between machines, not its plugin binaries or its symlink. Steps 6–7 happen
once, after both machines are provisioned. Step 8 is not a step at all — it is
what Session 1 does about scheduling, and what you should know before it does.

## 0. Create the vault folder *before* you start the Cowork session

On a Cowork machine, do these two things in this order:

1. **Create the empty vault folder** in Finder / Explorer, at the location
   agreed with the client.
2. **Then start the Cowork session** on it — or on a folder that contains
   it.

Cowork's shell runs in a Linux VM that mounts the connected folder when the
session boots. A folder created after that is not mounted, and picking it
in the folder picker does not remount it: the picker grants the *app*
access, which is a different path from the VM's filesystem. The symptom is
a genuinely strange one — a file can be written into the folder and then
be invisible to every shell command, including `/provision-vault`'s own
step 1. Restarting the session is the only fix, so it is cheaper to get
the order right.

Do not work around it by creating the directory from inside the session:
that writes into the VM, and the vault would vanish when the session ends.
If you were diagnosing and left a file in the folder, delete it from the
machine before retrying — step 1 refuses any non-empty target, dotfiles
included.

Claude Code needs none of this — it runs on the machine's own filesystem
and creates the target itself.

## 1. Instantiate the vault

**Primary: run `/provision-vault`.** From Claude Code or Cowork with the
plugin installed, its step 1 runs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/instantiate_vault.py" <vault>
```

which copies `plugin/template/` — **including the hidden `.obsidian/`
directory** — from the plugin's own cache into the vault location you agreed
with the client. No repo checkout involved. It refuses to touch a target
that already has files in it, and it verifies afterward that `.obsidian/`
arrived and `structure-version` reads `2` before reporting success — the
single most common provisioning mistake used to be a copy that silently
skipped the dotfile and opened with none of the layout or tables and no
obvious reason why; this is now checked by the tool that does the copy,
not by a human remembering to look.

Never initialise git in the vault. It has no git by design; Obsidian Sync's
version history and the client's own backups cover recovery, and a `.git`
directory inside a synced folder causes more problems than it solves.

**Note for the data-flow one-pager:** once `/setup-my-brain` binds the vault
owner's accounts, `99-workflow-config/config.json` holds their connector identifier
(email or account id) as the binding hint — deliberately non-secret, since
it is what a later `config verify-account` check compares the signed-in
account against. If whoever owns information security wants it named, that
is the one line to give them.

### Fallback: instantiate by hand

If the plugin cache is unavailable on this machine, or you are recovering
from a broken install, copy the contents of `plugin/template/` — from an
accelerator repo checkout, **including the hidden `.obsidian/` directory** —
into the vault location you agreed with the client, and check that
`.obsidian/` arrived yourself.

## 2. Provision the Obsidian plugins and theme

**Primary: `/provision-vault`'s step 2** runs, from the plugin's own cache —
no repo checkout, same as step 1:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/provision_plugins.py" <vault>
```

That installs the pinned releases listed in the plugin's own
`lib/plugin-pins.json` into the vault's `.obsidian/plugins/` and
`.obsidian/themes/Minimal/`, from the copies vendored inside the plugin at
`vendor/obsidian/` — each file verified against its pinned sha256 before it
is written. **No network is involved**, so Cowork's network-egress setting
is not a prerequisite for this step: do not ask a client's IT to enable it
for provisioning (it is an org-wide admin switch their console flags as a
security risk, and even with it on, GitHub's release-asset host stays
blocked). A fresh vault reports `14 installed, 0 already ok, 0 problem(s).`;
a re-run reports `0 installed, 14 already ok`. The vault's first open then
needs only the one **"trust author and enable plugins"** click — turning off
Restricted Mode is the one step that can never ship as files.

A `vendored copy sha256 mismatch` error means the plugin shipped a wrong
file; the script refuses to install it and will not download a replacement.
File it as a plugin defect and use the by-hand fallback below for that
plugin only.

### Fallback: no plugin cache, or install fully by hand

If you have an accelerator repo checkout but no plugin installed, run the
same script directly: `python plugin/lib/provision_plugins.py <vault>` — the
checkout carries the same vendored tree.

If neither is available, install by hand from within Obsidian. The list the
vault expects is in its own `.obsidian/community-plugins.json`, so you do
not need this runbook in front of you to recover it: Dataview, Minimal
Theme Settings, Style Settings, Notebook Navigator — plus the **Minimal**
theme via Settings → Appearance. **Installing Dataview by hand, pick 0.5.68
explicitly** — the community browser's newer 0.5.70 is a mislabeled beta
with a broken manifest (see `plugin-pins.json`'s `_readme`).

## 3. Create the `.claude → claude` symlink

Obsidian hides dot-folders, so the vault keeps Claude Code's home as a visible
`claude/` directory and points `.claude` at it. Claude Code reads `.claude/`;
the vault owner browses the same files as `claude/`.

**Primary:** `/provision-vault`'s step 1 already attempted this as part of
instantiation and reports the outcome — `"created"`, or `"failed — <reason>"`
if this machine refused it. Confirm which one it reported before moving on.

### Fallback: create it (or recover from a reported failure) by hand

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
vault owner's machine and the assistant's.

## 4. Set the Obsidian Sync exclusions

Exclude three paths from sync:

| Path | Why |
|---|---|
| `95-private/` | The owner-private folder. The assistant must never see it, and sync is how it would leak. |
| `_heavy-assets/` | Generated binaries. Excluded for size, not secrecy. |
| `99-workflow-config/snapshots/` | The full-vault zips `/upgrade-vault` takes before each migration run. Excluded for size and because a snapshot is only ever needed for restore on the machine that made it — there is nothing for the second machine to gain from carrying it. |

All three are account/device-level Obsidian Sync settings, configured on
each machine at provisioning — none of this ships as files, and
`plugin/template/.obsidian` carries no sync configuration to skip that step.

## 5. Connect Obsidian Sync, then verify the exclusions again

Sign in and connect Sync on this machine.

Then re-check all three exclusions **on this machine specifically**. Sync
exclusions are a per-device setting, not a vault setting — setting them on the
vault owner's machine does nothing for the assistant's. Getting this wrong on the
second machine is how `95-private/` ends up shared, and nothing in the vault
will tell you it happened.

## 6. Create the feedback channel

One-time, not per-machine: the token file lands inside the vault and reaches
the assistant's machine the same way everything else does, over Sync.

1. From an accelerator repo checkout, run the script:

   ```bash
   python scripts/provision_client.py <slug> --owner <name or initials> \
     --delivery-path <A..E> --dist-channel client
   ```

   It creates the delaware-owned `sb-client-<slug>` GitHub repo (or reuses it
   if it already exists), seeds its `README.md` and
   `.github/ISSUE_TEMPLATE/feedback.md`, ensures the `feedback` /
   `health-report` / `triage:*` labels, and writes the `registry.yaml` entry
   for you — see step 7. `/report-feedback` and `/health-check` only ever
   open issues on this repo; feedback never lands on a repo shared across
   clients. Pass `--register-only` instead if the repo already exists and
   only the registry entry is missing (never run the script without
   `--register-only` or `--dry-run` unless you mean to create or modify a
   real GitHub repo).
2. Follow the recipe the script prints, verbatim: mint a token scoped
   **fine-grained**, **`issues: read` + `issues: write` on that repo
   only** — **no `contents` scope**. This is the leak blast-radius control:
   the token file lives inside the vault, readable by anything with vault
   access, so the worst case of a leak has to stay "someone can file or
   read issues on this client's own feedback repo" — a `contents` scope
   would turn the same leak into read or write access to a repo's actual
   files, which is a materially worse failure than the one this channel is
   meant to allow. Set the expiration to 1 year — that is what
   `registry.yaml`'s `token_minted` date measures against. Record the mint
   date the same day, which is the last line of the recipe the script prints:

   ```bash
   python scripts/provision_client.py <slug> --update --register-only --token-minted
   ```

   (`--token-minted` bare means today; pass a date — `--token-minted
   2027-03-14` — if you are recording it after the fact.) `provisioned` is a
   different date and stays put: it is the day the deployment was stood up.
3. Place the token, and nothing else, at
   `99-workflow-config/secrets/feedback-token` in the instantiated vault — one
   line, no surrounding commentary.
4. Point the vault at the repo. `/provision-vault`'s step 4 does this once
   the token file above is in place — it verifies the file exists and is
   non-empty **without reading its contents**, then runs:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" config write --vault <vault> \
     --field feedback.repo --value <org>/sb-client-<slug>
   ```

   The script's recipe prints this same command, already filled in — run it
   directly, the same way, if you are not going through the skill.

   **The token usually arrives after setup day, and that is fine.** Skip
   step 4 on the day, then re-run `/provision-vault` against the same vault
   whenever the token is in place: it detects an already-provisioned vault,
   skips instantiation, and offers step 4 alone. You are not meant to
   hand-run the `config write` above because the skill "cannot" be re-run —
   it can.

5. Rotate the token at any tune-up — swap the file's contents; the repo name
   in `config.json` doesn't change, so there is nothing to re-run `config
   write` for. Do re-run the script with `--token-minted` when you rotate,
   though: nothing else restarts the expiry clock, and a `token_minted` left
   at last year's date is how a channel goes quietly dead. Same command as
   step 2 above. Add `--owner`, `--care-package`, `--delivery-path` or
   `--dist-channel` to the same run if any of those changed — see step 7.
6. Vault snapshots (`99-workflow-config/snapshots/`) are full-vault zips, so
   they include the token file too — treat a snapshot copied off the machine
   as carrying a live credential, and rotate the token if one ever leaves the
   machine.

## 7. Hand over

Open the vault and leave the vault owner on **`Start here`** — their own
orientation note, written for them. Do not walk them through this runbook;
none of it is theirs.

`registry.yaml` is already written — step 6 ran `scripts/provision_client.py`,
which wrote the entry as part of creating the feedback channel. Nothing left
to do here except double-check it landed: `git diff registry.yaml` (or
`git status`, if this checkout tracks it) should show one new entry for this
client, with the header comment untouched above it. If anything about the
deployment changes at a tune-up — owner, care package, delivery path, dist
channel — re-run the script with `--update` rather than hand-editing the
YAML.

`--update` only touches what you name. It restamps `plugin_version` and
`structure_version` from the checkout it runs in and leaves every other
field at its registered value, so recording a release against a deployment
that is otherwise unchanged needs no flags at all:

```bash
python scripts/provision_client.py <slug> --update --register-only
```

Both dates survive that (see step 6 for which is which), and you don't have
to restate `--owner` or any field you aren't changing. Run it from a
checkout at the version you actually shipped — that is where the two version
numbers are read from.

## 8. The standing evening run — know what Session 1 will do

Provisioning does not schedule anything. **Session 1 does**, at its close:
`/setup-my-brain` phase 4b invokes `/schedule-daily-loop`, which asks the vault
owner what time they want tomorrow prepared and creates a Claude scheduled task on
that machine. Nothing here needs doing on setup day — but four things about
it are yours to know before you are asked, because you will be:

1. **It runs where it was created.** The task is machine-local. If the evening
   run is meant to happen on the assistant's machine rather than the vault
   owner's, it has to be created there, from a session that can see the vault
   — Session 1 scheduling it on the vault owner's laptop does not put it on
   the EA's.
2. **The machine has to be awake with Claude open.** A task due while the app
   is closed fires at next launch instead. `/evening-sync` recovers on its own
   (the recap window widens and the note says so), but there is no version of
   this that runs on a closed laptop. The vault is a local folder, so a
   cloud-scheduled run has nothing to read.
3. **Its first run happens with the vault owner in the room, on purpose.** Tool
   permissions are granted per task, during a run — so a routine that has
   never been started by hand stops at a permission prompt the first night it
   tries to reach Plaud or Microsoft 365, unattended, with nobody watching.
   This covers Bash too, not just connectors: `/evening-sync` and
   `/sync-recordings` are built so every Bash call on the unattended path is
   either `python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" ...` (every
   deterministic write, plus the scratch-hygiene sweep and the run-log line)
   or a plain `$SCRATCH`-scoped write (`cat > "$SCRATCH/..."`, `printf ... >
   "$SCRATCH/..."`) — so the one manual run grants a single narrow allowlist
   that covers the whole routine, connectors and Bash alike.
   `/schedule-daily-loop` starts it once for exactly this reason. If you are
   ever setting one of these up outside Session 1, do the same, and if that
   first run stops at a prompt for anything outside those two Bash shapes,
   treat it as a product bug to report, not a permission gap to paper over
   with a broader grant.
4. **Say it in those terms, not as a promise.** "Your note is prepared each
   evening the laptop is on" is true and survives contact with a week of
   travel. "Your note arrives every evening" does not, and it is the first
   thing the vault owner will notice is false.

If the scheduler is unavailable on the client's machine, `/schedule-daily-loop`
hands the job over in writing instead — what, where, who, by when. Make sure
the "who" is you or the EA by name before you leave, and put it in the
registry note for the deployment.
