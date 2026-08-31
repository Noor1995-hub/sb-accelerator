"""Tests build against the real plugin/template/ and fixtures/demo-vault/ trees,
same pattern as test_lint_plugin.py's use of the shipped denylist — a
synthetic fixture tree would defeat the point of testing the actual
instantiation."""
import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

from make_test_vault import TargetNotEmptyError, build_vault, main
from redate import discover_anchor, weekday_aligned_shift

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


def test_default_overlays_fixtures(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    assert (target / "CLAUDE.md").is_file()
    assert (target / "40-entities" / "nordbridge-components" / "dossier.md").is_file()
    identity_text = (target / "99-workflow-config" / "context" / "identity.md").read_text()
    assert "Placeholder." not in identity_text
    assert "Morgan Ellery" in identity_text


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


def test_cli_default_demo_day_uses_todays_date(tmp_path, monkeypatch):
    fixed_today = date(2026, 9, 10)

    class FixedDate(date):
        @classmethod
        def today(cls):
            return fixed_today

    monkeypatch.setattr("redate.date", FixedDate)
    target = tmp_path / "vault"
    exit_code = main([str(target)])
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
