"""Offline tests for scripts/refresh_vendor.py — the dev-only script that
regenerates plugin/vendor/obsidian/ from plugin/lib/plugin-pins.json (#164).
Network is never touched: refresh() takes an injectable fetch keyed by URL."""
import hashlib
import json
from pathlib import Path

import pytest

import refresh_vendor
from refresh_vendor import LICENSE_DEST, PINS_PATH, dump_pins, load_pins, refresh

REPO_ROOT = Path(__file__).resolve().parents[2]

GOOD = b"release bytes\n"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()
LICENCE = b"MIT License\n\nCopyright (c) 2020 Upstream Author\n"


def make_pins(sha: str = GOOD_SHA) -> dict:
    return {
        "_readme": "test pins",
        "plugins": [
            {
                "id": "fake-plugin",
                "repo": "example/fake-plugin",
                "tag": "1.0.0",
                "assets": ["main.js", "manifest.json"],
                "license": "MIT",
                "license_file": "LICENSE",
                "sha256": {"main.js": sha, "manifest.json": sha},
            }
        ],
        "theme": {
            "name": "Minimal",
            "repo": "example/fake-theme",
            "tag": "2.0.0",
            "assets": ["theme.css", "manifest.json"],
            "license": "MIT",
            "license_file": "LICENSE.txt",
            "sha256": {"theme.css": sha, "manifest.json": sha},
        },
    }


class FakeFetch:
    """Serves GOOD for every release asset and LICENCE for every raw file,
    unless `overrides` maps a URL to other bytes (or to an exception)."""

    def __init__(self, overrides: dict | None = None):
        self.overrides = overrides or {}
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if url in self.overrides:
            value = self.overrides[url]
            if isinstance(value, Exception):
                raise value
            return value
        if "raw.githubusercontent.com" in url:
            return LICENCE
        return GOOD


def test_verify_mode_writes_every_matching_asset_and_the_licence(tmp_path):
    vendor = tmp_path / "vendor"
    fetch = FakeFetch()
    actions, problems = refresh(make_pins(), vendor, fetch=fetch)
    assert problems == []
    assert (vendor / "fake-plugin" / "main.js").read_bytes() == GOOD
    assert (vendor / "fake-plugin" / "manifest.json").read_bytes() == GOOD
    assert (vendor / "Minimal" / "theme.css").read_bytes() == GOOD
    assert (vendor / "fake-plugin" / LICENSE_DEST).read_bytes() == LICENCE
    assert (vendor / "Minimal" / LICENSE_DEST).read_bytes() == LICENCE
    assert sum(1 for a in actions if a.startswith("written")) == 6  # 4 assets + 2 licences


def test_urls_follow_the_release_and_raw_patterns(tmp_path):
    fetch = FakeFetch()
    refresh(make_pins(), tmp_path / "vendor", fetch=fetch)
    assert "https://github.com/example/fake-plugin/releases/download/1.0.0/main.js" in fetch.urls
    assert "https://raw.githubusercontent.com/example/fake-plugin/1.0.0/LICENSE" in fetch.urls
    assert "https://raw.githubusercontent.com/example/fake-theme/2.0.0/LICENSE.txt" in fetch.urls


def test_verify_mode_mismatch_is_a_problem_and_writes_nothing_for_that_asset(tmp_path):
    """The vendored tree only ever holds bytes the pins vouch for: a
    download that does not match is reported and left out, so the shipped
    tree can never quietly disagree with plugin-pins.json."""
    vendor = tmp_path / "vendor"
    bad_url = "https://github.com/example/fake-plugin/releases/download/1.0.0/main.js"
    fetch = FakeFetch({bad_url: b"something else entirely"})
    actions, problems = refresh(make_pins(), vendor, fetch=fetch)
    assert len(problems) == 1
    assert "fake-plugin/main.js" in problems[0] and "sha256 mismatch" in problems[0]
    assert "--record" in problems[0]
    assert not (vendor / "fake-plugin" / "main.js").exists()
    assert (vendor / "fake-plugin" / "manifest.json").read_bytes() == GOOD  # the rest still lands


def test_record_mode_updates_the_pins_in_place_and_writes(tmp_path):
    vendor = tmp_path / "vendor"
    pins = make_pins(sha="0" * 64)  # stale pins, as after a tag bump
    actions, problems = refresh(pins, vendor, fetch=FakeFetch(), record=True)
    assert problems == []
    for entry in [*pins["plugins"], pins["theme"]]:
        for asset in entry["assets"]:
            assert entry["sha256"][asset] == GOOD_SHA
    assert (vendor / "fake-plugin" / "main.js").read_bytes() == GOOD
    recorded = [a for a in actions if a.startswith("recorded")]
    assert len(recorded) == 4
    assert all(f"was {'0' * 64}" in a for a in recorded)


def test_record_mode_says_when_a_digest_did_not_change(tmp_path):
    actions, problems = refresh(make_pins(), tmp_path / "vendor", fetch=FakeFetch(), record=True)
    assert problems == []
    assert all("(unchanged)" in a for a in actions if a.startswith("recorded"))


def test_rerun_reports_unchanged(tmp_path):
    vendor = tmp_path / "vendor"
    refresh(make_pins(), vendor, fetch=FakeFetch())
    actions, problems = refresh(make_pins(), vendor, fetch=FakeFetch())
    assert problems == []
    assert all(a.startswith("unchanged") for a in actions)
    assert len(actions) == 6


def test_download_failure_is_a_problem(tmp_path):
    url = "https://github.com/example/fake-theme/releases/download/2.0.0/theme.css"
    actions, problems = refresh(make_pins(), tmp_path / "vendor",
                                fetch=FakeFetch({url: OSError("403 Forbidden")}))
    assert problems == ["Minimal/theme.css: download failed: 403 Forbidden"]


def test_stale_file_in_an_entry_dir_is_removed(tmp_path):
    """A pin bump that drops an asset must not leave the old file behind —
    the shipped tree would carry bytes no pin vouches for."""
    vendor = tmp_path / "vendor"
    stale = vendor / "fake-plugin" / "old-asset.js"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"from a previous pin")
    actions, problems = refresh(make_pins(), vendor, fetch=FakeFetch())
    assert problems == []
    assert not stale.exists()
    assert "removed   fake-plugin/old-asset.js (not in pins)" in actions


def test_unpinned_directory_at_the_vendor_root_is_reported_not_deleted(tmp_path):
    vendor = tmp_path / "vendor"
    (vendor / "retired-plugin").mkdir(parents=True)
    (vendor / "retired-plugin" / "main.js").write_bytes(b"x")
    (vendor / "LICENSES.md").write_text("index\n", encoding="utf-8")
    (vendor / "notes.txt").write_text("stray\n", encoding="utf-8")
    actions, problems = refresh(make_pins(), vendor, fetch=FakeFetch())
    assert any("retired-plugin" in p and "no pin" in p for p in problems)
    assert any("notes.txt" in p for p in problems)
    assert not any("LICENSES.md" in p for p in problems)
    assert (vendor / "retired-plugin" / "main.js").exists()  # never deletes a directory


def test_missing_license_file_in_a_pin_is_a_problem(tmp_path):
    pins = make_pins()
    del pins["theme"]["license_file"]
    actions, problems = refresh(pins, tmp_path / "vendor", fetch=FakeFetch())
    assert problems == ["Minimal: pin has no license_file — every vendored copy ships its licence text"]
    assert not (tmp_path / "vendor" / "Minimal" / LICENSE_DEST).exists()


def test_dump_pins_round_trips_the_shipped_file_byte_for_byte():
    """--record rewrites plugin-pins.json; the formatting must be the one the
    repo already uses, so a pin bump's diff is the tag and the digests and
    nothing else."""
    text = PINS_PATH.read_text(encoding="utf-8")
    assert dump_pins(load_pins(PINS_PATH)) == text


def test_shipped_vendor_tree_is_what_refresh_would_produce_from_the_pins():
    """Verify mode against the real tree with a fetch that serves the vendored
    bytes back: every action must be `unchanged` — proving the tree, the
    pins and the script agree (the sha256 half of that is also asserted in
    test_provision_plugins.py; this adds the LICENSE files and the
    no-leftovers rule from the script's own point of view)."""
    pins = load_pins(PINS_PATH)
    vendor = refresh_vendor.VENDOR_DIR

    def serve_from_tree(url: str) -> bytes:
        for label, entry in refresh_vendor.entries(pins):
            for asset in entry["assets"]:
                if url == refresh_vendor.RELEASE_URL.format(repo=entry["repo"], tag=entry["tag"], asset=asset):
                    return (vendor / label / asset).read_bytes()
            if url == refresh_vendor.RAW_URL.format(repo=entry["repo"], tag=entry["tag"], path=entry["license_file"]):
                return (vendor / label / LICENSE_DEST).read_bytes()
        raise AssertionError(f"unexpected URL {url}")

    actions, problems = refresh(pins, vendor, fetch=serve_from_tree)
    assert problems == []
    assert actions and all(a.startswith("unchanged") for a in actions)


def test_main_record_writes_the_pins_file(tmp_path, monkeypatch):
    pins_path = tmp_path / "pins.json"
    pins_path.write_text(dump_pins(make_pins(sha="0" * 64)), encoding="utf-8")
    monkeypatch.setattr(refresh_vendor, "fetch_url", FakeFetch())
    rc = refresh_vendor.main(["--pins", str(pins_path), "--vendor", str(tmp_path / "vendor"), "--record"])
    assert rc == 0
    rewritten = json.loads(pins_path.read_text(encoding="utf-8"))
    assert rewritten["plugins"][0]["sha256"]["main.js"] == GOOD_SHA
    assert rewritten["_readme"] == "test pins"


def test_main_verify_does_not_touch_the_pins_file(tmp_path, monkeypatch):
    pins_path = tmp_path / "pins.json"
    original = dump_pins(make_pins())
    pins_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(refresh_vendor, "fetch_url", FakeFetch())
    rc = refresh_vendor.main(["--pins", str(pins_path), "--vendor", str(tmp_path / "vendor")])
    assert rc == 0
    assert pins_path.read_text(encoding="utf-8") == original


def test_main_exits_1_on_a_problem(tmp_path, monkeypatch, capsys):
    pins_path = tmp_path / "pins.json"
    pins_path.write_text(dump_pins(make_pins(sha="0" * 64)), encoding="utf-8")
    monkeypatch.setattr(refresh_vendor, "fetch_url", FakeFetch())
    rc = refresh_vendor.main(["--pins", str(pins_path), "--vendor", str(tmp_path / "vendor")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "sha256 mismatch" in err
