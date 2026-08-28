"""TDD for plugin/lib/instantiate_vault.py — the /provision-vault skill's
copy primitive.

The happy-path tests build against the real plugin/template/ tree (same
pattern as test_make_test_vault.py's use of the shipped template): a
synthetic fixture would defeat the point of testing the actual copy this
module ships to run. The guardrail tests that need to force a bad state
(a stale structure-version, a missing .obsidian/) use a synthetic template
instead, via the injectable template_root parameter — mutating the real
shipped template just to exercise a failure path would be worse than not
testing it.
"""
import json
from pathlib import Path

import pytest

import instantiate_vault
from instantiate_vault import EXPECTED_STRUCTURE_VERSION, InstantiateError, instantiate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"


def make_fake_template(tmp_path, *, structure_version=EXPECTED_STRUCTURE_VERSION,
                        with_obsidian=True, with_claude=True) -> Path:
    src = tmp_path / "fake-template"
    src.mkdir()
    (src / "CLAUDE.md").write_text("stub\n", encoding="utf-8")
    (src / "structure-version").write_text(f"{structure_version}\n", encoding="utf-8")
    if with_obsidian:
        (src / ".obsidian").mkdir()
        (src / ".obsidian" / "app.json").write_text("{}\n", encoding="utf-8")
    if with_claude:
        (src / "claude" / "skills").mkdir(parents=True)
    return src


# --- Happy path, against the real shipped template ---


def test_happy_path_instantiates_the_real_template(tmp_path):
    target = tmp_path / "vault"
    result = instantiate(target)
    assert result["obsidian_present"] is True
    assert result["structure_version"] == EXPECTED_STRUCTURE_VERSION
    assert (target / "CLAUDE.md").is_file()


def test_dotfile_directory_arrives(tmp_path):
    """The exact risk PR-1 flagged: a naive copy can silently drop
    dotfiles. shutil.copytree does not, but this locks it as a regression
    test rather than trusting that forever."""
    target = tmp_path / "vault"
    instantiate(target)
    assert (target / ".obsidian" / "app.json").is_file()
    assert (target / ".obsidian" / "core-plugins.json").is_file()


def test_existing_empty_target_is_accepted(tmp_path):
    target = tmp_path / "vault"
    target.mkdir()
    result = instantiate(target)
    assert result["obsidian_present"] is True


def test_default_template_root_is_this_plugins_own_template(tmp_path):
    """TEMPLATE_ROOT must resolve relative to this file, not the caller's
    cwd or the repo root — that is the whole point of shipping this module
    inside plugin/lib/ for a zero-checkout provisioning path."""
    assert instantiate_vault.TEMPLATE_ROOT == TEMPLATE


# --- Guardrail: refuse a non-empty target ---


def test_non_empty_target_is_refused(tmp_path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "existing.txt").write_text("already here\n", encoding="utf-8")
    with pytest.raises(InstantiateError, match="already exists and is not empty"):
        instantiate(target)
    # The refusal must not have touched what was already there.
    assert (target / "existing.txt").is_file()
    assert not (target / ".obsidian").exists()


def test_non_empty_target_that_is_a_file_is_refused(tmp_path):
    target = tmp_path / "vault"
    target.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(InstantiateError, match="already exists and is not empty"):
        instantiate(target)


# --- Guardrail: verify the copy actually landed ---


def test_stale_structure_version_is_refused(tmp_path):
    src = make_fake_template(tmp_path, structure_version="1")
    target = tmp_path / "vault"
    with pytest.raises(InstantiateError, match="structure-version"):
        instantiate(target, template_root=src)


def test_missing_structure_version_file_is_refused(tmp_path):
    src = make_fake_template(tmp_path)
    (src / "structure-version").unlink()
    target = tmp_path / "vault"
    with pytest.raises(InstantiateError, match="structure-version"):
        instantiate(target, template_root=src)


def test_missing_obsidian_directory_is_refused(tmp_path):
    src = make_fake_template(tmp_path, with_obsidian=False)
    target = tmp_path / "vault"
    with pytest.raises(InstantiateError, match=r"\.obsidian"):
        instantiate(target, template_root=src)


# --- The .claude -> claude symlink ---


def test_symlink_created_on_success(tmp_path):
    src = make_fake_template(tmp_path)
    target = tmp_path / "vault"
    result = instantiate(target, template_root=src)
    assert result["symlink"] == "created"
    assert (target / ".claude").is_symlink()


def test_symlink_failure_is_reported_not_raised(tmp_path, monkeypatch):
    """A Windows machine with no Developer Mode and no elevated shell is an
    expected, recoverable case — it must come back as a warning in the
    result, not blow up the whole provisioning run."""
    src = make_fake_template(tmp_path)
    target = tmp_path / "vault"

    def raise_oserror(*_args, **_kwargs):
        raise OSError("symbolic link privilege not held")

    monkeypatch.setattr(instantiate_vault.os, "symlink", raise_oserror)
    result = instantiate(target, template_root=src)
    assert result["symlink"].startswith("failed — ")
    assert "privilege" in result["symlink"]
    # The rest of the vault is still complete — only the symlink is missing.
    assert result["obsidian_present"] is True
    assert not (target / ".claude").exists()


def test_symlink_skipped_without_a_claude_directory(tmp_path):
    src = make_fake_template(tmp_path, with_claude=False)
    target = tmp_path / "vault"
    result = instantiate(target, template_root=src)
    assert result["symlink"].startswith("skipped")


# --- The CLI's JSON envelope ---


def test_cli_reports_ok_true_json(tmp_path, capsys):
    target = tmp_path / "vault"
    exit_code = instantiate_vault.main([str(target)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"]["obsidian_present"] is True


def test_cli_reports_ok_false_json_on_refusal(tmp_path, capsys):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "x.txt").write_text("x", encoding="utf-8")
    exit_code = instantiate_vault.main([str(target)])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "already exists and is not empty" in payload["error"]
    assert payload["hint"]
