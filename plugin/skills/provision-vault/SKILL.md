---
name: provision-vault
description: Instantiate a fresh vault from the plugin's own template, install the pinned Obsidian plugins, attempt the .claude symlink, and optionally bind the feedback channel — the zero-checkout provisioning path. Triggers when the user invokes /provision-vault.
user_invocable: true
origin: net-new
---

# Provision Vault

Provisioning still belongs to the consultant, at setup, on each machine —
this skill changes the delivery channel, not who runs it or when. Before
#86 (part 1), the vault template and the Obsidian-plugin provisioner lived
in `scripts/` and `template/`, so setting up a client machine needed an
accelerator repo checkout sitting on it. They now ship inside the plugin
itself (`plugin/template/`, `plugin/lib/`), which means the plugin cache
Claude Code or Cowork already installed is enough — no repo checkout, no
`git clone`, nothing extra to bring to the client's machine.

## Audience

**Consultant-run, at setup day, once per machine.** Never hand this to the
vault owner or their EA — it writes into a location that does not exist
yet, and step 4 touches a credential that must never appear in a chat
transcript. Run the whole sequence on the vault owner's machine, then
repeat steps 1–3 on the assistant's; step 4 is one-time, not per-machine.

## Requirements

Running this needs a shell, so it runs in **Cowork** or **Claude Code** —
it cannot run in **Chat**, because plugins are not loaded there. Say so
plainly rather than trying to copy or symlink anything by hand.

Interpreter resolution — try `python3`, then `python`, then `py -3`, using
the first that works — is documented in the plugin's `CLAUDE.md`; do not
hardcode one name.

Set `VAULT` to the vault location agreed with the client before starting.

## Usage

```
/provision-vault
```

Ask for the vault target path and which machine this is (vault owner's or
assistant's) before running step 1 — step 4 only ever happens once, and
running it a second time on the second machine would mint a second, unused
binding intent.

## Step 1 — Instantiate the vault

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/instantiate_vault.py" "$VAULT"
```

This copies `plugin/template/` — **including the hidden `.obsidian/`
directory** — from the plugin's own cache into `$VAULT`, refuses to touch a
target that already has files in it, makes the copy writable (a read-only
plugin cache — Cowork's is one — would otherwise hand its read-only modes
to every file and folder in the new vault), and verifies afterward that
the vault accepts a write, that `.obsidian/` arrived, and that
`structure-version` reads `2` before reporting success. It also attempts
the `.claude → claude` symlink as part of the same run (see step 3).

Read `ok` first. On `ok: false`, **surface `error` and `hint` verbatim**.
There are two refusals:

- **A target that was not empty** — the usual one. Confirm the intended
  location with the client rather than picking a different one or
  overwriting what is there.
- **A target that is not writable** — the vault location itself refuses
  writes even after the copied modes were normalised. This is a location
  or ownership question for the consultant (in Cowork: is `$VAULT` inside a
  connected folder?), never something to route around with `sudo` or by
  writing files some other way. Remove the partial copy before retrying.

On `ok: true`, this same call already records the vault's provenance
baseline — which plugin version and structure version provisioned it, and
a digest of every shipped file as laid down — at
`99-workflow-config/provenance.json`. Nothing further to run for that:
`/health-check` reads plugin-version drift off it later, and a future
`/upgrade-vault` step reads it to know what it can refresh silently versus
what needs the consultant's eyes. Report `result.provenance` only if it
starts with `"failed —"` — a provenance write failing on its own is never
a reason to redo provisioning, but it is worth a one-line note for whoever
runs the next tune-up.

**If both `provenance` and `symlink` start with `"failed —"`, stop.** Two
unrelated soft failures in the same run are not two soft failures: they
are the first two writes into the new vault, and both failing means the
vault cannot be written to at all. Check the target before anything else
— `ls -ld "$VAULT" "$VAULT/99-workflow-config"`, then try creating a file
there — and do not continue to `config write` or step 2 until it accepts a
write. Since 0.10.29 step 1 refuses such a vault outright with `ok:
false`, so this pairing should not occur; the rule stays because it is
what tells a broken target apart from two coincidences.

Never `git init` the vault. It has no git by design — Obsidian Sync's
version history and the client's own backups cover recovery, and a `.git`
directory inside a synced folder causes more problems than it solves.

Then stamp the vault's horizon — today's date, the provisioning date:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
python3 "$VAULTLIB" config write --vault "$VAULT" --field sync.start-date --value <today, YYYY-MM-DD>
```

`sync.start-date` is the line no sync ever crosses: no adapter lists,
fetches, or writes a meeting dated before it, so recurring calendar series
cannot drag in occurrences from before the vault existed. If the client
wants meetings from before today in the vault, that is a deliberate,
interactive backfill run later — never a reason to backdate this value.

## Step 2 — Obsidian plugins and theme

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/provision_plugins.py" "$VAULT"
```

This installs the pinned releases from the plugin's own vendored copies
(`vendor/obsidian/`) into `.obsidian/plugins/` and
`.obsidian/themes/Minimal/`, verifying each file against the sha256 in
`lib/plugin-pins.json` before it is written — same zero-checkout path as
step 1, and **no network needed**: the bytes travel inside the plugin
cache, so a Cowork sandbox with egress off installs exactly what a
machine with egress on would. Exit 0 means done; report any `error: ...`
lines on stderr verbatim, and the summary line
(`N installed, N already ok, N problem(s).`) either way. A fresh vault
reports `14 installed`; a re-run reports `14 already ok`.

A `vendored copy sha256 mismatch` error means the plugin itself shipped a
wrong file — the script refuses to install it and does not try to download
a replacement. That is a plugin defect to report through the feedback
channel, not something to route around on setup day.

The vault's first open then needs only the one **"trust author and enable
plugins"** click — turning off Restricted Mode is the one step that can
never ship as files.

**Fallback if this step fails:** install by hand from within Obsidian. The
vault's own `.obsidian/community-plugins.json` names exactly what it
expects, so you do not need this skill or the runbook in front of you to
recover it: Dataview, Minimal Theme Settings, Style Settings, Notebook
Navigator — plus the **Minimal** theme via Settings → Appearance. If you
install Dataview by hand, **pick version 0.5.68 explicitly** (the
community browser offers a newer 0.5.70 that is a mislabeled beta with a
broken manifest); the other three and the theme can take their latest.

## Step 3 — Confirm the symlink

Read step 1's `symlink` field and report it, rather than assuming it
worked:

- `"created"` — done, nothing further to do.
- `"failed — <reason>"` with `provenance` **not** failed — most likely
  Windows without symlink privileges. Say so out loud and give the
  fallback: `mklink /D .claude claude` from an elevated shell, or with
  Developer Mode enabled. If neither is available on this machine, point
  Claude Code at the `claude/` directory directly instead of `.claude/` —
  the vault still works; only the dot-path convenience is lost.
- `"failed — <reason>"` with `provenance` **also** failed — not a symlink
  story at all: the vault is not writable. Go back to step 1's
  writability check before doing anything else.
- `"skipped — ..."` — the template shipped without a `claude/` directory to
  link, which is a plugin defect, not something to work around by hand;
  report it rather than improvising a fix.

## Step 4 — Feedback channel (optional, skippable)

This step is **one-time per client, not per machine**, and can be skipped
entirely for now — a vault with no feedback channel configured degrades
gracefully; `/report-feedback` and `/health-check` just save the draft to
the inbox instead of sending it.

Repo creation and token minting stay a manual, out-of-band consultant
action — this skill never does either:

1. A delaware-owned `sb-client-<slug>` GitHub repo, scoped to this client
   only.
2. A fine-grained token: `issues: read` + `issues: write` on that repo,
   **no `contents` scope** — the leak blast-radius control.

Ask whether the consultant has already placed that token at
`99-workflow-config/secrets/feedback-token` inside `$VAULT` (one line, no
surrounding commentary). **Never ask for the token's value in chat, and
never open or display that file's contents** — confirm only that it exists
and is non-empty:

```bash
test -s "$VAULT/99-workflow-config/secrets/feedback-token" && echo "token file present" || echo "token file missing"
```

Report only `present` or `missing`, never the file's contents. If it is
missing, tell the consultant exactly where to place it and stop here for
now — come back to the rest of this step once it exists.

Once the token file is confirmed present, bind the vault to the repo:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
python3 "$VAULTLIB" config write --vault "$VAULT" --field feedback.repo --value <owner>/sb-client-<slug>
```

## Handoff — what this skill deliberately did not do

Enumerate these out loud before ending the session, and point at
`playbooks/provisioning-runbook.md` to finish the rest of setup day — this
skill covers that runbook's §1–§3 and the config half of §6, not the whole
day:

- **Obsidian's Restricted-Mode "trust author and enable plugins" click** —
  no file can do this; it happens the first time the vault owner or
  assistant opens the vault.
- **Connecting Obsidian Sync and setting (then re-checking) the three sync
  exclusions on each machine** — `95-private/`, `_heavy-assets/`,
  `99-workflow-config/snapshots/` — runbook §4–5. Per-device settings, not
  vault settings; this skill never touches them.
- **Minting or rotating the feedback repo's token** — a manual, out-of-band
  action, described above but never performed by this skill.
- **Handover** — opening the vault to `Start here` for the vault owner and
  recording the deployment in `registry.yaml` — runbook §7.

## Hard rules

1. **Never `git init` the vault.**
2. **Never display, log, or ask for the feedback token's value.** Confirm
   only that the file exists and is non-empty.
3. **Never paraphrase `error` or `hint` from `instantiate_vault.py`.** A
   refused, non-empty target is a location question for the consultant to
   resolve with the client, not something to route around; a refused,
   unwritable target is a permissions question for the same conversation,
   never a reason for `sudo` or a location picked on your own.
4. **Never run this against a vault the owner or assistant is actively
   using.** Step 1's refusal on a non-empty target is a safety net, not
   permission to retarget an in-use vault at will.
