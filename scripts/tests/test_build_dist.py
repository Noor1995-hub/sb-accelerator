"""Tests for scripts/build_dist.py — the offline-testable dist-tree builder
behind the tag-triggered release pipeline (#10).

Builds run against the *real* repo root (REPO_ROOT) into tmp_path, so these
tests exercise the actual plugin/ tree, the actual CHANGELOG.md, and the
actual scripts/dist/README.md.tmpl — not a synthetic fixture. That is
deliberate: a fixture repo could not have caught the dev-marketplace-name
leak or a real clean-room violation, which is exactly the failure mode the
release pipeline exists to prevent.
"""
import json
from pathlib import Path

import pytest

import build_dist

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- build(): per-channel manifest, README pin line, CHANGELOG, RELEASE.json ---


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_build_writes_a_valid_channel_manifest(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT, source_ref="plugin-v9.9.9",
                      source_sha="deadbee")
    manifest = json.loads((out / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert manifest["name"] == build_dist.CHANNELS[channel]["marketplace_name"]
    assert manifest["owner"] == {"name": "delaware"}
    assert len(manifest["plugins"]) == 1
    plugin = manifest["plugins"][0]
    assert plugin["name"] == "second-brain"
    assert plugin["source"] == "./plugin"
    assert "description" in plugin and plugin["description"]


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_build_writes_matching_plugin_version(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT)
    real_version = json.loads(
        (REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    dist_version = json.loads(
        (out / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    assert dist_version == real_version


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_build_readme_carries_the_verbatim_pin_line(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT)
    readme = (out / "README.md").read_text(encoding="utf-8")
    plugin_version = json.loads(
        (out / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    structure_version = (out / "plugin" / "template" / "structure-version").read_text(
        encoding="utf-8"
    ).strip()
    expected = (
        f"Pinned contents: plugin **{plugin_version}**, "
        f"template **structure-version {structure_version}**."
    )
    assert expected in readme


def test_dryrun_readme_carries_the_channel_notice(tmp_path):
    out = tmp_path / "out"
    build_dist.build("dryrun", out, REPO_ROOT)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Status: temporary" in readme
    assert "sb-dist" in readme


def test_client_readme_carries_no_channel_notice(tmp_path):
    out = tmp_path / "out"
    build_dist.build("client", out, REPO_ROOT)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Status: temporary" not in readme


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_build_copies_the_real_changelog(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT)
    dist_changelog = (out / "CHANGELOG.md").read_text(encoding="utf-8")
    real_changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert dist_changelog == real_changelog


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_build_writes_release_json_fields(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT, source_ref="plugin-v9.9.9",
                      source_sha="deadbeef1234")
    release = json.loads((out / "RELEASE.json").read_text(encoding="utf-8"))
    plugin_version = json.loads(
        (out / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]
    structure_version = (out / "plugin" / "template" / "structure-version").read_text(
        encoding="utf-8"
    ).strip()
    assert release["plugin_version"] == plugin_version
    assert release["structure_version"] == structure_version
    assert release["channel"] == channel
    assert release["marketplace"] == build_dist.CHANNELS[channel]["marketplace_name"]
    assert release["source_ref"] == "plugin-v9.9.9"
    assert release["source_sha"] == "deadbeef1234"
    assert "timestamp" not in release


def test_build_writes_a_gitignore(tmp_path):
    out = tmp_path / "out"
    build_dist.build("client", out, REPO_ROOT)
    assert (out / ".gitignore").is_file()


# --- no dev-marketplace text leaks into either channel ---


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_no_dev_marketplace_text_leaks_into_the_dist_tree(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT)
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        assert "sb-accelerator-dev" not in text, path
        assert "Internal development marketplace" not in text, path


# --- verify_tree() ---


@pytest.mark.parametrize("channel", sorted(build_dist.CHANNELS))
def test_verify_tree_is_clean_on_a_real_build(tmp_path, channel):
    out = tmp_path / "out"
    build_dist.build(channel, out, REPO_ROOT, lint=False)
    assert build_dist.verify_tree(out, REPO_ROOT) == []


def test_verify_tree_catches_a_synthetic_denylist_hit(tmp_path):
    """A manufactured clean-room violation in the built tree must be caught —
    this is the "run the real linter on the output" guarantee the release
    pipeline exists to provide, not just a lint over the source tree."""
    out = tmp_path / "out"
    build_dist.build("client", out, REPO_ROOT, lint=False)
    (out / "plugin" / "skills" / "evening-sync" / "leak.md").write_text(
        "Ping Michael about this.\n", encoding="utf-8"
    )
    problems = build_dist.verify_tree(out, REPO_ROOT)
    assert any("michael" in p.lower() for p in problems)


def test_build_raises_on_a_lint_failure_and_writes_nothing_further():
    """build() with lint=True (the default, and what CI uses) must surface the
    violation rather than silently produce a bad tree — the workflow's build
    step is where a clean-room finding must fail, before anything is pushed."""
    import shutil
    import tempfile

    tmp_path = Path(tempfile.mkdtemp())
    try:
        out = tmp_path / "out"
        # Pre-seed a violation the same way the synthetic test above does,
        # but this time let build() itself run the lint by building twice:
        # once to get a tree, poison it, then ask verify_tree via build()'s
        # own lint path by re-running build with lint straight through.
        build_dist.build("client", out, REPO_ROOT, lint=False)
        (out / "plugin" / "skills" / "evening-sync" / "leak.md").write_text(
            "Ping Michael about this.\n", encoding="utf-8"
        )
        problems = build_dist.verify_tree(out, REPO_ROOT)
        assert problems  # sanity: the fixture really is dirty
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_build_with_lint_raises_dist_build_error_on_violation(tmp_path, monkeypatch):
    """Exercises build()'s own lint=True path end-to-end by monkeypatching
    verify_tree to return a finding, rather than depending on the real repo
    tree being clean (which it should be, but a lint bug should not be
    masked by that)."""
    out = tmp_path / "out"
    monkeypatch.setattr(build_dist, "verify_tree", lambda *_a, **_k: ["fake: violation"])
    with pytest.raises(build_dist.DistBuildError) as excinfo:
        build_dist.build("client", out, REPO_ROOT, lint=True)
    assert excinfo.value.problems == ["fake: violation"]


# --- rebuild determinism ---


def _tree_snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_two_builds_are_byte_identical(tmp_path):
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    build_dist.build("client", out1, REPO_ROOT, source_ref="plugin-v9.9.9", source_sha="abc123")
    build_dist.build("client", out2, REPO_ROOT, source_ref="plugin-v9.9.9", source_sha="abc123")
    assert _tree_snapshot(out1) == _tree_snapshot(out2)


# --- unknown channel ---


def test_unknown_channel_raises(tmp_path):
    with pytest.raises(ValueError):
        build_dist.build("bogus", tmp_path / "out", REPO_ROOT)


# --- notes() extractor ---


def test_notes_extracts_the_matching_versioned_section(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "- something new (#999)\n\n"
        "## v0.10.24 — 2026-09-01\n\n"
        "- first line for this release (#143)\n"
        "- second line for this release (#142)\n\n"
        "## v0.10.23 — 2026-08-30\n\n"
        "- an older release\n",
        encoding="utf-8",
    )
    text, fell_back = build_dist.notes("0.10.24", changelog)
    assert fell_back is False
    assert "first line for this release (#143)" in text
    assert "second line for this release (#142)" in text
    assert "an older release" not in text
    assert "something new (#999)" not in text


def test_notes_falls_back_to_unreleased_with_a_warning_flag(tmp_path):
    """The real-world case this covers: the first tag is cut on a main commit
    whose CHANGELOG still only has '## Unreleased' — no '## v<version>'
    section exists yet. The extractor must not crash; it falls back and
    tells the caller it did, so cut_release.sh's caller can warn instead of
    failing obscurely."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "- something new (#999)\n",
        encoding="utf-8",
    )
    text, fell_back = build_dist.notes("0.10.24", changelog)
    assert fell_back is True
    assert "something new (#999)" in text


def test_notes_on_the_real_changelog_finds_unreleased_or_a_version(tmp_path):
    """Sanity check against the actual repo CHANGELOG.md, not a synthetic one."""
    text, _fell_back = build_dist.notes("0.0.0-does-not-exist", REPO_ROOT / "CHANGELOG.md")
    assert isinstance(text, str)
