# Plugin Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A script that provisions the four Obsidian community plugins + the Minimal theme into a vault from pinned, checksummed official GitHub releases — collapsing vault setup to one trust click — closing GitHub issue #27.

**Architecture:** `scripts/plugin-pins.json` is the single pin manifest (id, repo, tag, assets, sha256 per asset, license). `scripts/provision_plugins.py` reads it and installs into `<vault>/.obsidian/plugins/<id>/` and `<vault>/.obsidian/themes/Minimal/`, verifying sha256 before install; idempotent (existing file with matching hash = skip; mismatch = repair). The downloader is an injectable `fetch(url) -> bytes` so all tests run offline against fakes; only the implementer's one-time manifest generation and the acceptance run touch the network. `make_test_vault.py` gains `--with-plugins`. CI stays fully offline.

**Tech Stack:** Python 3.13 stdlib only (`urllib.request`, `hashlib`, `json`, `argparse`, `pathlib`) + pytest for tests. No new dependencies.

**Spec:** GitHub issue #27 (read via `gh issue view 27`).

## Verified release data (researched 2026-08-23 — use these exact values)

| id / name | repo (canonical) | tag | assets | license |
|---|---|---|---|---|
| `dataview` | `blacksmithgu/obsidian-dataview` | `0.5.68` | main.js, manifest.json, styles.css | MIT |
| `obsidian-minimal-settings` | `kepano/obsidian-minimal-settings` | `9.0.0` | main.js, manifest.json, styles.css | MIT |
| `obsidian-style-settings` | `community-archive/obsidian-style-settings` | `1.0.9` | main.js, manifest.json, styles.css | GPL-3.0 |
| `notebook-navigator` | `johansan/notebook-navigator` | `3.3.4` | main.js, manifest.json, styles.css | GPL-3.0 |
| theme `Minimal` | `kepano/obsidian-minimal` | `9.0.2` | theme.css, manifest.json | MIT |

Notes bound to these pins:
- **Dataview is pinned to `0.5.68`, NOT the nominally-latest `0.5.70`:** 0.5.70 is labeled a beta by the maintainer and its manifest.json asset internally reports version 0.5.68 (broken). 2.09M downloads sit on 0.5.68. Do not "fix" this to latest.
- **Style Settings repo was renamed** (`obsidian-community/…` → `community-archive/…`; GitHub 301-redirects the old name). Pin the canonical new name.
- **No `v` prefix on any of these tags.** Download URL pattern: `https://github.com/<repo>/releases/download/<tag>/<asset>`.
- **Theme install layout:** `.obsidian/themes/Minimal/{theme.css, manifest.json}` — folder name must equal the manifest's `name` (`Minimal`), matching the template's `appearance.json` (`"cssTheme": "Minimal"`). Both files are release assets on `9.0.2`.

## Global Constraints

- **CI stays offline:** no test may touch the network. All provisioner tests use an injected fake fetch. The pin manifest's shape test reads the real shipped JSON (no downloads).
- **Clean-room rule:** `template/README.md` is the only shipped file touched; no denylisted terms.
- **No `plugin/` files touched** → no plugin version bump. No `structure-version` bump (no vault structure change).
- **Script conventions:** stdlib only, `pathlib`, docstring stating exit behavior, `main(argv=None) -> int` + `if __name__ == "__main__":` (mirror `make_test_vault.py`).
- **Commit trailer**, every commit, exact: `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Branch:** `feat/plugin-provisioning`.
- **Local verification trio:** `python scripts/lint_plugin.py` · `python scripts/validate_template.py` · `python -m pytest scripts/tests -q` (use `python3`).

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/provision_plugins.py` | Provisioner: load pins, verify/download/repair into a vault; CLI |
| `scripts/plugin-pins.json` | Pin manifest: the five entries above + real sha256 checksums |
| `scripts/tests/test_provision_plugins.py` | Offline tests: manifest shape + provision logic with fake fetch |
| `scripts/make_test_vault.py` | `--with-plugins` flag |
| `scripts/tests/test_make_test_vault.py` | +2 tests for the flag (provisioner monkeypatched) |
| `docs/local-setup.md` | Runbook step 2 rewritten around the script |
| `template/README.md` | Provisioning step 1 rewritten around the script |

---

### Task 1: `provision_plugins.py` + offline tests (TDD)

**Files:**
- Create: `scripts/provision_plugins.py`
- Test: `scripts/tests/test_provision_plugins.py`

**Interfaces:**
- Consumes: nothing existing.
- Produces: `load_pins(path: Path) -> dict` · `provision(vault: Path, pins: dict, fetch=fetch_url) -> tuple[list[str], list[str]]` returning `(actions, problems)` · `fetch_url(url: str) -> bytes` · `PINS_PATH` · `main(argv=None) -> int`. Task 2 runs `main` for real; Task 3 imports `provision` and `load_pins`.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_provision_plugins.py`:

```python
"""Offline tests for the plugin provisioner. Network is never touched:
provision() takes an injectable fetch, and the fake below records calls.
The shipped pin manifest's shape (incl. real checksums present for every
asset) is tested against the actual scripts/plugin-pins.json."""
import hashlib
import json
from pathlib import Path

import pytest

from provision_plugins import PINS_PATH, load_pins, provision

REPO_ROOT = Path(__file__).resolve().parents[2]

FAKE_ASSET = b"fake plugin code\n"
FAKE_SHA = hashlib.sha256(FAKE_ASSET).hexdigest()


def make_pins() -> dict:
    return {
        "plugins": [
            {
                "id": "fake-plugin",
                "repo": "example/fake-plugin",
                "tag": "1.0.0",
                "assets": ["main.js", "manifest.json"],
                "license": "MIT",
                "sha256": {"main.js": FAKE_SHA, "manifest.json": FAKE_SHA},
            }
        ],
        "theme": {
            "name": "Minimal",
            "repo": "example/fake-theme",
            "tag": "2.0.0",
            "assets": ["theme.css", "manifest.json"],
            "license": "MIT",
            "sha256": {"theme.css": FAKE_SHA, "manifest.json": FAKE_SHA},
        },
    }


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    return vault


class FakeFetch:
    def __init__(self, payload: bytes = FAKE_ASSET):
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.payload


def test_fresh_install_places_all_assets(tmp_path):
    vault, fetch = make_vault(tmp_path), FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=fetch)
    assert problems == []
    assert (vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js").read_bytes() == FAKE_ASSET
    assert (vault / ".obsidian" / "themes" / "Minimal" / "theme.css").read_bytes() == FAKE_ASSET
    assert len(fetch.urls) == 4  # 2 plugin assets + 2 theme assets


def test_download_urls_follow_release_pattern(tmp_path):
    vault, fetch = make_vault(tmp_path), FakeFetch()
    provision(vault, make_pins(), fetch=fetch)
    assert "https://github.com/example/fake-plugin/releases/download/1.0.0/main.js" in fetch.urls


def test_rerun_is_idempotent_no_downloads(tmp_path):
    vault = make_vault(tmp_path)
    provision(vault, make_pins(), fetch=FakeFetch())
    second = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=second)
    assert problems == []
    assert second.urls == []  # everything verified in place, nothing re-fetched


def test_tampered_file_gets_repaired(tmp_path):
    vault = make_vault(tmp_path)
    provision(vault, make_pins(), fetch=FakeFetch())
    target = vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js"
    target.write_bytes(b"tampered")
    repair = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=repair)
    assert problems == []
    assert target.read_bytes() == FAKE_ASSET
    assert len(repair.urls) == 1  # only the tampered asset re-fetched


def test_checksum_mismatch_reports_problem_and_installs_nothing(tmp_path):
    vault = make_vault(tmp_path)
    bad_fetch = FakeFetch(payload=b"not what was pinned")
    actions, problems = provision(vault, make_pins(), fetch=bad_fetch)
    assert any("sha256" in p for p in problems)
    assert not (vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js").exists()


def test_refuses_non_vault_target(tmp_path):
    not_a_vault = tmp_path / "plain-dir"
    not_a_vault.mkdir()
    actions, problems = provision(not_a_vault, make_pins(), fetch=FakeFetch())
    assert any(".obsidian" in p for p in problems)


def test_shipped_pins_manifest_is_wellformed():
    pins = load_pins(PINS_PATH)
    ids = {p["id"] for p in pins["plugins"]}
    assert ids == {"dataview", "obsidian-minimal-settings", "obsidian-style-settings", "notebook-navigator"}
    assert pins["theme"]["name"] == "Minimal"
    for entry in [*pins["plugins"], pins["theme"]]:
        assert entry["repo"] and entry["tag"] and entry["license"]
        assert entry["assets"], f"{entry}: no assets"
        for asset in entry["assets"]:
            digest = entry["sha256"].get(asset, "")
            assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), (
                f"{entry.get('id') or entry.get('name')}/{asset}: missing or malformed sha256"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_provision_plugins.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'provision_plugins'`.

- [ ] **Step 3: Implement the provisioner**

Create `scripts/provision_plugins.py`:

```python
#!/usr/bin/env python3
"""Provision Obsidian community plugins + theme into a vault from pinned,
checksummed official GitHub releases (scripts/plugin-pins.json).

Idempotent: an asset already in place with a matching sha256 is skipped;
a missing or tampered asset is (re)downloaded and verified before install.
A checksum mismatch on downloaded bytes is a problem, never an install.

Exit 0 on success (summary on stdout); exit 1 with problems on stderr.
To bump a pin: edit the tag in plugin-pins.json, blank the sha256 values,
run this script against a scratch vault to see the mismatch digests it
reports, then record those digests — or recompute them directly from the
release assets.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

PINS_PATH = Path(__file__).resolve().parent / "plugin-pins.json"
DOWNLOAD_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"


def load_pins(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def _sync_entry(target_dir: Path, entry: dict, fetch, actions: list, problems: list) -> None:
    label = entry.get("id") or entry.get("name")
    for asset in entry["assets"]:
        expected = entry["sha256"][asset]
        dest = target_dir / asset
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == expected:
            actions.append(f"ok       {label}/{asset}")
            continue
        url = DOWNLOAD_URL.format(repo=entry["repo"], tag=entry["tag"], asset=asset)
        try:
            payload = fetch(url)
        except Exception as e:  # noqa: BLE001 — any fetch failure is a provisioning problem
            problems.append(f"{label}/{asset}: download failed: {e}")
            continue
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            problems.append(
                f"{label}/{asset}: sha256 mismatch (expected {expected}, got {actual}) — not installed"
            )
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        actions.append(f"installed {label}/{asset}")


def provision(vault: Path, pins: dict, fetch=fetch_url) -> tuple[list[str], list[str]]:
    actions: list[str] = []
    problems: list[str] = []
    obsidian = vault / ".obsidian"
    if not obsidian.is_dir():
        problems.append(f"{vault}: no .obsidian/ directory — not an Obsidian vault")
        return actions, problems
    for plugin in pins["plugins"]:
        _sync_entry(obsidian / "plugins" / plugin["id"], plugin, fetch, actions, problems)
    theme = pins["theme"]
    _sync_entry(obsidian / "themes" / theme["name"], theme, fetch, actions, problems)
    return actions, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the pinned Obsidian plugins + theme into a vault."
    )
    parser.add_argument("vault", type=Path, help="Path to the vault (contains .obsidian/)")
    args = parser.parse_args(argv)
    actions, problems = provision(args.vault.resolve(), load_pins(PINS_PATH))
    for line in actions:
        print(line)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    installed = sum(1 for a in actions if a.startswith("installed"))
    verified = sum(1 for a in actions if a.startswith("ok"))
    print(f"{installed} installed, {verified} already ok, {len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests again**

Run: `python3 -m pytest scripts/tests/test_provision_plugins.py -v`
Expected: every test passes EXCEPT `test_shipped_pins_manifest_is_wellformed`, which fails with `FileNotFoundError` for `scripts/plugin-pins.json` — that file is Task 2's deliverable. This is the intended red/green boundary between the tasks.

- [ ] **Step 5: Commit**

```bash
git add scripts/provision_plugins.py scripts/tests/test_provision_plugins.py
git commit -m "$(cat <<'EOF'
feat: add provision_plugins.py — pinned, checksummed Obsidian plugin installer

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Real pin manifest with computed checksums (network task)

**Files:**
- Create: `scripts/plugin-pins.json`

**Interfaces:**
- Consumes: the verified release table at the top of this plan (exact repos/tags/assets/licenses — do not substitute "latest").
- Produces: the shipped manifest `test_shipped_pins_manifest_is_wellformed` validates and Task 4's docs reference.

- [ ] **Step 1: Download the pinned assets and compute checksums**

Run this snippet — it downloads every pinned asset from the official releases and prints the manifest JSON with real sha256 values filled in:

```bash
python3 - <<'EOF'
import hashlib, json, urllib.request

ENTRIES = {
    "plugins": [
        {"id": "dataview", "repo": "blacksmithgu/obsidian-dataview", "tag": "0.5.68",
         "assets": ["main.js", "manifest.json", "styles.css"], "license": "MIT"},
        {"id": "obsidian-minimal-settings", "repo": "kepano/obsidian-minimal-settings", "tag": "9.0.0",
         "assets": ["main.js", "manifest.json", "styles.css"], "license": "MIT"},
        {"id": "obsidian-style-settings", "repo": "community-archive/obsidian-style-settings", "tag": "1.0.9",
         "assets": ["main.js", "manifest.json", "styles.css"], "license": "GPL-3.0"},
        {"id": "notebook-navigator", "repo": "johansan/notebook-navigator", "tag": "3.3.4",
         "assets": ["main.js", "manifest.json", "styles.css"], "license": "GPL-3.0"},
    ],
    "theme": {"name": "Minimal", "repo": "kepano/obsidian-minimal", "tag": "9.0.2",
              "assets": ["theme.css", "manifest.json"], "license": "MIT"},
}

for entry in [*ENTRIES["plugins"], ENTRIES["theme"]]:
    entry["sha256"] = {}
    for asset in entry["assets"]:
        url = f"https://github.com/{entry['repo']}/releases/download/{entry['tag']}/{asset}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        entry["sha256"][asset] = hashlib.sha256(data).hexdigest()
        print(f"# {entry.get('id') or entry['name']}/{asset}: {len(data)} bytes", flush=True)

print(json.dumps(ENTRIES, indent=2))
EOF
```

Write the printed JSON object (from `{` to the final `}`) to `scripts/plugin-pins.json`, then add one top-level key as the FIRST entry of the object:

```json
  "_readme": "Pinned Obsidian plugin/theme releases. To bump: edit the tag, rerun the checksum snippet in docs/superpowers/plans/2026-08-23-plugin-provisioning.md Task 2 (or blank the sha256s and read the mismatch digests provision_plugins.py reports), and update sha256. dataview is deliberately pinned to 0.5.68 — 0.5.70 is a mislabeled beta with a broken manifest asset. obsidian-style-settings' canonical repo is community-archive/... (renamed from obsidian-community/..., which still redirects).",
```

- [ ] **Step 2: Run the full provisioner test file**

Run: `python3 -m pytest scripts/tests/test_provision_plugins.py -v`
Expected: all tests PASS, including `test_shipped_pins_manifest_is_wellformed`.

- [ ] **Step 3: Acceptance run against a real scratch vault (network)**

```bash
python3 scripts/make_test_vault.py /tmp/pins-accept-vault
python3 scripts/provision_plugins.py /tmp/pins-accept-vault
python3 scripts/provision_plugins.py /tmp/pins-accept-vault
ls /tmp/pins-accept-vault/.obsidian/plugins /tmp/pins-accept-vault/.obsidian/themes/Minimal
rm -rf /tmp/pins-accept-vault
```

Expected: first run prints 14 `installed …` lines (4 plugins × 3 assets + theme × 2) and `14 installed, 0 already ok, 0 problem(s).`; second run prints 14 `ok …` lines and `0 installed, 14 already ok, 0 problem(s).`; the `ls` shows the four plugin dirs and `manifest.json theme.css`. Record the outputs in your report.

- [ ] **Step 4: Commit**

```bash
git add scripts/plugin-pins.json
git commit -m "$(cat <<'EOF'
feat: pin manifest for Obsidian plugins + Minimal theme (checksummed releases)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `make_test_vault.py --with-plugins`

**Files:**
- Modify: `scripts/make_test_vault.py`
- Modify: `scripts/tests/test_make_test_vault.py`

**Interfaces:**
- Consumes: `provision(vault, pins, fetch=...)`, `load_pins`, `PINS_PATH` from Task 1.
- Produces: the `--with-plugins` CLI flag Task 4's docs reference; `make_test_vault.provision_into(vault) -> tuple[list[str], list[str]]` (the monkeypatch seam).

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_make_test_vault.py` (add `import pytest` to its imports if not already present):

```python
def test_with_plugins_flag_invokes_provisioner(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "make_test_vault.provision_into",
        lambda vault: calls.append(vault) or (["installed fake/main.js"], []),
    )
    target = tmp_path / "vault"
    exit_code = main([str(target), "--with-plugins"])
    assert exit_code == 0
    assert calls == [target.resolve()]
    assert "installed" in capsys.readouterr().out


def test_without_flag_provisioner_not_called(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "make_test_vault.provision_into",
        lambda vault: pytest.fail("provisioner must not run without --with-plugins"),
    )
    target = tmp_path / "vault"
    assert main([str(target)]) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_make_test_vault.py -k plugins -v`
Expected: FAIL — `make_test_vault` has no `provision_into` attribute (monkeypatch raises AttributeError).

- [ ] **Step 3: Implement the flag**

In `scripts/make_test_vault.py`:

1. Add below the existing imports:

```python
def provision_into(vault: Path) -> tuple[list[str], list[str]]:
    """Install the pinned Obsidian plugins + theme into the new vault.
    Kept as a thin module-level seam so tests monkeypatch it (no network)."""
    from provision_plugins import PINS_PATH, load_pins, provision

    return provision(vault, load_pins(PINS_PATH))
```

2. In `parse_args`, add:

```python
    parser.add_argument(
        "--with-plugins",
        action="store_true",
        help="Also download the pinned Obsidian community plugins + theme (network)",
    )
```

3. In `main`, after the success `print(f"Test vault created at ...")` line and before `return 0`, add:

```python
    if args.with_plugins:
        actions, problems = provision_into(args.target.resolve())
        for line in actions:
            print(line)
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if problems:
            return 1
```

4. Append to the module docstring's first paragraph: `With --with-plugins, also downloads the pinned Obsidian community plugins and theme into the new vault (network required).`

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest scripts/tests/test_make_test_vault.py -v` → all pass.
Run: `python3 -m pytest scripts/tests -q` → full suite green, no network touched.

- [ ] **Step 5: Commit**

```bash
git add scripts/make_test_vault.py scripts/tests/test_make_test_vault.py
git commit -m "$(cat <<'EOF'
feat: add --with-plugins to make_test_vault.py

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Docs — runbook + template README

**Files:**
- Modify: `docs/local-setup.md` (runbook steps 1–2)
- Modify: `template/README.md` (provisioning step 1)

**Interfaces:**
- Consumes: the CLI surfaces from Tasks 1–3.
- Produces: nothing downstream — closes issue #27's docs deliverable.

- [ ] **Step 1: Extend runbook step 1 and rewrite step 2 in `docs/local-setup.md`**

In the "### 1. Create the test vault" section, immediately after the paragraph ending "Delete the directory first when you want a clean rebuild.", insert a new paragraph + fenced bash block:

Paragraph text: `Add --with-plugins to also download the pinned Obsidian community plugins and the Minimal theme into the vault (network required — pins and checksums live in scripts/plugin-pins.json):` — with `--with-plugins` and `scripts/plugin-pins.json` in backticks.

Bash block content: `python scripts/make_test_vault.py /tmp/sb-test-vault --with-plugins`

Then replace the body of "### 2. Open it in Obsidian" (keep the heading) with:

````markdown
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
````

- [ ] **Step 2: Rewrite provisioning step 1 in `template/README.md`**

Replace list item 1 under "## Provisioning steps that cannot ship as files" with:

````markdown
1. **Provision community plugins and the Minimal theme.** Preferred: run
   `python scripts/provision_plugins.py <vault>` from the accelerator repo —
   it installs the pinned, checksum-verified releases listed in
   `scripts/plugin-pins.json` into `.obsidian/plugins/` and
   `.obsidian/themes/Minimal/`, so the vault's first open needs only the
   one "trust and enable" click. Fallback (no repo access on the client
   machine): install by hand the plugins listed in
   `.obsidian/community-plugins.json` (Dataview, Minimal Theme Settings,
   Style Settings, Notebook Navigator) and the **Minimal** theme.
````

Items 2 and 3 (Sync exclusions, Sync connection) stay unchanged.

- [ ] **Step 3: Full verification trio + docs read-back**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all pass. Read both edited docs back end-to-end and confirm fences/headings are well-formed and no stale manual-install instruction survives outside the deliberate fallbacks.

- [ ] **Step 4: Commit**

```bash
git add docs/local-setup.md template/README.md
git commit -m "$(cat <<'EOF'
docs: provisioning script replaces manual plugin installs in runbook + template README

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** issue #27 deliverable 1 (script) → Task 1; deliverable 2 (pin manifest + documented update procedure) → Task 2 (`_readme` key + script docstring); deliverable 3 (`--with-plugins`, default off, offline CI) → Task 3; deliverable 4 (offline tests incl. real-manifest shape) → Tasks 1–3; deliverable 5 (docs) → Task 4 — with a ruling: the pre-flight playbook doesn't exist yet (`playbooks/` holds only a stub README), so the consultant-facing pointer lands in `template/README.md`'s provisioning section, where the manual instruction lives today; a future playbook issue inherits it from there.
- **Acceptance criteria from the issue:** fresh clone + `--with-plugins` → one trust click (Task 2 Step 3 proves the provisioning half; the Obsidian half is documented in the runbook and hand-verified by Michael); tamper-and-repair → `test_tampered_file_gets_repaired` offline + Task 2 Step 3's idempotent re-run live.
- **Deliberate cross-task red:** Task 1 ends with `test_shipped_pins_manifest_is_wellformed` failing (`plugin-pins.json` doesn't exist until Task 2) — stated in Task 1 Step 4 so a reviewer doesn't flag it.
- **GPL-3.0 items** (style-settings, notebook-navigator): no code vendored or redistributed — the user's machine downloads official release artifacts directly; licenses recorded per-entry in the manifest.
- **Placeholder scan:** the only non-literal values are the sha256 digests — the output of Task 2 Step 1's exact runnable snippet, a computation step, not a TBD.
