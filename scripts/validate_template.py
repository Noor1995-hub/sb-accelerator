#!/usr/bin/env python3
"""Template skeleton invariants.

While template/ holds only its README, that's the valid bootstrap state.
The moment anything else exists (the template-extraction issue), the template
must carry its two markers: CLAUDE.md (vault instructions) and
structure-version (consumed by /upgrade-vault).

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import sys
from pathlib import Path


def main(root: Path) -> list[str]:
    template = root / "template"
    if not template.is_dir():
        return ["template/ directory is missing"]
    entries = [p for p in template.rglob("*") if p.name != ".gitkeep"]
    non_readme = [p for p in entries if p.relative_to(template) != Path("README.md")]
    if not non_readme:
        return []  # unpopulated skeleton — valid bootstrap state
    problems = []
    if not (template / "CLAUDE.md").is_file():
        problems.append("populated template/ is missing CLAUDE.md")
    if not (template / "structure-version").is_file():
        problems.append("populated template/ is missing the structure-version marker")
    return problems


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
