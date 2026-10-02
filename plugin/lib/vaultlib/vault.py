"""Vault root resolution and safe writes.

The vault root is always supplied by the caller: under Cowork it is a VirtioFS
mount point, not a path shape anything can infer.
"""
from __future__ import annotations

import datetime as _datetime
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import List, Optional

IDENTITY_RELPATH = Path("99-workflow-config") / "context" / "identity.md"
_BEGIN = "<!-- setup-my-brain:begin -->"
_END = "<!-- setup-my-brain:end -->"

CONTEXT_DIR = Path("99-workflow-config") / "context"
CONTEXT_FILES = ("identity", "role-and-responsibilities", "communication-style",
                 "preferences-and-constraints", "tools-and-systems")

# The folder taxonomy and the ISO-date shape live here, in the one module
# every other one already imports, so a rename is a single edit rather than a
# grep. Modules alias what they use (`MEETINGS_DIR = vault.MEETINGS_DIR`).
INBOX_DIR = "10-inbox"
MEETINGS_DIR = "20-meetings"
PROJECTS_DIR = "30-projects"
ENTITIES_DIR = "40-entities"
PEOPLE_DIR = "50-people"
DAILY_NOTES_DIR = "60-daily-notes"
ARCHIVE_DIR = "90-archive"
ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

# A directory is a vault if it carries the config folder and at least one
# numbered content folder. Cheap, and it stops a mistyped path from scattering
# object folders across someone's home directory.
_MARKER = Path("99-workflow-config")
_CONTENT_FOLDERS = (INBOX_DIR, MEETINGS_DIR, PROJECTS_DIR, ENTITIES_DIR,
                    PEOPLE_DIR, DAILY_NOTES_DIR)


class VaultError(Exception):
    """A vault path or argument the caller must fix."""


def resolve(raw: str) -> Path:
    root = Path(os.path.expanduser(str(raw))).resolve()
    if not root.is_dir():
        raise VaultError(
            f"vault path does not exist or is not a directory: {root} — in "
            "Cowork this is usually a mount, not a typo, and there are two "
            "causes: the folder was created after the session started, so it "
            "was never mounted (restart the session with the folder "
            "connected — re-picking it in the folder picker does not remount "
            "it), or this is a cloud session, where the vault is not a "
            "filesystem at all (Settings → Cowork → Run new tasks in the "
            "cloud: off)")
    if not (root / _MARKER).is_dir() or not any(
        (root / folder).is_dir() for folder in _CONTENT_FOLDERS
    ):
        raise VaultError(
            f"{root} does not look like a vault "
            f"(expected a {_MARKER}/ folder and at least one numbered content folder)"
        )
    return root


# Windows refuses a rename onto (or of) a file another process holds open
# without delete-sharing — a scanner or indexer looking at the file just
# written — with WinError 5 for a few milliseconds. Seen at ~8% of
# migration-test runs on a Windows host; a short retry cleared all of them.
# A lasting PermissionError still surfaces, ~0.6 s later.
REPLACE_ATTEMPTS = 6
_REPLACE_BACKOFF_S = 0.02


def _replace(src: str, dst: str) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * 2 ** attempt)


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
        _replace(handle.name, str(path))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def atomic_create(path: Path, text: str) -> None:
    """atomic_write, but refuse to replace a file that already exists.

    Two concurrent writers that both looked and saw no file at `path` must
    not last-write-wins each other — /sync-recordings runs its per-recording
    workers in parallel, and one meeting captured by two sources in the same
    run derives the same note stem in both workers. The name is claimed with
    O_EXCL (atomic on every platform Python supports), then the durable
    temp+replace of atomic_write lands the content over the caller's own
    claim. The loser gets FileExistsError and re-resolves. A crash between
    claim and replace leaves an empty file, which a later writer treats as
    an existing unreadable note — suffixed around, never overwritten.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    atomic_write(path, text)


def _context_path(root: Path, stem: str) -> Path:
    if stem not in CONTEXT_FILES:
        raise VaultError(
            f"context file must be one of {sorted(CONTEXT_FILES)}, got {stem!r}")
    path = root / CONTEXT_DIR / f"{stem}.md"
    if not path.is_file():
        raise VaultError(
            f"{(CONTEXT_DIR / (stem + '.md')).as_posix()} is missing from this vault")
    return path


def read_context_block(root: Path, stem: str) -> Optional[str]:
    """Return the content between one context file's setup-my-brain markers.

    Extraction only. Deciding what belongs in the block is judgment, and
    stays with the model.
    """
    text = _context_path(root, stem).read_text(encoding="utf-8")
    start, end = text.find(_BEGIN), text.find(_END)
    if start == -1 or end == -1 or end <= start:
        return None
    block = text[start + len(_BEGIN):end].strip()
    return block or None


def write_context_block(root: Path, stem: str, content: str) -> dict:
    """Replace one context file's setup-my-brain block, byte-exact outside it."""
    if _BEGIN in content or _END in content:
        raise VaultError(
            "content must not contain the setup-my-brain markers — the CLI "
            "owns them")
    path = _context_path(root, stem)
    text = path.read_text(encoding="utf-8")
    start, end = text.find(_BEGIN), text.find(_END)
    if start == -1 or end == -1 or end <= start:
        raise VaultError(
            f"{path.name} has no intact setup-my-brain marker pair — restore "
            "it from the template before writing")
    replaced = bool(text[start + len(_BEGIN):end].strip())
    new = (text[:start + len(_BEGIN)] + "\n" + content.strip() + "\n"
           + text[end:])
    atomic_write(path, new)
    return {"file": (CONTEXT_DIR / f"{stem}.md").as_posix(),
            "replaced": replaced}


def read_identity_block(root: Path) -> Optional[str]:
    """Return the content between identity.md's setup-my-brain markers.

    Extraction only. Deciding *which* words in it are the vault owner's name
    is judgment, and stays with the model.
    """
    try:
        return read_context_block(root, "identity")
    except VaultError:
        return None


def today_iso(explicit: Optional[str] = None) -> str:
    """Today as unquoted ISO. Explicit values keep the CLI deterministic."""
    if explicit is None:
        return _datetime.date.today().isoformat()
    if not ISO_DATE_RE.match(explicit):
        raise VaultError(f"date {explicit!r} must be ISO YYYY-MM-DD")
    return explicit


def list_dir_names(path: Path) -> List[str]:
    if not path.is_dir():
        return []
    return sorted(entry.name for entry in path.iterdir() if entry.is_dir())


def plugin_version() -> str:
    """The shipped plugin version, for stamping feedback reports.

    Never raises: a broken or missing plugin.json must not stop feedback
    from being sent — it just loses its version stamp.
    """
    path = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


def structure_version(root: Path) -> str:
    """The vault-root structure-version marker, stripped."""
    path = root / "structure-version"
    if not path.is_file():
        raise VaultError(f"{path.name} is missing from this vault")
    return path.read_text(encoding="utf-8").strip()
