#!/usr/bin/env python3
"""Provision Obsidian community plugins + theme into a vault from pinned,
checksummed official GitHub releases (plugin/lib/plugin-pins.json).

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
