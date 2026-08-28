# Local setup

No app to run — this repo is a plugin + template + docs. You need:

- `gh` CLI, authenticated with access to `DLW-INT-BTA-BELUX`
- Python 3.13 with `pytest` and `pyyaml` (`pip install pytest pyyaml`)

## Run what CI runs

```bash
python scripts/lint_plugin.py
python scripts/validate_template.py
python -m pytest scripts/tests -q
```

(If `python` is not on your PATH — stock macOS — use `python3`.)

## Test the plugin against a demo vault

This is the full path from a fresh clone to a hand-testable vault. It's the
acceptance test for the test-vault harness itself — if any step here doesn't
work, that's a bug in the harness, not in your setup.

### 1. Create the test vault

```bash
python scripts/make_test_vault.py /tmp/sb-test-vault
```

This copies `plugin/template/` into `/tmp/sb-test-vault` and overlays
`fixtures/demo-vault/` on top — a populated demo vault for one fictional
persona (Morgan Ellery, CCO at Cascadia Intermodal Group). The script
refuses to touch a target directory that already exists and has files in
it — it fails fast (exit 1) instead of overwriting. Delete the directory
first when you want a clean rebuild.

Add `--with-plugins` to also download the pinned Obsidian community plugins and the Minimal theme into the vault (network required — pins and checksums live in `plugin/lib/plugin-pins.json`):

```bash
python scripts/make_test_vault.py /tmp/sb-test-vault --with-plugins
```

To test the *unpopulated* onboarding path instead (no demo content, just
the placeholder template):

```bash
python scripts/make_test_vault.py /tmp/sb-onboarding-vault --fresh
```

### 2. Open it in Obsidian

Open `/tmp/sb-test-vault` as an Obsidian vault (`Open folder as vault`).

If you created the vault with `--with-plugins`, the community plugins and
the Minimal theme are already on disk and marked enabled — Obsidian shows
one **"trust author and enable plugins"** dialog on first open; accept it
and you're done (turning off Restricted Mode is the one step that can never
ship as files, by design).

If you created the vault without the flag, either re-create it with
`--with-plugins`, run `python plugin/lib/provision_plugins.py /tmp/sb-test-vault`
and reopen the vault, or install by hand — Dataview, Minimal Theme Settings,
Style Settings, Notebook Navigator, plus the Minimal theme via Settings →
Appearance. The authoritative list is the vault's own
`.obsidian/community-plugins.json`; `playbooks/provisioning-runbook.md` §2
covers the same fallback on a client machine.

### 3. Verify what the vault renders

**Both halves of this are now automated.** Which rows each view shows is
asserted in CI (`scripts/tests/test_bases_views.py` via `scripts/basesim.py`,
plus `test_dataview_refs.py` for property references). What it *looks like* is
asserted locally by the probe harness:

```bash
# The probe only drives vaults under test-vaults/ (see the guard, below), so
# build one there rather than in /tmp:
python scripts/make_test_vault.py test-vaults/$(date +%F)-visual --with-plugins
python scripts/obsidian_probe.py doctor
python scripts/obsidian_probe.py up --vault test-vaults/$(date +%F)-visual
python scripts/obsidian_probe.py tour
python -m pytest scripts/tests -q -m obsidian
```

That launches an isolated Obsidian, opens each Base view, project index, entity
dossier and a daily note in Live Preview, and captures a screenshot plus a DOM
dump of each into `.obsidian-probe-out/`. It asserts no view errors or renders
empty, that column headers are the declared `displayName`s rather than raw
property names, that Dataview blocks render tables, that the
`<!-- evening-sync:* -->` markers are hidden in Live Preview, and that the real
Bases engine agrees with `basesim.py` row for row. Full guide, prerequisites
and traps: `docs/visual-verification.md`.

The probe refuses any vault outside `test-vaults/` — that guard is what keeps a
mistargeted `vault=` away from your real notes. `test-vaults/` is gitignored.

**What still needs your eyes** — read the PNGs the tour captured, or open the
vault. Assertions cover what a selector can express; these are judgement:

- Column widths and date/duration/list formatting are legible rather than
  cramped or raw.
- Heading colours, page width and spacing look deliberate.
- Two projects — `commercial-ops-pipeline-governance` and
  `meridian-warehouse-pilot-phase-0` — have no decisions yet, so an empty
  decisions table there is correct, not a bug.
- Notebook Navigator's Shortcuts section lists Meetings, Projects, Entities,
  People, Decisions and the daily-notes folder (rainbow-tinted), and
  `claude/skills` is browsable in the file tree (`ls -la` shows
  `.claude -> claude`).

If a row set ever disagrees with what Obsidian shows, **Obsidian is right** —
fix `scripts/basesim.py` and the expectations it pinned. The probe's
cross-check enforces that continuously, but only on a **pristine** vault: it
skips on one you have been hand-testing in, because notes created during
testing are legitimate rows that `basesim` cannot know about.

### 4. Load the plugin locally and verify skills are invocable

**Claude Code** can load the plugin from a path:

```bash
cd /tmp/sb-test-vault
claude --plugin-dir /path/to/sb-accelerator/plugin
```

Run `/help` and confirm `/new-project`, `/update-entity`, and `/log-decision`
appear.

**Cowork cannot** — `--plugin-dir` is a Claude Code flag, and Cowork loads
skills only from installed plugins and your own skill store, never from a
connected folder. To exercise the skills where they are designed to run, add
this repo as a marketplace (Customize → Plugins → Add marketplace) using the
root `.claude-plugin/marketplace.json` (`sb-accelerator-dev`), then install
`second-brain`.

### 5. Run a skill against the fixtures

Open the test vault and try them:

```
/new-project "Northgate Terminal Refresh"
/update-entity nordbridge-components
/log-decision meridian-yard-automation-program
```

Then check the CLI directly, which is what the skills call:

```bash
python3 plugin/lib/vaultlib/cli.py entity read \
  --vault /tmp/sb-test-vault --slug meridian-freight-holdings
```

Every call prints one JSON object with an `ok` field. Confirm the created
project's frontmatter matches
`plugin/template/99-workflow-config/reference/ontology.md`, and that its body carries
the three H2 sections the ontology's `body_sections` declares.

### 6. Tear down and recreate

```bash
rm -rf /tmp/sb-test-vault
python scripts/make_test_vault.py /tmp/sb-test-vault
```

Confirms the harness is fully disposable — no state leaks between runs.
