"""Semantics of the Bases filter evaluator, against synthetic notes.

These tests pin the evaluator's *logic*. test_bases_views.py points the same
evaluator at the five real .base files and the demo fixtures.

Everything here is deliberately synthetic: the fixture corpus cannot exercise
some of the semantics that matter most (no fixture meeting omits `reviewed`,
so the missing-is-not-true rule below has no natural example).
"""
import pytest

import basesim


def base(filters=None, views=None):
    """A minimal parsed .base mapping."""
    out = {"views": views or [{"type": "table", "name": "All"}]}
    if filters is not None:
        out["filters"] = filters
    return out


def rows(filters, corpus, view_filters=None):
    views = [{"type": "table", "name": "All"}]
    if view_filters is not None:
        views[0]["filters"] = view_filters
    return basesim.view_rows(base(filters, views), corpus, "All")


# --- file.inFolder is recursive -------------------------------------------

def test_infolder_matches_nested_descendants():
    """Decisions.base filters on `30-projects` but its notes live at
    30-projects/<slug>/decisions/*.md. A direct-children reading returns
    nothing and the view looks empty in Obsidian."""
    corpus = {
        "30-projects/alpha/index.md": {},
        "30-projects/alpha/decisions/one.md": {},
        "20-meetings/x.md": {},
    }
    got = rows({"and": ['file.inFolder("30-projects")']}, corpus)
    assert got == {"30-projects/alpha/index.md", "30-projects/alpha/decisions/one.md"}


def test_infolder_does_not_match_a_sibling_with_the_same_prefix():
    corpus = {"30-projects-archive/x.md": {}, "30-projects/y.md": {}}
    assert rows({"and": ['file.inFolder("30-projects")']}, corpus) == {"30-projects/y.md"}


def test_infolder_does_not_match_the_folder_note_itself_by_prefix():
    corpus = {"30-projects.md": {}, "30-projects/y.md": {}}
    assert rows({"and": ['file.inFolder("30-projects")']}, corpus) == {"30-projects/y.md"}


# --- missing is not true --------------------------------------------------

def test_not_equal_true_includes_a_note_missing_the_property():
    """Meetings/Triage uses `reviewed != true`. An unreviewed note that has no
    `reviewed` key at all must still show up for triage."""
    corpus = {"a.md": {"reviewed": True}, "b.md": {"reviewed": False}, "c.md": {}}
    assert rows({"and": ["reviewed != true"]}, corpus) == {"b.md", "c.md"}


def test_equality_against_a_missing_property_is_false():
    corpus = {"a.md": {"status": "active"}, "b.md": {}}
    assert rows({"and": ['status == "active"']}, corpus) == {"a.md"}


def test_boolean_literals_are_not_strings():
    corpus = {"a.md": {"reviewed": True}, "b.md": {"reviewed": "true"}}
    assert rows({"and": ["reviewed == true"]}, corpus) == {"a.md"}


# --- isEmpty -------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", [], {}])
def test_is_empty_is_true_for_absent_null_and_empty_containers(value):
    assert rows({"and": ["relationship.isEmpty()"]}, {"a.md": {"relationship": value}}) == {"a.md"}


def test_is_empty_is_true_for_a_property_that_is_not_present_at_all():
    assert rows({"and": ["relationship.isEmpty()"]}, {"a.md": {}}) == {"a.md"}


def test_is_empty_is_false_for_a_populated_value():
    assert rows({"and": ["relationship.isEmpty()"]}, {"a.md": {"relationship": "client"}}) == set()


def test_negated_note_bracket_is_empty():
    """People.base's top-level filter is `!note["person-name"].isEmpty()` —
    the bracket accessor plus the ! prefix, the only place both appear."""
    corpus = {"a.md": {"person-name": "Morgan Ellery"}, "b.md": {"person-name": None}, "c.md": {}}
    got = rows({"and": ['!note["person-name"].isEmpty()']}, corpus)
    assert got == {"a.md"}


# --- file.name / file.ext ------------------------------------------------

def test_file_name_is_the_stem_without_extension():
    corpus = {"40-entities/alpha/dossier.md": {}, "40-entities/alpha/notes.md": {}}
    assert rows({"and": ['file.name == "dossier"']}, corpus) == {"40-entities/alpha/dossier.md"}


def test_file_ext_excludes_non_markdown():
    corpus = {"20-meetings/a.md": {}, "20-meetings/b.png": {}}
    assert rows({"and": ['file.ext == "md"']}, corpus) == {"20-meetings/a.md"}


# --- combinators ---------------------------------------------------------

def test_or_inside_and_matches_meetings_triage_shape():
    corpus = {
        "in-needs-review.md": {"review_status": "needs-review", "reviewed": False, "archived": False},
        "in-needs-attention.md": {"review_status": "needs-attention", "reviewed": False, "archived": False},
        "out-confirmed.md": {"review_status": "confirmed", "reviewed": False, "archived": False},
        "out-reviewed.md": {"review_status": "needs-review", "reviewed": True, "archived": False},
        "out-archived.md": {"review_status": "needs-attention", "reviewed": False, "archived": True},
    }
    got = rows(
        None,
        corpus,
        view_filters={
            "and": [
                {"or": ['review_status == "needs-review"', 'review_status == "needs-attention"']},
                "reviewed != true",
                "archived != true",
            ]
        },
    )
    assert got == {"in-needs-review.md", "in-needs-attention.md"}


def test_base_level_and_view_level_filters_are_anded():
    corpus = {
        "30-projects/a/index.md": {"status": "active"},
        "30-projects/b/index.md": {"status": "completed"},
        "20-meetings/c.md": {"status": "active"},
    }
    got = rows(
        {"and": ['file.inFolder("30-projects")', 'file.name == "index"']},
        corpus,
        view_filters={"and": ['status == "active"']},
    )
    assert got == {"30-projects/a/index.md"}


def test_a_view_without_filters_sees_only_the_base_level_filters():
    corpus = {"a.md": {"type": "entity"}, "b.md": {"type": "project"}}
    assert rows({"and": ['type == "entity"']}, corpus) == {"a.md"}


def test_a_base_with_no_filters_at_all_matches_everything():
    corpus = {"a.md": {}, "b.md": {}}
    assert rows(None, corpus) == {"a.md", "b.md"}


# --- fail loudly on anything unmodeled -----------------------------------

@pytest.mark.parametrize("expression", [
    'status.contains("act")',
    "date > 2026-01-01",
    'file.hasTag("x")',
    'file.unknownAttribute == "x"',
    "status =~ /active/",
])
def test_unmodeled_leaf_expressions_raise(expression):
    """The evaluator covers only what the five .base files use. Anything else
    must fail loudly — an operator silently read as "no match" turns a real
    regression into a green test with an empty expectation."""
    with pytest.raises(basesim.UnmodeledFilter):
        rows({"and": [expression]}, {"a.md": {"status": "active"}})


@pytest.mark.parametrize("expression", [
    "file.inFolder()",
    'relationship.isEmpty("x")',
])
def test_wrong_argument_arity_raises(expression):
    """Arity is part of the grammar. An argument-less inFolder() would compare
    against the string "None" and match nothing — the silent-empty-view
    failure, reintroduced by the module meant to catch it."""
    with pytest.raises(basesim.UnmodeledFilter):
        rows({"and": [expression]}, {"20-meetings/a.md": {}})


def test_unmodeled_combinator_raises():
    with pytest.raises(basesim.UnmodeledFilter):
        rows({"not": ['status == "active"']}, {"a.md": {}})


def test_unknown_view_name_raises():
    with pytest.raises(KeyError):
        basesim.view_rows(base(), {}, "NoSuchView")


# --- corpus loading -----------------------------------------------------

def test_load_corpus_reads_frontmatter_and_uses_posix_relative_paths(tmp_path):
    note = tmp_path / "20-meetings" / "a.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntype: meeting\nreviewed: false\n---\n\nbody\n", encoding="utf-8")
    corpus = basesim.load_corpus(tmp_path)
    assert corpus == {"20-meetings/a.md": {"type": "meeting", "reviewed": False}}


def test_load_corpus_includes_non_markdown_with_empty_frontmatter(tmp_path):
    (tmp_path / "70-resources").mkdir()
    (tmp_path / "70-resources" / "deck.pptx").write_bytes(b"\x00")
    assert basesim.load_corpus(tmp_path) == {"70-resources/deck.pptx": {}}


def test_load_corpus_skips_dot_directories(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.md").write_text("---\ntype: entity\n---\n", encoding="utf-8")
    assert set(basesim.load_corpus(tmp_path)) == {"a.md"}


def test_load_corpus_tolerates_a_markdown_file_with_no_frontmatter(tmp_path):
    (tmp_path / "README.md").write_text("# just prose\n", encoding="utf-8")
    assert basesim.load_corpus(tmp_path) == {"README.md": {}}


def test_load_corpus_reads_obsidian_unquoted_1_1_as_a_string(tmp_path):
    # Obsidian's property editor strips the quotes from `type: "1:1"`, and
    # YAML-1.1 sexagesimal notation then makes stock PyYAML read int 61
    # (issue #53, finding C1). Obsidian's own js-yaml dropped sexagesimal, so
    # the fidelity rule says string — a `type == "1:1"` filter must still hit.
    (tmp_path / "a.md").write_text("---\ntype: 1:1\n---\n", encoding="utf-8")
    assert basesim.load_corpus(tmp_path) == {"a.md": {"type": "1:1"}}


def test_zero_padded_numbers_load_as_base_ten_ints_not_a_crash(tmp_path):
    # The replaced int resolver tags `08` as an int, but PyYAML's stock
    # constructor keeps YAML-1.1 semantics where a leading 0 means octal and
    # int("08", 8) raises, killing the whole corpus load. js-yaml v4 (the
    # fidelity target) is YAML-1.2 core: plain decimal, `08` is 8.
    (tmp_path / "a.md").write_text("---\npadded: 08\noctal-ish: 010\n---\n",
                                   encoding="utf-8")
    assert basesim.load_corpus(tmp_path) == {"a.md": {"padded": 8,
                                                      "octal-ish": 10}}


def test_plain_integers_still_load_as_integers(tmp_path):
    (tmp_path / "a.md").write_text("---\nmeetings-7d: 3\nneg: -2\n---\n",
                                   encoding="utf-8")
    assert basesim.load_corpus(tmp_path) == {"a.md": {"meetings-7d": 3,
                                                      "neg": -2}}
