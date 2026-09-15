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
anything itself (the only file it writes is the writability probe, which it
deletes again before returning).

The copy is followed by a mode normalisation, because shutil.copytree calls
copystat on every directory regardless of copy_function and copy2 on every
file, so the vault inherits whatever modes the *source* presents. In Cowork
the plugin cache is a read-only FUSE mount that presents 0o500 directories
and 0o400 files — modes that are a mount-layer presentation, and that
copytree faithfully writes onto the real filesystem through the read-write
vault mount. Any read-only cache (an MDM profile, a restored backup)
reproduces it. Normalising after the copy is the fix; switching
copy_function is not, since directory copystat runs anyway.

Prints exactly one JSON object, in the same envelope vaultlib/cli.py uses:

    {"ok": true,  "result": {...}}                 exit 0
    {"ok": false, "error": "...", "hint": "..."}   exit 1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Optional

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "template"

# Where the writability guard creates (and immediately removes) its probe
# file. 99-workflow-config/ is the first directory anything writes into after
# the copy — record_provision()'s provenance.json — so a probe there fails
# exactly where the first real write would have.
PROBE_RELPATH = Path("99-workflow-config") / ".write-probe.tmp"

DEFAULT_HINT = "choose an empty target, or remove the partial copy and retry"
NOT_WRITABLE_HINT = (
    "the vault must live on a read-write location this user owns (in "
    "Cowork, a connected folder). The read-only modes a read-only plugin "
    "cache (Cowork's is one) hands to the copy are normalised automatically, "
    "so this refusal means the target itself refuses writes: fix the "
    "location or its ownership, remove the partial copy, and retry")

# The structure-version a freshly instantiated vault must carry. Mirrors
# scripts/validate_template.py's EXPECTED_STRUCTURE_VERSION and the same
# rationale: hardcoded rather than read from the migration chain, because a
# stale plugin cache silently shipping the wrong template is exactly what
# this check exists to catch — importing the chain here would make the
# assertion agree with whatever the chain says and catch nothing. Bump both
# together.
EXPECTED_STRUCTURE_VERSION = "3"


class InstantiateError(Exception):
    """A guardrail this module refuses to proceed past.

    Every case it is raised for — a non-empty target, a copy that failed to
    verify, a target that cannot be written to — is a refusal, not a partial
    state: the caller never has to reason about a half-built vault, only
    about "did it happen or not". `hint` is what main() puts in the JSON
    envelope next to the error, so each refusal can say what to do about it.
    """

    def __init__(self, message: str, *, hint: str = DEFAULT_HINT):
        super().__init__(message)
        self.hint = hint


def make_user_writable(root: Path) -> None:
    """`chmod -R u+rwX` in stdlib: every directory under root (root itself
    included) gets `mode | 0o700`, every regular file `mode | 0o600`. Only
    ever widens modes — group/other bits are left exactly as copied.

    Runs directly after shutil.copytree, because copytree calls copystat on
    every directory it creates (root included, so the mode target.mkdir()
    gave it is overwritten) and copies file permission bits with copy2 — a
    read-only source therefore yields a vault nobody can write into.
    Symlinks are left alone: chmod would follow them to their target.
    scripts/make_test_vault.py calls this too, so the two copy paths cannot
    drift on it.
    """
    root = Path(root)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | 0o700)
    for child in root.iterdir():
        if child.is_symlink():
            continue
        if child.is_dir():
            make_user_writable(child)
        else:
            child.chmod(stat.S_IMODE(child.stat().st_mode) | 0o600)


def _probe_write(path: Path) -> None:
    """The one write the writability guard performs — a seam so a test can
    make it fail without a read-only filesystem to hand."""
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write("probe\n")


def _ensure_writable(target: Path) -> None:
    """Normalise the copied modes, then create and remove a probe file where
    the first real write will land.

    A vault that cannot be written to is exactly as broken as one missing
    .obsidian/, so this raises rather than warns. Before it existed, the
    first casualties of a read-only vault were record_provision() and the
    symlink — both reported through never-raises "failed — …" contracts, so
    the envelope read ok: true over a vault the client could not add a note
    to.
    """
    try:
        make_user_writable(target)
    except OSError as exc:
        raise InstantiateError(
            f"{target} is not writable — could not make the copied template "
            f"user-writable: {exc}", hint=NOT_WRITABLE_HINT) from exc

    probe = target / PROBE_RELPATH
    if not probe.parent.is_dir():
        probe = target / PROBE_RELPATH.name
    try:
        _probe_write(probe)
    except OSError as exc:
        raise InstantiateError(
            f"{target} is not writable — creating "
            f"{probe.relative_to(target).as_posix()} failed: {exc}",
            hint=NOT_WRITABLE_HINT) from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def instantiate(target: Path, template_root: Optional[Path] = None) -> dict:
    """Copy template_root (default: this plugin's own plugin/template) into
    target, make the copy user-writable, verify it landed, and attempt the
    .claude symlink.

    Raises InstantiateError before touching anything if target already
    exists and is not empty. Raises InstantiateError after the copy if the
    target cannot be written to, if .obsidian/ did not arrive, or if
    structure-version does not read as EXPECTED_STRUCTURE_VERSION — each
    means the source template (or the plugin cache it came from) is
    read-only or corrupt, not that this run did something wrong, but it
    must stop here rather than hand back a vault that looks complete and is
    not.
    """
    template_root = Path(template_root) if template_root is not None else TEMPLATE_ROOT
    target = Path(target)

    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise InstantiateError(f"{target} already exists and is not empty")

    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_root, target, dirs_exist_ok=True)
    # Before anything writes: record_provision() and the symlink below are
    # the first writes into the new vault, and both report failure softly.
    _ensure_writable(target)

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

    # Imported here, not at module load, so a plugin cache that is somehow
    # missing vaultlib (or has it broken) fails this one step — reported
    # through record_provision's own never-raises "failed — ..." contract —
    # rather than killing the whole primitive with an import traceback and
    # no JSON envelope at all before instantiate() even starts.
    try:
        from vaultlib import provenance
    except Exception as exc:  # noqa: BLE001 — never raises, by design
        provenance_status = f"failed — {exc}"
    else:
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
        _emit({"ok": False, "error": str(exc), "hint": exc.hint})
        return 1
    _emit({"ok": True, "result": result})
    return 0


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
