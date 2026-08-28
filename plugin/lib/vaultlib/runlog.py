"""The append-only routine-run log.

`--unattended` exiting 0 having done nothing is a silent failure by
construction: nothing crashed, nothing prompted, and the only trace was a
summary nobody read because nothing looked wrong. This module gives every
unattended run — including the "nothing to do" case — exactly one line in
one place a human can grep:
`99-workflow-config/logs/routine-runs.log`.

The log lives under the vault, not `$SCRATCH`: it is small, append-only,
and it is meant to outlive any single run. It is runtime-created (the
directory does not ship in `plugin/template/`), so an older vault gains it the
first time a routine runs after upgrading — no migration needed.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

LOG_RELPATH = Path("99-workflow-config") / "logs" / "routine-runs.log"
_ROUTINE_RE = re.compile(r"\A[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")


class RunLogError(Exception):
    """A run-log argument the caller must fix."""


def append(root: Path, routine: str, outcome: str) -> Dict[str, str]:
    """Append one `{timestamp}\\t{routine}\\t{outcome}` line, tab-separated.

    `outcome` is collapsed to a single line (embedded newlines become
    spaces) so the log stays one line per run regardless of what the
    caller passes — a multi-line outcome would otherwise make the file
    ungreppable for exactly the runs someone most wants to find.
    """
    if not _ROUTINE_RE.match(routine):
        raise RunLogError(
            f"--routine must be lowercase kebab-case (e.g. 'evening-sync'), "
            f"got {routine!r}")
    collapsed = " ".join(outcome.split())
    if not collapsed:
        raise RunLogError("--outcome must not be empty")

    log_path = root / LOG_RELPATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{stamp}\t{routine}\t{collapsed}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return {"path": log_path.relative_to(root).as_posix(), "line": line.rstrip("\n")}
