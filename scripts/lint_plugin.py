#!/usr/bin/env python3
"""Skill frontmatter lint + clean-room scan for plugin/, template/, and fixtures/.

Two jobs:
1. Every plugin/skills/*/SKILL.md has YAML frontmatter with name (matching its
   directory), description, and user_invocable: true.
2. No denylisted term (scripts/cleanroom-denylist.txt, case-insensitive
   substrings) appears in any text file under plugin/, template/, or
   fixtures/ — the clean-room rule from CLAUDE.md. plugin/ and template/
   ship to clients; fixtures/ never ships but must stay just as clean.

Exemption: for the "busdev" term only, the matched `upstreamed-from:\\s*busdev@`
span (case-insensitive) is stripped from the line before checking — the
provenance convention documented in plugin/skills/README.md. This is a
per-occurrence exemption, not a whole-line one: any other "busdev" mention
riding along on the same line still flags, as do other terms on that line and
bare "busdev" anywhere else (including filenames).

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import re
import sys
from pathlib import Path

import yaml

PROVENANCE_RE = re.compile(r"upstreamed-from:\s*busdev@", re.IGNORECASE)


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
    for tree in ("plugin", "template", "fixtures"):
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


def main(root: Path) -> list[str]:
    return lint_skills(root) + scan_cleanroom(root, load_denylist(root))


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
