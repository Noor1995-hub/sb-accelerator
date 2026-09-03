#!/usr/bin/env python3
"""Refresh plugin/vendor/obsidian/ from plugin/lib/plugin-pins.json.

Dev-only (scripts/, never ships). The provisioner
(plugin/lib/provision_plugins.py) installs the Obsidian plugins + theme from
the plugin's own vendored copies first, so a client machine never needs to
reach GitHub (#164: Cowork's sandbox egress blocks release assets, and that
is a client-org admin setting, not ours). This script is the one place the
vendored bytes come from — never hand-edit that tree.

  refresh_vendor.py            download every pinned asset, verify its sha256
                               against the pin, write it under plugin/vendor/
  refresh_vendor.py --record   same, but RECORD the downloaded digest into
                               plugin-pins.json instead of verifying it.
                               A pin bump is: edit the tag, run with --record,
                               read the diff, commit.

Each entry's `license_file` (path in the upstream repo at the pinned tag) is
fetched too and written next to the assets as LICENSE — two of the five are
GPL-3.0 and redistribution needs the text alongside; the MIT ones want their
copyright notice kept as well. plugin/vendor/obsidian/LICENSES.md is the
hand-written index; keep it in step when a pin changes.

Exit 0 on success (actions on stdout); exit 1 with problems on stderr. A
verify-mode mismatch writes nothing for that asset — the vendored tree only
ever holds bytes the pins vouch for.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PINS_PATH = REPO_ROOT / "plugin" / "lib" / "plugin-pins.json"
VENDOR_DIR = REPO_ROOT / "plugin" / "vendor" / "obsidian"
RELEASE_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{tag}/{path}"
LICENSE_DEST = "LICENSE"
# Files at the vendor root that are not a pinned entry's directory.
VENDOR_ROOT_FILES = {"LICENSES.md"}


def fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def load_pins(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_pins(pins: dict) -> str:
    return json.dumps(pins, indent=2, ensure_ascii=False) + "\n"


def entries(pins: dict):
    """(label, entry) pairs — label is the plugin id or the theme name, which
    is also the directory name both the vault and the vendor tree use."""
    for plugin in pins["plugins"]:
        yield plugin["id"], plugin
    yield pins["theme"]["name"], pins["theme"]


def _write(dest: Path, payload: bytes, label: str, actions: list) -> None:
    if dest.is_file() and dest.read_bytes() == payload:
        actions.append(f"unchanged {label}/{dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    actions.append(f"written   {label}/{dest.name}")


def refresh(pins: dict, vendor_dir: Path, fetch=fetch_url, record: bool = False
            ) -> tuple[list[str], list[str]]:
    """Download every pinned asset into vendor_dir/<label>/. In verify mode a
    digest that differs from the pin is a problem and nothing is written for
    that asset; with record=True the pin dict is updated in place instead
    (the caller decides whether to persist it). Returns (actions, problems)."""
    actions: list[str] = []
    problems: list[str] = []
    labels = set()
    for label, entry in entries(pins):
        labels.add(label)
        target = vendor_dir / label
        for asset in entry["assets"]:
            url = RELEASE_URL.format(repo=entry["repo"], tag=entry["tag"], asset=asset)
            try:
                payload = fetch(url)
            except Exception as e:  # noqa: BLE001 — any fetch failure is a refresh problem
                problems.append(f"{label}/{asset}: download failed: {e}")
                continue
            digest = hashlib.sha256(payload).hexdigest()
            pinned = entry.setdefault("sha256", {}).get(asset)
            if record:
                entry["sha256"][asset] = digest
                note = "unchanged" if pinned == digest else f"was {pinned or 'unset'}"
                actions.append(f"recorded  {label}/{asset} sha256 {digest} ({note})")
            elif digest != pinned:
                problems.append(
                    f"{label}/{asset}: sha256 mismatch (pinned {pinned}, downloaded {digest}) "
                    f"— not written. If the tag was bumped on purpose, rerun with --record."
                )
                continue
            _write(target / asset, payload, label, actions)
        license_file = entry.get("license_file")
        if not license_file:
            problems.append(
                f"{label}: pin has no license_file — every vendored copy ships its licence text"
            )
        else:
            url = RAW_URL.format(repo=entry["repo"], tag=entry["tag"], path=license_file)
            try:
                text = fetch(url)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{label}/{LICENSE_DEST}: download failed: {e}")
            else:
                _write(target / LICENSE_DEST, text, label, actions)
        expected = set(entry["assets"]) | {LICENSE_DEST}
        if target.is_dir():
            for stale in sorted(p for p in target.iterdir() if p.name not in expected):
                if stale.is_file():
                    stale.unlink()
                    actions.append(f"removed   {label}/{stale.name} (not in pins)")
                else:
                    problems.append(f"{label}/{stale.name}: unexpected directory in the vendor tree")
    if vendor_dir.is_dir():
        for extra in sorted(vendor_dir.iterdir()):
            if extra.is_dir() and extra.name not in labels:
                problems.append(
                    f"{extra.relative_to(vendor_dir)}: vendored directory with no pin — remove it"
                )
            elif extra.is_file() and extra.name not in VENDOR_ROOT_FILES:
                problems.append(f"{extra.name}: unexpected file at the vendor root")
    return actions, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the vendored Obsidian plugin/theme assets from the pins.",
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pins", type=Path, default=PINS_PATH)
    parser.add_argument("--vendor", type=Path, default=VENDOR_DIR)
    parser.add_argument("--record", action="store_true",
                        help="record downloaded sha256 digests into the pins instead of verifying")
    args = parser.parse_args(argv)
    pins = load_pins(args.pins)
    # fetch_url passed explicitly (looked up at call time) rather than relying
    # on refresh()'s default, so tests can substitute the module attribute.
    actions, problems = refresh(pins, args.vendor, fetch=fetch_url, record=args.record)
    for line in actions:
        print(line)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if args.record:
        args.pins.write_text(dump_pins(pins), encoding="utf-8", newline="\n")
        print(f"pins written: {args.pins}")
    written = sum(1 for a in actions if a.startswith("written"))
    unchanged = sum(1 for a in actions if a.startswith("unchanged"))
    print(f"{written} written, {unchanged} unchanged, {len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
