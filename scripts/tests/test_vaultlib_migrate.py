"""The migrate framework: discovery, status, snapshot, run, and the log.

Migrations ship inside the plugin, so fixtures build fake migration
directories in a tmp path and monkeypatch migrate.MIGRATIONS_DIR rather than
touching the real plugin/migrations/ tree.
"""
import textwrap

import pytest

from vaultlib import migrate, provenance, vault

from test_vaultlib_vault import make_vault


def write_migration(dirpath, number, slug, target, body_marker, lossy=None,
                    fail_apply=False, fail_verify=False, needs_human=()):
    mdir = dirpath / f"{number:03d}-{slug}"
    mdir.mkdir(parents=True)
    (mdir / "migrate.py").write_text(textwrap.dedent(f"""\
        from pathlib import Path
        TARGET_VERSION = {target}
        LOSSY = {lossy!r}
        def apply(root):
            if {fail_apply}:
                raise RuntimeError("boom")
            (root / "{body_marker}").write_text("done", encoding="utf-8")
            return {{"marker": "{body_marker}",
                     "needs_human": {list(needs_human)!r}}}
        def verify(root):
            if {fail_verify}:
                raise ValueError("two notes still carry tags")
            assert (root / "{body_marker}").is_file()
            return {{"checked": 1}}
        """), encoding="utf-8")
    return mdir


@pytest.fixture
def migrations_dir(tmp_path, monkeypatch):
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mdir)
    return mdir


def versioned_vault(tmp_path, version="1"):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text(f"{version}\n", encoding="utf-8")
    return root


def test_status_lists_pending_in_order(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1", lossy="drops a field")
    write_migration(migrations_dir, 2, "second", 3, "m2")
    root = versioned_vault(tmp_path)
    result = migrate.status(root)
    assert result["structure_version"] == 1
    assert result["expected_version"] == 3
    assert [p["slug"] for p in result["pending"]] == ["first", "second"]
    assert result["pending"][0]["lossy"] == "drops a field"


def test_run_applies_pending_snapshots_first_bumps_and_logs(tmp_path,
                                                            migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    root = versioned_vault(tmp_path)
    result = migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    assert result["structure_version"] == 2
    assert [a["slug"] for a in result["applied"]] == ["first"]
    assert (root / "99-workflow-config" / "snapshots"
            / "vault-2026-08-25-101500.zip").is_file()
    assert vault.structure_version(root) == "2"
    log = (root / "99-workflow-config" / "migration-log.md") \
        .read_text(encoding="utf-8")
    assert "v1→v2" in log and "vault-2026-08-25-101500.zip" in log
    # re-run: nothing pending, no second snapshot
    again = migrate.run(root, "2026-08-25", stamp="2026-08-25-102000")
    assert again["applied"] == [] and again["snapshot"] is None
    assert not (root / "99-workflow-config" / "snapshots"
                / "vault-2026-08-25-102000.zip").exists()


def test_run_appends_an_upgrade_provenance_event(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    write_migration(migrations_dir, 2, "second", 3, "m2")
    root = versioned_vault(tmp_path, version="1")
    result = migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    assert result["provenance"] == provenance.PROVENANCE_RELPATH.as_posix()
    data = provenance.read(root)
    assert data["events"][-1]["event"] == "upgrade"
    assert data["events"][-1]["structure_version"] == "3"
    assert data["events"][-1]["from_structure_version"] == "1"


def test_run_with_nothing_pending_never_touches_provenance(tmp_path, migrations_dir):
    root = versioned_vault(tmp_path)
    result = migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    assert result["applied"] == []
    assert "provenance" not in result
    assert provenance.read(root) is None


def test_run_reports_a_provenance_failure_without_failing_the_migration(
        tmp_path, migrations_dir, monkeypatch):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    root = versioned_vault(tmp_path)

    def boom(*_args, **_kwargs):
        raise provenance.ProvenanceError("provenance.json is not valid JSON")

    monkeypatch.setattr(migrate.provenance, "record_event", boom)
    result = migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    assert result["structure_version"] == 2
    assert [a["slug"] for a in result["applied"]] == ["first"]
    assert result["provenance"].startswith("failed: ")
    assert "not valid JSON" in result["provenance"]


def test_snapshot_rotation_keeps_three(tmp_path, migrations_dir):
    root = versioned_vault(tmp_path)
    snapdir = root / "99-workflow-config" / "snapshots"
    for stamp in ("2026-08-01-000000", "2026-08-02-000000",
                  "2026-08-03-000000"):
        migrate.snapshot(root, stamp)
    migrate.snapshot(root, "2026-08-04-000000")
    names = sorted(p.name for p in snapdir.glob("*.zip"))
    assert len(names) == 3 and "vault-2026-08-01-000000.zip" not in names


def test_snapshot_excludes_snapshots_dir(tmp_path, migrations_dir):
    import zipfile
    root = versioned_vault(tmp_path)
    migrate.snapshot(root, "2026-08-01-000000")
    path = migrate.snapshot(root, "2026-08-02-000000")
    with zipfile.ZipFile(root / path) as zf:
        assert not any("snapshots/" in n for n in zf.namelist())
        assert any(n.endswith("structure-version") for n in zf.namelist())


def test_failed_apply_stops_chain_and_logs_failure(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    write_migration(migrations_dir, 2, "boom", 3, "m2", fail_apply=True)
    root = versioned_vault(tmp_path)
    with pytest.raises(migrate.MigrateError):
        migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    # first landed, second did not, version reflects the stop point
    assert vault.structure_version(root) == "2"
    log = (root / "99-workflow-config" / "migration-log.md") \
        .read_text(encoding="utf-8")
    assert "FAILED" in log


def test_failed_verify_carries_needs_human_to_the_consultant(tmp_path,
                                                             migrations_dir):
    """apply builds the list of files a human has to fix; verify then refuses
    to pass the vault. Discarding the apply report on that path threw the list
    away, leaving the consultant the verify message and nothing to act on."""
    write_migration(migrations_dir, 1, "first", 2, "m1", lossy="drops a field")
    write_migration(migrations_dir, 2, "strict", 3, "m2", fail_verify=True,
                    needs_human=["30-projects/a/decisions/x.md: remove tags "
                                 "by hand"])
    root = versioned_vault(tmp_path)

    with pytest.raises(migrate.MigrateError) as excinfo:
        migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")

    error = excinfo.value
    assert error.needs_human == [
        "30-projects/a/decisions/x.md: remove tags by hand"]
    assert error.partial["apply"]["marker"] == "m2"
    assert [a["slug"] for a in error.applied] == ["first"]
    log = (root / "99-workflow-config" / "migration-log.md") \
        .read_text(encoding="utf-8")
    assert "FAILED" in log
    assert "30-projects/a/decisions/x.md" in log, "the log lost needs_human"


def test_failed_apply_has_no_partial_report(tmp_path, migrations_dir):
    """apply itself raising means there is no report at all — the error must
    say so rather than pretend an empty needs_human list is a clean bill."""
    write_migration(migrations_dir, 1, "boom", 2, "m1", fail_apply=True)
    root = versioned_vault(tmp_path)
    with pytest.raises(migrate.MigrateError) as excinfo:
        migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    assert excinfo.value.partial["apply"] is None
    assert excinfo.value.needs_human == []


def test_chain_gap_is_refused(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    write_migration(migrations_dir, 2, "skips", 4, "m2")
    root = versioned_vault(tmp_path)
    with pytest.raises(migrate.MigrateError):
        migrate.status(root)
