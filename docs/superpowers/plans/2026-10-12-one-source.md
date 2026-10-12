# One source instead of copies Implementation Plan (#273 piece 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person links to an entity and carries title, decision role and stance; a project stores its stage; an entity page shows Stakeholders and Engagements as live queries; a migration moves every typed table's content to people and projects; skills and `/update-tables` follow.

**Architecture:** Ontology first (schema drives validation). Then the writers: `person set` / `person ensure --entity`, `project touch` stage, the dossier template's live sections, and `entity write` refusing the two keys. Then migration 013 (structure 14), which converts existing vaults and the demo fixture. Last, the skills, `tables.py` and People.base.

**Tech Stack:** Python 3 stdlib (`plugin/lib/vaultlib`, `plugin/migrations`), pytest, skill markdown, Obsidian `.base` YAML (template).

**Spec:** `docs/superpowers/specs/2026-10-12-one-source-design.md`

## Global Constraints

- Worktree `C:\Users\danneelm\projects\sb-accelerator-273b`, branch `feat/273-one-source`, base `origin/main`. If #280 merges first, rebase and take main+1 as the version (expected **0.13.16**).
- Stdlib only. Frontmatter edits are byte-preserving (`markdown.upsert_scalar_field`). New notes go through the existing creators.
- Vocabularies (closed, from ontology.md today): `decision-role`: sponsor, champion, evaluator, influencer, blocker. `stance`: champion, neutral, blocker.
- Migration contract (`plugin/migrations/README.md`): `TARGET_VERSION = 14`, `LOSSY` set (it replaces typed tables; their content moves), `apply(root) -> dict`, `verify(root) -> dict` (raises on failure), idempotent.
- After any ontology edit run `python scripts/compile_ontology.py` (regenerates `plugin/lib/vaultlib/schema.json`). The regeneration test fails if it is stale.
- Wording: "entity" (never "organisation"); never "jot".
- Tests: `python -m pytest scripts/tests -q` from the worktree root. Known unrelated Windows flakes: `test_migration_001` (indented key), `test_vaultlib_entity.py::test_context_bullets_written_across_calls_are_never_dropped_by_the_cap`.
- CHANGELOG line (client-facing) ends with `(#273, #<PR>)`; it says the change needs `/upgrade-vault` (structure 14).

## Review Focus

1. **A Stakeholders row whose person already has a different title, role or stance**: the person's value is kept, and the clash is listed, never overwritten. Test in Task 5.
2. **A company text that matches two entities** (an entity and a team both named "Finance"): left as text and listed, not guessed. Test in Task 5.
3. **Owner text under or above a typed table** (a remark line): it survives the replacement. Test in Task 5.
4. **Running the upgrade twice**: the second run changes nothing (no duplicate Notes bullets, no duplicate project Notes lines). Test in Task 5.
5. **A person linked to a team**: appears on the parent's Stakeholders with the team name, and on the team's own page without one. Pinned by the query text in Task 4 (`dqlrefs` + a contract test). Dataview itself is checked in the end-to-end step.

---

### Task 1: Ontology and schema

**Files:**
- Modify: `plugin/template/99-workflow-config/reference/ontology.md` (Person block, Project block, the Stakeholders and Engagements rows of the Entity body table, the vocabulary lines near "Role in Decision vocabulary")
- Regenerate: `plugin/lib/vaultlib/schema.json`
- Test: `scripts/tests/test_compile_ontology.py` (or the file holding schema enum tests; check with `grep -rn "enum_values" scripts/tests | head`)

- [ ] **Step 1: Write the failing tests**

```python
def test_person_links_to_an_entity_and_carries_stakeholder_fields():
    from vaultlib import schema
    assert schema.enum_values("person", "decision-role") == [
        "sponsor", "champion", "evaluator", "influencer", "blocker", None]
    assert schema.enum_values("person", "stance") == ["champion", "neutral", "blocker", None]


def test_project_has_a_machine_stage():
    text = (REPO_ROOT / "plugin/template/99-workflow-config/reference/ontology.md").read_text(encoding="utf-8")
    assert "`stage`" in text and "machine" in " ".join(text.split()).lower()
```

Use the file's existing `REPO_ROOT` and import style. If `enum_values` does not append `None` for optional enums, assert the list without `None`, and write the enums exactly as `relationship` is written in the Person block.

- [ ] **Step 2:** Run it; expected FAIL.
- [ ] **Step 3: Edit ontology.md.** Person block:

```yaml
object: person
required: [person-name, slug]
keys_present: [relationship]
optional: [email, entity, company, role, decision-role, stance, projects, created,
           last-updated, meetings-7d, meetings-30d, last-met, messages-7d, messages-30d]
enums:
  relationship: [colleague, direct-report, external, null]
  decision-role: [sponsor, champion, evaluator, influencer, blocker, null]
  stance: [champion, neutral, blocker, null]
```

Under it, add bullets:
- `entity` — the slug of the entity (or team) the person belongs to; the entity page's Stakeholders lists them. Set by `person set`, by `/update-tables`, and by `person ensure --entity` when routing knows it.
- `company` — legacy free text, kept only where the structure-14 upgrade found no single matching entity. Nothing new writes it.
- `role` (title), `decision-role` and `stance` are the person's stakeholder fields, shown on their entity's page.

Project block: add `stage` to `optional`, and a bullet: "`stage` — the card's Stage sentence, stored by `project state write` (machine-maintained, like `state-updated`); the entity page's Engagements shows it."

Entity body table: the Stakeholders row becomes "Live query: people whose `entity` is this entity or one of its teams (Name · Team · Title · Role in decision · Stance). Not written; edit the people." The Engagements row becomes "Live query: projects of this entity or its teams (Project · Status · Where it stands · Next milestone). Not written." Move the vocabulary line to say it applies to the person's `decision-role` and `stance`.

- [ ] **Step 4:** `python scripts/compile_ontology.py`, then `python -m pytest scripts/tests/test_compile_ontology.py scripts/tests/test_vaultlib_schema.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(#273): ontology — person entity link and stakeholder fields, project stage`.

---

### Task 2: `person set` and `person ensure --entity`

**Files:**
- Modify: `plugin/lib/vaultlib/person.py`, `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_person.py` (append)

**Interfaces:**
- Produces:
  - `person.ensure(root, name, today, email=None, entity=None)`. A new note gets `entity: <slug>` (or the empty key) and **no** `company` key. On an existing note, `entity` fills only when empty (`result["updated"]` includes `"entity"`); a different set entity goes to `ignored`.
  - `person.set_fields(root, slug, *, entity=None, role=None, decision_role=None, stance=None) -> {"slug", "path", "changed": [props]}`. It raises `ValueError` on an unknown slug, a missing entity dossier, or a value outside the enum. An empty string clears the field. `None` leaves the field alone.
  - CLI: `person ensure --entity E`, `person set --vault V --slug S [--entity E] [--role R] [--decision-role D] [--stance X]`.

- [ ] **Step 1: Write the failing tests**

```python
def _entity(root, slug="acme"):
    (root / "40-entities" / slug).mkdir(parents=True, exist_ok=True)
    (root / "40-entities" / slug / "dossier.md").write_text(
        f'---\ntype: entity\nentity-name: "Acme"\nslug: {slug}\nstatus: active\n---\n', encoding="utf-8")


def test_ensure_links_a_new_person_and_writes_no_company(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    made = person.ensure(root, "Jan Peeters", "2026-10-12", entity="acme")
    text = (root / made["path"]).read_text(encoding="utf-8")
    assert "entity: acme" in text and "company" not in text


def test_ensure_fills_an_empty_entity_only(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    _entity(root, "beta")
    person.ensure(root, "Jan Peeters", "2026-10-12")
    assert "entity" in person.ensure(root, "Jan Peeters", "2026-10-12", entity="acme")["updated"]
    again = person.ensure(root, "Jan Peeters", "2026-10-12", entity="beta")
    assert "entity" in again["ignored"]


def test_set_fields_writes_and_validates(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    person.ensure(root, "Jan Peeters", "2026-10-12")
    got = person.set_fields(root, "jan-peeters", entity="acme", role="CFO",
                            decision_role="sponsor", stance="champion")
    assert got["changed"] == ["entity", "role", "decision-role", "stance"]
    text = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    assert 'role: "CFO"' in text and "decision-role: sponsor" in text
    with pytest.raises(ValueError, match="stance"):
        person.set_fields(root, "jan-peeters", stance="hostile")
    with pytest.raises(ValueError, match="entity"):
        person.set_fields(root, "jan-peeters", entity="nobody")
```

Use the file's existing `make_vault` (check its name with `grep -n "^def make_vault\|^from" scripts/tests/test_vaultlib_person.py`); it must create `40-entities/`, so add the folder in the test if it does not.

- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3: Implement.** In `person.py`, add `"role"` to the quote keys as it already is, keep `company` in `PERSON_QUOTE_KEYS` for legacy writes. In `ensure`: add `entity: Optional[str] = None`. Validate it (`naming.validate_slug`, and the dossier exists at `ENTITIES_DIR/<e>/dossier.md`, else `ValueError`). In the existing-note branch, mirror the email logic for `entity` (fill when empty, otherwise `ignored`). In the new-note frontmatter, replace `"company": None` with `"entity": entity`. Add:

```python
_ENUMS = {"decision-role": ("sponsor", "champion", "evaluator", "influencer", "blocker"),
          "stance": ("champion", "neutral", "blocker")}


def set_fields(root: Path, slug: str, *, entity: Optional[str] = None,
               role: Optional[str] = None, decision_role: Optional[str] = None,
               stance: Optional[str] = None) -> dict:
    """Write a person's entity link and stakeholder fields (#273). `None`
    leaves a field alone; an empty string clears it."""
    found = _existing_note(root, slug)
    if found is None:
        raise ValueError(f"no person {slug!r} in {PEOPLE_DIR}/")
    text = found.read_text(encoding="utf-8")
    current, _ = markdown.split_frontmatter(text)
    wanted = {"entity": entity, "role": role, "decision-role": decision_role, "stance": stance}
    changed = []
    for prop, value in wanted.items():
        if value is None:
            continue
        value = str(value).strip()
        if value and prop == "entity":
            naming.validate_slug(value)
            if not (root / ENTITIES_DIR / value / "dossier.md").is_file():
                raise ValueError(f"entity {value!r} has no dossier at {ENTITIES_DIR}/{value}/dossier.md")
        if value and prop in _ENUMS and value not in _ENUMS[prop]:
            raise ValueError(f"{prop} {value!r} is not one of {list(_ENUMS[prop])}")
        if str(current.get(prop) or "") == value:
            continue
        rendered = markdown.emit_scalar(value, prop in PERSON_QUOTE_KEYS) if value else ""
        text = markdown.upsert_scalar_field(text, prop, rendered)
        changed.append(prop)
    if changed:
        vault.atomic_write(found, text)
    return {"slug": found.stem, "path": found.relative_to(root).as_posix(), "changed": changed}
```

(`ENTITIES_DIR = vault.ENTITIES_DIR` at module top if it is not there.) CLI: add `--entity` to `person ensure`, and a `person set` parser with the four optional flags, dispatching to `set_fields`. `ValueError` is already mapped by the CLI's generic handler; check that it yields a `_fail` with the message.

- [ ] **Step 4:** Run `python -m pytest scripts/tests/test_vaultlib_person.py scripts/tests/test_vaultlib_cli.py -q`. Expected PASS. Then run `test_vaultlib_msgroute.py` and `test_vaultlib_syncjob.py`: any test asserting `company:` on a new person note must now expect `entity:`. Update such assertions; do not weaken them.
- [ ] **Step 5: Commit** `feat(#273): person set and person ensure --entity`.

---

### Task 3: `stage` on the project

**Files:**
- Modify: `plugin/lib/vaultlib/project.py` (`touch` gains `stage`), `plugin/lib/vaultlib/projectstate.py` (passes `state["stage"]`)
- Test: `scripts/tests/test_vaultlib_projectstate.py` (append)

- [ ] **Step 1: Failing test**

```python
def test_state_write_stores_the_stage_in_frontmatter(tmp_path):
    root, slug = scaffolded(tmp_path)
    payload = state()
    payload["stage"] = "Vendor shortlist agreed; selection by 27 Dec"
    projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")
    text = (root / "30-projects" / slug / "index.md").read_text(encoding="utf-8")
    assert 'stage: "Vendor shortlist agreed; selection by 27 Dec"' in text
```

(`scaffolded` and `state` are the file's own helpers.)

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** `project.touch(..., stage: Optional[str] = None)`. When `stage` is given, `upsert_scalar_field(text, "stage", markdown.emit_scalar(stage, True))`. Add `"stage"` to `PROJECT_QUOTE_KEYS`. In `projectstate.write`, pass `stage=state.get("stage") or None` to `touch`.
- [ ] **Step 4:** Run `test_vaultlib_projectstate.py`, `test_vaultlib_project.py` and `test_vaultlib_updatequeue.py`; PASS. If a byte-exact `touch` test breaks because a new `stage` line appears, update the expected bytes for that test only.
- [ ] **Step 5: Commit** `feat(#273): project state write stores the stage sentence`.

---

### Task 4: Live Stakeholders and Engagements on the entity page

**Files:**
- Modify: `plugin/lib/vaultlib/entity.py`
- Test: `scripts/tests/test_vaultlib_entity.py` (convert), `scripts/tests/test_dataview_refs.py` (or wherever dossier queries are scanned), `scripts/tests/test_skill_contracts.py` (later, Task 7)

**Interfaces:**
- Produces: `entity.STAKEHOLDERS_QUERY`, `entity.ENGAGEMENTS_QUERY` (the spec's two dataview blocks, verbatim), and `entity.TEAMS_SECTION`, now with only its first query. `entity.write` raises `EntityError("stakeholders live on the person — use: person set --slug <person> --entity <this> …")` for the key `stakeholders`, and an analogous message for `engagements` ("Engagements is a live list of this entity's projects — nothing to write").

- [ ] **Step 1: Failing tests** (append):

```python
def test_a_new_dossier_carries_the_live_sections(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    body = (root / "40-entities/acme/dossier.md").read_text(encoding="utf-8")
    assert entity.STAKEHOLDERS_QUERY in body and entity.ENGAGEMENTS_QUERY in body
    assert "| Name | Title |" not in body and "| Project | Status | One-liner |" not in body


def test_writing_stakeholders_or_engagements_is_refused_with_a_pointer(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    with pytest.raises(entity.EntityError, match="person set"):
        entity.write(root, "acme", {"stakeholders": [{"name": "Jan"}]}, "2026-10-12")
    with pytest.raises(entity.EntityError, match="live list"):
        entity.write(root, "acme", {"engagements": [{"project": "x"}]}, "2026-10-12")


def test_the_teams_section_no_longer_lists_projects():
    assert 'FROM "30-projects"' not in entity.TEAMS_SECTION
```

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Implement.**
  - Add the two query constants, with a comment like the Meeting Log's ("slug-free; `this.slug` resolves at render time").
  - In `_empty_body`, render `## Stakeholders\n\n{STAKEHOLDERS_QUERY}\n` and `## Engagements\n\n{ENGAGEMENTS_QUERY}\n`.
  - Cut `TEAMS_SECTION` down to its first query.
  - In `write`, refuse the two keys before any merge, with the messages above.
  - Delete `_merge_stakeholders`, `_merge_engagements`, `STAKEHOLDER_HEADER`, `ENGAGEMENT_HEADER` and their entries in the merge map and field lists, only if nothing else imports them (`grep -rn "STAKEHOLDER_HEADER\|_merge_stakeholders\|ENGAGEMENT_HEADER" plugin scripts`). Keep them if migration 001's frozen copies depend on them. Migrations import their own frozen literals, so check.
  - `read()`: the two sections are returned as raw text, never parsed into rows.
- [ ] **Step 4: Convert the existing entity tests.** Tests that exercise stakeholder or engagement **merging** test removed behaviour. Delete them, and list each deleted test name in the ledger as a ruling. Tests that only *create* an entity and assert the old header change to assert the new query. Run `python -m pytest scripts/tests/test_vaultlib_entity.py -q` until green.
- [ ] **Step 5: Query checks.** Find how existing dossier queries are validated (`grep -n "MEETING_LOG_QUERY\|TEAMS_SECTION" scripts/tests/test_dataview_refs.py scripts/tests/*.py`). Add the two new constants to that check, so every property they read (`person-name`, `entity`, `role`, `decision-role`, `stance`, `project-name`, `status`, `stage`, `next-milestone`, `parent`, `entity-name`, `type`) exists in the ontology. Run it; PASS.
- [ ] **Step 6: Commit** `feat(#273): Stakeholders and Engagements are live queries on the entity page`.

---

### Task 5: Migration 013 → structure 14

**Files:**
- Create: `plugin/migrations/013-structure-version-14/migrate.py`
- Test: `scripts/tests/test_migration_013.py`
- Modify: `plugin/template/structure-version` → `14`

**Interfaces:**
- Produces: `apply(root) -> {"linked": int, "unmatched": [{"person", "company"}], "stakeholders_moved": int, "people_created": [slug], "clashes": [str], "notes_moved": int, "one_liners_moved": int, "unresolved": [str], "dossiers": int}`. `verify(root)` raises if any dossier still holds a typed Stakeholders or Engagements table, or a Teams section still has its project query.
- The migration carries **frozen copies** of the two query blocks and of the trimmed Teams query (migrations never import live constants that may change later; see `test_migration_001`'s frozen-literal pattern).

- [ ] **Step 1: Failing tests.** Build fixtures with plain file writes:

```python
"""Migration 013: one source instead of copies (#273)."""
import importlib.util
from pathlib import Path

import pytest

MIG = Path(__file__).resolve().parents[2] / "plugin/migrations/013-structure-version-14/migrate.py"


def load():
    spec = importlib.util.spec_from_file_location("m013", MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD_DOSSIER = """---
type: entity
entity-name: "Acme"
slug: acme
status: active
---

# Acme

## Context

> [!info]+ **Standing context**
> x

## Stakeholders

Owner's remark above the table.

| Name | Title | Role in Decision | Stance | Notes |
|------|-------|------------------|--------|-------|
| [[jan-peeters]] | CFO | sponsor | champion | Wants numbers, not narrative. |
| Sofie Maes | COO | evaluator | hostile | <!-- needs-review --> |
| Piet Nieuw | Buyer | influencer | neutral | Joined in May. |

## Relationship History

x

## Meeting Log

x

## Sensitivities

x

## Engagements

| Project | Status | One-liner |
|---------|--------|-----------|
| [acme-erp](../../30-projects/acme-erp/index.md) | Active | Go-live in Q1 |
| [ghost](../../30-projects/ghost/index.md) | Active | Never existed |

## Teams

```dataview
TABLE WITHOUT ID
  link(file.path, entity-name) AS "Team"
FROM "40-entities"
WHERE parent = this.slug
```

```dataview
TABLE WITHOUT ID
  link(file.path, project-name) AS "Project"
FROM "30-projects"
WHERE type = "project" AND link("40-entities/" + entity + "/dossier").parent = this.slug
```
"""


def vault(tmp_path):
    root = tmp_path / "v"
    for d in ("50-people", "30-projects/acme-erp", "40-entities/acme", "40-entities/acme-finance",
              "99-workflow-config", "20-meetings"):
        (root / d).mkdir(parents=True)
    (root / "40-entities/acme/dossier.md").write_text(OLD_DOSSIER, encoding="utf-8")
    (root / "40-entities/acme-finance/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Finance"\nslug: acme-finance\nstatus: active\nparent: acme\n---\n# Finance\n',
        encoding="utf-8")
    (root / "30-projects/acme-erp/index.md").write_text(
        '---\ntype: project\nproject-name: "ERP"\nslug: acme-erp\nentity: acme\n---\n# ERP\n', encoding="utf-8")
    people = {
        "jan-peeters": '---\nperson-name: "Jan Peeters"\nslug: jan-peeters\nrelationship:\ncompany: "acme"\nrole: "Finance director"\n---\n# Jan Peeters\n',
        "sofie-maes": '---\nperson-name: "Sofie Maes"\nslug: sofie-maes\nrelationship:\ncompany: "LLBG"\nrole:\n---\n# Sofie Maes\n',
        "an-de-smet": '---\nperson-name: "An De Smet"\nslug: an-de-smet\nrelationship:\ncompany: "finance"\nrole:\n---\n# An De Smet\n',
    }
    for slug, text in people.items():
        (root / "50-people" / f"{slug}.md").write_text(text, encoding="utf-8")
    return root


def fm(root, rel):
    from vaultlib import markdown
    return markdown.split_frontmatter((root / rel).read_text(encoding="utf-8"))


def test_company_becomes_an_entity_link_when_it_matches_one(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    data, _ = fm(root, "50-people/jan-peeters.md")
    assert data["entity"] == "acme" and "company" not in data
    assert {"person": "sofie-maes", "company": "LLBG"} in result["unmatched"]


def test_an_ambiguous_company_stays_text(tmp_path):
    root = vault(tmp_path)
    (root / "40-entities/finance").mkdir()
    (root / "40-entities/finance/dossier.md").write_text(
        '---\ntype: entity\nentity-name: "Finance"\nslug: finance\nstatus: active\n---\n', encoding="utf-8")
    load().apply(root)
    assert fm(root, "50-people/an-de-smet.md")[0]["company"] == "finance"


def test_stakeholder_rows_move_to_people_and_clashes_are_kept(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    jan, body = fm(root, "50-people/jan-peeters.md")
    assert jan["role"] == "Finance director"                      # kept, not the table's "CFO"
    assert jan["decision-role"] == "sponsor" and jan["stance"] == "champion"
    assert any("jan-peeters" in c and "CFO" in c for c in result["clashes"])
    assert "## Notes from Acme" in body and "Wants numbers, not narrative." in body
    sofie, sbody = fm(root, "50-people/sofie-maes.md")
    assert sofie.get("stance") in (None, "")                     # "hostile" is not in the vocabulary
    assert any("hostile" in c for c in result["clashes"])
    assert "## Notes from" not in sbody                          # only a needs-review marker
    assert "piet-nieuw" in result["people_created"]
    piet, _ = fm(root, "50-people/piet-nieuw.md")
    assert piet["entity"] == "acme" and piet["role"] == "Buyer"


def test_one_liners_move_to_the_project_and_unresolved_rows_are_listed(tmp_path):
    root = vault(tmp_path)
    result = load().apply(root)
    _, body = fm(root, "30-projects/acme-erp/index.md")
    assert "## Notes" in body and "Go-live in Q1" in body
    assert any("ghost" in u for u in result["unresolved"])


def test_tables_are_replaced_and_owner_text_survives(tmp_path):
    root = vault(tmp_path)
    module = load()
    module.apply(root)
    _, body = fm(root, "40-entities/acme/dossier.md")
    assert "| Name | Title |" not in body and "| Project | Status |" not in body
    assert module.STAKEHOLDERS_QUERY in body and module.ENGAGEMENTS_QUERY in body
    assert "Owner's remark above the table." in body
    assert body.count('FROM "30-projects"') == 1                 # Engagements only; Teams lost its query
    module.verify(root)


def test_a_second_run_changes_nothing(tmp_path):
    root = vault(tmp_path)
    module = load()
    module.apply(root)
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    module.apply(root)
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot


def test_a_vault_without_dossiers_is_fine(tmp_path):
    root = tmp_path / "v"
    for d in ("50-people", "40-entities", "99-workflow-config"):
        (root / d).mkdir(parents=True)
    module = load()
    assert module.apply(root)["dossiers"] == 0
    module.verify(root)
```

- [ ] **Step 2:** Run; FAIL (file missing).
- [ ] **Step 3: Implement `migrate.py`.** Module docstring as the other migrations (what, why, what the owner sees, not lossy in substance: the content moves). `TARGET_VERSION = 14`. `LOSSY = "replaces each entity page's typed Stakeholders and Engagements tables with live lists; their titles, roles, stances and notes move to the people, their one-liners to the projects' Notes"`. Constants: frozen `STAKEHOLDERS_QUERY`, `ENGAGEMENTS_QUERY` (equal to `entity.py`'s at the time of writing), and the regex for the Teams project block. Functions:
  1. `_people(root)`: slug → (path, frontmatter, text).
  2. `_entities(root)`: slug → (entity-name, parent).
  3. `_match_entity(text, entities)`: a case-insensitive match on entity-name **or** slug. Exactly one hit → slug; otherwise None.
  4. **Company step:** for every person with `company` and no `entity`, match. On a hit, `upsert_scalar_field(text, "entity", slug)` and remove the `company` line. Write a small `_remove_field(text, field)` that deletes the node the way `_replace_field_node` finds it. Otherwise record it in `unmatched`.
  5. **Dossier step,** per dossier: split sections with `markdown.split_sections(body, level=2)`. Then:
     - **Stakeholders:** find the table lines (`|`-prefixed). The text before is the preamble and the text after is the postamble. Parse rows with the same pipe-split rule as `entity._split_row`: copy that function as a frozen helper, honouring `\|`. Per row:
       - resolve the person (a `[[slug]]` / `[[slug|alias]]` wikilink, else the name matched to `person-name` case-insensitively, else `person.ensure(root, name, today)` with today = `date.today().isoformat()`, recorded in `people_created`);
       - fill the empty `role`/`decision-role`/`stance` from Title/Role in Decision/Stance. An out-of-vocabulary value goes to `clashes` (`f"{slug}: stance 'hostile' is not in the vocabulary"`). A differing existing value goes to `clashes` (`f"{slug}: role kept 'Finance director' (table said 'CFO')"`);
       - set `entity` if empty;
       - Notes without `<!-- needs-review -->` and not empty → add a bullet under `## Notes from <Entity name>` on the person's page (create the heading at the end if missing). Skip it if the identical bullet text is already there (idempotency). Format: `- <notes> (moved from the <Entity name> page, <today>)`; idempotency compares on `- <notes> (moved from the <Entity name> page,`.
       
       Then the section becomes `preamble + STAKEHOLDERS_QUERY + postamble`.
     - **Engagements:** parse rows. The project slug comes from the link target (`../../30-projects/<slug>/index.md` or `[[...]]`). If the index exists and the one-liner is not empty → append `- Engagement note (moved from the <Entity name> page, <today>): <one-liner>` under `## Notes` at the end of the project body (create the heading if missing; skip if the same `): <one-liner>` text is already present). Otherwise record it in `unresolved`. The section becomes `preamble + ENGAGEMENTS_QUERY + postamble`.
     - **Teams:** remove a ```` ```dataview ```` block containing `FROM "30-projects"`.
     - A section already holding the query (second run) is left alone.
  6. Re-render the body with `markdown.render_sections` and write it only if it changed.
  7. `verify`: for every dossier, assert there is no `| Name | Title |` header and no `| Project | Status | One-liner |` header, and that the Teams section has no `FROM "30-projects"`.

  All writes go through `vault.atomic_write`. `person.ensure` is imported from `vaultlib` (allowed: it creates notes with today's shape).
- [ ] **Step 4:** Set `plugin/template/structure-version` to `14`. Run `python -m pytest scripts/tests/test_migration_013.py scripts/tests/test_vaultlib_migrate.py -q`; PASS. `test_vaultlib_migrate.py` checks the chain is consecutive.
- [ ] **Step 5: Commit** `feat(#273): migration 013 — stakeholder tables to people, engagement tables to projects (structure 14)`.

---

### Task 6: People.base and `/update-tables`

**Files:**
- Modify: `plugin/template/50-people/People.base`, `plugin/lib/vaultlib/tables.py`
- Test: `scripts/tests/test_vaultlib_tables_export.py`, `scripts/tests/test_vaultlib_tables_import.py`, `scripts/tests/test_bases_views.py` (if it pins People columns)

- [ ] **Step 1: Failing tests**

```python
def test_people_export_has_entity_role_in_decision_and_stance(tmp_path):
    root = make_vault(tmp_path)
    note = root / "50-people/jan-peeters.md"
    note.write_text(note.read_text(encoding="utf-8").replace('company: "Acme"', "entity: acme"), encoding="utf-8")
    book = xlsx.read(root / tables.export(root, "people", today="2026-10-12")["path"])
    header, row = book["People"][0], book["People"][1]
    assert row[header.index("Entity")] == "Acme"
    assert "Role in decision" in header and "Stance" in header


def test_an_unknown_entity_on_a_person_is_refused(tmp_path):
    root = make_vault(tmp_path)
    rel, book = exported(root)
    book["People"][1][col(book, "People", "Entity")] = "LLBG"
    save(root, rel, book)
    assert tables.plan(root, rel)["counts"]["refused"] == 1
```

(`make_vault` in `test_vaultlib_tables_export.py` writes Jan with `company: "Acme"`; update that fixture to `entity: acme`, and adjust tests asserting Company to Entity. The `company`-is-text test becomes the refusal test above.)

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: People.base.**
  - Add a formula `entity-name: if(entity, link("40-entities/" + entity + "/dossier.md", if(file("40-entities/" + entity + "/dossier.md"), file("40-entities/" + entity + "/dossier.md").properties["entity-name"], entity)), company)`.
  - Its property `formula.entity-name: displayName: Entity`, plus `note.decision-role: displayName: Role in decision` and `note.stance: displayName: Stance`.
  - In every view's `order`, replace `company` with `formula.entity-name`, and in the All view add `decision-role`, `stance` after `role`.
  
  `tables.py` People fields: replace `("company", "company", False)` with `("entity", "entity", False)`, and add `("decision-role", "choice:sponsor|champion|evaluator|influencer|blocker", False)` and `("stance", "choice:champion|neutral|blocker", False)` after `role`. The formula maps to `entity` by `_refs` (it also references `company`, which is not editable, so the single editable ref is `entity`). Remove the `company` kind handling if nothing else uses it.
- [ ] **Step 4:** Run the three table test files plus `test_bases_views.py` and `test_template_config.py`; PASS.
- [ ] **Step 5: Commit** `feat(#273): People shows Entity, Role in decision and Stance; /update-tables follows`.

---

### Task 7: Skills

**Files:**
- Modify: `plugin/skills/update-entity/SKILL.md`, `plugin/skills/new-project/SKILL.md`, `plugin/skills/sync-recordings/SKILL.md` (+ `references/worker-contract.md` where `person ensure` is briefed), `plugin/skills/sync-messages/SKILL.md` (if it calls `person ensure`), `plugin/skills/setup-my-brain/SKILL.md`, `plugin/skills/update-tables/SKILL.md` (unknown entity is now refused, no "keep as text")
- Test: `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Failing contract tests**

```python
def test_update_entity_writes_stakeholders_onto_the_person():
    text = read_skill("update-entity")
    assert "person set" in text and "--decision-role" in text
    assert '"stakeholders"' not in text and '"engagements"' not in text


def test_new_project_no_longer_writes_an_engagements_row():
    assert "engagements" not in read_skill("new-project").lower()


def test_person_ensure_passes_the_entity_only_when_routing_knows_it():
    flat = " ".join(read_skill("sync-recordings").split())
    assert "--entity" in flat and "never a guess" in flat.lower()
```

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Edit the skills.**
  - **update-entity:** remove the `stakeholders`/`engagements` payload keys and their examples. Add a section "**People at this entity**": for each person, `person ensure --name` if new, then `person set --slug <s> --entity <this slug> [--role …] [--decision-role …] [--stance …]` (vocabularies as before). A note about the person goes onto the person's page under `## Notes from <entity name>` until piece 4 provides "What I know". Engagements: "nothing to write; the page lists the entity's projects itself."
  - **new-project:** delete step 5 and renumber; rule 5's "dossier link skipped" goes.
  - **sync-recordings:** at the `person ensure` for attendees (step 3, and the worker contract for M365), add: pass `--entity <slug>` only when the attendee's email domain matched exactly one entity in routing (signal 1). Never a guess; otherwise omit.
  - **sync-messages:** only if it calls `person ensure` directly; same rule.
  - **setup-my-brain:** in the people step, pass `--entity` when the owner said where the person works and that entity exists.
  - **update-tables:** step 3, an unknown Entity on People: *"<name> is not an entity: create it first (`entity ensure`), then import again"*. Drop "keep as text".
- [ ] **Step 4:** Run `python -m pytest scripts/tests/test_skill_contracts.py scripts/tests/test_template_prose.py -q` and `python scripts/lint_plugin.py`; PASS. Fix older contract tests that pinned the removed text by re-pointing them at the new behaviour, never by deleting the assertion's intent. Ledger each one.
- [ ] **Step 5: Commit** `feat(#273): skills write stakeholder fields onto people; Engagements needs no writing`.

---

### Task 8: Demo fixture, docs, version, end to end, PR

- [ ] **Step 1: Migrate the demo fixture.** Run migration 013 on a copy of `fixtures/demo-vault` and copy the changed files back:
  - `python -c "…load migrate.py; apply(Path('fixtures/demo-vault'))"` on a scratch copy;
  - check the diff: dossiers get live sections, people get entity, decision-role and stance, and Notes move;
  - commit the result.
  
  Run `test_fixtures_ontology.py`, `test_validate_template.py` and `test_make_test_vault.py`.
- [ ] **Step 2: Docs.** Start here: if it mentions Stakeholders or Engagements, say they fill themselves. `plugin/CLAUDE.md`: if it lists `entity write` keys, update them. CHANGELOG (top of Unreleased):

```markdown
- **Entity pages fill themselves**: Stakeholders now lists the people linked to the entity (and its teams), with their title, role in decision and stance, and Engagements lists its projects with where each stands and what is next — always current, however a person or project was added. A person's company is now a real link to an entity (the People table shows **Entity**); title, role in decision and stance live on the person and can be filled in with `/update-tables`. Needs `/upgrade-vault` (structure 14): it links people to their entity where the company name matches one (others are listed for you to resolve), moves each Stakeholders row's details and notes onto the person and each project's one-liner into the project's Notes, then replaces the old typed tables. (#273)
```

- [ ] **Step 3:** Rebase on `origin/main`, bump the version (main+1) in `plugin.json` and the manifest test, then run the full suite and lint.
- [ ] **Step 4: End to end.**
  - `make_test_vault.py --demo-day <today>` → open the Commercial Operations dossier in Obsidian (the isolated-CDP recipe in memory, or ask the owner) to see that the live Stakeholders and Engagements render, including the Team column for a team member.
  - A fresh `/upgrade-vault` run on a structure-13 copy of the demo vault, where `make_test_vault` builds the current structure: produce a structure-13 copy by checking out `origin/main`'s fixture into scratch. Check the report.
- [ ] **Step 5:** Push, open the PR, add the PR number to the CHANGELOG line, check, push. Report CI; never merge.
