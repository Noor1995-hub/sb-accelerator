#!/usr/bin/env python3
"""Instantiate a throwaway vault for hand-testing the plugin.

Copies plugin/template/ into TARGET, then overlays fixtures/demo-vault/ on top
unless --fresh is given (template-only, for onboarding testing). When the
demo fixtures are overlaid, they are also re-dated (--demo-day, default
today) so vaultlib.dates.plan()'s recap window works regardless of what day
this script is run — see redate.py. Refuses to touch a TARGET that already
exists and is non-empty — this script only ever creates, never merges into
or overwrites existing work. With --with-plugins, also downloads the pinned
Obsidian community plugins and theme into the new vault (network required).

Also creates the .claude -> claude symlink so vault-local Claude Code files
stay visible in Obsidian (warning, not failure, if the OS refuses).

Exit 0 on success; exit 1 with a message on stderr if TARGET is non-empty.
"""
import argparse
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import redate


def provision_into(vault: Path) -> tuple[list[str], list[str]]:
    """Install the pinned Obsidian plugins + theme into the new vault.
    Kept as a thin module-level seam so tests monkeypatch it (no network)."""
    # provision_plugins.py lives at plugin/lib/ (it ships with the plugin),
    # not next to this script — put it on sys.path before importing. Tests
    # get this for free from conftest.py; a direct `python3
    # scripts/make_test_vault.py` invocation does not.
    lib_dir = str(Path(__file__).resolve().parents[1] / "plugin" / "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from provision_plugins import PINS_PATH, load_pins, provision

    return provision(vault, load_pins(PINS_PATH))


class TargetNotEmptyError(Exception):
    pass


def build_vault(target: Path, repo_root: Path, fresh: bool,
                 demo_day: Optional[date] = None) -> list[str]:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmptyError(f"{target} already exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "plugin" / "template", target, dirs_exist_ok=True)
    if not fresh:
        shutil.copytree(repo_root / "fixtures" / "demo-vault", target, dirs_exist_ok=True)
        # demo_day is ignored for --fresh (fresh has no fixtures to re-date).
        # `redate.date` (not a plain `date` import) so tests can monkeypatch
        # the "today" default without a live clock.
        redate.redate_vault(target, demo_day or redate.date.today())
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


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--demo-day must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from exc


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Instantiate a test vault from plugin/template/ (+ demo fixtures unless --fresh)."
    )
    parser.add_argument("target", type=Path, help="Directory to create the test vault in")
    parser.add_argument(
        "--fresh", action="store_true", help="Template only — skip the demo fixtures overlay"
    )
    parser.add_argument(
        "--demo-day", type=_parse_iso_date, default=None,
        help="re-date demo fixtures as if today were this date (default: today); "
             "ignored with --fresh",
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
        warnings = build_vault(args.target.resolve(), repo_root, args.fresh, args.demo_day)
    except TargetNotEmptyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    mode = "template-only" if args.fresh else "template + demo fixtures"
    print(f"Test vault created at {args.target} ({mode}).")
    if not args.fresh:
        demo_day = args.demo_day or redate.date.today()
        anchor = redate.discover_anchor(repo_root / "fixtures" / "demo-vault")
        shift_a_days, recap_from = redate.weekday_aligned_shift(anchor, demo_day)
        print(
            f"demo day: {demo_day.isoformat()} (shifted fixtures {shift_a_days:+d} days; "
            f"recap window covers {recap_from.isoformat()}..{demo_day.isoformat()})"
        )
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
