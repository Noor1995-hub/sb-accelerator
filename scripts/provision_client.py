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
        [--token-minted [YYYY-MM-DD]] [--register-only] [--update] [--dry-run]
        [--org DLW-INT-BTA-BELUX] [--feedback-repo ORG/REPO]
        [--registry registry.yaml]

`--register-only` skips every `gh` call and only writes the registry entry
— use this for a vault that already has (or never needs) a real feedback
repo, e.g. the internal DryRunVault. `--dry-run` never spawns `gh` either
(a RecordingRunner stands in) and, unlike `--register-only`, does not touch
registry.yaml — it only prints what would happen. Creating or modifying a
real GitHub repo is a deliberate act: never run this without one of those
two flags unless you mean to call `gh` for real.

`--update` is non-destructive by design: it restamps `plugin_version` and
`structure_version` from this checkout and leaves every other field at its
registered value unless you pass that field's flag. `feedback_repo` is one
of those fields: a deployment whose channel is not named `sb-client-<slug>`
(the internal test vaults are `sb-internal-<name>`) keeps its registered
name through every --update, and `--feedback-repo ORG/REPO` is how you say
one out loud. So recording a release against an existing deployment is the
whole command —

    provision_client.py <slug> --update --register-only

— and neither date moves. `provisioned` is the deployment's birth date,
written once; `token_minted` is what the feedback token's 1-year expiry
counts from, and only `--token-minted` moves it (bare flag = today). Pass it
when you rotate the token, not when you bump a version.
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

# `<org>/<repo>`, as GitHub spells an owner and a repository name. Only used
# for an explicit --feedback-repo: a registered value is trusted as written.
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

# What a field falls back to when it is left off the command line *and* there
# is no existing entry to inherit it from. On an --update the registered value
# wins over every one of these — a flag you don't type changes nothing.
CREATE_DEFAULTS = {
    "delivery_path": "E",
    "dist_channel": "client",
    "archetype": "commercial-leader",
    "care_package": "active",
    "notes": "",
}


class SlugError(ValueError):
    """Slug does not match SLUG_RE."""


class FeedbackRepoError(ValueError):
    """--feedback-repo is not `<org>/<repo>`."""


class DuplicateClientError(Exception):
    """Slug already has a registry.yaml entry and --update was not given."""


class UnknownClientError(Exception):
    """--update was given for a slug with no registry.yaml entry."""


class MissingOwnerError(ValueError):
    """Creating an entry without an owner. Only an --update may omit it."""


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


def validate_feedback_repo(repo: str) -> str:
    if not REPO_RE.match(repo):
        raise FeedbackRepoError(
            f"invalid feedback repo {repo!r} — must be <org>/<repo>, e.g. "
            f"{DEFAULT_ORG}/sb-internal-acme")
    return repo


def _feedback_repo_type(value: str) -> str:
    try:
        return validate_feedback_repo(value)
    except FeedbackRepoError as exc:
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

def _repo_name(feedback_repo: str) -> str:
    """The repository half of `<org>/<repo>`. Every human-facing string that
    used to spell `sb-client-<slug>` reads this instead — a deployment whose
    channel is named something else (the internal test vaults) would
    otherwise get a README, a description and a token recipe all naming a
    repo that does not exist."""
    return feedback_repo.split("/", 1)[-1]


def _seed_files(slug: str, feedback_repo: str) -> list:
    repo_name = _repo_name(feedback_repo)
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
        description = f"delaware feedback channel for {_repo_name(feedback_repo)} — see README"
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
        f"  - Repository access: Only select repositories -> {_repo_name(feedback_repo)}\n"
        "  - Permissions: Issues -> Read and write\n"
        "  - Contents: leave at No access — no Contents permission on this token\n"
        "  - Expiration: 1 year, counted from this deployment's `token_minted`\n"
        "Save the token, and nothing else, at:\n"
        "  <vault>/99-workflow-config/secrets/feedback-token\n"
        "Record the mint date (do this again on every rotation):\n"
        f"  python scripts/provision_client.py {slug} --update --register-only "
        "--token-minted\n"
        "Then bind the vault to this repo:\n"
        '  python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" config write --vault <vault> \\\n'
        f"    --field feedback.repo --value {feedback_repo}\n"
    )


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

@dataclass
class ProvisionOptions:
    """`None` means "not given on the command line" for every entry field —
    which on an --update means "keep what's registered", and on a create
    means CREATE_DEFAULTS. Never conflate the two: a dataclass default here
    would silently overwrite a registered value at the next tune-up."""

    slug: str
    owner: Optional[str] = None
    delivery_path: Optional[str] = None
    dist_channel: Optional[str] = None
    archetype: Optional[str] = None
    care_package: Optional[str] = None
    notes: Optional[str] = None
    token_minted: Optional[date] = None
    org: Optional[str] = None
    feedback_repo: Optional[str] = None
    register_only: bool = False
    update: bool = False
    dry_run: bool = False


def provision(opts: ProvisionOptions, runner: GhRunner, registry_path: Path,
              today: date) -> dict:
    """Pure orchestration: validate, (maybe) provision the repo through
    `runner`, then write the registry entry. Raises DuplicateClientError if
    the slug is already registered and `opts.update` is not set, and
    UnknownClientError for the reverse.

    On an --update every entry field left `None` in `opts` keeps its
    registered value; only `plugin_version` and `structure_version` are
    unconditionally restamped from this checkout, since recording what is
    deployed is what an update is for."""
    slug = validate_slug(opts.slug)

    registry = load_registry(registry_path)
    clients = registry["clients"]
    index = next((i for i, c in enumerate(clients) if c.get("client") == slug), None)
    if index is not None and not opts.update:
        raise DuplicateClientError(
            f"client {slug!r} is already registered in {registry_path} — "
            "pass --update to replace its entry")
    if index is None and opts.update:
        raise UnknownClientError(
            f"client {slug!r} is not registered in {registry_path} — "
            "--update edits an existing entry; drop it to register a new "
            "deployment (check the slug for a typo first)")

    existing = clients[index] if index is not None else {}

    # The org is sticky, read back off the registered `feedback_repo` — so a
    # deployment registered in a non-default org keeps it through a bare
    # --update, and the gh calls below (and the printed recipe) address that
    # org rather than silently the default one.
    registered_repo = str(existing.get("feedback_repo") or "")
    registered_org, _, registered_name = registered_repo.partition("/")
    if opts.org is not None:
        org = opts.org
    elif registered_name:
        org = registered_org
    else:
        org = DEFAULT_ORG

    # The repo *name* is sticky for the same reason the org is: it is a
    # registered field, not a function of the slug. `sb-client-<slug>` is only
    # the default for a name nobody has recorded yet — an internal test vault
    # on `sb-internal-<name>` used to have that rewritten to a non-existent
    # repo by every --update, silently, while --help promised the opposite.
    if opts.feedback_repo is not None:
        feedback_repo = validate_feedback_repo(opts.feedback_repo)
    elif registered_name:
        feedback_repo = f"{org}/{registered_name}"
    else:
        feedback_repo = f"{org}/sb-client-{slug}"

    owner = opts.owner if opts.owner is not None else existing.get("owner")
    if not owner:
        raise MissingOwnerError(
            f"--owner is required to register {slug!r} — it is only optional "
            "on an --update, which inherits the registered owner")

    def field(name: str):
        given = getattr(opts, name)
        if given is not None:
            return given
        return existing.get(name, CREATE_DEFAULTS[name])

    # The deployment's birth date: written once, never moved. `token_minted`
    # is the clock the 1-year feedback token expires against, and it only
    # moves when --token-minted says a token was (re)minted. On a row that
    # predates the split, the old single field is the best-known clock start.
    provisioned = existing.get("provisioned") or today.isoformat()
    if opts.token_minted is not None:
        token_minted = opts.token_minted.isoformat()
    else:
        token_minted = existing.get("token_minted") or provisioned

    gh_actions: list[str] = []
    if not opts.register_only:
        gh_actions = _provision_repo(runner, feedback_repo, slug)

    entry = {
        "client": slug,
        "owner": owner,
        "plugin_version": _plugin_version(),
        "structure_version": _structure_version(),
        "archetype": field("archetype"),
        "care_package": field("care_package"),
        "delivery_path": field("delivery_path"),
        "feedback_repo": feedback_repo,
        "dist_channel": field("dist_channel"),
        "provisioned": provisioned,
        "token_minted": token_minted,
        "notes": field("notes"),
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
        "recipe": token_recipe(feedback_repo, slug, org),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_token_minted(raw: Optional[str], today: date) -> Optional[date]:
    """`--token-minted` as a date. `None` (flag absent) means "don't move the
    token clock"; a bare flag arrives as "today"."""
    if raw is None:
        return None
    if raw == "today":
        return today
    return date.fromisoformat(raw)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Create/reuse a client's sb-client-<slug> feedback repo, "
                     "register the deployment, and print the token recipe.")
    parser.add_argument("slug", type=_slug_type,
                         help="Client slug, e.g. 'acme' -> sb-client-acme")
    # Every entry field defaults to None, not to its value: on an --update a
    # flag you leave off keeps whatever is registered. The create-time
    # fallbacks live in CREATE_DEFAULTS.
    parser.add_argument("--owner",
                         help="Consultant owning this deployment (name or initials). "
                              "Required to register a new deployment; on --update it "
                              "defaults to the registered owner")
    parser.add_argument("--delivery-path", choices=list("ABCDE"), default=None,
                         help="Which playbooks/plugin-distribution.md path this "
                              "deployment uses (A-E); default E (manual ZIP upload)")
    parser.add_argument("--dist-channel", choices=["client", "dryrun"], default=None)
    parser.add_argument("--archetype", default=None,
                         help="Default commercial-leader")
    parser.add_argument("--care-package", choices=["active", "lapsed", "none"],
                         default=None, help="Default active")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--token-minted", nargs="?", const="today", default=None,
                         metavar="YYYY-MM-DD",
                         help="Record that the feedback token was minted on this "
                              "date (bare flag = today) — the 1-year expiry counts "
                              "from it. Pass this when you rotate the token; leave "
                              "it off and the date does not move")
    parser.add_argument("--register-only", action="store_true",
                         help="Skip every gh call — only write the registry.yaml entry")
    parser.add_argument("--update", action="store_true",
                         help="Edit this slug's existing entry instead of refusing "
                              "it as a duplicate. Restamps plugin_version and "
                              "structure_version; every other field keeps its "
                              "registered value unless you pass its flag")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print the gh calls and registry entry that would "
                              "result; never spawns gh, never touches registry.yaml")
    parser.add_argument("--org", default=None,
                         help="GitHub org that owns client repos (default "
                              f"{DEFAULT_ORG}; on --update, the org this "
                              "deployment is already registered under)")
    parser.add_argument("--feedback-repo", type=_feedback_repo_type, default=None,
                         metavar="ORG/REPO",
                         help="Full name of this deployment's feedback repo, "
                              "for a channel not named sb-client-<slug> (the "
                              "internal test vaults). Registered once and then "
                              "sticky: a bare --update keeps it")
    parser.add_argument("--registry", type=Path, default=None,
                         help="Path to registry.yaml (default: repo root's registry.yaml)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    registry_path = args.registry if args.registry is not None else (REPO_ROOT / "registry.yaml")
    today = date.today()

    try:
        token_minted = resolve_token_minted(args.token_minted, today)
    except ValueError:
        print(f"error: --token-minted {args.token_minted!r} is not an ISO date "
              "(YYYY-MM-DD); pass the flag bare for today", file=sys.stderr)
        return 1

    opts = ProvisionOptions(
        slug=args.slug,
        owner=args.owner,
        delivery_path=args.delivery_path,
        dist_channel=args.dist_channel,
        archetype=args.archetype,
        care_package=args.care_package,
        notes=args.notes,
        token_minted=token_minted,
        register_only=args.register_only,
        update=args.update,
        dry_run=args.dry_run,
        org=args.org,
        feedback_repo=args.feedback_repo,
    )

    runner: GhRunner = RecordingRunner(echo=True) if opts.dry_run else SubprocessRunner()

    try:
        result = provision(opts, runner, registry_path, today)
    except (DuplicateClientError, UnknownClientError, MissingOwnerError) as exc:
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
