"""Offline tests for the plugin provisioner. Network is never touched:
provision() takes an injectable fetch, and the fake below records calls.

Two sources feed an install (#164): the plugin's own vendored copy first
(plugin/vendor/obsidian/<id>/), the GitHub download only when no vendored
file exists. The tests below cover each source in isolation and the shipped
tree for real: every pinned asset must be vendored and match its pin, and
a fresh vault must provision fully with a fetch that refuses every call.

The shipped pin manifest's shape (incl. real checksums present for every
asset) is tested against the actual plugin/lib/plugin-pins.json."""
import hashlib
import json
from pathlib import Path

import pytest

from provision_plugins import PINS_PATH, VENDOR_DIR, load_pins, main, provision

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


def no_vendor(tmp_path: Path) -> Path:
    """An empty vendor tree: the download path, exactly as it behaved before
    #164. The default VENDOR_DIR is the real shipped tree, whose Minimal/
    directory would otherwise shadow the fake theme in make_pins()."""
    return tmp_path / "vendor-empty"


def make_vendor(tmp_path: Path, pins: dict, payload: bytes = FAKE_ASSET,
                skip: set = frozenset()) -> Path:
    """A vendor tree mirroring `pins`: <label>/<asset> for every asset not in
    `skip`, all carrying `payload`."""
    vendor = tmp_path / "vendor"
    for label, entry in [(p["id"], p) for p in pins["plugins"]] + [(pins["theme"]["name"], pins["theme"])]:
        for asset in entry["assets"]:
            if f"{label}/{asset}" in skip:
                continue
            dest = vendor / label / asset
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
    return vendor


class FakeFetch:
    def __init__(self, payload: bytes = FAKE_ASSET):
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.payload


def refuse_fetch(url: str) -> bytes:
    """The network the client machine does not have (#164): any call is a
    test failure, not a problem line — the point is that nothing calls it."""
    raise AssertionError(f"provision() tried to download {url}")


# --- download path (vendor tree empty) — unchanged behaviour ---


def test_fresh_install_places_all_assets(tmp_path):
    vault, fetch = make_vault(tmp_path), FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=fetch, vendor_dir=no_vendor(tmp_path))
    assert problems == []
    assert (vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js").read_bytes() == FAKE_ASSET
    assert (vault / ".obsidian" / "themes" / "Minimal" / "theme.css").read_bytes() == FAKE_ASSET
    assert len(fetch.urls) == 4  # 2 plugin assets + 2 theme assets


def test_download_urls_follow_release_pattern(tmp_path):
    vault, fetch = make_vault(tmp_path), FakeFetch()
    provision(vault, make_pins(), fetch=fetch, vendor_dir=no_vendor(tmp_path))
    assert "https://github.com/example/fake-plugin/releases/download/1.0.0/main.js" in fetch.urls


def test_rerun_is_idempotent_no_downloads(tmp_path):
    vault = make_vault(tmp_path)
    provision(vault, make_pins(), fetch=FakeFetch(), vendor_dir=no_vendor(tmp_path))
    second = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=second, vendor_dir=no_vendor(tmp_path))
    assert problems == []
    assert second.urls == []  # everything verified in place, nothing re-fetched


def test_tampered_file_gets_repaired(tmp_path):
    vault = make_vault(tmp_path)
    provision(vault, make_pins(), fetch=FakeFetch(), vendor_dir=no_vendor(tmp_path))
    target = vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js"
    target.write_bytes(b"tampered")
    repair = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=repair, vendor_dir=no_vendor(tmp_path))
    assert problems == []
    assert target.read_bytes() == FAKE_ASSET
    assert len(repair.urls) == 1  # only the tampered asset re-fetched


def test_checksum_mismatch_reports_problem_and_installs_nothing(tmp_path):
    vault = make_vault(tmp_path)
    bad_fetch = FakeFetch(payload=b"not what was pinned")
    actions, problems = provision(vault, make_pins(), fetch=bad_fetch, vendor_dir=no_vendor(tmp_path))
    assert any("sha256" in p and "downloaded" in p for p in problems)
    assert not (vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js").exists()


def test_download_failure_names_the_missing_vendored_copy(tmp_path):
    """The error a consultant reads on a client machine has to say both
    halves: the plugin did not carry the file, AND the network did not
    either — otherwise the first is invisible and they debug the wrong one."""
    vault = make_vault(tmp_path)

    def down(url):
        raise OSError("Tunnel connection failed: 403 Forbidden")

    actions, problems = provision(vault, make_pins(), fetch=down, vendor_dir=no_vendor(tmp_path))
    assert len(problems) == 4
    assert all("not vendored" in p and "download failed" in p for p in problems)


def test_refuses_non_vault_target(tmp_path):
    not_a_vault = tmp_path / "plain-dir"
    not_a_vault.mkdir()
    actions, problems = provision(not_a_vault, make_pins(), fetch=FakeFetch(), vendor_dir=no_vendor(tmp_path))
    assert any(".obsidian" in p for p in problems)


# --- vendored path (#164) ---


def test_vendored_assets_install_with_no_fetch_at_all(tmp_path):
    vault = make_vault(tmp_path)
    vendor = make_vendor(tmp_path, make_pins())
    actions, problems = provision(vault, make_pins(), fetch=refuse_fetch, vendor_dir=vendor)
    assert problems == []
    installed = [a for a in actions if a.startswith("installed")]
    assert len(installed) == 4
    assert all(a.endswith("(vendored)") for a in installed)
    assert (vault / ".obsidian" / "plugins" / "fake-plugin" / "main.js").read_bytes() == FAKE_ASSET
    assert (vault / ".obsidian" / "themes" / "Minimal" / "manifest.json").read_bytes() == FAKE_ASSET


def test_vendored_mismatch_is_a_problem_and_never_falls_through_to_download(tmp_path):
    """A vendored file that does not match its pin means the plugin shipped
    the wrong bytes. That is reported, not papered over by a download that
    would happen to succeed on a machine with network — the next machine
    without it would hit the same bad file with no warning ever raised."""
    vault = make_vault(tmp_path)
    vendor = make_vendor(tmp_path, make_pins(), payload=b"stale vendored bytes")
    fetch = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=fetch, vendor_dir=vendor)
    assert len(problems) == 4
    assert all("vendored copy sha256 mismatch" in p and "not installed" in p for p in problems)
    assert fetch.urls == []
    assert not (vault / ".obsidian" / "plugins" / "fake-plugin").exists()
    assert not (vault / ".obsidian" / "themes" / "Minimal").exists()


def test_vendored_absent_falls_back_to_download_for_that_asset_only(tmp_path):
    vault = make_vault(tmp_path)
    vendor = make_vendor(tmp_path, make_pins(), skip={"fake-plugin/manifest.json"})
    fetch = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=fetch, vendor_dir=vendor)
    assert problems == []
    assert fetch.urls == ["https://github.com/example/fake-plugin/releases/download/1.0.0/manifest.json"]
    assert "installed fake-plugin/manifest.json (downloaded)" in actions
    assert "installed fake-plugin/main.js (vendored)" in actions


def test_missing_vendor_dir_is_the_download_path(tmp_path):
    """A vendor_dir that does not exist at all (an older plugin cache, a
    hand-trimmed checkout) must degrade to exactly the pre-#164 behaviour."""
    vault = make_vault(tmp_path)
    fetch = FakeFetch()
    actions, problems = provision(vault, make_pins(), fetch=fetch,
                                  vendor_dir=tmp_path / "does-not-exist")
    assert problems == []
    assert len(fetch.urls) == 4


def test_tampered_vault_file_is_repaired_from_the_vendored_copy(tmp_path):
    vault = make_vault(tmp_path)
    vendor = make_vendor(tmp_path, make_pins())
    provision(vault, make_pins(), fetch=refuse_fetch, vendor_dir=vendor)
    target = vault / ".obsidian" / "themes" / "Minimal" / "theme.css"
    target.write_bytes(b"tampered")
    actions, problems = provision(vault, make_pins(), fetch=refuse_fetch, vendor_dir=vendor)
    assert problems == []
    assert target.read_bytes() == FAKE_ASSET
    assert actions.count("installed Minimal/theme.css (vendored)") == 1
    assert sum(1 for a in actions if a.startswith("ok")) == 3


# --- the shipped tree, for real ---


def _shipped_entries(pins: dict):
    for plugin in pins["plugins"]:
        yield plugin["id"], plugin
    yield pins["theme"]["name"], pins["theme"]


def test_shipped_pins_manifest_is_wellformed():
    pins = load_pins(PINS_PATH)
    ids = {p["id"] for p in pins["plugins"]}
    assert ids == {"dataview", "obsidian-minimal-settings", "obsidian-style-settings", "notebook-navigator"}
    assert pins["theme"]["name"] == "Minimal"
    for entry in [*pins["plugins"], pins["theme"]]:
        assert entry["repo"] and entry["tag"] and entry["license"]
        assert entry["license_file"], f"{entry}: no license_file — refresh_vendor.py needs it"
        assert entry["assets"], f"{entry}: no assets"
        for asset in entry["assets"]:
            digest = entry["sha256"].get(asset, "")
            assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), (
                f"{entry.get('id') or entry.get('name')}/{asset}: missing or malformed sha256"
            )


def test_vendor_dir_is_inside_the_plugin():
    """The whole point: the vendored bytes travel with the plugin cache,
    which is the one thing guaranteed to be on the client machine."""
    assert VENDOR_DIR == REPO_ROOT / "plugin" / "vendor" / "obsidian"


def test_shipped_vendor_tree_carries_every_pinned_asset_matching_its_pin():
    """The guard that makes a stale vendor tree a CI failure rather than a
    setup-day surprise: a pin bumped without running refresh_vendor.py, or a
    vendored file edited by hand, fails here."""
    pins = load_pins(PINS_PATH)
    for label, entry in _shipped_entries(pins):
        for asset in entry["assets"]:
            vendored = VENDOR_DIR / label / asset
            assert vendored.is_file(), f"{label}/{asset}: not vendored — run scripts/refresh_vendor.py"
            actual = hashlib.sha256(vendored.read_bytes()).hexdigest()
            assert actual == entry["sha256"][asset], (
                f"{label}/{asset}: vendored bytes do not match plugin-pins.json"
            )


def test_shipped_vendor_tree_holds_nothing_the_pins_do_not_name():
    """Exactly the pinned assets plus each project's LICENSE, and the index —
    no leftovers from a previous pin, no stray downloads."""
    pins = load_pins(PINS_PATH)
    expected_dirs = {label for label, _ in _shipped_entries(pins)}
    assert {p.name for p in VENDOR_DIR.iterdir() if p.is_dir()} == expected_dirs
    assert {p.name for p in VENDOR_DIR.iterdir() if p.is_file()} == {"LICENSES.md"}
    for label, entry in _shipped_entries(pins):
        files = {p.name for p in (VENDOR_DIR / label).iterdir()}
        assert files == set(entry["assets"]) | {"LICENSE"}, f"{label}: {files}"


def test_shipped_licences_are_present_and_indexed():
    """Two of the five are GPL-3.0: redistribution needs the licence text
    alongside. The index must name every vendored project, its tag, and the
    licence the pins claim for it."""
    pins = load_pins(PINS_PATH)
    index = (VENDOR_DIR / "LICENSES.md").read_text(encoding="utf-8")
    for label, entry in _shipped_entries(pins):
        text = (VENDOR_DIR / label / "LICENSE").read_text(encoding="utf-8")
        if entry["license"] == "GPL-3.0":
            assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3" in text, label
        else:
            assert "MIT License" in text, label
        assert f"`{label}/`" in index, f"{label}: not in LICENSES.md"
        assert entry["repo"] in index and entry["tag"] in index, f"{label}: repo/tag not in LICENSES.md"
        assert entry["license"] in index


def test_shipped_tree_provisions_a_fresh_vault_with_the_network_refused(tmp_path):
    """#164's acceptance, as a test: a fresh vault, the real pins, the real
    vendored tree, and a fetch that fails the test if it is ever called.
    First run installs all 14; the re-run finds all 14 already ok."""
    vault = make_vault(tmp_path)
    pins = load_pins(PINS_PATH)
    actions, problems = provision(vault, pins, fetch=refuse_fetch)
    assert problems == []
    assert sum(1 for a in actions if a.startswith("installed")) == 14
    for label, entry in _shipped_entries(pins):
        folder = "themes" if label == pins["theme"]["name"] else "plugins"
        for asset in entry["assets"]:
            assert (vault / ".obsidian" / folder / label / asset).is_file()
    again, problems = provision(vault, pins, fetch=refuse_fetch)
    assert problems == []
    assert sum(1 for a in again if a.startswith("ok")) == 14


def test_cli_summary_line_on_the_shipped_tree(tmp_path, capsys, monkeypatch):
    """The exact line the skill tells the consultant to report, produced with
    urlopen replaced by a hard failure so any download attempt is loud."""
    import provision_plugins

    def no_network(url, timeout=None):
        raise OSError("network disabled for this test")

    monkeypatch.setattr(provision_plugins.urllib.request, "urlopen", no_network)
    vault = make_vault(tmp_path)
    assert main([str(vault)]) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == "14 installed, 0 already ok, 0 problem(s)."
    assert main([str(vault)]) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == "0 installed, 14 already ok, 0 problem(s)."
