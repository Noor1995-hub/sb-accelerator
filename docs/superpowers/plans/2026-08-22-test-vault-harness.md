# Test-Vault Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the project a hand-testable demo vault (`fixtures/demo-vault/`), a script that instantiates it (`scripts/make_test_vault.py`), a CI guard that keeps the fixtures conformant to the ontology, and a runbook that walks a fresh tester through the whole thing end to end — closing GitHub issue #24.

**Architecture:** `fixtures/demo-vault/` is a content overlay with the exact same folder shape as `template/`: one fictional CCO persona (Morgan Ellery, Cascadia Intermodal Group) with entities, people, projects, decisions, meetings, a filled context portfolio, daily notes, and raw inbox captures. `scripts/make_test_vault.py` copies `template/` into a target directory and then copies `fixtures/demo-vault/` on top (skipped with `--fresh`). A new pytest module (`scripts/tests/test_fixtures_ontology.py`) hand-encodes the required fields and enums from `template/99-workflow-config/reference/ontology.md` and walks the fixture tree asserting conformance and coverage — it is written first (red, since no fixtures exist yet) and goes green as each object type's fixtures are added. `scripts/lint_plugin.py`'s clean-room scan is widened to cover `fixtures/` too, since the tree is invented-cast-only but still must never leak real names. `docs/local-setup.md` gets a runbook section replacing its current stale scratch-vault snippet.

**Tech Stack:** Python 3.13, pytest, PyYAML (all already repo dependencies — see `docs/local-setup.md`). No new dependencies.

**Spec:** GitHub issue #24 (`Test-vault harness: demo fixtures + make_test_vault script (slop guard)`), read via `gh issue view 24`. Authoritative schema: `template/99-workflow-config/reference/ontology.md`. Clean-room rule: repo-root `CLAUDE.md`.

## Global Constraints

- **Clean-room rule:** nothing under `fixtures/` may reference delaware clients, Michael, or busdev content — same rule as `plugin/`/`template/`, extended mechanically in Task 1. The persona (Morgan Ellery, Cascadia Intermodal Group, Nordbridge Components, Meridian Freight Holdings) is entirely invented; no resemblance to real delaware clients is intended or permitted.
- **Dates in frontmatter are unquoted ISO** (`2026-02-07`, not `"2026-02-07"`) — quoted dates silently break Bases/Dataview date handling (ontology.md, section "Entity").
- **Slugs are lowercase-hyphenated** and are join keys: an entity's `slug:` must equal its folder name; a project's `slug:` must equal its folder name; a person's `slug:` must equal its filename stem (`template/CLAUDE.md`, "Key Patterns → Slugs").
- **Decision notes are never deleted** — status flips only (`active` → `superseded`/`withdrawn`); body pattern is exactly `**Decision** — / **Why** — / **Implications**` (`template/CLAUDE.md`, "Decision Notes").
- **Commit trailer**, every commit: `Co-Authored-By: Claude <noreply@anthropic.com>` (`CONTRIBUTING.md`).
- **Branch naming:** `feat/<short-description>` (this plan targets `feat/test-vault-harness`).
- **No plugin/ version bump needed** — this work touches `fixtures/`, `scripts/`, and `docs/` only, never `plugin/`.
- **Local verification commands** (must all pass before considering the plan done): `python scripts/lint_plugin.py`, `python scripts/validate_template.py`, `python -m pytest scripts/tests -q` (use `python3` if `python` isn't on PATH).
- **`fixtures/` never ships** — no packaging script currently exists that would need updating to exclude it; this is a documentation/convention fact (issue #24 body), not a code change.

---

## File structure

| File | Responsibility |
|---|---|
| `fixtures/demo-vault/40-entities/{slug}/dossier.md` (×3) | Entity fixtures: one prospect client, one active client, one active business unit |
| `fixtures/demo-vault/50-people/{slug}.md` (×9) | Person fixtures, incl. one uncurated (`relationship: null`) |
| `fixtures/demo-vault/30-projects/{slug}/index.md` (×5) | Project fixtures covering all 4 `project-type` enum values |
| `fixtures/demo-vault/30-projects/{slug}/decisions/*.md` (×4) | Decision fixtures incl. one supersession chain and all 3 `status` enum values |
| `fixtures/demo-vault/20-meetings/{DD-MM-YY-slug}.md` (×8) | Meeting fixtures covering type/review_status enums and Meetings.base Triage-view edge cases |
| `fixtures/demo-vault/99-workflow-config/context/*.md` (×5) | Filled context portfolio overlay (overwrites the template's placeholder files) |
| `fixtures/demo-vault/60-daily-notes/*.md` (×3) | Daily notes referencing the meeting/decision fixtures |
| `fixtures/demo-vault/10-inbox/*.txt` (×3) | Raw unprocessed captures: Teams transcript, voice memo, forwarded email |
| `scripts/tests/test_fixtures_ontology.py` | New pytest module: ontology conformance + coverage guard over `fixtures/demo-vault/` |
| `scripts/lint_plugin.py` | Modified: clean-room scan also covers `fixtures/` |
| `scripts/tests/test_lint_plugin.py` | Modified: new test locking the `fixtures/` scan coverage |
| `scripts/make_test_vault.py` | New script: instantiate `template/` (+ fixtures overlay, unless `--fresh`) into a target dir |
| `scripts/tests/test_make_test_vault.py` | New tests for `make_test_vault.py` |
| `docs/local-setup.md` | Modified: replace the stale scratch-vault section with the end-to-end runbook |

---

### Task 1: Widen the clean-room lint to scan `fixtures/`

**Files:**
- Modify: `scripts/lint_plugin.py:2,8,78`
- Test: `scripts/tests/test_lint_plugin.py`

**Interfaces:**
- Consumes: nothing new — `scan_cleanroom(root: Path, terms: list[str]) -> list[str]` already exists.
- Produces: `scan_cleanroom` now also walks `root / "fixtures"` when present. No signature change, so no other task depends on this beyond "the fixtures written later must pass this scan."

- [ ] **Step 1: Write the failing test**

Add to `scripts/tests/test_lint_plugin.py` (after `test_cleanroom_violation_in_template_fails`):

```python
def test_cleanroom_violation_in_fixtures_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "fixtures" / "demo-vault" / "50-people").mkdir(parents=True)
    (root / "fixtures" / "demo-vault" / "50-people" / "note.md").write_text(
        "Contact Michael about this.\n", encoding="utf-8"
    )
    problems = main(root)
    assert any("michael" in p.lower() for p in problems)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest scripts/tests/test_lint_plugin.py -k fixtures -v`
Expected: FAIL — `scan_cleanroom` doesn't scan `fixtures/` yet, so `problems` is empty and the `any(...)` assertion fails.

- [ ] **Step 3: Widen the scan**

In `scripts/lint_plugin.py`, line 78, change:

```python
    for tree in ("plugin", "template"):
```

to:

```python
    for tree in ("plugin", "template", "fixtures"):
```

Also update the two docstring lines that enumerate the scanned trees so the module header stays accurate. Line 2:

```python
"""Skill frontmatter lint + clean-room scan for plugin/, template/, and fixtures/.
```

Line 8:

```python
2. No denylisted term (scripts/cleanroom-denylist.txt, case-insensitive
   substrings) appears in any text file under plugin/, template/, or
   fixtures/ — the clean-room rule from CLAUDE.md. plugin/ and template/
   ship to clients; fixtures/ never ships but must stay just as clean.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest scripts/tests/test_lint_plugin.py -v`
Expected: all tests PASS, including the new `test_cleanroom_violation_in_fixtures_fails`.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint_plugin.py scripts/tests/test_lint_plugin.py
git commit -m "$(cat <<'EOF'
fix: scan fixtures/ in the clean-room lint

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Write the ontology conformance pytest guard (red)

**Files:**
- Create: `scripts/tests/test_fixtures_ontology.py`

**Interfaces:**
- Consumes: nothing (reads `fixtures/demo-vault/` directly from disk via `REPO_ROOT`, same pattern as `test_lint_plugin.py`'s `REPO_ROOT = Path(__file__).resolve().parents[2]`).
- Produces: this is the acceptance test every later fixture-creation task (3–8) is written against. `SCHEMAS` dict keys (`entity`, `project`, `person`, `decision`, `meeting`) and the glob patterns inside it are the contract later tasks' file paths must satisfy.

- [ ] **Step 1: Write the test module**

Create `scripts/tests/test_fixtures_ontology.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails (red)**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -v`
Expected: FAIL across the board — `fixtures/demo-vault/` does not exist yet, so every minimum-count and enum-coverage assertion fails with messages like `expected at least 3 entity fixtures, found 0`. This is the correct starting state; Tasks 3–8 turn these green incrementally.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_fixtures_ontology.py
git commit -m "$(cat <<'EOF'
test: add ontology conformance guard for demo-vault fixtures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Entity fixtures (3)

**Files:**
- Create: `fixtures/demo-vault/40-entities/nordbridge-components/dossier.md`
- Create: `fixtures/demo-vault/40-entities/meridian-freight-holdings/dossier.md`
- Create: `fixtures/demo-vault/40-entities/commercial-operations/dossier.md`

**Interfaces:**
- Consumes: `SCHEMAS["entity"]` from Task 2 (`glob: "40-entities/*/dossier.md"`, required fields `type, entity-name, slug, status`, `entity-type`/`status` enums, slug-must-match-folder).
- Produces: entity slugs `nordbridge-components`, `meridian-freight-holdings`, `commercial-operations` — Task 5 (projects) and Task 4 (people, via `company:`) reference these exact slugs/names.

- [ ] **Step 1: Create the prospect client entity**

Create `fixtures/demo-vault/40-entities/nordbridge-components/dossier.md`:

```markdown
---
type: entity
entity-name: "Nordbridge Components"
slug: nordbridge-components
entity-type: client
status: prospect
industry: "Industrial components manufacturing"
owner: jordan-vance
created: 2026-02-01
last-updated: 2026-06-12
---

## Overview

Tier-2 automotive and industrial components manufacturer, ~2,200 employees
across three plants. Introduced by [[jordan-vance]] via an industry
conference; no prior commercial relationship with Cascadia Intermodal.

## Key contacts

- [[dana-whitfield]] — VP Procurement, primary buyer-side contact.

## Relationship history

Intro call held 2026-03-02 ([[02-03-26-nordbridge-intro-call]]). Initial pilot
site proposal withdrawn after an unrelated ERP migration freeze
([[2026-03-02-pilot-site-selection-withdrawn]]); regional rollout proposal
now in progress under [[nordbridge-regional-rollout-proposal]].
```

- [ ] **Step 2: Create the active client entity**

Create `fixtures/demo-vault/40-entities/meridian-freight-holdings/dossier.md`:

```markdown
---
type: entity
entity-name: "Meridian Freight Holdings"
slug: meridian-freight-holdings
entity-type: client
status: active
industry: "Freight & logistics"
owner: priya-nathan
created: 2025-09-15
last-updated: 2026-06-01
---

## Overview

Mid-size regional freight operator running three yards. Existing client since
the Phase 0 warehouse pilot; now in delivery on the full yard-automation
program.

## Key contacts

- [[leo-marchetti]] — Chief Operating Officer, executive sponsor.
- [[renee-castillo]] — IT Director, technical stakeholder.

## Relationship history

Phase 0 warehouse pilot ([[meridian-warehouse-pilot-phase-0]]) completed
2026-02. Yard automation program ([[meridian-yard-automation-program]]) is
the active delivery engagement, including one vendor-strategy supersession
(see [[2026-05-20-single-vendor-strategy-adopted]]).
```

- [ ] **Step 3: Create the internal business-unit entity**

Create `fixtures/demo-vault/40-entities/commercial-operations/dossier.md`:

```markdown
---
type: entity
entity-name: "Commercial Operations"
slug: commercial-operations
entity-type: business-unit
status: active
industry: "Internal — commercial organization"
owner: sam-okafor
created: 2025-06-01
last-updated: 2026-06-05
---

## Overview

Internal business unit covering CRM/pipeline tooling and process governance
for the whole commercial organization. Led by [[sam-okafor]], reporting to
the CCO.

## Key contacts

- [[sam-okafor]] — VP, Commercial Operations.
- [[omar-siddiqui]] — Analytics Lead.

## Relationship history

CRM data modernization ([[commercial-ops-crm-modernization]]) and pipeline
governance ([[commercial-ops-pipeline-governance]]) are the two active
projects under this unit.
```

- [ ] **Step 4: Run the ontology test to confirm entity coverage is green**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -k entity -v`
Expected: `test_object_type_has_minimum_fixtures[entity]` and
`test_object_type_frontmatter_conforms[entity]` PASS. (Wikilinks to
`jordan-vance`, `priya-nathan`, etc. don't resolve yet — that's expected
until Task 4; frontmatter conformance doesn't check body links.)

- [ ] **Step 5: Commit**

```bash
git add fixtures/demo-vault/40-entities
git commit -m "$(cat <<'EOF'
feat: add demo-vault entity fixtures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Person fixtures (9, incl. one uncurated)

**Files:**
- Create: `fixtures/demo-vault/50-people/jordan-vance.md`
- Create: `fixtures/demo-vault/50-people/priya-nathan.md`
- Create: `fixtures/demo-vault/50-people/sam-okafor.md`
- Create: `fixtures/demo-vault/50-people/dana-whitfield.md`
- Create: `fixtures/demo-vault/50-people/leo-marchetti.md`
- Create: `fixtures/demo-vault/50-people/renee-castillo.md`
- Create: `fixtures/demo-vault/50-people/omar-siddiqui.md`
- Create: `fixtures/demo-vault/50-people/taylor-brooks.md`
- Create: `fixtures/demo-vault/50-people/jamie-ellwood.md`

**Interfaces:**
- Consumes: `SCHEMAS["person"]` from Task 2 (required `person-name, slug`; `relationship` key must be present, enum incl. `None`; slug-must-match-filename-stem).
- Produces: person slugs referenced as `owner:`/`stakeholders:` on projects (Task 5) and `attendees:` on meetings (Task 6): `jordan-vance, priya-nathan, sam-okafor, dana-whitfield, leo-marchetti, renee-castillo, omar-siddiqui, taylor-brooks, jamie-ellwood`.

- [ ] **Step 1: Create the two account-owning colleagues**

Create `fixtures/demo-vault/50-people/jordan-vance.md`:

```markdown
---
person-name: "Jordan Vance"
slug: jordan-vance
email: jordan.vance@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Sales Director, New Logo"
projects: [nordbridge-regional-rollout-proposal]
created: 2026-02-01
last-updated: 2026-06-12
meetings-7d: 0
meetings-30d: 2
---
```

Create `fixtures/demo-vault/50-people/priya-nathan.md`:

```markdown
---
person-name: "Priya Nathan"
slug: priya-nathan
email: priya.nathan@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Account Director, Meridian Freight"
projects: [meridian-yard-automation-program, meridian-warehouse-pilot-phase-0]
created: 2025-09-15
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 3
---
```

- [ ] **Step 2: Create the two direct reports**

Create `fixtures/demo-vault/50-people/sam-okafor.md`:

```markdown
---
person-name: "Sam Okafor"
slug: sam-okafor
email: sam.okafor@cascadia-intermodal.example
relationship: direct-report
company: "Cascadia Intermodal Group"
role: "VP, Commercial Operations"
projects: [commercial-ops-crm-modernization, commercial-ops-pipeline-governance]
created: 2025-06-01
last-updated: 2026-06-05
meetings-7d: 0
meetings-30d: 3
---
```

Create `fixtures/demo-vault/50-people/omar-siddiqui.md`:

```markdown
---
person-name: "Omar Siddiqui"
slug: omar-siddiqui
email: omar.siddiqui@cascadia-intermodal.example
relationship: direct-report
company: "Cascadia Intermodal Group"
role: "Analytics Lead, Commercial Operations"
projects: [commercial-ops-crm-modernization]
created: 2025-06-01
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 2
---
```

- [ ] **Step 3: Create the three external client contacts**

Create `fixtures/demo-vault/50-people/dana-whitfield.md`:

```markdown
---
person-name: "Dana Whitfield"
slug: dana-whitfield
email: dana.whitfield@nordbridge.example
relationship: external
company: "Nordbridge Components"
role: "VP Procurement"
projects: [nordbridge-regional-rollout-proposal]
created: 2026-03-02
last-updated: 2026-03-02
meetings-7d: 0
meetings-30d: 1
---
```

Create `fixtures/demo-vault/50-people/leo-marchetti.md`:

```markdown
---
person-name: "Leo Marchetti"
slug: leo-marchetti
email: leo.marchetti@meridianfreight.example
relationship: external
company: "Meridian Freight Holdings"
role: "Chief Operating Officer"
projects: [meridian-yard-automation-program]
created: 2026-03-10
last-updated: 2026-05-20
meetings-7d: 0
meetings-30d: 2
---
```

Create `fixtures/demo-vault/50-people/renee-castillo.md`:

```markdown
---
person-name: "Renee Castillo"
slug: renee-castillo
email: renee.castillo@meridianfreight.example
relationship: external
company: "Meridian Freight Holdings"
role: "IT Director"
projects: [meridian-yard-automation-program]
created: 2026-03-10
last-updated: 2026-03-10
meetings-7d: 0
meetings-30d: 1
---
```

- [ ] **Step 4: Create the CCO's chief of staff (colleague)**

Create `fixtures/demo-vault/50-people/taylor-brooks.md`:

```markdown
---
person-name: "Taylor Brooks"
slug: taylor-brooks
email: taylor.brooks@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Chief of Staff"
projects: [commercial-ops-pipeline-governance]
created: 2025-06-01
last-updated: 2026-06-05
meetings-7d: 0
meetings-30d: 1
---
```

- [ ] **Step 5: Create the uncurated person**

Create `fixtures/demo-vault/50-people/jamie-ellwood.md` — this represents a
meeting attendee auto-created from a transcript and never manually enriched:
`relationship`, `email`, `company`, and `role` are present as keys but empty
(YAML `null`), which is exactly what makes `relationship.isEmpty()` true and
populates People.base's "Uncurated" view.

```markdown
---
person-name: "Jamie Ellwood"
slug: jamie-ellwood
email:
relationship:
company:
role:
projects: [meridian-yard-automation-program]
created: 2026-05-20
last-updated: 2026-05-20
meetings-7d: 0
meetings-30d: 1
---
```

- [ ] **Step 6: Run the ontology test to confirm person coverage is green**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -k person -v`
Expected: `test_object_type_has_minimum_fixtures[person]`,
`test_object_type_frontmatter_conforms[person]`, and
`test_at_least_one_uncurated_person` all PASS.

- [ ] **Step 7: Commit**

```bash
git add fixtures/demo-vault/50-people
git commit -m "$(cat <<'EOF'
feat: add demo-vault person fixtures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Project fixtures (5, all 4 project-type enum values)

**Files:**
- Create: `fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/index.md` (`project-type: presales`)
- Create: `fixtures/demo-vault/30-projects/meridian-yard-automation-program/index.md` (`project-type: delivery`)
- Create: `fixtures/demo-vault/30-projects/meridian-warehouse-pilot-phase-0/index.md` (`project-type: delivery`, `status: completed`, parent of the above)
- Create: `fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/index.md` (`project-type: internal`)
- Create: `fixtures/demo-vault/30-projects/commercial-ops-pipeline-governance/index.md` (`project-type: area-of-responsibility`)

**Interfaces:**
- Consumes: `SCHEMAS["project"]` from Task 2 (required fields, `status`/`project-type` enums, slug-must-match-folder); entity slugs from Task 3; person slugs from Task 4.
- Produces: project slugs `nordbridge-regional-rollout-proposal`, `meridian-yard-automation-program`, `meridian-warehouse-pilot-phase-0`, `commercial-ops-crm-modernization`, `commercial-ops-pipeline-governance` — Task 6 (meetings' `projects:`) and Task 7 (decisions' `project:` and folder) reference these exact slugs.

- [ ] **Step 1: Create the presales project**

Create `fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/index.md`:

```markdown
---
type: project
project-name: "Nordbridge Components — Regional Rollout Proposal"
slug: nordbridge-regional-rollout-proposal
status: active
project-type: presales
entity: nordbridge-components
owner: jordan-vance
stakeholders: [jordan-vance, dana-whitfield]
created: 2026-02-10
last-updated: 2026-06-12
meetings-7d: 0
meetings-30d: 1
key-people: [jordan-vance, dana-whitfield]
next-milestone: "Submit regional rollout proposal"
next-milestone-date: 2026-09-15
---

## Overview

Proposal to extend Cascadia's yard-automation offering across Nordbridge's
three plants, following the 2026-03-02 intro call.

## Deliverables

None yet — proposal in drafting.
```

- [ ] **Step 2: Create the active delivery project and its parent Phase 0 pilot**

Create `fixtures/demo-vault/30-projects/meridian-warehouse-pilot-phase-0/index.md`:

```markdown
---
type: project
project-name: "Meridian Freight — Warehouse Pilot (Phase 0)"
slug: meridian-warehouse-pilot-phase-0
status: completed
project-type: delivery
entity: meridian-freight-holdings
owner: priya-nathan
stakeholders: [priya-nathan, leo-marchetti]
created: 2025-10-01
last-updated: 2026-02-01
meetings-7d: 0
meetings-30d: 0
key-people: [priya-nathan]
next-milestone:
next-milestone-date:
---

## Overview

Single-warehouse automation pilot that preceded the full yard-automation
program. Completed 2026-02; superseded by [[meridian-yard-automation-program]].
```

Create `fixtures/demo-vault/30-projects/meridian-yard-automation-program/index.md`:

```markdown
---
type: project
project-name: "Meridian Freight — Yard Automation Program"
slug: meridian-yard-automation-program
status: active
project-type: delivery
entity: meridian-freight-holdings
owner: priya-nathan
parent: meridian-warehouse-pilot-phase-0
stakeholders: [priya-nathan, leo-marchetti, renee-castillo]
created: 2026-02-15
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 2
key-people: [priya-nathan, leo-marchetti]
next-milestone: "Vendor contract signature — single-vendor consolidation"
next-milestone-date: 2026-09-01
---

## Overview

Full three-yard automation rollout following the Phase 0 pilot. Vendor
strategy shifted mid-program from phased multi-vendor to single-vendor
consolidation — see [[2026-05-20-single-vendor-strategy-adopted]], which
supersedes [[2026-03-10-phased-regional-rollout-adopted]].
```

- [ ] **Step 3: Create the internal and area-of-responsibility projects**

Create `fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/index.md`:

```markdown
---
type: project
project-name: "Commercial Operations — CRM Data Modernization"
slug: commercial-ops-crm-modernization
status: active
project-type: internal
entity: commercial-operations
owner: sam-okafor
stakeholders: [sam-okafor, omar-siddiqui]
created: 2026-03-01
last-updated: 2026-06-01
meetings-7d: 0
meetings-30d: 2
key-people: [sam-okafor, omar-siddiqui]
next-milestone: "Vendor selection finalized"
next-milestone-date: 2026-08-30
---

## Overview

Consolidates commercial pipeline data currently split across the CRM and
spreadsheets into a single modernized schema.
```

Create `fixtures/demo-vault/30-projects/commercial-ops-pipeline-governance/index.md`:

```markdown
---
type: project
project-name: "Commercial Operations — Pipeline Governance"
slug: commercial-ops-pipeline-governance
status: active
project-type: area-of-responsibility
entity: commercial-operations
owner: taylor-brooks
stakeholders: [sam-okafor, taylor-brooks]
created: 2026-01-20
last-updated: 2026-06-05
meetings-7d: 0
meetings-30d: 1
key-people: [taylor-brooks]
next-milestone: "Q3 pipeline governance review"
next-milestone-date: 2026-09-30
---

## Overview

Ongoing area of responsibility: pipeline hygiene standards, forecast-call
cadence, and quarterly governance review across the commercial org.
```

- [ ] **Step 4: Run the ontology test to confirm project coverage is green**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -k project -v`
Expected: `test_object_type_has_minimum_fixtures[project]`,
`test_object_type_frontmatter_conforms[project]`, and
`test_project_type_enum_fully_covered` all PASS.

- [ ] **Step 5: Commit**

```bash
git add fixtures/demo-vault/30-projects
git commit -m "$(cat <<'EOF'
feat: add demo-vault project fixtures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Meeting fixtures (8, covering type/review_status enums and Triage edge cases)

**Files:**
- Create: `fixtures/demo-vault/20-meetings/02-03-26-nordbridge-intro-call.md`
- Create: `fixtures/demo-vault/20-meetings/10-03-26-meridian-steerco-01.md`
- Create: `fixtures/demo-vault/20-meetings/15-04-26-priya-1on1.md`
- Create: `fixtures/demo-vault/20-meetings/20-04-26-commercial-ops-workshop.md`
- Create: `fixtures/demo-vault/20-meetings/20-05-26-meridian-vendor-strategy-brainstorm.md`
- Create: `fixtures/demo-vault/20-meetings/01-06-26-commercial-ops-status-update.md`
- Create: `fixtures/demo-vault/20-meetings/05-06-26-pipeline-governance-review.md`
- Create: `fixtures/demo-vault/20-meetings/12-06-26-jordan-1on1.md`

**Interfaces:**
- Consumes: `SCHEMAS["meeting"]` from Task 2 (required fields, `type`/`review_status` enums); project slugs from Task 5; person slugs from Task 4.
- Produces: meeting filenames (without `.md`) referenced as `[[wikilinks]]` in Decision `source:` fields in Task 7 — exact names: `02-03-26-nordbridge-intro-call`, `10-03-26-meridian-steerco-01`, `20-05-26-meridian-vendor-strategy-brainstorm`, `01-06-26-commercial-ops-status-update`.

This set is deliberately designed to exercise `Meetings.base`'s Triage view
(filter: `(review_status == "needs-review" OR review_status ==
"needs-attention") AND reviewed != true AND archived != true`): meetings 1,
4, and 5 below should appear in Triage; meetings 2, 3, and 8 are `confirmed`
and correctly excluded; meeting 6 is `needs-review` but `reviewed: true`
(tests that the boolean overrides the status); meeting 7 is `needs-attention`
but `archived: true` (tests the same for archival).

**YAML gotcha (verified):** `type: 1:1` unquoted is parsed by PyYAML as the
sexagesimal integer `61`, not the string `"1:1"` — the 1:1 meetings below
MUST write it quoted (`type: "1:1"`). Obsidian's js-yaml reads the quoted
form identically, so nothing breaks on the vault side.

- [ ] **Step 1: Create the presales intro call (needs-review, shows in Triage)**

Create `fixtures/demo-vault/20-meetings/02-03-26-nordbridge-intro-call.md`:

```markdown
---
date: 2026-03-02T10:00
type: meeting
calendar-subject: "Nordbridge Components / Cascadia Intermodal — Intro Call"
calendar_match: true
organizer: jordan-vance
location: "Microsoft Teams"
recurring: false
start-time: 2026-03-02T10:00
attendee-emails: [jordan.vance@cascadia-intermodal.example, dana.whitfield@nordbridge.example]
attendees: [jordan-vance, dana-whitfield]
projects: [nordbridge-regional-rollout-proposal]
review_status: needs-review
reviewed: false
archived: false
recording-duration: 32
source: teams
processed: true
---

## Notes

- Nordbridge open to a regional rollout across all three plants, starting
  with whichever site is least disrupted by their ongoing ERP work.
- Dana flagged the Ohio Valley plant is mid-ERP-migration — do not propose
  that site first.

## Action items

- [ ] Jordan to draft a phased proposal excluding Ohio Valley from Phase 1.
```

- [ ] **Step 2: Create the Meridian steering committee (confirmed, hidden from Triage; source of a superseded decision)**

Create `fixtures/demo-vault/20-meetings/10-03-26-meridian-steerco-01.md`:

```markdown
---
date: 2026-03-10T14:00
type: steerco
calendar-subject: "Meridian Freight — Yard Automation Steering Committee #1"
calendar_match: true
organizer: priya-nathan
location: "Microsoft Teams"
recurring: true
start-time: 2026-03-10T14:00
attendee-emails: [priya.nathan@cascadia-intermodal.example, leo.marchetti@meridianfreight.example, renee.castillo@meridianfreight.example]
attendees: [priya-nathan, leo-marchetti, renee-castillo]
projects: [meridian-yard-automation-program]
review_status: confirmed
reviewed: true
archived: false
recording-duration: 58
source: teams
processed: true
---

## Notes

- Agreed to roll out phased, multi-vendor automation across the three
  yards, starting with the highest-volume site.
- See [[2026-03-10-phased-regional-rollout-adopted]].
```

- [ ] **Step 3: Create a 1:1 with Priya (confirmed, hidden from Triage)**

Create `fixtures/demo-vault/20-meetings/15-04-26-priya-1on1.md`:

```markdown
---
date: 2026-04-15T09:30
type: "1:1"
calendar-subject: "1:1 — Priya Nathan"
calendar_match: true
organizer: priya-nathan
location: "Microsoft Teams"
recurring: true
start-time: 2026-04-15T09:30
attendee-emails: [priya.nathan@cascadia-intermodal.example]
attendees: [priya-nathan]
projects: [meridian-yard-automation-program]
review_status: confirmed
reviewed: true
archived: false
recording-duration: 25
source: teams
processed: true
---

## Notes

- Priya flagged early friction between the two candidate vendors' PLC
  integrations — likely drives a vendor-strategy decision soon.
```

- [ ] **Step 4: Create the Commercial Ops workshop (needs-attention, shows in Triage)**

Create `fixtures/demo-vault/20-meetings/20-04-26-commercial-ops-workshop.md`:

```markdown
---
date: 2026-04-20T13:00
type: workshop
calendar-subject: "Commercial Operations — CRM Data Modernization Kickoff Workshop"
calendar_match: true
organizer: sam-okafor
location: "Microsoft Teams"
recurring: false
start-time: 2026-04-20T13:00
attendee-emails: [sam.okafor@cascadia-intermodal.example, omar.siddiqui@cascadia-intermodal.example, taylor.brooks@cascadia-intermodal.example]
attendees: [sam-okafor, omar-siddiqui, taylor-brooks]
projects: [commercial-ops-crm-modernization]
review_status: needs-attention
reviewed: false
archived: false
recording-duration: 75
source: teams
processed: true
---

## Notes

- Scoped the CRM data model gaps; Omar to draft the target schema.
- Flagged for follow-up: current pipeline stage definitions are inconsistent
  across regions — needs a governance decision, not just a data fix.
```

- [ ] **Step 5: Create the vendor-strategy brainstorm (needs-review, shows in Triage; recorder capture, not calendar-matched; source of the superseding decision; introduces the uncurated attendee)**

Create `fixtures/demo-vault/20-meetings/20-05-26-meridian-vendor-strategy-brainstorm.md`:

```markdown
---
date: 2026-05-20T11:00
type: brainstorm
calendar-subject: "Meridian Freight — Vendor Strategy Brainstorm"
calendar_match: false
attendees: [priya-nathan, leo-marchetti, jamie-ellwood]
projects: [meridian-yard-automation-program]
review_status: needs-review
reviewed: false
archived: false
recording-duration: 41
source: recorder
source-filename: "REC-2026-0520-1103.m4a"
processed: true
---

## Notes

- Leo pushed to consolidate on a single automation vendor across all three
  yards rather than run three parallel integrations.
- Jamie Ellwood (Meridian ops lead, not yet a regular attendee) joined to
  give the floor-operations perspective — first time in a Cascadia meeting.
- See [[2026-05-20-single-vendor-strategy-adopted]], which supersedes
  [[2026-03-10-phased-regional-rollout-adopted]].
```

- [ ] **Step 6: Create the status update (needs-review but reviewed: true — Triage-suppression edge case; source of an active decision)**

Create `fixtures/demo-vault/20-meetings/01-06-26-commercial-ops-status-update.md`:

```markdown
---
date: 2026-06-01T09:00
type: status-update
calendar-subject: "Commercial Operations — Weekly Status Update"
calendar_match: true
organizer: sam-okafor
location: "Microsoft Teams"
recurring: true
start-time: 2026-06-01T09:00
attendee-emails: [sam.okafor@cascadia-intermodal.example, omar.siddiqui@cascadia-intermodal.example]
attendees: [sam-okafor, omar-siddiqui]
projects: [commercial-ops-crm-modernization]
review_status: needs-review
reviewed: true
archived: false
recording-duration: 20
source: teams
processed: true
---

## Notes

- Approved a three-vendor shortlist for the CRM modernization RFP; see
  [[2026-06-01-vendor-shortlist-approved]].
- `review_status` still shows `needs-review` from the transcript import, but
  this note has already been triaged (`reviewed: true`) — it should NOT
  appear in the Meetings.base Triage view.
```

- [ ] **Step 7: Create the pipeline governance review (needs-attention but archived: true — Triage-suppression edge case)**

Create `fixtures/demo-vault/20-meetings/05-06-26-pipeline-governance-review.md`:

```markdown
---
date: 2026-06-05T15:00
type: meeting
calendar-subject: "Commercial Operations — Pipeline Governance Review"
calendar_match: true
organizer: sam-okafor
location: "Microsoft Teams"
recurring: false
start-time: 2026-06-05T15:00
attendee-emails: [sam.okafor@cascadia-intermodal.example, taylor.brooks@cascadia-intermodal.example]
attendees: [sam-okafor, taylor-brooks]
projects: [commercial-ops-pipeline-governance]
review_status: needs-attention
reviewed: false
archived: true
recording-duration: 30
source: teams
processed: true
---

## Notes

- Reviewed forecast-call cadence; no material decision, filed for record
  and archived — should NOT appear in the Meetings.base Triage view despite
  `needs-attention`.
```

- [ ] **Step 8: Create the second 1:1 (confirmed, hidden from Triage)**

Create `fixtures/demo-vault/20-meetings/12-06-26-jordan-1on1.md`:

```markdown
---
date: 2026-06-12T10:00
type: "1:1"
calendar-subject: "1:1 — Jordan Vance"
calendar_match: true
organizer: jordan-vance
location: "Microsoft Teams"
recurring: true
start-time: 2026-06-12T10:00
attendee-emails: [jordan.vance@cascadia-intermodal.example]
attendees: [jordan-vance]
projects: [nordbridge-regional-rollout-proposal]
review_status: confirmed
reviewed: true
archived: false
recording-duration: 22
source: teams
processed: true
---

## Notes

- Proposal drafting on track for the September submission target.
```

- [ ] **Step 9: Run the ontology test to confirm meeting coverage is green**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -k meeting -v`
Expected: `test_object_type_has_minimum_fixtures[meeting]`,
`test_object_type_frontmatter_conforms[meeting]`,
`test_meeting_review_status_enum_fully_covered`, and
`test_meeting_type_enum_broadly_covered` all PASS.

- [ ] **Step 10: Commit**

```bash
git add fixtures/demo-vault/20-meetings
git commit -m "$(cat <<'EOF'
feat: add demo-vault meeting fixtures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Decision fixtures (4, incl. one supersession chain and full status-enum coverage)

**Files:**
- Create: `fixtures/demo-vault/30-projects/meridian-yard-automation-program/decisions/2026-03-10-phased-regional-rollout-adopted.md` (`status: superseded`)
- Create: `fixtures/demo-vault/30-projects/meridian-yard-automation-program/decisions/2026-05-20-single-vendor-strategy-adopted.md` (`status: active`, supersedes the above)
- Create: `fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/decisions/2026-03-02-pilot-site-selection-withdrawn.md` (`status: withdrawn`)
- Create: `fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/decisions/2026-06-01-vendor-shortlist-approved.md` (`status: active`)

**Interfaces:**
- Consumes: `SCHEMAS["decision"]` from Task 2 (required fields, `status` enum); project slugs from Task 5; meeting filenames from Task 6 for `source:` wikilinks.
- Produces: nothing further downstream depends on these filenames, but body cross-links in Tasks 3, 5, and 6 already reference `[[2026-03-10-phased-regional-rollout-adopted]]` and `[[2026-05-20-single-vendor-strategy-adopted]]` by these exact names — keep them identical.

Decision note bodies follow the exact pattern from `template/CLAUDE.md`
("Decision Notes"): `**Decision** — / **Why** — / **Implications**`.

- [ ] **Step 1: Create the superseded decision**

Create `fixtures/demo-vault/30-projects/meridian-yard-automation-program/decisions/2026-03-10-phased-regional-rollout-adopted.md`:

```markdown
---
type: decision
project: meridian-yard-automation-program
date: 2026-03-10
status: superseded
summary: "Adopt a phased, multi-vendor rollout across three regional yards, starting with the highest-volume site."
supersedes:
source: "[[10-03-26-meridian-steerco-01]]"
tags: [scope, staffing]
---

**Decision** — Roll out yard automation in three phases, one yard at a time,
using separate vendors selected per-site.

**Why** — Minimizes disruption at any single yard and lets each site's
integration team move at its own pace.

**Implications** — Three parallel vendor integrations to manage; superseded
2026-05-20 once the integration overhead proved too costly — see
[[2026-05-20-single-vendor-strategy-adopted]].
```

- [ ] **Step 2: Create the active decision that supersedes it**

Create `fixtures/demo-vault/30-projects/meridian-yard-automation-program/decisions/2026-05-20-single-vendor-strategy-adopted.md`:

```markdown
---
type: decision
project: meridian-yard-automation-program
date: 2026-05-20
status: active
summary: "Consolidate on a single automation vendor across all three yards to simplify integration and reduce total cost of ownership."
supersedes: "[[2026-03-10-phased-regional-rollout-adopted]]"
source: "[[20-05-26-meridian-vendor-strategy-brainstorm]]"
tags: [platform, commercial]
---

**Decision** — Consolidate on a single automation vendor across all three
yards.

**Why** — Running three vendors' PLC and control software in parallel was
creating integration overhead that outweighed the site-pacing benefit of the
phased approach.

**Implications** — The Phase 0 pilot vendor stays for yard 1; yards 2–3
re-scope onto the same platform, pushing final commissioning out roughly six
weeks versus the original phased plan.
```

- [ ] **Step 3: Create the withdrawn decision**

Create `fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/decisions/2026-03-02-pilot-site-selection-withdrawn.md`:

```markdown
---
type: decision
project: nordbridge-regional-rollout-proposal
date: 2026-03-02
status: withdrawn
summary: "Proposed piloting the rollout at Nordbridge's Ohio Valley plant first; withdrawn after Nordbridge flagged an unrelated ERP migration freeze at that site."
supersedes:
source: "[[02-03-26-nordbridge-intro-call]]"
tags: [timing]
---

**Decision** — Pilot the regional rollout proposal at the Ohio Valley plant
first.

**Why** — Ohio Valley had the most automation-ready floor layout of
Nordbridge's three plants.

**Implications** — Withdrawn same-day once Dana flagged Ohio Valley is
mid-ERP-migration; Phase 1 site selection is now open pending Nordbridge's
input on a non-conflicting site.
```

- [ ] **Step 4: Create the second active decision**

Create `fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/decisions/2026-06-01-vendor-shortlist-approved.md`:

```markdown
---
type: decision
project: commercial-ops-crm-modernization
date: 2026-06-01
status: active
summary: "Approve a three-vendor shortlist for the CRM data modernization RFP, weighted toward integration effort over list price."
supersedes:
source: "[[01-06-26-commercial-ops-status-update]]"
tags: [methodology]
---

**Decision** — Shortlist three vendors for the CRM data modernization RFP.

**Why** — Weighting integration effort over sticker price, given the
existing pipeline-stage inconsistencies flagged at the kickoff workshop.

**Implications** — RFP responses due by the next milestone
(vendor selection finalized, 2026-08-30); Omar owns scoring.
```

- [ ] **Step 5: Run the ontology test to confirm decision coverage is green**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -v`
Expected: every test in the module now PASSES **except**
`test_context_portfolio_is_filled_not_placeholder` (Task 8 handles that).
Specifically confirm `test_decision_supersession_chain_exists` and
`test_decision_status_enum_fully_covered` pass.

- [ ] **Step 6: Commit**

```bash
git add fixtures/demo-vault/30-projects
git commit -m "$(cat <<'EOF'
feat: add demo-vault decision fixtures, incl. a supersession chain

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Filled context portfolio (5 files)

**Files:**
- Create: `fixtures/demo-vault/99-workflow-config/context/identity.md`
- Create: `fixtures/demo-vault/99-workflow-config/context/role-and-responsibilities.md`
- Create: `fixtures/demo-vault/99-workflow-config/context/communication-style.md`
- Create: `fixtures/demo-vault/99-workflow-config/context/preferences-and-constraints.md`
- Create: `fixtures/demo-vault/99-workflow-config/context/tools-and-systems.md`

**Interfaces:**
- Consumes: `test_context_portfolio_is_filled_not_placeholder` from Task 2 (must not contain the string `"Placeholder."`; the `<!-- setup-my-brain:begin -->...end -->` block must be non-empty).
- Produces: these five files fully replace the template's placeholder versions when `make_test_vault.py` (Task 10) overlays fixtures on top of the template copy — they must be complete, standalone files, not diffs.

Each file keeps the template's `## Purpose` and `## Interview questions`
sections (they're reusable onboarding scaffolding, not per-user content) and
replaces the placeholder banner + fills the `## Content` marker block, as if
the onboarding interview had already run for Morgan Ellery.

- [ ] **Step 1: Create identity.md**

Create `fixtures/demo-vault/99-workflow-config/context/identity.md`:

```markdown
# Identity

## Purpose

Who the executive is, in their own words. Read by every skill that writes on their behalf or addresses them; keep it short and factual.

## Interview questions

- What is your full name, and what do people actually call you?
- What is your role title and company?
- Which languages do you work in, and which do you prefer for briefs?
- What is your time zone and typical working window?

## Content

<!-- setup-my-brain:begin -->
Morgan Ellery — goes by Morgan. Chief Commercial Officer at Cascadia
Intermodal Group, a mid-size industrial and logistics company (~1,400
employees). 14 years in commercial leadership across logistics and
industrial services, the last 4 as CCO. Works in English; time zone
America/Chicago, typical working window 07:00–18:00 with client-site weeks
running later.
<!-- setup-my-brain:end -->
```

- [ ] **Step 2: Create role-and-responsibilities.md**

Create `fixtures/demo-vault/99-workflow-config/context/role-and-responsibilities.md`:

```markdown
# Role & Responsibilities

## Purpose

What the executive owns and is accountable for. Read by briefing and processing skills to judge relevance — what deserves attention versus noise.

## Interview questions

- What areas, functions, or units do you own?
- What are the 3–5 metrics or outcomes you are judged on?
- Who reports to you directly?
- Which recurring forums (boards, steercos, councils) are you accountable in?
- What decisions are yours alone, and which do you share or delegate?

## Content

<!-- setup-my-brain:begin -->
Owns the commercial P&L: new-logo growth (presales), existing-client delivery
oversight, and the Commercial Operations business unit. Judged on: new
bookings, gross margin on delivery engagements, and net revenue retention
across the existing client base. Direct reports: Sam Okafor (VP Commercial
Operations) and a regional sales-director bench including Jordan Vance and
Priya Nathan. Chairs the monthly pipeline review and the Meridian Freight
steering committee. Final approver on any vendor-strategy decision above
$250K total cost of ownership; delegates day-to-day account management to
account directors.
<!-- setup-my-brain:end -->
```

- [ ] **Step 3: Create communication-style.md**

Create `fixtures/demo-vault/99-workflow-config/context/communication-style.md`:

```markdown
# Communication Style

## Purpose

How Claude should sound when writing as or to the executive. Read by every skill that drafts prose.

## Interview questions

- Do you prefer bullets or narrative prose in briefs?
- How formal should drafts in your name be?
- Any words, phrases, or tones to avoid?
- How direct should pushback be when Claude disagrees with you?
- Which language(s) for which audiences?

## Content

<!-- setup-my-brain:begin -->
Direct and numbers-first — wants the headline and the delta before the
narrative. Prefers bullets over prose for internal updates; narrative prose
is fine for client-facing drafts. Comfortable being pushed back on with
data — say so plainly, don't hedge. Dislikes restating context already in
the CRM or a prior meeting note; assume it's been read. English only, no
formality beyond plain professional tone.
<!-- setup-my-brain:end -->
```

- [ ] **Step 4: Create preferences-and-constraints.md**

Create `fixtures/demo-vault/99-workflow-config/context/preferences-and-constraints.md`:

```markdown
# Preferences & Constraints

## Purpose

Boundaries and rhythm. Read by every skill; constraints here override convenience everywhere else.

## Interview questions

- What kinds of content must go to `95-private/` (invisible to your assistant)?
- What must never leave the vault without your explicit review?
- What is your assistant allowed to see, do, and sign off on?
- When do you want your morning brief and evening digest?
- Any confidentiality rules from your company that Claude must enforce?

## Content

<!-- setup-my-brain:begin -->
Compensation and org-change discussions go to `95-private/`. Nothing goes to
a client or prospect without Morgan's explicit review — no auto-sent
proposals or emails. Taylor Brooks (Chief of Staff) can triage and draft on
Morgan's behalf but not send externally. Morning brief by 07:30 local;
evening digest by 18:30. Standard NDA confidentiality applies to all
prospect and client content — never mix commercial terms across accounts in
a single note.
<!-- setup-my-brain:end -->
```

- [ ] **Step 5: Create tools-and-systems.md**

Create `fixtures/demo-vault/99-workflow-config/context/tools-and-systems.md`:

```markdown
# Tools & Systems

## Purpose

The systems around the vault. Read by capture and sync skills to know where information comes from and where outputs must land.

## Interview questions

- Calendar and mail platform (tenant, shared mailboxes)?
- Meeting platform(s), and is transcription enabled?
- Which recorder do you use for non-platform meetings?
- Where do heavy files live (drive, sites)?
- Which business systems matter for context (CRM, ERP, BI)?
- What tooling does your assistant run daily?

## Content

<!-- setup-my-brain:begin -->
Microsoft 365 (Teams, Outlook) for calendar and mail; Teams transcription is
enabled tenant-wide. Physical recorder for site visits and calls without a
Teams link — used for the Meridian vendor-strategy brainstorm, for example.
Heavy files (proposal decks, RFP responses) live in a shared SharePoint
site, referenced from `_heavy-assets/` stubs. CRM: internal Salesforce
instance, not yet integrated with this vault — pipeline numbers are
manually reconciled during the weekly status update.
<!-- setup-my-brain:end -->
```

- [ ] **Step 6: Run the full ontology test suite to confirm all-green**

Run: `python -m pytest scripts/tests/test_fixtures_ontology.py -v`
Expected: every test in the module PASSES, including
`test_context_portfolio_is_filled_not_placeholder`.

- [ ] **Step 7: Commit**

```bash
git add fixtures/demo-vault/99-workflow-config
git commit -m "$(cat <<'EOF'
feat: fill demo-vault context portfolio

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Daily notes and raw inbox captures

**Files:**
- Create: `fixtures/demo-vault/60-daily-notes/2026-06-01.md`
- Create: `fixtures/demo-vault/60-daily-notes/2026-06-05.md`
- Create: `fixtures/demo-vault/60-daily-notes/2026-06-12.md`
- Create: `fixtures/demo-vault/10-inbox/2026-08-19-teams-transcript-nordbridge-checkin.txt`
- Create: `fixtures/demo-vault/10-inbox/2026-08-20-voice-memo-fleet-visit.txt`
- Create: `fixtures/demo-vault/10-inbox/2026-08-21-forwarded-email-meridian-renewal.txt`

**Interfaces:**
- Consumes: meeting/decision fixtures from Tasks 6–7 (daily notes link to them); the inbox items are deliberately *not* linked to any processed fixture — they represent unprocessed capture, the standard input shape a future capture skill (issue #14 etc.) will consume.
- Produces: nothing downstream depends on these — they're not covered by `test_fixtures_ontology.py` (daily notes and raw inbox text have no ontology frontmatter schema; the inbox items in particular are intentionally *not* vault objects yet).

- [ ] **Step 1: Create three daily notes**

Create `fixtures/demo-vault/60-daily-notes/2026-06-01.md`:

```markdown
# 2026-06-01

## Morning brief

- Commercial Operations status-update at 09:00 — CRM modernization vendor
  shortlist decision expected.

## Notes

- [[01-06-26-commercial-ops-status-update]] — shortlist approved, see
  [[2026-06-01-vendor-shortlist-approved]].

## Evening brief

- Shortlist approved; next step is RFP scoring criteria sign-off with Sam.
```

Create `fixtures/demo-vault/60-daily-notes/2026-06-05.md`:

```markdown
# 2026-06-05

## Morning brief

- Pipeline governance review at 15:00 with Sam and Taylor.

## Notes

- [[05-06-26-pipeline-governance-review]] — forecast-call cadence reviewed,
  no material decision this cycle; filed and archived.

## Evening brief

- Quiet day otherwise. Nordbridge proposal drafting continues in the
  background.
```

Create `fixtures/demo-vault/60-daily-notes/2026-06-12.md`:

```markdown
# 2026-06-12

## Morning brief

- 1:1 with Jordan Vance at 10:00 — Nordbridge proposal status.

## Notes

- [[12-06-26-jordan-1on1]] — proposal drafting on track for September
  submission.

## Evening brief

- No blockers this week on either the Nordbridge or Meridian fronts.
```

- [ ] **Step 2: Create the raw Teams-transcript-style inbox item**

Create `fixtures/demo-vault/10-inbox/2026-08-19-teams-transcript-nordbridge-checkin.txt`:

```
Microsoft Teams — Meeting Transcript
Meeting: Nordbridge Components / Cascadia Intermodal — Quarterly Check-in
Date: 2026-08-19 10:00–10:35 (America/Chicago)
Participants: Jordan Vance, Dana Whitfield

[10:00:12] Jordan Vance: Thanks for jumping on, Dana. Wanted to check in
ahead of the proposal submission — anything changed on your end since we
last talked?

[10:00:41] Dana Whitfield: Not much has changed. The ERP freeze at Ohio
Valley is still in effect through end of Q3, so keep that site out of Phase
1 like we discussed.

[10:01:20] Jordan Vance: Understood, we've already scoped Phase 1 around
the Kentucky plant instead. Timeline still looking like a September
submission on our end.

[10:02:05] Dana Whitfield: That works. One thing — procurement wants to see
a total-cost-of-ownership comparison against our current manual process,
not just the automation vendor pricing. Can you build that in?

[10:02:40] Jordan Vance: Yes, we'll add a TCO section. I'll get you a draft
before the formal submission so there's no surprises.

[10:03:15] Dana Whitfield: Appreciated. That's all from my side.

[10:03:22] Jordan Vance: Great, thanks Dana — talk soon.
```

- [ ] **Step 3: Create the raw voice-memo-style inbox item**

Create `fixtures/demo-vault/10-inbox/2026-08-20-voice-memo-fleet-visit.txt`:

```
Voice memo — dictated by Morgan Ellery
Recorded: 2026-08-20, 16:42 (America/Chicago)
Device: personal recorder, auto-transcribed

Okay, quick notes from the site visit today with Sam at the regional
distribution center. Two things worth flagging. One — the pipeline data
Omar's team is cleaning up as part of the CRM modernization project, I saw
firsthand today how bad the current stage definitions are, floor
supervisors are literally using three different terms for the same
handoff step. That's going to slow down the modernization timeline if we
don't get operations input, not just sales input, into the new schema.
Second thing — Sam mentioned informally that the pipeline governance
review cadence, monthly isn't enough right now given how much is moving on
the Meridian side, might want to bump that to biweekly for the rest of the
quarter. Nothing urgent, just wanted to get this down before I forget it.
That's it.
```

- [ ] **Step 4: Create the raw forwarded-email-style inbox item**

Create `fixtures/demo-vault/10-inbox/2026-08-21-forwarded-email-meridian-renewal.txt`:

```
---------- Forwarded message ---------
From: Leo Marchetti <leo.marchetti@meridianfreight.example>
To: Priya Nathan <priya.nathan@cascadia-intermodal.example>
Date: Fri, Aug 21, 2026 at 9:14 AM
Subject: Renewal terms — heads up before next steerco

Priya,

Wanted to give you a heads up before Tuesday's steerco: our board is asking
us to revisit the automation program's contract length as part of our
annual renewal cycle. Nothing alarming — we're happy with where the
single-vendor consolidation has landed — but they want a 3-year term
instead of the current 2-year, in exchange for a modest volume commitment
on our end.

Can you loop in whoever handles commercial terms on your side? Would like
to have a term sheet to review before the board meets again in October.

Best,
Leo

---------- Forwarded by Priya Nathan ----------
Morgan — flagging this for visibility ahead of the September commercial
review. Will bring a term-sheet draft to you and Taylor next week.
```

- [ ] **Step 5: Verify the files render as expected**

Run: `find fixtures/demo-vault/60-daily-notes fixtures/demo-vault/10-inbox -type f | sort`
Expected output (6 lines):
```
fixtures/demo-vault/10-inbox/2026-08-19-teams-transcript-nordbridge-checkin.txt
fixtures/demo-vault/10-inbox/2026-08-20-voice-memo-fleet-visit.txt
fixtures/demo-vault/10-inbox/2026-08-21-forwarded-email-meridian-renewal.txt
fixtures/demo-vault/60-daily-notes/2026-06-01.md
fixtures/demo-vault/60-daily-notes/2026-06-05.md
fixtures/demo-vault/60-daily-notes/2026-06-12.md
```

- [ ] **Step 6: Run the clean-room lint to confirm the new fixtures are clean**

Run: `python scripts/lint_plugin.py`
Expected: exits 0 with no output (confirms Task 1's widened `fixtures/` scan
finds nothing — the invented cast never mentions Michael/Bulthé/busdev).

- [ ] **Step 7: Commit**

```bash
git add fixtures/demo-vault/60-daily-notes fixtures/demo-vault/10-inbox
git commit -m "$(cat <<'EOF'
feat: add demo-vault daily notes and raw inbox captures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `scripts/make_test_vault.py`

**Files:**
- Create: `scripts/make_test_vault.py`
- Test: `scripts/tests/test_make_test_vault.py`

**Interfaces:**
- Consumes: `template/` and `fixtures/demo-vault/` directory trees (both now fully populated as of Task 9).
- Produces: `build_vault(target: Path, repo_root: Path, fresh: bool) -> None` (raises `TargetNotEmptyError` on a non-empty target) — this is the function Task 11's runbook instructs testers to invoke via the CLI wrapper `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_make_test_vault.py`:

```python
"""Tests build against the real template/ and fixtures/demo-vault/ trees,
same pattern as test_lint_plugin.py's use of the shipped denylist — a
synthetic fixture tree would defeat the point of testing the actual
instantiation."""
from pathlib import Path

import pytest

from make_test_vault import TargetNotEmptyError, build_vault, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_fresh_copies_template_only(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "CLAUDE.md").is_file()
    assert not (target / "40-entities" / "nordbridge-components").exists()


def test_default_overlays_fixtures(tmp_path):
    target = tmp_path / "vault"
    build_vault(target, REPO_ROOT, fresh=False)
    assert (target / "CLAUDE.md").is_file()
    assert (target / "40-entities" / "nordbridge-components" / "dossier.md").is_file()
    identity_text = (target / "99-workflow-config" / "context" / "identity.md").read_text()
    assert "Placeholder." not in identity_text
    assert "Morgan Ellery" in identity_text


def test_refuses_nonempty_target(tmp_path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "existing-file.txt").write_text("don't touch me\n")
    with pytest.raises(TargetNotEmptyError):
        build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "existing-file.txt").is_file()  # untouched


def test_target_created_when_missing(tmp_path):
    target = tmp_path / "nested" / "vault"
    build_vault(target, REPO_ROOT, fresh=True)
    assert (target / "CLAUDE.md").is_file()


def test_refuses_existing_file_target(tmp_path):
    target = tmp_path / "vault"
    target.write_text("a file, not a directory\n")
    with pytest.raises(TargetNotEmptyError):
        build_vault(target, REPO_ROOT, fresh=True)


def test_cli_refuses_nonempty_target(tmp_path, capsys):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "existing-file.txt").write_text("don't touch me\n")
    exit_code = main([str(target)])
    assert exit_code == 1
    assert "not empty" in capsys.readouterr().err


def test_cli_default_mode_reports_fixtures(tmp_path, capsys):
    target = tmp_path / "vault"
    exit_code = main([str(target)])
    assert exit_code == 0
    assert "demo fixtures" in capsys.readouterr().out
    assert (target / "40-entities").is_dir()


def test_cli_fresh_mode_reports_template_only(tmp_path, capsys):
    target = tmp_path / "vault"
    exit_code = main([str(target), "--fresh"])
    assert exit_code == 0
    assert "template-only" in capsys.readouterr().out
    # 40-entities/ itself ships with the template (Entities.base) — only the
    # fixture overlay content must be absent in --fresh mode.
    assert not (target / "40-entities" / "nordbridge-components").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_make_test_vault.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'make_test_vault'`.

- [ ] **Step 3: Implement the script**

Create `scripts/make_test_vault.py`:

```python
#!/usr/bin/env python3
"""Instantiate a throwaway vault for hand-testing the plugin.

Copies template/ into TARGET, then overlays fixtures/demo-vault/ on top
unless --fresh is given (template-only, for onboarding testing). Refuses to
touch a TARGET that already exists and is non-empty — this script only ever
creates, never merges into or overwrites existing work.

Exit 0 on success; exit 1 with a message on stderr if TARGET is non-empty.
"""
import argparse
import shutil
import sys
from pathlib import Path


class TargetNotEmptyError(Exception):
    pass


def build_vault(target: Path, repo_root: Path, fresh: bool) -> None:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmptyError(f"{target} already exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "template", target, dirs_exist_ok=True)
    if not fresh:
        shutil.copytree(repo_root / "fixtures" / "demo-vault", target, dirs_exist_ok=True)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Instantiate a test vault from template/ (+ demo fixtures unless --fresh)."
    )
    parser.add_argument("target", type=Path, help="Directory to create the test vault in")
    parser.add_argument(
        "--fresh", action="store_true", help="Template only — skip the demo fixtures overlay"
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        build_vault(args.target.resolve(), repo_root, args.fresh)
    except TargetNotEmptyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    mode = "template-only" if args.fresh else "template + demo fixtures"
    print(f"Test vault created at {args.target} ({mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_make_test_vault.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Run the full local test suite**

Run:
```bash
python scripts/lint_plugin.py
python scripts/validate_template.py
python -m pytest scripts/tests -q
```
Expected: all three commands exit 0 — this is the same sequence CI runs, plus the new fixture and script tests are now part of `scripts/tests`.

- [ ] **Step 6: Commit**

```bash
git add scripts/make_test_vault.py scripts/tests/test_make_test_vault.py
git commit -m "$(cat <<'EOF'
feat: add make_test_vault.py to instantiate a test vault from template + fixtures

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: End-to-end runbook in `docs/local-setup.md`

**Files:**
- Modify: `docs/local-setup.md` (replace the "Test the plugin against a scratch vault" section, lines 18–28)

**Interfaces:**
- Consumes: `scripts/make_test_vault.py` (Task 10), `template/README.md`'s community-plugin/theme provisioning list, `template/50-people/People.base`'s "Uncurated" view, all five `.base` files.
- Produces: nothing downstream — this is the terminal task and the issue's stated acceptance test ("a fresh reader must be able to follow it start to finish").

- [ ] **Step 1: Replace the stale scratch-vault section**

In `docs/local-setup.md`, replace everything from `## Test the plugin against a scratch vault` (line 18) through the end of the file with:

````markdown
## Test the plugin against a demo vault

This is the full path from a fresh clone to a hand-testable vault. It's the
acceptance test for the test-vault harness itself — if any step here doesn't
work, that's a bug in the harness, not in your setup.

### 1. Create the test vault

```bash
python scripts/make_test_vault.py /tmp/sb-test-vault
```

This copies `template/` into `/tmp/sb-test-vault` and overlays
`fixtures/demo-vault/` on top — a populated demo vault for one fictional
persona (Morgan Ellery, CCO at Cascadia Intermodal Group). The script
refuses to touch a target directory that already exists and has files in
it — it fails fast (exit 1) instead of overwriting. Delete the directory
first when you want a clean rebuild.

To test the *unpopulated* onboarding path instead (no demo content, just
the placeholder template):

```bash
python scripts/make_test_vault.py /tmp/sb-onboarding-vault --fresh
```

### 2. Open it in Obsidian

Open `/tmp/sb-test-vault` as an Obsidian vault (`Open folder as vault`).
Obsidian community plugins can't ship pre-installed, so install them by
hand once per test vault, per `template/README.md`:

1. Settings → Community plugins → Turn on community plugins.
2. Install and enable: **Dataview**, **Minimal Theme Settings**, **Style
   Settings**, **Notebook Navigator** (the plugin IDs are already listed in
   `.obsidian/community-plugins.json`, so Obsidian should offer to enable
   them directly).
3. Settings → Appearance → set the theme to **Minimal**.

### 3. Verify the five Bases render

Open each `.base` file and confirm it shows fixture rows, not an empty
table:

- `40-entities/Entities.base` — "All" shows 3 entities; "Prospects" shows
  Nordbridge Components; "Active" shows the other two.
- `30-projects/Projects.base` — "Active" shows 4 projects; "All" shows all 5
  (including the completed Phase 0 pilot).
- `30-projects/Decisions.base` — "All" shows 4 decisions with the
  `supersedes` column populated on one row.
- `20-meetings/Meetings.base` — "Triage" shows exactly 3 meetings (the two
  `needs-review` and one `needs-attention` that are neither reviewed nor
  archived); "All Meetings" shows all 8.
- `50-people/People.base` — "All" shows 9 people; "Uncurated" shows exactly
  one row (Jamie Ellwood, `relationship` empty).

### 4. Load the plugin locally and verify skills are invocable

```bash
cd /tmp/sb-test-vault
claude --plugin-dir /path/to/sb-accelerator/plugin
```

Run `/help` (or your Claude Code client's plugin/skill listing) and confirm
the vault-scoped skills from `plugin/skills/` are visible. As of this
writing `plugin/skills/` has no skills yet (they land via issues #14–#20) —
if that's still true when you run this, this step just confirms the plugin
loads without error; re-run it against a real skill once one exists.

### 5. Run one skill against the fixtures

Once at least one skill exists, invoke it against a fixture input — for
example, a meeting-capture skill against
`10-inbox/2026-08-19-teams-transcript-nordbridge-checkin.txt` — and confirm
it produces output consistent with the ontology (a `20-meetings/` note with
the required frontmatter fields from
`template/99-workflow-config/reference/ontology.md`).

### 6. Tear down and recreate

```bash
rm -rf /tmp/sb-test-vault
python scripts/make_test_vault.py /tmp/sb-test-vault
```

Confirms the harness is fully disposable — no state leaks between runs.
````

- [ ] **Step 2: Read the file back and confirm it renders correctly**

Run: `python -c "import pathlib; print(pathlib.Path('docs/local-setup.md').read_text())"` and
visually confirm the markdown is well-formed (no broken code fences, headings
in order).

- [ ] **Step 3: Dry-run the runbook's first and last commands**

Run:
```bash
rm -rf /tmp/sb-test-vault-dryrun
python scripts/make_test_vault.py /tmp/sb-test-vault-dryrun
ls /tmp/sb-test-vault-dryrun
rm -rf /tmp/sb-test-vault-dryrun
```
Expected: the `ls` output includes `CLAUDE.md`, `40-entities`, `50-people`,
`30-projects`, `20-meetings`, `99-workflow-config`, confirming steps 1 and 6
of the runbook work as written.

- [ ] **Step 4: Run the full local CI-equivalent suite one final time**

Run:
```bash
python scripts/lint_plugin.py
python scripts/validate_template.py
python -m pytest scripts/tests -q
```
Expected: all three exit 0. This closes out issue #24's deliverables 1–4.

- [ ] **Step 5: Commit**

```bash
git add docs/local-setup.md
git commit -m "$(cat <<'EOF'
docs: add end-to-end test-vault runbook

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** deliverable 1 (fixtures) → Tasks 3–9; deliverable 2
  (`make_test_vault.py`) → Task 10; deliverable 3 (CI slop guard) → Task 2
  (guard) + Task 1 (clean-room extension, since the issue explicitly calls
  out "stays denylist-clean" as part of the same slop-guard concern);
  deliverable 4 (runbook) → Task 11.
- **Known limitation, called out explicitly in Task 11 Step 4 rather than
  hidden:** no capture skill exists yet in `plugin/skills/` (ports #14–#20
  are still open), so "verify skills are invocable" and "run one skill
  against the fixtures" can't be fully exercised today. The runbook says so
  plainly instead of asserting a false success — the fixtures are built to
  be the input those skills will consume once ported, per the issue's own
  "why before the ports" rationale.
- **Type/name consistency check:** all cross-file references — entity
  slugs, project slugs, person slugs, meeting filenames, decision
  supersession target — were traced across Tasks 3–9 for exact-string
  matches (e.g. `[[2026-03-10-phased-regional-rollout-adopted]]` in Task 7
  Step 2 matches the filename created in Task 7 Step 1).
- **Second review pass (pre-execution) fixed five defects:** (1) unquoted
  `type: 1:1` parses as integer 61 under PyYAML — verified empirically,
  fixtures now quote it; (2) the slop guard gained decision-`tags`
  vocabulary, entity type/status variety, and referential-integrity tests
  (project→entity, meeting→project/person, decision→folder joins);
  (3) a no-op `monkeypatch` line was removed from the CLI tests and an
  existing-file-target guard + test added to `make_test_vault.py`;
  (4) Task 11's replacement block had broken nested code fences, now a
  4-backtick outer fence; (5) the runbook wrongly called re-running the
  script against an existing target "a no-op check" — it exits 1.
