"""Tests build against the real plugin/template/ and fixtures/demo-vault/ trees,
same pattern as test_lint_plugin.py's use of the shipped denylist — a
synthetic fixture tree would defeat the point of testing the actual
instantiation."""
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path

import pytest

from make_test_vault import TargetNotEmptyError, build_vault, main
from redate import discover_anchor, weekday_aligned_shift
from test_instantiate_vault import chmod_tree, user_writable_paths
from vaultlib import provenance

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"


def _symlinks_supported() -> bool:
    """Whether this platform lets us create a symlink at all.

    Windows refuses os.symlink without Developer Mode or elevation, which is
    the default on a CI runner. build_vault degrades to a warning there — the
    behaviour test_symlink_failure_degrades_to_warning already covers — so the
    link's own assertions have nothing to say and must skip rather than fail.
    """
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink("target", Path(tmp) / "probe")
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


SYMLINKS_SUPPORTED = _symlinks_supported()


def test_fresh_copies_template_only(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "CLAUDE.md").is_file()
    assert not (target / "40-entities" / "nordbridge-components").exists()


def test_fresh_records_provenance_for_all_46_template_files(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    data = provenance.read(target)
    assert data is not None
    assert data["events"][-1]["event"] == "provision"
    assert len(data["template_files"]) == 46


def test_default_overlay_still_records_provenance_for_unchanged_files(tmp_path):
    """The demo fixture overlays some template files (identity.md, for
    instance) with different bytes — those are simply absent from
    template_files, never a reason to fail the whole record."""
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    data = provenance.read(target)
    assert data is not None
    assert data["events"][-1]["event"] == "provision"
    # Meetings.base is untouched by the demo overlay (a Base file, not a
    # fixture-owned markdown note), so it still matches the template.
    assert "20-meetings/Meetings.base" in data["template_files"]


def test_demo_day_builds_record_identical_provenance_bytes(tmp_path):
    """Round-2 review fix: two --demo-day builds of the same day must be
    byte-identical everywhere, including provenance.json — that invariant
    is what test_redate.py::test_determinism_same_demo_day_same_output
    checks. record_provision()'s "at" is pinned to midnight UTC on the demo
    day itself rather than left at the wall-clock default, so it no longer
    differs between two builds run moments apart."""
    demo_day = date(2026, 9, 10)
    target_a = tmp_path / "vault-a"
    target_b = tmp_path / "vault-b"
    build_vault(target_a, REPO_ROOT, fresh=False, demo_day=demo_day)
    build_vault(target_b, REPO_ROOT, fresh=False, demo_day=demo_day)

    provenance_relpath = Path("99-workflow-config") / "provenance.json"
    bytes_a = (target_a / provenance_relpath).read_bytes()
    bytes_b = (target_b / provenance_relpath).read_bytes()
    assert bytes_a == bytes_b

    data = provenance.read(target_a)
    assert data["events"][-1]["at"] == "2026-09-10T00:00:00Z"


def test_without_demo_day_provenance_carries_a_wall_clock_timestamp(tmp_path):
    """The non-demo-day path is unpinned on purpose — nothing else about
    that build is deterministic either, so provenance's "at" should keep
    reading as a real, current wall-clock timestamp rather than a frozen
    stand-in that would misrepresent when the vault was actually built."""
    before = provenance._now_iso()
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    after = provenance._now_iso()

    data = provenance.read(target)
    at = data["events"][-1]["at"]
    assert at.endswith("Z")
    assert before <= at <= after


def test_default_overlays_fixtures(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    assert (target / "CLAUDE.md").is_file()
    assert (target / "40-entities" / "nordbridge-components" / "dossier.md").is_file()
    identity_text = (target / "99-workflow-config" / "context" / "identity.md").read_text()
    assert "Placeholder." not in identity_text
    assert "Morgan Ellery" in identity_text


def test_read_only_template_source_yields_a_writable_dev_vault(tmp_path):
    """Same copytree, same inherited modes as instantiate_vault.py (#163):
    a checkout or cache presenting 0o500/0o400 must not produce a test
    vault nobody can write into. Built against a scratch repo root whose
    plugin/template is a read-only copy of the shipped one."""
    fake_repo = tmp_path / "repo"
    fake_template = fake_repo / "plugin" / "template"
    shutil.copytree(REPO_ROOT / "plugin" / "template", fake_template)
    chmod_tree(fake_template, 0o500, 0o400)
    target = tmp_path / "vault"
    try:
        warnings = build_vault(target, fake_repo, fresh=True)
        assert user_writable_paths(target) == []
        (target / "99-workflow-config" / "note.md").write_text("a note\n")
        assert not any("provenance" in w for w in warnings)
    finally:
        # Restore before pytest's retained tmp dir has to be removed —
        # Windows refuses to unlink a read-only file.
        chmod_tree(fake_repo, 0o700, 0o600)
        if target.is_dir():
            chmod_tree(target, 0o700, 0o600)


def test_refuses_nonempty_target(tmp_path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "existing-file.txt").write_text("don't touch me\n")
    with pytest.raises(TargetNotEmptyError):
        build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "existing-file.txt").is_file()  # untouched


def test_target_created_when_missing(tmp_path):
    target = tmp_path / "nested" / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "CLAUDE.md").is_file()


def test_refuses_existing_file_target(tmp_path):
    target = tmp_path / "vault"
    target.write_text("a file, not a directory\n")
    with pytest.raises(TargetNotEmptyError):
        build_vault(target, REPO_ROOT, fresh=True)


def test_cli_refuses_nonempty_target(tmp_path, capsys):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "existing-file.txt").write_text("don't touch me\n")
    exit_code = main([str(target)])
    assert exit_code == 1
    assert "not empty" in capsys.readouterr().err


def test_cli_default_mode_reports_fixtures(tmp_path, capsys):
    target = tmp_path / "vault"
    exit_code = main([str(target)])
    assert exit_code == 0
    assert "demo fixtures" in capsys.readouterr().out
    assert (target / "40-entities").is_dir()


def test_cli_fresh_mode_reports_template_only(tmp_path, capsys):
    target = tmp_path / "vault"
    exit_code = main([str(target), "--fresh"])
    assert exit_code == 0
    assert "template-only" in capsys.readouterr().out
    # 40-entities/ itself ships with the template (Entities.base) — only the
    # fixture overlay content must be absent in --fresh mode.
    assert not (target / "40-entities" / "nordbridge-components").exists()


def test_with_plugins_flag_invokes_provisioner(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "make_test_vault.provision_into",
        lambda vault: calls.append(vault) or (["installed fake/main.js"], []),
    )
    target = tmp_path / "vault"
    exit_code = main([str(target), "--with-plugins"])
    assert exit_code == 0
    assert calls == [target.resolve()]
    assert "installed" in capsys.readouterr().out


def test_without_flag_provisioner_not_called(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "make_test_vault.provision_into",
        lambda vault: pytest.fail("provisioner must not run without --with-plugins"),
    )
    target = tmp_path / "vault"
    assert main([str(target)]) == 0


@pytest.mark.skipif(
    not SYMLINKS_SUPPORTED,
    reason="platform does not permit symlink creation (Windows without "
           "Developer Mode); build_vault degrades to a warning there",
)
def test_claude_symlink_created(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    link = target / ".claude"
    assert link.is_symlink(), ".claude symlink missing"
    assert os.readlink(link) == "claude", "symlink must be relative, pointing at claude/"
    assert (link / "skills").is_dir(), "symlink must resolve to the visible claude/ dir"


def test_symlink_failure_degrades_to_warning(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("symlinks not permitted")

    monkeypatch.setattr("make_test_vault.os.symlink", refuse)
    target = tmp_path / "vault"
    warnings = build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "CLAUDE.md").is_file()  # vault still built
    assert any(".claude" in w for w in warnings)


def test_cli_omitted_demo_day_leaves_fixtures_pristine(tmp_path, capsys):
    """--demo-day is opt-in (#91 controller ruling): the visual-check tier
    (obsidian_probe.provenance() + its basesim cross-check) needs the demo
    fixtures byte-pristine, so the default build must not re-date at all."""
    target = tmp_path / "vault"
    exit_code = main([str(target)])
    assert exit_code == 0
    note = target / "60-daily-notes" / "2026-06-15.md"
    original = FIXTURE_ROOT / "60-daily-notes" / "2026-06-15.md"
    assert note.is_file()
    assert note.read_bytes() == original.read_bytes()
    assert "demo day" not in capsys.readouterr().out  # nothing was re-dated


def test_cli_accepts_demo_day_flag(tmp_path):
    target = tmp_path / "vault"
    demo_day = date(2026, 9, 10)
    exit_code = main([str(target), "--demo-day", demo_day.isoformat()])
    assert exit_code == 0
    anchor = discover_anchor(FIXTURE_ROOT)
    _, recap_from = weekday_aligned_shift(anchor, demo_day)
    assert (target / "60-daily-notes" / f"{recap_from.isoformat()}.md").is_file()


def test_cli_echoes_demo_day_and_shift(tmp_path, capsys):
    target = tmp_path / "vault"
    exit_code = main([str(target), "--demo-day", "2026-09-10"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "2026-09-10" in out
    assert "demo day" in out


def test_cli_rejects_malformed_demo_day(tmp_path, capsys):
    target = tmp_path / "vault"
    with pytest.raises(SystemExit) as exc_info:
        main([str(target), "--demo-day", "nope"])
    # argparse type-conversion failures exit 2 and mention the flag on stderr.
    assert exc_info.value.code == 2
    assert "--demo-day" in capsys.readouterr().err


def test_cli_bare_demo_day_flag_uses_todays_date(tmp_path, monkeypatch):
    """--demo-day with no value (nargs="?") means "as if today were the demo
    day" — distinct from omitting the flag entirely, which means no
    re-dating at all (see test_cli_omitted_demo_day_leaves_fixtures_pristine)."""
    fixed_today = date(2026, 9, 10)

    class FixedDate(date):
        @classmethod
        def today(cls):
            return fixed_today

    monkeypatch.setattr("redate.date", FixedDate)
    target = tmp_path / "vault"
    exit_code = main([str(target), "--demo-day"])
    assert exit_code == 0
    anchor = discover_anchor(FIXTURE_ROOT)
    _, recap_from = weekday_aligned_shift(anchor, fixed_today)
    assert (target / "60-daily-notes" / f"{recap_from.isoformat()}.md").is_file()


def test_fresh_mode_never_calls_redate(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("redate_vault must not run in --fresh mode")

    monkeypatch.setattr("redate.redate_vault", fail)
    target = tmp_path / "vault"
    exit_code = main([str(target), "--fresh", "--demo-day", "2026-09-10"])
    assert exit_code == 0
