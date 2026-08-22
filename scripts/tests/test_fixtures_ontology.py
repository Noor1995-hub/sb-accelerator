"""Ontology conformance guard for fixtures/demo-vault/.

Walks the demo-vault fixture tree and checks each object note's frontmatter
against the schemas and enums documented in
template/99-workflow-config/reference/ontology.md — the authority. That doc
is prose plus one YAML example, not a machine-readable schema, so this
module hand-encodes it as a checkable one. Also checks the fixture set's
overall shape against issue #24's deliverable (minimum counts, enum
coverage), so the fixtures stay a real conformance test as they grow rather
than a pile of unchecked sample content.
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"

SCHEMAS = {
    "entity": {
        "glob": "40-entities/*/dossier.md",
        "required": ["type", "entity-name", "slug", "status"],
        "enums": {
            "status": {"prospect", "active", "dormant"},
            "entity-type": {"client", "business-unit", "partner", "supplier", "other"},
        },
        "slug_must_match_parent_dir": True,
    },
    "project": {
        "glob": "30-projects/*/index.md",
        "required": [
            "project-name", "slug", "status", "project-type", "entity",
            "owner", "created", "last-updated",
        ],
        "enums": {
            "status": {"active", "paused", "completed", "cancelled"},
            "project-type": {"presales", "delivery", "internal", "area-of-responsibility"},
        },
        "slug_must_match_parent_dir": True,
    },
    "person": {
        "glob": "50-people/*.md",
        "required": ["person-name", "slug"],
        "keys_present": ["relationship"],
        "enums": {"relationship": {"colleague", "direct-report", "external", None}},
        "slug_must_match_stem": True,
    },
    "decision": {
        "glob": "30-projects/*/decisions/*.md",
        "required": ["type", "project", "date", "status", "summary"],
        "enums": {
            "status": {"active", "superseded", "withdrawn"},
            "type": {"decision"},
        },
    },
    "meeting": {
        "glob": "20-meetings/*.md",
        "required": [
            "date", "type", "calendar-subject", "calendar_match", "attendees",
            "projects", "review_status", "recording-duration", "source", "processed",
        ],
        "enums": {
            "type": {"meeting", "1:1", "steerco", "workshop", "brainstorm", "status-update"},
            "review_status": {"needs-review", "confirmed", "needs-attention"},
        },
    },
}

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


DECISION_TAGS_VOCABULARY = {
    "scope", "platform", "staffing", "methodology", "commercial", "timing", "stakeholder",
}


def test_decision_tags_within_controlled_vocabulary():
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        tags = parse_frontmatter(path).get("tags") or []
        assert len(tags) <= 2, f"{path}: more than 2 tags"
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
