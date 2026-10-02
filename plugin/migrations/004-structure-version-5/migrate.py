"""Structure-version 5: the vault opens on today's daily note (#238).

Sets Notebook Navigator's homepage to the daily note, and points its
calendar integration at Obsidian's own Daily notes settings (folder
`60-daily-notes`, `YYYY-MM-DD`) — the note the evening run writes — rather
than Navigator's own file pattern. `createMissingPeriodicNote` is off: on a
morning after a skipped evening run, an empty note created by Navigator
would have no recap or prep markers, and the catch-up run then refuses to
write into it. With no note for today, Obsidian simply opens what it had
open.

Merged key by key into `.obsidian/plugins/notebook-navigator/data.json`,
like migration 003 and for the same reason — Navigator writes its own UI
state into that file. Only `homepage` and `calendarIntegrationMode` are
written. A vault without the file skips (the template refresh restores a
missing one, already carrying these values).

The review block at the top of the daily note and its CSS need no
migration: the evening run writes the block into each new note, and the
snippet arrives with the template refresh. Notes written before this
version keep their layout.

`LOSSY` is set because both keys are reset to the shipped values even where
the owner had chosen another homepage. Obsidian must be closed while this
runs, as for every migration that touches `.obsidian/`.
"""
from __future__ import annotations

import json
from pathlib import Path

TARGET_VERSION = 5
LOSSY = (
    "sets Notebook Navigator to open today's daily note on startup and to "
    "follow the Daily notes settings for which note that is — replacing any "
    "other homepage the owner had chosen there"
)

NN_RELPATH = Path(".obsidian") / "plugins" / "notebook-navigator" / "data.json"
HOMEPAGE = {"source": "daily-note", "file": None, "createMissingPeriodicNote": False}
CALENDAR_INTEGRATION = "daily-notes"


class MigrationError(Exception):
    """The Navigator settings file does not parse."""


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{path.as_posix()} is not readable JSON ({exc}) — fix or delete "
            "it (the template refresh restores the Navigator settings) and "
            "re-run") from exc
    if not isinstance(data, dict):
        raise MigrationError(f"{path.as_posix()} is not a JSON object")
    return data


def apply(root: Path) -> dict:
    nn = Path(root) / NN_RELPATH
    if not nn.is_file():
        return {"navigator": "skipped: no data.json"}
    before = nn.read_text(encoding="utf-8")
    data = _load(nn)
    data["homepage"] = dict(HOMEPAGE)
    data["calendarIntegrationMode"] = CALENDAR_INTEGRATION
    nn.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    return {"navigator": "unchanged" if nn.read_text(encoding="utf-8") == before
            else "merged"}


def verify(root: Path) -> dict:
    nn = Path(root) / NN_RELPATH
    if not nn.is_file():
        return {"checked": []}
    data = _load(nn)
    if data.get("homepage") != HOMEPAGE:
        raise MigrationError(f"{NN_RELPATH.as_posix()}: homepage is {data.get('homepage')!r}")
    if data.get("calendarIntegrationMode") != CALENDAR_INTEGRATION:
        raise MigrationError(f"{NN_RELPATH.as_posix()}: calendarIntegrationMode is "
                             f"{data.get('calendarIntegrationMode')!r}")
    return {"checked": [NN_RELPATH.as_posix()]}
