"""Structure version 6: the hidden `_messages/` folder for mail and Teams logs.

Creates `_messages/` and hides it in the file list (Notebook Navigator's
`vaultProfiles[0].hiddenFolders`) and in search, graph and quick switcher
(Obsidian's `userIgnoreFilters`). Each list is merged into, never replaced:
whatever the owner already hid stays hidden. A file that is missing, or a
Notebook Navigator config with no `vaultProfiles`, is skipped (and `verify`
does not demand it). Moves nothing, lossless. `verify` only reads.

Touches two template-managed files, both in the silent tier of
`vaultlib/template.py`: `.obsidian/app.json` and
`.obsidian/plugins/notebook-navigator/data.json`. Editing them leaves their
recorded digest stale, so `template status` reports them as `needs-consent`
(locally edited) with no local edit behind it. The shipped template carries
the same two entries, so a template refresh that names either file with
`--consent` keeps `_messages` hidden; it also replaces the file with the
shipped bytes, which drops any other entry the owner added to that list.
Without consent the owner's lists stay exactly as this migration left them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 6
LOSSY = None
_NAV = Path(".obsidian") / "plugins" / "notebook-navigator" / "data.json"
_APP = Path(".obsidian") / "app.json"
_NAV_ENTRY = vault.MESSAGES_DIR
_APP_ENTRY = f"{vault.MESSAGES_DIR}/"


def _nav_list(data: dict, create: bool):
    profiles = data.get("vaultProfiles") or []
    if not profiles:
        return None
    if create:
        return profiles[0].setdefault("hiddenFolders", [])
    return profiles[0].get("hiddenFolders", [])


def _app_list(data: dict, create: bool):
    if create:
        return data.setdefault("userIgnoreFilters", [])
    return data.get("userIgnoreFilters", [])


def _merge(path: Path, getter, entry: str) -> bool:
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    target = getter(data, True)
    if target is None or entry in target:
        return False
    target.append(entry)
    vault.atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


def _has(path: Path, getter, entry: str) -> bool:
    """True when the file is absent (nothing to demand) or lists `entry`."""
    if not path.is_file():
        return True
    target = getter(json.loads(path.read_text(encoding="utf-8")), False)
    return target is None or entry in target


def apply(root: Path) -> dict:
    folder = root / vault.MESSAGES_DIR
    created = not folder.is_dir()
    folder.mkdir(exist_ok=True)
    return {"created": created,
            "nav": _merge(root / _NAV, _nav_list, _NAV_ENTRY),
            "app": _merge(root / _APP, _app_list, _APP_ENTRY)}


def verify(root: Path) -> dict:
    if not (root / vault.MESSAGES_DIR).is_dir():
        raise RuntimeError(f"{vault.MESSAGES_DIR}/ was not created")
    if not _has(root / _NAV, _nav_list, _NAV_ENTRY):
        raise RuntimeError(f"{_NAV_ENTRY} is not hidden in Notebook Navigator")
    if not _has(root / _APP, _app_list, _APP_ENTRY):
        raise RuntimeError(f"{_APP_ENTRY} is not excluded in app.json userIgnoreFilters")
    return {"checked": 3}
