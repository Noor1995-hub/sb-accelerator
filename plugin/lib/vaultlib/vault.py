"""Vault root resolution and safe writes.

The vault root is always supplied by the caller: under Cowork it is a VirtioFS
mount point, not a path shape anything can infer.
"""
from __future__ import annotations

import datetime as _datetime
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

IDENTITY_RELPATH = Path("99-workflow-config") / "context" / "identity.md"
_BEGIN = "<!-- setup-my-brain:begin -->"
_END = "<!-- setup-my-brain:end -->"
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

# A directory is a vault if it carries the config folder and at least one
# numbered content folder. Cheap, and it stops a mistyped path from scattering
# object folders across someone's home directory.
_MARKER = Path("99-workflow-config")
_CONTENT_FOLDERS = ("10-inbox", "20-meetings", "30-projects", "40-entities",
                    "50-people", "60-daily-notes")


class VaultError(Exception):
    """A vault path or argument the caller must fix."""


def resolve(raw: str) -> Path:
    root = Path(os.path.expanduser(str(raw))).resolve()
    if not root.is_dir():
        raise VaultError(f"vault path does not exist or is not a directory: {root}")
    if not (root / _MARKER).is_dir() or not any(
        (root / folder).is_dir() for folder in _CONTENT_FOLDERS
    ):
        raise VaultError(
            f"{root} does not look like a vault "
            f"(expected a {_MARKER}/ folder and at least one numbered content folder)"
        )
    return root


def atomic_write(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings, via a temp file in the same directory.

    newline="\\n" is explicit: a write from a Windows host must not inject
    CRLF into markdown that syncs to a Mac.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n",
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp", delete=False,
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, str(path))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def read_identity_block(root: Path) -> Optional[str]:
    """Return the content between identity.md's setup-my-brain markers.

    Extraction only. Deciding *which* words in it are the executive's name is
    judgment, and stays with the model.
    """
    path = root / IDENTITY_RELPATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1 or end <= start:
        return None
    block = text[start + len(_BEGIN):end].strip()
    return block or None


def today_iso(explicit: Optional[str] = None) -> str:
    """Today as unquoted ISO. Explicit values keep the CLI deterministic."""
    if explicit is None:
        return _datetime.date.today().isoformat()
    if not _ISO_DATE_RE.match(explicit):
        raise VaultError(f"date {explicit!r} must be ISO YYYY-MM-DD")
    return explicit


def list_dir_names(path: Path) -> List[str]:
    if not path.is_dir():
        return []
    return sorted(entry.name for entry in path.iterdir() if entry.is_dir())
