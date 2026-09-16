import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# scripts/ — for compile_ontology, lint_plugin, validate_template, make_test_vault
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# plugin/lib/ — for the vaultlib package the skills call at runtime
sys.path.insert(0, str(REPO_ROOT / "plugin" / "lib"))

# 1970-01-12 — far enough from any runner's clock that "still stale" and
# "rewritten just now" can never be confused.
STALE_MTIME_NS = 1_000_000_000


@pytest.fixture
def mark_stale():
    """Back-date a file's mtime, and return the stamp it now carries.

    Sampling `st_mtime_ns` before a write and comparing after is not a
    reliable "was this rewritten?" check: two writes inside one timer tick
    land on the same stamp, so a real rewrite reads as no rewrite. That went
    red on a Windows runner while the Ubuntu jobs stayed green. Back-dating
    first removes the race — a rewrite has to move the stamp by decades.
    """
    def mark(path: Path) -> int:
        os.utime(path, ns=(STALE_MTIME_NS, STALE_MTIME_NS))
        return STALE_MTIME_NS
    return mark


def pytest_configure(config):
    """Register the marker here rather than in a new pytest.ini — keeps `-q`
    free of unknown-marker warnings without adding a config file."""
    config.addinivalue_line(
        "markers",
        "obsidian: needs a live Obsidian instance and a captured probe tour "
        "(local only; skipped in CI)")
