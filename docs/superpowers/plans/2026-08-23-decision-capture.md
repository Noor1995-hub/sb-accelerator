# Decision Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the decision-note pattern (#20) and `/log-decision` (#36) — the
skill that produces decision notes in a validated foreground mode and an
unattended background mode the evening brief calls.

**Architecture:** Same as P1a — the model decides, the script writes. Judgment
(which candidates are material decisions, the title, the prose, whether an
explicit supersession exists) stays in `SKILL.md`; everything mechanical
(filenames, frontmatter, schema validation, collision detection, the two-sided
supersession edge, atomic writes) is a new `decision` group on
`plugin/lib/vaultlib/cli.py`. The ontology gains §Decision's missing half and is
recompiled to `schema.json`.

**Tech Stack:** Python 3.10+, standard library only at runtime. `pytest` +
`PyYAML` in tests only. Obsidian Bases YAML for `.base` views.

**Spec:** `docs/superpowers/specs/2026-08-23-decision-capture-design.md`
(read it before Task 1 — the plan argues from it, and its "Decisions" section is
the rationale for choices that otherwise look arbitrary).

## Global Constraints

- **Runtime is stdlib only.** Nothing under `plugin/lib/` may import `yaml` or
  any third-party package. Tests may.
- **Python 3.10 is the syntax floor.** CI runs 3.13 and 3.10; a 3.11+ construct
  fails only on a client machine.
- **Writes are UTF-8 with `newline="\n"`** — always via `vault.atomic_write`.
- **The vault root is always a parameter**, never inferred from a path shape.
- **Case-insensitive collision checks** — Linux inside Cowork's VM will create
  `Foo.md` and `foo.md`; the APFS or NTFS host underneath collapses them.
- **Clean-room rule.** Nothing in `plugin/` or `template/` may name a delaware
  client, a real person, or a busdev path. The only permitted "busdev" mention
  is `upstreamed-from: busdev@ccc27b8` in skill frontmatter.
- **Every commit message ends with the exact trailer:**
  `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Local verification = CI**, all four, from the worktree root:
  ```bash
  python3 scripts/lint_plugin.py
  python3 scripts/validate_template.py
  python3 scripts/compile_ontology.py --check
  python3 -m pytest scripts/tests -q
  ```
- **Never run `git checkout`, `git switch`, `git reset`, `git stash` or
  `git rebase` in this worktree.** Another session commits here concurrently and
  those commands orphan its work. To read a file at a commit use
  `git show <sha>:<path>`.
- **A fenced block containing another fenced block needs four backticks.** This
  plan uses them; preserve them when copying content out.

---

### Task 1: The decision pattern — ontology, base view, fixtures

Closes the #20 half. No runtime code: this task makes the pattern machine truth
and brings the fixtures onto it, so every later task has a schema to validate
against.

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md` (§Decision, lines 98–115)
- Modify: `template/30-projects/Decisions.base`
- Modify: `template/CLAUDE.md` (§Decision Notes)
- Modify: `plugin/lib/vaultlib/schema.json` (generated — never hand-edited)
- Modify: `scripts/compile_ontology.py:29`
- Modify: all four `fixtures/demo-vault/30-projects/*/decisions/*.md`
- Test: `scripts/tests/test_fixtures_ontology.py`, `scripts/tests/test_compile_ontology.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the compiled decision schema every later task validates against —
  `required: [type, project, date, status, summary]`,
  `optional: [supersedes, source]`, `keys_present: [reviewed]`,
  `enums: {type: [decision], status: [active, superseded, withdrawn]}`, and
  **no** `tags` key. Also the footer text
  `**Superseded** — {date} · replaced by [[{stem}]].` which Task 4 must emit
  byte-for-byte.

- [ ] **Step 1: Write the failing tests**

In `scripts/tests/test_compile_ontology.py`, append:

```python
def test_decision_carries_reviewed_and_no_tags_vocabulary():
    decision = co.compile_schema()["objects"]["decision"]
    assert decision["optional"] == ["supersedes", "source"]
    assert decision["keys_present"] == ["reviewed"]
    assert "tags" not in decision, (
        "decision tags were dropped in P1a decision 6 — a compiled key nothing "
        "validates is the silent-divergence shape the compiler exists to prevent"
    )


def test_carried_keys_are_exactly_what_the_runtime_validator_reads():
    # schema.validate() reads required / optional / keys_present / enums;
    # body_sections is read by schema.body_sections(). Anything else compiled
    # into schema.json affects nothing and will drift.
    assert set(co.CARRIED_KEYS) == {
        "required", "optional", "enums", "keys_present", "body_sections",
    }
```

In `scripts/tests/test_fixtures_ontology.py`: **delete** lines 79–81 (the
`_DECISION_TAGS` / `DECISION_TAGS_VOCABULARY` / `DECISION_TAGS_MAX` block — it
raises `KeyError` at import once `tags` is gone) and **delete**
`test_decision_tags_within_controlled_vocabulary` (lines 176–181). Then append:

```python
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
```

`ONTOLOGY_DOC.parents[2]` is `template/` (`ONTOLOGY_DOC` is
`template/99-workflow-config/reference/ontology.md`). `re` and `yaml` are
already imported at the top of that module.

- [ ] **Step 2: Run the tests and confirm they fail for the right reasons**

```bash
python3 -m pytest scripts/tests/test_compile_ontology.py scripts/tests/test_fixtures_ontology.py -q
```

Expected: the two new `test_compile_ontology` tests fail on the current
`optional`/`keys_present`/`tags` values and on `CARRIED_KEYS` still containing
`"tags"`; the fixture tests fail on missing `reviewed`, on `tags` still present,
and on the missing footer. If a test passes now, it is not testing anything —
fix it before continuing.

- [ ] **Step 3: Rewrite ontology.md §Decision**

Replace lines 98–115 of `template/99-workflow-config/reference/ontology.md` (from
the `### Decision — …` heading through the `- Example:` line, i.e. everything
before `### Entity`) with:

`````markdown
### Decision — `30-projects/{slug}/decisions/YYYY-MM-DD-{summary}.md` · Base: `Decisions.base`

```yaml
object: decision
required: [type, project, date, status, summary]
optional: [supersedes, source]
keys_present: [reviewed]
enums:
  type: [decision]
  status: [active, superseded, withdrawn]
```

- **Edges:** `supersedes` (`[[decision]]` / null) · `source` (`[[meeting]]`).
- Never deleted — status flips only. Supersession is a wikilink edge.
- `date` is the date the decision was **made**, not the date it was written
  down. It is what orders the decision log.
- `summary` is one full sentence — it is the Decision column in
  `Decisions.base`. The filename carries a *short* kebab label instead, because
  a slug of the summary sentence is a truncated paragraph.
- `reviewed` is the triage marker: `true` when a human validated the note as it
  was written, `false` when it was captured unattended. It is in
  `keys_present`, so the key always exists — `Decisions.base`'s **Needs review**
  view filters on `reviewed == false`, and a missing key would make that view
  silently incomplete. Same one-click convention as Meeting's `reviewed`.
- `source` names a note in `20-meetings/`. A decision drawn from an inbox
  transcript, a pasted paragraph or dictation carries no `source`; its
  provenance goes in the **Why** text.
- Example: `30-projects/acme-industries-operating-model/decisions/2026-05-20-single-vendor-strategy-adopted.md`

### Decision note template

Three bold markers, not H2 sections — so this object has no `body_sections`,
and the conformance guard checks the markers instead. One paragraph per marker.

```markdown
---
type: decision
project: acme-industries-operating-model
date: 2026-05-20
status: active
summary: "One sentence stating what was decided, specific enough to be useful without opening the note."
supersedes: "[[2026-03-10-prior-decision-stem]]"
source: "[[20-05-26-vendor-strategy-brainstorm]]"
reviewed: true
---

**Decision** — What was decided.

**Why** — The reasoning, including what was traded away.

**Implications** — What changes as a result: scope, dates, who does what.
```

Quoting `supersedes` and `source` is required, not house style: unquoted,
`[[x]]` is a nested YAML list, and the note's edges stop resolving silently.
Leave `supersedes:` empty (no value) when there is nothing superseded.

### Supersession procedure

A decision is superseded when a later decision **replaces** it — stated in
words, not inferred because two notes look inconsistent. One operation, three
effects, applied together:

1. The **new** note carries `supersedes: "[[{prior-stem}]]"`.
2. The **prior** note's `status` flips `active` → `superseded`. Nothing else in
   its frontmatter changes.
3. The **prior** note gains a footer, appended — never replacing prose:

   `**Superseded** — {YYYY-MM-DD} · replaced by [[{new-stem}]].`

   The date is the new decision's date. The footer exists so a reader of the old
   note can see what replaced it without running a query.

Only an `active` decision can be superseded: `superseded` and `withdrawn`
decisions were not in force, so replacing one is a category error — and in
practice that is what a stale or mistyped stem looks like. A decision that was
reversed rather than replaced is written `withdrawn` instead. **Never delete a
decision note** — the trace is the point.
`````

- [ ] **Step 4: Regenerate the compiled schema**

```bash
python3 scripts/compile_ontology.py
python3 scripts/compile_ontology.py --check
```

Expected: `wrote plugin/lib/vaultlib/schema.json`, then exit 0. Never hand-edit
`schema.json`.

- [ ] **Step 5: Drop `"tags"` from `CARRIED_KEYS`**

In `scripts/compile_ontology.py:29`:

```python
CARRIED_KEYS = ("required", "optional", "enums", "keys_present", "body_sections")
```

Re-run Step 4 (the value is unchanged either way now, but confirm `--check`
still exits 0).

- [ ] **Step 6: Rewrite `template/30-projects/Decisions.base`**

```yaml
filters:
  and:
    - file.inFolder("30-projects")
    - type == "decision"
formulas:
  open: link(file.path, "→")
properties:
  formula.open:
    displayName: " "
  summary:
    displayName: Decision
  project:
    displayName: Project
  date:
    displayName: Date
  status:
    displayName: Status
  reviewed:
    displayName: Reviewed
  supersedes:
    displayName: Supersedes
views:
  - type: table
    name: Active
    filters:
      and:
        - status == "active"
    order:
      - formula.open
      - summary
      - project
      - date
    sort:
      - property: date
        direction: DESC
  - type: table
    name: Needs review
    filters:
      and:
        - reviewed == false
    order:
      - formula.open
      - summary
      - project
      - date
      - status
    sort:
      - property: date
        direction: DESC
  - type: table
    name: All
    order:
      - formula.open
      - summary
      - project
      - date
      - status
      - reviewed
      - supersedes
    sort:
      - property: date
        direction: DESC
```

- [ ] **Step 7: Update `template/CLAUDE.md` §Decision Notes**

Replace the `### Decision Notes` paragraph with:

```markdown
### Decision Notes

Each material decision on a project is an atomic note at
`30-projects/{slug}/decisions/YYYY-MM-DD-{kebab-summary}.md`. Body:
`**Decision** — / **Why** — / **Implications**`. **Never delete a decision** —
status flips only (`active` → `superseded` / `withdrawn`). The trace is
permanent.

Superseding is one operation with two sides: `supersedes: "[[prior]]"` on the
new note **and** `status: superseded` on the prior one, which also gains a
`**Superseded** —` footer pointing forward. `/log-decision` does both; doing one
by hand leaves a half-edge.

`reviewed` says whether a human validated the note (`true`) or it was captured
unattended overnight (`false`). Decisions.base's **Needs review** view is the
queue; tick the checkbox there once you have read one.
```

- [ ] **Step 8: Bring the four decision fixtures onto the pattern**

`fixtures/demo-vault/30-projects/meridian-yard-automation-program/decisions/2026-05-20-single-vendor-strategy-adopted.md`
— drop `tags`, append `reviewed: true`:

```markdown
---
type: decision
project: meridian-yard-automation-program
date: 2026-05-20
status: active
summary: "Consolidate on a single automation vendor across all three yards to simplify integration and reduce total cost of ownership."
supersedes: "[[2026-03-10-phased-regional-rollout-adopted]]"
source: "[[20-05-26-meridian-vendor-strategy-brainstorm]]"
reviewed: true
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

`…/decisions/2026-03-10-phased-regional-rollout-adopted.md` — drop `tags`, add
`reviewed: true`, and replace the hand-written "superseded … see [[…]]" clause
with the deterministic footer. As it stands this fixture is a note no skill
could have produced:

```markdown
---
type: decision
project: meridian-yard-automation-program
date: 2026-03-10
status: superseded
summary: "Adopt a phased, multi-vendor rollout across three regional yards, starting with the highest-volume site."
supersedes:
source: "[[10-03-26-meridian-steerco-01]]"
reviewed: true
---

**Decision** — Roll out yard automation in three phases, one yard at a time,
using separate vendors selected per-site.

**Why** — Minimizes disruption at any single yard and lets each site's
integration team move at its own pace.

**Implications** — Three parallel vendor integrations to manage, each with its
own commissioning window and its own spares inventory.

**Superseded** — 2026-05-20 · replaced by [[2026-05-20-single-vendor-strategy-adopted]].
```

`fixtures/demo-vault/30-projects/nordbridge-regional-rollout-proposal/decisions/2026-03-02-pilot-site-selection-withdrawn.md`
— drop `tags`, add `reviewed: true`. Body unchanged.

`fixtures/demo-vault/30-projects/commercial-ops-crm-modernization/decisions/2026-06-01-vendor-shortlist-approved.md`
— drop `tags`, add `reviewed: false`. This is the fixture that demonstrates an
unattended capture, so the new **Needs review** view has a row. Body unchanged.

- [ ] **Step 9: Run the full local suite**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
python3 scripts/compile_ontology.py --check
python3 -m pytest scripts/tests -q
```

Expected: all four clean. `test_decision_status_enum_fully_covered` still passes
(active + superseded + withdrawn are all present across the four fixtures) and
`MINIMUMS["decision"] == 2` is still satisfied by four files.

- [ ] **Step 10: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md template/30-projects/Decisions.base template/CLAUDE.md plugin/lib/vaultlib/schema.json scripts/compile_ontology.py fixtures/demo-vault/30-projects scripts/tests/test_compile_ontology.py scripts/tests/test_fixtures_ontology.py
git commit -m "$(cat <<'MSG'
feat(template): decision-note pattern — reviewed marker, supersession procedure

Closes the #20 half. The ontology's Decision block gained the parts that
were only ever demonstrated in fixtures: the note template, the two-sided
supersession procedure, and a body-structure statement. `tags` is gone
(P1a decision 6) and so is the CARRIED_KEYS entry that compiled it into a
schema nothing validated.

New: `reviewed` in keys_present, the queryable audit marker background
captures write, plus the Decisions.base view that makes it actionable.

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: `decision list` — the read side and the canonical stem

The bare-stem boundary from spec decision 3 lands here, in the direction that
proves it: whatever `list` returns is what `write` accepts in Task 3.

**Files:**
- Create: `plugin/lib/vaultlib/decision.py`
- Modify: `plugin/lib/vaultlib/naming.py` (add `MAX_STEM_LENGTH`, give
  `validate_slug` a `max_length` parameter)
- Modify: `plugin/lib/vaultlib/cli.py` (the `decision` group, `list` action)
- Test: `scripts/tests/test_vaultlib_decision.py` (create),
  `scripts/tests/test_vaultlib_naming.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter`, `naming.validate_slug`,
  `naming.slugify`, `vault.resolve`, `schema.enum_values` (Task 3 onward).
- Produces:
  - `naming.MAX_STEM_LENGTH` (int, 71) and
    `naming.validate_slug(slug, max_length=naming.MAX_SLUG_LENGTH)`.
  - `decision.DecisionError`
  - `decision.canonical_stem(raw, *, field) -> str`
  - `decision.list_decisions(root, project) -> dict` with keys
    `project` and `decisions` (a list of dicts carrying `stem`, `path`, `date`,
    `status`, `summary`, `supersedes`, `source`, `reviewed`; or `stem`, `path`,
    `unreadable`).
  - `decision.DECISIONS_DIR`, `decision.PROJECTS_DIR`, `decision.MEETINGS_DIR`.
  - CLI: `decision list --vault V --project SLUG`.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_decision.py`:

```python
"""Decision notes.

The invariant these tests exist for: the wikilink syntax never crosses the CLI
boundary. Whatever `list_decisions` returns for `supersedes` or `source` must be
accepted verbatim by `write` — the property P1a's pipe-escaped table cells do
not have, and the reason that defect class recurred five times there.
"""
import pytest

from vaultlib import decision, markdown, naming

from test_vaultlib_vault import make_vault


def vault_with_project(tmp_path, slug="meridian-yard-automation-program"):
    """A vault carrying one project index and an empty decisions/ folder."""
    root = make_vault(tmp_path)
    folder = root / "30-projects" / slug
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(
        "---\ntype: project\nslug: " + slug + "\n---\n\n# Project\n",
        encoding="utf-8")
    return root


def add_meeting(root, stem="20-05-26-vendor-strategy-brainstorm"):
    (root / "20-meetings" / f"{stem}.md").write_text(
        "---\ntype: meeting\n---\n", encoding="utf-8")
    return stem


def write_note(root, project, stem, **fields):
    """Hand-place a decision note, so read-side tests do not depend on write()."""
    data = {"type": "decision", "project": project, "date": "2026-03-10",
            "status": "active", "summary": "A prior decision.",
            "supersedes": None, "source": None, "reviewed": True}
    data.update(fields)
    path = root / "30-projects" / project / "decisions" / f"{stem}.md"
    path.write_text(
        markdown.emit_frontmatter(data, decision.DECISION_QUOTE_KEYS)
        + "\n**Decision** — d.\n\n**Why** — w.\n\n**Implications** — i.\n",
        encoding="utf-8")
    return path


# --- canonical_stem -------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "2026-03-10-phased-regional-rollout-adopted",
    "[[2026-03-10-phased-regional-rollout-adopted]]",
    "  [[2026-03-10-phased-regional-rollout-adopted]]  ",
    "2026-03-10-phased-regional-rollout-adopted.md",
    "[[2026-03-10-phased-regional-rollout-adopted|The phased rollout]]",
    "[[2026-03-10-phased-regional-rollout-adopted.md]]",
])
def test_every_form_a_model_might_send_reduces_to_one_stem(raw):
    assert decision.canonical_stem(raw, field="supersedes") == (
        "2026-03-10-phased-regional-rollout-adopted")


@pytest.mark.parametrize("raw", [
    "30-projects/p/decisions/2026-03-10-x",
    "30-projects\\p\\2026-03-10-x",
    "../2026-03-10-x",
])
def test_a_path_is_refused_rather_than_resolved(raw):
    with pytest.raises(decision.DecisionError, match="bare note stem"):
        decision.canonical_stem(raw, field="supersedes")


@pytest.mark.parametrize("raw", ["", "   ", "[[]]", None])
def test_an_empty_stem_is_refused(raw):
    with pytest.raises(decision.DecisionError):
        decision.canonical_stem(raw, field="supersedes")


# `supersedes` and `source` fail identically, so the message has to say which.
def test_an_unusable_stem_names_the_field():
    with pytest.raises(decision.DecisionError, match="source"):
        decision.canonical_stem("Not A Stem", field="source")


def test_a_stem_longer_than_a_date_plus_a_full_slug_is_refused():
    too_long = "2026-03-10-" + ("a" * (naming.MAX_SLUG_LENGTH + 1))
    with pytest.raises(decision.DecisionError):
        decision.canonical_stem(too_long, field="supersedes")


def test_a_date_prefixed_stem_at_the_cap_is_accepted():
    # An object slug caps at 60; a decision stem is a date prefix plus one, so
    # validating it with the object cap would reject legal filenames.
    stem = "2026-03-10-" + ("a" * naming.MAX_SLUG_LENGTH)
    assert len(stem) == naming.MAX_STEM_LENGTH
    assert decision.canonical_stem(stem, field="supersedes") == stem


# --- list_decisions -------------------------------------------------------

def test_listing_a_project_with_no_decisions_is_empty_not_an_error(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.list_decisions(root, "meridian-yard-automation-program")
    assert result == {"project": "meridian-yard-automation-program",
                      "decisions": []}


def test_listing_a_project_without_a_decisions_folder_is_empty(tmp_path):
    root = vault_with_project(tmp_path)
    (root / "30-projects" / "meridian-yard-automation-program"
     / "decisions").rmdir()
    assert decision.list_decisions(
        root, "meridian-yard-automation-program")["decisions"] == []


def test_listing_an_unknown_project_points_at_new_project(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="/new-project"):
        decision.list_decisions(root, "no-such-project")


def test_list_returns_supersedes_and_source_as_bare_stems(tmp_path):
    project = "meridian-yard-automation-program"
    root = vault_with_project(tmp_path)
    write_note(root, project, "2026-03-10-phased-rollout-adopted",
               status="superseded")
    write_note(root, project, "2026-05-20-single-vendor-adopted",
               date="2026-05-20",
               supersedes="[[2026-03-10-phased-rollout-adopted]]",
               source="[[20-05-26-vendor-strategy-brainstorm]]",
               reviewed=False)
    entries = {e["stem"]: e
               for e in decision.list_decisions(root, project)["decisions"]}
    later = entries["2026-05-20-single-vendor-adopted"]
    assert later["supersedes"] == "2026-03-10-phased-rollout-adopted"
    assert later["source"] == "20-05-26-vendor-strategy-brainstorm"
    assert later["reviewed"] is False
    assert entries["2026-03-10-phased-rollout-adopted"]["supersedes"] is None


def test_list_sorts_newest_first(tmp_path):
    project = "meridian-yard-automation-program"
    root = vault_with_project(tmp_path)
    write_note(root, project, "2026-03-10-a")
    write_note(root, project, "2026-05-20-b", date="2026-05-20")
    write_note(root, project, "2026-01-04-c", date="2026-01-04")
    stems = [e["stem"]
             for e in decision.list_decisions(root, project)["decisions"]]
    assert stems == ["2026-05-20-b", "2026-03-10-a", "2026-01-04-c"]


def test_list_reports_an_unreadable_note_instead_of_raising(tmp_path):
    project = "meridian-yard-automation-program"
    root = vault_with_project(tmp_path)
    write_note(root, project, "2026-03-10-good")
    (root / "30-projects" / project / "decisions" / "hand-mangled.md"
     ).write_text("no frontmatter here\n", encoding="utf-8")
    entries = {e["stem"]: e
               for e in decision.list_decisions(root, project)["decisions"]}
    assert "unreadable" in entries["hand-mangled"]
    assert entries["2026-03-10-good"]["status"] == "active"
```

Append to `scripts/tests/test_vaultlib_naming.py`:

```python
def test_validate_slug_takes_a_caller_supplied_cap():
    long_stem = "2026-03-10-" + ("a" * naming.MAX_SLUG_LENGTH)
    with pytest.raises(ValueError, match="exceeds 60"):
        naming.validate_slug(long_stem)
    naming.validate_slug(long_stem, max_length=naming.MAX_STEM_LENGTH)


def test_max_stem_length_is_a_date_prefix_plus_a_full_slug():
    assert naming.MAX_STEM_LENGTH == len("YYYY-MM-DD-") + naming.MAX_SLUG_LENGTH
```

Check the import name at the top of `test_vaultlib_naming.py` first (it may be
`from vaultlib import naming` or `from vaultlib.naming import ...`) and match it.

Append to `scripts/tests/test_vaultlib_cli.py`:

```python
def test_decision_list_through_the_cli(capsys, tmp_path):
    from test_vaultlib_decision import vault_with_project, write_note
    root = vault_with_project(tmp_path)
    write_note(root, "meridian-yard-automation-program", "2026-03-10-a")
    code, payload = run(capsys, [
        "decision", "list", "--vault", str(root),
        "--project", "meridian-yard-automation-program",
    ])
    assert code == 0
    assert [e["stem"] for e in payload["result"]["decisions"]] == ["2026-03-10-a"]


def test_decision_list_on_an_unknown_project_is_a_structured_error(capsys, tmp_path):
    from test_vaultlib_decision import vault_with_project
    root = vault_with_project(tmp_path)
    code, payload = run(capsys, [
        "decision", "list", "--vault", str(root), "--project", "nope",
    ])
    assert code == 1
    assert payload["ok"] is False
    assert "/new-project" in payload["error"]
    assert payload["hint"]
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
python3 -m pytest scripts/tests/test_vaultlib_decision.py scripts/tests/test_vaultlib_naming.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named
'vaultlib.decision'`. That is the correct first failure.

- [ ] **Step 3: Give `naming.validate_slug` a caller-supplied cap**

In `plugin/lib/vaultlib/naming.py`, after `MAX_SLUG_LENGTH = 60`:

```python
# A decision or meeting note stem is a date prefix plus a title slug
# (`YYYY-MM-DD-{title}`), so it is legitimately longer than an object slug.
# Validating one against MAX_SLUG_LENGTH would reject legal filenames.
MAX_STEM_LENGTH = len("YYYY-MM-DD-") + MAX_SLUG_LENGTH
```

and change the signature and the length check:

```python
def validate_slug(slug: str, max_length: int = MAX_SLUG_LENGTH) -> None:
    """Raise ValueError if the slug is unusable as a folder or file stem."""
    if not slug:
        raise ValueError("slug is empty")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"slug {slug!r} must be lowercase alphanumeric segments joined by "
            "single hyphens, with no leading or trailing hyphen"
        )
    if len(slug) > max_length:
        raise ValueError(f"slug {slug!r} exceeds {max_length} characters")
    if slug in RESERVED_STEMS:
        raise ValueError(f"slug {slug!r} is a reserved filename on Windows")
```

Every existing caller passes one argument, so the default keeps them unchanged.

- [ ] **Step 4: Create `plugin/lib/vaultlib/decision.py` (read side)**

```python
"""Decision notes: the atomic record of a material decision on a project.

One rule runs through this module: **the wikilink syntax never crosses the CLI
boundary.** `supersedes` and `source` are taken and returned as bare note stems;
the `[[...]]` wrapping and its mandatory quoting exist only inside the file. A
caller that reads a stem out of `list_decisions` can pass that exact value back
into `write` — which is the property P1a's pipe-escaped table cells do not have,
and the reason that defect class recurred five times there.

Section shapes, the note template and the supersession procedure are the
contract in ontology.md §Decision.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import markdown, naming

PROJECTS_DIR = "30-projects"
DECISIONS_DIR = "decisions"
MEETINGS_DIR = "20-meetings"

# Quoting these three is a correctness requirement, not house style: unquoted,
# `[[x]]` is a nested YAML list. PyYAML reads [['x']] and this repo's stdlib
# parser reads the string "[x]" — a silent divergence between the two parsers
# the design keeps in agreement.
DECISION_QUOTE_KEYS = frozenset({"summary", "supersedes", "source"})

_WS_RUN_RE = re.compile(r"\s+")
_WIKILINK_RE = re.compile(r"\A\[\[(?P<target>[^\[\]|]+?)(?:\|[^\]]*)?\]\]\Z")


class DecisionError(Exception):
    """A decision argument or vault state the caller must fix."""


def canonical_stem(raw, *, field: str) -> str:
    """Reduce any form a model might send to the one canonical note stem.

    Accepts `stem`, `[[stem]]`, `[[stem|Alias]]` and `stem.md`, in any
    combination. Refuses anything carrying a path separator: a stem is a
    filename, and resolving a caller-supplied path would let a write escape its
    own project's folder.
    """
    text = _WS_RUN_RE.sub(" ", "" if raw is None else str(raw)).strip()
    match = _WIKILINK_RE.match(text)
    if match:
        text = match.group("target").strip()
    else:
        text = text.split("|", 1)[0].strip()
    if text[-3:].lower() == ".md":
        text = text[:-3].strip()
    if not text:
        raise DecisionError(f"{field} is empty (got {raw!r})")
    if "/" in text or "\\" in text:
        raise DecisionError(
            f"{field} {raw!r} looks like a path — pass the bare note stem, "
            "the filename without its .md extension "
            "(e.g. 2026-03-10-phased-regional-rollout-adopted)"
        )
    try:
        naming.validate_slug(text, max_length=naming.MAX_STEM_LENGTH)
    except ValueError as exc:
        raise DecisionError(
            f"{field} {raw!r} is not a usable note stem: {exc}"
        ) from exc
    return text


def _unwrap(value) -> Optional[str]:
    """Return the bare stem stored in a wikilink field, or None.

    The inverse of the `[[...]]` wrapping write() applies, and the only place
    that inverse exists — so a caller never has to know a transformation
    happened.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _WIKILINK_RE.match(text)
    return (match.group("target").strip() if match else text) or None


def _project_index(root: Path, project: str) -> Path:
    return root / PROJECTS_DIR / project / "index.md"


def _decisions_dir(root: Path, project: str) -> Path:
    return root / PROJECTS_DIR / project / DECISIONS_DIR


def _require_project(root: Path, project: str) -> None:
    try:
        naming.validate_slug(str(project or "").strip())
    except ValueError as exc:
        raise DecisionError(
            f"project {project!r} is not a project slug: {exc}"
        ) from exc
    if not _project_index(root, project).is_file():
        raise DecisionError(
            f"no project {project!r} at {PROJECTS_DIR}/{project}/index.md — "
            "create it first with /new-project"
        )


def _find_note(folder: Path, stem: str) -> Optional[Path]:
    """Case-insensitive stem lookup.

    Cowork's VM is Linux and will happily hold `Foo.md` and `foo.md`; the APFS
    or NTFS host underneath collapses them into one file.
    """
    if not folder.is_dir():
        return None
    lowered = stem.lower()
    for candidate in sorted(folder.glob("*.md")):
        if candidate.stem.lower() == lowered:
            return candidate
    return None


def list_decisions(root: Path, project: str) -> dict:
    """Every decision on a project, newest first.

    An unparseable note is reported rather than raised: one hand-mangled file
    must not make the skill unusable on that project.
    """
    _require_project(root, project)
    folder = _decisions_dir(root, project)
    entries = []
    paths = sorted(folder.glob("*.md")) if folder.is_dir() else []
    for path in paths:
        entry = {"stem": path.stem, "path": path.relative_to(root).as_posix()}
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            entry["unreadable"] = str(exc)
        else:
            entry.update({
                "date": data.get("date"),
                "status": data.get("status"),
                "summary": data.get("summary"),
                "supersedes": _unwrap(data.get("supersedes")),
                "source": _unwrap(data.get("source")),
                "reviewed": data.get("reviewed"),
            })
        entries.append(entry)
    entries.sort(key=lambda e: (str(e.get("date") or ""), e["stem"]),
                 reverse=True)
    return {"project": project, "decisions": entries}
```

- [ ] **Step 5: Wire `decision list` into the CLI**

In `plugin/lib/vaultlib/cli.py`, extend the import on line 33:

```python
from vaultlib import decision, entity, person, project, schema, vault  # noqa: E402
```

Add to `build_parser()`, after the `entity` group and before `return parser`:

```python
    decisions = top.add_parser("decision", help="decision notes")
    decisions_sub = decisions.add_subparsers(dest="action", required=True)

    dec_list = decisions_sub.add_parser(
        "list", help="print a project's decisions as JSON")
    _add_vault_argument(dec_list)
    dec_list.add_argument("--project", required=True, help="project slug")
```

Add to `_dispatch()`, before the final `raise AssertionError`:

```python
    if args.group == "decision":
        if args.action == "list":
            return _ok(decision.list_decisions(root, args.project))
```

Add to `main()`'s handler chain, next to the other domain errors:

```python
    except decision.DecisionError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
```

- [ ] **Step 6: Run the tests**

```bash
python3 -m pytest scripts/tests -q
```

Expected: all green. Fix real bugs rather than weakening a test; if a test looks
wrong, say so and stop.

- [ ] **Step 7: Commit**

```bash
git add plugin/lib/vaultlib/decision.py plugin/lib/vaultlib/naming.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_decision.py scripts/tests/test_vaultlib_naming.py scripts/tests/test_vaultlib_cli.py
git commit -m "$(cat <<'MSG'
feat(vaultlib): decision list, and one canonical note stem

`supersedes` and `source` cross the CLI boundary as bare stems in both
directions — canonical_stem() normalizes every form a model might send
([[x]], x.md, [[x|alias]]) and _unwrap() is the single inverse. That is
the countermeasure to P1a's transform-on-write/naive-match-on-read class,
not a note in a doc.

validate_slug() gains a max_length parameter: a decision stem is a date
prefix plus a title slug, so the object-slug cap would reject legal
filenames.

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: `decision write` — the note, without supersession

**Files:**
- Modify: `plugin/lib/vaultlib/decision.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_decision.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: everything Task 2 produced, plus `schema.validate`,
  `schema.enum_values`, `markdown.emit_frontmatter`, `vault.atomic_write`,
  `vault.today_iso`.
- Produces:
  - `decision.write(root, *, project, date, payload, reviewed) -> dict` with
    keys `stem`, `path`, `project`, `date`, `status`, `reviewed`, `supersedes`,
    `source`, `supersession` (always `None` until Task 4).
  - `decision.REQUIRED_NOTE_FIELDS`, `decision.OPTIONAL_NOTE_FIELDS`,
    `decision.BODY_MARKERS`, `decision.WRAP_WIDTH`.
  - CLI: `decision write --vault V --project SLUG [--date D] --note FILE
    (--foreground | --background)`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_decision.py`:

```python
import yaml  # test-only: the independent parser. decision.py imports no yaml.

NOTE = {
    "title": "single vendor strategy adopted",
    "summary": "Consolidate on a single automation vendor across all three "
               "yards to simplify integration and reduce total cost of "
               "ownership.",
    "decision": "Consolidate on a single automation vendor across all three "
                "yards.",
    "why": "Running three vendors' PLC and control software in parallel was "
           "creating integration overhead that outweighed the site-pacing "
           "benefit of the phased approach.",
    "implications": "The Phase 0 pilot vendor stays for yard 1; yards 2-3 "
                    "re-scope onto the same platform.",
}
PROJECT = "meridian-yard-automation-program"


def note(**overrides):
    payload = dict(NOTE)
    payload.update(overrides)
    return payload


def test_write_creates_the_note_at_date_plus_title_slug(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    assert result["stem"] == "2026-05-20-single-vendor-strategy-adopted"
    assert result["path"] == (
        f"30-projects/{PROJECT}/decisions/"
        "2026-05-20-single-vendor-strategy-adopted.md")
    assert (root / result["path"]).is_file()
    assert result["supersession"] is None


def test_the_filename_is_not_a_slug_of_the_summary_sentence(tmp_path):
    # A slug of `summary` is a truncated paragraph; `title` exists so the
    # filename stays readable.
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    assert "consolidate-on-a-single" not in result["stem"]


def test_frontmatter_conforms_and_keeps_its_declared_order(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=False)
    text = (root / result["path"]).read_text(encoding="utf-8")
    keys = [line.split(":", 1)[0]
            for line in text.split("---")[1].strip().split("\n")]
    assert keys == ["type", "project", "date", "status", "summary",
                    "supersedes", "source", "reviewed"]
    data, _ = markdown.split_frontmatter(text)
    assert data["reviewed"] is False
    assert data["status"] == "active"
    assert data["supersedes"] is None


def test_reviewed_records_which_mode_wrote_the_note(tmp_path):
    root = vault_with_project(tmp_path)
    fg = decision.write(root, project=PROJECT, date="2026-05-20",
                        payload=note(), reviewed=True)
    bg = decision.write(root, project=PROJECT, date="2026-05-21",
                        payload=note(title="second decision"), reviewed=False)
    assert markdown.split_frontmatter(
        (root / fg["path"]).read_text(encoding="utf-8"))[0]["reviewed"] is True
    assert markdown.split_frontmatter(
        (root / bg["path"]).read_text(encoding="utf-8"))[0]["reviewed"] is False


def test_the_body_carries_three_wrapped_bold_markers(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    body = (root / result["path"]).read_text(encoding="utf-8").split("---\n", 2)[2]
    assert body.startswith("\n**Decision** — ")
    assert "\n\n**Why** — " in body
    assert "\n\n**Implications** — " in body
    assert body.endswith("\n")
    assert all(len(line) <= decision.WRAP_WIDTH
               for line in body.split("\n")), "body prose must wrap"


def test_a_multi_line_body_field_becomes_one_paragraph(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(
        root, project=PROJECT, date="2026-05-20",
        payload=note(why="First line.\n\nSecond line."), reviewed=True)
    body = (root / result["path"]).read_text(encoding="utf-8")
    assert "**Why** — First line. Second line." in " ".join(body.split())


def test_source_is_stored_as_a_quoted_wikilink_to_the_meeting(tmp_path):
    root = vault_with_project(tmp_path)
    stem = add_meeting(root)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(source=stem), reviewed=True)
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert f'source: "[[{stem}]]"' in text
    assert result["source"] == stem


def test_a_source_that_matches_no_meeting_is_refused_with_the_alternative(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="omit 'source'"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(source="never-recorded-this"),
                       reviewed=True)


def test_a_source_given_as_a_wikilink_still_resolves(tmp_path):
    root = vault_with_project(tmp_path)
    stem = add_meeting(root)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(source=f"[[{stem}]]"), reviewed=True)
    assert result["source"] == stem


def test_a_withdrawn_decision_can_be_written_directly(tmp_path):
    root = vault_with_project(tmp_path)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(status="withdrawn"), reviewed=True)
    assert result["status"] == "withdrawn"


def test_a_note_cannot_be_written_as_superseded(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="supersedes"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(status="superseded"), reviewed=True)


def test_an_unknown_status_is_refused(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="not one of"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(status="pending"), reviewed=True)


def test_a_colliding_filename_is_refused_case_insensitively(tmp_path):
    root = vault_with_project(tmp_path)
    decision.write(root, project=PROJECT, date="2026-05-20", payload=note(),
                   reviewed=True)
    with pytest.raises(decision.DecisionError, match="already exists"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(title="Single Vendor Strategy Adopted"),
                       reviewed=True)


def test_an_unknown_payload_key_is_refused_not_ignored(tmp_path):
    # A typo'd `implication` that silently dropped a paragraph is the failure
    # nobody notices until a client reads the note.
    root = vault_with_project(tmp_path)
    payload = note()
    payload["implication"] = payload.pop("implications")
    with pytest.raises(decision.DecisionError, match="unknown payload key"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=payload, reviewed=True)


@pytest.mark.parametrize("field", list(NOTE))
def test_every_required_field_is_required(tmp_path, field):
    root = vault_with_project(tmp_path)
    payload = note()
    del payload[field]
    with pytest.raises(decision.DecisionError, match=field):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=payload, reviewed=True)


@pytest.mark.parametrize("value", [["a list"], {"a": "dict"}, 7, "", "   "])
def test_a_non_string_body_field_is_refused_not_stringified(tmp_path, value):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="why"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(why=value), reviewed=True)


@pytest.mark.parametrize("value", [["a list"], {"a": "dict"}, 7])
def test_a_non_string_optional_field_is_refused(tmp_path, value):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="source"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(source=value), reviewed=True)


def test_a_payload_that_is_not_an_object_is_refused(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="JSON object"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=[note()], reviewed=True)


def test_writing_to_an_unknown_project_points_at_new_project(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="/new-project"):
        decision.write(root, project="no-such-project", date="2026-05-20",
                       payload=note(), reviewed=True)


def test_the_decisions_folder_is_created_if_a_project_lacks_one(tmp_path):
    root = vault_with_project(tmp_path)
    (root / "30-projects" / PROJECT / "decisions").rmdir()
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(), reviewed=True)
    assert (root / result["path"]).is_file()


def test_a_title_that_slugifies_to_nothing_is_refused(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="title"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(title="!!! ???"), reviewed=True)


def test_pyyaml_reads_every_written_field_as_the_type_it_looks_like(tmp_path):
    """The independent-parser check. This repo keeps a stdlib frontmatter
    parser and PyYAML in agreement; an unquoted [[x]] is where they diverge."""
    root = vault_with_project(tmp_path)
    stem = add_meeting(root)
    result = decision.write(root, project=PROJECT, date="2026-05-20",
                            payload=note(source=stem), reviewed=False)
    text = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(text.split("---")[1])
    assert isinstance(data["source"], str), (
        "unquoted [[x]] parses as a nested list under PyYAML"
    )
    assert data["source"] == f"[[{stem}]]"
    assert data["reviewed"] is False
    assert str(data["date"]) == "2026-05-20"
```

Append to `scripts/tests/test_vaultlib_cli.py`:

```python
def test_decision_write_reads_its_payload_from_stdin(capsys, tmp_path, monkeypatch):
    import io
    import json as _json
    from test_vaultlib_decision import note, vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(note())))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--date", "2026-05-20", "--note", "-", "--background",
    ])
    assert code == 0
    assert out["result"]["reviewed"] is False


def test_decision_write_requires_a_mode(tmp_path):
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["decision", "write", "--vault", str(root),
                  "--project", PROJECT, "--note", "-"])


def test_decision_write_refuses_both_modes_at_once(tmp_path):
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["decision", "write", "--vault", str(root),
                  "--project", PROJECT, "--note", "-",
                  "--foreground", "--background"])


def test_foreground_mode_marks_the_note_reviewed(capsys, tmp_path, monkeypatch):
    import io
    import json as _json
    from test_vaultlib_decision import note, vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(note())))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--date", "2026-05-20", "--note", "-", "--foreground",
    ])
    assert code == 0
    assert out["result"]["reviewed"] is True


def test_a_malformed_decision_payload_is_a_structured_error(capsys, tmp_path, monkeypatch):
    import io
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"title": "only a title"}'))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--note", "-", "--background",
    ])
    assert code == 1
    assert out["ok"] is False
    assert out["error"].strip()
    assert out["hint"].strip()


def test_a_decision_payload_that_is_not_json_is_a_structured_error(
        capsys, tmp_path, monkeypatch):
    import io
    from test_vaultlib_decision import vault_with_project, PROJECT
    root = vault_with_project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code, out = run(capsys, [
        "decision", "write", "--vault", str(root), "--project", PROJECT,
        "--note", "-", "--background",
    ])
    assert code == 1
    assert "not valid JSON" in out["error"]
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
python3 -m pytest scripts/tests/test_vaultlib_decision.py -q
```

Expected: `AttributeError: module 'vaultlib.decision' has no attribute 'write'`.

- [ ] **Step 3: Add the write side to `decision.py`**

Extend the imports at the top of the module:

```python
import re
import textwrap
from pathlib import Path
from typing import Optional

from . import markdown, naming, schema, vault
```

Add the constants beside the existing ones:

```python
BODY_MARKERS = ("Decision", "Why", "Implications")
WRAP_WIDTH = 76

REQUIRED_NOTE_FIELDS = ("title", "summary", "decision", "why", "implications")
OPTIONAL_NOTE_FIELDS = ("status", "source", "supersedes")
```

Then append:

```python
def _collapse(value, field: str) -> str:
    """One line, single-spaced. Frontmatter is line-based and the body's bold
    markers are paragraph-delimited, so an embedded newline in either place
    changes the file's structure rather than its text."""
    text = _WS_RUN_RE.sub(" ", "" if value is None else str(value)).strip()
    if not text:
        raise DecisionError(f"payload field {field!r} is empty")
    return text


def _validate_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise DecisionError(
            "the note payload must be a JSON object with the keys "
            f"{list(REQUIRED_NOTE_FIELDS)}"
        )
    unknown = sorted(set(payload) - set(REQUIRED_NOTE_FIELDS)
                     - set(OPTIONAL_NOTE_FIELDS))
    if unknown:
        raise DecisionError(
            f"unknown payload key(s) {unknown} — expected "
            f"{list(REQUIRED_NOTE_FIELDS + OPTIONAL_NOTE_FIELDS)}. A misspelled "
            "key would otherwise drop its content silently."
        )
    for field in REQUIRED_NOTE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DecisionError(
                f"payload field {field!r} must be a non-empty string "
                f"(got {type(value).__name__})"
            )
    for field in OPTIONAL_NOTE_FIELDS:
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise DecisionError(
                f"payload field {field!r} must be a string or absent "
                f"(got {type(value).__name__})"
            )
    return payload


def _validated_status(payload: dict) -> str:
    status = (payload.get("status") or "active").strip()
    allowed = schema.enum_values("decision", "status")
    if status not in allowed:
        raise DecisionError(f"status {status!r} is not one of {allowed}")
    if status == "superseded":
        raise DecisionError(
            "a note cannot be written as 'superseded' — that status is set on "
            "the *prior* note by writing the decision that replaces it. Pass "
            "the prior note's stem as 'supersedes' and write this one 'active'."
        )
    return status


def _title_slug(title: str) -> str:
    try:
        slug = naming.slugify(_collapse(title, "title"))
        naming.validate_slug(slug)
    except ValueError as exc:
        raise DecisionError(f"payload field 'title' is unusable: {exc}") from exc
    return slug


def _resolve_source(root: Path, raw: Optional[str]) -> Optional[str]:
    """Return the on-disk stem of the meeting this decision came from.

    The ontology types the edge as [[meeting]], and a source pointing at
    nothing is a silent data-quality defect — so it is verified. Decisions drawn
    from an inbox transcript or from dictation carry no source; their provenance
    goes in the Why prose.
    """
    if raw is None or not str(raw).strip():
        return None
    stem = canonical_stem(raw, field="source")
    found = _find_note(root / MEETINGS_DIR, stem)
    if found is None:
        raise DecisionError(
            f"source {stem!r} matches no meeting note at "
            f"{MEETINGS_DIR}/{stem}.md — omit 'source' and put the provenance "
            "in the 'why' text, or create the meeting note first"
        )
    return found.stem


def _render_body(decision_text: str, why: str, implications: str) -> str:
    paragraphs = [
        textwrap.fill(f"**{marker}** — {text}", width=WRAP_WIDTH,
                      break_long_words=False, break_on_hyphens=False)
        for marker, text in zip(BODY_MARKERS,
                                (decision_text, why, implications))
    ]
    return "\n" + "\n\n".join(paragraphs) + "\n"


def write(root: Path, *, project: str, date: str, payload: dict,
          reviewed: bool) -> dict:
    """Write one decision note, applying any supersession edge.

    `reviewed` is the mode: True from /log-decision's foreground mode, where a
    human validated this note as it was written; False from background mode.
    """
    _require_project(root, project)
    payload = _validate_payload(payload)

    stem = f"{date}-{_title_slug(payload['title'])}"
    try:
        naming.validate_slug(stem, max_length=naming.MAX_STEM_LENGTH)
    except ValueError as exc:
        raise DecisionError(
            f"the filename {stem!r} is unusable: {exc}. Shorten 'title'."
        ) from exc

    folder = _decisions_dir(root, project)
    clash = _find_note(folder, stem)
    if clash is not None:
        raise DecisionError(
            f"a decision note already exists at "
            f"{clash.relative_to(root).as_posix()} — pick a different title, or "
            f"run `decision list --project {project}` to see what is recorded"
        )

    status = _validated_status(payload)
    source = _resolve_source(root, payload.get("source"))

    frontmatter = {
        "type": "decision",
        "project": project,
        "date": date,
        "status": status,
        "summary": _collapse(payload["summary"], "summary"),
        "supersedes": None,
        "source": f"[[{source}]]" if source else None,
        "reviewed": reviewed,
    }
    problems = schema.validate("decision", frontmatter)
    if problems:
        raise DecisionError(
            "refusing to write non-conformant decision frontmatter: "
            + "; ".join(problems)
        )

    body = _render_body(_collapse(payload["decision"], "decision"),
                        _collapse(payload["why"], "why"),
                        _collapse(payload["implications"], "implications"))
    target = folder / f"{stem}.md"
    vault.atomic_write(
        target,
        markdown.emit_frontmatter(frontmatter, DECISION_QUOTE_KEYS) + body,
    )

    return {
        "stem": stem,
        "path": target.relative_to(root).as_posix(),
        "project": project,
        "date": date,
        "status": status,
        "reviewed": reviewed,
        "supersedes": None,
        "source": source,
        "supersession": None,
    }
```

- [ ] **Step 4: Wire `decision write` into the CLI**

In `build_parser()`, after `dec_list`:

```python
    dec_write = decisions_sub.add_parser(
        "write", help="write a decision note, applying any supersession edge")
    _add_vault_argument(dec_write)
    dec_write.add_argument("--project", required=True, help="project slug")
    dec_write.add_argument(
        "--date", help="ISO date the decision was MADE; defaults to today")
    dec_write.add_argument("--note", required=True,
                           help="path to a JSON file, or - to read stdin")
    # No default: the mode decides what goes into the `reviewed` audit field,
    # and a wrong default writes a lie into it.
    mode = dec_write.add_mutually_exclusive_group(required=True)
    mode.add_argument("--foreground", action="store_true",
                      help="a human validated this inline; writes reviewed: true")
    mode.add_argument("--background", action="store_true",
                      help="unattended capture; writes reviewed: false")
```

In `_dispatch()`, extend the `decision` branch:

```python
    if args.group == "decision":
        if args.action == "list":
            return _ok(decision.list_decisions(root, args.project))
        payload = (json.load(sys.stdin) if args.note == "-"
                   else json.loads(Path(args.note).read_text(encoding="utf-8")))
        return _ok(decision.write(
            root, project=args.project, date=vault.today_iso(args.date),
            payload=payload, reviewed=args.foreground,
        ))
```

`reviewed=args.foreground` is the whole mapping: the group is required and
mutually exclusive, so exactly one flag is set.

Finally, generalize the `JSONDecodeError` hint in `main()` — it currently names
entity sections and is now shared with `decision write`:

```python
    except json.JSONDecodeError as exc:
        return _fail(f"payload is not valid JSON: {exc}",
                     "Pass a JSON object in a file, or - to read stdin.")
```

Check `scripts/tests/test_vaultlib_cli.py` for the existing assertion on that
message (`"not valid JSON" in out["error"]`) — it still matches.

- [ ] **Step 5: Run the tests**

```bash
python3 -m pytest scripts/tests -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/decision.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_decision.py scripts/tests/test_vaultlib_cli.py
git commit -m "$(cat <<'MSG'
feat(vaultlib): decision write

The note itself: filename from date + a short title (never a slug of the
summary sentence), schema-validated frontmatter in declared key order,
three wrapped bold markers, source verified against 20-meetings/.

Mode is a required mutually-exclusive flag pair, --foreground or
--background, because it decides what goes into the `reviewed` audit
field and a default would write a lie into it. Refuses writing a note as
'superseded' — that status belongs to the prior note.

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 4: The two-sided supersession edge

The spec's decision 4 and the defect-class countermeasure, together. The
round-trip test in Step 1 is the one that matters: it feeds a value that came
*out* of `decision list` back *into* `decision write`.

**Files:**
- Modify: `plugin/lib/vaultlib/decision.py`
- Test: `scripts/tests/test_vaultlib_decision.py`

**Interfaces:**
- Consumes: Task 3's `write`, `markdown.replace_scalar_field`.
- Produces: `decision.SUPERSEDED_FOOTER` (the format string, `{date}` and
  `{stem}`), and `write`'s `supersession` result value —
  `None`, or `{"stem", "path", "status_flipped", "footer_added"}` plus an
  `"error"` key when the new note landed but the flip did not.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_decision.py`:

```python
def write_prior(root, date="2026-03-10", title="phased regional rollout adopted"):
    return decision.write(root, project=PROJECT, date=date,
                          payload=note(title=title), reviewed=True)


def test_supersession_sets_both_sides_and_appends_a_footer(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    later = decision.write(
        root, project=PROJECT, date="2026-05-20",
        payload=note(supersedes=prior["stem"]), reviewed=True)

    new_text = (root / later["path"]).read_text(encoding="utf-8")
    assert f'supersedes: "[[{prior["stem"]}]]"' in new_text

    prior_text = (root / prior["path"]).read_text(encoding="utf-8")
    prior_fm, _ = markdown.split_frontmatter(prior_text)
    assert prior_fm["status"] == "superseded"
    assert prior_text.rstrip("\n").endswith(
        decision.SUPERSEDED_FOOTER.format(date="2026-05-20",
                                          stem=later["stem"]))
    assert later["supersession"] == {
        "stem": prior["stem"], "path": prior["path"],
        "status_flipped": True, "footer_added": True,
    }


def test_the_flip_changes_status_and_nothing_else(tmp_path):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    before = (root / prior["path"]).read_text(encoding="utf-8")
    later = decision.write(root, project=PROJECT, date="2026-05-20",
                           payload=note(supersedes=prior["stem"]),
                           reviewed=True)
    after = (root / prior["path"]).read_text(encoding="utf-8")
    footer = decision.SUPERSEDED_FOOTER.format(date="2026-05-20",
                                               stem=later["stem"])
    assert after == before.replace("status: active", "status: superseded",
                                   1).rstrip("\n") + "\n\n" + footer + "\n"


def test_the_stem_list_returns_is_the_stem_write_accepts(tmp_path):
    """The round trip, in the direction the P1a defect class breaks.

    Take `supersedes` straight out of `decision list` and feed it back to
    `write`. It must fail because that decision is already superseded — the
    domain reason — and never with a mangled-path or not-found error, which is
    what a double-wrapped `[[[[x]]]]` produces.
    """
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    decision.write(root, project=PROJECT, date="2026-05-20",
                   payload=note(supersedes=prior["stem"]), reviewed=True)

    listed = {e["stem"]: e
              for e in decision.list_decisions(root, PROJECT)["decisions"]}
    round_tripped = listed["2026-05-20-single-vendor-strategy-adopted"]["supersedes"]
    assert round_tripped == prior["stem"]

    with pytest.raises(decision.DecisionError, match="not 'active'"):
        decision.write(root, project=PROJECT, date="2026-06-01",
                       payload=note(title="third decision",
                                    supersedes=round_tripped),
                       reviewed=True)


@pytest.mark.parametrize("form", ["{stem}", "[[{stem}]]", "{stem}.md",
                                  "[[{stem}|An alias]]"])
def test_every_wikilink_form_resolves_to_the_same_prior_note(tmp_path, form):
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    later = decision.write(
        root, project=PROJECT, date="2026-05-20",
        payload=note(supersedes=form.format(stem=prior["stem"])),
        reviewed=True)
    assert later["supersession"]["stem"] == prior["stem"]
    text = (root / later["path"]).read_text(encoding="utf-8")
    assert text.count("[[") == 1, "the wrapping must not accumulate"


def test_superseding_a_missing_note_names_decision_list(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="decision list"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes="2026-01-01-never-existed"),
                       reviewed=True)


def test_nothing_is_written_when_the_supersession_target_is_bad(tmp_path):
    """Preconditions run before the new note is written, so a bad edge leaves
    no half-applied state."""
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes="2026-01-01-never-existed"),
                       reviewed=True)
    assert decision.list_decisions(root, PROJECT)["decisions"] == []


def test_a_withdrawn_decision_cannot_be_superseded(tmp_path):
    root = vault_with_project(tmp_path)
    prior = decision.write(root, project=PROJECT, date="2026-03-10",
                           payload=note(title="withdrawn thing",
                                        status="withdrawn"),
                           reviewed=True)
    with pytest.raises(decision.DecisionError, match="not 'active'"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes=prior["stem"]), reviewed=True)


def test_a_decision_cannot_supersede_itself(tmp_path):
    root = vault_with_project(tmp_path)
    with pytest.raises(decision.DecisionError, match="supersede itself"):
        decision.write(
            root, project=PROJECT, date="2026-05-20",
            payload=note(supersedes="2026-05-20-single-vendor-strategy-adopted"),
            reviewed=True)


def test_a_decision_in_another_project_cannot_be_superseded(tmp_path):
    root = vault_with_project(tmp_path)
    other = "commercial-ops-crm-modernization"
    folder = root / "30-projects" / other
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(
        f"---\ntype: project\nslug: {other}\n---\n", encoding="utf-8")
    elsewhere = decision.write(root, project=other, date="2026-03-10",
                               payload=note(title="their decision"),
                               reviewed=True)
    with pytest.raises(decision.DecisionError, match="matches no decision"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes=elsewhere["stem"]),
                       reviewed=True)


def test_a_prior_note_with_unreadable_frontmatter_is_a_clean_refusal(tmp_path):
    root = vault_with_project(tmp_path)
    (root / "30-projects" / PROJECT / "decisions" / "2026-03-10-mangled.md"
     ).write_text("no frontmatter\n", encoding="utf-8")
    with pytest.raises(decision.DecisionError, match="cannot be read"):
        decision.write(root, project=PROJECT, date="2026-05-20",
                       payload=note(supersedes="2026-03-10-mangled"),
                       reviewed=True)


def test_a_failed_flip_reports_a_one_sided_edge_rather_than_success(
        tmp_path, monkeypatch):
    """The new note is written first on purpose: flipping first and failing to
    write would leave a superseded decision with no successor, which no reader
    can diagnose. This asserts the surviving failure is reported, not hidden."""
    root = vault_with_project(tmp_path)
    prior = write_prior(root)
    real_write = decision.vault.atomic_write
    calls = {"n": 0}

    def flaky(path, text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("read-only file system")
        return real_write(path, text)

    monkeypatch.setattr(decision.vault, "atomic_write", flaky)
    later = decision.write(root, project=PROJECT, date="2026-05-20",
                           payload=note(supersedes=prior["stem"]),
                           reviewed=True)
    assert (root / later["path"]).is_file(), "the new note must survive"
    assert later["supersession"]["status_flipped"] is False
    assert "one-sided" in later["supersession"]["error"]
    prior_fm, _ = markdown.split_frontmatter(
        (root / prior["path"]).read_text(encoding="utf-8"))
    assert prior_fm["status"] == "active"


def test_the_fixture_footer_matches_what_the_code_writes(tmp_path):
    """Binds the demo vault to the implementation. test_fixtures_ontology.py
    deliberately does not import plugin runtime code, so without this the
    fixture's footer and SUPERSEDED_FOOTER can drift apart silently."""
    from pathlib import Path as _Path
    repo = _Path(__file__).resolve().parents[2]
    fixture = (repo / "fixtures" / "demo-vault" / "30-projects"
               / "meridian-yard-automation-program" / "decisions"
               / "2026-03-10-phased-regional-rollout-adopted.md")
    expected = decision.SUPERSEDED_FOOTER.format(
        date="2026-05-20",
        stem="2026-05-20-single-vendor-strategy-adopted")
    assert expected in fixture.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
python3 -m pytest scripts/tests/test_vaultlib_decision.py -q
```

Expected: `AttributeError: module 'vaultlib.decision' has no attribute
'SUPERSEDED_FOOTER'` at collection, then supersession failures.

- [ ] **Step 3: Add the footer constant and the supersession planner**

Beside the other constants in `decision.py`:

```python
# Both sides of the edge are written together; this footer is the reverse
# direction, appended so a reader of the old note sees what replaced it without
# running a query. Append-only — the prior note's prose is never rewritten.
SUPERSEDED_FOOTER = "**Superseded** — {date} · replaced by [[{stem}]]."
```

Then, above `write`:

```python
def _plan_supersession(root: Path, project: str, raw: Optional[str],
                       new_stem: str, date: str) -> Optional[dict]:
    """Resolve and validate the prior note and precompute its new text.

    Every precondition is checked here, before the new note is written, so a
    caller that gets past this function has a supersession that can only fail
    on I/O.
    """
    if raw is None or not str(raw).strip():
        return None
    stem = canonical_stem(raw, field="supersedes")
    if stem.lower() == new_stem.lower():
        raise DecisionError(
            "a decision cannot supersede itself — 'supersedes' names the "
            "*prior* decision this one replaces"
        )
    found = _find_note(_decisions_dir(root, project), stem)
    if found is None:
        raise DecisionError(
            f"supersedes {stem!r} matches no decision in "
            f"{PROJECTS_DIR}/{project}/{DECISIONS_DIR}/ — run "
            f"`decision list --project {project}` and pass a stem from it"
        )
    text = found.read_text(encoding="utf-8")
    try:
        data, _ = markdown.split_frontmatter(text)
    except ValueError as exc:
        raise DecisionError(
            f"{found.relative_to(root).as_posix()} cannot be read as a "
            f"decision note: {exc}"
        ) from exc
    prior_status = data.get("status")
    if prior_status != "active":
        held = (f"has status {prior_status!r}" if prior_status
                else "carries no status field")
        raise DecisionError(
            f"decision {found.stem!r} {held}, not 'active' — only a decision "
            "that is in force can be superseded. A decision that was reversed "
            "rather than replaced is written 'withdrawn' instead."
        )
    updated = markdown.replace_scalar_field(text, "status", "superseded")
    footer = SUPERSEDED_FOOTER.format(date=date, stem=new_stem)
    return {
        "stem": found.stem,
        "path": found.relative_to(root).as_posix(),
        "target": found,
        "text": updated.rstrip("\n") + "\n\n" + footer + "\n",
    }
```

- [ ] **Step 4: Apply the edge in `write`**

Replace the `source = _resolve_source(...)` line and everything after it, up to
the `return`, with:

```python
    status = _validated_status(payload)
    source = _resolve_source(root, payload.get("source"))
    supersession = _plan_supersession(root, project, payload.get("supersedes"),
                                      stem, date)

    frontmatter = {
        "type": "decision",
        "project": project,
        "date": date,
        "status": status,
        "summary": _collapse(payload["summary"], "summary"),
        "supersedes": f"[[{supersession['stem']}]]" if supersession else None,
        "source": f"[[{source}]]" if source else None,
        "reviewed": reviewed,
    }
    problems = schema.validate("decision", frontmatter)
    if problems:
        raise DecisionError(
            "refusing to write non-conformant decision frontmatter: "
            + "; ".join(problems)
        )

    body = _render_body(_collapse(payload["decision"], "decision"),
                        _collapse(payload["why"], "why"),
                        _collapse(payload["implications"], "implications"))
    target = folder / f"{stem}.md"
    vault.atomic_write(
        target,
        markdown.emit_frontmatter(frontmatter, DECISION_QUOTE_KEYS) + body,
    )

    result = {
        "stem": stem,
        "path": target.relative_to(root).as_posix(),
        "project": project,
        "date": date,
        "status": status,
        "reviewed": reviewed,
        "supersedes": supersession["stem"] if supersession else None,
        "source": source,
        "supersession": None,
    }
    if supersession is not None:
        applied = {
            "stem": supersession["stem"], "path": supersession["path"],
            "status_flipped": False, "footer_added": False,
        }
        try:
            vault.atomic_write(supersession["target"], supersession["text"])
        except OSError as exc:
            # The new note is on disk. Say so plainly: a caller told "ok" while
            # the prior note still reads `active` has no way to notice.
            applied["error"] = (
                f"the new note was written, but {supersession['path']} could "
                f"not be updated: {exc}. Its status is still 'active', so the "
                "edge is one-sided until that is fixed."
            )
        else:
            applied["status_flipped"] = True
            applied["footer_added"] = True
        result["supersession"] = applied
    return result
```

- [ ] **Step 5: Run everything**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
python3 scripts/compile_ontology.py --check
python3 -m pytest scripts/tests -q
```

Expected: all four clean.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/decision.py scripts/tests/test_vaultlib_decision.py
git commit -m "$(cat <<'MSG'
feat(vaultlib): the two-sided supersession edge

One operation, three effects: `supersedes` on the new note, the prior
note's status flip, and an append-only **Superseded** footer pointing
forward. Preconditions are checked before any byte is written, and the
new note is written before the flip — a failed flip leaves a recoverable
one-sided edge the result reports, where flipping first would leave a
superseded decision with no successor.

The regression test that matters takes `supersedes` straight out of
`decision list` and feeds it back to `write`: it must fail on the domain
reason ("not 'active'"), never on a mangled path.

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

### Task 5: `/log-decision`, and the release surface

**Files:**
- Create: `plugin/skills/log-decision/SKILL.md`
- Modify: `plugin/CLAUDE.md`
- Modify: `plugin/.claude-plugin/plugin.json`
- Modify: `CHANGELOG.md`
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: `decision list` and `decision write` exactly as Tasks 2–4 defined
  them. Every subcommand named in the SKILL must exist — `test_skill_contracts`
  introspects the parser to check.
- Produces: the skill `/log-decision` and its `--background` mode, which #16's
  evening run invokes.

- [ ] **Step 1: Write the failing tests**

In `scripts/tests/test_skill_contracts.py`, change `test_expected_skills_exist`:

```python
def test_expected_skills_exist():
    # Each skill task appends its own name here as it lands, so this test is
    # always satisfiable by the task that touches it.
    names = {path.parent.name for path in SKILL_FILES}
    assert {"new-project", "update-entity", "log-decision"} <= names
```

and append:

```python
def test_log_decision_documents_both_modes():
    text = (SKILLS_DIR / "log-decision" / "SKILL.md").read_text(encoding="utf-8")
    assert "--foreground" in text and "--background" in text, (
        "the mode flag is the interface #16's evening run calls; both halves "
        "have to be written down"
    )


def test_log_decision_forbids_prompting_in_background_mode():
    # The lab's production failure: an unattended run that asks a question
    # exits having done nothing.
    text = (SKILLS_DIR / "log-decision" / "SKILL.md").read_text(encoding="utf-8")
    assert "never ask" in text.lower() or "never prompt" in text.lower(), (
        "background mode must state that it never blocks on a prompt"
    )


def test_plugin_claude_md_documents_the_bare_stem_boundary():
    text = (REPO_ROOT / "plugin" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "bare" in text.lower() and "supersedes" in text, (
        "the wikilink-never-crosses-the-boundary rule belongs next to the "
        "pipe-escaping rule — they are the same lesson twice"
    )
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
python3 -m pytest scripts/tests/test_skill_contracts.py -q
```

Expected: failures on the missing skill directory and the missing
`plugin/CLAUDE.md` section.

- [ ] **Step 3: Create `plugin/skills/log-decision/SKILL.md`**

`````markdown
---
name: log-decision
description: Extract material decisions from a meeting note, transcript, or description and write them as atomic decision notes on a project, setting both sides of any supersession edge. Triggers when the user invokes /log-decision or asks to record, log, or capture a decision.
user_invocable: true
upstreamed-from: busdev@ccc27b8
---

# Log Decision

Turn a source into atomic decision notes on a project. You decide what counts
as a decision and what it supersedes; the CLI writes the notes and maintains
both sides of every supersession edge.

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat — plugins are not loaded there. Say so
plainly rather than hand-writing a decision note.

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

The JSON envelope and interpreter resolution are documented in the plugin's
`CLAUDE.md`. Read `ok` on every call; on failure show the `error` and `hint`
rather than retrying blind or writing the file by hand.

## Usage

```
/log-decision
/log-decision meridian-yard-automation-program
/log-decision meridian-yard-automation-program --background
```

**Foreground** (the default) proposes each candidate and waits for the user.
**Background** never prompts — it is what the evening run calls, and it marks
what it writes `reviewed: false` for later audit.

## What counts as a decision

The test both modes apply, and the reason the decision log stays worth reading:
a candidate qualifies only if it **commits the engagement** *and* **would change
a stakeholder's behaviour**.

| Not a decision | Why |
|---|---|
| "Omar will send the scoring sheet" | A task. It belongs in the project's Open Items. |
| "Leo thinks the yard-2 timeline is tight" | An opinion. Record it in the dossier's Sensitivities if it matters. |
| "We'll meet again on the 14th" | Scheduling. |
| "We prefer the phased approach" | A preference, until something is committed. |
| Anything already in `decision list` | A restatement. Say so and move on. |

**Writing nothing is a valid outcome.** If the source carries no material
decision, say what you read, say why none of it earned a note, and stop. A
fabricated entry to justify the invocation is the failure mode this skill has to
avoid.

## Workflow

### 1. Identify the project

If no slug was given, list what exists and ask:

```bash
ls "$VAULT/30-projects"
```

The project must already exist — `decision write` refuses otherwise and points
at `/new-project`. Do not create a project just to hold a decision; ask.

### 2. Read what is already recorded

```bash
python3 "$VAULTLIB" decision list --vault "$VAULT" --project <slug>
```

You get every decision on the project, newest first: `stem`, `date`, `status`,
`summary`, `supersedes`, `source`, `reviewed`. **Read this before extracting.**
It is what lets you recognise a restatement, and it is where any supersession
candidate comes from.

`supersedes` and `source` come back as **bare stems**
(`2026-03-10-phased-rollout-adopted`), which is exactly the form `decision
write` takes. Pass them back as they came — do not add `[[…]]`.

An entry carrying `unreadable` is a hand-mangled file. Mention it once and work
around it; do not try to repair it here.

### 3. Get the source

In foreground mode, if the user has not already provided it:

> What should I read? Paste the notes, point me at a file, or just tell me what
> was decided.

Accept any of three forms: pasted text, a file anywhere in the vault (inbox
captures live in `10-inbox/`, meeting notes in `20-meetings/`), or a spoken
description. In background mode the source is handed to you by the caller.

### 4. Extract candidates

For each candidate, decide:

- **`title`** — a short kebab-able label, three to six words. This becomes the
  filename after the date: `2026-05-20-single-vendor-strategy-adopted`. Do not
  reuse the summary sentence; a slug of it is a truncated paragraph.
- **`summary`** — one full sentence, specific enough to be useful in a table
  without opening the note. This is the Decision column in `Decisions.base`.
- **`decision` / `why` / `implications`** — one paragraph each. `why` includes
  what was traded away; `implications` says what actually changes — scope,
  dates, who does what. No lists: each field is rendered as a single wrapped
  paragraph.
- **`status`** — `active`, or `withdrawn` if the source shows it was decided and
  then reversed. Never `superseded`; that status is set on the *prior* note.
- **`source`** — the stem of the meeting note this came from, if there is one.
  It must resolve to a file in `20-meetings/`. For an inbox transcript, a pasted
  paragraph or dictation there is no meeting note: **omit `source`** and put the
  provenance in the `why` text instead.
- **`supersedes`** — see below.
- **the date** — the date the decision was **made**, read out of the source. A
  steerco on the 12th logged on the 14th is dated the 12th; the date is what
  orders the log. Today is the fallback, not the answer.

### 5. Supersession — only on explicit conflict

A new decision supersedes a prior one when the source **says** it replaces it:
"instead of", "we're reversing", "this replaces". Not because you judge two
notes inconsistent.

When you are unsure, write the new note **without** `supersedes` and say in your
summary that the two look inconsistent. Two active decisions a human resolves
beats a wrong edge, because the flip is a write on somebody else's note.

Only an `active` decision can be superseded, and only one in the same project.
The CLI enforces both.

### 6. Confirm, then write

**Foreground.** Present each candidate before writing — title, summary, and what
it supersedes if anything — and let the user confirm, edit, or drop it. Then
write the accepted ones, one call each:

```bash
cat > /tmp/decision.json <<'JSON'
{
  "title": "single vendor strategy adopted",
  "summary": "Consolidate on a single automation vendor across all three yards to simplify integration and reduce total cost of ownership.",
  "decision": "Consolidate on a single automation vendor across all three yards.",
  "why": "Running three vendors' control software in parallel created integration overhead that outweighed the site-pacing benefit of the phased approach.",
  "implications": "The pilot vendor stays for yard 1; yards 2-3 re-scope onto the same platform, pushing commissioning out roughly six weeks.",
  "source": "20-05-26-vendor-strategy-brainstorm",
  "supersedes": "2026-03-10-phased-rollout-adopted"
}
JSON
python3 "$VAULTLIB" decision write --vault "$VAULT" \
  --project meridian-yard-automation-program \
  --date 2026-05-20 --note /tmp/decision.json --foreground
```

Build the payload as a **file**, never inline — shell quoting mangles
apostrophes and em dashes. One decision per call: a failure then names exactly
which decision failed.

`--foreground` writes `reviewed: true`, which is a claim that a human validated
this note. Only pass it when one actually did.

**Background.** Identical, with `--background` and two rules that are not
negotiable:

1. **Never ask a question.** An unattended run that blocks on a prompt exits
   having done nothing. Ambiguity means skip that candidate and report it — a
   skipped decision is recoverable, a hung job is not.
2. **Verify against disk, not your own narrative.** Build the summary from what
   `decision write` returned and from the files that exist, never from your
   intent. A lab job once reported "Processed: 0" while having correctly written
   a note.

Extract more conservatively here than in foreground: if a candidate would need a
question to get right, it is not a background candidate.

### 7. Summarise

Report, from the CLI's results rather than from memory:

- each note written — path, and what it supersedes
- **each supersession, both sides**: "flipped `2026-03-10-phased-rollout-adopted`
  to superseded". If `supersession.error` is present the edge is one-sided —
  surface that verbatim, it needs a human.
- what you read and deliberately did **not** record, and why
- any inconsistency you spotted but did not resolve into a supersession

In background mode this summary is the caller's return value — the evening run
renders it directly, so it must be complete and it must be true.

## Rules

1. **Never hand-write a decision note.** Every write goes through
   `decision write`. It validates against the ontology; you do not.
2. **Never delete a decision.** Status flips only. The CLI has no delete.
3. **Read `decision list` before extracting.** Without it you cannot tell a new
   decision from a restatement, and you cannot find a supersession target.
4. **Pass stems back as they came.** `supersedes` and `source` cross this
   boundary as bare stems in both directions. Wrapping one in `[[…]]` yourself
   is how you get `[[[[…]]]]`.
5. **Supersession needs explicit conflict language.** When in doubt, leave both
   active and say so.
6. **`--foreground` is a claim about a human.** Unattended writes are
   `--background`, always.
7. **Do not invent.** No decision is better than a plausible one; this vault is
   read as a record.
`````

- [ ] **Step 4: Add the two rules to `plugin/CLAUDE.md`**

After the "Table cells are stored with the pipe escaped" subsection, add:

```markdown
### Wikilink fields cross the boundary as bare stems

`decision write` takes `supersedes` and `source` as bare note stems
(`2026-03-10-phased-rollout-adopted`) and `decision list` returns them the same
way. The `[[...]]` wrapping — and the quoting that keeps YAML from reading it as
a nested list — exists only inside the file.

So the value that comes out is the value that goes back in. This is deliberately
*not* the table-cell situation above: there, the stored escape is what a reader
gets and the caller has to strip it. Here the CLI owns both directions, because
a caller that re-wraps a stem it just read produces `[[[[...]]]]`, and the write
succeeds while the edge silently resolves to nothing.

### The mode flag decides an audit field

`decision write` requires exactly one of `--foreground` or `--background`, and
it has no default. Foreground writes `reviewed: true` — a claim that a human
validated the note as it was written. Background writes `reviewed: false`, which
is what `Decisions.base`'s **Needs review** view queues up. A default here would
write a lie into the audit trail, which is why argparse is made to refuse the
call instead.
```

- [ ] **Step 5: Bump the plugin version**

`plugin/.claude-plugin/plugin.json`:

```json
{
  "name": "second-brain",
  "version": "0.2.0",
  "description": "Second Brain Accelerator plugin — skills, hooks, and agents for a client executive's personal AI operating system."
}
```

- [ ] **Step 6: Add the CHANGELOG entry**

At the top of the list under `## Unreleased` in `CHANGELOG.md`:

```markdown
- **`/log-decision` — the decision log gets a producer.** Point it at a meeting
  note, a transcript, or just describe what was decided, and it proposes the
  decisions it found, one at a time, for you to confirm or correct before
  anything is written. Each one becomes its own dated note in the project's
  `decisions/` folder. When a decision replaces an earlier one it maintains both
  ends: the new note records what it supersedes, and the old note is marked
  superseded with a pointer forward — never deleted, so the trail of how the
  engagement changed its mind stays readable. It also runs unattended as part of
  the evening routine, and everything it writes that way is flagged for review
  in the Decisions base, so nothing lands in the record without a human seeing
  it. (#PR)
- **Decisions no longer carry tags.** A seven-word tag vocabulary was thin at
  the volume a decision log actually reaches, and decisions are found by project,
  by recency, or by asking. One less field to fill in. (#PR)
```

Replace `#PR` with the real pull-request number once the PR exists.

- [ ] **Step 7: Run everything**

```bash
python3 scripts/lint_plugin.py
python3 scripts/validate_template.py
python3 scripts/compile_ontology.py --check
python3 -m pytest scripts/tests -q
```

Expected: all four clean. `lint_plugin.py` is the check that the
`upstreamed-from: busdev@ccc27b8` line is exempted correctly and that nothing
else in the new SKILL.md trips the denylist.

- [ ] **Step 8: Commit**

```bash
git add plugin/skills/log-decision/SKILL.md plugin/CLAUDE.md plugin/.claude-plugin/plugin.json CHANGELOG.md scripts/tests/test_skill_contracts.py
git commit -m "$(cat <<'MSG'
feat(plugin): /log-decision in foreground and background modes

Closes the #36 half. Foreground proposes each candidate for the user to
confirm; background never prompts and marks what it writes reviewed:
false, which is the mode #16's evening run calls.

Carries the material-decision test (commits the engagement AND would
change a stakeholder's behaviour), the explicit-conflict-only rule for
supersession, and the two production rules an unattended run needs:
never block on a prompt, verify against disk rather than your own
narrative.

plugin/CLAUDE.md gains the bare-stem boundary rule next to the
pipe-escaping one. Version 0.1.0 -> 0.2.0.

Co-Authored-By: Claude <noreply@anthropic.com>
MSG
)"
```

---

## Post-plan: hand-test before the PR

Not a task — the controller does this once Task 5 is green, because quality is
judged on real output, not on a passing suite.

```bash
python3 scripts/make_test_vault.py /tmp/p1b-vault
python3 plugin/lib/vaultlib/cli.py decision list --vault /tmp/p1b-vault \
  --project meridian-yard-automation-program
```

Then write a decision superseding the active one, and read both files: is the
frontmatter right, does the body read like something a person would keep, did
the prior note get its footer without losing prose? Check
`scripts/make_test_vault.py --help` first for the actual flag names.
