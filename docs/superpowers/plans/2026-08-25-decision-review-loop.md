# Decision Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the decision review queue workable from Obsidian, open the vault
on the review queue, retire the legacy `needs-attention` status without losing
its clobber-risk signal, and rewrite every sync summary line that requires
source access to decode.

**Architecture:** Four independent findings from one E2E session, landed in one
PR because they overlap in the same five files. Two are `.base` edits with no
code. The third relocates a signal from a `review_status` enum value onto the
`conflicts-with` edge that already means exactly the same thing — so the guard
that refuses to auto-confirm a duplicate keys on a field rather than a status.
The fourth is prose in two SKILL.md files, pinned by a contract test.

**Tech Stack:** Python 3.10+ stdlib only, pytest, Obsidian Bases YAML
(`.base`), markdown with YAML frontmatter.

**Spec:** `docs/superpowers/specs/2026-08-25-decision-review-loop-design.md`

## Global Constraints

- **Stdlib only** in `plugin/lib/` — no PyYAML at runtime; the ontology is
  compiled to `schema.json`.
- **Python 3.10 is the syntax floor** (Cowork ships 3.10; CI runs 3.13).
- **Writes are UTF-8 with `newline="\n"`.**
- **Clean-room rule:** nothing in `plugin/` or `template/` may name a delaware
  client, a real person, or a busdev path.
- **Every commit message ends with the trailer**
  `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **After any `ontology.md` edit:** run `python3 scripts/compile_ontology.py`,
  or `test_schema_json_is_not_stale` fails.
- **Do not edit `docs/superpowers/plans/*` or `docs/superpowers/specs/*` from
  earlier dates.** They are dated records of past work and legitimately still
  name `needs-attention`. Only this plan's own files are in scope.
- **Task order is load-bearing.** Task 2 lands the new guard before Task 3
  stops producing the old status, so a confirmed-target sibling is never
  unguarded. Task 4 changes the enum only once nothing writes the old value.
- **The three local gates**, run before every commit:
  `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`

---

### Task 1: `Decisions.base` — the checkbox in the queue, and triage first

Findings A9 and A8. No code: the tick already writes `reviewed: true` from
Obsidian, so the queue view just needs the control and the first slot.

**Files:**
- Modify: `template/30-projects/Decisions.base` (whole file, below)
- Modify: `template/99-workflow-config/reference/ontology.md:145-149`
- Test: `scripts/tests/test_bases_views.py` (append at end of file)

**Interfaces:**
- Consumes: `basesim.load_base(path) -> dict`, `basesim.view_names(base) -> list[str]`
  (both already exist in `scripts/basesim.py`).
- Produces: the module-level constants `DEFAULT_VIEWS` and `REQUIRED_COLUMNS`
  in `test_bases_views.py`. Task 5 appends one row to `REQUIRED_COLUMNS`.

- [ ] **Step 1: Write the failing tests**

Append to the end of `scripts/tests/test_bases_views.py`:

```python
# The view a human lands on when they open a .base file is the first view in
# the file. Triage-first posture, and a row-set test cannot see a reordering.
DEFAULT_VIEWS = [
    ("30-projects/Decisions.base", "Needs review"),
    ("20-meetings/Meetings.base", "Triage"),
]


@pytest.mark.parametrize("base_path,expected", DEFAULT_VIEWS,
                         ids=[b.split("/")[-1] for b, _ in DEFAULT_VIEWS])
def test_first_view_is_the_review_queue(vault, base_path, expected):
    names = basesim.view_names(basesim.load_base(vault / base_path))
    assert names[0] == expected, (
        f"{base_path} opens on {names[0]!r} — Obsidian shows the first view, "
        f"and triage comes first"
    )


# (base file, view, property) — a control the human must reach to work the
# queue. A filter that hides ticked rows is a dead end without the checkbox.
REQUIRED_COLUMNS = [
    ("30-projects/Decisions.base", "Needs review", "reviewed"),
    ("20-meetings/Meetings.base", "Triage", "reviewed"),
]


@pytest.mark.parametrize("base_path,view,prop", REQUIRED_COLUMNS,
                         ids=[f"{b.split('/')[-1]}:{v}:{p}"
                              for b, v, p in REQUIRED_COLUMNS])
def test_view_exposes_the_column(vault, base_path, view, prop):
    base = basesim.load_base(vault / base_path)
    order = next(v.get("order") or [] for v in base["views"]
                 if v.get("name") == view)
    assert prop in order, (
        f"{base_path} view {view!r} omits {prop!r} from order: — the property "
        f"is not shown, so it cannot be edited"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_bases_views.py -k "first_view or exposes_the_column" -v`
Expected: `Decisions.base:Needs review:reviewed` FAILS (`omits 'reviewed' from order:`) and
`first_view_is_the_review_queue[Decisions.base]` FAILS (`opens on 'Active'`). The two
Meetings cases PASS already.

- [ ] **Step 3: Rewrite `Decisions.base`**

Replace the whole of `template/30-projects/Decisions.base` with:

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
    displayName: ✓ Reviewed
  supersedes:
    displayName: Supersedes
views:
  - type: table
    name: Needs review
    filters:
      and:
        - reviewed != true
    order:
      - formula.open
      - summary
      - project
      - date
      - reviewed
      - status
      - supersedes
    sort:
      - property: date
        direction: DESC
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

Two changes beyond the reorder: `reviewed` joins the **Needs review** `order:`
right after `date` so it is reachable without scrolling past the long Decision
sentence, and its `displayName` becomes `✓ Reviewed` to match Meetings. The
`properties:` block is shared by every view, so the **All** view's header
changes too — intended.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_bases_views.py -v`
Expected: all PASS, including the pre-existing row-set expectations (adding a
column changes no filter, so the **Needs review** row set is unchanged).

- [ ] **Step 5: Record the asymmetry in the ontology**

In `template/99-workflow-config/reference/ontology.md`, replace this bullet:

```markdown
- `reviewed` is the triage marker: `true` when a human validated the note as it
  was written, `false` when it was captured unattended. It is in
  `keys_present`, so the key always exists — `Decisions.base`'s **Needs review**
  view filters on `reviewed == false`, and a missing key would make that view
  silently incomplete. Same one-click convention as Meeting's `reviewed`.
```

with:

```markdown
- `reviewed` is the triage marker: `true` when a human validated the note as it
  was written, `false` when it was captured unattended. It is in
  `keys_present`, so the key always exists — `Decisions.base`'s **Needs review**
  view filters on `reviewed != true`, and a missing key would make that view
  silently incomplete. Same one-click convention as Meeting's `reviewed`, and
  that view carries the checkbox, so the queue is worked where it is read.
- **There is no second status behind the tick.** Nothing gates on a decision's
  review state the way project metrics gate on a meeting's `review_status`, so
  ticking the box *is* the confirmation and no sync step folds it further. The
  asymmetry with Meeting is deliberate, not a missing feature.
```

(The `reviewed == false` → `reviewed != true` correction matches the filter
that actually ships; the absence-tolerant form also catches pre-0.2.0 notes
carrying no `reviewed` key.)

- [ ] **Step 6: Run the three local gates**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: lint and validator print nothing but their own success lines; suite green.

- [ ] **Step 7: Commit**

```bash
git add template/30-projects/Decisions.base template/99-workflow-config/reference/ontology.md scripts/tests/test_bases_views.py
git commit -m "fix: the decision queue opens first and carries its checkbox (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `reconcile_reviews` keys the duplicate guard on `conflicts-with`

Finding F6, first half. The guard moves off the status before anything stops
writing that status, so a confirmed-target sibling is guarded at every commit.

**Files:**
- Modify: `plugin/lib/vaultlib/syncjob.py:138-173`
- Modify: `plugin/lib/vaultlib/cli.py:210-211`
- Test: `scripts/tests/test_vaultlib_syncjob.py:97-116`

**Interfaces:**
- Consumes: `markdown.split_frontmatter(text) -> (dict, str)`,
  `markdown.replace_scalar_field(text, key, value) -> str`,
  `vault.atomic_write(path, text)` — all unchanged.
- Produces: `syncjob.reconcile_reviews(root) -> {"flipped": list[str],
  "conflict_ticks": list[str], "warnings": list[str]}`. The key
  `needs_attention_ticks` is gone; Task 6 renames it in both skills' prose.

- [ ] **Step 1: Extend the test helper to write a `conflicts-with` edge**

In `scripts/tests/test_vaultlib_syncjob.py`, replace `write_triaged_meeting`:

```python
def write_triaged_meeting(root, stem, review_status, reviewed,
                          conflicts_with=None):
    """`conflicts_with=None` omits the key; a stem writes the quoted wikilink;
    `""` writes the key with no value — the shape Obsidian leaves behind when
    a human clears the field to say the duplicate is resolved."""
    lines = [
        "---", "date: 2026-08-20T10:00", "type: meeting",
        'calendar-subject: "X"', f"review_status: {review_status}",
        f"reviewed: {'true' if reviewed else 'false'}", "archived: false",
    ]
    if conflicts_with is not None:
        value = f'"[[{conflicts_with}]]"' if conflicts_with else ""
        lines.append(f"conflicts-with: {value}".rstrip())
    lines += ["---", "", "## Key Takeaways", "- x", ""]
    (root / "20-meetings" / f"{stem}.md").write_text(
        "\n".join(lines), encoding="utf-8")
```

- [ ] **Step 2: Write the failing tests**

In the same file, replace `test_reconcile_flips_only_reviewed_needs_review`
with these two tests:

```python
def test_reconcile_flips_only_reviewed_needs_review(tmp_path):
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "a-ticked", "needs-review", True)
    write_triaged_meeting(root, "b-unticked", "needs-review", False)
    write_triaged_meeting(root, "c-confirmed", "confirmed", True)
    # The clobber-risk case: a -v2 sibling the CLI wrote rather than overwrite
    # a confirmed note. Ticked, but the duplicate is unresolved.
    write_triaged_meeting(root, "d-duplicate", "needs-review", True,
                          conflicts_with="c-confirmed")

    result = syncjob.reconcile_reviews(root)
    assert result["flipped"] == ["20-meetings/a-ticked.md"]
    assert result["conflict_ticks"] == ["20-meetings/d-duplicate.md"]

    text = (root / "20-meetings" / "a-ticked.md").read_text(encoding="utf-8")
    assert "review_status: confirmed" in text
    assert "reviewed: true" in text          # the tick itself is never touched
    untouched = (root / "20-meetings" / "b-unticked.md").read_text(encoding="utf-8")
    assert "review_status: needs-review" in untouched
    still_flagged = (root / "20-meetings" / "d-duplicate.md").read_text(encoding="utf-8")
    assert "review_status: needs-review" in still_flagged


def test_clearing_the_conflict_edge_lets_the_tick_fold(tmp_path):
    """The escape hatch: emptying conflicts-with is how a human says the
    duplicate is merged or deleted, and the next run confirms normally."""
    root = make_vault(tmp_path)
    write_triaged_meeting(root, "resolved", "needs-review", True,
                          conflicts_with="")

    result = syncjob.reconcile_reviews(root)
    assert result["flipped"] == ["20-meetings/resolved.md"]
    assert result["conflict_ticks"] == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -k "reconcile_flips or clearing_the_conflict" -v`
Expected: both FAIL with `KeyError: 'conflict_ticks'`.

- [ ] **Step 4: Rewrite `reconcile_reviews`**

In `plugin/lib/vaultlib/syncjob.py`, replace the whole function:

```python
def reconcile_reviews(root: Path) -> dict:
    """Fold triage ticks back into review_status: reviewed true flips
    needs-review -> confirmed. One-way and narrow: a tick on a note that still
    carries a `conflicts-with` edge is surfaced for a human, never
    auto-confirmed — that edge means the note is a duplicate the CLI kept
    rather than overwrite a confirmed meeting, and confirming it silently would
    bless two notes for one meeting. Clearing the edge is how a human says the
    duplicate is resolved; the next run folds the tick. `archived` is never
    read by any pipeline.
    """
    flipped: List[str] = []
    conflict_ticks: List[str] = []
    warnings: List[str] = []
    meetings = root / MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data, _ = markdown.split_frontmatter(text)
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        if data.get("reviewed") is not True:
            continue
        if data.get("review_status") != "needs-review":
            continue
        if data.get("conflicts-with"):
            conflict_ticks.append(rel)
            continue
        try:
            updated = markdown.replace_scalar_field(
                text, "review_status", "confirmed")
        except ValueError as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        vault.atomic_write(path, updated)
        flipped.append(rel)
    return {"flipped": flipped, "conflict_ticks": conflict_ticks,
            "warnings": warnings}
```

The status check comes *before* the edge check on purpose: a `confirmed` note
with a stale edge is then silently skipped rather than reported on every run,
while a note that cannot fold stays `needs-review` and keeps being reported —
which is accurate, because it is still unresolved.

- [ ] **Step 5: Extend the CLI help text**

In `plugin/lib/vaultlib/cli.py`, replace:

```python
        "reconcile-reviews",
        help="flip review_status needs-review -> confirmed where reviewed is ticked")
```

with:

```python
        "reconcile-reviews",
        help="flip review_status needs-review -> confirmed where reviewed is "
             "ticked; a note still carrying conflicts-with is reported, "
             "not flipped")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_syncjob.py scripts/tests/test_vaultlib_cli.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the three local gates**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: green. (Both SKILL.md files still say `needs_attention_ticks` in
prose — no test couples prose to the result key until Task 6.)

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/syncjob.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_syncjob.py
git commit -m "fix: the review fold guards on the conflicts-with edge, not a status (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: the confirmed-target sibling is written `needs-review`

Finding F6, second half. The `conflicts-with` edge this path already writes is
now the whole signal, so the status can be ordinary.

**Files:**
- Modify: `plugin/lib/vaultlib/meeting.py:280-283`
- Test: `scripts/tests/test_vaultlib_meeting.py:144-164`

**Interfaces:**
- Consumes: `syncjob.reconcile_reviews`'s edge-keyed guard from Task 2.
- Produces: `meeting.write(root, payload)`'s result dict is unchanged in shape
  — `review_status` now reads `"needs-review"` on a `confirmed-target`
  conflict; `result["conflict"]` still carries
  `{"kind": "confirmed-target", "conflicts_with": <stem>}`.

- [ ] **Step 1: Update the test to the new expectation**

In `scripts/tests/test_vaultlib_meeting.py`, replace
`test_confirmed_target_gets_needs_attention_sibling` with:

```python
def test_confirmed_target_gets_a_flagged_sibling(tmp_path):
    """The sibling is an ordinary needs-review note; the conflicts-with edge
    is what marks it as a duplicate that must not be auto-confirmed."""
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    # A human confirms it via triage.
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")

    dup = payload(**{"source-recording-id": "inbox:ffff2a41d8e07b56"})
    result = meeting.write(root, dup)
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-v2"
    assert result["review_status"] == "needs-review"
    assert result["conflict"] == {
        "kind": "confirmed-target",
        "conflicts_with": "20-05-26-vendor-strategy-brainstorm",
    }
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'conflicts-with: "[[20-05-26-vendor-strategy-brainstorm]]"' in text
    # The confirmed note was not touched.
    assert "review_status: confirmed" in p.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py::test_confirmed_target_gets_a_flagged_sibling -v`
Expected: FAIL — `assert 'needs-attention' == 'needs-review'`.

- [ ] **Step 3: Change the conflict branch**

In `plugin/lib/vaultlib/meeting.py`, in `_resolve_target`, replace:

```python
    if status == "confirmed":
        sibling = _first_free(folder, stem + "-v{n}")
        conflict = {"kind": "confirmed-target", "conflicts_with": existing.stem}
        return sibling, "needs-attention", existing.stem, conflict
```

with:

```python
    if status == "confirmed":
        # An ordinary needs-review note: the conflicts-with edge below is the
        # clobber-risk signal, and reconcile_reviews refuses to fold a tick
        # while it is present.
        sibling = _first_free(folder, stem + "-v{n}")
        conflict = {"kind": "confirmed-target", "conflicts_with": existing.stem}
        return sibling, "needs-review", existing.stem, conflict
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest scripts/tests/test_vaultlib_meeting.py -v`
Expected: all PASS (`test_second_conflict_takes_v3` asserts stems, not status).

- [ ] **Step 5: Run the three local gates**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: green — the `12-06-26-jordan-1on1-v2` fixture still carries the old
status and still validates against the not-yet-changed enum.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/meeting.py scripts/tests/test_vaultlib_meeting.py
git commit -m "fix: a duplicate capture is needs-review plus a conflicts-with edge (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: retire `needs-attention` from the ontology, schema, and fixtures

Nothing writes the value any more, so the enum can lose it. The enum, the
fixture that carries it, and the fixture test that asserts it are one atomic
change — split them and the suite is red in between.

**Files:**
- Modify: `template/99-workflow-config/reference/ontology.md:38` and `:76-78`
- Modify (generated): `plugin/lib/vaultlib/schema.json`
- Modify: `fixtures/demo-vault/20-meetings/12-06-26-jordan-1on1-v2.md:12`
- Modify: `fixtures/demo-vault/60-daily-notes/2026-06-12.md:12`
- Test: `scripts/tests/test_fixtures_ontology.py:612-614`
- Test: `scripts/tests/test_compile_ontology.py` (append at end of file)

**Interfaces:**
- Consumes: `compile_ontology.compile_schema() -> dict` with
  `["objects"]["meeting"]["enums"]["review_status"]`.
- Produces: the compiled meeting enum is exactly
  `["needs-review", "confirmed"]`.

- [ ] **Step 1: Write the failing enum test**

Append to `scripts/tests/test_compile_ontology.py`:

```python
def test_review_status_retired_needs_attention():
    """#58: `needs-attention` was a busdev-era status. The clobber-risk signal
    it used to carry now lives on the `conflicts-with` edge, which is a field
    rather than a status — so the enum is two values, and stays two."""
    meeting = co.compile_schema()["objects"]["meeting"]
    assert meeting["enums"]["review_status"] == ["needs-review", "confirmed"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest scripts/tests/test_compile_ontology.py::test_review_status_retired_needs_attention -v`
Expected: FAIL — the third value is still there.

- [ ] **Step 3: Edit the ontology**

In `template/99-workflow-config/reference/ontology.md`, in the Meeting YAML
block, replace:

```yaml
  review_status: [needs-review, confirmed, needs-attention]
```

with:

```yaml
  review_status: [needs-review, confirmed]
```

Then replace the `conflicts-with` bullet:

```markdown
- `conflicts-with` (`[[meeting]]`, quoted) appears only on a
  `needs-attention` sibling written because its target would have
  overwritten a `confirmed` meeting.
```

with:

```markdown
- `conflicts-with` (`[[meeting]]`, quoted) appears only on a `-v{n}` sibling
  written because its target would have overwritten a `confirmed` meeting. It
  is the clobber-risk signal: while it is present, `sync reconcile-reviews`
  reports a `reviewed` tick on that note instead of confirming it, because one
  meeting now has two notes and a human has to decide which survives. Clearing
  or deleting the field says the duplicate is resolved, and the next run folds
  the tick normally.
```

- [ ] **Step 4: Regenerate `schema.json` and confirm the enum test passes**

Run: `python3 scripts/compile_ontology.py && python3 -m pytest scripts/tests/test_compile_ontology.py -v`
Expected: `wrote plugin/lib/vaultlib/schema.json`, then all PASS.

- [ ] **Step 5: Update the fixture that carries the status**

In `fixtures/demo-vault/20-meetings/12-06-26-jordan-1on1-v2.md`, change line 12:

```yaml
review_status: needs-attention
```

to:

```yaml
review_status: needs-review
```

Leave `conflicts-with: "[[12-06-26-jordan-1on1]]"` exactly as it is — that line
is now the entire signal.

- [ ] **Step 6: De-jargon the daily-note fixture prose**

In `fixtures/demo-vault/60-daily-notes/2026-06-12.md`, change:

```markdown
- [[05-06-26-pipeline-governance-review]] — cadence reviewed; capture flagged needs-attention (low-confidence match), no decision logged.
```

to:

```markdown
- [[05-06-26-pipeline-governance-review]] — cadence reviewed; capture flagged for review (low-confidence match), no decision logged.
```

- [ ] **Step 7: Restate the fixture invariant**

In `scripts/tests/test_fixtures_ontology.py`, inside
`test_conflict_sibling_fixture_exercises_conflicts_with`, replace:

```python
        assert fm["review_status"] == "needs-attention", (
            f"{path}: conflicts-with appears only on needs-attention siblings"
        )
```

with:

```python
        assert fm["review_status"] != "confirmed", (
            f"{path}: a note carrying conflicts-with is an unresolved "
            f"duplicate — it cannot be confirmed while the edge stands"
        )
```

The assertions above it — that the value is a quoted wikilink resolving to a
real fixture stem — are unchanged and now carry more of the weight.

- [ ] **Step 8: Run the three local gates**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: green. `test_bases_views.py`'s Triage row set is unchanged — the
`-v2` sibling still matches the `or:` branch that is still in `Meetings.base`,
now via its `needs-review` value.

- [ ] **Step 9: Commit**

```bash
git add template/99-workflow-config/reference/ontology.md plugin/lib/vaultlib/schema.json fixtures/demo-vault/20-meetings/12-06-26-jordan-1on1-v2.md fixtures/demo-vault/60-daily-notes/2026-06-12.md scripts/tests/test_fixtures_ontology.py scripts/tests/test_compile_ontology.py
git commit -m "refactor: retire the needs-attention review status (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `Meetings.base` — collapse the Triage `or`, surface the duplicate

The Triage filter's second branch now matches nothing, and the relocated
signal has to be visible where triage happens.

**Files:**
- Modify: `template/20-meetings/Meetings.base:24-53`
- Test: `scripts/tests/test_bases_views.py:83-92` (comment) and its
  `REQUIRED_COLUMNS` from Task 1
- Test: `scripts/tests/test_basesim.py:111-130`

**Interfaces:**
- Consumes: `REQUIRED_COLUMNS` in `test_bases_views.py` (Task 1).
- Produces: nothing later tasks read.

- [ ] **Step 1: Write the failing column expectation**

In `scripts/tests/test_bases_views.py`, add a third row to `REQUIRED_COLUMNS`:

```python
REQUIRED_COLUMNS = [
    ("30-projects/Decisions.base", "Needs review", "reviewed"),
    ("20-meetings/Meetings.base", "Triage", "reviewed"),
    # The clobber-risk signal, relocated off review_status in #58: triage has
    # to show which capture is a duplicate of a confirmed note.
    ("20-meetings/Meetings.base", "Triage", "conflicts-with"),
]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest scripts/tests/test_bases_views.py -k exposes_the_column -v`
Expected: `Meetings.base:Triage:conflicts-with` FAILS
(`omits 'conflicts-with' from order:`).

- [ ] **Step 3: Edit `Meetings.base`**

Add to the `properties:` block, after the `review_status` entry:

```yaml
  conflicts-with:
    displayName: ⚠ Duplicate of
```

Then replace the Triage view's `filters:` and `order:`:

```yaml
  - type: table
    name: Triage
    filters:
      and:
        - review_status == "needs-review"
        - reviewed != true
        - archived != true
    order:
      - formula.open
      - date
      - calendar-subject
      - calendar_match
      - attendees
      - projects
      - conflicts-with
      - reviewed
      - archived
      - recording-duration
      - source
      - type
```

Everything else in the file — the base-level filters, the formula, the other
property entries, the **All Meetings** view — is unchanged.

- [ ] **Step 4: Run the base tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_bases_views.py -v`
Expected: all PASS. The Triage row set is unchanged: `02-03-26-nordbridge-intro-call`
and `12-06-26-jordan-1on1-v2` both hold `review_status: needs-review`.

- [ ] **Step 5: Rewrite the stale comment above the Triage expectation**

In `scripts/tests/test_bases_views.py`, replace the comment block above the
`("20-meetings/Meetings.base", "Triage", ...)` entry in `EXPECTED`:

```python
    # Each exclusion path stays represented: 20-04 is reviewed-but-not-yet-
    # reconciled (reviewed: true holds it out of Triage until reconcile-reviews
    # flips it to confirmed), 05-06 is archived, and the five `confirmed`
    # meetings fail the review_status or. The -v2 collision sibling is
    # needs-attention, unreviewed, unarchived — it stays in Triage alongside
    # the unreviewed intro call.
```

with:

```python
    # Each exclusion path stays represented: 20-04 is reviewed-but-not-yet-
    # reconciled (reviewed: true holds it out of Triage until reconcile-reviews
    # flips it to confirmed), 05-06 is archived, and the five `confirmed`
    # meetings fail the review_status term. The -v2 collision sibling is an
    # ordinary needs-review note carrying a conflicts-with edge — it stays in
    # Triage alongside the unreviewed intro call, flagged by its ⚠ Duplicate
    # of column rather than by a status of its own.
```

- [ ] **Step 6: Retarget the basesim `or` test off the retired value**

In `scripts/tests/test_basesim.py`, replace
`test_or_inside_and_matches_meetings_triage_shape` with:

```python
def test_or_inside_and():
    """`or:` is a Bases combinator basesim must evaluate. No shipped view uses
    one since #58 collapsed the Meetings Triage filter, so this keeps the
    evaluator covered against the next view that needs it."""
    corpus = {
        "in-active.md": {"status": "active", "archived": False},
        "in-paused.md": {"status": "paused", "archived": False},
        "out-completed.md": {"status": "completed", "archived": False},
        "out-archived.md": {"status": "active", "archived": True},
    }
    got = rows(
        None,
        corpus,
        view_filters={
            "and": [
                {"or": ['status == "active"', 'status == "paused"']},
                "archived != true",
            ]
        },
    )
    assert got == {"in-active.md", "in-paused.md"}
```

- [ ] **Step 7: Run the three local gates**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add template/20-meetings/Meetings.base scripts/tests/test_bases_views.py scripts/tests/test_basesim.py
git commit -m "fix: triage flags a duplicate capture with a column, not a status (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: skill prose and plain-speech summaries

Findings F5 and the prose half of F6. Both skills still name the retired
status and still print field names at a human.

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md` — lines 106, 281-284, 293-300
- Modify: `plugin/skills/evening-sync/SKILL.md` — lines 182, 220-226
- Test: `scripts/tests/test_skill_contracts.py` (append at end of file)

**Interfaces:**
- Consumes: `reconcile_reviews`'s `conflict_ticks` key (Task 2);
  `read_skill(name) -> str` in `test_skill_contracts.py`.
- Produces: nothing later tasks read.

- [ ] **Step 1: Write the failing contract tests**

Append to `scripts/tests/test_skill_contracts.py`:

```python
# #58 (F5, F6): a summary line is read by the exec and the EA, so it may not
# quote a frontmatter value, a result key, or a retired status at them. The
# retired-status check covers the whole file, not just the summary block.
RETIRED_OR_OPAQUE = (
    "needs-attention",
    "needs_attention_ticks",
    "Reviewed ticks folded",
    "reviewed: false)",
)


@pytest.mark.parametrize("name", ["sync-recordings", "evening-sync"])
def test_sync_summaries_speak_plainly(name):
    text = read_skill(name)
    for token in RETIRED_OR_OPAQUE:
        assert token not in text, (
            f"{name}: {token!r} is a field name or a retired status — say it "
            f"in words the exec can read"
        )
    assert "**Meetings you ticked as reviewed:**" in text, (
        f"{name}: the fold result needs a plain-speech summary line"
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -k speak_plainly -v`
Expected: both parameterizations FAIL — `sync-recordings` on
`needs_attention_ticks`, `evening-sync` on `needs-attention`.

- [ ] **Step 3: Fix `/sync-recordings` — the fold instruction**

Replace:

```markdown
Report `flipped` in the summary; surface any `needs_attention_ticks` for a
human — those are never auto-confirmed.
```

with:

```markdown
Report `flipped` in the summary; surface any `conflict_ticks` for a human — a
note that still carries a `conflicts-with` edge is a duplicate nobody has
resolved yet, so a tick on it is never auto-confirmed. Say so in words, and say
what settles it: merge or delete one of the two notes, then clear the
`⚠ Duplicate of` field in Obsidian, and the next run confirms the tick.
```

- [ ] **Step 4: Fix `/sync-recordings` — the conflict-result prose in §6**

Replace:

```markdown
Read the result: a `conflict` of kind `confirmed-target` means the CLI wrote
a `-v2` sibling marked `needs-attention` instead of touching a confirmed
note — report it, it surfaces in triage. `stem-collision` means a `-2`
suffix. An `error` about an already-synced id means dedup was bypassed —
stop and say so.
```

with:

```markdown
Read the result: a `conflict` of kind `confirmed-target` means the CLI wrote a
`-v2` sibling carrying a `conflicts-with` edge instead of touching a confirmed
note — report it as a possible duplicate; it shows in triage under
`⚠ Duplicate of`. `stem-collision` means a `-2` suffix and nothing was at
risk. An `error` about an already-synced id means dedup was bypassed — stop and
say so.
```

- [ ] **Step 5: Fix `/sync-recordings` — the summary block**

Replace the fenced summary block under `### 7. Summarize` with:

```
## Sync Complete
**Processed:** {N} → `20-meetings/` ({list the stems})
**New people:** {N} created in `50-people/`
**Meetings you ticked as reviewed:** {N} now confirmed
**Possible duplicates:** {N} (kept as separate notes — each would have overwritten a meeting you already confirmed)
**Skipped / errors:** {N} (will retry next run)
**Adapters:** inbox ok · plaud ok | REFUSED — signed in as a different account (account-mismatch) | REFUSED — no account bound to this vault yet (no-account-hint) | disabled | unavailable · m365 disabled | not yet supported
**Calendar enrichment:** ok | UNAVAILABLE
```

- [ ] **Step 6: Fix `/evening-sync` — the Stage 6 watch-items list**

Replace:

```markdown
harvest jottings worth carrying forward, and watch items (conflicts,
needs-attention flags, self-check warnings). Respect the language and depth
```

with:

```markdown
harvest jottings worth carrying forward, and watch items (conflicts,
unresolved duplicates, self-check warnings). Respect the language and depth
```

- [ ] **Step 7: Fix `/evening-sync` — the summary block**

Replace the fenced block under `## Stage 7` with:

```
## Evening Sync Complete
**Synced:** {N} recordings → `20-meetings/` ({stems})
**Meetings you ticked as reviewed:** {N} now confirmed
**Possible duplicates:** {N} (kept as separate notes — each would have overwritten a meeting you already confirmed)
**Metrics refreshed:** {P} projects · {Q} people
**Projects updated:** {N} ({slugs}) — {M} decisions captured for review, {K} candidates skipped
**Tomorrow's note:** `60-daily-notes/{date}.md` ({DayName}) — {N} meetings prepped | calendar unavailable | calendar REFUSED — signed in as a different account (account-mismatch) | calendar REFUSED — no account bound to this vault yet (no-account-hint) | m365 disabled
**Warnings:** {verbatim, including SELF-CHECK lines} | none
```

The **Possible duplicates** line is new here. Stage 3 already tells this
pipeline to record the conflicts the nested sync reports, and an unattended run
is exactly when nobody is watching the sync's own summary.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -v`
Expected: all PASS, including `test_every_cli_invocation_named_by_a_skill_exists`
and `test_no_skill_reads_machine_decisions_from_prose` (no edit above names
`identity.md` or `tools-and-systems`).

- [ ] **Step 9: Run the three local gates**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: green.

- [ ] **Step 10: Confirm the retired status is gone from every shipped tree**

Run: `grep -rn "needs-attention" plugin/ template/ fixtures/`
Expected: no output (exit 1). Hits in `docs/` are dated records and stay.

- [ ] **Step 11: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md plugin/skills/evening-sync/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "docs: sync summaries read as sentences, not field names (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: version bump, changelog, migration note, full verification

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json:3`
- Modify: `CHANGELOG.md` (under `## Unreleased`)
- Modify: `migrations/README.md` (the pending-migration paragraph)

**Interfaces:**
- Consumes: every earlier task.
- Produces: the PR-ready tree.

- [ ] **Step 1: Bump the plugin version**

In `plugin/.claude-plugin/plugin.json`, change `"version": "0.5.0"` to
`"version": "0.5.1"`. (CI's version guard requires a bump on any PR touching
`plugin/` except `plugin/CLAUDE.md`. Patch, not minor: no new CLI surface —
one result key renamed, one status retired.)

- [ ] **Step 2: Changelog entry**

In `CHANGELOG.md`, add as the first bullet under `## Unreleased`:

```markdown
- **The decision queue is now something you can work.** `Decisions.base` opens
  on **Needs review**, and that view carries the ✓ Reviewed checkbox — so a
  decision captured overnight gets validated where you read it, in one click.
  A duplicate capture now says what it is: when the sync keeps a recording as
  a separate note rather than overwrite a meeting you had already confirmed,
  Meetings triage flags it under **⚠ Duplicate of**, and clearing that field is
  how you tell the next run the duplicate is settled. The old
  "needs-attention" status is gone. Sync and evening summaries read as
  sentences instead of field names. (#58)
```

- [ ] **Step 3: Note the migration**

In `migrations/README.md`, append to the pending-migration paragraph:

```markdown
Also: rewrite `review_status: needs-attention` → `needs-review` on existing
meeting notes (v0.5.1 retired the status; those notes already carry the
`conflicts-with` edge that now carries the clobber-risk signal, so nothing
else has to be written).
```

- [ ] **Step 4: Full verification**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: lint clean, validator clean, whole suite green with no skips beyond
the pre-existing ones.

- [ ] **Step 5: Confirm the acceptance criteria, one command each**

```bash
python3 -m pytest scripts/tests/test_bases_views.py -k "first_view or exposes_the_column" -v
python3 -m pytest scripts/tests/test_vaultlib_syncjob.py -k "reconcile or conflict" -v
python3 -m pytest scripts/tests/test_compile_ontology.py -k review_status -v
python3 -m pytest scripts/tests/test_skill_contracts.py -k speak_plainly -v
grep -rn "needs-attention" plugin/ template/ fixtures/ ; echo "exit=$? (1 means clean)"
```

Expected: four green runs, then `exit=1`.

- [ ] **Step 6: Commit**

```bash
git add plugin/.claude-plugin/plugin.json CHANGELOG.md migrations/README.md
git commit -m "chore: bump plugin to 0.5.1 for the decision review loop (#58)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 7: Open the PR**

```bash
git push -u origin claude/issue-58-superpowers-7813eb
```

PR body must state: closes #58; the four findings and how each was addressed;
that A9's acceptance criterion was restated (the tick is the write — there is
no second field for a fold to flip, and the spec argues why inventing one was
rejected); the three local gates run green; version bumped; changelog line
added; migration note added.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: A9 → Task 1; A8 → Task 1;
F6 → Tasks 2, 3, 4, 5 plus the prose in 6; F5 → Task 6; testing section →
distributed across the tasks that cause each change; housekeeping → Task 7.
The spec's `displayName` decision (`✓ Reviewed`, shared across views) is in
Task 1 Step 3; the escape-hatch behaviour is pinned by Task 2 Step 2's second
test and documented in Task 4 Step 3 and Task 6 Step 3.

**Placeholders.** None: every step names exact files, quotes the exact old text
to replace, and gives the exact new text or code.

**Type consistency.** `conflict_ticks` is the name in the implementation (Task 2
Step 4), the tests (Task 2 Step 2), the CLI help (Task 2 Step 5) and the skill
prose (Task 6 Step 3). `REQUIRED_COLUMNS` and `DEFAULT_VIEWS` are defined in
Task 1 Step 1 and extended in Task 5 Step 1. `read_skill` (Task 6) and
`write_triaged_meeting` (Task 2) match the existing helpers in their files.
