#!/usr/bin/env python3
"""Build a distribution tree for one release channel, offline and testable.

Backs the tag-triggered release pipeline (`.github/workflows/release.yml`,
issue #10). Two subcommands:

  build --channel {dryrun,client} --out DIR [--repo-root] [--source-ref]
        [--source-sha] [--no-lint]
      Copies plugin/ from a clean checkout into --out, writes a channel-scoped
      marketplace.json, README.md, CHANGELOG.md and RELEASE.json next to it,
      then (unless --no-lint) runs the real clean-room linter over the built
      tree and fails loudly on any finding — nothing gets pushed on a dirty
      build. The build writes no timestamp anywhere, so building the same
      source twice produces a byte-identical tree: the publish job's
      idempotency gate (`git diff --cached --quiet`) depends on that.

  notes --version X [--changelog PATH]
      Extracts the `## v<X> — <date>` section from CHANGELOG.md for the
      GitHub Release body. Falls back to the `## Unreleased` section (with a
      warning on stderr) when no versioned heading exists yet — the state of
      the very first tag, cut before any release has turned Unreleased into
      a dated section.

Both channels ship the same plugin/ content; they differ only in the
marketplace name, the target dist repo, and a channel notice appended near
the top of the built README (the dryrun repo's existing "temporary, hand-
built" notice; nothing for the client channel).
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

# lint_plugin (imported lazily, inside verify_tree()) pulls in PyYAML. `notes`
# — the subcommand `github_release` runs — must work without it: that job has
# no reason to install PyYAML, and importing lint_plugin at module scope made
# every `notes` invocation depend on a dependency only the lint path needs.
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]

# The dryrun repo's own README carried this paragraph from the start (it was
# hand-built ahead of the pipeline that now writes it) — reused verbatim
# rather than rewritten, so the notice a consultant has already read once
# does not silently change wording underneath them.
_DRYRUN_NOTICE = (
    "> **Status: temporary.** This repository is hand-built for a pre-pilot dry run.\n"
    "> It is superseded by the real `sb-dist`, whose contents are written\n"
    "> exclusively by a tag-triggered release pipeline. Do not treat anything here\n"
    "> as a released artifact, and do not point a client deployment at it.\n"
    "\n"
)

# name: the marketplace's own `name` field.
# dist_repo: the GitHub repo (under the org) this channel publishes to.
# channel_notice: text inserted near the top of the built README; empty for
# the client channel, which carries no caveat.
CHANNELS = {
    "dryrun": {
        "marketplace_name": "sb-accelerator-dryrun",
        "dist_repo": "sb-dist-dryrun",
        "channel_notice": _DRYRUN_NOTICE,
    },
    "client": {
        "marketplace_name": "sb-accelerator",
        "dist_repo": "sb-dist",
        "channel_notice": "",
    },
}

# Client-safe: no "internal", no "dev", no delaware-consultant framing —
# already proven on the hand-built dryrun repo, reused rather than redrafted
# so the description a client's admin sees does not depend on which script
# happened to write it.
MARKETPLACE_DESCRIPTION = (
    "Second Brain Accelerator plugin — skills, hooks, and agents for a "
    "client executive's personal AI operating system."
)

# Text that must never survive into a built dist tree: the giveaway strings
# of this repo's *internal* marketplace.json (root .claude-plugin/marketplace.json,
# name "sb-accelerator-dev"). A copy/paste of that manifest into build() would
# leak the dev name and description into a client's plugin catalogue.
DEV_LEAKAGE_STRINGS = ("sb-accelerator-dev", "Internal development marketplace")

# The complete, exact set of entries build() writes at the dist root. A
# mismatch here (something extra, or something missing) means build() drifted
# from what it is documented to produce — the root-file scan below is a net
# for that, not a redundant check on top of the per-file assertions.
EXPECTED_ROOT_ENTRIES = {
    ".claude-plugin",
    ".gitignore",
    "README.md",
    "CHANGELOG.md",
    "RELEASE.json",
    "plugin",
}


class DistBuildError(RuntimeError):
    """Raised by build() when lint=True and the built tree fails verify_tree()."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def _plugin_version(out: Path) -> str:
    data = json.loads((out / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return data["version"]


def _structure_version(out: Path) -> str:
    return (out / "plugin" / "template" / "structure-version").read_text(encoding="utf-8").strip()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def build(channel: str, out: Path, repo_root: Path, *,
          source_ref: str = "unknown", source_sha: str = "unknown",
          lint: bool = True) -> Path:
    """Build `channel`'s dist tree at `out` from `repo_root`'s plugin/ and
    CHANGELOG.md. Returns `out`. Raises ValueError for an unknown channel and
    DistBuildError (carrying `.problems`) when lint=True and the built tree
    fails verify_tree()."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r} — choose one of {sorted(CHANNELS)}")
    spec = CHANNELS[channel]

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # A fresh copytree of a clean checkout's plugin/ is equal to `git archive`
    # of that ref — offline and testable, unlike shelling out to git.
    shutil.copytree(
        repo_root / "plugin", out / "plugin",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )

    plugin_version = _plugin_version(out)
    structure_version = _structure_version(out)

    (out / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    _write_json(out / ".claude-plugin" / "marketplace.json", {
        "name": spec["marketplace_name"],
        "owner": {"name": "delaware"},
        "plugins": [{
            "name": "second-brain",
            "source": "./plugin",
            "description": MARKETPLACE_DESCRIPTION,
        }],
    })

    tmpl = (repo_root / "scripts" / "dist" / "README.md.tmpl").read_text(encoding="utf-8")
    readme = tmpl.format(
        plugin_version=plugin_version,
        structure_version=structure_version,
        marketplace_name=spec["marketplace_name"],
        channel_notice=spec["channel_notice"],
    )
    (out / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    shutil.copy2(repo_root / "CHANGELOG.md", out / "CHANGELOG.md")

    (out / ".gitignore").write_text("__pycache__/\n*.pyc\n.DS_Store\n", encoding="utf-8", newline="\n")

    # Deliberately no timestamp field: two builds of the same source must be
    # byte-identical, which is what lets the publish job's
    # `git diff --cached --quiet` detect "nothing changed, already published".
    _write_json(out / "RELEASE.json", {
        "plugin_version": plugin_version,
        "structure_version": structure_version,
        "channel": channel,
        "marketplace": spec["marketplace_name"],
        "source_repo": "sb-accelerator",
        "source_ref": source_ref,
        "source_sha": source_sha,
    })

    if lint:
        problems = verify_tree(out, repo_root)
        if problems:
            raise DistBuildError(problems)

    return out


def _scan_dev_leakage(out: Path) -> list[str]:
    problems = []
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        for needle in DEV_LEAKAGE_STRINGS:
            if needle in text:
                problems.append(
                    f"{path.relative_to(out)}: internal marketplace text leaked "
                    f"into the dist tree: {needle!r}"
                )
    return problems


def _root_file_scan(out: Path) -> list[str]:
    found = {p.name for p in out.iterdir()}
    problems = []
    for name in sorted(found - EXPECTED_ROOT_ENTRIES):
        problems.append(f"{name}: unexpected entry at the dist root")
    for name in sorted(EXPECTED_ROOT_ENTRIES - found):
        problems.append(f"{name}: missing from the dist root")
    return problems


def verify_tree(out: Path, repo_root: Path) -> list[str]:
    """Runs the real, product-repo clean-room linter over a *built* dist
    tree — not the source tree lint_plugin.py normally checks.

    Scans the whole dist root (`trees=(".",)`), not just `out/plugin/`:
    build() also writes README.md, CHANGELOG.md and RELEASE.json at the
    root, and CHANGELOG.md above all is free-form human prose that
    explicitly ships to sb-dist — and scripts/lint_plugin.py's own
    SHIPPED_TREES (plugin/ + fixtures/) never scans it at PR time either, so
    this is the only gate that ever could. `pathlib` collapses `out / "."`
    to `out`, so one token widens the walk to the whole built tree (plugin/
    included) with no double-scan.

    Imports lint_plugin here, not at module scope: lint_plugin imports
    PyYAML, and notes() (below) must keep working in a job that never
    installs it — only the lint path needs it."""
    from lint_plugin import lint_skills, load_denylist, scan_cleanroom

    problems: list[str] = []
    problems.extend(lint_skills(out))
    problems.extend(scan_cleanroom(out, load_denylist(repo_root), trees=(".",)))
    problems.extend(_root_file_scan(out))
    problems.extend(_scan_dev_leakage(out))
    return problems


# --- notes() ---

# The negative lookahead excludes a line like "## #stray" from matching as a
# heading at all — without it, its captured heading text would be "#stray",
# a heading whose own text starts with "#" and so reads ambiguously next to
# a real "### " sub-heading one level down. Sub-headings themselves (three or
# more leading "#") never matched this pattern regardless — the mandatory
# literal space right after exactly two "#" characters already rejects them
# — but the lookahead removes the one adjacent case that did slip through.
_SECTION_RE = re.compile(r"^## (?!#)(.+?)\s*$", re.MULTILINE)


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(_SECTION_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((heading, text[start:end]))
    return out


def notes(version: str, changelog_path: Path) -> tuple[str, bool]:
    """Returns (body, fell_back). body is the bullet text under the matching
    `## v<version> ...` heading, stripped. fell_back is True when no such
    heading exists and the `## Unreleased` section was used instead (the
    state of a repo before its first release has ever cut a versioned
    section) — the caller decides how loudly to warn."""
    text = changelog_path.read_text(encoding="utf-8")
    sections = _sections(text)
    key = f"v{version}"
    for heading, body in sections:
        if heading == key or heading.startswith(key + " "):
            return body.strip() + "\n", False
    for heading, body in sections:
        if heading == "Unreleased":
            return body.strip() + "\n", True
    return "", True


# --- CLI ---


def _cli_build(args: argparse.Namespace) -> int:
    try:
        build(args.channel, args.out, args.repo_root,
              source_ref=args.source_ref, source_sha=args.source_sha,
              lint=not args.no_lint)
    except DistBuildError as exc:
        for problem in exc.problems:
            print(problem)
        print(
            f"build_dist: {len(exc.problems)} problem(s) in the built "
            f"{args.channel} tree — nothing pushed", file=sys.stderr,
        )
        return 1
    except (ValueError, OSError) as exc:
        print(f"build_dist: {exc}", file=sys.stderr)
        return 1
    print(f"built {args.channel} dist tree at {args.out}")
    return 0


def _cli_notes(args: argparse.Namespace) -> int:
    try:
        text, fell_back = notes(args.version, args.changelog)
    except FileNotFoundError as exc:
        print(f"build_dist: {exc}", file=sys.stderr)
        return 1
    if fell_back:
        print(
            f"build_dist: no '## v{args.version} ...' section in "
            f"{args.changelog} — falling back to '## Unreleased'. This is "
            f"expected only for the very first tag; if a later release hits "
            f"this, the CHANGELOG's release-PR step (Unreleased -> "
            f"'## v<version> — <date>') was skipped.", file=sys.stderr,
        )
    sys.stdout.write(text)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build_dist.py", description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="build one channel's dist tree")
    p_build.add_argument("--channel", required=True, choices=sorted(CHANNELS))
    p_build.add_argument("--out", required=True, type=Path)
    p_build.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    p_build.add_argument("--source-ref", default="unknown")
    p_build.add_argument("--source-sha", default="unknown")
    p_build.add_argument("--no-lint", action="store_true",
                          help="skip verify_tree() after building (CI never sets this)")
    p_build.set_defaults(func=_cli_build)

    p_notes = sub.add_parser("notes", help="extract a version's release notes from CHANGELOG.md")
    p_notes.add_argument("--version", required=True)
    p_notes.add_argument("--changelog", type=Path, default=None)
    p_notes.set_defaults(func=_cli_notes)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "notes" and args.changelog is None:
        args.changelog = DEFAULT_REPO_ROOT / "CHANGELOG.md"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
