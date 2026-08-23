# Vault template

The L0 vault skeleton, instantiated once per client deployment: folder
structure, `.obsidian/` configuration, `.base` views, vault instructions
(`CLAUDE.md`), a context portfolio with guided placeholder slots, and a
`structure-version` marker consumed by `/upgrade-vault`.

## Instantiating

Copy the contents of this directory (including `.obsidian/`) into the new
vault location on the client machine. Do not initialize git in the vault —
the vault has no git by design; snapshots and sync history cover recovery.

## Provisioning steps that cannot ship as files

Obsidian Sync requires a signed-in account, so the consultant configures
these by hand at provisioning (see the pre-flight checklist playbook):

1. **Provision community plugins and the Minimal theme.** Preferred: run
   `python scripts/provision_plugins.py <vault>` from the accelerator repo —
   it installs the pinned, checksum-verified releases listed in
   `scripts/plugin-pins.json` into `.obsidian/plugins/` and
   `.obsidian/themes/Minimal/`, so the vault's first open needs only the
   one "trust and enable" click. Fallback (no repo access on the client
   machine): install by hand the plugins listed in
   `.obsidian/community-plugins.json` (Dataview, Minimal Theme Settings,
   Style Settings, Notebook Navigator) and the **Minimal** theme.
2. **Create the `.claude → claude` symlink** in the vault root:
   `ln -s claude .claude` (macOS/Linux) — Obsidian hides dot-folders, so
   the vault keeps Claude Code's home visible as `claude/` with `.claude`
   pointing at it. On Windows: `mklink /D .claude claude`, run from an
   elevated shell or with Developer Mode enabled (Windows restricts symlink
   creation otherwise). `make_test_vault.py` does this automatically for
   test vaults; on client machines it is a manual step
   (`template/claude/README.md` explains the arrangement). If symlink
   creation isn't possible on a given machine, point Claude Code at the
   `claude/` directory directly — the vault still works; only the
   `.claude` dot-path convenience is lost.
3. **Exclude from Obsidian Sync:** `95-private/` (exec-private folder) and
   `_heavy-assets/` (generated binaries).
4. Connect Obsidian Sync on both machines (exec + assistant) and verify the
   exclusions on each.

## Markers

- `structure-version` — plain integer, bumped only by structure migrations
  under `migrations/`; read by `/upgrade-vault`.
