#!/usr/bin/env python3
"""Provision Obsidian community plugins + theme into a vault from the pinned,
checksummed releases in plugin/lib/plugin-pins.json.

Local-first (#164): every pinned asset ships inside the plugin at
plugin/vendor/obsidian/<id>/ (theme: .../Minimal/), so a client machine needs
no network — Cowork's sandbox egress blocks GitHub release assets, and that
switch belongs to the client's org admin, not to us. The GitHub download is
the fallback for an asset that is absent from the vendored tree only.

Every candidate — vendored or downloaded — is verified against the SAME
sha256 from the pins before it is written into the vault. A vendored file
that does not match its pin is a problem, never an install, and never a
silent fall-through to the download: the plugin shipped the wrong bytes and
someone needs to know.

Idempotent: an asset already in place with a matching sha256 is skipped;
a missing or tampered asset is re-installed from the vendored copy.

Exit 0 on success (summary on stdout); exit 1 with problems on stderr.
To bump a pin: edit the tag in plugin-pins.json and run
scripts/refresh_vendor.py --record (dev-only; see its docstring).
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

PINS_PATH = Path(__file__).resolve().parent / "plugin-pins.json"
# plugin/lib/provision_plugins.py -> plugin/vendor/obsidian/
VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor" / "obsidian"
DOWNLOAD_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"


def load_pins(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def _sync_entry(target_dir: Path, vendored_dir: Path, entry: dict, fetch,
                actions: list, problems: list) -> None:
    label = entry.get("id") or entry.get("name")
    for asset in entry["assets"]:
        expected = entry["sha256"][asset]
        dest = target_dir / asset
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == expected:
            actions.append(f"ok       {label}/{asset}")
            continue
        vendored = vendored_dir / asset
        if vendored.is_file():
            payload = vendored.read_bytes()
            source = "vendored"
        else:
            url = DOWNLOAD_URL.format(repo=entry["repo"], tag=entry["tag"], asset=asset)
            try:
                payload = fetch(url)
            except Exception as e:  # noqa: BLE001 — any fetch failure is a provisioning problem
                problems.append(
                    f"{label}/{asset}: not vendored in the plugin and download failed: {e}"
                )
                continue
            source = "downloaded"
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            problems.append(
                f"{label}/{asset}: {source} copy sha256 mismatch "
                f"(expected {expected}, got {actual}) — not installed"
            )
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        actions.append(f"installed {label}/{asset} ({source})")


def provision(vault: Path, pins: dict, fetch=fetch_url,
              vendor_dir: Path = VENDOR_DIR) -> tuple[list[str], list[str]]:
    actions: list[str] = []
    problems: list[str] = []
    obsidian = vault / ".obsidian"
    if not obsidian.is_dir():
        problems.append(f"{vault}: no .obsidian/ directory — not an Obsidian vault")
        return actions, problems
    for plugin in pins["plugins"]:
        _sync_entry(obsidian / "plugins" / plugin["id"], vendor_dir / plugin["id"],
                    plugin, fetch, actions, problems)
    theme = pins["theme"]
    _sync_entry(obsidian / "themes" / theme["name"], vendor_dir / theme["name"],
                theme, fetch, actions, problems)
    return actions, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the pinned Obsidian plugins + theme into a vault "
                    "from the plugin's own vendored copies (no network needed)."
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
