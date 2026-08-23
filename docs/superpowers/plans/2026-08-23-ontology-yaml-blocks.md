# Ontology YAML Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `template/99-workflow-config/reference/ontology.md` the machine truth: its normative parts (required fields, enums, vocabularies) become fenced YAML blocks that the conformance guard loads directly, deleting the guard's hand-copied `SCHEMAS` values — closing GitHub issue #26.

**Architecture:** Each object-type section in `ontology.md` gains one fenced ```yaml block carrying an `object:` key plus `required`/`optional`/`enums` (and, for Decision, a `tags` vocabulary with max count; for Person, `keys_present`). Prose stays for rationale. The guard (`scripts/tests/test_fixtures_ontology.py`) gains a loader that scans the doc's yaml fences, keeps dicts with an `object` key (the Entity *example* block has no such key and is skipped), and merges them with a small hand-coded `HARNESS` dict that keeps test-harness-only concerns (globs, slug-join rules, fixture minimums). Malformed/missing/duplicate blocks raise a `RuntimeError` naming the doc — a loud collection-time failure. This is a truth-relocation refactor: the schema VALUES do not change, so the existing 48-test suite must stay green throughout.

**Tech Stack:** Python 3.13, pytest, PyYAML (existing repo dependencies). No new dependencies.

**Spec:** GitHub issue #26 (reworked 2026-08-23; read via `gh issue view 26`). The current ontology doc: `template/99-workflow-config/reference/ontology.md`. The current guard: `scripts/tests/test_fixtures_ontology.py`.

## Global Constraints

- **Behavior-preserving:** every schema value (field names, enum members, vocabularies) stays byte-identical to today's; only where truth lives changes. `python -m pytest scripts/tests -q` passes with the same green suite before and after every task (48 tests; Task 2 adds one → 49).
- **The `"1:1"` meeting type stays quoted** in the YAML block — unquoted `1:1` parses as integer 61 (PyYAML sexagesimal; verified in issue #24's work).
- **Clean-room rule:** `template/` ships to clients; no denylisted term (michael/bulthe/bulthé/busdev) in any new content. The new doc text below is clean.
- **No `plugin/` files touched** → no plugin version bump. **No `structure-version` bump** — that marker tracks folder-structure migrations for `/upgrade-vault`; this is doc content, not structure.
- **Commit trailer**, every commit, exact: `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Branch:** `feat/ontology-yaml-blocks`.
- **Local verification trio:** `python scripts/lint_plugin.py` · `python scripts/validate_template.py` · `python -m pytest scripts/tests -q` (use `python3` on this machine).

---

## File structure

| File | Responsibility |
|---|---|
| `template/99-workflow-config/reference/ontology.md` | Rewritten: normative schema in fenced YAML blocks (one per object type), prose keeps rationale |
| `scripts/tests/test_fixtures_ontology.py` | Guard loads `SCHEMAS` from the doc's blocks; hand-coded values deleted; +1 test for block presence/shape |
| `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md` | Rider: parked open question (Obsidian surface vs local-first app) |

---

### Task 1: Rewrite `ontology.md` with normative YAML blocks

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md` (full-file replacement; new content below)

**Interfaces:**
- Consumes: nothing.
- Produces: five fenced yaml blocks, each a mapping with an `object` key ∈ {`meeting`, `project`, `person`, `decision`, `entity`} — Task 2's loader keys on exactly `object`, `required`, `optional`, `keys_present`, `enums`, `tags.vocabulary`, `tags.max`. The Entity *example* block deliberately has NO `object` key so the loader skips it.

- [ ] **Step 1: Replace the file content**

Replace the entire content of `template/99-workflow-config/reference/ontology.md` with:

`````markdown
---
tags: [meta, reference, ontology]
---

# Vault Ontology — Authoritative Object Model

> **Single source of truth for the vault's object types, fields, and
> controlled vocabularies.** Edit here; never let the schema live in prose
> elsewhere.

Five object types: **Meeting · Project · Person · Decision · Entity**.
Relationships live in YAML frontmatter (wikilinks / slug joins), not folder
hierarchy. Curation happens in Bases, not by browsing folders.

## How to read this file

Each object type below carries a fenced `yaml` block with an `object:` key.
That block is the **normative schema** — required fields, optional fields,
enums, controlled vocabularies. Machines load these blocks directly: the
repo's conformance tests validate fixture frontmatter against them, and
skills consult them before writing any object frontmatter. The prose around
each block carries the rationale and conventions the YAML cannot. Editing a
block IS editing the ontology — there is no second copy to keep in sync.

## 1. Object catalog

### Meeting — `20-meetings/{DD-MM-YY-slug}.md` · Base: `Meetings.base`

```yaml
object: meeting
required: [date, type, calendar-subject, calendar_match, attendees, projects,
           review_status, recording-duration, source, processed]
optional: [attendee-emails, organizer, location, recurring, start-time,
           source-drive-id, source-filename, reviewed, archived]
enums:
  type: [meeting, "1:1", steerco, workshop, brainstorm, status-update]
  review_status: [needs-review, confirmed, needs-attention]
```

- `date` is an ISO datetime (e.g. `2026-05-05T14:37`).
- `attendee-emails`, `organizer`, `location`, `recurring`, `start-time`
  appear on calendar-matched meetings only. `source-drive-id`,
  `source-filename` are recorder provenance.
- **Triage checkboxes (booleans, edited in Meetings.base):** `reviewed` —
  one-click confirm; `archived` — hides the row from triage views (noise
  disposal; the file stays).
- Write-once; only triage fields (`attendees`, `projects`, `review_status`,
  `reviewed`, `archived`) are edited later.
- The `1:1` type value must stay **quoted** in frontmatter and in the block
  above — unquoted YAML parses `1:1` as the integer 61.
- Example: `20-meetings/05-05-26-quarterly-portfolio-review.md`

### Project — `30-projects/{slug}/index.md` · Base: `Projects.base`

```yaml
object: project
required: [project-name, slug, status, project-type, entity, owner, created,
           last-updated]
optional: [type, parent, stakeholders, meetings-7d, meetings-30d, key-people,
           next-milestone, next-milestone-date]
enums:
  status: [active, paused, completed, cancelled]
  project-type: [presales, delivery, internal, area-of-responsibility]
```

- **Edges:** `parent` (project slug) · `stakeholders[]` (person slugs).
- **Auto-maintained:** `meetings-7d`, `meetings-30d`, `key-people`.
  **Index extras:** `next-milestone`, `next-milestone-date`.
- `entity` is a slug string joining to an Entity's `slug` (and folder name).
- Example: `30-projects/acme-industries-operating-model/index.md`

### Person — `50-people/{slug}.md` · Base: `People.base`

```yaml
object: person
required: [person-name, slug]
keys_present: [relationship]
optional: [email, company, role, projects, created, last-updated,
           meetings-7d, meetings-30d]
enums:
  relationship: [colleague, direct-report, external, null]
```

- `relationship: null` (key present, value empty) = **uncurated** — that is
  what People.base's "Uncurated" view filters on. `keys_present` means the
  key itself must exist even when its value is null.
- Auto-created from meeting attendees; enriched manually via People Base.
- Example: `50-people/jordan-reyes.md`

### Decision — `30-projects/{slug}/decisions/YYYY-MM-DD-{summary}.md` · Base: `Decisions.base`

```yaml
object: decision
required: [type, project, date, status, summary]
optional: [supersedes, source, tags]
enums:
  type: [decision]
  status: [active, superseded, withdrawn]
tags:
  vocabulary: [scope, platform, staffing, methodology, commercial, timing,
               stakeholder]
  max: 2
```

- **Edges:** `supersedes` (`[[decision]]` / null) · `source` (`[[meeting]]`).
- Never deleted — status flips only. Supersession is a wikilink edge.
- Example: `30-projects/acme-industries-operating-model/decisions/2026-05-20-single-vendor-strategy-adopted.md`

### Entity — `40-entities/{slug}/dossier.md` · Base: `Entities.base`

An entity is any organization the executive maintains a working relationship
with: a client, a business unit, a partner, a supplier.

```yaml
object: entity
required: [type, entity-name, slug, status]
optional: [entity-type, industry, owner, created, last-updated]
enums:
  status: [prospect, active, dormant]
  entity-type: [client, business-unit, partner, supplier, other]
```

A filled dossier's frontmatter looks like this (an example, not the schema):

```yaml
type: entity
entity-name: "Acme Industries"
slug: acme-industries        # MUST equal the folder name AND the entity: value on projects (join key)
entity-type: client
status: active
industry: "Industrial manufacturing"
owner: jordan-reyes
created: 2026-02-07
last-updated: 2026-04-01
```

- `slug` MUST equal the folder name AND the `entity:` value on its projects —
  it is the join key.
- Dates written **unquoted ISO** (`2026-02-07`) — quoted dates silently break
  Bases/Dataview date handling. This convention applies to every object type.
- Per-entity project lists come free by grouping `Projects.base` on `entity`.

## 2. Relationship graph

- `Meeting —projects[]→ Project`
- `Meeting —attendees[]→ Person`
- `Project —entity→ Entity`
- `Decision —project→ Project`
- `Decision —source→ Meeting`
- `Decision —supersedes→ Decision`
`````

- [ ] **Step 2: Verify the doc parses as intended**

Run:
```bash
python3 - <<'EOF'
import re, yaml, pathlib
text = pathlib.Path("template/99-workflow-config/reference/ontology.md").read_text()
blocks = [yaml.safe_load(m.group(1)) for m in re.finditer(r"^```yaml\s*\n(.*?)^```\s*$", text, re.M | re.S)]
schemas = [b for b in blocks if isinstance(b, dict) and "object" in b]
print("total yaml blocks:", len(blocks), "| schema blocks:", sorted(b["object"] for b in schemas))
assert sorted(b["object"] for b in schemas) == ["decision", "entity", "meeting", "person", "project"]
assert "1:1" in next(b for b in schemas if b["object"] == "meeting")["enums"]["type"]
assert None in next(b for b in schemas if b["object"] == "person")["enums"]["relationship"]
print("OK")
EOF
```
Expected: `total yaml blocks: 6 | schema blocks: ['decision', 'entity', 'meeting', 'person', 'project']` then `OK` (6 = 5 schema blocks + the Entity example, which has no `object` key).

- [ ] **Step 3: Verify nothing else broke**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all pass, 48 tests (guard still hand-coded at this point — the doc rewrite must not disturb it).

- [ ] **Step 4: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md
git commit -m "$(cat <<'EOF'
feat(template): normative ontology schema as fenced YAML blocks

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Guard loads SCHEMAS from the ontology blocks

**Files:**
- Modify: `scripts/tests/test_fixtures_ontology.py` (replace the top section — docstring through the `MINIMUMS` dict — and the tags-vocabulary constants; everything from `def parse_frontmatter` onward stays as-is except the two named edits in Step 3)

**Interfaces:**
- Consumes: the five `object:`-keyed yaml blocks from Task 1 (exact key shape documented there).
- Produces: module-level `SCHEMAS` with the same merged shape all existing tests already use (`glob`, `required`, `enums` as sets, `keys_present`, `slug_must_match_*`), plus `load_ontology_schemas()`, `HARNESS`, `DECISION_TAGS_VOCABULARY`, `DECISION_TAGS_MAX`.

- [ ] **Step 1: Write the failing test first**

Append to `scripts/tests/test_fixtures_ontology.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py -k wellformed -v`
Expected: FAIL with `NameError: name 'load_ontology_schemas' is not defined`.

- [ ] **Step 3: Rewire the module top**

In `scripts/tests/test_fixtures_ontology.py`, replace everything from the module docstring down to (and including) the `MINIMUMS = ...` line with:

```python
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
```

Then two targeted edits further down, leaving everything else untouched:

1. Delete the old standalone `DECISION_TAGS_VOCABULARY = { ... }` set literal that sat above `test_decision_tags_within_controlled_vocabulary` (it is now defined at the top, from the doc).
2. In `test_decision_tags_within_controlled_vocabulary`, replace the hardcoded max line:

```python
        assert len(tags) <= 2, f"{path}: more than 2 tags"
```

with:

```python
        assert len(tags) <= DECISION_TAGS_MAX, f"{path}: more than {DECISION_TAGS_MAX} tags"
```

- [ ] **Step 4: Run the new test, then the full suite**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py -v`
Expected: all tests PASS including `test_ontology_schema_blocks_present_and_wellformed` — same schema values, new source of truth.

Run: `python3 -m pytest scripts/tests -q`
Expected: `49 passed` (48 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_fixtures_ontology.py
git commit -m "$(cat <<'EOF'
test: load conformance schemas from ontology.md yaml blocks

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Drift acceptance check + design-doc rider

**Files:**
- Modify: `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md` (append one open-question bullet)

**Interfaces:**
- Consumes: Tasks 1–2 complete.
- Produces: nothing downstream — this closes out issue #26's acceptance criterion and rider.

- [ ] **Step 1: Prove the drift check works (issue #26's acceptance test)**

Temporarily edit `template/99-workflow-config/reference/ontology.md`: in the meeting block's `type` enum, remove `brainstorm`. Run:

```bash
python3 -m pytest scripts/tests/test_fixtures_ontology.py -k meeting -q
```

Expected: FAILURES naming the member — `test_object_type_frontmatter_conforms[meeting]` fails on the brainstorm fixture (`type='brainstorm' not in {...}`). Then **revert the edit** (`git checkout -- template/99-workflow-config/reference/ontology.md`) and re-run the full suite: `python3 -m pytest scripts/tests -q` → `49 passed`. Record both outputs in your report — this proves no second edit location exists.

- [ ] **Step 2: Add the parked open question to the design doc**

In `docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md`: if a `## Open questions` section exists, append the bullet below to it; otherwise append the section header and the bullet at the end of the file.

```markdown
## Open questions

- **Obsidian as the exec surface vs. a custom local-first app** on the
  markdown layer: revisit after the v1.0 pilot with exec-usage data (do
  execs open Obsidian at all, or live in Claude + email?). Until then the
  markdown + YAML data layer stays surface-agnostic; the only
  Obsidian-proprietary surfaces are `.obsidian/` config and the `.base`
  views, both thin YAML. (Parked 2026-08-23.)
```

(If the section already exists, omit the `## Open questions` header line and append only the bullet.)

- [ ] **Step 3: Full verification trio**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all pass, 49 tests.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-08-22-second-brain-accelerator-design.md
git commit -m "$(cat <<'EOF'
docs: park the Obsidian-vs-local-first-app surface question until pilot

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** issue #26 deliverable 1 (YAML blocks in the doc) → Task 1; deliverable 2 (guard loads blocks, hand-coded dict deleted, harness concerns stay) → Task 2; deliverable 3 (suite green before == after) → enforced in every task's verification; deliverable 4 (design-doc rider) → Task 3; acceptance test → Task 3 Step 1.
- **The Entity example block** in the doc parses as a dict WITHOUT an `object` key → the loader skips it by design; Task 1 Step 2 asserts exactly 6 yaml blocks / 5 schema blocks so an accidental sixth schema block fails fast.
- **Import-time loading:** `SCHEMAS = build_schemas()` runs at module import, so a malformed doc surfaces as a pytest collection error carrying the `RuntimeError` message naming `ontology.md` — loud and named, satisfying the issue's failure-mode requirement; the dedicated wellformed-test additionally covers shape drift that still parses.
- **Value-identity check:** the YAML blocks in Task 1 were transcribed from the current guard's `SCHEMAS`/vocabulary and cross-checked member-by-member (incl. quoted `"1:1"`, `null` in the person relationship enum, the 7-word tags vocabulary, max 2). `optional` lists are documentation-only today (the guard doesn't enforce them) — they come from the current doc's prose (calendar-matched fields, recorder provenance, triage booleans, auto-maintained project fields, `type` on projects as used by the fixtures).
