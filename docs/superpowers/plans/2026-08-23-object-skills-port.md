# Object Skills Port (P1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `/new-project` and `/update-entity` as the first two skills in the plugin, backed by a deterministic stdlib-only CLI whose write path enforces the same ontology contract CI checks.

**Architecture:** The model decides (slug quality, context extraction, section routing, prose); a Python CLI writes (validation, collision detection, frontmatter emission, table merges, atomic writes). The ontology's fenced YAML blocks are compiled to a checked-in `schema.json` that the CLI reads at runtime, with a CI test proving the two agree.

**Tech Stack:** Python 3.10 (syntax floor), stdlib only at runtime; PyYAML dev/CI-time only; pytest; Obsidian Dataview blocks in project index bodies.

**Spec:** `docs/superpowers/specs/2026-08-23-object-skills-port-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.10 is the syntax floor.** Cowork's VM ships 3.10; repo CI runs 3.13. No `match` statements, no PEP 604 unions in runtime-evaluated positions without `from __future__ import annotations`.
- **`plugin/lib/` imports stdlib only.** No PyYAML, no third-party anything. PyYAML is allowed in `scripts/` and in tests.
- **Every file write uses `encoding="utf-8"` and `newline="\n"`.** A Windows-side write must never inject CRLF into markdown that syncs to a Mac.
- **Vault root is always an explicit parameter.** Never derive it from `__file__` or `cwd` — under Cowork it is a mount point, not `/Users/...` or `C:\...`.
- **Collision checks are case-insensitive.** Linux in the VM allows `Foo/` and `foo/`; the APFS/NTFS host collapses them.
- **Clean-room rule (hard):** nothing under `plugin/`, `template/`, or `fixtures/` may contain `michael`, `bulthe`, `bulthé`, or `busdev` (case-insensitive substrings, `scripts/cleanroom-denylist.txt`). The sole exemption is the matched span `upstreamed-from: busdev@<sha>`.
- **Provenance:** both SKILL.md files carry `upstreamed-from: busdev@ccc27b8` in frontmatter.
- **Skill frontmatter:** `name` (must equal the directory name), `description`, `user_invocable: true`.
- **Dates:** unquoted ISO `YYYY-MM-DD` in frontmatter. Quoted dates break Bases/Dataview.
- **`project-type` enum after Task 1:** exactly `[initiative, area-of-responsibility]`.
- **Entity `body_sections`:** exactly `[Context, Stakeholders, Relationship History, Meeting Log, Sensitivities, Engagements]`.
- **Project `body_sections`:** exactly `[Decisions, Open Items, Related Meetings]`.
- **Commit trailer, every commit, exact:** `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Never commit to `main`.** Work stays on `feat/object-skills-port`.
- **Three checks must pass before the PR:** `python3 scripts/lint_plugin.py`, `python3 scripts/validate_template.py`, `python3 -m pytest scripts/tests -q`.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/compile_ontology.py` | Parse ontology.md's fenced yaml blocks (PyYAML), emit `schema.json`. Dev-time only. |
| `plugin/lib/vaultlib/naming.py` | Slug derivation and validation. Pure strings, no filesystem. |
| `plugin/lib/vaultlib/markdown.py` | Frontmatter parse/emit, targeted field replacement, H2/H3 section splitting. |
| `plugin/lib/vaultlib/schema.py` | Load `schema.json`; validate a frontmatter dict against one object schema. |
| `plugin/lib/vaultlib/vault.py` | Vault root resolution, atomic writes, identity-block extraction, date helper. |
| `plugin/lib/vaultlib/person.py` | `person ensure` — create a person note if absent. |
| `plugin/lib/vaultlib/project.py` | `project scaffold` — validate, write `index.md`, create `decisions/`. |
| `plugin/lib/vaultlib/entity.py` | `entity ensure/read/write` — dossier creation and section merges. |
| `plugin/lib/vaultlib/cli.py` | argparse dispatch; JSON on stdout; exit code signals success. |
| `plugin/skills/new-project/SKILL.md` | Conversation + judgment for project creation; delegates writes. |
| `plugin/skills/update-entity/SKILL.md` | Conversation + routing for dossier updates; delegates writes. |
| `plugin/CLAUDE.md` | Internal plugin instructions: CLI invocation, interpreter resolution, stdlib rule. |
| `.claude-plugin/marketplace.json` | Repo-root marketplace manifest (internal/dev + Cowork hand-testing). |

Natural review halves: Tasks 1–5 are the library; Tasks 6–11 are the skills, fixtures and plumbing. Worth an intermediate look before Task 6.

---

### Task 1: Ontology narrows to two project types and gains machine-readable body structure

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md`
- Create: `scripts/compile_ontology.py`
- Create: `plugin/lib/vaultlib/schema.json` (generated)
- Create: `scripts/tests/test_compile_ontology.py`
- Modify: `fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/index.md:6`
- Modify: `fixtures/demo-vault/30-projects/meridian-yard-automation-program/index.md:6`
- Modify: `fixtures/demo-vault/30-projects/meridian-warehouse-pilot-phase-0/index.md:6`
- Modify: `fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/index.md:6`
- Modify: `fixtures/demo-vault/99-workflow-config/context/role-and-responsibilities.md:18`

**Interfaces:**
- Consumes: nothing.
- Produces: `plugin/lib/vaultlib/schema.json` with shape
  `{"generated_from": str, "objects": {<name>: {"required": [str], "optional": [str], "enums": {str: [str]}, "keys_present": [str], "body_sections": [str], "tags": {...}}}}`.
  Keys absent from a block are omitted. Consumed by Task 3's `schema.py`.

- [ ] **Step 1: Change the project-type enum and add body_sections to the two blocks**

In `template/99-workflow-config/reference/ontology.md`, replace the `object: project` block with:

```yaml
object: project
required: [project-name, slug, status, project-type, entity, owner, created,
           last-updated]
optional: [type, parent, stakeholders, meetings-7d, meetings-30d, key-people,
           next-milestone, next-milestone-date]
enums:
  status: [active, paused, completed, cancelled]
  project-type: [initiative, area-of-responsibility]
body_sections: [Decisions, Open Items, Related Meetings]
```

Replace the `object: entity` block with:

```yaml
object: entity
required: [type, entity-name, slug, status]
optional: [entity-type, industry, owner, created, last-updated]
enums:
  status: [prospect, active, dormant]
  entity-type: [client, business-unit, partner, supplier, other]
body_sections: [Context, Stakeholders, Relationship History, Meeting Log,
                Sensitivities, Engagements]
```

- [ ] **Step 2: Document the two-value axis in the Project prose**

Immediately after the project block's bullet list, add:

```markdown
- **`project-type` is one axis: timeboxed vs ongoing.** `initiative` is
  bounded work with an end; `area-of-responsibility` is a standing
  responsibility with no end date. Counterparty is deliberately *not*
  encoded here — a project's `entity` joins to an Entity whose `entity-type`
  already says whether the work faces a client, a partner, a supplier, or
  your own business unit. Areas of responsibility are always top-level: they
  never carry a `parent`.
```

- [ ] **Step 3: Add the Entity body schema to §Entity**

After the existing filled-dossier example block in §Entity, add:

````markdown
### Entity body structure

The dossier body carries exactly the six H2 sections in `body_sections`
above, in that order. Two skills write it — `/new-project` creates a
baseline, `/update-entity` maintains it — so this is the shared contract, not
a per-skill template.

| Section | Shape | Merge rule |
|---|---|---|
| `## Context` | `- **{Label}:** {fact} — {why it matters}` | Update the bullet with a matching label; otherwise append. Maximum 8 bullets; consolidate the least important rather than exceeding it. |
| `## Stakeholders` | Table: Name · Title · Role in Decision · Stance · Notes | Match on name, case-insensitive. Update only fields carrying new information; never overwrite specific data with vaguer data. Never remove a row. New rows get `<!-- needs-review -->` in Notes. |
| `## Relationship History` | `- **{YYYY-MM-DD}:** {what happened} — {significance}` | Insert in date order. Never modify or remove an existing entry. |
| `## Meeting Log` | `### {YYYY-MM-DD} — {Topic}` then Attendees / Key outcomes / Follow-ups / Dynamics bullets | Append-only, newest first (prepend). Never modify an existing entry. |
| `## Sensitivities` | `- **{topic}:** {detail} — {implications}` | Update a matching topic; otherwise append. Never remove. |
| `## Engagements` | Table: Project · Status · One-liner | Match on project slug. Update status and one-liner. Never remove. Link `[{slug}](../../30-projects/{slug}/index.md)`. |

Empty sections carry `*No entries yet.*` — replaced on first real entry.

**Role in Decision** vocabulary: sponsor · champion · evaluator · influencer
· blocker. **Stance** vocabulary: champion · neutral · blocker.

**Unvalidated marking.** Content that was generated rather than confirmed by
a human carries `<!-- unvalidated -->` directly under its section header, and
the file carries a top banner:

```
> [!unvalidated] Generated context — verify before relying on details.
```

When a human supplies content for a section, drop that section's marker. When
the last marker goes, drop the banner. This is the vault's "be epistemically
honest" rule made mechanical; keep it even where no skill currently generates
context, because `/setup-my-brain` will.
````

- [ ] **Step 4: Write the schema compiler**

Create `scripts/compile_ontology.py`:

```python
#!/usr/bin/env python3
"""Compile the ontology's fenced yaml blocks into plugin/lib/vaultlib/schema.json.

The ontology doc stays the single human-editable source of truth. The plugin's
runtime cannot depend on PyYAML (unverified in the Cowork VM), so the schema
is compiled here — at dev time, where PyYAML is available — and the generated
JSON is checked in. scripts/tests/test_compile_ontology.py regenerates and
diffs, so editing the ontology without regenerating fails CI.

Usage:
    python3 scripts/compile_ontology.py            # write schema.json
    python3 scripts/compile_ontology.py --check    # exit 1 if stale
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_DOC = REPO_ROOT / "template" / "99-workflow-config" / "reference" / "ontology.md"
SCHEMA_JSON = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "schema.json"
SOURCE_LABEL = "template/99-workflow-config/reference/ontology.md"

YAML_FENCE_RE = re.compile(r"^```yaml\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

CARRIED_KEYS = ("required", "optional", "enums", "keys_present", "body_sections", "tags")


def load_blocks(doc: Path) -> dict:
    """Return {object-name: block} for every fenced yaml block with an
    `object:` key. Narrative example blocks are skipped; malformed or
    duplicated blocks raise, because a broken ontology must fail loudly."""
    blocks = {}
    for match in YAML_FENCE_RE.finditer(doc.read_text(encoding="utf-8")):
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            raise RuntimeError(f"{doc}: unparseable yaml block: {exc}") from exc
        if not isinstance(data, dict) or "object" not in data:
            continue
        name = data["object"]
        if name in blocks:
            raise RuntimeError(f"{doc}: duplicate schema block for {name!r}")
        blocks[name] = data
    if not blocks:
        raise RuntimeError(f"{doc}: no schema blocks found")
    return blocks


def compile_schema(doc: Path = ONTOLOGY_DOC) -> dict:
    objects = {}
    for name, block in sorted(load_blocks(doc).items()):
        objects[name] = {key: block[key] for key in CARRIED_KEYS if key in block}
    return {"generated_from": SOURCE_LABEL, "objects": objects}


def render(schema: dict) -> str:
    """Stable bytes: sorted keys, two-space indent, trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the checked-in schema.json is stale")
    args = parser.parse_args(argv)
    rendered = render(compile_schema())
    if args.check:
        current = SCHEMA_JSON.read_text(encoding="utf-8") if SCHEMA_JSON.is_file() else ""
        if current != rendered:
            print(f"{SCHEMA_JSON.relative_to(REPO_ROOT)} is stale — "
                  f"run: python3 scripts/compile_ontology.py")
            return 1
        return 0
    SCHEMA_JSON.parent.mkdir(parents=True, exist_ok=True)
    with SCHEMA_JSON.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    print(f"wrote {SCHEMA_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Write the failing regeneration test**

Create `scripts/tests/test_compile_ontology.py`:

```python
"""The checked-in schema.json must be exactly what the ontology compiles to."""
from pathlib import Path

import pytest

import compile_ontology as co

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_schema_json_is_not_stale():
    assert co.SCHEMA_JSON.is_file(), (
        "plugin/lib/vaultlib/schema.json is missing — "
        "run: python3 scripts/compile_ontology.py"
    )
    expected = co.render(co.compile_schema())
    actual = co.SCHEMA_JSON.read_text(encoding="utf-8")
    assert actual == expected, (
        "schema.json does not match ontology.md — "
        "run: python3 scripts/compile_ontology.py"
    )


def test_check_mode_agrees_with_the_file_on_disk():
    assert co.main(["--check"]) == 0


def test_all_five_objects_compile():
    objects = co.compile_schema()["objects"]
    assert set(objects) == {"meeting", "project", "person", "decision", "entity"}
    for name, block in objects.items():
        assert block["required"], f"{name}: empty required list"


def test_project_type_enum_is_the_two_value_axis():
    project = co.compile_schema()["objects"]["project"]
    assert project["enums"]["project-type"] == ["initiative", "area-of-responsibility"]


def test_body_sections_are_carried_for_project_and_entity():
    objects = co.compile_schema()["objects"]
    assert objects["project"]["body_sections"] == [
        "Decisions", "Open Items", "Related Meetings",
    ]
    assert objects["entity"]["body_sections"] == [
        "Context", "Stakeholders", "Relationship History",
        "Meeting Log", "Sensitivities", "Engagements",
    ]


@pytest.mark.parametrize("object_name", ["meeting", "person", "decision"])
def test_objects_without_body_schema_omit_the_key(object_name):
    assert "body_sections" not in co.compile_schema()["objects"][object_name]
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `python3 -m pytest scripts/tests/test_compile_ontology.py -q`
Expected: FAIL — `test_schema_json_is_not_stale` asserts on the missing file with "schema.json is missing".

- [ ] **Step 7: Generate the schema and re-run**

```bash
python3 scripts/compile_ontology.py
python3 -m pytest scripts/tests/test_compile_ontology.py -q
```

Expected: `wrote plugin/lib/vaultlib/schema.json`, then 7 passed.

- [ ] **Step 8: Re-tag the four fixture project types**

Change `project-type:` on line 6 of each:

| File | From | To |
|---|---|---|
| `nordbridge-regional-rollout-proposal/index.md` | `presales` | `initiative` |
| `meridian-yard-automation-program/index.md` | `delivery` | `initiative` |
| `meridian-warehouse-pilot-phase-0/index.md` | `delivery` | `initiative` |
| `commercial-ops-crm-modernization/index.md` | `internal` | `initiative` |

`commercial-ops-pipeline-governance/index.md` already reads
`area-of-responsibility` — leave it. That gives 4 × `initiative` + 1 ×
`area-of-responsibility`, so `test_project_type_enum_fully_covered` still
sees full coverage.

- [ ] **Step 9: Reword the one context-portfolio sentence**

In `fixtures/demo-vault/99-workflow-config/context/role-and-responsibilities.md`,
line 18 reads:

```
Owns the commercial P&L: new-logo growth (presales), existing-client delivery
```

Replace `(presales)` with `(new pursuits)` so no fixture prose carries the
retired enum value.

- [ ] **Step 10: Run the full suite**

Run: `python3 -m pytest scripts/tests -q`
Expected: PASS — 72 tests (65 existing + 7 new). If
`test_project_type_enum_fully_covered` fails, a fixture re-tag was missed.

- [ ] **Step 11: Run the other two checks**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: both silent, exit 0.

- [ ] **Step 12: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md \
        scripts/compile_ontology.py \
        scripts/tests/test_compile_ontology.py \
        plugin/lib/vaultlib/schema.json \
        fixtures/demo-vault/30-projects \
        fixtures/demo-vault/99-workflow-config/context/role-and-responsibilities.md
git commit -m "$(cat <<'EOF'
feat: narrow project-type to two values and compile the ontology to JSON

project-type becomes initiative | area-of-responsibility — one axis,
timeboxed vs ongoing. The four-value enum conflated lifecycle with
counterparty, and counterparty is already carried by a project's entity via
entity-type. Free to change now: registry.yaml is empty, so no deployed vault
needs re-tagging.

Adds body_sections to the project and entity blocks so body structure becomes
machine truth alongside frontmatter, and a compiler that derives
plugin/lib/vaultlib/schema.json from the ontology. The plugin runtime cannot
depend on PyYAML (unverified in the Cowork VM), so the schema is compiled at
dev time and checked in, with a test that regenerates and diffs.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: vaultlib naming — slug derivation and validation

**Files:**
- Create: `plugin/lib/vaultlib/__init__.py`
- Create: `plugin/lib/vaultlib/naming.py`
- Create: `scripts/tests/test_vaultlib_naming.py`
- Modify: `scripts/tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MAX_SLUG_LENGTH: int = 60`
  - `RESERVED_STEMS: frozenset[str]`
  - `slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str`
  - `validate_slug(slug: str) -> None` — raises `ValueError`
  - `find_collision(slug: str, existing: Iterable[str]) -> Optional[str]`

- [ ] **Step 1: Put `plugin/lib` on the test import path**

Replace `scripts/tests/conftest.py` with:

```python
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# scripts/ — for compile_ontology, lint_plugin, validate_template, make_test_vault
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# plugin/lib/ — for the vaultlib package the skills call at runtime
sys.path.insert(0, str(REPO_ROOT / "plugin" / "lib"))
```

- [ ] **Step 2: Write the failing tests**

Create `scripts/tests/test_vaultlib_naming.py`:

```python
"""Slug rules. Pure string logic, so this is where the edge cases live."""
import pytest

from vaultlib import naming


@pytest.mark.parametrize("text,expected", [
    ("Yard Automation Program", "yard-automation-program"),
    ("AI Delivery Platform Choice", "ai-delivery-platform-choice"),
    ("  leading and trailing  ", "leading-and-trailing"),
    ("Multiple   spaces", "multiple-spaces"),
    ("Punctuation: it's here!", "punctuation-it-s-here"),
    ("Already-Hyphenated", "already-hyphenated"),
    ("Numbers 123 stay", "numbers-123-stay"),
    ("Ampersand & more", "ampersand-more"),
    ("Em — dash", "em-dash"),
])
def test_slugify_shapes(text, expected):
    assert naming.slugify(text) == expected


def test_slugify_folds_accents_to_ascii():
    assert naming.slugify("Café Zürich naïve") == "cafe-zurich-naive"


def test_slugify_truncates_without_leaving_a_partial_word():
    text = "quarterly commercial operations pipeline governance review programme"
    result = naming.slugify(text, max_length=40)
    assert len(result) <= 40
    assert not result.endswith("-")
    # every segment survives whole
    assert all(segment in text.lower().split() for segment in result.split("-"))


def test_slugify_respects_an_exact_length_boundary():
    # 'abcde-fghij' is 11 chars; a limit of 11 keeps both segments
    assert naming.slugify("abcde fghij", max_length=11) == "abcde-fghij"
    # a limit of 10 cuts mid-segment, so the partial segment is dropped
    assert naming.slugify("abcde fghij", max_length=10) == "abcde"


def test_slugify_raises_when_nothing_survives():
    with pytest.raises(ValueError, match="produced an empty slug"):
        naming.slugify("!!! ???")


@pytest.mark.parametrize("slug", [
    "meridian-freight-holdings", "a", "a1", "yard-2", "one-two-three",
])
def test_validate_slug_accepts_well_formed(slug):
    naming.validate_slug(slug)


@pytest.mark.parametrize("slug,message", [
    ("", "empty"),
    ("Has-Upper", "lowercase"),
    ("has space", "lowercase"),
    ("has_underscore", "lowercase"),
    ("-leading", "lowercase"),
    ("trailing-", "lowercase"),
    ("double--hyphen", "lowercase"),
    ("con", "reserved"),
    ("NUL", "lowercase"),        # rejected on shape before reservation
    ("com1", "reserved"),
    ("lpt9", "reserved"),
    ("a" * 61, "exceeds"),
])
def test_validate_slug_rejects(slug, message):
    with pytest.raises(ValueError, match=message):
        naming.validate_slug(slug)


def test_find_collision_is_case_insensitive():
    existing = ["Meridian-Freight", "other-project"]
    assert naming.find_collision("meridian-freight", existing) == "Meridian-Freight"


def test_find_collision_returns_none_when_clear():
    assert naming.find_collision("new-thing", ["a", "b"]) is None


def test_find_collision_tolerates_an_empty_vault():
    assert naming.find_collision("first-project", []) is None
```

- [ ] **Step 3: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_naming.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vaultlib'`.

- [ ] **Step 4: Create the package marker**

Create `plugin/lib/vaultlib/__init__.py`:

```python
"""Deterministic vault operations for the Second Brain Accelerator plugin.

Stdlib only, on purpose: this package runs inside the Cowork Linux VM, where
PyYAML's presence is unverified. Python 3.10 is the syntax floor. See
docs/superpowers/specs/2026-08-23-object-skills-port-design.md.
"""
```

- [ ] **Step 5: Implement naming.py**

Create `plugin/lib/vaultlib/naming.py`:

```python
"""Slug derivation and validation. Pure string logic — no filesystem access."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

MAX_SLUG_LENGTH = 60

# Windows refuses these stems whatever the extension. The vault syncs to
# Windows machines even when written from the Cowork Linux VM, so a slug that
# is legal where it is created can be illegal where it lands.
RESERVED_STEMS = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)]
)

_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Lowercase, hyphen-joined, ASCII-only slug.

    Truncation drops a trailing partial segment rather than cutting a word in
    half, and the result is length-capped because a vault synced to Windows
    inherits its 260-character path limit.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG_CHARS.sub("-", ascii_only.lower()).strip("-")
    if not slug:
        raise ValueError(f"{text!r} produced an empty slug")
    if len(slug) <= max_length:
        return slug
    cut = slug[:max_length]
    # If the character just past the cut is neither the end nor a hyphen, the
    # cut landed inside a segment — drop that partial segment.
    if slug[max_length : max_length + 1] not in ("", "-"):
        head = cut.rpartition("-")[0]
        cut = head or cut
    result = cut.strip("-")
    if not result:
        raise ValueError(f"{text!r} produced an empty slug at max_length={max_length}")
    return result


def validate_slug(slug: str) -> None:
    """Raise ValueError if the slug is unusable as a folder or file stem."""
    if not slug:
        raise ValueError("slug is empty")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"slug {slug!r} must be lowercase alphanumeric segments joined by "
            "single hyphens, with no leading or trailing hyphen"
        )
    if len(slug) > MAX_SLUG_LENGTH:
        raise ValueError(f"slug {slug!r} exceeds {MAX_SLUG_LENGTH} characters")
    if slug in RESERVED_STEMS:
        raise ValueError(f"slug {slug!r} is a reserved filename on Windows")


def find_collision(slug: str, existing: Iterable[str]) -> Optional[str]:
    """Return the colliding existing name, or None.

    Case-insensitive: the Cowork VM is Linux and will create both `Foo` and
    `foo`, but the APFS or NTFS host underneath collapses them into one.
    """
    lowered = slug.lower()
    for name in existing:
        if name.lower() == lowered:
            return name
    return None
```

- [ ] **Step 6: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_naming.py -q`
Expected: PASS — 34 tests.

- [ ] **Step 7: Confirm the clean-room lint tolerates the new tree**

Run: `python3 scripts/lint_plugin.py`
Expected: silent, exit 0. `plugin/lib/` is not under `plugin/skills/`, so the
per-directory `SKILL.md` requirement does not apply to it; the clean-room
scan does cover it.

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/__init__.py plugin/lib/vaultlib/naming.py \
        scripts/tests/test_vaultlib_naming.py scripts/tests/conftest.py
git commit -m "$(cat <<'EOF'
feat: add vaultlib slug derivation and validation

Slugs are folder and file names, so the rules encode two portability hazards
the Cowork VM hides: collision checks are case-insensitive because Linux in
the VM will create both Foo/ and foo/ while the APFS or NTFS host collapses
them, and reserved Windows stems are rejected because a slug legal where it
is written can be illegal where it syncs. Truncation drops a trailing partial
segment instead of cutting a word in half.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: vaultlib markdown — frontmatter and sections without PyYAML

**Files:**
- Create: `plugin/lib/vaultlib/markdown.py`
- Create: `scripts/tests/test_vaultlib_markdown.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parse_frontmatter_block(block: str) -> dict`
  - `split_frontmatter(text: str) -> tuple[dict, str]` — returns `(data, body)`
  - `emit_frontmatter(data: Mapping, quote_keys: Collection[str] = ()) -> str`
  - `replace_scalar_field(text: str, field: str, value: str) -> str`
  - `split_sections(body: str, level: int = 2) -> list[tuple[str, str]]`
  - `render_sections(sections: Sequence[tuple[str, str]], level: int = 2) -> str`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_markdown.py`:

```python
"""Frontmatter and section handling. The parser is ours because PyYAML is not
verified present in the Cowork VM, so its narrow subset is pinned here."""
import pytest

from vaultlib import markdown as md

DOSSIER = """---
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

## Context

- **Industry:** freight — matters for yard scope.

## Stakeholders

| Name | Title |
|------|-------|
"""


def test_split_frontmatter_returns_data_and_body():
    data, body = md.split_frontmatter(DOSSIER)
    assert data["slug"] == "meridian-freight-holdings"
    assert data["entity-name"] == "Meridian Freight Holdings"
    assert body.startswith("\n## Context")


def test_dates_stay_verbatim_strings():
    data, _ = md.split_frontmatter(DOSSIER)
    assert data["created"] == "2025-09-15"
    assert data["last-updated"] == "2026-06-01"


def test_missing_frontmatter_raises():
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        md.split_frontmatter("# Just a heading\n")


def test_unterminated_frontmatter_raises():
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        md.split_frontmatter("---\nslug: x\n")


def test_crlf_input_parses():
    data, body = md.split_frontmatter("---\r\nslug: x\r\n---\r\n\r\nbody\r\n")
    assert data["slug"] == "x"
    assert "body" in body


def test_inline_list_parses():
    data = md.parse_frontmatter_block("stakeholders: [priya-nathan, leo-marchetti]")
    assert data["stakeholders"] == ["priya-nathan", "leo-marchetti"]


def test_empty_inline_list_parses():
    assert md.parse_frontmatter_block("stakeholders: []")["stakeholders"] == []


def test_inline_list_respects_quoted_commas():
    data = md.parse_frontmatter_block('tags: ["a, b", c]')
    assert data["tags"] == ["a, b", "c"]


def test_block_list_parses():
    data = md.parse_frontmatter_block("tags:\n  - platform\n  - commercial")
    assert data["tags"] == ["platform", "commercial"]


def test_bare_key_is_null_not_empty_list():
    # People.base's "Uncurated" view filters on relationship being null, so
    # this distinction is load-bearing.
    assert md.parse_frontmatter_block("relationship:")["relationship"] is None


def test_explicit_null_is_null():
    assert md.parse_frontmatter_block("parent: null")["parent"] is None


def test_integers_parse_as_integers():
    data = md.parse_frontmatter_block("meetings-7d: 0\nmeetings-30d: 12")
    assert data["meetings-7d"] == 0
    assert data["meetings-30d"] == 12


def test_booleans_parse_as_booleans():
    data = md.parse_frontmatter_block("reviewed: true\narchived: false")
    assert data["reviewed"] is True
    assert data["archived"] is False


def test_quoted_colon_value_survives():
    # An unquoted 1:1 would parse as the integer 61 in real YAML; ours keeps
    # the quoted form intact.
    assert md.parse_frontmatter_block('type: "1:1"')["type"] == "1:1"


def test_wikilink_value_survives():
    data = md.parse_frontmatter_block('source: "[[20-05-26-vendor-strategy]]"')
    assert data["source"] == "[[20-05-26-vendor-strategy]]"


def test_comments_and_blank_lines_are_ignored():
    data = md.parse_frontmatter_block("# a comment\n\nslug: x\n")
    assert data == {"slug": "x"}


def test_unparseable_line_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="unparseable"):
        md.parse_frontmatter_block("this has no colon")


def test_emit_frontmatter_round_trips():
    data = {"slug": "x", "stakeholders": ["a", "b"], "parent": None,
            "meetings-7d": 0, "reviewed": True}
    text = md.emit_frontmatter(data)
    assert text.startswith("---\n") and text.endswith("---\n")
    assert md.parse_frontmatter_block(text[4:-4]) == data


def test_emit_quotes_only_the_requested_keys():
    text = md.emit_frontmatter(
        {"project-name": "Yard Program", "slug": "yard-program"},
        quote_keys={"project-name"},
    )
    assert 'project-name: "Yard Program"' in text
    assert "slug: yard-program" in text


def test_emit_writes_null_as_a_bare_key():
    assert "parent:\n" in md.emit_frontmatter({"parent": None})


def test_emit_escapes_embedded_quotes():
    text = md.emit_frontmatter({"n": 'a "quoted" word'}, quote_keys={"n"})
    assert md.parse_frontmatter_block(text[4:-4])["n"] == 'a "quoted" word'


def test_replace_scalar_field_preserves_everything_else():
    updated = md.replace_scalar_field(DOSSIER, "last-updated", "2026-08-23")
    assert "last-updated: 2026-08-23" in updated
    assert 'entity-name: "Meridian Freight Holdings"' in updated
    assert updated.count("---") == DOSSIER.count("---")
    # body untouched
    assert updated.split("---\n", 2)[2] == DOSSIER.split("---\n", 2)[2]


def test_replace_scalar_field_raises_on_absent_field():
    with pytest.raises(ValueError, match="not present"):
        md.replace_scalar_field(DOSSIER, "nope", "x")


def test_replace_scalar_field_ignores_body_matches():
    text = "---\nstatus: active\n---\n\nstatus: decoy in the body\n"
    updated = md.replace_scalar_field(text, "status", "dormant")
    assert "status: dormant" in updated
    assert "status: decoy in the body" in updated


def test_split_sections_returns_titles_and_content():
    _, body = md.split_frontmatter(DOSSIER)
    sections = md.split_sections(body)
    assert [title for title, _ in sections] == ["", "Context", "Stakeholders"]
    assert "Industry" in dict(sections)["Context"]


def test_split_sections_ignores_h2_inside_fenced_code():
    body = "## Real\n\n```\n## Not a heading\n```\n\n## Also Real\n"
    assert [t for t, _ in md.split_sections(body)] == ["", "Real", "Also Real"]


def test_render_sections_round_trips():
    body = "\n## One\n\nalpha\n\n## Two\n\nbeta\n"
    assert md.render_sections(md.split_sections(body)) == body
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_markdown.py -q`
Expected: FAIL — `ImportError: cannot import name 'markdown'`.

- [ ] **Step 3: Implement markdown.py**

Create `plugin/lib/vaultlib/markdown.py`:

```python
"""Frontmatter and section handling for vault markdown.

Stdlib only, deliberately: PyYAML's presence in the Cowork VM is unverified.
The parser covers the flat subset vault frontmatter actually uses — scalars,
inline lists, block lists, nulls, integers, booleans — and raises on anything
outside it rather than guessing. CI's conformance guard still uses PyYAML, and
scripts/tests/test_vaultlib_markdown.py pins the subset both must agree on.
"""
from __future__ import annotations

import re
from typing import Collection, List, Mapping, Optional, Sequence, Tuple

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_KEY_RE = re.compile(r"\A([A-Za-z_][A-Za-z0-9_-]*):(.*)\Z")
_INT_RE = re.compile(r"\A-?\d+\Z")
_FENCE_RE = re.compile(r"\A\s*(```|~~~)")

_PENDING = object()


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _scalar(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        return inner.replace('\\"', '"') if raw[0] == '"' else inner
    if raw in ("", "null", "~"):
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if _INT_RE.match(raw):
        return int(raw)
    return raw


def _split_top_level(body: str) -> List[str]:
    """Split on commas that are not inside a quoted run."""
    parts, buf, quote = [], [], None
    for char in body:
        if quote:
            if char == quote:
                quote = None
            buf.append(char)
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return [part for part in (p.strip() for p in parts) if part]


def _inline_list(raw: str) -> list:
    inner = raw.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        raise ValueError(f"malformed inline list: {raw!r}")
    body = inner[1:-1].strip()
    return [_scalar(part) for part in _split_top_level(body)] if body else []


def parse_frontmatter_block(block: str) -> dict:
    """Parse the text between the `---` fences into a flat mapping."""
    data: dict = {}
    current_key: Optional[str] = None
    for line in _normalize(block).split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") or stripped == "-":
            if current_key is None:
                raise ValueError(f"list item before any key: {line!r}")
            if data[current_key] is _PENDING:
                data[current_key] = []
            data[current_key].append(_scalar(stripped[1:]))
            continue
        match = _KEY_RE.match(stripped)
        if not match:
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        key, rest = match.group(1), match.group(2).strip()
        if rest == "":
            # Could be a null value or the header of a block list — only the
            # next line tells us, so defer and resolve at the end.
            data[key] = _PENDING
            current_key = key
        elif rest.startswith("["):
            data[key] = _inline_list(rest)
            current_key = None
        else:
            data[key] = _scalar(rest)
            current_key = None
    return {key: (None if value is _PENDING else value) for key, value in data.items()}


def split_frontmatter(text: str) -> Tuple[dict, str]:
    """Return (frontmatter mapping, body). Raises if frontmatter is absent."""
    match = _FRONTMATTER_RE.match(_normalize(text))
    if not match:
        raise ValueError("file has no YAML frontmatter")
    return parse_frontmatter_block(match.group(1)), _normalize(text)[match.end():]


def _emit_scalar(value, quoted: bool) -> str:
    if quoted:
        return '"{}"'.format(str(value).replace('"', '\\"'))
    return str(value)


def emit_frontmatter(data: Mapping, quote_keys: Collection[str] = ()) -> str:
    """Render a frontmatter block.

    Quoting is caller-declared rather than inferred: the vault's convention is
    semantic (display names and prose quoted; slugs, enums and dates bare),
    which no syntactic rule can recover.
    """
    lines = ["---"]
    for key, value in data.items():
        quoted = key in quote_keys
        if value is None:
            lines.append(f"{key}:")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (list, tuple)):
            rendered = ", ".join(_emit_scalar(item, quoted) for item in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {_emit_scalar(value, quoted)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def replace_scalar_field(text: str, field: str, value: str) -> str:
    """Replace one top-level scalar inside existing frontmatter, leaving every
    other byte alone.

    Editing an existing note this way rather than re-emitting the whole block
    is what keeps hand-authored key order, quoting and comments intact.
    """
    normalized = _normalize(text)
    match = _FRONTMATTER_RE.match(normalized)
    if not match:
        raise ValueError("file has no YAML frontmatter")
    block = match.group(1)
    pattern = re.compile(rf"^({re.escape(field)}:)([ \t]*)(.*)$", re.MULTILINE)
    if not pattern.search(block):
        raise ValueError(f"field {field!r} is not present in frontmatter")
    updated_block = pattern.sub(rf"\g<1> {value}", block, count=1)
    return normalized[: match.start(1)] + updated_block + normalized[match.end(1):]


def split_sections(body: str, level: int = 2) -> List[Tuple[str, str]]:
    """Split a body into (heading title, content) pairs at the given heading
    level. Content before the first heading is returned under "".

    Headings inside fenced code blocks are ignored — project index bodies
    carry Dataview blocks, and a `##` inside one is not a section.
    """
    marker = "#" * level + " "
    sections: List[Tuple[str, List[str]]] = [("", [])]
    fence: Optional[str] = None
    for line in _normalize(body).split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            token = fence_match.group(1)
            fence = None if fence == token else (fence or token)
        if fence is None and line.startswith(marker):
            sections.append((line[len(marker):].strip(), []))
            continue
        sections[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in sections]


def render_sections(sections: Sequence[Tuple[str, str]], level: int = 2) -> str:
    """Inverse of split_sections."""
    marker = "#" * level + " "
    chunks = []
    for title, content in sections:
        chunks.append(content if not title else f"{marker}{title}\n{content}")
    return "\n".join(chunks)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_markdown.py -q`
Expected: PASS — 27 tests.

- [ ] **Step 5: Verify the two parsers agree on every fixture**

This is the divergence risk the compiled schema was meant to remove, so prove
it once against real files. Run:

```bash
python3 - <<'PY'
import sys, pathlib, yaml
sys.path.insert(0, "plugin/lib")
from vaultlib import markdown as md
root = pathlib.Path("fixtures/demo-vault")
checked = 0
for path in sorted(root.rglob("*.md")):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        continue
    ours, _ = md.split_frontmatter(text)
    theirs = yaml.safe_load(text.split("---", 2)[1])
    assert ours == theirs, f"{path}\n ours={ours}\n pyyaml={theirs}"
    checked += 1
print(f"{checked} fixture files: our parser and PyYAML agree")
PY
```

Expected: `N fixture files: our parser and PyYAML agree` with N ≥ 20. Any
mismatch is a real bug in `markdown.py` — fix it before continuing rather
than adjusting the assertion.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/markdown.py scripts/tests/test_vaultlib_markdown.py
git commit -m "$(cat <<'EOF'
feat: add stdlib frontmatter and section handling to vaultlib

Parses the flat subset vault frontmatter actually uses and raises on anything
outside it rather than guessing, because a parser that quietly half-reads a
note is worse than one that stops. Verified to agree with PyYAML across every
fixture note, since CI's conformance guard uses PyYAML and a divergence
between the two would be invisible.

Edits to existing notes go through replace_scalar_field rather than
re-emitting the block, so hand-authored key order and quoting survive.
Section splitting ignores headings inside fenced code, because project index
bodies carry Dataview blocks.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: vaultlib schema and vault — validation and safe filesystem access

**Files:**
- Create: `plugin/lib/vaultlib/schema.py`
- Create: `plugin/lib/vaultlib/vault.py`
- Create: `scripts/tests/test_vaultlib_schema.py`
- Create: `scripts/tests/test_vaultlib_vault.py`

**Interfaces:**
- Consumes: `naming`, `markdown` (Tasks 2–3); `schema.json` (Task 1).
- Produces:
  - `schema.load(path: Optional[Path] = None) -> dict`
  - `schema.for_object(name: str) -> dict` — raises `KeyError` on unknown
  - `schema.enum_values(object_name: str, field: str) -> list[str]`
  - `schema.body_sections(object_name: str) -> list[str]`
  - `schema.validate(object_name: str, frontmatter: Mapping) -> list[str]`
  - `vault.VaultError(Exception)`
  - `vault.resolve(raw: str) -> Path`
  - `vault.atomic_write(path: Path, text: str) -> None`
  - `vault.read_identity_block(root: Path) -> Optional[str]`
  - `vault.today_iso(explicit: Optional[str] = None) -> str`
  - `vault.list_dir_names(path: Path) -> list[str]`

- [ ] **Step 1: Write the failing schema tests**

Create `scripts/tests/test_vaultlib_schema.py`:

```python
"""The runtime schema is compiled from the ontology, so these tests assert the
contract the CLI relies on rather than restating the ontology."""
import pytest

from vaultlib import schema


def test_all_five_objects_are_present():
    assert set(schema.load()["objects"]) == {
        "meeting", "project", "person", "decision", "entity",
    }


def test_for_object_raises_on_unknown():
    with pytest.raises(KeyError, match="unknown object type"):
        schema.for_object("nonsense")


def test_enum_values_reads_the_two_value_axis():
    assert schema.enum_values("project", "project-type") == [
        "initiative", "area-of-responsibility",
    ]


def test_body_sections_for_entity():
    assert schema.body_sections("entity") == [
        "Context", "Stakeholders", "Relationship History",
        "Meeting Log", "Sensitivities", "Engagements",
    ]


def test_body_sections_empty_for_objects_without_one():
    assert schema.body_sections("meeting") == []


def test_validate_accepts_a_complete_project():
    problems = schema.validate("project", {
        "project-name": "Yard Program", "slug": "yard-program",
        "status": "active", "project-type": "initiative",
        "entity": "meridian-freight-holdings", "owner": "morgan-ellery",
        "created": "2026-08-23", "last-updated": "2026-08-23",
    })
    assert problems == []


def test_validate_reports_every_missing_required_field():
    problems = schema.validate("project", {"slug": "x"})
    joined = " ".join(problems)
    for field in ("project-name", "status", "project-type", "entity", "owner"):
        assert field in joined


def test_validate_rejects_an_empty_required_value():
    problems = schema.validate("entity", {
        "type": "entity", "entity-name": "", "slug": "x", "status": "active",
    })
    assert any("entity-name" in p for p in problems)


def test_validate_rejects_an_off_enum_value():
    problems = schema.validate("project", {
        "project-name": "X", "slug": "x", "status": "active",
        "project-type": "presales", "entity": "e", "owner": "o",
        "created": "2026-08-23", "last-updated": "2026-08-23",
    })
    assert any("presales" in p for p in problems)


def test_validate_ignores_absent_optional_fields():
    assert schema.validate("person", {"person-name": "A", "slug": "a",
                                      "relationship": None}) == []


def test_validate_requires_keys_present_even_when_null():
    problems = schema.validate("person", {"person-name": "A", "slug": "a"})
    assert any("relationship" in p for p in problems)


def test_validate_flags_unknown_fields():
    problems = schema.validate("person", {
        "person-name": "A", "slug": "a", "relationship": None, "invented": 1,
    })
    assert any("invented" in p for p in problems)
```

- [ ] **Step 2: Write the failing vault tests**

Create `scripts/tests/test_vaultlib_vault.py`:

```python
"""Filesystem access. Every test builds its own vault under tmp_path, because
the real vault root is a mount point in Cowork and must never be inferred."""
import pytest

from vaultlib import vault

IDENTITY = """# Identity

## Content

<!-- setup-my-brain:begin -->
Morgan Ellery — goes by Morgan. Chief Commercial Officer at Cascadia
Intermodal Group.
<!-- setup-my-brain:end -->
"""


def make_vault(tmp_path, identity_text=IDENTITY):
    root = tmp_path / "vault"
    for folder in ("10-inbox", "20-meetings", "30-projects", "40-entities",
                   "50-people", "60-daily-notes"):
        (root / folder).mkdir(parents=True)
    context = root / "99-workflow-config" / "context"
    context.mkdir(parents=True)
    if identity_text is not None:
        (context / "identity.md").write_text(identity_text, encoding="utf-8")
    return root


def test_resolve_accepts_a_real_vault(tmp_path):
    root = make_vault(tmp_path)
    assert vault.resolve(str(root)) == root.resolve()


def test_resolve_rejects_a_missing_directory(tmp_path):
    with pytest.raises(vault.VaultError, match="does not exist"):
        vault.resolve(str(tmp_path / "nope"))


def test_resolve_rejects_a_directory_that_is_not_a_vault(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(vault.VaultError, match="does not look like a vault"):
        vault.resolve(str(plain))


def test_resolve_expands_a_user_path(tmp_path, monkeypatch):
    root = make_vault(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert vault.resolve("~/vault") == root.resolve()


def test_atomic_write_creates_parents(tmp_path):
    target = tmp_path / "a" / "b" / "note.md"
    vault.atomic_write(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_atomic_write_uses_lf_even_on_windows(tmp_path):
    target = tmp_path / "note.md"
    vault.atomic_write(target, "one\ntwo\n")
    assert target.read_bytes() == b"one\ntwo\n"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "note.md"
    vault.atomic_write(target, "x\n")
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


def test_atomic_write_overwrites(tmp_path):
    target = tmp_path / "note.md"
    vault.atomic_write(target, "first\n")
    vault.atomic_write(target, "second\n")
    assert target.read_text(encoding="utf-8") == "second\n"


def test_read_identity_block_returns_the_delimited_content(tmp_path):
    root = make_vault(tmp_path)
    block = vault.read_identity_block(root)
    assert "Morgan Ellery" in block
    assert "setup-my-brain" not in block


def test_read_identity_block_returns_none_when_the_block_is_empty(tmp_path):
    root = make_vault(tmp_path, IDENTITY.replace(
        "Morgan Ellery — goes by Morgan. Chief Commercial Officer at Cascadia\n"
        "Intermodal Group.\n", ""))
    assert vault.read_identity_block(root) is None


def test_read_identity_block_returns_none_when_the_file_is_absent(tmp_path):
    root = make_vault(tmp_path, identity_text=None)
    assert vault.read_identity_block(root) is None


def test_today_iso_passes_through_an_explicit_date():
    assert vault.today_iso("2026-08-23") == "2026-08-23"


def test_today_iso_rejects_a_malformed_date():
    with pytest.raises(vault.VaultError, match="YYYY-MM-DD"):
        vault.today_iso("23-08-2026")


def test_today_iso_defaults_to_a_well_formed_date():
    assert len(vault.today_iso()) == 10


def test_list_dir_names_returns_only_directories(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c.md").write_text("x", encoding="utf-8")
    assert vault.list_dir_names(tmp_path) == ["a", "b"]


def test_list_dir_names_tolerates_a_missing_directory(tmp_path):
    assert vault.list_dir_names(tmp_path / "nope") == []
```

- [ ] **Step 3: Run both to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_schema.py scripts/tests/test_vaultlib_vault.py -q`
Expected: FAIL — `ImportError` for both `schema` and `vault`.

- [ ] **Step 4: Implement schema.py**

Create `plugin/lib/vaultlib/schema.py`:

```python
"""Load the compiled ontology schema and validate frontmatter against it.

schema.json is generated by scripts/compile_ontology.py from the ontology
doc; a CI test regenerates and diffs it, so this module can treat it as
authoritative without parsing YAML at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Mapping, Optional

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"

_cache: Optional[dict] = None


def load(path: Optional[Path] = None) -> dict:
    """Load and memoize the compiled schema."""
    global _cache
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    if _cache is None:
        _cache = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _cache


def for_object(name: str) -> dict:
    objects = load()["objects"]
    if name not in objects:
        raise KeyError(f"unknown object type {name!r}; known: {sorted(objects)}")
    return objects[name]


def enum_values(object_name: str, field: str) -> List[str]:
    return list(for_object(object_name).get("enums", {}).get(field, []))


def body_sections(object_name: str) -> List[str]:
    return list(for_object(object_name).get("body_sections", []))


def validate(object_name: str, frontmatter: Mapping) -> List[str]:
    """Return a list of human-readable problems; empty means conformant."""
    block = for_object(object_name)
    required = block.get("required", [])
    optional = block.get("optional", [])
    keys_present = block.get("keys_present", [])
    problems: List[str] = []

    for field in required:
        if field not in frontmatter:
            problems.append(f"missing required field {field!r}")
        elif frontmatter[field] in (None, ""):
            problems.append(f"required field {field!r} is empty")

    for field in keys_present:
        if field not in frontmatter:
            problems.append(f"missing required key {field!r} (value may be null)")

    for field, allowed in block.get("enums", {}).items():
        value = frontmatter.get(field)
        if field in frontmatter and value is not None and value not in allowed:
            problems.append(f"{field}={value!r} is not one of {allowed}")

    known = set(required) | set(optional) | set(keys_present) | set(block.get("enums", {}))
    for field in frontmatter:
        if field not in known:
            problems.append(
                f"unknown field {field!r} for object {object_name!r}; "
                "add it to the ontology block first"
            )
    return problems
```

- [ ] **Step 5: Implement vault.py**

Create `plugin/lib/vaultlib/vault.py`:

```python
"""Vault root resolution and safe writes.

The vault root is always supplied by the caller: under Cowork it is a VirtioFS
mount point, not a path shape anything can infer.
"""
from __future__ import annotations

import datetime as _datetime
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

IDENTITY_RELPATH = Path("99-workflow-config") / "context" / "identity.md"
_BEGIN = "<!-- setup-my-brain:begin -->"
_END = "<!-- setup-my-brain:end -->"
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

# A directory is a vault if it carries the config folder and at least one
# numbered content folder. Cheap, and it stops a mistyped path from scattering
# object folders across someone's home directory.
_MARKER = Path("99-workflow-config")
_CONTENT_FOLDERS = ("10-inbox", "20-meetings", "30-projects", "40-entities",
                    "50-people", "60-daily-notes")


class VaultError(Exception):
    """A vault path or argument the caller must fix."""


def resolve(raw: str) -> Path:
    root = Path(os.path.expanduser(str(raw))).resolve()
    if not root.is_dir():
        raise VaultError(f"vault path does not exist or is not a directory: {root}")
    if not (root / _MARKER).is_dir() or not any(
        (root / folder).is_dir() for folder in _CONTENT_FOLDERS
    ):
        raise VaultError(
            f"{root} does not look like a vault "
            f"(expected a {_MARKER}/ folder and at least one numbered content folder)"
        )
    return root


def atomic_write(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings, via a temp file in the same directory.

    newline="\\n" is explicit: a write from a Windows host must not inject
    CRLF into markdown that syncs to a Mac.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n",
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp", delete=False,
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, str(path))
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def read_identity_block(root: Path) -> Optional[str]:
    """Return the content between identity.md's setup-my-brain markers.

    Extraction only. Deciding *which* words in it are the executive's name is
    judgment, and stays with the model.
    """
    path = root / IDENTITY_RELPATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1 or end <= start:
        return None
    block = text[start + len(_BEGIN):end].strip()
    return block or None


def today_iso(explicit: Optional[str] = None) -> str:
    """Today as unquoted ISO. Explicit values keep the CLI deterministic."""
    if explicit is None:
        return _datetime.date.today().isoformat()
    if not _ISO_DATE_RE.match(explicit):
        raise VaultError(f"date {explicit!r} must be ISO YYYY-MM-DD")
    return explicit


def list_dir_names(path: Path) -> List[str]:
    if not path.is_dir():
        return []
    return sorted(entry.name for entry in path.iterdir() if entry.is_dir())
```

- [ ] **Step 6: Run to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_schema.py scripts/tests/test_vaultlib_vault.py -q`
Expected: PASS — 29 tests.

- [ ] **Step 7: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/schema.py plugin/lib/vaultlib/vault.py \
        scripts/tests/test_vaultlib_schema.py scripts/tests/test_vaultlib_vault.py
git commit -m "$(cat <<'EOF'
feat: add schema validation and safe vault writes to vaultlib

Validation reads the compiled schema.json rather than parsing YAML, so the
write path enforces the same ontology contract CI checks — closing the gap
where fixtures conformed but real output was unverified. Unknown fields are
flagged too: a skill inventing frontmatter should fail loudly rather than
quietly extend the object model.

resolve() refuses a directory that does not look like a vault, so a mistyped
path cannot scatter object folders across a home directory, and it never
infers the root — under Cowork that root is a mount point.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `person ensure` and the CLI skeleton

**Files:**
- Create: `plugin/lib/vaultlib/person.py`
- Create: `plugin/lib/vaultlib/cli.py`
- Create: `scripts/tests/test_vaultlib_person.py`
- Create: `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `naming.slugify`, `naming.validate_slug`, `markdown.emit_frontmatter`,
  `schema.validate`, `vault.resolve`, `vault.atomic_write`,
  `vault.read_identity_block`, `vault.today_iso`.
- Produces:
  - `person.PERSON_QUOTE_KEYS: frozenset[str]`
  - `person.ensure(root: Path, name: str, today: str) -> dict` returning
    `{"slug": str, "path": str, "created": bool}` — `path` is relative to the
    vault root, POSIX-separated.
  - `cli.main(argv: Optional[Sequence[str]] = None) -> int` — prints one JSON
    object to stdout; exit 0 on success, 1 on a handled error.
  - CLI surface: `identity show --vault P` ·
    `person ensure --vault P --name N [--today D]`
  - Error envelope used by every later subcommand:
    `{"ok": false, "error": "<message>", "hint": "<what to do>"}`
  - Success envelope: `{"ok": true, "result": {...}}`

- [ ] **Step 1: Write the failing person tests**

Create `scripts/tests/test_vaultlib_person.py`:

```python
"""Person notes. The executive's own note is created here, because a project
owner that joins to nothing is a hole in the relationship graph."""
import pytest

from vaultlib import markdown as md
from vaultlib import person, schema

from test_vaultlib_vault import make_vault


def test_ensure_creates_a_conformant_note(tmp_path):
    root = make_vault(tmp_path)
    result = person.ensure(root, "Morgan Ellery", "2026-08-23")
    assert result == {
        "slug": "morgan-ellery",
        "path": "50-people/morgan-ellery.md",
        "created": True,
    }
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    data, body = md.split_frontmatter(text)
    assert schema.validate("person", data) == []
    assert body.strip() == ""


def test_ensure_writes_relationship_as_a_present_null_key(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    data, _ = md.split_frontmatter(text)
    # People.base's "Uncurated" view filters on this being null, so the key
    # must exist with an empty value rather than be absent.
    assert "relationship" in data
    assert data["relationship"] is None


def test_ensure_quotes_the_display_name_and_leaves_the_slug_bare(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    assert 'person-name: "Morgan Ellery"' in text
    assert "slug: morgan-ellery" in text


def test_ensure_is_idempotent_and_does_not_rewrite(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    target = root / "50-people" / "morgan-ellery.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("relationship:", "relationship: colleague"),
        encoding="utf-8",
    )
    result = person.ensure(root, "Morgan Ellery", "2026-08-24")
    assert result["created"] is False
    # curation survives a second call
    assert "relationship: colleague" in target.read_text(encoding="utf-8")


def test_ensure_matches_an_existing_note_case_insensitively(tmp_path):
    root = make_vault(tmp_path)
    (root / "50-people" / "Morgan-Ellery.md").write_text(
        '---\nperson-name: "Morgan Ellery"\nslug: Morgan-Ellery\nrelationship:\n---\n',
        encoding="utf-8",
    )
    result = person.ensure(root, "Morgan Ellery", "2026-08-23")
    assert result["created"] is False
    assert result["path"] == "50-people/Morgan-Ellery.md"


def test_ensure_rejects_a_name_that_slugifies_to_nothing(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="empty slug"):
        person.ensure(root, "!!!", "2026-08-23")


def test_ensure_uses_lf_endings(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    raw = (root / "50-people" / "morgan-ellery.md").read_bytes()
    assert b"\r\n" not in raw
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_person.py -q`
Expected: FAIL — `ImportError: cannot import name 'person'`.

- [ ] **Step 3: Implement person.py**

Create `plugin/lib/vaultlib/person.py`:

```python
"""Person notes.

Auto-created from a display name. The body stays empty on purpose: person
notes are curated through People.base, and an invented body would be noise
the assistant has to clear.
"""
from __future__ import annotations

from pathlib import Path

from . import markdown, naming, vault

PEOPLE_DIR = "50-people"
PERSON_QUOTE_KEYS = frozenset({"person-name", "company", "role"})


def _existing_note(root: Path, slug: str):
    """Return an existing note path matching slug case-insensitively."""
    people = root / PEOPLE_DIR
    if not people.is_dir():
        return None
    lowered = slug.lower()
    for candidate in sorted(people.glob("*.md")):
        if candidate.stem.lower() == lowered:
            return candidate
    return None


def ensure(root: Path, name: str, today: str) -> dict:
    """Create 50-people/{slug}.md if no note for this person exists yet.

    Never rewrites an existing note — curation added through People.base must
    survive every later call.
    """
    slug = naming.slugify(name)
    naming.validate_slug(slug)

    found = _existing_note(root, slug)
    if found is not None:
        return {
            "slug": slug,
            "path": found.relative_to(root).as_posix(),
            "created": False,
        }

    frontmatter = {
        "person-name": name,
        "slug": slug,
        "email": None,
        # Key present with an empty value = uncurated. People.base's
        # "Uncurated" view filters on exactly this.
        "relationship": None,
        "company": None,
        "role": None,
        "projects": [],
        "created": today,
        "last-updated": today,
        "meetings-7d": 0,
        "meetings-30d": 0,
    }
    target = root / PEOPLE_DIR / f"{slug}.md"
    vault.atomic_write(
        target, markdown.emit_frontmatter(frontmatter, PERSON_QUOTE_KEYS)
    )
    return {"slug": slug, "path": target.relative_to(root).as_posix(), "created": True}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_person.py -q`
Expected: PASS — 7 tests.

- [ ] **Step 5: Write the failing CLI tests**

Create `scripts/tests/test_vaultlib_cli.py`:

```python
"""The CLI contract: one JSON object on stdout, exit code signals success.

Skills read this output, so the envelope shape is part of the interface and
changing it silently breaks every SKILL.md.
"""
import json

import pytest

from vaultlib import cli

from test_vaultlib_vault import make_vault


def run(capsys, argv):
    code = cli.main(argv)
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def test_identity_show_returns_the_content_block(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, ["identity", "show", "--vault", str(root)])
    assert code == 0
    assert payload["ok"] is True
    assert "Morgan Ellery" in payload["result"]["identity"]


def test_identity_show_reports_an_empty_portfolio_without_failing(capsys, tmp_path):
    root = make_vault(tmp_path, identity_text=None)
    code, payload = run(capsys, ["identity", "show", "--vault", str(root)])
    assert code == 0
    assert payload["result"]["identity"] is None


def test_person_ensure_returns_the_created_note(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(root),
        "--name", "Morgan Ellery", "--today", "2026-08-23",
    ])
    assert code == 0
    assert payload["result"] == {
        "slug": "morgan-ellery",
        "path": "50-people/morgan-ellery.md",
        "created": True,
    }


def test_a_bad_vault_path_is_a_structured_error_not_a_traceback(capsys, tmp_path):
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(tmp_path / "nope"), "--name", "A",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "does not exist" in payload["error"]
    assert payload["hint"]


def test_a_malformed_date_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "person", "ensure", "--vault", str(root),
        "--name", "A", "--today", "23-08-2026",
    ])
    assert code == 1
    assert "YYYY-MM-DD" in payload["error"]


def test_stdout_is_always_a_single_json_object(capsys, tmp_path):
    root = make_vault(tmp_path)
    cli.main(["identity", "show", "--vault", str(root)])
    out = capsys.readouterr().out
    assert out.endswith("\n")
    json.loads(out)  # raises if anything else was printed


def test_unknown_subcommand_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["nonsense"])
    assert excinfo.value.code != 0
```

- [ ] **Step 6: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_cli.py -q`
Expected: FAIL — `ImportError: cannot import name 'cli'`.

- [ ] **Step 7: Implement cli.py**

Create `plugin/lib/vaultlib/cli.py`:

```python
#!/usr/bin/env python3
"""Deterministic vault operations for the Second Brain Accelerator skills.

Skills call these subcommands via Bash and read one JSON object from stdout.
The model decides — slug quality, context extraction, section routing, prose —
and this CLI writes: validation, collision detection, frontmatter emission,
table merges, atomic writes.

Invoke it as:

    python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" <subcommand> --vault <path> ...

Every run prints exactly one JSON object:

    {"ok": true,  "result": {...}}                       exit 0
    {"ok": false, "error": "...", "hint": "..."}         exit 1

Stdlib only, Python 3.10 floor — this runs inside the Cowork Linux VM.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    # Executed as a file path rather than imported as a package, which is how
    # the skills invoke it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultlib import person, vault  # noqa: E402


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _ok(result: dict) -> int:
    _emit({"ok": True, "result": result})
    return 0


def _fail(message: str, hint: str) -> int:
    _emit({"ok": False, "error": message, "hint": hint})
    return 1


def _add_vault_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vault", required=True,
        help="absolute path to the vault root (a mount point under Cowork)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vaultlib", description=__doc__)
    top = parser.add_subparsers(dest="group", required=True)

    identity = top.add_parser("identity", help="read the context portfolio")
    identity_sub = identity.add_subparsers(dest="action", required=True)
    identity_show = identity_sub.add_parser(
        "show", help="print identity.md's setup-my-brain content block")
    _add_vault_argument(identity_show)

    people = top.add_parser("person", help="person notes")
    people_sub = people.add_subparsers(dest="action", required=True)
    person_ensure = people_sub.add_parser(
        "ensure", help="create a person note if none exists")
    _add_vault_argument(person_ensure)
    person_ensure.add_argument("--name", required=True, help="display name")
    person_ensure.add_argument("--today", help="ISO date; defaults to today")

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    root = vault.resolve(args.vault)
    if args.group == "identity":
        return _ok({"identity": vault.read_identity_block(root)})
    if args.group == "person":
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(person.ensure(root, args.name, today))
    raise AssertionError(f"unhandled group {args.group!r}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except vault.VaultError as exc:
        return _fail(str(exc), "Check the --vault path points at the vault root.")
    except ValueError as exc:
        return _fail(str(exc), "Fix the argument named in the error and retry.")
    except OSError as exc:
        return _fail(f"filesystem error: {exc}",
                     "Check the vault is mounted and writable from this session.")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS — 7 tests.

- [ ] **Step 9: Verify the file-path invocation the skills will actually use**

The tests import the package; the skills run it as a path. Prove both work:

```bash
rm -rf /tmp/cli-check
python3 scripts/make_test_vault.py /tmp/cli-check
python3 plugin/lib/vaultlib/cli.py identity show --vault /tmp/cli-check
```

Expected: a JSON object with `"ok": true` and Morgan Ellery's identity text.
If it raises `ImportError`, the `__package__` guard at the top of `cli.py` is
wrong — that guard is the only thing making path invocation work.

- [ ] **Step 10: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add plugin/lib/vaultlib/person.py plugin/lib/vaultlib/cli.py \
        scripts/tests/test_vaultlib_person.py scripts/tests/test_vaultlib_cli.py
git commit -m "$(cat <<'EOF'
feat: add the vaultlib CLI envelope and person-note creation

One JSON object on stdout, exit code signals success — skills read this, so
the envelope is interface, not formatting. Handled errors return a structured
message plus a hint instead of a traceback, because the reader is a model
deciding what to do next.

person ensure never rewrites an existing note: curation added through
People.base has to survive every later call, and matching is
case-insensitive so a host filesystem cannot end up with two notes for one
person. relationship is written as a present-but-null key, which is exactly
what People.base's Uncurated view filters on.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Task 6: `project scaffold`

**Files:**
- Create: `plugin/lib/vaultlib/project.py`
- Create: `scripts/tests/test_vaultlib_project.py`
- Modify: `plugin/lib/vaultlib/cli.py` (add the `project` group)

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces:
  - `project.PROJECT_QUOTE_KEYS: frozenset[str]`
  - `project.scaffold(root, *, name, project_type, entity, owner, today, parent=None, stage=None, contacts=None, source=None) -> dict`
    returning `{"slug": str, "path": str, "decisions_dir": str, "created": [str]}`
  - CLI: `project scaffold --vault P --name N --type T --entity E --owner O [--parent S] [--today D] [--stage TEXT] [--contacts TEXT] [--source TEXT]`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_project.py`:

```python
"""Project scaffolding. The guard rails here are the ones a model gets wrong:
collisions, parent depth, and areas that should never be nested."""
import pytest

from vaultlib import markdown as md
from vaultlib import project, schema

from test_vaultlib_vault import make_vault

BASE = dict(
    name="Yard Automation Program",
    project_type="initiative",
    entity="meridian-freight-holdings",
    owner="morgan-ellery",
    today="2026-08-23",
)


def vault_with_entity(tmp_path, slug="meridian-freight-holdings"):
    root = make_vault(tmp_path)
    dossier = root / "40-entities" / slug / "dossier.md"
    dossier.parent.mkdir(parents=True)
    dossier.write_text(
        f'---\ntype: entity\nentity-name: "E"\nslug: {slug}\nstatus: active\n---\n',
        encoding="utf-8",
    )
    return root


def test_scaffold_writes_a_conformant_index(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    assert result["slug"] == "yard-automation-program"
    assert result["path"] == "30-projects/yard-automation-program/index.md"
    data, _ = md.split_frontmatter(
        (root / result["path"]).read_text(encoding="utf-8"))
    assert schema.validate("project", data) == []
    assert data["project-type"] == "initiative"
    assert data["entity"] == "meridian-freight-holdings"
    assert data["owner"] == "morgan-ellery"
    assert data["created"] == "2026-08-23"
    assert data["parent"] is None


def test_scaffold_creates_the_decisions_directory(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    assert (root / result["decisions_dir"]).is_dir()
    assert result["decisions_dir"] == "30-projects/yard-automation-program/decisions"


def test_body_carries_the_three_ontology_sections(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    _, body = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    titles = [title for title, _ in md.split_sections(body) if title]
    assert titles == schema.body_sections("project")


def test_decisions_dataview_hardcodes_this_project_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    # Dataview does not reliably accept this.file.folder as a FROM source, so
    # the slug is substituted rather than derived at query time.
    assert 'FROM "30-projects/yard-automation-program/decisions"' in text


def test_related_meetings_dataview_matches_on_this_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'FROM "20-meetings"' in text
    assert "econtains(projects, this.slug)" in text


def test_no_attendee_self_filter_is_emitted(tmp_path):
    # The upstream query filtered the executive out by display name. That
    # cannot ship (clean-room) and would not work anyway: attendees are slugs.
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "a !=" not in text


def test_supplied_context_reaches_the_context_callout(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(
        root, **BASE, stage="Awaiting vendor shortlist",
        contacts="Leo Marchetti (COO)", source="Forwarded renewal email",
    )
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "Awaiting vendor shortlist" in text
    assert "Leo Marchetti (COO)" in text
    assert "Forwarded renewal email" in text


def test_absent_context_falls_back_to_placeholders(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "_none yet_" in text


def test_collision_is_refused_case_insensitively(tmp_path):
    root = vault_with_entity(tmp_path)
    (root / "30-projects" / "Yard-Automation-Program").mkdir(parents=True)
    with pytest.raises(project.ProjectError, match="already exists"):
        project.scaffold(root, **BASE)


def test_unknown_project_type_is_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    args = dict(BASE, project_type="presales")
    with pytest.raises(project.ProjectError, match="presales"):
        project.scaffold(root, **args)


def test_missing_entity_is_refused_with_an_actionable_message(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(project.ProjectError, match="entity ensure"):
        project.scaffold(root, **BASE)


def test_area_of_responsibility_refuses_a_parent(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Pipeline Governance"))
    args = dict(BASE, name="Nested Area",
                project_type="area-of-responsibility",
                parent="pipeline-governance")
    with pytest.raises(project.ProjectError, match="always top-level"):
        project.scaffold(root, **args)


def test_missing_parent_is_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    with pytest.raises(project.ProjectError, match="parent"):
        project.scaffold(root, **dict(BASE, parent="does-not-exist"))


def test_parent_is_recorded_when_valid(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Warehouse Pilot"))
    result = project.scaffold(root, **dict(BASE, parent="warehouse-pilot"))
    data, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert data["parent"] == "warehouse-pilot"


def test_grandchildren_are_refused(tmp_path):
    root = vault_with_entity(tmp_path)
    project.scaffold(root, **dict(BASE, name="Top Level"))
    project.scaffold(root, **dict(BASE, name="Middle", parent="top-level"))
    with pytest.raises(project.ProjectError, match="two levels"):
        project.scaffold(root, **dict(BASE, name="Bottom", parent="middle"))


def test_folder_name_equals_the_slug(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    data, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert (root / "30-projects" / data["slug"]).is_dir()


def test_nothing_is_written_when_validation_fails(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(project.ProjectError):
        project.scaffold(root, **BASE)
    assert list((root / "30-projects").iterdir()) == []


def test_index_uses_lf_endings(tmp_path):
    root = vault_with_entity(tmp_path)
    result = project.scaffold(root, **BASE)
    assert b"\r\n" not in (root / result["path"]).read_bytes()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_project.py -q`
Expected: FAIL — `ImportError: cannot import name 'project'`.

- [ ] **Step 3: Implement project.py**

Create `plugin/lib/vaultlib/project.py`:

```python
"""Project scaffolding: index.md plus an empty decisions/ folder.

Validation lives here rather than in the skill because these are exactly the
rules a model relaxes under pressure — a colliding slug, a third nesting
level, an area given a parent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import markdown, naming, schema, vault

PROJECTS_DIR = "30-projects"
ENTITIES_DIR = "40-entities"
PROJECT_QUOTE_KEYS = frozenset({"project-name", "next-milestone"})

_PLACEHOLDER = "_none yet_"


class ProjectError(Exception):
    """A project argument the caller must fix."""


def _load_project(root: Path, slug: str) -> Optional[dict]:
    index = root / PROJECTS_DIR / slug / "index.md"
    if not index.is_file():
        return None
    data, _ = markdown.split_frontmatter(index.read_text(encoding="utf-8"))
    return data


def _validate_inputs(root: Path, slug: str, project_type: str,
                     entity: str, parent: Optional[str]) -> None:
    allowed_types = schema.enum_values("project", "project-type")
    if project_type not in allowed_types:
        raise ProjectError(
            f"project-type {project_type!r} is not one of {allowed_types}"
        )

    existing = vault.list_dir_names(root / PROJECTS_DIR)
    clash = naming.find_collision(slug, existing)
    if clash is not None:
        raise ProjectError(
            f"a project folder already exists at {PROJECTS_DIR}/{clash} — "
            "pick a different name or work in the existing project"
        )

    if not (root / ENTITIES_DIR / entity / "dossier.md").is_file():
        raise ProjectError(
            f"no entity {entity!r} at {ENTITIES_DIR}/{entity}/dossier.md — "
            f"create it first with: entity ensure --slug {entity}"
        )

    if parent is None:
        return

    if project_type == "area-of-responsibility":
        raise ProjectError(
            "areas of responsibility are always top-level and cannot have a parent"
        )
    parent_data = _load_project(root, parent)
    if parent_data is None:
        raise ProjectError(
            f"parent project {parent!r} does not exist at "
            f"{PROJECTS_DIR}/{parent}/index.md"
        )
    if parent_data.get("parent") not in (None, ""):
        raise ProjectError(
            f"maximum two levels of nesting: {parent!r} already has a parent "
            f"({parent_data['parent']!r})"
        )


def _render_body(slug: str, name: str, today_display: str, stage: Optional[str],
                 contacts: Optional[str], source: Optional[str]) -> str:
    return f"""
# {name}

> [!summary]+ **Now** — as of {today_display}
> - **Stage** — {stage or "_newly created; awaiting first meeting or intake_"}
> - **Defining decision** — {_PLACEHOLDER}
> - **Next event** — _none scheduled_
> - **Owe** — {_PLACEHOLDER}
> - **Watch** — {_PLACEHOLDER}

> [!info]- **Context**
> - **Contacts** — {contacts or _PLACEHOLDER}
> - **Source** — {source or _PLACEHOLDER}

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "{PROJECTS_DIR}/{slug}/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — {_PLACEHOLDER}
- **Awaiting** — {_PLACEHOLDER}
- **Question** — {_PLACEHOLDER}
- **Pending** — {_PLACEHOLDER}

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date",
  slice(attendees, 0, 3) AS "Attendees",
  recording-duration AS "Min",
  calendar-subject AS "Subject"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
SORT date DESC
LIMIT 15
```
"""


def _display_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}-{month}-{year[2:]}"


def scaffold(root: Path, *, name: str, project_type: str, entity: str,
             owner: str, today: str, parent: Optional[str] = None,
             stage: Optional[str] = None, contacts: Optional[str] = None,
             source: Optional[str] = None) -> dict:
    """Create 30-projects/{slug}/index.md and its decisions/ folder."""
    slug = naming.slugify(name)
    naming.validate_slug(slug)
    _validate_inputs(root, slug, project_type, entity, parent)

    frontmatter = {
        "type": "project",
        "project-name": name,
        "slug": slug,
        "status": "active",
        "project-type": project_type,
        "entity": entity,
        "owner": owner,
        "parent": parent,
        "stakeholders": [],
        "created": today,
        "last-updated": today,
        "meetings-7d": 0,
        "meetings-30d": 0,
        "key-people": [],
        "next-milestone": None,
        "next-milestone-date": None,
    }
    problems = schema.validate("project", frontmatter)
    if problems:
        raise ProjectError(
            "refusing to write non-conformant project frontmatter: "
            + "; ".join(problems)
        )

    body = _render_body(slug, name, _display_date(today), stage, contacts, source)
    text = markdown.emit_frontmatter(frontmatter, PROJECT_QUOTE_KEYS) + body

    folder = root / PROJECTS_DIR / slug
    index = folder / "index.md"
    decisions = folder / "decisions"
    vault.atomic_write(index, text)
    decisions.mkdir(parents=True, exist_ok=True)

    return {
        "slug": slug,
        "path": index.relative_to(root).as_posix(),
        "decisions_dir": decisions.relative_to(root).as_posix(),
        "created": [
            index.relative_to(root).as_posix(),
            decisions.relative_to(root).as_posix() + "/",
        ],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_project.py -q`
Expected: PASS — 18 tests. If `test_body_carries_the_three_ontology_sections`
fails, `split_sections` is counting a `##` inside a Dataview fence — that is
the fence-awareness added in Task 3.

- [ ] **Step 5: Wire the subcommand into cli.py**

In `plugin/lib/vaultlib/cli.py`, widen the deferred import to:

```python
from vaultlib import person, project, schema, vault  # noqa: E402
```

Then add this parser block inside `build_parser()`, immediately before
`return parser`:

```python
    projects = top.add_parser("project", help="project folders")
    projects_sub = projects.add_subparsers(dest="action", required=True)
    scaffold = projects_sub.add_parser(
        "scaffold", help="create a project index and decisions folder")
    _add_vault_argument(scaffold)
    scaffold.add_argument("--name", required=True, help="human-readable project name")
    scaffold.add_argument("--type", dest="project_type", required=True,
                          choices=schema.enum_values("project", "project-type"))
    scaffold.add_argument("--entity", required=True, help="entity slug (join key)")
    scaffold.add_argument("--owner", required=True, help="owner person slug")
    scaffold.add_argument("--parent", help="parent project slug (initiatives only)")
    scaffold.add_argument("--today", help="ISO date; defaults to today")
    scaffold.add_argument("--stage", help="one line for the Now callout")
    scaffold.add_argument("--contacts", help="one line for the Context callout")
    scaffold.add_argument("--source", help="one line for the Context callout")
```

Add this branch to `_dispatch()` before the final `raise`:

```python
    if args.group == "project":
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(project.scaffold(
            root, name=args.name, project_type=args.project_type,
            entity=args.entity, owner=args.owner, today=today,
            parent=args.parent, stage=args.stage,
            contacts=args.contacts, source=args.source,
        ))
```

Add `ProjectError` to the handled exceptions in `main()`:

```python
    except project.ProjectError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
```

Place that `except` clause **before** `except ValueError`, since a future
`ProjectError` subclassing change must not be shadowed.

- [ ] **Step 6: Add the CLI-level tests**

Append to `scripts/tests/test_vaultlib_cli.py`:

```python
def test_project_scaffold_through_the_cli(capsys, tmp_path):
    from test_vaultlib_project import vault_with_entity
    root = vault_with_entity(tmp_path)
    code, payload = run(capsys, [
        "project", "scaffold", "--vault", str(root),
        "--name", "Yard Automation Program", "--type", "initiative",
        "--entity", "meridian-freight-holdings", "--owner", "morgan-ellery",
        "--today", "2026-08-23",
    ])
    assert code == 0
    assert payload["result"]["slug"] == "yard-automation-program"


def test_project_scaffold_rejects_a_retired_type_at_the_parser(tmp_path):
    from test_vaultlib_project import vault_with_entity
    root = vault_with_entity(tmp_path)
    with pytest.raises(SystemExit):
        cli.main([
            "project", "scaffold", "--vault", str(root), "--name", "X",
            "--type", "presales", "--entity", "meridian-freight-holdings",
            "--owner", "o",
        ])


def test_project_error_is_a_structured_failure(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, [
        "project", "scaffold", "--vault", str(root), "--name", "X",
        "--type", "initiative", "--entity", "missing-entity", "--owner", "o",
    ])
    assert code == 1
    assert "entity ensure" in payload["error"]
```

- [ ] **Step 7: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/project.py plugin/lib/vaultlib/cli.py \
        scripts/tests/test_vaultlib_project.py scripts/tests/test_vaultlib_cli.py
git commit -m "$(cat <<'EOF'
feat: add project scaffold to vaultlib

The guard rails live in the script, not the skill, because these are the
rules a model relaxes under pressure: a colliding folder, a third nesting
level, an area of responsibility handed a parent. A missing entity fails with
the command that fixes it rather than a bare refusal.

Frontmatter is validated against the compiled schema before anything is
written, so a non-conformant project cannot reach disk. The Related Meetings
query drops the upstream self-filter, which matched the executive by display
name — unshippable under the clean-room rule and wrong regardless, since
attendees are slugs.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Task 7: `entity ensure` / `read` / `write`

**Files:**
- Create: `plugin/lib/vaultlib/entity.py`
- Create: `scripts/tests/test_vaultlib_entity.py`
- Modify: `plugin/lib/vaultlib/cli.py` (add the `entity` group)

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces:
  - `entity.EntityError(Exception)`
  - `entity.ensure(root, *, slug, name, today, entity_type=None, status="prospect", owner=None) -> dict`
  - `entity.read(root, slug) -> dict` → `{"slug", "path", "frontmatter", "sections": {title: content}, "unvalidated": [title], "banner": bool}`
  - `entity.write(root, slug, edits: Mapping, today: str) -> dict` → `{"path", "changes": [str]}`
  - Edit payload keys, all optional, all lists:
    `context: [{label, fact, why}]` ·
    `stakeholders: [{name, title, role, stance, notes}]` ·
    `relationship_history: [{date, what, significance}]` ·
    `meeting_log: [{date, topic, attendees, outcomes, followups, dynamics}]` ·
    `sensitivities: [{topic, detail, implications}]` ·
    `engagements: [{project, status, one_liner}]`
- CLI: `entity ensure --vault P --slug S --name N [--type T] [--status S] [--owner O] [--today D]` ·
  `entity read --vault P --slug S` ·
  `entity write --vault P --slug S --edits FILE|-` (`-` reads stdin)

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_entity.py`:

```python
"""Dossier creation and merges.

The hard rule under test throughout: never remove existing content. Everything
else is section-specific placement.
"""
import pytest

from vaultlib import entity, markdown as md, schema

from test_vaultlib_vault import make_vault

TODAY = "2026-08-23"


def seeded(tmp_path, **kwargs):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="meridian-freight-holdings",
                  name="Meridian Freight Holdings", today=TODAY, **kwargs)
    return root


# --- ensure ---------------------------------------------------------------

def test_ensure_creates_a_conformant_dossier(tmp_path):
    root = seeded(tmp_path, entity_type="client", status="active")
    text = (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_text(
        encoding="utf-8")
    data, body = md.split_frontmatter(text)
    assert schema.validate("entity", data) == []
    assert data["slug"] == "meridian-freight-holdings"
    assert data["type"] == "entity"
    assert data["status"] == "active"
    assert [t for t, _ in md.split_sections(body) if t] == schema.body_sections("entity")


def test_ensure_slug_equals_the_folder_name(tmp_path):
    root = seeded(tmp_path)
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_text(
            encoding="utf-8"))
    assert data["slug"] == "meridian-freight-holdings"


def test_ensure_defaults_to_prospect(tmp_path):
    root = seeded(tmp_path)
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_text(
            encoding="utf-8"))
    assert data["status"] == "prospect"


def test_ensure_seeds_empty_sections_with_the_placeholder(tmp_path):
    root = seeded(tmp_path)
    sections = entity.read(root, "meridian-freight-holdings")["sections"]
    for title in ("Relationship History", "Meeting Log", "Sensitivities"):
        assert "*No entries yet.*" in sections[title]


def test_ensure_marks_generated_context_unvalidated(tmp_path):
    root = seeded(tmp_path)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert parsed["banner"] is True
    assert "Context" in parsed["unvalidated"]


def test_ensure_is_idempotent(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nhand edit\n",
                      encoding="utf-8")
    result = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-01")
    assert result["created"] is False
    assert "hand edit" in target.read_text(encoding="utf-8")


def test_ensure_rejects_an_off_enum_status(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(entity.EntityError, match="status"):
        entity.ensure(root, slug="x", name="X", today=TODAY, status="lapsed")


def test_ensure_rejects_a_malformed_slug(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="lowercase"):
        entity.ensure(root, slug="Bad Slug", name="X", today=TODAY)


# --- read -----------------------------------------------------------------

def test_read_raises_on_a_missing_dossier(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(entity.EntityError, match="no dossier"):
        entity.read(root, "nobody")


def test_read_returns_all_six_sections(tmp_path):
    root = seeded(tmp_path)
    assert list(entity.read(root, "meridian-freight-holdings")["sections"]) == \
        schema.body_sections("entity")


# --- write: context -------------------------------------------------------

def test_context_bullet_is_appended(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "regional freight, three yards",
         "why": "sets the yard-automation scope"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert "**Industry:** regional freight, three yards — sets the yard-automation scope" in text


def test_context_bullet_with_a_matching_label_is_replaced_not_duplicated(tmp_path):
    root = seeded(tmp_path)
    for fact in ("1,200 staff", "1,400 staff"):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": "Size", "fact": fact, "why": "scale"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert text.count("**Size:**") == 1
    assert "1,400 staff" in text
    assert "1,200 staff" not in text


def test_context_is_capped_at_eight_bullets(tmp_path):
    root = seeded(tmp_path)
    edits = {"context": [{"label": f"L{i}", "fact": f"f{i}", "why": "w"}
                         for i in range(12)]}
    entity.write(root, "meridian-freight-holdings", edits, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert len([line for line in text.splitlines() if line.startswith("- **")]) == 8


# --- write: stakeholders --------------------------------------------------

def test_new_stakeholder_row_is_flagged_for_review(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO", "role": "sponsor",
         "stance": "champion", "notes": "direct, wants numbers"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert "Leo Marchetti" in text
    assert "<!-- needs-review -->" in text


def test_existing_stakeholder_is_matched_case_insensitively(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "leo marchetti", "stance": "neutral"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert text.count("Marchetti") == 1
    assert "neutral" in text
    assert "COO" in text  # the earlier field survived


def test_blank_stakeholder_field_never_overwrites_a_filled_one(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": ""}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert "COO" in text


def test_stakeholder_rows_are_never_removed(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti"}, {"name": "Renee Castillo"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert "Renee Castillo" in text


def test_off_vocabulary_role_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="role"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            {"name": "X", "role": "kingmaker"}]}, TODAY)


def test_off_vocabulary_stance_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="stance"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            {"name": "X", "stance": "hostile"}]}, TODAY)


def test_a_pipe_in_a_field_cannot_break_the_table(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "says a | b"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    assert row.count("|") == 6  # 5 columns => 6 delimiters
    assert r"\|" in row


# --- write: relationship history & meeting log ---------------------------

def test_relationship_history_is_date_ordered(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-06-01", "what": "second", "significance": "b"},
        {"date": "2026-02-01", "what": "first", "significance": "a"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Relationship History"]
    assert text.index("first") < text.index("second")
    assert "*No entries yet.*" not in text


def test_meeting_log_prepends_newest_first(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "attendees": "Leo",
         "outcomes": "scope agreed", "followups": "send plan",
         "dynamics": "warm"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-05-20", "topic": "Vendor strategy", "attendees": "Leo, Renee",
         "outcomes": "consolidate", "followups": "draft memo", "dynamics": "tense"}]},
        TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert text.index("Vendor strategy") < text.index("SteerCo 01")
    assert "*No entries yet.*" not in text


def test_meeting_log_entries_are_never_modified(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "outcomes": "scope agreed"}]},
        TODAY)
    before = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "outcomes": "different"}]},
        TODAY)
    after = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert "scope agreed" in after
    assert before.strip() in after


# --- write: sensitivities & engagements ---------------------------------

def test_sensitivity_with_a_matching_topic_is_updated(tmp_path):
    root = seeded(tmp_path)
    for detail in ("old detail", "new detail"):
        entity.write(root, "meridian-freight-holdings", {"sensitivities": [
            {"topic": "Incumbent vendor", "detail": detail,
             "implications": "tread carefully"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Sensitivities"]
    assert text.count("**Incumbent vendor:**") == 1
    assert "new detail" in text


def test_engagement_row_links_to_the_project_index(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "meridian-yard-automation-program", "status": "Active",
         "one_liner": "Three-yard rollout"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    assert "../../30-projects/meridian-yard-automation-program/index.md" in text


def test_engagement_row_is_updated_not_duplicated(tmp_path):
    root = seeded(tmp_path)
    for status in ("Active", "Completed"):
        entity.write(root, "meridian-freight-holdings", {"engagements": [
            {"project": "meridian-yard-automation-program", "status": status,
             "one_liner": "Three-yard rollout"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    assert text.count("meridian-yard-automation-program") == 1
    assert "Completed" in text


# --- write: cross-cutting ------------------------------------------------

def test_writing_a_section_clears_its_unvalidated_marker(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight", "why": "scope"}]}, TODAY)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert "Context" not in parsed["unvalidated"]
    assert parsed["banner"] is False


def test_last_updated_is_bumped_without_reordering_frontmatter(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    before = target.read_text(encoding="utf-8").split("---")[1].splitlines()
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "T", "detail": "d", "implications": "i"}]}, "2026-09-01")
    after = target.read_text(encoding="utf-8").split("---")[1].splitlines()
    assert [line.split(":")[0] for line in before if line.strip()] == \
           [line.split(":")[0] for line in after if line.strip()]
    assert "last-updated: 2026-09-01" in target.read_text(encoding="utf-8")


def test_write_reports_what_changed(tmp_path):
    root = seeded(tmp_path)
    result = entity.write(root, "meridian-freight-holdings", {
        "context": [{"label": "Industry", "fact": "freight", "why": "scope"}],
        "stakeholders": [{"name": "Leo Marchetti"}],
    }, TODAY)
    joined = " ".join(result["changes"])
    assert "Context" in joined and "Stakeholders" in joined


def test_an_empty_edit_payload_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="no edits"):
        entity.write(root, "meridian-freight-holdings", {}, TODAY)


def test_an_unknown_edit_key_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="invented"):
        entity.write(root, "meridian-freight-holdings",
                     {"invented": [{"a": 1}]}, TODAY)


def test_write_uses_lf_endings(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "T", "detail": "d", "implications": "i"}]}, TODAY)
    raw = (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_bytes()
    assert b"\r\n" not in raw
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_entity.py -q`
Expected: FAIL — `ImportError: cannot import name 'entity'`.

- [ ] **Step 3: Implement entity.py**

Create `plugin/lib/vaultlib/entity.py`:

```python
"""Entity dossiers: creation and section merges.

One hard rule runs through every merge: never remove existing content. Add or
update only, and report contradictions to the caller rather than resolving
them silently.

Section shapes and merge rules are the contract in ontology.md §Entity. Two
skills write dossiers — /new-project creates a baseline, /update-entity
maintains one — so the rules live here rather than in either SKILL.md.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from . import markdown, naming, schema, vault

ENTITIES_DIR = "40-entities"
ENTITY_QUOTE_KEYS = frozenset({"entity-name", "industry"})

PLACEHOLDER = "*No entries yet.*"
UNVALIDATED = "<!-- unvalidated -->"
NEEDS_REVIEW = "<!-- needs-review -->"
BANNER = ("> [!unvalidated] Generated context — verify before relying on "
          "details.")

MAX_CONTEXT_BULLETS = 8
ROLE_VOCABULARY = ("sponsor", "champion", "evaluator", "influencer", "blocker")
STANCE_VOCABULARY = ("champion", "neutral", "blocker")

STAKEHOLDER_HEADER = (
    "| Name | Title | Role in Decision | Stance | Notes |\n"
    "|------|-------|------------------|--------|-------|"
)
ENGAGEMENT_HEADER = (
    "| Project | Status | One-liner |\n"
    "|---------|--------|-----------|"
)

_EDIT_KEYS = ("context", "stakeholders", "relationship_history",
              "meeting_log", "sensitivities", "engagements")
_SECTION_FOR_EDIT = {
    "context": "Context",
    "stakeholders": "Stakeholders",
    "relationship_history": "Relationship History",
    "meeting_log": "Meeting Log",
    "sensitivities": "Sensitivities",
    "engagements": "Engagements",
}


class EntityError(Exception):
    """An entity argument or dossier state the caller must fix."""


def _cell(value: Optional[str]) -> str:
    """Escape a value for a markdown table cell."""
    text = "" if value is None else str(value).strip()
    return text.replace("|", r"\|").replace("\n", " ")


def _dossier_path(root: Path, slug: str) -> Path:
    return root / ENTITIES_DIR / slug / "dossier.md"


# --- creation -------------------------------------------------------------

def _empty_body() -> str:
    parts = [""]
    for title in schema.body_sections("entity"):
        if title == "Context":
            parts.append(f"## Context\n{UNVALIDATED}\n\n{PLACEHOLDER}\n")
        elif title == "Stakeholders":
            parts.append(f"## Stakeholders\n\n{STAKEHOLDER_HEADER}\n")
        elif title == "Engagements":
            parts.append(f"## Engagements\n\n{ENGAGEMENT_HEADER}\n")
        else:
            parts.append(f"## {title}\n\n{PLACEHOLDER}\n")
    return "\n" + BANNER + "\n\n" + "\n".join(parts[1:])


def ensure(root: Path, *, slug: str, name: str, today: str,
           entity_type: Optional[str] = None, status: str = "prospect",
           owner: Optional[str] = None) -> dict:
    """Create 40-entities/{slug}/dossier.md if it does not exist."""
    naming.validate_slug(slug)
    path = _dossier_path(root, slug)
    if path.is_file():
        return {"slug": slug, "path": path.relative_to(root).as_posix(),
                "created": False}

    frontmatter = {
        "type": "entity",
        "entity-name": name,
        "slug": slug,
        "entity-type": entity_type,
        "status": status,
        "industry": None,
        "owner": owner,
        "created": today,
        "last-updated": today,
    }
    problems = schema.validate("entity", frontmatter)
    if problems:
        raise EntityError(
            "refusing to write non-conformant entity frontmatter: "
            + "; ".join(problems)
        )
    text = markdown.emit_frontmatter(frontmatter, ENTITY_QUOTE_KEYS) + _empty_body()
    vault.atomic_write(path, text)
    return {"slug": slug, "path": path.relative_to(root).as_posix(),
            "created": True}


# --- reading --------------------------------------------------------------

def read(root: Path, slug: str) -> dict:
    path = _dossier_path(root, slug)
    if not path.is_file():
        raise EntityError(
            f"no dossier at {ENTITIES_DIR}/{slug}/dossier.md — "
            f"create it first with: entity ensure --slug {slug} --name <name>"
        )
    text = path.read_text(encoding="utf-8")
    frontmatter, body = markdown.split_frontmatter(text)
    sections = dict(markdown.split_sections(body))
    preamble = sections.pop("", "")
    return {
        "slug": slug,
        "path": path.relative_to(root).as_posix(),
        "frontmatter": frontmatter,
        "sections": {title: sections.get(title, "")
                     for title in schema.body_sections("entity")},
        "unvalidated": [title for title, content in sections.items()
                        if UNVALIDATED in content],
        "banner": BANNER in preamble,
    }


# --- merge helpers --------------------------------------------------------

def _lines(content: str) -> List[str]:
    return [line for line in content.split("\n")]


def _strip_placeholder(lines: List[str]) -> List[str]:
    return [line for line in lines if line.strip() != PLACEHOLDER]


def _merge_labelled_bullets(content: str, items, label_key: str,
                            render, cap: Optional[int] = None) -> Tuple[str, int]:
    """Update a bullet whose bold label matches, else append. Returns
    (content, touched-count)."""
    lines = _strip_placeholder(_lines(content))
    touched = 0
    for item in items:
        label = str(item[label_key]).strip()
        rendered = render(item)
        marker = f"- **{label}:**"
        for index, line in enumerate(lines):
            if line.strip().startswith(marker):
                lines[index] = rendered
                break
        else:
            insert_at = len(lines)
            while insert_at > 0 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, rendered)
        touched += 1
    bullets = [line for line in lines if line.strip().startswith("- **")]
    if cap is not None and len(bullets) > cap:
        # Drop oldest bullets first: the newest carry the freshest facts.
        doomed = set(id(line) for line in bullets[: len(bullets) - cap])
        lines = [line for line in lines if id(line) not in doomed]
    return "\n".join(lines), touched


def _parse_table(content: str, columns: int) -> Tuple[List[str], List[List[str]]]:
    """Return (non-table lines before the table, data rows as cell lists)."""
    preamble, rows, seen_header = [], [], 0
    for line in _lines(content):
        stripped = line.strip()
        if stripped.startswith("|"):
            seen_header += 1
            if seen_header <= 2:
                continue  # header row and separator
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            cells += [""] * (columns - len(cells))
            rows.append(cells[:columns])
        elif seen_header == 0:
            preamble.append(line)
    return preamble, rows


def _render_table(preamble: List[str], header: str,
                  rows: List[List[str]]) -> str:
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    lead = "\n".join(_strip_placeholder(preamble)).rstrip("\n")
    chunk = header + ("\n" + body if body else "")
    return (lead + "\n\n" if lead.strip() else "\n") + chunk + "\n"


# --- per-section merges ---------------------------------------------------

def _merge_context(content: str, items) -> Tuple[str, int]:
    return _merge_labelled_bullets(
        content, items, "label",
        lambda item: f"- **{item['label']}:** {item['fact']} — {item['why']}",
        cap=MAX_CONTEXT_BULLETS,
    )


def _merge_sensitivities(content: str, items) -> Tuple[str, int]:
    return _merge_labelled_bullets(
        content, items, "topic",
        lambda item: f"- **{item['topic']}:** {item['detail']} — {item['implications']}",
    )


def _merge_stakeholders(content: str, items) -> Tuple[str, int]:
    preamble, rows = _parse_table(content, 5)
    touched = 0
    for item in items:
        role = (item.get("role") or "").strip()
        stance = (item.get("stance") or "").strip()
        if role and role not in ROLE_VOCABULARY:
            raise EntityError(
                f"role {role!r} is not one of {list(ROLE_VOCABULARY)}")
        if stance and stance not in STANCE_VOCABULARY:
            raise EntityError(
                f"stance {stance!r} is not one of {list(STANCE_VOCABULARY)}")
        incoming = [_cell(item.get("name")), _cell(item.get("title")),
                    _cell(role), _cell(stance), _cell(item.get("notes"))]
        name_key = incoming[0].lower()
        for row in rows:
            if row[0].lower() == name_key:
                # Only fill; never replace a filled cell with an empty one.
                for index in range(1, 5):
                    if incoming[index]:
                        row[index] = incoming[index]
                break
        else:
            if not incoming[4]:
                incoming[4] = NEEDS_REVIEW
            else:
                incoming[4] = f"{incoming[4]} {NEEDS_REVIEW}"
            rows.append(incoming)
        touched += 1
    return _render_table(preamble, STAKEHOLDER_HEADER, rows), touched


def _merge_engagements(content: str, items) -> Tuple[str, int]:
    preamble, rows = _parse_table(content, 3)
    touched = 0
    for item in items:
        slug = str(item["project"]).strip()
        link = f"[{slug}](../../30-projects/{slug}/index.md)"
        incoming = [link, _cell(item.get("status") or "Active"),
                    _cell(item.get("one_liner"))]
        for row in rows:
            if slug in row[0]:
                for index in (1, 2):
                    if incoming[index]:
                        row[index] = incoming[index]
                break
        else:
            rows.append(incoming)
        touched += 1
    return _render_table(preamble, ENGAGEMENT_HEADER, rows), touched


def _merge_relationship_history(content: str, items) -> Tuple[str, int]:
    lines = _strip_placeholder(_lines(content))
    entries = [line for line in lines if line.strip().startswith("- **")]
    for item in items:
        entries.append(
            f"- **{item['date']}:** {item['what']} — {item['significance']}")
    entries.sort(key=lambda line: line[4:14])
    return "\n" + "\n".join(entries) + "\n", len(items)


def _merge_meeting_log(content: str, items) -> Tuple[str, int]:
    existing = "\n".join(_strip_placeholder(_lines(content))).strip("\n")
    blocks = []
    for item in items:
        rows = [
            ("Attendees", item.get("attendees")),
            ("Key outcomes", item.get("outcomes")),
            ("Follow-ups", item.get("followups")),
            ("Dynamics", item.get("dynamics")),
        ]
        detail = "\n".join(f"- **{label}:** {value}"
                           for label, value in rows if value)
        blocks.append(f"### {item['date']} — {item['topic']}\n\n{detail}")
    fresh = "\n\n".join(blocks)
    combined = "\n\n".join(part for part in (fresh, existing) if part)
    return "\n" + combined + "\n", len(items)


_MERGERS = {
    "context": _merge_context,
    "stakeholders": _merge_stakeholders,
    "relationship_history": _merge_relationship_history,
    "meeting_log": _merge_meeting_log,
    "sensitivities": _merge_sensitivities,
    "engagements": _merge_engagements,
}


# --- writing --------------------------------------------------------------

def write(root: Path, slug: str, edits: Mapping, today: str) -> dict:
    """Apply section edits to an existing dossier."""
    unknown = [key for key in edits if key not in _EDIT_KEYS]
    if unknown:
        raise EntityError(
            f"unknown edit key(s) {unknown}; expected any of {list(_EDIT_KEYS)}")
    active = {key: list(edits[key]) for key in _EDIT_KEYS
              if edits.get(key)}
    if not active:
        raise EntityError(
            f"no edits supplied; expected at least one of {list(_EDIT_KEYS)}")

    path = _dossier_path(root, slug)
    parsed = read(root, slug)
    text = path.read_text(encoding="utf-8")
    _, body = markdown.split_frontmatter(text)
    sections = markdown.split_sections(body)

    changes: List[str] = []
    updated: List[Tuple[str, str]] = []
    for title, content in sections:
        edit_key = next((key for key, name in _SECTION_FOR_EDIT.items()
                         if name == title), None)
        if edit_key is None or edit_key not in active:
            updated.append((title, content))
            continue
        merged, touched = _MERGERS[edit_key](content, active[edit_key])
        # A human supplied this content, so the section is no longer
        # unvalidated.
        merged = "\n".join(line for line in merged.split("\n")
                           if line.strip() != UNVALIDATED)
        updated.append((title, merged))
        changes.append(f"{title}: {touched} entr{'y' if touched == 1 else 'ies'}")

    new_body = markdown.render_sections(updated)
    if UNVALIDATED not in new_body:
        new_body = new_body.replace(BANNER + "\n", "").replace(BANNER, "")
        if parsed["banner"]:
            changes.append("removed the unvalidated banner")

    head = text[: text.index("\n---", 4) + len("\n---") + 1]
    rewritten = markdown.replace_scalar_field(head + new_body,
                                              "last-updated", today)
    vault.atomic_write(path, rewritten)
    return {"path": path.relative_to(root).as_posix(), "changes": changes}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_entity.py -q`
Expected: PASS — 30 tests.

Two failures are likely on first run and both are real bugs, not test
problems: `test_context_is_capped_at_eight_bullets` if `_merge_labelled_bullets`
dedupes by identity where two bullets render identically (switch the cap to
slice by index instead of `id()`), and
`test_last_updated_is_bumped_without_reordering_frontmatter` if the `head`
slice in `write()` mis-locates the closing fence (assert on
`head.count("---") == 2` while debugging).

- [ ] **Step 5: Wire the subcommands into cli.py**

Widen the deferred import to include `entity`, then add to `build_parser()`
before `return parser`:

```python
    entities = top.add_parser("entity", help="entity dossiers")
    entities_sub = entities.add_subparsers(dest="action", required=True)

    ent_ensure = entities_sub.add_parser(
        "ensure", help="create a dossier if none exists")
    _add_vault_argument(ent_ensure)
    ent_ensure.add_argument("--slug", required=True)
    ent_ensure.add_argument("--name", required=True, help="display name")
    ent_ensure.add_argument("--type", dest="entity_type",
                            choices=schema.enum_values("entity", "entity-type"))
    ent_ensure.add_argument("--status", default="prospect",
                            choices=schema.enum_values("entity", "status"))
    ent_ensure.add_argument("--owner", help="owner person slug")
    ent_ensure.add_argument("--today", help="ISO date; defaults to today")

    ent_read = entities_sub.add_parser(
        "read", help="print the dossier's frontmatter and sections as JSON")
    _add_vault_argument(ent_read)
    ent_read.add_argument("--slug", required=True)

    ent_write = entities_sub.add_parser(
        "write", help="apply section edits from a JSON payload")
    _add_vault_argument(ent_write)
    ent_write.add_argument("--slug", required=True)
    ent_write.add_argument("--edits", required=True,
                           help="path to a JSON file, or - to read stdin")
    ent_write.add_argument("--today", help="ISO date; defaults to today")
```

Add to `_dispatch()` before the final `raise`:

```python
    if args.group == "entity":
        if args.action == "ensure":
            return _ok(entity.ensure(
                root, slug=args.slug, name=args.name,
                today=vault.today_iso(args.today),
                entity_type=args.entity_type, status=args.status,
                owner=args.owner,
            ))
        if args.action == "read":
            return _ok(entity.read(root, args.slug))
        payload = (json.load(sys.stdin) if args.edits == "-"
                   else json.loads(Path(args.edits).read_text(encoding="utf-8")))
        return _ok(entity.write(root, args.slug, payload,
                                vault.today_iso(args.today)))
```

Add to `main()`'s handlers, before `except ValueError`:

```python
    except entity.EntityError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except json.JSONDecodeError as exc:
        return _fail(f"edits payload is not valid JSON: {exc}",
                     "Pass a JSON object keyed by section, or - for stdin.")
```

- [ ] **Step 6: Add the CLI-level tests**

Append to `scripts/tests/test_vaultlib_cli.py`:

```python
def test_entity_write_reads_edits_from_stdin(capsys, tmp_path, monkeypatch):
    import io
    import json as _json
    from vaultlib import entity
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme-industries", name="Acme Industries",
                  today="2026-08-23")
    payload = {"sensitivities": [
        {"topic": "Incumbent", "detail": "d", "implications": "i"}]}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-", "--today", "2026-08-24",
    ])
    assert code == 0
    assert any("Sensitivities" in change for change in out["result"]["changes"])


def test_malformed_edits_payload_is_a_structured_error(capsys, tmp_path, monkeypatch):
    import io
    from vaultlib import entity
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme-industries", name="Acme Industries",
                  today="2026-08-23")
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code, out = run(capsys, [
        "entity", "write", "--vault", str(root), "--slug", "acme-industries",
        "--edits", "-",
    ])
    assert code == 1
    assert "not valid JSON" in out["error"]
```

- [ ] **Step 7: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/entity.py plugin/lib/vaultlib/cli.py \
        scripts/tests/test_vaultlib_entity.py scripts/tests/test_vaultlib_cli.py
git commit -m "$(cat <<'EOF'
feat: add entity dossier creation and section merges to vaultlib

Markdown table merging is exactly the deterministic work a script should own,
so the six section rules from ontology §Entity live here rather than in either
skill that writes a dossier. Section routing — deciding which section a
sentence belongs to — stays with the model.

The hard rule is enforced rather than documented: rows and entries are never
removed, a blank incoming field never overwrites a filled one, and meeting-log
entries are append-only. Pipes in free text are escaped so a stakeholder's
quoted aside cannot break the table. last-updated is bumped through a targeted
field replacement, so hand-authored key order and quoting survive.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Task 8: `/new-project` skill and the plugin's internal instructions

**Files:**
- Create: `plugin/CLAUDE.md`
- Create: `plugin/skills/new-project/SKILL.md`
- Create: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: the CLI surface from Tasks 5–7.
- Produces: the `${VAULTLIB}` invocation convention every later skill reuses.

- [ ] **Step 1: Write the failing skill-contract tests**

These guard the things a prose file gets wrong silently. Create
`scripts/tests/test_skill_contracts.py`:

```python
"""Structural checks on SKILL.md files.

lint_plugin.py already covers frontmatter and the clean-room denylist. These
cover the contract between a skill and the CLI it calls: a skill that
references a subcommand that does not exist fails at the worst possible
moment, in front of a client.
"""
import re
from pathlib import Path

import pytest

from vaultlib import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "plugin" / "skills"

SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))
INVOCATION_RE = re.compile(r'cli\.py"?\s+([a-z-]+)\s+([a-z-]+)')


def known_subcommands() -> set:
    """(group, action) pairs the CLI actually implements."""
    parser = cli.build_parser()
    pairs = set()
    for action in parser._subparsers._group_actions[0].choices.items():
        group, sub = action
        nested = sub._subparsers
        if nested is None:
            continue
        for name in nested._group_actions[0].choices:
            pairs.add((group, name))
    return pairs


def test_at_least_the_two_expected_skills_exist():
    names = {path.parent.name for path in SKILL_FILES}
    assert {"new-project", "update-entity"} <= names


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_records_provenance(path):
    head = path.read_text(encoding="utf-8").split("---")[1]
    assert "upstreamed-from: busdev@" in head, (
        f"{path.parent.name}: ported skills record upstreamed-from in frontmatter"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_states_its_surface_requirement(path):
    text = path.read_text(encoding="utf-8")
    assert "Cowork" in text and "Claude Code" in text, (
        f"{path.parent.name}: must state that writes need Cowork or Claude Code — "
        "plugins do not load in Chat, so the skill has to say so rather than fail"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_cli_invocation_named_by_a_skill_exists(path):
    implemented = known_subcommands()
    text = path.read_text(encoding="utf-8")
    referenced = set(INVOCATION_RE.findall(text))
    assert referenced, f"{path.parent.name}: no CLI invocation found"
    unknown = referenced - implemented
    assert not unknown, (
        f"{path.parent.name} references subcommands the CLI does not implement: "
        f"{sorted(unknown)}"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_does_not_instruct_hand_written_frontmatter(path):
    text = path.read_text(encoding="utf-8").lower()
    for phrase in ("write the frontmatter", "emit the following frontmatter",
                   "create the file with this frontmatter"):
        assert phrase not in text, (
            f"{path.parent.name}: writes go through the CLI, never model-authored "
            "frontmatter — that is the whole point of the deterministic layer"
        )


def test_plugin_claude_md_documents_interpreter_resolution():
    text = (REPO_ROOT / "plugin" / "CLAUDE.md").read_text(encoding="utf-8")
    for token in ("python3", "python", "py -3"):
        assert token in text, (
            "plugin/CLAUDE.md must document the interpreter fallback chain: "
            "a clean Mac has no real python3 and Windows python3 is often a "
            "Store alias stub"
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: FAIL — `test_at_least_the_two_expected_skills_exist` fails on the
empty skills directory, and the parametrized tests collect nothing.

- [ ] **Step 3: Write plugin/CLAUDE.md**

Create `plugin/CLAUDE.md`:

````markdown
# Plugin internals

Instructions for working *on* this plugin. Not shipped guidance for the
executive — that lives in the vault's own `CLAUDE.md`. Excluded from the
version-bump requirement (see the repo's root `CLAUDE.md`).

## Where writes happen

Skills do not author object frontmatter. Every write goes through the
deterministic CLI:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" <group> <action> --vault "$VAULT" ...
```

Each run prints exactly one JSON object and signals through its exit code:

```json
{"ok": true,  "result": {...}}
{"ok": false, "error": "...", "hint": "..."}
```

Read `ok` before anything else. On failure, the `error` names the constraint
and `hint` says what to do — surface both to the user rather than retrying
blind or working around the CLI by writing files directly.

## Interpreter resolution

Never hardcode one interpreter name. Try in order, using the first that
works:

1. `python3` — correct on the Cowork Linux VM and on a developer Mac
2. `python` — the usual name on Windows
3. `py -3` — the Python Launcher, the most reliable invocation on Windows

Why this matters: a clean Mac has no real `python3` (the stub triggers an
Xcode Command Line Tools prompt), and on Windows `python3` frequently
resolves to a Microsoft Store alias that opens the Store instead of running.

## Runtime constraints for `lib/`

- **Stdlib only.** PyYAML's presence in the Cowork VM is unverified. The
  ontology is compiled to `lib/vaultlib/schema.json` by
  `scripts/compile_ontology.py` precisely so nothing parses YAML at runtime.
- **Python 3.10 is the syntax floor.** Cowork ships 3.10; repo CI runs 3.13.
  A 3.11+ construct fails only on the client machine, which is the worst
  place to discover it.
- **The vault root is always a parameter.** Under Cowork it is a VirtioFS
  mount point, not `/Users/...` or `C:\...`.
- **Writes are UTF-8 with `newline="\n"`.** A write from a Windows host must
  not inject CRLF into markdown that syncs to a Mac.

## Surfaces

| Surface | Skills load | Shell | Object writes |
|---|---|---|---|
| Chat + filesystem or Obsidian MCP | no | none | not supported |
| Cowork | yes | Linux VM | yes |
| Claude Code CLI | yes | host OS | yes |

Plugins are not used in Chat, so a skill cannot run there at all. Every
object-writing skill states this in its own body so the user gets an
explanation rather than a silent absence.

## After changing the ontology

```bash
python3 scripts/compile_ontology.py
python3 -m pytest scripts/tests -q
```

The regeneration test fails if `schema.json` is stale. That is the only thing
keeping the runtime contract and the ontology doc in agreement.
````

- [ ] **Step 4: Write the /new-project skill**

Create `plugin/skills/new-project/SKILL.md`:

````markdown
---
name: new-project
description: Create a project or area of responsibility with a structured index, and link it into its entity's dossier. Triggers when the user invokes /new-project or asks to start a new project, initiative, engagement, opportunity, or area of responsibility.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# New Project

Create `30-projects/{slug}/` with a queryable `index.md` and an empty
`decisions/` log, then link the project into its entity's dossier.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there. If you
find yourself without a shell, say so plainly and point the user at Cowork
rather than hand-writing the files.

Set `VAULT` to the vault root and `VAULTLIB` once at the start:

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Interpreter resolution and the JSON envelope are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure show the `error` and `hint`
instead of retrying blind.

## Usage

```
/new-project
/new-project "Yard Automation Program"
/new-project "Pipeline Governance" --type area-of-responsibility
```

## Workflow

### 1. Gather what you need

Ask only for what is missing, one question at a time.

- **Name** — the human-readable project name. Keep the entity out of it: the
  `entity` field already carries that, and the Projects base shows it as its
  own column. "Yard Automation Program", not "Meridian — Yard Automation".
- **Type** — `initiative` (timeboxed work with an end) or
  `area-of-responsibility` (standing, no end date). Default to `initiative`
  without asking when the name plainly describes bounded work.
- **Entity** — which organisation this belongs to. List what exists:

  ```bash
  ls "$VAULT/40-entities"
  ```

  If the right entity is not there, create it first:

  ```bash
  python3 "$VAULTLIB" entity ensure --vault "$VAULT" \
    --slug <slug> --name "<Display Name>" --type client --status prospect
  ```

  Ask which `--type` and `--status` fit rather than guessing: `prospect` for
  something being pursued, `active` for a live relationship.
- **Parent** — only for initiatives, and only if the user implies one.
  Maximum two levels; areas of responsibility are always top-level. The CLI
  enforces both.

### 2. Offer to gather context

Ask once, for every project:

> Anything to seed this with? Paste an email or notes, point me at a file, or
> just describe it — or skip and we'll create it bare.

Accept any of three forms:

- **Pasted text** — read it directly.
- **A file** — read it. Inbox captures live in `10-inbox/`; a path anywhere
  in the vault is fine.
- **A spoken description** — treat it as the same material.

From whatever you get, extract only what is actually there. Do not invent:

| Extract | Into |
|---|---|
| One line on where this stands right now | `--stage` |
| Named people and their roles | `--contacts` |
| How this arrived — referral, inbound mail, a meeting | `--source` |
| Deadlines or urgency signals | mention in your summary; the index has no field for it yet |

If the user skips, omit the flags — the index falls back to placeholders.

### 3. Resolve the owner

The owner is a person slug, and it must resolve to a real person note.
Default to the executive.

```bash
python3 "$VAULTLIB" identity show --vault "$VAULT"
```

Read the executive's name out of the returned `identity` text — that judgment
is yours, the CLI only extracts the block. Then make sure the note exists:

```bash
python3 "$VAULTLIB" person ensure --vault "$VAULT" --name "<Full Name>"
```

Use the returned `slug` as `--owner`. If `identity` comes back `null` the
portfolio is unfilled: ask who owns this project, and offer that
`/setup-my-brain` fills the portfolio properly.

If the user names a different owner, `person ensure` them instead — the same
call handles both cases and never touches an existing note.

### 4. Scaffold

```bash
python3 "$VAULTLIB" project scaffold --vault "$VAULT" \
  --name "Yard Automation Program" \
  --type initiative \
  --entity meridian-freight-holdings \
  --owner morgan-ellery \
  --stage "Vendor shortlist agreed; contract drafting" \
  --contacts "Leo Marchetti (COO), Renee Castillo (IT Director)" \
  --source "Forwarded renewal email, 2026-08-21"
```

The CLI derives the slug, refuses collisions, checks the entity exists,
validates the frontmatter against the ontology, writes `index.md`, and creates
`decisions/`. If it refuses, relay the reason — several of its errors name the
exact command that fixes them.

### 5. Link it into the dossier

Add the project to its entity's `Engagements` table. Write the edits to a file
and pass it, so quoting cannot mangle the payload:

```bash
cat > /tmp/engagement.json <<'JSON'
{"engagements": [{"project": "yard-automation-program",
                  "status": "Active",
                  "one_liner": "Three-yard automation rollout"}]}
JSON
python3 "$VAULTLIB" entity write --vault "$VAULT" \
  --slug meridian-freight-holdings --edits /tmp/engagement.json
```

The one-liner is one sentence, drawn from the context you gathered.

**This step is non-blocking.** If it fails, the project still exists — say
"dossier link skipped" in your summary and move on. Never unwind the project
because the dossier update failed.

### 6. Summarise

Report, briefly:

- name, slug, type, entity, owner
- the path to `index.md`
- what you extracted from the supplied context, and what you could not find
- whether the dossier link succeeded
- one suggested next step — usually recording the first decision, or feeding a
  transcript in

## Rules

1. **Never hand-write the files.** Every write goes through the CLI. It
   validates against the ontology; you do not.
2. **One folder per project.** `index.md` is the queryable object; artifacts
   sit beside it.
3. **Do not invent context.** A placeholder is better than a plausible
   fabrication — this vault is read as a record.
4. **Do not put the entity name in the project name.** It is already a field
   and a column.
5. **Dossier failures never fail the project.**
````

- [ ] **Step 5: Run the contract tests**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS. `test_every_cli_invocation_named_by_a_skill_exists` is the one
worth watching — it parses `cli.py <group> <action>` out of the prose and
checks each pair against the live parser.

- [ ] **Step 6: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass. `lint_plugin.py` is doing real work for the first time
here — it checks `name` matches the directory, `user_invocable: true` is
present, and that the only `busdev` occurrence is the exempted
`upstreamed-from:` span.

- [ ] **Step 7: Commit**

```bash
git add plugin/CLAUDE.md plugin/skills/new-project/SKILL.md \
        scripts/tests/test_skill_contracts.py
git commit -m "$(cat <<'EOF'
feat: add the /new-project skill and the plugin's internal instructions

Collapses the upstream new-opportunity and new-project skills into one.
Context gathering is offered on every project rather than gated on a type,
which is both simpler and closer to how the work actually arrives — an email,
a document, or a sentence.

The skill orchestrates and judges; it never authors frontmatter. Contract
tests parse the CLI invocations out of the prose and check each one against
the live parser, so a skill referencing a subcommand that does not exist fails
in CI rather than in front of a client.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `/update-entity` skill

**Files:**
- Create: `plugin/skills/update-entity/SKILL.md`

**Interfaces:**
- Consumes: `entity read` / `entity ensure` / `entity write` (Task 7); the
  `${VAULTLIB}` convention and `plugin/CLAUDE.md` (Task 8).
- Produces: nothing further consumed.

- [ ] **Step 1: Write the skill**

Create `plugin/skills/update-entity/SKILL.md`:

````markdown
---
name: update-entity
description: Record relationship context about an organisation — people, meetings, company facts, sensitivities, engagements — into its dossier. Triggers when the user invokes /update-entity or asks to update, capture, or record context on a client, partner, supplier, or business unit.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Update Entity

Route free-form notes into the right sections of an entity's dossier. You
decide what belongs where; the CLI does the merging.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there. Say so
plainly rather than hand-editing the dossier.

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are in the plugin's `CLAUDE.md`.

## Usage

```
/update-entity
/update-entity meridian-freight-holdings
```

## Workflow

### 1. Identify the entity

If no slug was given, list what exists and ask:

```bash
ls "$VAULT/40-entities"
```

If it does not exist yet, create it before routing anything:

```bash
python3 "$VAULTLIB" entity ensure --vault "$VAULT" \
  --slug <slug> --name "<Display Name>" --type client --status prospect
```

Ask which `entity-type` and `status` fit rather than guessing.

### 2. Read the current dossier

```bash
python3 "$VAULTLIB" entity read --vault "$VAULT" --slug <slug>
```

You get the frontmatter, all six sections, which sections are still marked
unvalidated, and whether the banner is present. **Read this before routing** —
knowing what is already recorded is what lets you update rather than duplicate,
and lets you notice a contradiction.

### 3. Get the input

If the user has not already provided it:

> What do you want to record about {Display Name}? Paste meeting notes,
> observations, an email, or point me at a file.

### 4. Route it

Decide which section each piece belongs to. A single paragraph about a meeting
routinely produces three entries: the meeting itself, a new person, and a
political dynamic worth remembering.

| What you are looking at | Section |
|---|---|
| Company facts — industry, size, systems, strategy, recent news | `context` |
| People — names, titles, who decides, where they stand | `stakeholders` |
| A meeting — who was there, what came out of it, what is owed | `meeting_log` |
| Political dynamics, sore points, topics to avoid, competitor ties | `sensitivities` |
| Milestones in the relationship — trust earned or lost, turning points | `relationship_history` |
| Projects and their status | `engagements` |

Judgment calls worth getting right:

- **A meeting that revealed a dynamic** goes in *both* `meeting_log` and
  `sensitivities`. Do not make the user choose.
- **`relationship_history` is for turning points**, not every interaction. If
  it would read as noise in a year, it belongs in `meeting_log` only.
- **`context` is capped at eight bullets** and the CLI enforces it. Prefer
  updating an existing label to adding a ninth.
- **Vocabularies are closed.** Role in decision: sponsor · champion ·
  evaluator · influencer · blocker. Stance: champion · neutral · blocker. The
  CLI refuses anything else, so pick the nearest rather than inventing.

### 5. Write it

Build the payload as a file — never inline, where quoting mangles apostrophes
and em dashes:

```bash
cat > /tmp/entity-edits.json <<'JSON'
{
  "context": [
    {"label": "Fleet", "fact": "three yards, 240 trailers",
     "why": "sets the automation scope"}
  ],
  "stakeholders": [
    {"name": "Leo Marchetti", "title": "COO", "role": "sponsor",
     "stance": "champion", "notes": "wants numbers, not narrative"}
  ],
  "meeting_log": [
    {"date": "2026-08-21", "topic": "Renewal planning",
     "attendees": "Leo Marchetti, Renee Castillo",
     "outcomes": "Renewal in principle; scope revisit in September",
     "followups": "Send revised scope by 2026-09-05",
     "dynamics": "Warm; Renee quieter than usual on integration"}
  ],
  "sensitivities": [
    {"topic": "Incumbent integrator", "detail": "long relationship with the yard-1 vendor",
     "implications": "frame consolidation as additive, not a replacement"}
  ]
}
JSON
python3 "$VAULTLIB" entity write --vault "$VAULT" \
  --slug meridian-freight-holdings --edits /tmp/entity-edits.json
```

Every key is optional; send only the sections you have something for. Dates
are ISO `YYYY-MM-DD`.

### 6. Summarise

Report what changed, section by section, from the CLI's `changes` list. Then
two things the list cannot tell you:

- **Contradictions, explicitly.** "Updated Leo Marchetti's title: COO →
  Group COO" — never silently overwrite a fact the user may care about.
- **What you deliberately did not record**, if you dropped something as too
  thin or too speculative to be worth a permanent entry.

## Rules

1. **Never remove existing content.** The CLI enforces this, and you should
   not try to work around it. Dossiers are cumulative.
2. **Never hand-edit the dossier.** Every change goes through
   `entity write`.
3. **Read before you write.** Routing without reading produces duplicates.
4. **New stakeholders are flagged `needs-review` automatically.** Leave the
   marker for a human to clear; do not remove it on the user's behalf.
5. **Do not infer facts.** "Probably reports to the CFO" is not a fact. If it
   matters, ask.
6. **Do not touch `status` or `entity-type`** unless the user asks. Those are
   relationship-level judgments.
````

- [ ] **Step 2: Run the contract tests**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS — the parametrized tests now cover two skills.

- [ ] **Step 3: Verify both skills against a real vault**

```bash
rm -rf /tmp/skill-check
python3 scripts/make_test_vault.py /tmp/skill-check
python3 plugin/lib/vaultlib/cli.py entity read \
  --vault /tmp/skill-check --slug meridian-freight-holdings
```

Expected: `"ok": true` with the fixture dossier's sections. Note that the
fixture dossiers do **not** yet carry the six-section body — that lands in
Task 11 — so `sections` will show empty strings for most titles. That is
expected here and is exactly what Task 11 fixes.

- [ ] **Step 4: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/update-entity/SKILL.md
git commit -m "$(cat <<'EOF'
feat: add the /update-entity skill

Renamed from the upstream update-dossier: the skill maintains an entity's
context, and "dossier" is the artifact rather than the act. The file stays
dossier.md, which is an established vault noun that Entities.base filters on.

Routing stays with the model and merging stays with the CLI, which is the
division that makes the never-remove-content rule enforceable rather than
merely stated. The skill is told to read before routing, because routing
blind is what produces duplicate stakeholders, and to surface contradictions
explicitly rather than overwriting a fact the user may care about.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Task 10: marketplace manifest and version bump

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `scripts/tests/test_marketplace_manifest.py`
- Modify: `plugin/.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable marketplace. `--plugin-dir` is a Claude Code flag,
  so without this manifest there is no way to hand-test in Cowork at all.

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_marketplace_manifest.py`:

```python
"""The repo must be installable as a plugin marketplace.

Without a root .claude-plugin/marketplace.json neither Cowork nor Claude Code
can add this repo, and --plugin-dir does not exist in Cowork — so this file is
the only path to hand-testing the skills where they are meant to run.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_JSON = REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json"

# Anthropic's documented constraint on marketplace names.
NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
RESERVED_NAMES = {"unknown", "org", "org-provisioned"}


def load():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_exists_at_the_repo_root():
    assert MANIFEST.is_file(), (
        "missing .claude-plugin/marketplace.json — the repo is not installable "
        "as a marketplace without it"
    )


def test_name_satisfies_the_documented_pattern():
    name = load()["name"]
    assert NAME_RE.match(name), f"marketplace name {name!r} is not accepted"
    assert name not in RESERVED_NAMES


def test_owner_is_declared():
    assert load()["owner"]["name"]


def test_exactly_one_plugin_is_listed():
    assert len(load()["plugins"]) == 1


def test_plugin_source_is_a_relative_path_in_this_repo():
    source = load()["plugins"][0]["source"]
    assert isinstance(source, str) and source.startswith("./"), (
        "source must be a relative path — a plugin pointing at another "
        "repository is listed but never fetched or auto-installed"
    )
    assert (REPO_ROOT / source).is_dir()


def test_listed_plugin_name_matches_the_plugin_manifest():
    assert load()["plugins"][0]["name"] == json.loads(
        PLUGIN_JSON.read_text(encoding="utf-8"))["name"]


def test_the_referenced_plugin_carries_its_own_manifest():
    source = load()["plugins"][0]["source"]
    assert (REPO_ROOT / source / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_version_is_bumped_for_this_release():
    assert json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"] == "0.1.0"


def test_manifest_does_not_force_installation():
    # This is the internal/dev marketplace. Client-facing install preferences
    # belong to sb-dist and the client's own admin configuration (issue #10).
    assert "installationPreference" not in load()["plugins"][0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest scripts/tests/test_marketplace_manifest.py -q`
Expected: FAIL — the manifest is absent and the version is still `0.0.1`.

- [ ] **Step 3: Create the marketplace manifest**

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "sb-accelerator-dev",
  "owner": {
    "name": "delaware"
  },
  "plugins": [
    {
      "name": "second-brain",
      "source": "./plugin",
      "description": "Second Brain Accelerator — a personal AI operating system for client executives. Internal development marketplace; client deployments install from the released distribution repo."
    }
  ]
}
```

The `-dev` suffix is deliberate. An admin-configured marketplace replaces a
user-added one sharing its `name`, so the internal marketplace must not
collide with the client-facing one.

- [ ] **Step 4: Bump the plugin version**

In `plugin/.claude-plugin/plugin.json`, change `"version": "0.0.1"` to
`"version": "0.1.0"`. Minor rather than patch: this PR ships the first real
skills.

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest scripts/tests/test_marketplace_manifest.py -q`
Expected: PASS — 9 tests.

- [ ] **Step 6: Verify the marketplace resolves in Claude Code**

```bash
python3 -c "
import json, pathlib
m = json.loads(pathlib.Path('.claude-plugin/marketplace.json').read_text())
p = pathlib.Path(m['plugins'][0]['source'])
print('plugin dir:', p, p.is_dir())
print('manifest:  ', (p / '.claude-plugin' / 'plugin.json').is_file())
print('skills:    ', sorted(q.name for q in (p / 'skills').iterdir() if q.is_dir()))
"
```

Expected: the plugin directory resolves, its manifest exists, and both
`new-project` and `update-entity` are listed. Hand-verification in Cowork
happens in Task 11's final step, since it needs the enriched fixtures to be
worth looking at.

- [ ] **Step 7: Run the full suite and the other two checks**

```bash
python3 -m pytest scripts/tests -q
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
```

Expected: all pass. Note that `scripts/check-plugin-version.sh` runs only in
CI against the PR base, so a local pass here does not prove the version guard
is satisfied — the PR will confirm it.

- [ ] **Step 8: Commit**

```bash
git add .claude-plugin/marketplace.json plugin/.claude-plugin/plugin.json \
        scripts/tests/test_marketplace_manifest.py
git commit -m "$(cat <<'EOF'
feat: make the repo installable as a plugin marketplace, bump to 0.1.0

Without a root marketplace manifest the repo cannot be added as a marketplace
by anything, and --plugin-dir is a Claude Code flag — so this file is the only
route to hand-testing skills in Cowork, which is where they are designed to
run. Named with a -dev suffix because an admin-configured marketplace replaces
a user-added one sharing its name, and the client-facing marketplace lives in
the distribution repo (issue #10).

Tests assert the documented constraints rather than restating the file: the
name pattern, and that source is a relative path in this repo — a plugin
pointing at another repository is listed in the UI but never fetched.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: fixture enrichment, `Decisions.base` hardening, CI jobs, docs

**Files:**
- Modify: `template/30-projects/Decisions.base`
- Modify: `scripts/tests/test_fixtures_ontology.py`
- Create: `fixtures/demo-vault/50-people/morgan-ellery.md`
- Modify: all 5 of `fixtures/demo-vault/30-projects/*/index.md`
- Modify: all 3 of `fixtures/demo-vault/40-entities/*/dossier.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/local-setup.md`

**Interfaces:**
- Consumes: `schema.body_sections` (Task 4), the CLI (Tasks 5–7).
- Produces: nothing further consumed.

- [ ] **Step 1: Harden Decisions.base**

In `template/30-projects/Decisions.base`, change the filter block from:

```yaml
filters:
  and:
    - type == "decision"
```

to:

```yaml
filters:
  and:
    - file.inFolder("30-projects")
    - type == "decision"
```

Meetings.base and Projects.base both scope by folder; Decisions.base did not,
so any decision-typed file anywhere in the vault landed in the client's
decision table.

- [ ] **Step 2: Write the failing body-conformance tests**

In `scripts/tests/test_fixtures_ontology.py`, extend `build_schemas()` to
carry the new key. Change the loop body from:

```python
        if block.get("keys_present"):
            schema["keys_present"] = list(block["keys_present"])
```

to:

```python
        if block.get("keys_present"):
            schema["keys_present"] = list(block["keys_present"])
        if block.get("body_sections"):
            schema["body_sections"] = list(block["body_sections"])
```

Then append these tests to the file:

```python
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py -q`
Expected: FAIL — `test_body_sections_present_in_every_fixture` fails for both
object types (fixtures still carry `## Overview` and friends), and
`test_exec_person_note_exists_and_is_referenced_as_an_owner` may pass already
since current owners are direct reports.

- [ ] **Step 4: Create the executive's person note**

Create `fixtures/demo-vault/50-people/morgan-ellery.md`:

```markdown
---
person-name: "Morgan Ellery"
slug: morgan-ellery
email: morgan.ellery@cascadia-intermodal.example
relationship: colleague
company: "Cascadia Intermodal Group"
role: "Chief Commercial Officer"
projects: [commercial-ops-crm-modernization, commercial-ops-pipeline-governance]
created: 2025-09-15
last-updated: 2026-06-12
meetings-7d: 0
meetings-30d: 4
---
```

Then change `owner:` to `morgan-ellery` on the two commercial-operations
projects — `commercial-ops-crm-modernization/index.md` and
`commercial-ops-pipeline-governance/index.md` — since those are the
executive's own initiative and standing area. Leave the three client-facing
projects owned by their account leads.

- [ ] **Step 5: Rewrite the five project index bodies**

Replace each body (everything after the closing `---`) with the shape
`/new-project` produces — the two callouts, then exactly the three H2
sections — filled with content true to that project. Keep every existing
frontmatter field; only bodies change.

Worked example for `meridian-yard-automation-program/index.md`:

````markdown

# Meridian Freight — Yard Automation Program

> [!summary]+ **Now** — as of 01-06-26
> - **Stage** — Yard 1 commissioned; yards 2–3 re-scoping onto the single-vendor platform.
> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted]]
> - **Next event** — Vendor contract signature, target 2026-09-01
> - **Owe** — Revised commissioning schedule to Leo Marchetti
> - **Watch** — Six-week slip versus the original phased plan

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO, sponsor), Renee Castillo (IT Director)
> - **Source** — Follow-on from the Phase 0 warehouse pilot

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date",
  status AS "Status",
  summary AS "Decision"
FROM "30-projects/meridian-yard-automation-program/decisions"
SORT status ASC, date DESC
LIMIT 20
```

## Open Items

- **Owe** — Revised commissioning schedule (Renee Castillo, by 2026-06-15)
- **Awaiting** — Vendor's consolidated integration estimate
- **Question** — Whether yard 3's PLC refresh lands in this scope or the next
- **Pending** — Contract signature

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date",
  slice(attendees, 0, 3) AS "Attendees",
  recording-duration AS "Min",
  calendar-subject AS "Subject"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
SORT date DESC
LIMIT 15
```
````

Apply the same structure to the other four, substituting each project's own
slug in the Decisions `FROM` clause and writing content that matches its real
state:

| Project | Notes for its content |
|---|---|
| `nordbridge-regional-rollout-proposal` | A pursuit: proposal in drafting, one withdrawn decision, Dana Whitfield as the contact. |
| `meridian-warehouse-pilot-phase-0` | `status: completed` — the Now callout should read as closed, with Open Items showing none. |
| `commercial-ops-crm-modernization` | Internal initiative owned by the executive; one approved vendor shortlist decision. |
| `commercial-ops-pipeline-governance` | The standing area: no end date, so no milestone; Open Items are recurring obligations. |

Do not carry over the old `## Overview` or `## Deliverables` headings — the
conformance test requires the H2 list to equal `body_sections` exactly.

- [ ] **Step 6: Rewrite the three dossier bodies**

Replace each body with the six sections in ontology order, filled with real
content. Worked example for `meridian-freight-holdings/dossier.md`:

````markdown

## Context

- **Industry:** regional freight and intermodal logistics — the yard-automation offering lands directly in their core operation.
- **Scale:** three yards, roughly 240 trailers — large enough to justify automation, small enough to decide quickly.
- **Systems:** mixed PLC estate across yards, one vendor per site historically — the integration overhead that drove consolidation.
- **Relationship age:** client since the Phase 0 pilot in 2025 — past the trust-building stage.

## Stakeholders

| Name | Title | Role in Decision | Stance | Notes |
|------|-------|------------------|--------|-------|
| [[leo-marchetti]] | Chief Operating Officer | sponsor | champion | Wants numbers, not narrative. Decides fast once the case is quantified. |
| [[renee-castillo]] | IT Director | evaluator | neutral | Carries the integration risk; quieter in rooms where scope grows. |

## Relationship History

- **2025-11-04:** Phase 0 warehouse pilot signed — first paid engagement, scoped deliberately small.
- **2026-02-20:** Pilot delivered on time — earned the yard-automation conversation.
- **2026-05-20:** Vendor strategy reversed mid-program to single-vendor consolidation — handled without damage, but it cost six weeks.

## Meeting Log

### 2026-05-20 — Vendor strategy brainstorm

- **Attendees:** Leo Marchetti, Renee Castillo
- **Key outcomes:** Agreed to consolidate on one automation vendor across all three yards
- **Follow-ups:** Re-scope yards 2–3; revised commissioning schedule
- **Dynamics:** Leo decisive; Renee raised integration risk twice without pushing back directly

### 2026-03-10 — SteerCo 01

- **Attendees:** Leo Marchetti, Priya Nathan
- **Key outcomes:** Phased regional rollout approved as the working plan
- **Follow-ups:** Confirm yard sequencing
- **Dynamics:** Straightforward; no dissent surfaced

## Sensitivities

- **Incumbent yard-1 integrator:** long-standing relationship predating our engagement — frame consolidation as additive rather than as replacing their partner.
- **The May reversal:** the phased plan was theirs originally — avoid retelling the decision as a correction.

## Engagements

| Project | Status | One-liner |
|---------|--------|-----------|
| [meridian-yard-automation-program](../../30-projects/meridian-yard-automation-program/index.md) | Active | Three-yard automation rollout, single-vendor |
| [meridian-warehouse-pilot-phase-0](../../30-projects/meridian-warehouse-pilot-phase-0/index.md) | Completed | Warehouse pilot that opened the account |
````

For the other two: `nordbridge-components` is a `prospect`, so its Context is
thinner, Stakeholders holds Dana Whitfield, Relationship History has one
entry, and Engagements lists the proposal. `commercial-operations` is the
executive's own `business-unit`, so Stakeholders holds direct reports,
Sensitivities covers internal politics, and Engagements lists the two
commercial-ops projects.

Do not add the `<!-- unvalidated -->` markers or the banner to fixtures —
these represent human-curated dossiers.

- [ ] **Step 7: Run the conformance tests**

Run: `python3 -m pytest scripts/tests/test_fixtures_ontology.py -q`
Expected: PASS. Add `import re` at the top of the test module if
`test_dossier_engagements_resolve_to_real_projects` raises `NameError`.

- [ ] **Step 8: Add the two CI jobs**

Append to `.github/workflows/ci.yml`. **Do not** matrix the existing `plugin`
job — that renames its check context to
`plugin (skill lint + tests) (ubuntu-latest)` and the `main-ci` ruleset
requires the current names exactly, which would block every merge:

```yaml
  runtime_floor:
    name: runtime floor (python 3.10)
    # Cowork's VM ships Python 3.10 while the job above runs 3.13, so a 3.11+
    # construct would otherwise fail only on a client machine. Not a required
    # check yet — promote it in the ruleset once it has proven stable.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: install deps
        run: pip install pytest pyyaml
      - name: tests on the runtime floor
        run: python -m pytest scripts/tests -q

  cross_platform:
    name: cross-platform (windows)
    # The plugin runs inside Cowork's Linux VM, but the Claude Code CLI runs on
    # the host, and the consultant-side scripts run on consultant laptops.
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: install deps
        run: pip install pytest pyyaml
      - name: tests on windows
        run: python -m pytest scripts/tests -q
```

- [ ] **Step 9: Refresh docs/local-setup.md**

Section 4 currently says `plugin/skills/` has no skills yet. Replace that
paragraph with:

````markdown
### 4. Load the plugin locally and verify skills are invocable

**Claude Code** can load the plugin from a path:

```bash
cd /tmp/sb-test-vault
claude --plugin-dir /path/to/sb-accelerator/plugin
```

Run `/help` and confirm `/new-project` and `/update-entity` appear.

**Cowork cannot** — `--plugin-dir` is a Claude Code flag, and Cowork loads
skills only from installed plugins and your own skill store, never from a
connected folder. To exercise the skills where they are designed to run, add
this repo as a marketplace (Customize → Plugins → Add marketplace) using the
root `.claude-plugin/marketplace.json`, then install `second-brain`. See
`playbooks/plugin-distribution.md`.

### 5. Run a skill against the fixtures

Open the test vault and try both:

```
/new-project "Northgate Terminal Refresh"
/update-entity nordbridge-components
```

Then check the CLI directly, which is what the skills call:

```bash
python3 plugin/lib/vaultlib/cli.py entity read \
  --vault /tmp/sb-test-vault --slug meridian-freight-holdings
```

Every call prints one JSON object with an `ok` field. Confirm the created
project's frontmatter matches
`template/99-workflow-config/reference/ontology.md`, and that its body carries
the three H2 sections the ontology's `body_sections` declares.
````

- [ ] **Step 10: Hand-test end to end**

```bash
rm -rf /tmp/port-vault
python3 scripts/make_test_vault.py /tmp/port-vault --with-plugins
python3 plugin/lib/vaultlib/cli.py project scaffold --vault /tmp/port-vault \
  --name "Northgate Terminal Refresh" --type initiative \
  --entity nordbridge-components --owner morgan-ellery \
  --stage "Scoping" --contacts "Dana Whitfield (VP Procurement)" \
  --source "Inbox capture 2026-08-21"
cat /tmp/port-vault/30-projects/northgate-terminal-refresh/index.md
```

Expected: a JSON success envelope, then an index whose frontmatter and three
H2 sections match the enriched fixtures. Read the output rather than skimming
it — this is the artifact judged on quality, and anything that reads as
filler should be fixed in the templates before the PR.

- [ ] **Step 11: Run everything**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
python3 -m pytest scripts/tests -q
python3 scripts/compile_ontology.py --check
```

Expected: all four clean.

- [ ] **Step 12: Commit**

```bash
git add template/30-projects/Decisions.base \
        scripts/tests/test_fixtures_ontology.py \
        fixtures/demo-vault .github/workflows/ci.yml docs/local-setup.md
git commit -m "$(cat <<'EOF'
feat: enrich fixtures to real skill output, harden Decisions.base, add CI jobs

Fixture bodies were placeholders written before the skills that define their
shape existed. Project indexes and dossiers now carry what /new-project and
/update-entity actually produce, and the conformance guard checks body
structure against the ontology's body_sections rather than trusting prose.
Adds the executive's person note, without which a project owner joins to
nothing.

Decisions.base gains a folder filter: it matched type == "decision" with no
folder scope, unlike Meetings.base and Projects.base, so any decision-typed
file anywhere in a client vault landed in their decision table.

Two new CI jobs, both non-required and deliberately separate rather than
matrixed onto the existing plugin job — matrixing renames its check context
and the main-ci ruleset requires the current names exactly, which would block
every merge. The 3.10 job is the more valuable of the two: it is Cowork's
interpreter version, so without it a 3.11+ construct fails only on a client
machine.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage.** Every section of the design doc maps to a task: the
two-value enum, `body_sections`, and the §Entity body schema to Task 1; the
compiled schema to Tasks 1 and 4; the deterministic CLI to Tasks 2–7; D1 to
Tasks 6 and 8; D2 to Tasks 7 and 9; the marketplace manifest to Task 10;
fixture enrichment, the `Decisions.base` filter and both CI jobs to Task 11.

**Deliberately out of scope**, per the spec's own split: D3 (the decision-note
template fence, the two-sided supersession procedure, dropping `tags`) and
`/log-decision` belong to P1b (#20, #36). Task 1 leaves the decision block's
`tags` untouched for that PR to remove.

**Known gap carried forward.** The executive is not added to the meeting
fixtures' `attendees`; the daily-loop PR owns meeting shape. A consequence
worth stating: until then, `slice(attendees, 0, 3)` in the Related Meetings
query shows only other people, which is correct output over incorrect
fixtures.

**Type consistency.** `ProjectError` and `EntityError` are the only custom
exceptions, both raised in their own module and both handled in `cli.main()`
before the generic `ValueError` clause. `naming.find_collision` is used by
`project` and `person` under that one name. `markdown.split_sections` /
`render_sections` are inverses and used as a pair in `entity.write`. The CLI
envelope (`ok` / `result` / `error` / `hint`) is fixed in Task 5 and unchanged
after.

**One risk flagged for the executor.** `entity.write` reconstructs the file by
slicing the frontmatter head out of the original text. If Task 7's Step 4
turns up an off-by-one there, fix the slice rather than the test — the test
that catches it (`test_last_updated_is_bumped_without_reordering_frontmatter`)
is asserting the property that actually matters.

