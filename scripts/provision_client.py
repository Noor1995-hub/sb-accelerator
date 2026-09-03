#!/usr/bin/env python3
"""Per-client feedback-repo provisioning (issue #11). delaware-side tool —
never ships in plugin/. Creates (or reuses) a private `sb-client-<slug>`
GitHub repo, seeds its README and issue template, ensures the triage
labels, registers the deployment in `registry.yaml`, and prints the
fine-grained-token recipe a human has to mint by hand (PATs cannot be
minted via API).

Usage:
    provision_client.py <slug> --owner NAME [--delivery-path A..E]
        [--dist-channel client|dryrun] [--archetype commercial-leader]
        [--care-package active|lapsed|none] [--notes TEXT]
        [--register-only] [--update] [--dry-run]
        [--org DLW-INT-BTA-BELUX] [--registry registry.yaml]

`--register-only` skips every `gh` call and only writes the registry entry
— use this for a vault that already has (or never needs) a real feedback
repo, e.g. the internal DryRunVault. `--dry-run` never spawns `gh` either
(a RecordingRunner stands in) and, unlike `--register-only`, does not touch
registry.yaml — it only prints what would happen. Creating or modifying a
real GitHub repo is a deliberate act: never run this without one of those
two flags unless you mean to call `gh` for real.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from string import Template
from typing import Optional, Protocol

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = Path(__file__).resolve().parent / "dist" / "client-repo"

# (destination path in the client repo, template file under SEED_ROOT).
# The template tree mirrors the destination layout so what ships is obvious
# from browsing scripts/dist/client-repo/ — the .tmpl suffix is stripped and
# any $placeholder substituted before the PUT.
SEED_FILES = (
    ("README.md", "README.md.tmpl"),
    (".github/ISSUE_TEMPLATE/feedback.md", ".github/ISSUE_TEMPLATE/feedback.md.tmpl"),
)

# name, color (6-hex, no '#'). Idempotent via `gh label create --force`.
LABELS = (
    ("feedback", "0e8a16"),
    ("health-report", "1d76db"),
    ("triage:new", "fbca04"),
    ("triage:accepted", "0052cc"),
    ("triage:productized", "5319e7"),
    ("triage:declined", "b60205"),
)

DEFAULT_ORG = "DLW-INT-BTA-BELUX"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


class SlugError(ValueError):
    """Slug does not match SLUG_RE."""


class DuplicateClientError(Exception):
    """Slug already has a registry.yaml entry and --update was not given."""


class GhCommandError(RuntimeError):
    """A `gh` invocation exited non-zero."""

    def __init__(self, args: list, returncode: int, stderr: str):
        self.args_ = list(args)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"gh {' '.join(args)} failed ({returncode}): {stderr.strip()}")


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise SlugError(
            f"invalid client slug {slug!r} — must match {SLUG_RE.pattern} "
            "(lowercase letters, digits, hyphens; 2-40 chars, starting with a "
            "letter or digit)")
    return slug


def _slug_type(value: str) -> str:
    try:
        return validate_slug(value)
    except SlugError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# gh runners
# ---------------------------------------------------------------------------

class GhRunner(Protocol):
    def run(self, args: list, input: Optional[str] = None) -> str: ...  # noqa: A002


class SubprocessRunner:
    """Shells the real `gh` CLI. Never constructed for --dry-run or in tests."""

    def run(self, args: list, input: Optional[str] = None) -> str:  # noqa: A002
        result = subprocess.run(
            ["gh", *args], input=input, capture_output=True, text=True)
        if result.returncode != 0:
            raise GhCommandError(args, result.returncode, result.stderr)
        return result.stdout


class RecordingRunner:
    """Never spawns `gh`. Records every call, in order, in `.calls`.

    `existing_repo` and `existing_paths` script the canned answers a real
    `gh repo view` / `gh api <contents path>` would give, so a test (or a
    --dry-run preview) can simulate an already-provisioned repo or an
    already-seeded file with no network involved. `echo=True` prints each
    call as it is recorded, for --dry-run's human-readable preview.
    """

    def __init__(self, existing_repo: bool = False, existing_paths=(),
                 echo: bool = False):
        self.calls: list[dict] = []
        self.existing_repo = existing_repo
        self.existing_paths = set(existing_paths)
        self.echo = echo

    def run(self, args: list, input: Optional[str] = None) -> str:  # noqa: A002
        self.calls.append({"args": list(args), "input": input})
        if self.echo:
            print(f"[dry-run] gh {' '.join(args)}")
        if args[:2] == ["repo", "view"]:
            if self.existing_repo:
                return "{}"
            raise GhCommandError(args, 1, "GraphQL: Could not resolve to a Repository")
        if args and args[0] == "api" and len(args) == 2:
            # A bare `gh api <path>` is a GET — the existence check that
            # precedes every seed-file PUT.
            path = args[1]
            for existing in self.existing_paths:
                if path.endswith(f"contents/{existing}"):
                    return "{}"
            raise GhCommandError(args, 1, "HTTP 404: Not Found")
        return ""


# ---------------------------------------------------------------------------
# registry.yaml
# ---------------------------------------------------------------------------

def load_registry(path: Path) -> dict:
    """Every line before `clients:` is kept verbatim as `header` — that is
    where registry.yaml's explanatory comment lives, and nothing here should
    reformat a human's prose. `save_registry` re-emits it unchanged."""
    text = path.read_text(encoding="utf-8") if path.is_file() else "clients: []\n"
    header_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("clients:"):
            break
        header_lines.append(line)
    data = yaml.safe_load(text) or {}
    clients = data.get("clients") or []
    return {"header": "".join(header_lines), "clients": clients}


def save_registry(path: Path, registry: dict) -> None:
    dumped = yaml.safe_dump(
        {"clients": registry["clients"]}, sort_keys=False, default_flow_style=False)
    path.write_text(registry["header"] + dumped, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# version stamps
# ---------------------------------------------------------------------------

def _plugin_version() -> str:
    path = REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


def _structure_version() -> str:
    path = REPO_ROOT / "plugin" / "template" / "structure-version"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


# ---------------------------------------------------------------------------
# repo provisioning steps
# ---------------------------------------------------------------------------

def _seed_files(slug: str, feedback_repo: str) -> list:
    repo_name = f"sb-client-{slug}"
    rendered = []
    for dest, tmpl_rel in SEED_FILES:
        text = (SEED_ROOT / tmpl_rel).read_text(encoding="utf-8")
        rendered.append((dest, Template(text).substitute(
            repo_name=repo_name, feedback_repo=feedback_repo, slug=slug)))
    return rendered


def _repo_exists(runner: GhRunner, feedback_repo: str) -> bool:
    try:
        runner.run(["repo", "view", feedback_repo, "--json", "name"])
        return True
    except GhCommandError:
        return False


def _content_exists(runner: GhRunner, feedback_repo: str, path: str) -> bool:
    try:
        runner.run(["api", f"repos/{feedback_repo}/contents/{path}"])
        return True
    except GhCommandError:
        return False


def _put_content(runner: GhRunner, feedback_repo: str, path: str, content: str) -> None:
    payload = json.dumps({
        "message": f"chore: seed {path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    })
    runner.run(
        ["api", "-X", "PUT", f"repos/{feedback_repo}/contents/{path}", "--input", "-"],
        input=payload)


def _provision_repo(runner: GhRunner, feedback_repo: str, slug: str) -> list:
    actions = []
    if _repo_exists(runner, feedback_repo):
        actions.append(f"{feedback_repo} already exists — skipped create")
    else:
        description = f"delaware feedback channel for sb-client-{slug} — see README"
        runner.run(["repo", "create", feedback_repo, "--private", "--description", description])
        actions.append(f"created {feedback_repo}")

    for dest, content in _seed_files(slug, feedback_repo):
        if _content_exists(runner, feedback_repo, dest):
            actions.append(f"{dest} already present in {feedback_repo} — left untouched")
        else:
            _put_content(runner, feedback_repo, dest, content)
            actions.append(f"seeded {dest} in {feedback_repo}")

    for name, color in LABELS:
        runner.run(["label", "create", name, "--repo", feedback_repo, "--color", color, "--force"])
        actions.append(f"label {name!r} ensured on {feedback_repo}")
    return actions


# ---------------------------------------------------------------------------
# token recipe
# ---------------------------------------------------------------------------

def token_recipe(feedback_repo: str, slug: str, org: str) -> str:
    return (
        "Mint the feedback token by hand (fine-grained PATs cannot be minted via API):\n"
        f"  - Resource owner: {org}\n"
        f"  - Repository access: Only select repositories -> sb-client-{slug}\n"
        "  - Permissions: Issues -> Read and write\n"
        "  - Contents: leave at No access — no Contents permission on this token\n"
        "  - Expiration: 1 year (starts the token-expiry clock on this deployment)\n"
        "Save the token, and nothing else, at:\n"
        "  <vault>/99-workflow-config/secrets/feedback-token\n"
        "Then bind the vault to this repo:\n"
        '  python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" config write --vault <vault> \\\n'
        f"    --field feedback.repo --value {feedback_repo}\n"
    )


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

@dataclass
class ProvisionOptions:
    slug: str
    owner: str
    delivery_path: str = "E"
    dist_channel: str = "client"
    archetype: str = "commercial-leader"
    care_package: str = "active"
    notes: str = ""
    register_only: bool = False
    update: bool = False
    dry_run: bool = False
    org: str = DEFAULT_ORG


def provision(opts: ProvisionOptions, runner: GhRunner, registry_path: Path,
              today: date) -> dict:
    """Pure orchestration: validate, (maybe) provision the repo through
    `runner`, then update the registry entry. Raises DuplicateClientError
    if the slug is already registered and `opts.update` is not set."""
    slug = validate_slug(opts.slug)
    feedback_repo = f"{opts.org}/sb-client-{slug}"

    registry = load_registry(registry_path)
    clients = registry["clients"]
    index = next((i for i, c in enumerate(clients) if c.get("client") == slug), None)
    if index is not None and not opts.update:
        raise DuplicateClientError(
            f"client {slug!r} is already registered in {registry_path} — "
            "pass --update to replace its entry")

    gh_actions: list[str] = []
    if not opts.register_only:
        gh_actions = _provision_repo(runner, feedback_repo, slug)

    entry = {
        "client": slug,
        "owner": opts.owner,
        "plugin_version": _plugin_version(),
        "structure_version": _structure_version(),
        "archetype": opts.archetype,
        "care_package": opts.care_package,
        "delivery_path": opts.delivery_path,
        "feedback_repo": feedback_repo,
        "dist_channel": opts.dist_channel,
        "provisioned": today.isoformat(),
        "notes": opts.notes,
    }

    if index is not None:
        clients[index] = entry
    else:
        clients.append(entry)

    registered = False
    if not opts.dry_run:
        save_registry(registry_path, registry)
        registered = True

    return {
        "slug": slug,
        "feedback_repo": feedback_repo,
        "gh_actions": gh_actions,
        "entry": entry,
        "registered": registered,
        "recipe": token_recipe(feedback_repo, slug, opts.org),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Create/reuse a client's sb-client-<slug> feedback repo, "
                     "register the deployment, and print the token recipe.")
    parser.add_argument("slug", type=_slug_type,
                         help="Client slug, e.g. 'acme' -> sb-client-acme")
    parser.add_argument("--owner", required=True,
                         help="Consultant owning this deployment (name or initials)")
    parser.add_argument("--delivery-path", choices=list("ABCDE"), default="E",
                         help="Which playbooks/plugin-distribution.md path this "
                              "deployment uses (A-E); default E (manual ZIP upload)")
    parser.add_argument("--dist-channel", choices=["client", "dryrun"], default="client")
    parser.add_argument("--archetype", default="commercial-leader")
    parser.add_argument("--care-package", choices=["active", "lapsed", "none"], default="active")
    parser.add_argument("--notes", default="")
    parser.add_argument("--register-only", action="store_true",
                         help="Skip every gh call — only write the registry.yaml entry")
    parser.add_argument("--update", action="store_true",
                         help="Replace an existing entry for this slug instead of "
                              "refusing it as a duplicate")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print the gh calls and registry entry that would "
                              "result; never spawns gh, never touches registry.yaml")
    parser.add_argument("--org", default=DEFAULT_ORG,
                         help=f"GitHub org that owns client repos (default {DEFAULT_ORG})")
    parser.add_argument("--registry", type=Path, default=None,
                         help="Path to registry.yaml (default: repo root's registry.yaml)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    registry_path = args.registry if args.registry is not None else (REPO_ROOT / "registry.yaml")

    opts = ProvisionOptions(
        slug=args.slug,
        owner=args.owner,
        delivery_path=args.delivery_path,
        dist_channel=args.dist_channel,
        archetype=args.archetype,
        care_package=args.care_package,
        notes=args.notes,
        register_only=args.register_only,
        update=args.update,
        dry_run=args.dry_run,
        org=args.org,
    )

    runner: GhRunner = RecordingRunner(echo=True) if opts.dry_run else SubprocessRunner()

    try:
        result = provision(opts, runner, registry_path, date.today())
    except DuplicateClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (GhCommandError, SlugError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for action in result["gh_actions"]:
        print(action)

    if opts.dry_run:
        preview = yaml.safe_dump(
            {"clients": [result["entry"]]}, sort_keys=False, default_flow_style=False)
        print("[dry-run] registry.yaml entry would be:")
        print(preview.rstrip())
    else:
        print(f"registry.yaml updated for {result['slug']!r} -> {registry_path}")

    print()
    print(result["recipe"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
