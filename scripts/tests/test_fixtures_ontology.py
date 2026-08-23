"""Ontology conformance guard for fixtures/demo-vault/.

Walks the demo-vault fixture tree and checks each object note's frontmatter
against the ontology's normative schema. The schema is NOT hand-encoded
here: template/99-workflow-config/reference/ontology.md carries one fenced
yaml block per object type (keyed by `object:`), and this module loads them
at import time — editing a block IS editing what this guard enforces.
Harness-only concerns (which files to walk, slug-join rules, fixture
minimums, coverage targets) stay here: they describe the demo fixtures and
this test harness, not the ontology.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"
ONTOLOGY_DOC = REPO_ROOT / "template" / "99-workflow-config" / "reference" / "ontology.md"

YAML_FENCE_RE = re.compile(r"^```yaml\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

# Test-harness concerns per object type: where fixtures live and which
# slug-join rules the demo vault must satisfy. Schema truth lives in
# ONTOLOGY_DOC, not here.
HARNESS = {
    "entity": {"glob": "40-entities/*/dossier.md", "slug_must_match_parent_dir": True},
    "project": {"glob": "30-projects/*/index.md", "slug_must_match_parent_dir": True},
    "person": {"glob": "50-people/*.md", "slug_must_match_stem": True},
    "decision": {"glob": "30-projects/*/decisions/*.md"},
    "meeting": {"glob": "20-meetings/*.md"},
}


def load_ontology_schemas() -> dict:
    """Parse ONTOLOGY_DOC's fenced yaml blocks; return {object-name: block}
    for every block carrying an `object:` key. Narrative example blocks
    (no `object:` key) are skipped. Malformed or duplicate blocks raise —
    a broken ontology doc must fail loudly, not validate vacuously."""
    text = ONTOLOGY_DOC.read_text(encoding="utf-8")
    blocks: dict = {}
    for match in YAML_FENCE_RE.finditer(text):
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError as e:
            raise RuntimeError(f"{ONTOLOGY_DOC}: unparseable yaml block: {e}") from e
        if not isinstance(data, dict) or "object" not in data:
            continue
        name = data["object"]
        if name in blocks:
            raise RuntimeError(f"{ONTOLOGY_DOC}: duplicate schema block for {name!r}")
        blocks[name] = data
    return blocks


def build_schemas() -> dict:
    """Merge the ontology's normative blocks with the harness config."""
    ontology = load_ontology_schemas()
    missing = set(HARNESS) - set(ontology)
    if missing:
        raise RuntimeError(f"{ONTOLOGY_DOC}: missing schema block(s) for {sorted(missing)}")
    schemas = {}
    for name, harness in HARNESS.items():
        block = ontology[name]
        schema = dict(harness)
        schema["required"] = list(block.get("required") or [])
        schema["enums"] = {field: set(values) for field, values in (block.get("enums") or {}).items()}
        if block.get("keys_present"):
            schema["keys_present"] = list(block["keys_present"])
        schemas[name] = schema
    return schemas


SCHEMAS = build_schemas()

_DECISION_TAGS = load_ontology_schemas()["decision"]["tags"]
DECISION_TAGS_VOCABULARY = set(_DECISION_TAGS["vocabulary"])
DECISION_TAGS_MAX = int(_DECISION_TAGS["max"])

MINIMUMS = {"entity": 3, "project": 4, "person": 8, "meeting": 6, "decision": 2}


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: missing YAML frontmatter"
    end = text.find("\n---", 4)
    assert end != -1, f"{path}: unterminated YAML frontmatter"
    data = yaml.safe_load(text[4:end])
    assert isinstance(data, dict), f"{path}: frontmatter is not a mapping"
    return data


def iter_fixture_files(glob: str) -> list[Path]:
    if not FIXTURE_ROOT.is_dir():
        return []
    return sorted(FIXTURE_ROOT.glob(glob))


@pytest.mark.parametrize("object_type", sorted(SCHEMAS))
def test_object_type_has_minimum_fixtures(object_type):
    files = iter_fixture_files(SCHEMAS[object_type]["glob"])
    assert len(files) >= MINIMUMS[object_type], (
        f"expected at least {MINIMUMS[object_type]} {object_type} fixtures, found {len(files)}"
    )


@pytest.mark.parametrize("object_type", sorted(SCHEMAS))
def test_object_type_frontmatter_conforms(object_type):
    schema = SCHEMAS[object_type]
    for path in iter_fixture_files(schema["glob"]):
        fm = parse_frontmatter(path)
        for field in schema["required"]:
            assert field in fm and fm[field] not in (None, ""), (
                f"{path}: missing required field {field!r}"
            )
        for field in schema.get("keys_present", []):
            assert field in fm, f"{path}: missing required key {field!r} (value may be null)"
        for field, allowed in schema.get("enums", {}).items():
            if field in fm:
                assert fm[field] in allowed, f"{path}: {field}={fm[field]!r} not in {allowed}"
        if schema.get("slug_must_match_parent_dir"):
            assert fm["slug"] == path.parent.name, (
                f"{path}: slug {fm['slug']!r} != folder {path.parent.name!r}"
            )
        if schema.get("slug_must_match_stem"):
            assert fm["slug"] == path.stem, (
                f"{path}: slug {fm['slug']!r} != filename {path.stem!r}"
            )


def test_project_type_enum_fully_covered():
    files = iter_fixture_files(SCHEMAS["project"]["glob"])
    seen = {parse_frontmatter(p).get("project-type") for p in files}
    expected = SCHEMAS["project"]["enums"]["project-type"]
    assert seen == expected, f"missing project-type coverage: {expected - seen}"


def test_meeting_review_status_enum_fully_covered():
    files = iter_fixture_files(SCHEMAS["meeting"]["glob"])
    seen = {parse_frontmatter(p).get("review_status") for p in files}
    expected = SCHEMAS["meeting"]["enums"]["review_status"]
    assert seen == expected, f"missing review_status coverage: {expected - seen}"


def test_meeting_type_enum_broadly_covered():
    files = iter_fixture_files(SCHEMAS["meeting"]["glob"])
    seen = {parse_frontmatter(p).get("type") for p in files}
    assert len(seen) >= 4, f"only {len(seen)} distinct meeting types in fixtures: {seen}"


def test_at_least_one_uncurated_person():
    files = iter_fixture_files(SCHEMAS["person"]["glob"])
    assert any(parse_frontmatter(p).get("relationship") is None for p in files), (
        "expected at least one person fixture with relationship: null (uncurated)"
    )


def test_decision_supersession_chain_exists():
    files = iter_fixture_files(SCHEMAS["decision"]["glob"])
    supersedes = [parse_frontmatter(p).get("supersedes") for p in files]
    assert any(s not in (None, "") for s in supersedes), (
        "expected at least one decision with a supersedes edge"
    )


def test_decision_status_enum_fully_covered():
    files = iter_fixture_files(SCHEMAS["decision"]["glob"])
    seen = {parse_frontmatter(p).get("status") for p in files}
    expected = SCHEMAS["decision"]["enums"]["status"]
    assert seen == expected, f"missing decision status coverage: {expected - seen}"


def test_decision_tags_within_controlled_vocabulary():
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        tags = parse_frontmatter(path).get("tags") or []
        assert len(tags) <= DECISION_TAGS_MAX, f"{path}: more than {DECISION_TAGS_MAX} tags"
        for tag in tags:
            assert tag in DECISION_TAGS_VOCABULARY, f"{path}: tag {tag!r} not in vocabulary"


def test_entity_fixtures_cover_multiple_types_and_statuses():
    fms = [parse_frontmatter(p) for p in iter_fixture_files(SCHEMAS["entity"]["glob"])]
    if not fms:
        pytest.fail("no entity fixtures found")
    assert {"client", "business-unit"} <= {fm.get("entity-type") for fm in fms}
    assert {"prospect", "active"} <= {fm.get("status") for fm in fms}


def slugs_of(glob: str) -> set:
    return {parse_frontmatter(p).get("slug") for p in iter_fixture_files(glob)}


def test_project_entity_joins_resolve():
    entity_slugs = slugs_of(SCHEMAS["entity"]["glob"])
    for path in iter_fixture_files(SCHEMAS["project"]["glob"]):
        entity = parse_frontmatter(path).get("entity")
        assert entity in entity_slugs, f"{path}: entity {entity!r} matches no entity fixture"


def test_meeting_edges_resolve():
    project_slugs = slugs_of(SCHEMAS["project"]["glob"])
    person_slugs = slugs_of(SCHEMAS["person"]["glob"])
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        fm = parse_frontmatter(path)
        for slug in fm.get("projects") or []:
            assert slug in project_slugs, f"{path}: project {slug!r} matches no project fixture"
        for slug in fm.get("attendees") or []:
            assert slug in person_slugs, f"{path}: attendee {slug!r} matches no person fixture"


def test_decision_project_matches_its_folder():
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        project = parse_frontmatter(path).get("project")
        folder = path.parent.parent.name
        assert project == folder, f"{path}: project {project!r} != folder {folder!r}"


CONTEXT_PORTFOLIO_FILES = [
    "identity.md",
    "role-and-responsibilities.md",
    "communication-style.md",
    "preferences-and-constraints.md",
    "tools-and-systems.md",
]


def test_context_portfolio_is_filled_not_placeholder():
    portfolio_dir = FIXTURE_ROOT / "99-workflow-config" / "context"
    assert portfolio_dir.is_dir(), "fixtures/demo-vault/99-workflow-config/context/ is missing"
    for name in CONTEXT_PORTFOLIO_FILES:
        path = portfolio_dir / name
        assert path.is_file(), f"missing context portfolio fixture: {name}"
        text = path.read_text(encoding="utf-8")
        assert "Placeholder." not in text, f"{path}: still contains the placeholder banner"
        begin = text.find("<!-- setup-my-brain:begin -->")
        end = text.find("<!-- setup-my-brain:end -->")
        assert begin != -1 and end != -1 and end > begin + len("<!-- setup-my-brain:begin -->") + 1, (
            f"{path}: setup-my-brain content block is empty"
        )


def test_ontology_schema_blocks_present_and_wellformed():
    """The guard's schemas come FROM ontology.md — this test locks the
    contract: five object blocks, each with non-empty required fields, and
    enums shaped as field -> list."""
    blocks = load_ontology_schemas()
    assert set(blocks) == set(HARNESS), (
        f"ontology.md schema blocks {sorted(blocks)} != expected object types {sorted(HARNESS)}"
    )
    for name, block in blocks.items():
        assert block.get("required"), f"ontology.md block {name!r}: empty or missing 'required'"
        for field, values in (block.get("enums") or {}).items():
            assert isinstance(values, list) and values, (
                f"ontology.md block {name!r}: enum {field!r} must be a non-empty list"
            )
