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


def test_atomic_create_writes_when_the_target_is_free(tmp_path):
    target = tmp_path / "20-meetings" / "note.md"
    vault.atomic_create(target, "first\n")
    assert target.read_text(encoding="utf-8") == "first\n"


def test_atomic_create_refuses_an_existing_target(tmp_path):
    """Two concurrent writers that both saw no file must not last-write-wins
    each other — the loser gets FileExistsError, the winner's bytes stay."""
    target = tmp_path / "note.md"
    vault.atomic_create(target, "first\n")
    with pytest.raises(FileExistsError):
        vault.atomic_create(target, "second\n")
    assert target.read_text(encoding="utf-8") == "first\n"
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


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


CONTEXT_TEMPLATE = """# Role

> **Placeholder.** Filled by the onboarding interview (`/setup-my-brain`).

## Interview questions

- What do you own?

## Content

<!-- setup-my-brain:begin -->
<!-- setup-my-brain:end -->
"""


def _write_context(root, stem, text=CONTEXT_TEMPLATE):
    path = root / "99-workflow-config" / "context" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_write_context_block_replaces_only_the_fenced_region(tmp_path):
    root = make_vault(tmp_path)
    path = _write_context(root, "role-and-responsibilities")
    before = path.read_text(encoding="utf-8")
    result = vault.write_context_block(
        root, "role-and-responsibilities", "Owns commercial strategy.")
    after = path.read_text(encoding="utf-8")
    assert "Owns commercial strategy." in after
    # every byte outside the markers is preserved exactly
    begin, end = "<!-- setup-my-brain:begin -->", "<!-- setup-my-brain:end -->"
    assert after.split(begin)[0] == before.split(begin)[0]
    assert after.split(end)[1] == before.split(end)[1]
    assert vault.read_context_block(root, "role-and-responsibilities") \
        == "Owns commercial strategy."


def test_write_context_block_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    path = _write_context(root, "identity")
    vault.write_context_block(root, "identity", "Alex Doe, CEO.")
    once = path.read_text(encoding="utf-8")
    vault.write_context_block(root, "identity", "Alex Doe, CEO.")
    assert path.read_text(encoding="utf-8") == once


def test_write_context_block_refuses_marker_in_content(tmp_path):
    root = make_vault(tmp_path)
    _write_context(root, "identity")
    with pytest.raises(vault.VaultError):
        vault.write_context_block(
            root, "identity", "x\n<!-- setup-my-brain:end -->\ny")


def test_write_context_block_unknown_stem_and_missing_markers(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(vault.VaultError):
        vault.write_context_block(root, "shopping-list", "x")
    _write_context(root, "identity", "# Identity\n\nno markers here\n")
    with pytest.raises(vault.VaultError):
        vault.write_context_block(root, "identity", "x")
