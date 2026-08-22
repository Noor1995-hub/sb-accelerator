"""Tests build against the real template/ and fixtures/demo-vault/ trees,
same pattern as test_lint_plugin.py's use of the shipped denylist — a
synthetic fixture tree would defeat the point of testing the actual
instantiation."""
from pathlib import Path

import pytest

from make_test_vault import TargetNotEmptyError, build_vault, main

REPO_ROOT = Path(__file__).resolve().parents[2]


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
