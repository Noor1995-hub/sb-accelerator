#!/usr/bin/env python3
"""Instantiate a throwaway vault for hand-testing the plugin.

Copies plugin/template/ into TARGET, then overlays fixtures/demo-vault/ on top
unless --fresh is given (template-only, for onboarding testing). By default
the demo fixtures land byte-pristine — unchanged from the committed
fixture — because the visual-check tier (obsidian_probe.py's provenance()
and its basesim cross-check) depends on that exact match. Pass --demo-day to
opt into re-dating the fixtures (bare flag: as if today were the demo day;
with a value: as if today were that ISO date) so vaultlib.dates.plan()'s
recap window works on the day the demo is actually shown — see redate.py.
Refuses to touch a TARGET that already exists and is non-empty — this
script only ever creates, never merges into or overwrites existing work.
With --with-plugins, also downloads the pinned Obsidian community plugins
and theme into the new vault (network required).

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
    """demo_day=None means NO re-dating: the fixture overlay lands exactly as
    committed, byte-for-byte, which is what the visual-check tier requires
    (obsidian_probe.provenance() and its basesim cross-check compare against
    the committed fixture verbatim). Pass a concrete date to opt into
    redate.redate_vault(); the CLI resolves a bare --demo-day to "today"
    before calling this, so this function itself never defaults to today."""
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmptyError(f"{target} already exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "plugin" / "template", target, dirs_exist_ok=True)
    if not fresh:
        shutil.copytree(repo_root / "fixtures" / "demo-vault", target, dirs_exist_ok=True)
        if demo_day is not None:
            redate.redate_vault(target, demo_day)
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

    # plugin/lib/ is where the shipped vaultlib package lives, not next to
    # this script — same seam provision_into() uses above. record_provision
    # never raises; a "failed — ..." status is surfaced as a warning rather
    # than aborting a test vault that otherwise built fine.
    lib_dir = str(repo_root / "plugin" / "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from vaultlib import provenance

    status = provenance.record_provision(target, repo_root / "plugin" / "template")
    if status.startswith("failed"):
        warnings.append(f"provenance not recorded ({status})")
    return warnings


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--demo-day must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from exc


# nargs="?" gives --demo-day three distinct states argparse tells apart by
# identity, not by truthiness (a real date is always truthy, but so is this
# sentinel — `is` is what matters): omitted entirely -> default (None, no
# re-dating, byte-pristine fixtures); given with no value -> const (this
# sentinel, resolved to today by main()); given a value -> that value run
# through _parse_iso_date. argparse only applies `type` to a value actually
# present on the command line, so default/const bypass it and reach main()
# untouched.
_TODAY_SENTINEL = object()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Instantiate a test vault from plugin/template/ (+ demo fixtures unless --fresh)."
    )
    parser.add_argument("target", type=Path, help="Directory to create the test vault in")
    parser.add_argument(
        "--fresh", action="store_true", help="Template only — skip the demo fixtures overlay"
    )
    parser.add_argument(
        "--demo-day", nargs="?", const=_TODAY_SENTINEL, default=None, type=_parse_iso_date,
        help="opt into re-dating the demo fixtures so the recap window works "
             "today (they land byte-pristine, matching the committed fixture, "
             "if this flag is omitted entirely); bare flag means today, or "
             "pass an ISO date (YYYY-MM-DD) to re-date as if today were that "
             "date; ignored with --fresh",
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
    demo_day = None
    if not args.fresh and args.demo_day is not None:
        # `redate.date` (not a plain `date` import) so tests can monkeypatch
        # the "today" resolution without a live clock.
        demo_day = redate.date.today() if args.demo_day is _TODAY_SENTINEL else args.demo_day
    try:
        warnings = build_vault(args.target.resolve(), repo_root, args.fresh, demo_day)
    except TargetNotEmptyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    mode = "template-only" if args.fresh else "template + demo fixtures"
    print(f"Test vault created at {args.target} ({mode}).")
    if demo_day is not None:
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
