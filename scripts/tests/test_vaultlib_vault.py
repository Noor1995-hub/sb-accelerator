"""Filesystem access. Every test builds its own vault under tmp_path, because
the real vault root is a mount point in Cowork and must never be inferred."""
import pytest

from vaultlib import vault

IDENTITY = """# Identity

## Content

<!-- setup-my-brain:begin -->
Morgan Ellery — goes by Morgan. Chief Commercial Officer at Cascadia
Intermodal Group.
<!-- setup-my-brain:end -->
"""


def make_vault(tmp_path, identity_text=IDENTITY):
    root = tmp_path / "vault"
    for folder in ("10-inbox", "20-meetings", "30-projects", "40-entities",
                   "50-people", "60-daily-notes"):
        (root / folder).mkdir(parents=True)
    context = root / "99-workflow-config" / "context"
    context.mkdir(parents=True)
    if identity_text is not None:
        (context / "identity.md").write_text(identity_text, encoding="utf-8")
    return root


def test_resolve_accepts_a_real_vault(tmp_path):
    root = make_vault(tmp_path)
    assert vault.resolve(str(root)) == root.resolve()


def test_resolve_rejects_a_missing_directory(tmp_path):
    with pytest.raises(vault.VaultError, match="does not exist"):
        vault.resolve(str(tmp_path / "nope"))


def test_resolve_rejects_a_directory_that_is_not_a_vault(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(vault.VaultError, match="does not look like a vault"):
        vault.resolve(str(plain))


def test_resolve_expands_a_user_path(tmp_path, monkeypatch):
    root = make_vault(tmp_path)
    # expanduser reads HOME on POSIX and USERPROFILE on Windows; set both so
    # the tilde lands in tmp_path on either platform.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert vault.resolve("~/vault") == root.resolve()


def test_atomic_write_creates_parents(tmp_path):
    target = tmp_path / "a" / "b" / "note.md"
    vault.atomic_write(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_atomic_write_uses_lf_even_on_windows(tmp_path):
    target = tmp_path / "note.md"
    vault.atomic_write(target, "one\ntwo\n")
    assert target.read_bytes() == b"one\ntwo\n"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "note.md"
    vault.atomic_write(target, "x\n")
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


def test_atomic_write_overwrites(tmp_path):
    target = tmp_path / "note.md"
    vault.atomic_write(target, "first\n")
    vault.atomic_write(target, "second\n")
    assert target.read_text(encoding="utf-8") == "second\n"


def test_read_identity_block_returns_the_delimited_content(tmp_path):
    root = make_vault(tmp_path)
    block = vault.read_identity_block(root)
    assert "Morgan Ellery" in block
    assert "setup-my-brain" not in block


def test_read_identity_block_returns_none_when_the_block_is_empty(tmp_path):
    root = make_vault(tmp_path, IDENTITY.replace(
        "Morgan Ellery — goes by Morgan. Chief Commercial Officer at Cascadia\n"
        "Intermodal Group.\n", ""))
    assert vault.read_identity_block(root) is None


def test_read_identity_block_returns_none_when_the_file_is_absent(tmp_path):
    root = make_vault(tmp_path, identity_text=None)
    assert vault.read_identity_block(root) is None


def test_today_iso_passes_through_an_explicit_date():
    assert vault.today_iso("2026-08-23") == "2026-08-23"


def test_today_iso_rejects_a_malformed_date():
    with pytest.raises(vault.VaultError, match="YYYY-MM-DD"):
        vault.today_iso("23-08-2026")


def test_today_iso_defaults_to_a_well_formed_date():
    assert len(vault.today_iso()) == 10


def test_list_dir_names_returns_only_directories(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c.md").write_text("x", encoding="utf-8")
    assert vault.list_dir_names(tmp_path) == ["a", "b"]


def test_list_dir_names_tolerates_a_missing_directory(tmp_path):
    assert vault.list_dir_names(tmp_path / "nope") == []
