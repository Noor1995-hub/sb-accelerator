"""Every property a Dataview block names must exist in the ontology.

Dataview's failure mode is silent: a query naming a property the ontology
renamed renders an empty table, not an error. This is a *reference* check, not
an evaluator — deliberately. Reimplementing DQL to run 10 queries would cost
far more fidelity risk than it buys.
"""
from pathlib import Path

import pytest

import dqlrefs

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"
TEMPLATE_ROOT = REPO_ROOT / "plugin" / "template"

# (vault root, note) pairs. The root travels with the note rather than being
# inferred: only fixtures carry Dataview blocks today, but a block added to
# plugin/template/ (the HOME dashboard, #32) must resolve its FROM paths against
# plugin/template/, not against the fixtures.
NOTES_WITH_BLOCKS = sorted(
    (root, path)
    for root in (FIXTURE_ROOT, TEMPLATE_ROOT)
    for path in root.rglob("*.md")
    if "```dataview" in path.read_text(encoding="utf-8")
)


# Precomputed rather than an `ids=` callable: with a multi-argument
# parametrize, pytest calls the callable per argument, not per tuple.
BLOCK_IDS = [path.relative_to(root).as_posix() for root, path in NOTES_WITH_BLOCKS]


# --- extraction ---------------------------------------------------------

SAMPLE = '''TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date",
  slice(attendees, 0, 3) AS "Attendees",
  recording-duration AS "Min"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
SORT date DESC
LIMIT 15'''


def test_string_literals_do_not_leak_in_as_properties():
    """A blind identifier regex picks up `dd-MM`, `HH`, `mm` and the display
    aliases in `AS "..."` — every one of them a false property reference."""
    refs = dqlrefs.extract_refs(SAMPLE)
    for leaked in ("dd-MM", "HH", "mm", "Date", "Attendees", "Min"):
        assert leaked not in refs.properties


NAMES = '''TABLE WITHOUT ID
  map(slice(attendees, 0, 3), (a) => default(link("50-people/" + a).person-name, a)) AS "With",
  map(projects, (p) => link("30-projects/" + p + "/index", default(link("30-projects/" + p + "/index").project-name, p))) AS "Projects"
FROM "20-meetings"
WHERE econtains(projects, this.slug)'''


def test_lambda_params_and_linked_fields_are_not_the_queried_objects(tmp_path):
    """#259: `a` and `p` are lambda parameters, and `.person-name` /
    `.project-name` belong to the linked note, not to the meeting."""
    refs = dqlrefs.extract_refs(NAMES)
    assert refs.properties == {"attendees", "projects"}
    assert refs.linked_properties == {("person", "person-name"), ("project", "project-name")}


def test_a_linked_field_the_ontology_does_not_know_is_caught():
    refs = dqlrefs.extract_refs(NAMES.replace(".person-name", ".full-name"))
    assert ("person", "full-name") in refs.linked_properties
    assert "full-name" not in dqlrefs.known_fields("person")


def test_keywords_and_functions_are_not_properties():
    refs = dqlrefs.extract_refs(SAMPLE)
    for keyword in ("TABLE", "WITHOUT", "ID", "AS", "FROM", "WHERE", "SORT", "LIMIT", "DESC"):
        assert keyword not in refs.properties
    for func in ("link", "dateformat", "slice", "econtains"):
        assert func not in refs.properties


def test_file_implicits_are_not_properties():
    assert "file.path" not in dqlrefs.extract_refs(SAMPLE).properties
    assert "path" not in dqlrefs.extract_refs(SAMPLE).properties


def test_bare_properties_are_extracted_including_hyphenated_ones():
    assert dqlrefs.extract_refs(SAMPLE).properties == {
        "date", "attendees", "recording-duration", "projects"}


def test_this_properties_are_kept_separate():
    """`this.slug` resolves against the *containing* note's type, not the
    FROM type. Conflating them is how this test passes vacuously."""
    refs = dqlrefs.extract_refs(SAMPLE)
    assert refs.this_properties == {"slug"}
    assert "slug" not in refs.properties


def test_from_paths_are_extracted():
    assert dqlrefs.extract_refs(SAMPLE).from_paths == {"20-meetings"}


def test_unknown_function_raises():
    """The allowlist is the gate: a new DQL function must be added
    deliberately, not silently mistaken for a property."""
    with pytest.raises(dqlrefs.UnmodeledQuery):
        dqlrefs.extract_refs('TABLE truncate(summary, 40) AS "S"\nFROM "20-meetings"')


def test_block_extraction_finds_every_dataview_fence():
    text = (
        "prose\n\n```dataview\nTABLE x\nFROM \"20-meetings\"\n```\n\n"
        "more\n\n```dataview\nLIST\nFROM \"50-people\"\n```\n"
    )
    assert len(dqlrefs.dataview_blocks(text)) == 2


def test_block_extraction_matches_fence_length():
    """A nested block inside a four-backtick fence must not truncate it —
    the trap docs/superpowers/lessons.md records."""
    text = "````markdown\n```dataview\nTABLE x\nFROM \"20-meetings\"\n```\n````\n"
    assert dqlrefs.dataview_blocks(text) == ['TABLE x\nFROM "20-meetings"']


# --- object-type resolution --------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("40-entities/acme/dossier.md", "entity"),
    ("30-projects/thing/index.md", "project"),
    ("30-projects/thing/decisions/2026-01-01-x.md", "decision"),
    ("50-people/jane-doe.md", "person"),
    ("20-meetings/01-01-26-standup.md", "meeting"),
    ("99-workflow-config/reference/ontology.md", None),
    ("30-projects/thing/notes/scratch.md", None),
])
def test_object_type_for_path(path, expected):
    assert dqlrefs.object_type_for_path(path) == expected


@pytest.mark.parametrize("folder,expected", [
    ("20-meetings", "meeting"),
    ("50-people", "person"),
    ("40-entities", "entity"),
    ("30-projects/anything/decisions", "decision"),
])
def test_folder_object_type_resolves_by_shape(folder, expected):
    assert dqlrefs.folder_object_type(folder) == expected


def test_a_project_decisions_folder_resolves_before_it_exists():
    """Two fixture projects have no decisions/ folder at all and their index
    still carries the decisions query — an empty table is the correct render.
    Resolving by folder *contents* read those as dangling references."""
    assert dqlrefs.folder_object_type("30-projects/brand-new-project/decisions") == "decision"


def test_ambiguous_from_folder_raises():
    """FROM "30-projects" would sweep in both projects and decisions. Guessing
    one would silently validate half the references against the wrong schema."""
    with pytest.raises(dqlrefs.UnmodeledQuery, match="mixes object types"):
        dqlrefs.folder_object_type("30-projects")


def test_unmodeled_from_folder_raises():
    """Where a typo'd or renamed folder lands."""
    with pytest.raises(dqlrefs.UnmodeledQuery):
        dqlrefs.folder_object_type("20-meetups")


def test_known_fields_comes_from_the_compiled_ontology():
    fields = dqlrefs.known_fields("meeting")
    assert {"attendees", "recording-duration", "review_status"} <= fields
    assert "project-name" not in fields


def test_known_fields_rejects_an_unknown_object():
    with pytest.raises(KeyError):
        dqlrefs.known_fields("sprocket")


# --- the real corpus ----------------------------------------------------

def test_the_fixture_corpus_actually_has_dataview_blocks():
    """Guards against this whole module passing vacuously if the blocks move."""
    assert len(NOTES_WITH_BLOCKS) >= 5


@pytest.mark.parametrize("root,note", NOTES_WITH_BLOCKS, ids=BLOCK_IDS)
def test_every_property_reference_resolves(root, note):
    note_rel = note.relative_to(root).as_posix()
    # A note that is not an ontology object (a dashboard, say) can still carry
    # a query — it just has nothing for `this.` to resolve against, so that is
    # only required below if the block actually uses `this.`.
    containing_type = dqlrefs.object_type_for_path(note_rel)

    for index, block in enumerate(dqlrefs.dataview_blocks(note.read_text(encoding="utf-8"))):
        refs = dqlrefs.extract_refs(block)
        assert len(refs.from_paths) == 1, f"{note_rel} block {index}: expected one FROM"
        queried_type = dqlrefs.folder_object_type(next(iter(refs.from_paths)))

        unknown = refs.properties - dqlrefs.known_fields(queried_type)
        assert not unknown, (
            f"{note_rel} block {index}: {sorted(unknown)} are not {queried_type} fields — "
            "the ontology renamed them, or the query is wrong. Either way the table "
            "renders empty in Obsidian."
        )
        bad_links = {(kind, name) for kind, name in refs.linked_properties
                     if name not in dqlrefs.known_fields(kind)}
        assert not bad_links, (
            f"{note_rel} block {index}: {sorted(bad_links)} read a field the linked "
            "note's object type does not have — the cell renders empty")
        if refs.this_properties:
            assert containing_type, (
                f"{note_rel} block {index}: uses `this.` but the note is not an "
                "ontology object, so `this.` has no schema to resolve against"
            )
        unknown_this = refs.this_properties - (
            dqlrefs.known_fields(containing_type) if containing_type else set())
        assert not unknown_this, (
            f"{note_rel} block {index}: this.{sorted(unknown_this)} are not "
            f"{containing_type} fields"
        )


@pytest.mark.parametrize("root,note", NOTES_WITH_BLOCKS, ids=BLOCK_IDS)
def test_a_per_project_from_path_names_its_own_project(root, note):
    """The copy-paste bug: a project's index querying another project's
    decisions folder. Renders plausible rows, all of them wrong."""
    note_rel = note.relative_to(root).as_posix()
    if dqlrefs.object_type_for_path(note_rel) != "project":
        pytest.skip("not a project index")
    own_folder = note_rel.rsplit("/", 1)[0]
    for index, block in enumerate(dqlrefs.dataview_blocks(note.read_text(encoding="utf-8"))):
        for from_path in dqlrefs.extract_refs(block).from_paths:
            if from_path.startswith("30-projects/"):
                assert from_path.startswith(own_folder + "/"), (
                    f"{note_rel} block {index}: queries {from_path!r}, "
                    f"which belongs to a different project"
                )


@pytest.mark.parametrize("root,note", NOTES_WITH_BLOCKS, ids=BLOCK_IDS)
def test_a_vault_root_from_folder_exists(root, note):
    """Existence is only meaningful for shared folders. A project's own
    decisions/ folder may legitimately not exist yet, so it is excluded — the
    test above pins that it names the right project instead."""
    for index, block in enumerate(dqlrefs.dataview_blocks(note.read_text(encoding="utf-8"))):
        for from_path in dqlrefs.extract_refs(block).from_paths:
            if "/" in from_path:
                continue
            assert (root / from_path).is_dir(), (
                f"{note.relative_to(root).as_posix()} block {index}: "
                f"FROM \"{from_path}\" is not a vault folder"
            )


def test_boolean_and_null_literals_are_not_properties():
    refs = dqlrefs.extract_refs('TABLE WITHOUT ID summary AS "Decision"\nFROM "30-projects"\n'
                                'WHERE archived != true AND reviewed != false AND x != null')
    for literal in ("true", "false", "null"):
        assert literal not in refs.properties
    assert {"archived", "reviewed", "x"} <= set(refs.properties)
