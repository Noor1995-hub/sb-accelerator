"""Vault structure migrations: snapshot, apply, verify, log.

Migrations ship inside the plugin (plugin/migrations/NNN-<slug>/migrate.py)
so they ride the marketplace update channel — plugin version <-> available
migrations is deterministic. Consultant-run via /upgrade-vault, never
unattended.
"""
from __future__ import annotations

import datetime as _datetime
import importlib.util
import re
import zipfile
from pathlib import Path

from vaultlib import provenance, vault

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
SNAPSHOT_DIR = Path("99-workflow-config") / "snapshots"
LOG_RELPATH = Path("99-workflow-config") / "migration-log.md"
KEEP_SNAPSHOTS = 3
_DIR_RE = re.compile(r"\A(\d{3})-([a-z0-9-]+)\Z")


class MigrateError(Exception):
    """A migration state or contract problem the caller must fix.

    A failure inside `run` carries what the run had collected when it stopped:

    - `applied` — the reports of the migrations that fully landed before it.
    - `partial` — the failing migration's own `apply` report, or `None` under
      the `"apply"` key when `apply` itself raised and there is no report.
    - `needs_human` — that report's per-file hints.

    Without these the consultant saw only the verify message. `apply` is the
    phase that knows *which files* it refused to touch and what to do about
    each, and the report holding that list was discarded on exactly the path
    where it matters. An empty `needs_human` is not a clean bill: check
    `partial["apply"]` for `None` first.
    """

    def __init__(self, message, *, applied=None, partial=None,
                 needs_human=None):
        super().__init__(message)
        self.applied = list(applied or [])
        self.partial = partial
        self.needs_human = list(needs_human or [])


def discover() -> list:
    """Every migration under MIGRATIONS_DIR, sorted by number.

    Non-directories (the README) are skipped by construction. A malformed
    directory name or a module missing the contract raises MigrateError
    naming the offending directory.
    """
    migrations = []
    for entry in sorted(MIGRATIONS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        match = _DIR_RE.match(entry.name)
        if not match:
            raise MigrateError(
                f"migration directory {entry.name!r} must be named NNN-slug")
        number, slug = int(match.group(1)), match.group(2)
        module_path = entry / "migrate.py"
        spec = importlib.util.spec_from_file_location(
            f"sb_migration_{number:03d}", module_path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — surfaced as MigrateError
            raise MigrateError(
                f"migration {entry.name} failed to load: {exc}") from exc
        if not isinstance(getattr(module, "TARGET_VERSION", None), int):
            raise MigrateError(
                f"migration {entry.name} must define an int TARGET_VERSION")
        if not callable(getattr(module, "apply", None)):
            raise MigrateError(
                f"migration {entry.name} must define a callable apply(root)")
        if not callable(getattr(module, "verify", None)):
            raise MigrateError(
                f"migration {entry.name} must define a callable verify(root)")
        if not hasattr(module, "LOSSY"):
            raise MigrateError(
                f"migration {entry.name} must define LOSSY (str or None)")
        migrations.append({
            "number": number, "slug": slug, "path": entry, "module": module,
        })
    migrations.sort(key=lambda m: m["number"])
    return migrations


def _current(root: Path) -> int:
    raw = vault.structure_version(root)
    try:
        return int(raw)
    except ValueError as exc:
        raise MigrateError(
            f"structure-version {raw!r} is not an integer") from exc


def status(root: Path) -> dict:
    current = _current(root)
    pending = [m for m in discover() if m["module"].TARGET_VERSION > current]
    expected = current
    previous = current
    entries = []
    for migration in pending:
        target = migration["module"].TARGET_VERSION
        if target != previous + 1:
            raise MigrateError(
                f"migration chain gap: expected TARGET_VERSION "
                f"{previous + 1}, got {target} in "
                f"{migration['number']:03d}-{migration['slug']}")
        entries.append({
            "number": migration["number"],
            "slug": migration["slug"],
            "target_version": target,
            "lossy": migration["module"].LOSSY,
        })
        previous = target
        expected = target
    return {
        "structure_version": current,
        "expected_version": expected,
        "pending": entries,
    }


def snapshot(root: Path, stamp: str) -> str:
    """Zip the vault (minus the snapshots dir itself) and rotate old ones.

    Returns the vault-relative path string of the new snapshot.
    """
    snapdir = root / SNAPSHOT_DIR
    snapdir.mkdir(parents=True, exist_ok=True)
    relpath = SNAPSHOT_DIR / f"vault-{stamp}.zip"
    zip_path = root / relpath
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in root.rglob("*"):
            if entry.is_dir():
                continue
            relative = entry.relative_to(root)
            if relative.is_relative_to(SNAPSHOT_DIR):
                continue
            zf.write(entry, arcname=relative.as_posix())
    existing = sorted(snapdir.glob("*.zip"), key=lambda p: p.name)
    for stale in existing[:-KEEP_SNAPSHOTS]:
        stale.unlink()
    return relpath.as_posix()


def _log(root: Path, today: str, from_v: int, to_v: int, snapshot_name: str,
          outcome: str) -> None:
    log_path = root / LOG_RELPATH
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8")
    else:
        text = "# Migration log\n\n"
    text += (f"- {today} · v{from_v}→v{to_v} · plugin "
             f"{vault.plugin_version()} · snapshot {snapshot_name} "
             f"· {outcome}\n")
    vault.atomic_write(log_path, text)


def run(root: Path, today: str, stamp: str = None) -> dict:
    result = status(root)
    pending = result["pending"]
    current = result["structure_version"]
    if not pending:
        return {"snapshot": None, "applied": [], "structure_version": current}

    stamp = stamp or _datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    snapshot_name = snapshot(root, stamp)
    applied = []
    from_version = current
    modules_by_number = {m["number"]: m["module"] for m in discover()}
    for entry in pending:
        number, slug, target = entry["number"], entry["slug"], entry["target_version"]
        module = modules_by_number[number]
        apply_report = None
        try:
            apply_report = module.apply(root)
            verify_report = module.verify(root)
            vault.atomic_write(root / "structure-version", f"{target}\n")
            _log(root, today, from_version, target, snapshot_name, "ok")
        except Exception as exc:  # noqa: BLE001 — logged then re-raised
            # The apply report is the only place the per-file hints exist, and
            # verify raising is the likeliest failure, so both the log line and
            # the error carry them. A consultant who lost them has a refusal
            # message and no list of what to fix.
            needs_human = list((apply_report or {}).get("needs_human") or [])
            outcome = f"FAILED: {exc}"
            if needs_human:
                outcome += " · needs a human: " + "; ".join(needs_human)
            _log(root, today, from_version, target, snapshot_name, outcome)
            # A migration earlier in this same chain may have already
            # bumped structure-version on disk before this one failed — in
            # its own try, same as the success path below, so a provenance
            # failure never masks the MigrateError about to be raised.
            # `applied` empty means nothing landed and structure-version
            # never moved, so no event is recorded in that case.
            if applied:
                try:
                    provenance.record_event(
                        root, "upgrade", structure_version=from_version,
                        from_structure_version=str(current))
                except Exception:  # noqa: BLE001 — never masks the re-raise below
                    pass
            raise MigrateError(
                f"migration {number:03d}-{slug} failed after snapshot "
                f"{snapshot_name}: {exc}",
                applied=applied,
                partial={"number": number, "slug": slug,
                         "target_version": target, "apply": apply_report},
                needs_human=needs_human) from exc
        applied.append({
            "number": number, "slug": slug, "target_version": target,
            "apply": apply_report, "verify": verify_report,
        })
        from_version = target

    result = {
        "snapshot": snapshot_name,
        "applied": applied,
        "structure_version": from_version,
    }
    # In its own try: a provenance failure (a malformed provenance.json, an
    # unwritable vault) must never turn a chain of migrations that already
    # landed into a reported migration failure. Reported under "provenance"
    # instead — "failed: ..." rather than record_provision's "failed — ...",
    # to read as "the migration ran; recording that it did, did not."
    try:
        provenance.record_event(root, "upgrade", structure_version=from_version,
                                from_structure_version=str(current))
        result["provenance"] = provenance.PROVENANCE_RELPATH.as_posix()
    except Exception as exc:  # noqa: BLE001 — never a migration failure
        result["provenance"] = f"failed: {exc}"
    return result
