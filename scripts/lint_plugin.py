#!/usr/bin/env python3
"""Skill frontmatter lint + clean-room scan for plugin/, template/, and fixtures/.

Three jobs:
1. Every plugin/skills/*/SKILL.md has YAML frontmatter with name (matching its
   directory), description, and user_invocable: true.
2. No denylisted term (scripts/cleanroom-denylist.txt, case-insensitive
   substrings) appears in any text file under plugin/, template/, or
   fixtures/ — the clean-room rule from CLAUDE.md. plugin/ and template/
   ship to clients; fixtures/ never ships but must stay just as clean.
3. No prose in those same trees names a slash command that is not a shipped
   skill. `/morning-brief` outlived the skill it named in
   template/Start here.md (#84): the skill was removed on purpose — tomorrow's
   note *is* the morning brief — and nothing tied the orientation note to the
   shipped skill list. The vault owner's first act on day one was to type the
   one command that note put in bold and get nothing back.

Exemption: for the "busdev" term only, the matched `upstreamed-from:\\s*busdev@`
span (case-insensitive) is stripped from the line before checking — the
provenance convention documented in plugin/skills/README.md. This is a
per-occurrence exemption, not a whole-line one: any other "busdev" mention
riding along on the same line still flags, as do other terms on that line and
bare "busdev" anywhere else (including filenames).

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import json
import re
import sys
from pathlib import Path

import yaml

PROVENANCE_RE = re.compile(r"upstreamed-from:\s*busdev@", re.IGNORECASE)

# A slash command as this repo's prose writes it: backtick, slash, name,
# backtick. Both anchors carry weight, and the CLOSING one is the whole
# false-positive defence — `/Users/owner/vault` and `70-resources/attachments`
# have another segment after the name, so paths never match and no exclusion
# list is needed. Digits are IN the class: a future `/sync-m365` must be
# checked, not silently exempted (the same hazard test_skill_contracts.py
# warns about on CLI invocations). The first character is a letter, so a
# backticked folder written with a leading slash is not read as a command.
SLASH_COMMAND_RE = re.compile(r"`/([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`")

# config.json's _readme is prose inside JSON strings, where the backtick
# convention does not apply — its references are bare. So: require at least one
# hyphen, and forbid a preceding word char / slash / dot / backtick and a
# following word char / hyphen / slash. That triple guard is what rejects
# `Europe/Brussels`, `50-people/`, `(owner/name)` and any multi-segment path.
BARE_COMMAND_RE = re.compile(r"(?<![\w/`.])/([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?![\w/-])")

SHIPPED_TREES = ("plugin", "template", "fixtures")


def load_denylist(root: Path) -> list[str]:
    path = root / "scripts" / "cleanroom-denylist.txt"
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def shipped_skills(root: Path) -> set[str]:
    """Skill names as Claude Code discovers them: directory names under
    plugin/skills that hold a SKILL.md.

    plugin.json carries no skill list, so the filesystem IS the manifest.
    Kept separate from lint_skills(), which needs the directories *without* a
    SKILL.md so it can report them."""
    skills_dir = root / "plugin" / "skills"
    if not skills_dir.is_dir():
        return set()
    return {d.name for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()}


def lint_skills(root: Path) -> list[str]:
    problems = []
    skills_dir = root / "plugin" / "skills"
    if not skills_dir.is_dir():
        return problems
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        rel = skill_md.relative_to(root)
        if not skill_md.is_file():
            problems.append(f"{d.relative_to(root)}: missing SKILL.md")
            continue
        fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if fm is None:
            problems.append(f"{rel}: missing or unparseable YAML frontmatter")
            continue
        if fm.get("name") != d.name:
            problems.append(f"{rel}: frontmatter name {fm.get('name')!r} != directory name {d.name!r}")
        if not fm.get("description"):
            problems.append(f"{rel}: frontmatter missing description")
        if fm.get("user_invocable") is not True:
            problems.append(f"{rel}: frontmatter missing user_invocable: true")
    return problems


def scan_cleanroom(root: Path, terms: list[str]) -> list[str]:
    problems = []
    for tree in SHIPPED_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            # Filename check runs for every file, binary or text — a client
            # slug or name in a filename is a clean-room violation regardless
            # of whether the file's content can be decoded as text.
            for term in terms:
                if term in path.name.lower():
                    problems.append(f"{path.relative_to(root)}: clean-room violation in filename: {term!r}")
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue  # binary — filename already checked above
            for i, line in enumerate(text.splitlines(), 1):
                lower_line = line.lower()
                # Strip only the matched provenance span before checking the
                # "busdev" term, so an unrelated "busdev" elsewhere on the
                # same line still flags — a per-occurrence exemption, not a
                # whole-line one.
                busdev_haystack = PROVENANCE_RE.sub("", line).lower()
                for term in terms:
                    haystack = busdev_haystack if term == "busdev" else lower_line
                    if term in haystack:
                        problems.append(
                            f"{path.relative_to(root)}:{i}: clean-room violation: {term!r}"
                        )
    return problems


def scan_skill_references(root: Path, shipped: set[str]) -> list[str]:
    """No prose that ships may name a slash command that is not a shipped skill.

    Covers plugin/ as well as template/ and fixtures/: a SKILL.md pointing at a
    deleted sibling skill is the same defect one step further from the vault
    owner.
    Directories named .obsidian are skipped — machine config, not prose.

    Known boundaries, all deliberate:

    - An un-backticked reference in markdown is invisible. Dropping the
      backtick anchor would start matching filesystem paths, and every
      reference in these trees observes the convention.
    - docs/, playbooks/, CHANGELOG.md and the repo-root CLAUDE.md are out of
      scope. They legitimately name `/visual-check`, `/process-upstream` and
      `/tmp`, and CHANGELOG entries must stay free to name retired commands.
    - With no skill inventory at all the check returns nothing rather than
      flagging every reference, so the linter still works on a partial tree.
      That hole is closed by test_skill_contracts.py::test_expected_skills_exist,
      which asserts the nine names against the real repo in every pytest job.
    """
    if not shipped:
        return []
    inventory = ", ".join(sorted(shipped))
    problems = []
    for tree in SHIPPED_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            # Relative to root, not path.parts: a checkout that happens to sit
            # inside a directory named .obsidian would otherwise skip the lot.
            rel = path.relative_to(root)
            if ".obsidian" in rel.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                for name in SLASH_COMMAND_RE.findall(line):
                    if name not in shipped:
                        problems.append(
                            f"{rel}:{i}: names /{name}, which is not a shipped "
                            f"skill — shipped skills: {inventory}")
            if path.name == "config.json":
                problems.extend(_scan_config_readme(text, rel, shipped, inventory))
    return problems


def _scan_config_readme(text: str, rel: Path, shipped: set[str],
                        inventory: str) -> list[str]:
    """The vault config's _readme is the one prose surface where the backtick
    convention does not apply, so it gets the bare form. Scanned per value
    rather than per line: the value index is the actionable anchor, and parsing
    keeps the loose regex away from the rest of the file."""
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError:
        return []  # validate_template.py owns reporting an unparseable config
    if not isinstance(cfg, dict):
        return []
    readme = cfg.get("_readme")
    values = readme if isinstance(readme, list) else [readme]
    problems = []
    for idx, value in enumerate(values):
        if not isinstance(value, str):
            continue
        for name in BARE_COMMAND_RE.findall(value):
            if name not in shipped:
                problems.append(
                    f"{rel} (_readme[{idx}]): names /{name}, which is not a "
                    f"shipped skill — shipped skills: {inventory}")
    return problems


def main(root: Path) -> list[str]:
    return (lint_skills(root)
            + scan_cleanroom(root, load_denylist(root))
            + scan_skill_references(root, shipped_skills(root)))


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
