#!/usr/bin/env python3
"""A new `Unreleased` entry must cite the PR that introduced it.

CLAUDE.md, Git & CI: "a PR gets a line under `Unreleased` (ending with its PR
number)". That rule was broken eight times in the repo's first two weeks, and
every one of them was found by the Opus code reviewer at a few dollars a run:
`(#PR)` and `(#TBD)` placeholders left unfilled (#46, #143), and the closed
*issue* number cited where the PR's own number belongs (#48, #109, #112, #113,
#114, #123). It is a mechanical check wearing a code-review costume.

Worse, the reviewer cannot get this class right at the moment it runs. The
automatic review fires on `opened`, and a PR's number does not exist until the
PR does -- so the author writes a placeholder, the review flags it, and the fix
lands as a follow-up commit the review already read past. Three of the four
"already fixed, stale head" round-trips in that period were this exact loop.
CI runs *on* the PR, where the number is simply known, so it closes the class
outright and keeps the reviewer's budget on real defects.

Deliberately narrow, to stay free of false positives:

- Only added lines inside the `## Unreleased` block are considered. A release
  PR moves entries OUT of Unreleased and into a `## v<version>` section, so
  the other PRs' numbers it carries there are none of this check's business.
- The PR number is demanded only when the diff adds a new BULLET (`- ` at
  column 0) under Unreleased. Rewording an existing entry's prose adds lines
  but does not add an entry, and owes no number.
- The number must merely be PRESENT among the citations on the added lines, so
  an entry crediting both its tracking issue and its PR -- `(#44, #109)` --
  passes.

Usage: check_changelog_entry.py --pr <number> [--base <ref>] [--path <file>]
Exit 0 with no output on success; print problems and exit 1 otherwise.
"""
import argparse
import re
import subprocess
import sys

UNRELEASED_RE = re.compile(r"^##\s+Unreleased\s*$", re.IGNORECASE)
SECTION_RE = re.compile(r"^##\s+")
BULLET_RE = re.compile(r"^-\s+")
# Every `(#...)` citation group, so `(#44, #109)` is read as two tokens.
CITATION_RE = re.compile(r"\(#([^)]+)\)")
HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def unreleased_span(lines):
    """1-indexed [start, end) line span of the `## Unreleased` block's body.

    Returns None when the file carries no Unreleased heading at all -- which
    is a CHANGELOG.md problem, but not this check's to report.
    """
    start = None
    for i, line in enumerate(lines, start=1):
        if start is None:
            if UNRELEASED_RE.match(line):
                start = i + 1
        elif SECTION_RE.match(line):
            return (start, i)
    return None if start is None else (start, len(lines) + 1)


def added_lines(diff):
    """[(new-file line number, text)] for every `+` line in a unified diff."""
    out = []
    lineno = None
    for line in diff.splitlines():
        hunk = HUNK_RE.match(line)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if lineno is None or line.startswith("+++"):
            continue
        if line.startswith("+"):
            out.append((lineno, line[1:]))
            lineno += 1
        elif not line.startswith("-"):
            # Context line (leading space) or the trailing "\ No newline"
            # marker; both advance the new-file cursor by at most one line.
            lineno += 1
    return out


def citations(text):
    """(numbers, placeholders) cited on one line."""
    numbers, placeholders = [], []
    for group in CITATION_RE.findall(text):
        for token in group.split(","):
            token = token.strip().lstrip("#").strip()
            if token.isdigit():
                numbers.append(int(token))
            elif token:
                placeholders.append(token)
    return numbers, placeholders


def check(new_text, diff, pr_number):
    """Problems with the Unreleased entries this diff adds. Empty == clean."""
    span = unreleased_span(new_text.splitlines())
    if span is None:
        return []
    start, end = span

    added = [(n, t) for n, t in added_lines(diff) if start <= n < end]
    if not added:
        return []

    problems = []
    cited, new_bullets = set(), []
    for lineno, text in added:
        numbers, placeholders = citations(text)
        cited.update(numbers)
        for placeholder in placeholders:
            problems.append(
                f"CHANGELOG.md:{lineno}: unfilled placeholder `(#{placeholder})` "
                f"-- this PR is #{pr_number}"
            )
        if BULLET_RE.match(text):
            new_bullets.append(lineno)

    if new_bullets and pr_number not in cited:
        seen = ", ".join(f"#{n}" for n in sorted(cited)) or "none"
        problems.append(
            f"CHANGELOG.md:{new_bullets[0]}: this PR adds an `Unreleased` entry "
            f"that never cites its own number (#{pr_number}); citations found on "
            f"the added lines: {seen}. CLAUDE.md requires the line to end with "
            f"the PR number, not the tracking issue's."
        )
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True, help="this PR's number")
    parser.add_argument(
        "--base",
        default="HEAD~1",
        help="ref to diff against; on a merge-commit checkout HEAD~1 is the "
        "target-branch tip, so HEAD~1..HEAD is the PR's net change",
    )
    parser.add_argument("--path", default="CHANGELOG.md")
    args = parser.parse_args()

    def git(*cmd):
        return subprocess.run(
            ["git", *cmd], capture_output=True, text=True, check=True
        ).stdout

    diff = git("diff", "-U0", f"{args.base}..HEAD", "--", args.path)
    if not diff.strip():
        return 0

    problems = check(git("show", f"HEAD:{args.path}"), diff, args.pr)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
