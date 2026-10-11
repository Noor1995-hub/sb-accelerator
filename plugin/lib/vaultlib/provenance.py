"""CLI-owned vault provenance: 99-workflow-config/provenance.json.

Provenance lives in a sibling file, not in config.json — config._validate is
strict and on every skill's hot path, a hash table there would echo ~34
digests into every `config read`, and a pre-feature vault has neither key.
`read()` returning None for an absent file is the honest bootstrap state.

Hash = sha256 of bytes after \\r\\n -> \\n normalisation, applied identically
to shipped and vault bytes, so a Windows plugin cache or a Mac<->Windows sync
does not make every file look changed.

This module only writes `events` (append-only) and `template_files`
(rebaseline/record_provision). The managed-file tiers, `template.status`,
and `template.refresh` are a later PR (#117) built on top of this one — the
shape here (dotted event kinds, `structure_version` / `from_structure_version`
/ `refreshed` / `restored` keys) already leaves room for it.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
import json
from pathlib import Path
from typing import Optional

from . import vault

PROVENANCE_RELPATH = Path("99-workflow-config") / "provenance.json"
PROVENANCE_VERSION = 1
CLAUDE_LINK_NAME = ".claude"

# Resolved relative to this file, the same pattern migrate.py uses for
# MIGRATIONS_DIR: plugin/lib/vaultlib/provenance.py -> parents[2] is plugin/,
# so this is plugin/template regardless of whether this module is running
# from a repo checkout or a plugin cache.
TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "template"


class ProvenanceError(Exception):
    """A provenance.json this module cannot trust, CLI-owned — the caller
    restores it from a snapshot or deletes it to start from an unknown
    baseline. Never raised by anything that must not fail a provision or a
    migration run; those call sites catch it themselves."""


def digest(data: bytes) -> str:
    """sha256 hex digest, after CRLF -> LF normalisation."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def template_digest(rel) -> str:
    """digest() of the shipped template's own bytes for a relpath."""
    return digest((TEMPLATE_ROOT / str(rel)).read_bytes())


def vault_digest(root: Path, rel) -> str:
    """digest() of the vault's current bytes for a relpath.

    Raises OSError (FileNotFoundError included) exactly like read_bytes()
    would — callers that need "missing" to mean "skip this one" catch it
    themselves; this function does not paper over that distinction.
    """
    return digest((Path(root) / str(rel)).read_bytes())


def _now_iso() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _empty() -> dict:
    return {"provenance-version": PROVENANCE_VERSION, "events": [],
            "template_files": {}}


def _write(root: Path, data: dict) -> None:
    vault.atomic_write(root / PROVENANCE_RELPATH,
                       json.dumps(data, indent=2, sort_keys=True) + "\n")


def read(root: Path) -> Optional[dict]:
    """The parsed provenance.json, or None when the vault predates it.

    Malformed (bad JSON, wrong shape, an unsupported provenance-version)
    raises ProvenanceError rather than guessing — this file is CLI-owned,
    so anything wrong with it is either a hand-edit or corruption, not a
    shape this module should try to repair silently.
    """
    path = root / PROVENANCE_RELPATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProvenanceError(
            f"{PROVENANCE_RELPATH.as_posix()} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ProvenanceError(
            f"{PROVENANCE_RELPATH.as_posix()} must hold a JSON object")
    if data.get("provenance-version") != PROVENANCE_VERSION:
        raise ProvenanceError(
            f"{PROVENANCE_RELPATH.as_posix()} provenance-version "
            f"{data.get('provenance-version')!r} is not the supported "
            f"version {PROVENANCE_VERSION} — this plugin cannot read it")
    events = data.get("events")
    if not isinstance(events, list) or not all(
            isinstance(event, dict) for event in events):
        raise ProvenanceError(
            f"{PROVENANCE_RELPATH.as_posix()} is missing a valid events "
            "list — every entry must be an object")
    template_files = data.get("template_files")
    if not isinstance(template_files, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in template_files.items()):
        raise ProvenanceError(
            f"{PROVENANCE_RELPATH.as_posix()} is missing a valid "
            "template_files object — every value must be a string digest")
    return data


def record_event(root: Path, event: str, *, at: Optional[str] = None,
                  structure_version=None, **extra) -> dict:
    """Append one event. events is append-only; template_files is untouched.

    `at` defaults to now (UTC, second precision, Z-suffixed) — tests pass
    it explicitly to stay deterministic.
    """
    data = read(root)
    if data is None:
        data = _empty()
    entry = {"event": event, "at": at or _now_iso(),
             "plugin_version": vault.plugin_version()}
    if structure_version is not None:
        entry["structure_version"] = str(structure_version)
    entry.update(extra)
    data["events"].append(entry)
    _write(root, data)
    return entry


def rebaseline(root: Path, relpaths) -> dict:
    """Record the current vault digest for each relpath, but only where it
    equals the shipped template's bytes — "a value is only ever written when
    the vault copy is known to equal the shipped copy at that moment". A
    missing vault file or one that differs from the template is reported in
    `skipped`, never written and never raised.
    """
    data = read(root)
    if data is None:
        data = _empty()
    baselined, skipped = [], []
    for rel in relpaths:
        rel = str(rel)
        try:
            v_digest = vault_digest(root, rel)
        except OSError:
            skipped.append(rel)
            continue
        if v_digest == template_digest(rel):
            data["template_files"][rel] = v_digest
            baselined.append(rel)
        else:
            skipped.append(rel)
    _write(root, data)
    return {"baselined": baselined, "skipped": skipped}


def rename_template_file(root: Path, old: str, new: str) -> bool:
    """Move a recorded baseline from `old` to `new` when a shipped template
    file is renamed and the vault's copy with it, so the next template status
    sees the same file under its new name instead of one `missing` and one
    unknown. The digest is of the bytes, not the name, so it carries over. A
    vault without provenance or without a record for `old` is left alone; a
    record already under `new` wins. Returns whether anything was written.
    """
    data = read(root)
    if data is None or old not in data["template_files"]:
        return False
    recorded = data["template_files"].pop(old)
    data["template_files"].setdefault(new, recorded)
    _write(root, data)
    return True


def record_provision(root: Path, template_root, at: Optional[str] = None) -> str:
    """Called in-process right after instantiate()'s structure-version
    check, and by make_test_vault.build_vault(). Walks every file under
    `template_root` (the same root the caller just copied from — passed in
    rather than read from the module constant, so a synthetic template used
    by a guardrail test is honoured too), records a digest for every one
    whose vault copy already matches, and appends a `provision` event.

    Never raises: a provenance failure must never fail a provision. The
    caller reports the returned string under a `"provenance"` result key —
    either the provenance.json relpath on success, or `"failed — <reason>"`.
    """
    try:
        template_root = Path(template_root)
        data = read(root)
        if data is None:
            data = _empty()
        for path in sorted(template_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(template_root).as_posix()
            shipped_digest = digest(path.read_bytes())
            try:
                current_digest = vault_digest(root, rel)
            except OSError:
                continue
            if current_digest == shipped_digest:
                data["template_files"][rel] = current_digest
        structure_version = vault.structure_version(root)
        entry = {"event": "provision", "at": at or _now_iso(),
                 "plugin_version": vault.plugin_version(),
                 "structure_version": str(structure_version)}
        data["events"].append(entry)
        _write(root, data)
        return PROVENANCE_RELPATH.as_posix()
    except Exception as exc:  # noqa: BLE001 — never raises, by design
        return f"failed — {exc}"


def _parse_version(value) -> Optional[tuple]:
    if value is None:
        return None
    try:
        return tuple(int(part) for part in str(value).split("."))
    except ValueError:
        return None


def compare_versions(recorded, running) -> str:
    """Dotted-int compare: `behind` = tune-up pending (the vault's recorded
    plugin is older than the one running now); `ahead` = this machine's
    plugin cache is stale relative to what last wrote the vault; `unknown`
    when either side does not parse as dotted integers."""
    parsed_recorded, parsed_running = _parse_version(recorded), _parse_version(running)
    if parsed_recorded is None or parsed_running is None:
        return "unknown"
    if parsed_recorded == parsed_running:
        return "matches"
    return "behind" if parsed_recorded < parsed_running else "ahead"


def drift(data: Optional[dict]) -> str:
    """compare_versions(the last event's plugin_version, the running plugin)
    — the one place `provenance read`'s CLI dispatch and health's
    `_provenance_block` both derive plugin drift from, so a future reader
    of either cannot compute it differently. `data` is what `read()`
    returns: `None` (no provenance.json yet) and an events list with no
    plugin_version to read both fold to "unknown", same as
    `compare_versions` does for either side failing to parse.
    """
    if not data:
        return "unknown"
    events = data.get("events") or []
    recorded_version = events[-1].get("plugin_version") if events else None
    if recorded_version is None:
        return "unknown"
    return compare_versions(recorded_version, vault.plugin_version())


def claude_link_state(root: Path) -> dict:
    """Whether `.claude` is the intended relative symlink to `claude/`.

    `is_symlink: False` + `state: "directory"` is the OneDrive-copy case —
    a sync client that materialises the symlink target as a real directory
    copy instead of preserving the link. This module only reports it; it is
    never repaired automatically.
    """
    link = Path(root) / CLAUDE_LINK_NAME
    if link.is_symlink():
        return {"is_symlink": True, "state": "symlink"}
    if link.is_dir():
        return {"is_symlink": False, "state": "directory"}
    if link.exists():
        return {"is_symlink": False, "state": "other"}
    return {"is_symlink": False, "state": "missing"}
