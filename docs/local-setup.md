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

This copies `template/` into `/tmp/sb-test-vault` and overlays
`fixtures/demo-vault/` on top — a populated demo vault for one fictional
persona (Morgan Ellery, CCO at Cascadia Intermodal Group). The script
refuses to touch a target directory that already exists and has files in
it — it fails fast (exit 1) instead of overwriting. Delete the directory
first when you want a clean rebuild.

Add `--with-plugins` to also download the pinned Obsidian community plugins and the Minimal theme into the vault (network required — pins and checksums live in `scripts/plugin-pins.json`):

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
`--with-plugins`, run `python scripts/provision_plugins.py /tmp/sb-test-vault`
and reopen the vault, or install by hand per `template/README.md` (Dataview,
Minimal Theme Settings, Style Settings, Notebook Navigator + the Minimal
theme via Settings → Appearance).

### 3. Verify the five Bases render

Open each `.base` file and confirm it shows fixture rows, not an empty
table:

- `40-entities/Entities.base` — "All" shows 3 entities; "Prospects" shows
  Nordbridge Components; "Active" shows the other two.
- `30-projects/Projects.base` — "Active" shows 4 projects; "All" shows all 5
  (including the completed Phase 0 pilot).
- `30-projects/Decisions.base` — "All" shows 4 decisions with the
  `supersedes` column populated on one row.
- `20-meetings/Meetings.base` — "Triage" shows exactly 3 meetings (the two
  `needs-review` and one `needs-attention` that are neither reviewed nor
  archived); "All Meetings" shows all 8.
- `50-people/People.base` — "All" shows 10 people; "Uncurated" shows exactly
  one row (Jamie Ellwood, `relationship` empty).

Also verify the navigator defaults: Notebook Navigator's Shortcuts section
lists Meetings, Projects, Entities, People, Decisions and the daily-notes
folder (rainbow-tinted), and `claude/skills` is browsable in the file tree
(`ls -la` in the vault shows `.claude -> claude`).

### 4. Load the plugin locally and verify skills are invocable

**Claude Code** can load the plugin from a path:

```bash
cd /tmp/sb-test-vault
claude --plugin-dir /path/to/sb-accelerator/plugin
```

Run `/help` and confirm `/new-project` and `/update-entity` appear.

**Cowork cannot** — `--plugin-dir` is a Claude Code flag, and Cowork loads
skills only from installed plugins and your own skill store, never from a
connected folder. To exercise the skills where they are designed to run, add
this repo as a marketplace (Customize → Plugins → Add marketplace) using the
root `.claude-plugin/marketplace.json` (`sb-accelerator-dev`), then install
`second-brain`.

### 5. Run a skill against the fixtures

Open the test vault and try both:

```
/new-project "Northgate Terminal Refresh"
/update-entity nordbridge-components
```

Then check the CLI directly, which is what the skills call:

```bash
python3 plugin/lib/vaultlib/cli.py entity read \
  --vault /tmp/sb-test-vault --slug meridian-freight-holdings
```

Every call prints one JSON object with an `ok` field. Confirm the created
project's frontmatter matches
`template/99-workflow-config/reference/ontology.md`, and that its body carries
the three H2 sections the ontology's `body_sections` declares.

### 6. Tear down and recreate

```bash
rm -rf /tmp/sb-test-vault
python scripts/make_test_vault.py /tmp/sb-test-vault
```

Confirms the harness is fully disposable — no state leaks between runs.
