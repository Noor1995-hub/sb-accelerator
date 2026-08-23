# Vault UX Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two vault UX defaults from Michael's hand-testing feedback: Notebook Navigator preconfigured (rainbow colors + Bases/daily-notes shortcuts) and a visible `claude/` folder with a `.claude → claude` symlink created at instantiation — closing GitHub issue #31.

**Architecture:** `template/.obsidian/plugins/notebook-navigator/data.json` ships a MINIMAL settings file (one `vaultProfiles` profile carrying `fileVisibility: "all"`, the six shortcuts, and the `navRainbow` block; plus a `folderAppearances` entry for `claude/skills`); the plugin fills every other key with defaults. Because the reference config came from NN 2.6.2 and we pin 3.3.4, Task 1 first verifies the key shapes against the 3.3.4 source on GitHub and adapts only if drifted. The template gains a visible `claude/` directory (`README.md` + `skills/.gitkeep`); `make_test_vault.py` creates the relative symlink `.claude → claude` after instantiation (graceful stderr warning if the OS refuses — the symlink is deliberately NOT tracked in git, since mode-120000 symlinks materialize as broken text files on Windows checkouts without symlink privileges). A new pytest module guards the shipped data.json (parses; every shortcut path exists in the template; rainbow on; visibility all).

**Tech Stack:** Python 3.13 stdlib + pytest (existing). No new dependencies.

**Spec:** GitHub issue #31 (read via `gh issue view 31`). Reference config inspected 2026-08-23 in the lab vault (NN 2.6.2); verbatim `navRainbow`/`shortcuts` shapes are embedded below.

## Global Constraints

- **Clean-room rule:** everything under `template/` ships — no denylisted term (michael/bulthe/bulthé/busdev) in any new content, and no lab-vault-specific names. The new content below is clean.
- **Shortcut order is Michael's, exactly:** Meetings, Projects, Entities, People, Decisions, then the daily-notes folder.
- **The symlink is never committed to git.** Only the scripts create it, at instantiation time.
- **CI stays offline:** the new tests read local files only. Network is allowed only in Task 1's schema-verification step (implementer-run).
- **No `plugin/` files touched** → no version bump. No `structure-version` bump (additive template content; existing vaults get these via a future migration if ever needed — out of scope).
- **Commit trailer**, every commit, exact: `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Branch:** `feat/vault-ux-defaults`.
- **Local verification trio:** `python scripts/lint_plugin.py` · `python scripts/validate_template.py` · `python -m pytest scripts/tests -q` (use `python3`).

---

## File structure

| File | Responsibility |
|---|---|
| `template/.obsidian/plugins/notebook-navigator/data.json` | Shipped NN defaults: profile with shortcuts + rainbow + visibility |
| `scripts/tests/test_template_config.py` | Guard: data.json parses, shortcut paths exist, rainbow/visibility asserted |
| `template/claude/README.md` | Explains the visible-skills-folder arrangement |
| `template/claude/skills/.gitkeep` | Placeholder for vault-local skills |
| `scripts/make_test_vault.py` | Creates `.claude → claude` symlink post-copy; surfaces warnings |
| `scripts/tests/test_make_test_vault.py` | +2 tests: symlink created; OS refusal degrades to warning |
| `template/README.md` | Provisioning: symlink step documented for client machines |
| `docs/local-setup.md` | Runbook: what to verify in Obsidian (shortcuts, rainbow, claude/skills) |

---

### Task 1: Notebook Navigator defaults in the template (+ guard test)

**Files:**
- Create: `template/.obsidian/plugins/notebook-navigator/data.json`
- Test: `scripts/tests/test_template_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the shipped data.json; `folderAppearances["claude/skills"]` forward-references the folder Task 2 creates (harmless if read before Task 2 lands — NN ignores appearance entries for missing folders).

- [ ] **Step 1: Verify the settings schema against NN 3.3.4 (network, judgment step)**

The reference shapes below were read from a live NN **2.6.2** config; we pin **3.3.4**. Before writing the file, fetch the 3.3.4 source and confirm the key shapes still hold — check the settings/types definitions, e.g.:

```bash
curl -sL https://raw.githubusercontent.com/johansan/notebook-navigator/3.3.4/src/settings.ts | head -300
```

(If that path 404s, list the repo tree at the tag — `gh api repos/johansan/notebook-navigator/git/trees/3.3.4?recursive=1 --jq '.tree[].path' | grep -i -E "settings|types"` — and read the file(s) defining the persisted settings interface and defaults.)

Confirm specifically: (a) settings still persist a `vaultProfiles` array of profiles with `id`/`name`/`fileVisibility`/`shortcuts`/`navRainbow`; (b) `shortcuts` entries are `{type: "note"|"folder", path: string}`; (c) the `navRainbow` sub-keys used below still exist; (d) `folderAppearances` with `groupBy` still exists. **If any shape drifted in 3.3.4, adapt the JSON in Step 2 to the 3.3.4 shape (preserving the intent: rainbow on for folders/shortcuts/recents, the six shortcuts in order, visibility all) and record exactly what you changed and the evidence in your report.** If you cannot confirm the schema at all, STOP and report BLOCKED with what you found.

- [ ] **Step 2: Create the settings file**

Create `template/.obsidian/plugins/notebook-navigator/data.json` (adapt only per Step 1 findings):

```json
{
  "vaultProfiles": [
    {
      "id": "default",
      "name": "Default",
      "fileVisibility": "all",
      "propertyKeys": [],
      "hiddenFolders": [],
      "hiddenTags": [],
      "hiddenFileNames": [],
      "hiddenFileTags": [],
      "hiddenFileProperties": [],
      "navigationBanner": null,
      "periodicNotesFolder": "",
      "shortcuts": [
        { "type": "note", "path": "20-meetings/Meetings.base" },
        { "type": "note", "path": "30-projects/Projects.base" },
        { "type": "note", "path": "40-entities/Entities.base" },
        { "type": "note", "path": "50-people/People.base" },
        { "type": "note", "path": "30-projects/Decisions.base" },
        { "type": "folder", "path": "60-daily-notes" }
      ],
      "navRainbow": {
        "mode": "foreground",
        "balanceHueLuminance": true,
        "separateThemeColors": false,
        "shortcuts": {
          "enabled": true,
          "firstColor": "#ef4444",
          "lastColor": "#8b5cf6",
          "darkFirstColor": "#ef4444",
          "darkLastColor": "#8b5cf6",
          "transitionStyle": "rgb"
        },
        "recent": {
          "enabled": true,
          "firstColor": "#ef4444",
          "lastColor": "#8b5cf6",
          "darkFirstColor": "#ef4444",
          "darkLastColor": "#8b5cf6",
          "transitionStyle": "rgb"
        },
        "folders": {
          "enabled": true,
          "firstColor": "#ef4444",
          "lastColor": "#8b5cf6",
          "darkFirstColor": "#fb7185",
          "darkLastColor": "#c084fc",
          "transitionStyle": "hue",
          "scope": "root"
        },
        "tags": {
          "enabled": false,
          "firstColor": "#ef4444",
          "lastColor": "#8b5cf6",
          "darkFirstColor": "#fb7185",
          "darkLastColor": "#c084fc",
          "transitionStyle": "hue",
          "scope": "root"
        },
        "properties": {
          "enabled": false,
          "firstColor": "#ef4444",
          "lastColor": "#8b5cf6",
          "darkFirstColor": "#fb7185",
          "darkLastColor": "#c084fc",
          "transitionStyle": "hue",
          "scope": "root"
        }
      }
    }
  ],
  "vaultProfile": "default",
  "folderAppearances": {
    "claude/skills": { "groupBy": "none" }
  }
}
```

- [ ] **Step 3: Write the guard test (failing first is not meaningful here — the file exists by now; write it and run it)**

Create `scripts/tests/test_template_config.py`:

```python
"""Guards for shipped .obsidian configuration in the template.

The Notebook Navigator settings file references template paths (shortcuts)
— these tests keep it honest when folders or .base files get renamed."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "template"
NN_DATA = TEMPLATE / ".obsidian" / "plugins" / "notebook-navigator" / "data.json"

EXPECTED_SHORTCUTS = [
    ("note", "20-meetings/Meetings.base"),
    ("note", "30-projects/Projects.base"),
    ("note", "40-entities/Entities.base"),
    ("note", "50-people/People.base"),
    ("note", "30-projects/Decisions.base"),
    ("folder", "60-daily-notes"),
]


def load_profile() -> dict:
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    profiles = data["vaultProfiles"]
    assert len(profiles) == 1, "template ships exactly one NN profile"
    return profiles[0]


def test_nn_data_json_parses_and_profile_selected():
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    assert data["vaultProfile"] == data["vaultProfiles"][0]["id"]


def test_nn_shortcuts_exact_order_and_paths_exist():
    profile = load_profile()
    got = [(s["type"], s["path"]) for s in profile["shortcuts"]]
    assert got == EXPECTED_SHORTCUTS, f"shortcut list drifted: {got}"
    for kind, path in got:
        target = TEMPLATE / path
        if kind == "folder":
            assert target.is_dir(), f"shortcut folder missing in template: {path}"
        else:
            assert target.is_file(), f"shortcut file missing in template: {path}"


def test_nn_file_visibility_shows_base_files():
    assert load_profile()["fileVisibility"] == "all"


def test_nn_rainbow_enabled_for_folders_shortcuts_recents():
    rainbow = load_profile()["navRainbow"]
    for section in ("folders", "shortcuts", "recent"):
        assert rainbow[section]["enabled"] is True, f"navRainbow.{section} must be enabled"
```

(If Step 1 forced a shape adaptation, adapt these assertions to match — keeping their intent — and say so in your report.)

- [ ] **Step 4: Run the tests + trio**

Run: `python3 -m pytest scripts/tests/test_template_config.py -v` → 4 passed.
Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q` → all green (58 + 4 = 62).

- [ ] **Step 5: Commit**

```bash
git add template/.obsidian/plugins/notebook-navigator/data.json scripts/tests/test_template_config.py
git commit -m "$(cat <<'EOF'
feat(template): ship Notebook Navigator defaults (rainbow, Bases shortcuts)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Visible `claude/` folder + instantiation-time symlink

**Files:**
- Create: `template/claude/README.md`
- Create: `template/claude/skills/.gitkeep` (empty file)
- Modify: `scripts/make_test_vault.py`
- Test: `scripts/tests/test_make_test_vault.py`

**Interfaces:**
- Consumes: `build_vault(target, repo_root, fresh)` from the existing script.
- Produces: `build_vault` now returns `list[str]` (warnings; empty on success — existing callers/tests ignore the return value, so this is backward-compatible). The symlink contract: `<vault>/.claude` is a RELATIVE symlink to `claude`.

- [ ] **Step 1: Create the template folder**

Create `template/claude/README.md`:

```markdown
# claude/ — vault-local Claude Code home (visible)

Obsidian hides dot-folders, so this vault keeps Claude Code's home as a
visible `claude/` directory with a `.claude` symlink pointing at it —
Claude Code reads `.claude/`, you browse and edit the same files here.

- `skills/` — vault-local skills (per-deployment customizations). The
  product's core skills ship via the accelerator plugin, not here.
- The `.claude → claude` symlink is created at instantiation
  (`make_test_vault.py` does it automatically; for client machines it is a
  provisioning step — see the template README). It is intentionally not a
  checked-in file: symlinks do not survive naive copies or Windows
  checkouts without symlink privileges.
```

Create the empty file `template/claude/skills/.gitkeep`.

- [ ] **Step 2: Write the failing tests**

Append to `scripts/tests/test_make_test_vault.py`:

```python
def test_claude_symlink_created(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    link = target / ".claude"
    assert link.is_symlink(), ".claude symlink missing"
    assert os.readlink(link) == "claude", "symlink must be relative, pointing at claude/"
    assert (link / "skills").is_dir(), "symlink must resolve to the visible claude/ dir"


def test_symlink_failure_degrades_to_warning(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    monkeypatch.setattr("make_test_vault.os.symlink", refuse)
    target = tmp_path / "vault"
    warnings = build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "CLAUDE.md").is_file()  # vault still built
    assert any(".claude" in w for w in warnings)
```

Also add `import os` to that test file's imports if not already present.

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_make_test_vault.py -k symlink -v`
Expected: both FAIL — first on `is_symlink` (no link is created yet), second on `make_test_vault.os` (module doesn't import os yet).

- [ ] **Step 4: Implement**

In `scripts/make_test_vault.py`:

1. Add `import os` to the imports.
2. Change `build_vault` to create the symlink and return warnings:

```python
def build_vault(target: Path, repo_root: Path, fresh: bool) -> list[str]:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmptyError(f"{target} already exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "template", target, dirs_exist_ok=True)
    if not fresh:
        shutil.copytree(repo_root / "fixtures" / "demo-vault", target, dirs_exist_ok=True)
    warnings: list[str] = []
    link = target / ".claude"
    if (target / "claude").is_dir() and not link.exists():
        # Relative symlink so the vault stays relocatable. Obsidian hides
        # .claude; the visible claude/ dir is the same files.
        try:
            os.symlink("claude", link)
        except OSError as e:
            warnings.append(
                f"could not create .claude symlink ({e}); create it by hand: ln -s claude {link}"
            )
    return warnings
```

3. In `main`, capture and print the warnings — change the `build_vault(...)` call line to:

```python
        warnings = build_vault(args.target.resolve(), repo_root, args.fresh)
```

and after the `print(f"Test vault created at {args.target} ({mode}).")` line add:

```python
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
```

(Note the ordering in `main` stays: try/except → mode print → warnings → `--with-plugins` block → return.)

4. Append to the module docstring: `Also creates the .claude -> claude symlink so vault-local Claude Code files stay visible in Obsidian (warning, not failure, if the OS refuses).`

- [ ] **Step 5: Run the tests + trio**

Run: `python3 -m pytest scripts/tests/test_make_test_vault.py -v` → 12 passed.
Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q` → all green (64 total).

- [ ] **Step 6: Commit**

```bash
git add template/claude scripts/make_test_vault.py scripts/tests/test_make_test_vault.py
git commit -m "$(cat <<'EOF'
feat: visible claude/ folder in template, .claude symlink at instantiation

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Docs

**Files:**
- Modify: `template/README.md` (add symlink to the provisioning list, renumber)
- Modify: `docs/local-setup.md` (extend runbook step 3's verification list)

**Interfaces:**
- Consumes: Tasks 1–2 behavior.
- Produces: nothing downstream.

- [ ] **Step 1: template/README.md**

In "## Provisioning steps that cannot ship as files", insert a new item after item 1 (the plugin-provisioning step) and renumber the Sync items to 3 and 4:

```markdown
2. **Create the `.claude → claude` symlink** in the vault root:
   `ln -s claude .claude` (macOS/Linux) — Obsidian hides dot-folders, so
   the vault keeps Claude Code's home visible as `claude/` with `.claude`
   pointing at it. `make_test_vault.py` does this automatically for test
   vaults; on client machines it is a manual step (`template/claude/README.md`
   explains the arrangement).
```

- [ ] **Step 2: docs/local-setup.md**

In the runbook's "### 3. Verify the five Bases render" section, append after the People.base bullet:

```markdown
Also verify the navigator defaults: Notebook Navigator's Shortcuts section
lists Meetings, Projects, Entities, People, Decisions and the daily-notes
folder (rainbow-tinted), and `claude/skills` is browsable in the file tree
(`ls -la` in the vault shows `.claude -> claude`).
```

- [ ] **Step 3: Trio + read-back**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q` → green. Read both docs back; confirm numbering and fences.

- [ ] **Step 4: Commit**

```bash
git add template/README.md docs/local-setup.md
git commit -m "$(cat <<'EOF'
docs: document NN defaults verification and the .claude symlink provisioning step

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** issue #31 part 1 (NN config: rainbow, shortcuts in Michael's order, fileVisibility, minimal file, 3.3.4 schema verification, slop-guard pytest) → Task 1; part 2 (visible `claude/`, relative untracked symlink via make_test_vault with graceful degradation, README docs, NN appearance override) → Tasks 1 (override) + 2 + 3.
- **Backward compatibility:** `build_vault`'s return type changes None → list[str]; all existing callers/tests ignore the return value — verified against the current test file, which never binds it (only the new warning test does).
- **The symlink lands AFTER the fixtures overlay** and is guarded by `not link.exists()` — idempotent-shaped even though build_vault only ever runs on empty targets.
- **`--with-plugins` interaction:** provisioner writes under `.obsidian/`, orthogonal to the symlink; NN's shipped data.json is never touched by the provisioner (different file from the plugin's main.js/manifest/styles assets).
- **Placeholder scan:** Task 1 Step 1 is a genuine judgment step (schema verify/adapt) with explicit adapt-or-BLOCK instructions — intended, not a TBD; all other content is literal.
