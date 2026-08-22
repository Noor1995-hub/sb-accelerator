"""Tests build a fake repo tree in tmp_path and run the linter's main() against it."""
from pathlib import Path

from lint_plugin import load_denylist, main, scan_cleanroom

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "plugin" / "skills").mkdir(parents=True)
    (tmp_path / "template").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "cleanroom-denylist.txt").write_text(
        "# comment\nmichael\nbusdev\n", encoding="utf-8"
    )
    return tmp_path


def write_skill(root: Path, dirname: str, frontmatter: str, body: str = "Body.") -> None:
    d = root / "plugin" / "skills" / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}---\n\n{body}\n", encoding="utf-8")


def test_empty_plugin_passes(tmp_path):
    assert main(make_repo(tmp_path)) == []


def test_valid_skill_passes(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\ndescription: Checks vault health. Triggers when user invokes /health-check.\nuser_invocable: true\n")
    assert main(root) == []


def test_missing_frontmatter_fails(tmp_path):
    root = make_repo(tmp_path)
    d = root / "plugin" / "skills" / "broken"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("No frontmatter here.\n", encoding="utf-8")
    problems = main(root)
    assert any("broken" in p and "frontmatter" in p for p in problems)


def test_name_mismatch_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: wrong-name\ndescription: X.\nuser_invocable: true\n")
    problems = main(root)
    assert any("name" in p for p in problems)


def test_missing_description_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\nuser_invocable: true\n")
    problems = main(root)
    assert any("description" in p for p in problems)


def test_cleanroom_violation_in_plugin_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(root, "health-check", "name: health-check\ndescription: X.\nuser_invocable: true\n", body="Ping Michael when done.")
    problems = main(root)
    assert any("michael" in p.lower() for p in problems)


def test_cleanroom_violation_in_template_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "template" / "CLAUDE.md").write_text("Sync with busdev daily.\n", encoding="utf-8")
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


def test_cleanroom_scan_skips_binary_and_comments(tmp_path):
    root = make_repo(tmp_path)
    (root / "plugin" / "logo.png").write_bytes(b"\x89PNG\x00michael\x00")
    assert main(root) == []


# --- Ruling A: filename check must run for binary files too. ---


def test_binary_filename_violation_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "plugin" / "michael-logo.png").write_bytes(b"\x89PNG\x00binary-payload\x00")
    problems = main(root)
    assert any(
        "michael" in p.lower() and "filename" in p.lower() for p in problems
    )


# --- Ruling B: narrow provenance allowlist for the `busdev` term. ---


def test_upstreamed_from_busdev_provenance_passes(tmp_path):
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\nupstreamed-from: busdev@abc1234\n",
    )
    assert main(root) == []


def test_bare_busdev_elsewhere_still_fails(tmp_path):
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\n",
        body="Copied from busdev repo.",
    )
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


def test_provenance_line_with_extra_busdev_mention_still_flags(tmp_path):
    """The per-line provenance exemption must only cover the matched
    `upstreamed-from: busdev@...` span, not the whole line — an unrelated
    "busdev" mention riding along on the same line must still flag."""
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\n"
        "upstreamed-from: busdev@abc123  # copied from busdev/clients/acme.md\n",
    )
    problems = main(root)
    assert any("busdev" in p.lower() for p in problems)


# --- Finding 1 (final review): the shipped denylist must catch the accented surname. ---


def test_shipped_denylist_catches_accented_surname(tmp_path):
    """Locks scripts/cleanroom-denylist.txt itself: "bulthe" (plain e) does not
    match "Bulthé" (accented é) as a substring, so the real denylist needs its
    own accented entry. Runs scan_cleanroom with terms loaded from the actual
    shipped denylist file, not the slimmed-down fixture in make_repo()."""
    root = make_repo(tmp_path)
    write_skill(
        root,
        "health-check",
        "name: health-check\ndescription: X.\nuser_invocable: true\n",
        body="Ping Bulthé when done.",
    )
    real_terms = load_denylist(REPO_ROOT)
    problems = scan_cleanroom(root, real_terms)
    assert any("bulth" in p.lower() for p in problems)
