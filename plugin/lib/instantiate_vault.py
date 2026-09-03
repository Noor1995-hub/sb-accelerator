#!/usr/bin/env python3
"""Instantiate a vault from the plugin's own template.

This is the /provision-vault skill's copy primitive. It ships inside the
plugin, at plugin/lib/, specifically so it works with zero repo checkout —
the plugin cache installed on a client machine is the only copy of
plugin/template that machine has, and TEMPLATE_ROOT below is resolved
relative to this file for exactly that reason: `parents[1]` from
plugin/lib/instantiate_vault.py is plugin/, so `plugin/template` resolves
correctly whether this file is running from a repo checkout or from the
plugin cache Claude Code or Cowork installed it into.

Mirrors scripts/make_test_vault.py's guardrails (refuse a non-empty target,
verify the copy actually landed, attempt the `.claude -> claude` symlink),
because a dev-only script and a shipped one solving the same problem should
not silently drift into different behavior. It does not import
make_test_vault.py — that module lives in scripts/, which is not part of
the shipped plugin tree.

Stdlib only, Python 3.10 floor (plugin/CLAUDE.md's "Runtime constraints for
lib/") — this runs inside the Cowork Linux VM and on a consultant's own
machine equally. Writes UTF-8 with `newline="\\n"` where this module writes
anything itself (it currently only reads back what shutil.copytree wrote).

Prints exactly one JSON object, in the same envelope vaultlib/cli.py uses:

    {"ok": true,  "result": {...}}                 exit 0
    {"ok": false, "error": "...", "hint": "..."}   exit 1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from vaultlib import provenance

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "template"

# The structure-version a freshly instantiated vault must carry. Mirrors
# scripts/validate_template.py's EXPECTED_STRUCTURE_VERSION and the same
# rationale: hardcoded rather than read from the migration chain, because a
# stale plugin cache silently shipping the wrong template is exactly what
# this check exists to catch — importing the chain here would make the
# assertion agree with whatever the chain says and catch nothing. Bump both
# together.
EXPECTED_STRUCTURE_VERSION = "2"


class InstantiateError(Exception):
    """A guardrail this module refuses to proceed past.

    Both cases it is raised for — a non-empty target, a copy that failed to
    verify — are refusals, not partial states: the caller never has to
    reason about a half-built vault, only about "did it happen or not".
    """


def instantiate(target: Path, template_root: Optional[Path] = None) -> dict:
    """Copy template_root (default: this plugin's own plugin/template) into
    target, verify the copy landed, and attempt the .claude symlink.

    Raises InstantiateError before touching anything if target already
    exists and is not empty. Raises InstantiateError after the copy if
    .obsidian/ did not arrive or structure-version does not read as
    EXPECTED_STRUCTURE_VERSION — either means the source template (or the
    plugin cache it came from) is corrupt, not that this run did something
    wrong, but it must stop here rather than hand back a vault that looks
    complete and is not.
    """
    template_root = Path(template_root) if template_root is not None else TEMPLATE_ROOT
    target = Path(target)

    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise InstantiateError(f"{target} already exists and is not empty")

    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_root, target, dirs_exist_ok=True)

    obsidian_present = (target / ".obsidian").is_dir()
    if not obsidian_present:
        raise InstantiateError(
            f"{target / '.obsidian'} did not arrive — the copy from "
            f"{template_root} is incomplete")

    version_path = target / "structure-version"
    found_version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.is_file() else None
    )
    if found_version != EXPECTED_STRUCTURE_VERSION:
        raise InstantiateError(
            f"{version_path} reads {found_version!r}, expected "
            f"{EXPECTED_STRUCTURE_VERSION!r} — the copied template is stale "
            "or the plugin cache is corrupt")

    # Never raises (provenance.record_provision's own contract) — a
    # provenance failure must not fail a provision that otherwise landed.
    provenance_status = provenance.record_provision(target, template_root)

    return {
        "target": str(target),
        "template": str(template_root),
        "obsidian_present": obsidian_present,
        "structure_version": found_version,
        "symlink": _create_symlink(target),
        "provenance": provenance_status,
    }


def _create_symlink(target: Path) -> str:
    """Best-effort `.claude -> claude` relative symlink. A failure here is a
    warning the caller reports, never a reason to fail the whole run — the
    vault this produced is otherwise complete, and Windows machines without
    Developer Mode or an elevated shell are an expected, recoverable case
    (see playbooks/provisioning-runbook.md)."""
    claude_dir = target / "claude"
    link = target / ".claude"
    if not claude_dir.is_dir():
        return "skipped — no claude/ directory in the template"
    if link.exists():
        return "skipped — .claude already exists"
    try:
        os.symlink("claude", link)
    except OSError as exc:
        return f"failed — {exc}"
    return "created"


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Instantiate a vault from the plugin's own template.")
    parser.add_argument("target", type=Path, help="Directory to create the vault in")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    target = args.target.resolve()
    try:
        result = instantiate(target)
    except InstantiateError as exc:
        _emit({
            "ok": False,
            "error": str(exc),
            "hint": "choose an empty target, or remove the partial copy and retry",
        })
        return 1
    _emit({"ok": True, "result": result})
    return 0


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
