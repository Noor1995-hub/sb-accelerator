"""Scratch-directory hygiene for unattended runs.

`rm -f "$SCRATCH"/rec_*.json ...` looks harmless, but it is a Bash builtin
taking a glob — exactly the shape a permission system flags mid-run, and on
a headless run nobody is there to answer the prompt. Issue #95 traced a
52-minute unattended hang straight to that command, on the one step that
must always run: the privacy-hygiene sweep at the end of `/sync-recordings`.

The fix is not a broader pre-approval for `rm` — that widens the blast
radius of every future Bash call, prompt or no prompt. It is to make the
sweep itself a `python3 "$VAULTLIB" ...` call, so it sits behind the same
narrow pre-approval every other unattended step already uses.

This module is deliberately dumb: a fixed pattern list, one directory, no
recursion. It does not take a vault root and does not touch the vault — the
whole point of `$SCRATCH` is that it is not the vault.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

# Keep this list and the skills' "Scratch hygiene" prose in lockstep —
# see sync-recordings/SKILL.md, evening-sync/SKILL.md and
# setup-my-brain/SKILL.md.
SWEEP_PATTERNS = (
    "plaud.whoami.json",
    "m365.whoami.json",
    "rec_*.json",
    "plaud.list.json",
    "m365_*.json",
    "*.blob.md",
    "ids.json",
    "*.payload.json",
    # /log-decision qualifies the payload with the project slug
    # (decision-<slug>.json) so evening-sync's concurrent per-project
    # subagents cannot race on one shared file; the bare name stays for
    # payloads left behind by older plugin versions.
    "decision.json",
    "decision-*.json",
    # Session-1 onboarding (/setup-my-brain): a sent-mail sample, raw
    # calendar reads, and drafted context blocks. A block file is written
    # only when it is about to be consumed by `context write` — the sweep
    # takes anything matching, so nothing in-flight may sit in $SCRATCH.
    "sentmail.sample.json",
    "calendar.*.json",
    "*.block.md",
)


class ScratchError(Exception):
    """A scratch-sweep argument the caller must fix."""


def sweep(directory: str) -> Dict[str, object]:
    """Delete files directly inside `directory` matching SWEEP_PATTERNS.

    Never recurses — `Path.glob` with a bare filename pattern only matches
    entries directly in `directory`, so a subdirectory named `ids.json`
    cannot smuggle a wider delete in. A path matching a pattern that is not
    a plain file (a directory, a symlink to one) is reported as `skipped`,
    never removed.
    """
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ScratchError(f"scratch directory does not exist: {root}")

    deleted: List[str] = []
    skipped: List[str] = []
    seen = set()
    for pattern in SWEEP_PATTERNS:
        for match in sorted(root.glob(pattern)):
            if match.name in seen:
                continue
            seen.add(match.name)
            if match.is_dir() or not match.is_file():
                skipped.append(match.name)
                continue
            try:
                match.unlink()
                deleted.append(match.name)
            except OSError:
                skipped.append(match.name)
    return {"dir": str(root), "deleted": sorted(deleted), "skipped": sorted(skipped)}
