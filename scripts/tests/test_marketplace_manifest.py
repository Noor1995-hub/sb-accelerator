"""The repo must be installable as a plugin marketplace.

Without a root .claude-plugin/marketplace.json neither Cowork nor Claude Code
can add this repo, and --plugin-dir does not exist in Cowork — so this file is
the only path to hand-testing the skills where they are meant to run.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_JSON = REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json"

# Anthropic's documented constraint on marketplace names.
NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
RESERVED_NAMES = {"unknown", "org", "org-provisioned"}


def load():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_exists_at_the_repo_root():
    assert MANIFEST.is_file(), (
        "missing .claude-plugin/marketplace.json — the repo is not installable "
        "as a marketplace without it"
    )


def test_name_satisfies_the_documented_pattern():
    name = load()["name"]
    assert NAME_RE.match(name), f"marketplace name {name!r} is not accepted"
    assert name not in RESERVED_NAMES


def test_owner_is_declared():
    assert load()["owner"]["name"]


def test_exactly_one_plugin_is_listed():
    assert len(load()["plugins"]) == 1


def test_plugin_source_is_a_relative_path_in_this_repo():
    source = load()["plugins"][0]["source"]
    assert isinstance(source, str) and source.startswith("./"), (
        "source must be a relative path — a plugin pointing at another "
        "repository is listed but never fetched or auto-installed"
    )
    assert (REPO_ROOT / source).is_dir()


def test_listed_plugin_name_matches_the_plugin_manifest():
    assert load()["plugins"][0]["name"] == json.loads(
        PLUGIN_JSON.read_text(encoding="utf-8"))["name"]


def test_the_referenced_plugin_carries_its_own_manifest():
    source = load()["plugins"][0]["source"]
    assert (REPO_ROOT / source / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_version_is_bumped_for_this_release():
    assert json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"] == "0.10.0"


def test_manifest_does_not_force_installation():
    # This is the internal/dev marketplace. Client-facing install preferences
    # belong to sb-dist and the client's own admin configuration (issue #10).
    assert "installationPreference" not in load()["plugins"][0]
