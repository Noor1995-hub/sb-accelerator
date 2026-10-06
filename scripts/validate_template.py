#!/usr/bin/env python3
"""Template skeleton invariants.

While plugin/template/ is empty, that's the valid bootstrap state. The
template ships no README of its own — builder-facing instantiation
documentation lives in playbooks/ and docs/, because everything under
plugin/template/ is copied into the client's vault and read by the vault
owner.

The moment anything exists in it (the template-extraction issue), the template
must carry its markers: CLAUDE.md (vault instructions), structure-version
(consumed by /upgrade-vault, and pinned here to the latest migration's target),
and 99-workflow-config/config.json in the safe shipping state (identity values
null, connector adapters disabled, unbound).

Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import json
import sys
from pathlib import Path

# The structure-version a freshly instantiated vault ships at: the
# TARGET_VERSION of the last migration in plugin/migrations/. Hardcoded rather
# than read from the migration chain, because the two drifting apart is exactly
# what this check is for — importing the chain would make the assertion agree
# with whatever the chain says and catch nothing. Bump both together.
EXPECTED_STRUCTURE_VERSION = "11"


def main(root: Path) -> list[str]:
    template = root / "plugin" / "template"
    if not template.is_dir():
        return ["plugin/template/ directory is missing"]
    entries = [p for p in template.rglob("*") if p.name != ".gitkeep"]
    if not entries:
        return []  # unpopulated skeleton — valid bootstrap state
    problems = []
    if not (template / "CLAUDE.md").is_file():
        problems.append("populated template/ is missing CLAUDE.md")
    problems.extend(check_structure_version(template))
    problems.extend(check_config(template))
    problems.extend(check_feedback_contract(template))
    return problems


def check_structure_version(template: Path) -> list[str]:
    """The marker must exist and name the latest migration's target version.

    A migration that lands without this bump ships every new vault at the old
    version, so /upgrade-vault opens by proposing a migration with nothing to
    do — and nothing else in the repo notices, because the migration's own
    tests build their vaults by hand.
    """
    path = template / "structure-version"
    if not path.is_file():
        return ["populated template/ is missing the structure-version marker"]
    found = path.read_text(encoding="utf-8").strip()
    if found != EXPECTED_STRUCTURE_VERSION:
        return [f"template/structure-version is {found!r}, expected "
                f"{EXPECTED_STRUCTURE_VERSION!r} — the latest migration in "
                f"plugin/migrations/ targets that version"]
    return []


def check_feedback_contract(template: Path) -> list[str]:
    """The feedback disclosure and secrets rule must ship in the vault
    CLAUDE.md, and the secrets folder it points to must exist — Tasks 10/11/14
    SKILL.mds rely on this contract being present."""
    problems = []
    if not (template / "99-workflow-config" / "secrets" / "README.md").is_file():
        problems.append("template is missing 99-workflow-config/secrets/README.md")
    claude_md_path = template / "CLAUDE.md"
    if not claude_md_path.is_file():
        return problems  # already reported by the CLAUDE.md marker check
    claude_md = claude_md_path.read_text(encoding="utf-8")
    for phrase in ("solely to improve the product", "explicit approval",
                   "99-workflow-config/secrets"):
        if phrase not in claude_md:
            problems.append(
                f"template CLAUDE.md is missing the feedback-contract phrase "
                f"{phrase!r}")
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
    for key in ("timezone", "owner"):
        if key not in cfg or cfg[key] is not None:
            problems.append(f"template config.json must ship {key} as null")
    adapters = cfg.get("adapters")
    if not isinstance(adapters, dict) or set(adapters) != {"inbox", "plaud", "m365"}:
        problems.append("template config.json adapters must be exactly inbox, plaud, m365")
        return problems
    if adapters["inbox"] != {"enabled": True}:
        problems.append("template config.json must ship adapters.inbox as {\"enabled\": true}")
    if adapters["plaud"] != {"enabled": False, "account_hint": None}:
        problems.append(
            "template config.json must ship adapters.plaud disabled with a null account_hint")
    if adapters["m365"] != {"enabled": False, "account_hint": None,
                             "home_domains": None}:
        problems.append(
            "template config.json must ship adapters.m365 disabled with a "
            "null account_hint and a null home_domains")
    if cfg.get("feedback") != {"repo": None}:
        problems.append('template config.json must ship feedback as {"repo": null}')
    if cfg.get("sync") != {"start-date": None}:
        problems.append(
            'template config.json must ship sync as {"start-date": null} — '
            "provisioning writes the real date per deployment")
    if cfg.get("messages") != {"enabled": False, "consented-at": None,
                               "scope": [], "exclusions": []}:
        problems.append(
            "template config.json must ship messages off, with no consent, "
            "no scope and no exclusions")
    return problems


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    found = main(repo_root)
    for problem in found:
        print(problem)
    sys.exit(1 if found else 0)
