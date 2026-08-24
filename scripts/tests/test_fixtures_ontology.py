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
        if block.get("body_sections"):
            schema["body_sections"] = list(block["body_sections"])
        schemas[name] = schema
    return schemas


SCHEMAS = build_schemas()

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


def h2_titles(text: str) -> list:
    """H2 headings outside fenced code blocks."""
    titles, fence = [], None
    for line in text.split("\n"):
        token = line.strip()[:3]
        if token in ("```", "~~~"):
            fence = None if fence == token else (fence or token)
            continue
        if fence is None and line.startswith("## "):
            titles.append(line[3:].strip())
    return titles


@pytest.mark.parametrize("object_type", ["project", "entity"])
def test_body_sections_present_in_every_fixture(object_type):
    expected = SCHEMAS[object_type]["body_sections"]
    files = iter_fixture_files(SCHEMAS[object_type]["glob"])
    assert files, f"no {object_type} fixtures found"
    for path in files:
        assert h2_titles(path.read_text(encoding="utf-8")) == expected, (
            f"{path}: H2 sections do not match ontology body_sections for "
            f"{object_type}"
        )


def test_ontology_declares_body_sections_where_the_guard_expects_them():
    blocks = load_ontology_schemas()
    for name in ("project", "entity"):
        assert blocks[name].get("body_sections"), (
            f"ontology.md block {name!r}: body_sections is missing or empty"
        )


def test_project_indexes_scope_their_decisions_query_to_themselves():
    for path in iter_fixture_files(SCHEMAS["project"]["glob"]):
        slug = parse_frontmatter(path)["slug"]
        text = path.read_text(encoding="utf-8")
        assert f'FROM "30-projects/{slug}/decisions"' in text, (
            f"{path}: Decisions query must name this project's own slug — "
            "Dataview does not reliably accept this.file.folder as a source"
        )


def test_no_fixture_hardcodes_a_person_name_in_a_query():
    # The upstream Related Meetings query filtered the executive out by
    # display name. Nothing generated here may reintroduce that.
    for path in iter_fixture_files(SCHEMAS["project"]["glob"]):
        text = path.read_text(encoding="utf-8")
        assert "a !=" not in text, f"{path}: attendee self-filter reintroduced"


def test_exec_person_note_exists_and_is_referenced_as_an_owner():
    people = {parse_frontmatter(p)["slug"]
              for p in iter_fixture_files(SCHEMAS["person"]["glob"])}
    owners = {parse_frontmatter(p)["owner"]
              for p in iter_fixture_files(SCHEMAS["project"]["glob"])}
    assert owners <= people, f"project owners with no person note: {owners - people}"


def test_dossier_engagements_resolve_to_real_projects():
    project_slugs = slugs_of(SCHEMAS["project"]["glob"])
    for path in iter_fixture_files(SCHEMAS["entity"]["glob"]):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.\./\.\./30-projects/([a-z0-9-]+)/index\.md", text):
            assert match.group(1) in project_slugs, (
                f"{path}: Engagements row links to unknown project "
                f"{match.group(1)!r}"
            )


def test_no_decision_fixture_carries_tags():
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        assert "tags" not in parse_frontmatter(path), (
            f"{path}: decision tags were dropped from the ontology"
        )


def test_every_decision_fixture_declares_whether_it_was_reviewed():
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        fm = parse_frontmatter(path)
        assert isinstance(fm.get("reviewed"), bool), (
            f"{path}: reviewed must be present and boolean — Decisions.base's "
            "'Needs review' view filters on it, and a missing key makes that "
            "view silently incomplete"
        )


def test_decision_fixtures_demonstrate_both_review_states():
    seen = {parse_frontmatter(p)["reviewed"]
            for p in iter_fixture_files(SCHEMAS["decision"]["glob"])}
    assert seen == {True, False}, (
        "fixtures must show an unattended capture as well as a validated one"
    )


def test_every_decision_body_carries_the_three_bold_markers():
    # Decisions use bold markers rather than H2s, so body_sections does not
    # apply and this is the guard that replaces it.
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        text = path.read_text(encoding="utf-8")
        for marker in ("**Decision**", "**Why**", "**Implications**"):
            assert marker in text, f"{path}: body is missing {marker}"


def test_decision_object_declares_no_body_sections():
    assert not load_ontology_schemas()["decision"].get("body_sections"), (
        "decision bodies are bold markers, not H2 sections"
    )


SUPERSEDED_FOOTER_RE = re.compile(
    r"^\*\*Superseded\*\* — (\d{4}-\d{2}-\d{2}) · replaced by \[\[([^\]]+)\]\]\.$",
    re.MULTILINE,
)
WIKILINK_RE = re.compile(r"\A\[\[([^\]|]+)\]\]\Z")


def _decision_stems_by_project() -> dict:
    index: dict = {}
    for path in iter_fixture_files(SCHEMAS["decision"]["glob"]):
        index.setdefault(path.parent.parent.name, {})[path.stem] = path
    return index


def test_every_supersedes_edge_resolves_and_flips_its_target():
    """Both sides of the edge, on real files. This is the two-sided procedure
    the ontology now states; before P1b it was only demonstrated, never
    checked."""
    index = _decision_stems_by_project()
    for project, notes in index.items():
        for stem, path in notes.items():
            raw = parse_frontmatter(path).get("supersedes")
            if raw in (None, ""):
                continue
            match = WIKILINK_RE.match(str(raw).strip())
            assert match, (
                f"{path}: supersedes must be a quoted wikilink — unquoted "
                "[[x]] parses as a nested YAML list"
            )
            target_stem = match.group(1)
            assert target_stem in notes, (
                f"{path}: supersedes {target_stem!r} is not a decision in "
                f"{project}'s decisions folder"
            )
            target = notes[target_stem]
            assert parse_frontmatter(target)["status"] == "superseded", (
                f"{target}: superseded by {stem} but its status was not flipped"
            )
            footer = SUPERSEDED_FOOTER_RE.search(
                target.read_text(encoding="utf-8"))
            assert footer, f"{target}: missing the **Superseded** footer"
            assert footer.group(2) == stem, (
                f"{target}: footer points at {footer.group(2)!r}, not {stem!r}"
            )


def test_no_superseded_decision_lacks_an_incoming_edge():
    for project, notes in _decision_stems_by_project().items():
        superseded = {stem for stem, path in notes.items()
                      if parse_frontmatter(path)["status"] == "superseded"}
        claimed = set()
        for path in notes.values():
            raw = parse_frontmatter(path).get("supersedes")
            match = WIKILINK_RE.match(str(raw).strip()) if raw else None
            if match:
                claimed.add(match.group(1))
        assert superseded <= claimed, (
            f"{project}: superseded with no successor: {superseded - claimed}"
        )


BASE_PROPERTY_EXEMPTIONS = {"file.name", "file.path", "file.mtime"}


def test_decisions_base_columns_all_exist_in_the_ontology():
    """The drift guard the tags removal needs: a Base column for a field the
    ontology does not define renders an empty column in the client's vault."""
    base = ONTOLOGY_DOC.parents[2] / "30-projects" / "Decisions.base"
    config = yaml.safe_load(base.read_text(encoding="utf-8"))
    block = load_ontology_schemas()["decision"]
    known = (set(block.get("required") or [])
             | set(block.get("optional") or [])
             | set(block.get("keys_present") or []))
    for name in config.get("properties", {}):
        if name.startswith("formula.") or name in BASE_PROPERTY_EXEMPTIONS:
            continue
        assert name in known, (
            f"Decisions.base declares property {name!r}, which ontology.md "
            "§Decision does not define"
        )


def test_decisions_base_has_a_needs_review_view():
    base = ONTOLOGY_DOC.parents[2] / "30-projects" / "Decisions.base"
    config = yaml.safe_load(base.read_text(encoding="utf-8"))
    names = [view.get("name") for view in config.get("views", [])]
    assert "Needs review" in names, (
        f"the unattended-capture audit needs its own view; found {names}"
    )


# --- Meeting confidence vocabulary (loaded from the ontology, not hand-encoded) ---

_MEETING_BLOCK = load_ontology_schemas()["meeting"]
CONFIDENCE_REASON_GROUPS = _MEETING_BLOCK["confidence_reasons"]
NEW_ATTENDEES_RE = re.compile(r"\Anew-attendees:[1-9]\d*\Z")


def test_meeting_block_carries_reason_groups():
    assert set(CONFIDENCE_REASON_GROUPS) == {"calendar", "project-link", "attendees"}
    assert "calendar-tool-unavailable" in CONFIDENCE_REASON_GROUPS["calendar"]
    assert "no-calendar-match" in CONFIDENCE_REASON_GROUPS["calendar"]
    assert "entity-domain-match" in CONFIDENCE_REASON_GROUPS["project-link"]
    assert CONFIDENCE_REASON_GROUPS["attendees"] == ["all-attendees-known"]


def _matches_attendees_group(reason):
    return reason in CONFIDENCE_REASON_GROUPS["attendees"] or NEW_ATTENDEES_RE.match(reason)


def test_meeting_confidence_reasons_conform():
    """Where a meeting carries a confidence stamp, it is complete and closed-
    vocabulary: exactly one reason per group, and rating and reasons travel
    together."""
    for path in iter_fixture_files(SCHEMAS["meeting"]["glob"]):
        fm = parse_frontmatter(path)
        has_rating = "confidence" in fm
        has_reasons = "confidence-reasons" in fm
        assert has_rating == has_reasons, (
            f"{path}: confidence and confidence-reasons must travel together"
        )
        if not has_reasons:
            continue
        reasons = fm["confidence-reasons"]
        assert isinstance(reasons, list) and len(reasons) == 3, (
            f"{path}: expected exactly 3 reasons (one per group), got {reasons!r}"
        )
        cal = [r for r in reasons if r in CONFIDENCE_REASON_GROUPS["calendar"]]
        proj = [r for r in reasons if r in CONFIDENCE_REASON_GROUPS["project-link"]]
        att = [r for r in reasons if _matches_attendees_group(r)]
        assert len(cal) == 1, f"{path}: need exactly one calendar reason, got {cal}"
        assert len(proj) == 1, f"{path}: need exactly one project-link reason, got {proj}"
        assert len(att) == 1, f"{path}: need exactly one attendees reason, got {att}"
