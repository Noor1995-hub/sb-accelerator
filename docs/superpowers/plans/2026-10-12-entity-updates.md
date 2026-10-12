# Entity and team pages update themselves Implementation Plan (#273 piece 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every evening and on demand, each active or prospect entity with new material gets its Context, Relationship History, Dynamics and Sensitivities updated by a subagent through `entity write`, then stamped with `entity-updated`; team material also feeds the parent's Relationship History.

**Architecture:** `update-queue` gains an entity queue (`entitiesNeedingUpdate`) computed from the same indexes it already builds (meetings get `entities`). `entity touch` stamps `entity-updated`. `process.md` gains section D (dispatch, instructions, write-back), run after C by every caller.

**Tech Stack:** Python 3 stdlib, pytest, skill markdown.

**Spec:** `docs/superpowers/specs/2026-10-12-entity-updates-design.md`

## Global Constraints

- Worktree `C:\Users\danneelm\projects\sb-accelerator-273c`, branch `feat/273-entity-updates`, built on `feat/273-one-source` (#281). Before the PR: #281 merged, then `git rebase --onto origin/main <last #281 commit>`, version main+1.
- Stdlib only; byte-preserving frontmatter edits; CLI envelope via `_ok` / `_fail`.
- Only `status` active/prospect entities are queued. No cap.
- Every automatic dossier line ends with a source marker: `(meeting · [[stem]])`, `(mail · <link>)`, `(chat · <link>)`, `(session · [[path|title]])`, `(note · <title>)`. Parent mode adds `(<team name> team)` before the marker.
- Tests: `python -m pytest scripts/tests -q`. Known Windows flakes as before.

## Review Focus

1. **A meeting confirmed after the entity's last update** (old meeting, newly accepted): it queues the entity, using `confirmed-at` as for projects. Test in Task 2.
2. **An entity with no `entity-updated` stamp** (every existing vault on day one): its threshold is its `last-updated` day, so everything newer queues once, not all history every night. Test in Task 2.
3. **A team whose parent is dormant**: the team queues, the parent does not. Test in Task 2.
4. **Material with an entity whose dossier is missing**: no queue entry, no crash. Test in Task 2.
5. **On demand holds the lock through D**: the release is after D in `/sync-recordings` and `/add`. Contract test in Task 3.

---

### Task 1: `entity touch` and the ontology

**Files:** `plugin/lib/vaultlib/entity.py`, `plugin/lib/vaultlib/cli.py`, `plugin/template/99-workflow-config/reference/ontology.md` (+ `python scripts/compile_ontology.py`), `scripts/tests/test_vaultlib_entity.py`

**Interfaces:** Produces `entity.touch(root, slug, *, timestamp: str) -> {"slug", "path", "entity-updated", "changed"}` (`timestamp` `YYYY-MM-DDTHH:MM`, else `EntityError`); CLI `entity touch --vault V --slug S --timestamp T`.

- [ ] **Step 1: Failing tests**

```python
def test_touch_stamps_entity_updated_and_nothing_else(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    path = root / "40-entities/acme/dossier.md"
    before = path.read_text(encoding="utf-8")
    result = entity.touch(root, "acme", timestamp="2026-10-12T21:05")
    after = path.read_text(encoding="utf-8")
    assert result["entity-updated"] == "2026-10-12T21:05" and result["changed"]
    assert after.replace("entity-updated: 2026-10-12T21:05\n", "") == before


def test_touch_refuses_a_bad_timestamp(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    with pytest.raises(entity.EntityError):
        entity.touch(root, "acme", timestamp="12/10 21h")
```

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Implement.**
  - `touch`: validate with `re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", timestamp)`. The dossier must exist (`read(root, slug)` raises otherwise). Then `vault.atomic_write(path, markdown.upsert_scalar_field(text, "entity-updated", timestamp))`.
  - CLI: an `entities_sub` parser `touch` with `--slug` and `--timestamp`, and a dispatch `if args.action == "touch"`.
  - Ontology Entity block: add `entity-updated` to `optional`, plus a bullet: "`entity-updated` — when the automatic update last read new material (ISO minute; machine-maintained by `entity touch`). `last-updated` is the day the page last changed."
  - Run `compile_ontology.py`.
- [ ] **Step 4:** Run `test_vaultlib_entity.py`, `test_vaultlib_schema.py`, `test_compile_ontology.py`, `test_vaultlib_cli.py`; PASS.
- [ ] **Step 5: Commit** `feat(#273): entity touch stamps entity-updated`.

---

### Task 2: The entity queue in `update-queue`

**Files:** `plugin/lib/vaultlib/updatequeue.py`, `scripts/tests/test_vaultlib_updatequeue.py`

**Interfaces:**
- `_index_meetings` items gain `"entities": [slug]` (from frontmatter `entities`).
- `_index_logs` items gain `"entities": [slug]` (from frontmatter `entities`).
- `run()` result gains `"entitiesNeedingUpdate": [entry]`, built by a new `_entity_queue(root, confirmed, logs, sessions, included, warnings) -> list`. Entry: `{"slug", "dossierPath", "entityName", "entityUpdated": str|None, "parentMode": bool, "newFiles", "newLogs", "newSessions", "newNotes", "teamFiles": [{"team", "teamName", "files", "logs", "sessions", "notes"}]}`.

Rules:
- **Entities:** every `40-entities/*/dossier.md` with `status` in (active, prospect); read `slug` (or folder), `entity-name`, `parent`, `entity-updated`, `last-updated`.
- **Threshold:** `entity-updated` parsed, else `datetime.combine(last-updated, time.min)`, else (no parsable stamp) `datetime.min`. That last case means every item counts once.
- **Project → entity map** from project indexes (`entity` field).
- **Own material for entity E:**
  - confirmed, non-`note` meetings with E in `entities`, or with a project whose entity is E, and `_activity(m) >= threshold`;
  - logs with E in `entities`, or a strong project whose entity is E, and `updated >= threshold`;
  - sessions with a project whose entity is E, and `updated >= threshold`;
  - included notes with a project whose entity is E.
- **Team T (`parent: P`)** with own material: T gets a full entry. If P is in the active set, P's entry gets a `teamFiles` item `{team: T, teamName, files, logs, sessions, notes}`, using T's own lists. A P with no own material but team material gets an entry with `parentMode: true`; with both, `parentMode: false` plus `teamFiles`.
- Entries are sorted by slug.

- [ ] **Step 1: Failing tests** (reuse the file's `make_vault`, `write_project`, `write_meeting` with an added `entities` kw, `write_log`, `g`, `write_session`; add a helper `write_entity(root, slug, name, *, status="active", parent=None, entity_updated=None, last_updated="2026-10-01")`). Tests:

```python
def test_a_meeting_after_the_stamp_queues_its_entity(tmp_path): ...
    # entity acme stamped 2026-10-12T09:00; meeting 2026-10-12T10:00 confirmed, entities [acme]
    # → entitiesNeedingUpdate == [acme entry with newFiles == [the meeting]]

def test_a_meeting_confirmed_after_the_stamp_queues_even_if_old(tmp_path): ...
    # meeting date 2026-10-01, confirmed-at 2026-10-12T11:00, stamp 2026-10-12T09:00 → queued

def test_no_stamp_falls_back_to_last_updated_day(tmp_path): ...
    # no entity-updated, last-updated 2026-10-10; meetings 2026-10-05 and 2026-10-11 → only the 11th

def test_a_meeting_through_its_projects_entity_queues(tmp_path): ...
    # meeting has projects [acme-erp] (entity acme) and no entities field → queued

def test_logs_and_sessions_queue_by_entity_or_project(tmp_path): ...

def test_a_team_queues_itself_and_feeds_its_parent_in_parent_mode(tmp_path): ...
    # acme-finance parent acme; meeting entities [acme-finance]
    # → acme-finance: full entry; acme: parentMode True, teamFiles[0]["team"] == "acme-finance"

def test_a_dormant_parent_is_not_queued_by_its_team(tmp_path): ...

def test_dormant_entities_and_missing_dossiers_are_skipped(tmp_path): ...
    # meeting entities [ghost] (no dossier) and [old] (dormant) → no entries, no crash

def test_notes_and_unconfirmed_meetings(tmp_path): ...
    # needs-review meeting does not queue; a type: note capture does not queue
```

Write each body fully with the helpers, following the comments; every assertion names the exact entry fields.

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Implement** `_entity_queue` and the two index additions. Call it at the end of `run()`, before the return, with a `try/except (ValueError, OSError)` per dossier that only warns.
- [ ] **Step 4:** Run `test_vaultlib_updatequeue.py` (all, the old tests too), `test_vaultlib_cli.py`; PASS.
- [ ] **Step 5: Commit** `feat(#273): update-queue lists entities with new material`.

---

### Task 3: process.md section D and the callers

**Files:** `plugin/skills/evening-sync/references/process.md`, `plugin/skills/evening-sync/SKILL.md` (stage 4 pointer + stage 7 summary), `plugin/skills/sync-recordings/SKILL.md` (step 9 lock release after D; step 11 summary), `plugin/skills/add/SKILL.md` (step 6 release after D; step 8 summary), `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Failing contract tests**

```python
def test_process_has_entity_updates_after_project_updates():
    text = read_ref("evening-sync", "process.md")
    assert text.index("## C. Project-state updates") < text.index("## D. Entity updates") < text.index("## Returns")
    d = text.split("## D. Entity updates", 1)[1].split("## Returns", 1)[0]
    for needle in ("entitiesNeedingUpdate", "entity write", "entity touch", "parentMode",
                   "(meeting · ", "(mail · ", "(session · ", "(note · ", "team)", "section C"):
        assert needle in d, needle
    assert "Dispatch in blocking batches of at most 3" not in d   # C's rule, referenced not copied


def test_on_demand_runs_release_the_lock_after_entity_updates():
    for skill, step in (("sync-recordings", "### 9. Process"), ("add", "### 6. Process")):
        text = read_skill(skill)
        part = text.split(step, 1)[1].split("###", 1)[0]
        assert "section D" in part and part.index("section D") < part.index("runlock release"), skill


def test_summaries_list_entity_pages_updated():
    for skill in ("evening-sync", "sync-recordings", "add"):
        assert "Entity pages updated" in read_skill(skill), skill
```

- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Write section D** (between C and Returns), following the spec's "The subagent" section: dispatch per entry (sonnet, in blocking batches exactly as section C's rule, referenced as "the same blocking batches of at most 3 as section C" without repeating the rule's sentence), the four-section instructions with the per-run limits (≤ 3 History, ≤ 3 Dynamics), source markers, parent mode, `entity write --slug S --edits "$SCRATCH/entity-edits-<slug>.payload.json"` then `entity touch --slug S --timestamp <now from dates plan or the run's clock line>`. Note that the timestamp comes from the CLI: use `vault`'s current minute via `entity touch` without `--timestamp`? No: pass the run's `state-updated`-style stamp. Simplest: make `--timestamp` optional in Task 1's CLI and default to now (ISO minute), as `reconcile-reviews` does. Do that and ledger it. Add the return shape and "a failure is a warning; the entity stays queued". Add to the Inputs table a row "Entity updates (D) | yes | yes", and to Returns "`entitiesUpdated`: `[{slug, written}]`".
  - **evening-sync:** stage 4's pointer reads "Follow sections C and D"; the stage 7 summary gains `**Entity pages updated:** {names} | none`.
  - **sync-recordings** step 9 and **add** step 6: "sections A, B, C and D", and move the lock release to after D. The summaries gain `**Entity pages updated:** …`.
- [ ] **Step 4:** Run `test_skill_contracts.py`, `test_template_prose.py` and `lint_plugin.py`; PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat(#273): entity pages update themselves every evening and on demand`.

---

### Task 4: Docs, end to end, final review, PR

- [ ] **CHANGELOG** (Unreleased):

```markdown
- **Entity pages update themselves**: every evening, and right away when you call the meeting sync or `/add`, each active entity with new meetings, mail, sessions or notes gets its Context, Relationship History, Dynamics and Sensitivities brought up to date — every line says where it came from, and nothing you wrote is removed. A team's page is updated in full; its parent's history gets the team's big events. (#273)
```

- [ ] **End to end** on a demo vault:
  - a confirmed meeting with an entity → `update-queue` lists the entity;
  - write a hand-made edits payload with `entity write`, then `entity touch`;
  - `update-queue` no longer lists it.
- [ ] **Final whole-branch review** (fresh reviewer, most capable model); fix Critical/Important test-first.
- [ ] **After #281 merges:** rebase onto main, bump the version, full suite, push, PR, then the CHANGELOG PR number and check. Report CI; never merge.
