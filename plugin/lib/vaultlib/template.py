"""Managed-file tiers, status, diff and refresh for the vault template.

Builds directly on `provenance.py` (#147/D4a) — this module never re-derives
a digest or writes `provenance.json` without going through it. Manifest =
static tiers here, hashes computed at runtime from the shipped tree
(`TEMPLATE_ROOT`, the same constant `provenance.py` resolves relative to
this package so a synthetic template used by a test is honoured too).

Four tiers, and every file under `plugin/template/` is in exactly one of
them (`test_every_shipped_file_is_classified_exactly_once` is the pin):

- `MANAGED_SILENT` — refreshed automatically when the vault's copy is
  unchanged since the last baseline: `.base` views, `.obsidian` settings a
  consultant would never hand-edit, the CSS snippet, and the three
  boilerplate READMEs.
- `MANAGED_CONSENT_ALWAYS` — a behavioural file (`CLAUDE.md`) or one whose
  rename empties a Base view (`ontology.md`); refresh never touches these
  without `--consent`, even when the vault's copy is untouched since the
  last baseline.
- `SEEDED_ONCE` — laid down once at provision and never refreshed again
  (`config.json`, `lessons.md`, the five `context/*.md`). The vault's own
  copy is authoritative from the moment it is provisioned, so this tier is
  outside `MANAGED` entirely: `status()` never lists one of these files (a
  consultant would otherwise see `config.json` and every `context/*.md`
  permanently stuck at `needs-consent`, since they are never expected to
  match the shipped default again) and `diff()`/`refresh()` both treat a
  seeded-once relpath as unmanaged. `refresh()` additionally names the tier
  explicitly in its own refusal message when one is passed via `--file`
  (defence in depth, in case a future caller builds its own selection
  straight from `tier_of()` rather than going through `status()`).
- `IGNORED` — Obsidian's own UI state, the structure-version marker, and
  every `.gitkeep`. Never reported, never refreshed.

`MANAGED` (this module's status()/refresh() surface) is `MANAGED_SILENT |
MANAGED_CONSENT_ALWAYS` — 19 files. `ALL_TIERED` (used only to pin that
every shipped file is classified exactly once) is `MANAGED | SEEDED_ONCE |
IGNORED` — all 35.
"""
from __future__ import annotations

import datetime as _datetime
import difflib
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from . import migrate, provenance, vault

# Resolved exactly like provenance.py's own TEMPLATE_ROOT (which this module
# reuses rather than re-deriving): plugin/lib/vaultlib/template.py ->
# parents[2] is plugin/, so this is plugin/template regardless of whether
# this module is running from a repo checkout or a plugin cache.
TEMPLATE_ROOT = provenance.TEMPLATE_ROOT

SNAPSHOT_DIR = Path("99-workflow-config") / "snapshots"
LOG_RELPATH = migrate.LOG_RELPATH
KEEP_SNAPSHOTS = 3

MANAGED_SILENT = frozenset({
    ".obsidian/app.json",
    ".obsidian/appearance.json",
    ".obsidian/community-plugins.json",
    ".obsidian/core-plugins.json",
    ".obsidian/daily-notes.json",
    ".obsidian/plugins/notebook-navigator/data.json",
    ".obsidian/plugins/obsidian-minimal-settings/data.json",
    ".obsidian/snippets/sb-accelerator.css",
    "10-inbox/README.md",
    "20-meetings/Meetings.base",
    "30-projects/Decisions.base",
    "30-projects/Projects.base",
    "40-entities/Entities.base",
    "50-people/People.base",
    "90-archive/README.md",
    "99-workflow-config/secrets/README.md",
    "Start here.md",
})

MANAGED_CONSENT_ALWAYS = frozenset({
    "CLAUDE.md",
    "99-workflow-config/reference/ontology.md",
})

SEEDED_ONCE = frozenset({
    "99-workflow-config/config.json",
    "99-workflow-config/context/communication-style.md",
    "99-workflow-config/context/identity.md",
    "99-workflow-config/context/preferences-and-constraints.md",
    "99-workflow-config/context/role-and-responsibilities.md",
    "99-workflow-config/context/tools-and-systems.md",
    "99-workflow-config/reference/lessons.md",
})

IGNORED = frozenset({
    ".obsidian/workspace.json",
    "60-daily-notes/.gitkeep",
    "70-resources/attachments/.gitkeep",
    "80-thoughts-ideas/.gitkeep",
    "95-private/.gitkeep",
    "_heavy-assets/.gitkeep",
    "_messages/.gitkeep",
    "claude/skills/.gitkeep",
    "structure-version",
})

MANAGED = MANAGED_SILENT | MANAGED_CONSENT_ALWAYS
ALL_TIERED = MANAGED | SEEDED_ONCE | IGNORED

_SELECTABLE_STATES = ("refresh", "needs-consent", "missing")


class TemplateError(Exception):
    """A template-refresh state or contract problem the caller must fix.

    Raised for: a relpath that is not a managed file at all, a managed
    relpath missing from the shipped template (a corrupt plugin cache), a
    seeded-once file named in a refresh selection (never refreshed, by
    design, not even with --consent), a blocked (not-a-regular-file)
    selection, and a needs-consent/missing selection without --consent.
    """


def tier_of(rel: str) -> Optional[str]:
    """One of "silent", "consent_always", "seeded_once", "ignored", or None
    when `rel` is not a recognised template relpath at all."""
    if rel in MANAGED_SILENT:
        return "silent"
    if rel in MANAGED_CONSENT_ALWAYS:
        return "consent_always"
    if rel in SEEDED_ONCE:
        return "seeded_once"
    if rel in IGNORED:
        return "ignored"
    return None


def _now_stamp() -> str:
    return _datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")


def _line_delta(vault_text: Optional[str], template_text: str) -> tuple:
    """(lines_added, lines_removed) a refresh from `vault_text` (None when
    the vault has no copy) to `template_text` would make, via each side's
    own line splitting (which already treats \\r\\n, \\r and \\n uniformly,
    so a CRLF vault copy is compared fairly).

    `SequenceMatcher.get_opcodes()` rather than `difflib.ndiff` (review
    finding #9, round 1): `status()` now runs this for every managed file on
    every `health report`, and `ndiff` is quadratic in the input size where
    `get_opcodes()`'s underlying comparison is not. Tallying opcodes gives
    the same two counts ndiff's "+ "/"- " prefixes did, over the same
    underlying comparison.
    """
    vault_lines = vault_text.splitlines() if vault_text is not None else []
    template_lines = template_text.splitlines()
    matcher = difflib.SequenceMatcher(a=vault_lines, b=template_lines)
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def _status_entry(root: Path, rel: str, tier: str, recorded: Optional[str]) -> dict:
    template_path = TEMPLATE_ROOT / rel
    if not template_path.is_file():
        raise TemplateError(
            f"managed file {rel!r} is missing from the shipped template — "
            "the plugin cache is corrupt")
    template_bytes = template_path.read_bytes()
    t_digest = provenance.digest(template_bytes)
    template_text = template_bytes.decode("utf-8", errors="replace")

    vault_path = Path(root) / rel
    entry = {
        "relpath": rel, "tier": tier, "lines_added": 0, "lines_removed": 0,
        "resets_column_widths": False,
    }

    if vault_path.exists() and not vault_path.is_file():
        entry.update(state="blocked", reason=None)
        return entry

    try:
        vault_bytes = vault_path.read_bytes()
    except OSError:
        vault_bytes = None

    if vault_bytes is None:
        entry.update(state="missing", reason=None)
        added, removed = _line_delta(None, template_text)
        entry["lines_added"], entry["lines_removed"] = added, removed
        return entry

    if rel.endswith(".base") and b"columnSize" in vault_bytes:
        entry["resets_column_widths"] = True

    v_digest = provenance.digest(vault_bytes)
    if v_digest == t_digest:
        entry.update(state="current",
                      reason="baseline_stale" if recorded != t_digest else None)
        return entry

    if recorded is None:
        state, reason = "needs-consent", "unknown-baseline"
    elif v_digest == recorded:
        state, reason = (("refresh", None) if tier == "silent"
                         else ("needs-consent", "consent-always"))
    else:
        state, reason = "needs-consent", "locally-edited"

    entry.update(state=state, reason=reason)
    vault_text = vault_bytes.decode("utf-8", errors="replace")
    added, removed = _line_delta(vault_text, template_text)
    entry["lines_added"], entry["lines_removed"] = added, removed
    return entry


def status(root) -> dict:
    """Per managed file: {relpath, state, reason, tier, lines_added,
    lines_removed, resets_column_widths}. Top level: {baseline, counts,
    files}. `baseline` is "recorded" once provenance.json exists at all
    (even with zero recorded template_files — every managed file simply
    reads unknown-baseline until its first refresh or rebaseline), else
    "unknown" for a vault that predates the feature entirely.
    """
    root = Path(root)
    data = provenance.read(root)
    baseline = "unknown" if data is None else "recorded"
    template_files = (data or {}).get("template_files", {})

    counts = {"current": 0, "refresh": 0, "needs-consent": 0,
              "missing": 0, "blocked": 0}
    files: List[dict] = []
    for rel in sorted(MANAGED):
        tier = tier_of(rel)
        entry = _status_entry(root, rel, tier, template_files.get(rel))
        counts[entry["state"]] += 1
        files.append(entry)
    return {"baseline": baseline, "counts": counts, "files": files}


def diff(root, rel: str) -> str:
    """Unified diff from the vault's current copy to the shipped template."""
    if rel not in MANAGED:
        raise TemplateError(f"not a managed template file: {rel}")
    template_path = TEMPLATE_ROOT / rel
    if not template_path.is_file():
        raise TemplateError(
            f"managed file {rel!r} is missing from the shipped template — "
            "the plugin cache is corrupt")
    template_text = template_path.read_text(encoding="utf-8", errors="replace")
    vault_path = Path(root) / rel
    if vault_path.exists() and not vault_path.is_file():
        raise TemplateError(f"{rel} is not a regular file in this vault (blocked)")
    vault_text = (vault_path.read_text(encoding="utf-8", errors="replace")
                  if vault_path.is_file() else "")
    lines = difflib.unified_diff(
        vault_text.splitlines(keepends=True),
        template_text.splitlines(keepends=True),
        fromfile=f"vault/{rel}", tofile=f"template/{rel}",
    )
    return "".join(lines)


def _log(root: Path, today: str, stamp: str, refreshed: int, restored: int,
          skipped: int) -> None:
    log_path = root / LOG_RELPATH
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8")
    else:
        text = "# Migration log\n\n"
    text += (f"- {today} · template-refresh {stamp} · plugin "
             f"{vault.plugin_version()} · refreshed {refreshed} · "
             f"restored {restored} · skipped {skipped}\n")
    vault.atomic_write(log_path, text)


def refresh(root, *, files: Optional[Iterable[str]] = None,
            all_pending: bool = False, consent: bool = False,
            today, stamp: Optional[str] = None) -> dict:
    """Replace managed files with the shipped template.

    Selection: default (files is None and not all_pending) = every file
    currently in state "refresh"; `files=[...]` = exactly those relpaths;
    `all_pending=True` = every file in state refresh, needs-consent, or
    missing. Any needs-consent/missing file in the selection without
    `consent=True` raises TemplateError naming them, and nothing is
    written. A seeded-once relpath anywhere in an explicit `files=[...]`
    selection is always refused — --consent cannot override it, because
    this tier is never refreshed, by design. A blocked (not-a-regular-file)
    selection is refused the same way.
    """
    root = Path(root)
    if files is not None and all_pending:
        raise TemplateError("pass --file or --all-pending, not both")

    current = status(root)
    by_rel = {entry["relpath"]: entry for entry in current["files"]}

    if files is not None:
        # Order-preserving de-dup, before any consent/blocked/unknown check
        # (review finding, round 2): --file is argparse action="append", so
        # `--file X --file X --consent` used to leave X twice in `selected`.
        # The write loop then ran twice for X — the second pass's backup
        # copy overwrote the first with the just-written template bytes
        # (breaking the backup guarantee), refreshed[]/the provenance event/
        # the log line all double-counted it, and a duplicated *missing*
        # file was restored in pass 1 then "backed up" (from its own
        # freshly-restored copy) in pass 2, arming rotation for a pure
        # restore that should never have created a snapshot dir at all.
        selected = list(dict.fromkeys(files))
        # Checked before the generic "unknown" test below, and by tier_of()
        # rather than by "in MANAGED" — MANAGED no longer contains
        # SEEDED_ONCE relpaths at all (#117 review finding #2), so without
        # this ordering a seeded-once file would fall into the generic
        # "not a managed template file" branch and lose the clearer,
        # tier-specific message. Kept even though `by_rel` alone would
        # already reject it, as defence in depth: `tier_of()` recognises
        # the tier independently of whatever `selected` was built from.
        seeded = [rel for rel in selected if tier_of(rel) == "seeded_once"]
        if seeded:
            raise TemplateError(
                "seeded-once files are never refreshed, with or without "
                "consent: " + ", ".join(sorted(seeded)))
        unknown = [rel for rel in selected if rel not in by_rel]
        if unknown:
            raise TemplateError(
                "not a managed template file: " + ", ".join(sorted(unknown)))
    elif all_pending:
        selected = [rel for rel, entry in by_rel.items()
                    if entry["state"] in _SELECTABLE_STATES]
    else:
        selected = [rel for rel, entry in by_rel.items()
                    if entry["state"] == "refresh"]

    blocked = sorted(rel for rel in selected if by_rel[rel]["state"] == "blocked")
    if blocked:
        raise TemplateError(
            "not a regular file in this vault (blocked): " + ", ".join(blocked))

    needing_consent = sorted(
        rel for rel in selected
        if by_rel[rel]["state"] in ("needs-consent", "missing"))
    if needing_consent and not consent:
        raise TemplateError(
            "consent required for: " + ", ".join(needing_consent))

    # Resolved once, before any write (review finding #7, round 1): a vault
    # missing the structure-version marker must fail here, not partway
    # through the write loop having already replaced some files.
    structure_version = vault.structure_version(root)

    write_rels = sorted(rel for rel in selected if by_rel[rel]["state"] != "current")
    selected_current_rels = sorted(
        rel for rel in selected if by_rel[rel]["state"] == "current")
    # The baseline_stale repair pass runs over every managed file, not just
    # `selected` (review finding #3, round 1): `selected` only ever contains
    # a "current" entry when a --file explicitly names one, so the default
    # (silent-refresh) and --all-pending selections never repaired a stale
    # baseline on a file that otherwise needed no content change at all.
    stale_rels = sorted(
        rel for rel, entry in by_rel.items()
        if entry["state"] == "current" and entry["reason"] == "baseline_stale")

    if not write_rels and not stale_rels:
        # Nothing to write and nothing to repair — a pure status check (or a
        # --file naming an already-current, non-stale file). RULING (review
        # finding #1, round 1): no backup dir, no provenance event, no
        # migration-log line. /upgrade-vault's step 5 runs this every visit;
        # without this early return, three no-op visits in a row would
        # rotate away the one real backup a genuinely edited file needed.
        return {
            "refreshed": [], "restored": [], "backup": None, "baselined": [],
            "skipped": [], "structure_version": structure_version,
        }

    today = vault.today_iso(today)
    stamp = stamp or _now_stamp()
    backup_relpath = SNAPSHOT_DIR / f"template-refresh-{stamp}"
    backup_dir = root / backup_relpath

    refreshed, restored = [], []
    # backup_dir is created lazily, on the first file that actually needs a
    # copy (review finding #1, round 1) — a selection made entirely of
    # `missing` files (pure restores) has nothing to back up, and creating
    # an empty backup dir just to rotate it away next run is the same bug
    # the no-op case above fixes, one level down.
    backed_up_anything = False
    for rel in write_rels:
        vault_path = root / rel
        if vault_path.is_file():
            if not backed_up_anything:
                backup_dir.mkdir(parents=True, exist_ok=True)
                backed_up_anything = True
            backup_target = backup_dir / rel
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vault_path, backup_target)
        template_bytes = (TEMPLATE_ROOT / rel).read_bytes()
        text = template_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
        vault.atomic_write(vault_path, text)
        if by_rel[rel]["state"] == "missing":
            restored.append(rel)
        else:
            refreshed.append(rel)
    skipped = selected_current_rels

    if backed_up_anything:
        # Filter to directories before rmtree (review finding #8, round 1):
        # glob("template-refresh-*") only ever matches directories this
        # module itself creates, but a hand-placed file of the same name
        # pattern must not make shutil.rmtree raise mid-rotation.
        existing_dirs = sorted(
            (p for p in (root / SNAPSHOT_DIR).glob("template-refresh-*") if p.is_dir()),
            key=lambda p: p.name)
        for stale in existing_dirs[:-KEEP_SNAPSHOTS]:
            shutil.rmtree(stale)

    rebaseline_targets = sorted(set(write_rels) | set(selected_current_rels)
                                | set(stale_rels))
    rebaseline_result = provenance.rebaseline(root, rebaseline_targets)
    provenance.record_event(
        root, "template-refresh", structure_version=structure_version,
        refreshed=len(refreshed), restored=len(restored))
    _log(root, today, stamp, len(refreshed), len(restored), len(skipped))

    return {
        "refreshed": sorted(refreshed),
        "restored": sorted(restored),
        "backup": backup_relpath.as_posix() if backed_up_anything else None,
        "baselined": rebaseline_result["baselined"],
        "skipped": sorted(skipped),
        "structure_version": structure_version,
    }
