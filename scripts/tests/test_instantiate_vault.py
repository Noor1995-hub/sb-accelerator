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
import os
import shutil
import stat
from pathlib import Path

import pytest

import instantiate_vault
from instantiate_vault import (
    EXPECTED_STRUCTURE_VERSION, PROBE_RELPATH, InstantiateError, instantiate,
    make_user_writable)
from vaultlib import provenance

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"


def make_fake_template(tmp_path, *, structure_version=EXPECTED_STRUCTURE_VERSION,
                        with_obsidian=True, with_claude=True) -> Path:
    src = tmp_path / "fake-template"
    src.mkdir()
    (src / "CLAUDE.md").write_text("stub\n", encoding="utf-8")
    (src / "structure-version").write_text(f"{structure_version}\n", encoding="utf-8")
    (src / "99-workflow-config").mkdir()
    if with_obsidian:
        (src / ".obsidian").mkdir()
        (src / ".obsidian" / "app.json").write_text("{}\n", encoding="utf-8")
    if with_claude:
        (src / "claude" / "skills").mkdir(parents=True)
    return src


def chmod_tree(root: Path, dir_mode: int, file_mode: int) -> None:
    """chmod every directory and regular file under root (root included).
    Bottom-up, so restoring a read-only tree never has to list a directory
    it has just locked. Symlinks are skipped — chmod would follow them."""
    for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_symlink():
                path.chmod(file_mode)
        os.chmod(dirpath, dir_mode)


def user_writable_paths(root: Path) -> list:
    """Every directory and regular file under root (root included) whose
    mode lacks u+w, or — for directories — u+x. Empty means all good."""
    bad = []
    for dirpath, _dirnames, filenames in os.walk(root):
        mode = stat.S_IMODE(os.stat(dirpath).st_mode)
        if mode & 0o300 != 0o300:
            bad.append((dirpath, oct(mode)))
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            mode = stat.S_IMODE(path.stat().st_mode)
            if not mode & 0o200:
                bad.append((str(path), oct(mode)))
    return bad


@pytest.fixture
def read_only_template(tmp_path):
    """A fake template presenting exactly what Cowork's read-only plugin
    cache presents: 0o500 directories and 0o400 files. Modes are restored
    on teardown so pytest's retained tmp dirs stay removable (Windows
    refuses to unlink a read-only file)."""
    src = make_fake_template(tmp_path)
    chmod_tree(src, 0o500, 0o400)
    yield src
    chmod_tree(src, 0o700, 0o600)
    for leftover in tmp_path.iterdir():
        if leftover.is_dir() and not leftover.is_symlink():
            chmod_tree(leftover, 0o700, 0o600)


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


def test_happy_path_records_a_provision_event_for_all_34_shipped_files(tmp_path):
    target = tmp_path / "vault"
    result = instantiate(target)
    assert result["provenance"] == "99-workflow-config/provenance.json"
    data = provenance.read(target)
    assert data["events"][-1]["event"] == "provision"
    assert data["events"][-1]["structure_version"] == EXPECTED_STRUCTURE_VERSION
    assert len(data["template_files"]) == 34


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


# --- Guardrail: the vault must be writable (#163) ---


def test_copytree_alone_carries_read_only_modes_onto_the_copy(read_only_template, tmp_path):
    """The mechanism the guardrail exists for, pinned so the fixture is
    known to exercise it: copytree calls copystat on every directory and
    copy2 on every file, so a read-only source yields a read-only copy."""
    plain_copy = tmp_path / "plain-copy"
    shutil.copytree(read_only_template, plain_copy)
    assert user_writable_paths(plain_copy)


def test_read_only_template_yields_a_user_writable_vault(read_only_template, tmp_path):
    """Cowork's plugin cache is a read-only FUSE mount presenting 0o500
    directories and 0o400 files; before the fix the vault inherited them,
    provenance and the symlink both came back "failed — Permission denied",
    and the envelope still read ok: true over a vault nobody could add a
    note to."""
    target = tmp_path / "vault"
    result = instantiate(target, template_root=read_only_template)

    assert user_writable_paths(target) == []
    (target / "99-workflow-config" / "note.md").write_text("a note\n", encoding="utf-8")
    assert result["provenance"] == "99-workflow-config/provenance.json"
    assert result["symlink"] == "created"


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows has a single read-only attribute, no group/other bits: "
           "chmod(0o444) reads back as 0o666 once the attribute is cleared",
)
def test_normalisation_only_widens_the_user_bits(tmp_path):
    src = make_fake_template(tmp_path)
    (src / "CLAUDE.md").chmod(0o444)
    (src / ".obsidian").chmod(0o555)
    make_user_writable(src)
    assert stat.S_IMODE((src / "CLAUDE.md").stat().st_mode) & 0o077 == 0o044
    assert stat.S_IMODE((src / ".obsidian").stat().st_mode) & 0o077 == 0o055
    assert user_writable_paths(src) == []


def test_probe_file_does_not_survive_a_successful_run(tmp_path):
    target = tmp_path / "vault"
    instantiate(target)
    assert not (target / PROBE_RELPATH).exists()


def test_unwritable_target_is_refused(tmp_path, monkeypatch):
    """A target that still refuses writes after normalisation is exactly as
    broken as one missing .obsidian/: a refusal, not a soft warning."""
    src = make_fake_template(tmp_path)
    target = tmp_path / "vault"

    def refuse(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(instantiate_vault, "_probe_write", refuse)
    with pytest.raises(InstantiateError, match="not writable") as exc_info:
        instantiate(target, template_root=src)
    assert "99-workflow-config/.write-probe.tmp" in str(exc_info.value)
    assert "read-only plugin cache" in exc_info.value.hint
    # Refused before anything wrote: no provenance, no symlink.
    assert not (target / "99-workflow-config" / "provenance.json").exists()
    assert not (target / ".claude").exists()


def test_failed_normalisation_is_refused_not_a_traceback(tmp_path, monkeypatch):
    src = make_fake_template(tmp_path)
    target = tmp_path / "vault"

    def refuse(_root):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(instantiate_vault, "make_user_writable", refuse)
    with pytest.raises(InstantiateError, match="user-writable"):
        instantiate(target, template_root=src)


def test_cli_reports_ok_false_json_on_an_unwritable_target(tmp_path, capsys, monkeypatch):
    def refuse(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(instantiate_vault, "_probe_write", refuse)
    exit_code = instantiate_vault.main([str(tmp_path / "vault")])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "not writable" in payload["error"]
    assert "Permission denied" in payload["error"]
    assert "read-only plugin cache" in payload["hint"]
    assert "remove the partial copy" in payload["hint"]


# --- The .claude -> claude symlink ---


def test_symlink_created_on_success(tmp_path):
    src = make_fake_template(tmp_path)
    target = tmp_path / "vault"
    result = instantiate(target, template_root=src)
    assert result["symlink"] == "created"
    assert (target / ".claude").is_symlink()


def test_provenance_import_failure_is_reported_not_raised(tmp_path, monkeypatch):
    """Reviewer finding #3: a module-level `from vaultlib import provenance`
    would die with an import traceback (no ok envelope at all) if vaultlib
    were ever absent from a plugin cache. The import must happen inside
    instantiate()'s provenance step, so a failure lands in record_provision's
    own never-raises "failed — ..." path instead of killing the primitive."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "vaultlib":
            raise ImportError("vaultlib package is missing from this plugin cache")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    target = tmp_path / "vault"

    result = instantiate(target)

    assert result["provenance"].startswith("failed — ")
    assert "missing from this plugin cache" in result["provenance"]
    # The rest of the vault is still complete — only provenance is missing.
    assert result["obsidian_present"] is True
    assert (target / "CLAUDE.md").is_file()


def test_provenance_recorded_against_an_injected_template_root(tmp_path):
    """record_provision must use the passed-in template_root, not the
    module default — the same guardrail contract as the copy itself."""
    src = make_fake_template(tmp_path)
    target = tmp_path / "vault"
    result = instantiate(target, template_root=src)
    assert result["provenance"] == "99-workflow-config/provenance.json"
    data = provenance.read(target)
    assert set(data["template_files"]) == {
        "CLAUDE.md", "structure-version", ".obsidian/app.json"}


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
