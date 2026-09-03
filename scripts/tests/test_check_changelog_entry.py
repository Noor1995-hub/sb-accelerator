"""Coverage for the Unreleased-entry PR-number check.

Every "regression" case below is a real finding the Opus code reviewer spent a
few dollars catching in the repo's first two weeks, cited by PR number in the
test name. The point of the check is that none of them should ever reach a
reviewer again.
"""
from check_changelog_entry import added_lines, check, citations, unreleased_span

HEAD = """# Changelog

Entries accumulate under `Unreleased`.

## Unreleased

- **An entry that already shipped.** Prose. (#80)

## v0.1.0 — 2026-08-01

- **An older entry.** Prose. (#12)
"""


def insert(base, lineno, *lines):
    """(new file text, -U0 diff) for inserting `lines` at `lineno`.

    Both halves are derived from the same insertion on purpose. `check()` is
    handed the POST-change file (the script reads it with `git show
    HEAD:CHANGELOG.md`), so a fixture that pairs a synthetic diff with the
    PRE-change text mismatches the line numbers by however many lines the diff
    added -- which silently moves the citation on a wrapped entry's second
    line outside the Unreleased span and makes the check look broken.
    """
    kept = base.splitlines()
    new = kept[: lineno - 1] + list(lines) + kept[lineno - 1 :]
    diff = (
        "--- a/CHANGELOG.md\n"
        "+++ b/CHANGELOG.md\n"
        f"@@ -{lineno - 1},0 +{lineno},{len(lines)} @@\n"
        + "".join(f"+{line}\n" for line in lines)
    )
    return "\n".join(new) + "\n", diff


# --- the pieces ------------------------------------------------------------

def test_unreleased_span_stops_at_the_next_section():
    lines = HEAD.splitlines()
    start, end = unreleased_span(lines)
    assert lines[start - 1 : end - 1] == ["", "- **An entry that already shipped.** Prose. (#80)", ""]


def test_unreleased_span_runs_to_eof_when_it_is_the_last_section():
    assert unreleased_span(["# Changelog", "## Unreleased", "- a (#1)"]) == (3, 4)


def test_no_unreleased_heading_is_not_this_checks_problem():
    assert unreleased_span(["# Changelog", "## v0.1.0", "- a (#1)"]) is None


def test_added_lines_tracks_new_file_numbers_across_hunks():
    diff = (
        "--- a/f\n+++ b/f\n"
        "@@ -1,0 +2,1 @@\n+two\n"
        "@@ -9,0 +20,2 @@\n+twenty\n+twentyone\n"
    )
    assert added_lines(diff) == [(2, "two"), (20, "twenty"), (21, "twentyone")]


def test_added_lines_ignores_removals_and_advances_over_context():
    diff = "--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n ctx\n-gone\n+kept\n"
    assert added_lines(diff) == [(2, "kept")]


def test_citations_splits_a_multi_number_group():
    assert citations("prose (#44, #109)") == ([44, 109], [])


def test_citations_separates_placeholders_from_numbers():
    assert citations("prose (#TBD)") == ([], ["TBD"])


# --- the rule --------------------------------------------------------------

def test_a_new_entry_citing_its_own_pr_passes():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose. (#200)")
    assert check(new, diff, 200) == []


def test_an_entry_crediting_issue_and_pr_passes():
    """`(#44, #109)` — presence is enough; the issue number is welcome too."""
    new, diff = insert(HEAD, 8, "- **New thing.** Prose. (#44, #109)")
    assert check(new, diff, 109) == []


def test_a_wrapped_entry_citing_its_pr_on_the_last_line_passes():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose that wraps", "  onto a second line. (#200)")
    assert check(new, diff, 200) == []


def test_regression_pr_112_issue_number_instead_of_the_prs():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose. (#98)")
    problems = check(new, diff, 112)
    assert len(problems) == 1
    assert "never cites its own number (#112)" in problems[0]
    assert "#98" in problems[0]


def test_regression_pr_143_unfilled_tbd_placeholder():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose. (#TBD)")
    problems = check(new, diff, 143)
    assert any("unfilled placeholder `(#TBD)`" in p for p in problems)


def test_regression_pr_46_literal_pr_placeholder():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose. (#PR)")
    problems = check(new, diff, 46)
    assert any("unfilled placeholder `(#PR)`" in p for p in problems)


def test_an_entry_with_no_citation_at_all_is_caught():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose with no number.")
    problems = check(new, diff, 200)
    assert len(problems) == 1
    assert "citations found on the added lines: none" in problems[0]


def test_the_reported_line_number_is_the_new_bullets_own():
    new, diff = insert(HEAD, 8, "- **New thing.** Prose. (#98)")
    assert check(new, diff, 112)[0].startswith("CHANGELOG.md:8:")


# --- the narrowness that keeps it free of false positives ------------------

def test_rewording_an_existing_entry_owes_no_number():
    """Added lines under Unreleased, but no new bullet — not a new entry."""
    new, diff = insert(HEAD, 8, "  a clarifying sentence added to the entry above.")
    assert check(new, diff, 200) == []


def test_a_release_pr_moving_entries_out_of_unreleased_passes():
    """The other PRs' numbers land in a `## v<version>` section, not Unreleased."""
    new, diff = insert(HEAD, 6, "", "## v0.2.0 — 2026-09-03")
    assert check(new, diff, 155) == []


def test_a_pr_that_does_not_touch_unreleased_passes():
    """An edit to the file's preamble is not an entry."""
    new, diff = insert(HEAD, 3, "A clarifying line in the header prose.")
    assert check(new, diff, 200) == []


def test_an_edit_to_a_released_section_is_out_of_scope():
    new, diff = insert(HEAD, 11, "- **A backfilled old entry.** Prose. (#12)")
    assert check(new, diff, 200) == []
