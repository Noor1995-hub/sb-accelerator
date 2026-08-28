#!/usr/bin/env python3
"""Instantiate a throwaway vault for hand-testing the plugin.

Copies plugin/template/ into TARGET, then overlays fixtures/demo-vault/ on top
unless --fresh is given (template-only, for onboarding testing). Refuses to
touch a TARGET that already exists and is non-empty — this script only ever
creates, never merges into or overwrites existing work. With --with-plugins,
also downloads the pinned Obsidian community plugins and theme into the new
vault (network required).

Also creates the .claude -> claude symlink so vault-local Claude Code files
stay visible in Obsidian (warning, not failure, if the OS refuses).

Exit 0 on success; exit 1 with a message on stderr if TARGET is non-empty.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path


def provision_into(vault: Path) -> tuple[list[str], list[str]]:
    """Install the pinned Obsidian plugins + theme into the new vault.
    Kept as a thin module-level seam so tests monkeypatch it (no network)."""
    from provision_plugins import PINS_PATH, load_pins, provision

    return provision(vault, load_pins(PINS_PATH))


class TargetNotEmptyError(Exception):
    pass


def build_vault(target: Path, repo_root: Path, fresh: bool) -> list[str]:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmptyError(f"{target} already exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "plugin" / "template", target, dirs_exist_ok=True)
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


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Instantiate a test vault from plugin/template/ (+ demo fixtures unless --fresh)."
    )
    parser.add_argument("target", type=Path, help="Directory to create the test vault in")
    parser.add_argument(
        "--fresh", action="store_true", help="Template only — skip the demo fixtures overlay"
    )
    parser.add_argument(
        "--with-plugins",
        action="store_true",
        help="Also download the pinned Obsidian community plugins + theme (network)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        warnings = build_vault(args.target.resolve(), repo_root, args.fresh)
    except TargetNotEmptyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    mode = "template-only" if args.fresh else "template + demo fixtures"
    print(f"Test vault created at {args.target} ({mode}).")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.with_plugins:
        actions, problems = provision_into(args.target.resolve())
        for line in actions:
            print(line)
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if problems:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
