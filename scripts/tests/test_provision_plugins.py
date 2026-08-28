"""Offline tests for the plugin provisioner. Network is never touched:
provision() takes an injectable fetch, and the fake below records calls.
The shipped pin manifest's shape (incl. real checksums present for every
asset) is tested against the actual plugin/lib/plugin-pins.json."""
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
