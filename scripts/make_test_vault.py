#!/usr/bin/env python3
"""Instantiate a throwaway vault for hand-testing the plugin.

Copies template/ into TARGET, then overlays fixtures/demo-vault/ on top
unless --fresh is given (template-only, for onboarding testing). Refuses to
touch a TARGET that already exists and is non-empty — this script only ever
creates, never merges into or overwrites existing work.

Exit 0 on success; exit 1 with a message on stderr if TARGET is non-empty.
"""
import argparse
import shutil
import sys
from pathlib import Path


class TargetNotEmptyError(Exception):
    pass


def build_vault(target: Path, repo_root: Path, fresh: bool) -> None:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmptyError(f"{target} already exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "template", target, dirs_exist_ok=True)
    if not fresh:
        shutil.copytree(repo_root / "fixtures" / "demo-vault", target, dirs_exist_ok=True)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Instantiate a test vault from template/ (+ demo fixtures unless --fresh)."
    )
    parser.add_argument("target", type=Path, help="Directory to create the test vault in")
    parser.add_argument(
        "--fresh", action="store_true", help="Template only — skip the demo fixtures overlay"
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        build_vault(args.target.resolve(), repo_root, args.fresh)
    except TargetNotEmptyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    mode = "template-only" if args.fresh else "template + demo fixtures"
    print(f"Test vault created at {args.target} ({mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
