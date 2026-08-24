"""Structural checks on SKILL.md files.

lint_plugin.py already covers frontmatter and the clean-room denylist. These
cover the contract between a skill and the CLI it calls: a skill that
references a subcommand that does not exist fails at the worst possible
moment, in front of a client.
"""
import re
from pathlib import Path

import pytest

from vaultlib import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "plugin" / "skills"

SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))
# Skills invoke the CLI through the $VAULTLIB convention rather than repeating
# the path, so match either form: `cli.py <group> <action>` or
# `"$VAULTLIB" <group> <action>`.
INVOCATION_RE = re.compile(r'(?:cli\.py|\$\{?VAULTLIB\}?)"?\s+([a-z-]+)\s+([a-z-]+)')


def known_subcommands() -> set:
    """(group, action) pairs the CLI actually implements."""
    parser = cli.build_parser()
    pairs = set()
    for action in parser._subparsers._group_actions[0].choices.items():
        group, sub = action
        nested = sub._subparsers
        if nested is None:
            continue
        for name in nested._group_actions[0].choices:
            pairs.add((group, name))
    return pairs


def test_expected_skills_exist():
    # Each skill task appends its own name here as it lands, so this test is
    # always satisfiable by the task that touches it.
    names = {path.parent.name for path in SKILL_FILES}
    assert {"new-project", "update-entity", "log-decision",
            "sync-recordings"} <= names


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_records_provenance(path):
    head = path.read_text(encoding="utf-8").split("---")[1]
    assert "upstreamed-from: busdev@" in head, (
        f"{path.parent.name}: ported skills record upstreamed-from in frontmatter"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_states_its_surface_requirement(path):
    text = path.read_text(encoding="utf-8")
    assert "Cowork" in text and "Claude Code" in text, (
        f"{path.parent.name}: must state that writes need Cowork or Claude Code — "
        "plugins do not load in Chat, so the skill has to say so rather than fail"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_cli_invocation_named_by_a_skill_exists(path):
    implemented = known_subcommands()
    text = path.read_text(encoding="utf-8")
    referenced = set(INVOCATION_RE.findall(text))
    assert referenced, f"{path.parent.name}: no CLI invocation found"
    unknown = referenced - implemented
    assert not unknown, (
        f"{path.parent.name} references subcommands the CLI does not implement: "
        f"{sorted(unknown)}"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_does_not_instruct_hand_written_frontmatter(path):
    text = path.read_text(encoding="utf-8").lower()
    for phrase in ("write the frontmatter", "emit the following frontmatter",
                   "create the file with this frontmatter"):
        assert phrase not in text, (
            f"{path.parent.name}: writes go through the CLI, never model-authored "
            "frontmatter — that is the whole point of the deterministic layer"
        )


def test_plugin_claude_md_documents_interpreter_resolution():
    # Assert the fallback SEQUENCE, not three presence checks: "python" is a
    # substring of "python3", so a presence check on it can never fail
    # independently and the test claims coverage it does not have.
    text = (REPO_ROOT / "plugin" / "CLAUDE.md").read_text(encoding="utf-8")
    parts = text.split("## Interpreter resolution", 1)
    assert len(parts) == 2, "plugin/CLAUDE.md has no Interpreter resolution section"
    section = parts[1].split("\n## ", 1)[0]
    chain = re.findall(r"`(python3|python|py -3)`", section)
    assert chain[:3] == ["python3", "python", "py -3"], (
        "plugin/CLAUDE.md must document the interpreter fallback chain in "
        "order: a clean Mac has no real python3 and Windows python3 is often a "
        f"Store alias stub. Found {chain[:3]}"
    )


def test_log_decision_documents_both_modes():
    text = (SKILLS_DIR / "log-decision" / "SKILL.md").read_text(encoding="utf-8")
    assert "--foreground" in text and "--background" in text, (
        "the mode flag is the interface #16's evening run calls; both halves "
        "have to be written down"
    )


def test_log_decision_forbids_prompting_in_background_mode():
    # The lab's production failure: an unattended run that asks a question
    # exits having done nothing.
    text = (SKILLS_DIR / "log-decision" / "SKILL.md").read_text(encoding="utf-8")
    assert "never ask" in text.lower() or "never prompt" in text.lower(), (
        "background mode must state that it never blocks on a prompt"
    )


def test_plugin_claude_md_documents_the_bare_stem_boundary():
    text = (REPO_ROOT / "plugin" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "bare" in text.lower() and "supersedes" in text, (
        "the wikilink-never-crosses-the-boundary rule belongs next to the "
        "pipe-escaping rule — they are the same lesson twice"
    )
