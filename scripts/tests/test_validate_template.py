from pathlib import Path

from validate_template import main


def test_missing_template_dir_fails(tmp_path):
    problems = main(tmp_path)
    assert any("template" in p for p in problems)


def test_readme_only_template_passes(tmp_path):
    (tmp_path / "template").mkdir()
    (tmp_path / "template" / "README.md").write_text("stub", encoding="utf-8")
    assert main(tmp_path) == []


def test_populated_template_requires_markers(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    problems = main(tmp_path)
    assert any("CLAUDE.md" in p for p in problems)
    assert any("structure-version" in p for p in problems)


def test_populated_template_with_markers_passes(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    (t / "CLAUDE.md").write_text("vault instructions", encoding="utf-8")
    (t / "structure-version").write_text("1\n", encoding="utf-8")
    assert main(tmp_path) == []
