#!/usr/bin/env python3
"""Template skeleton invariants.

While template/ holds only its README, that's the valid bootstrap state.
The moment anything else exists (the template-extraction issue), the template
must carry its markers: CLAUDE.md (vault instructions), structure-version
(consumed by /upgrade-vault), and 99-workflow-config/config.json in the safe
shipping state (identity values null, connector adapters disabled, unbound).

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import json
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
    problems.extend(check_config(template))
    return problems


def check_config(template: Path) -> list[str]:
    """The shipped default must be valid AND in the safe shipping state:
    identity values null, connector adapters disabled and unbound. A template
    that ships a binding would silently wire every new vault to it."""
    path = template / "99-workflow-config" / "config.json"
    if not path.is_file():
        return ["populated template/ is missing 99-workflow-config/config.json"]
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"template config.json is not valid JSON: {exc}"]
    if not isinstance(cfg, dict):
        return ["template config.json must hold a JSON object"]
    problems = []
    if not cfg.get("_readme"):
        problems.append("template config.json must carry a _readme explaining the file")
    if cfg.get("config-version") != 1:
        problems.append("template config.json must declare config-version 1")
    for key in ("timezone", "executive"):
        if key not in cfg or cfg[key] is not None:
            problems.append(f"template config.json must ship {key} as null")
    adapters = cfg.get("adapters")
    if not isinstance(adapters, dict) or set(adapters) != {"inbox", "plaud", "m365"}:
        problems.append("template config.json adapters must be exactly inbox, plaud, m365")
        return problems
    if adapters["inbox"] != {"enabled": True}:
        problems.append("template config.json must ship adapters.inbox as {\"enabled\": true}")
    for name in ("plaud", "m365"):
        if adapters[name] != {"enabled": False, "account_hint": None}:
            problems.append(
                f"template config.json must ship adapters.{name} disabled with a null account_hint"
            )
    return problems


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
