# Input and Include Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Inbox table becomes **Input** (last in the main menu; Thoughts & ideas moves under Daily notes; the Library leads with Recent and ends with Archive), which shows everything tonight's run will pick up. The owner's own notes in Thoughts & ideas can be ticked **Include**; the evening run then absorbs them into projects and decisions and leaves them in place. The daily note's `## End of day` becomes `## Notes`.

**Architecture:** A new `vaultlib.notes` module owns the three frontmatter operations on owner notes: harvest, assign and mark-absorbed. `updatequeue` treats an included note like a new meeting for its projects. `decision` accepts a note as `source`. `recap` renders two lines computed by the CLI: notes read, and items still in Input. Template changes (bases, menu, CSS, prose) arrive through migration 010, which takes the vault to structure 11. The evening-sync skill wires it together and gates note absorption on `structure_version >= 11`.

**Tech Stack:** Python 3 stdlib (`plugin/lib/vaultlib`), pytest (`scripts/tests`), Obsidian Bases YAML, Markdown skills.

**Spec:** `docs/superpowers/specs/2026-10-06-input-and-include-design.md`

## Global Constraints

- The folder stays `10-inbox/`. Only the menu entry, the table and owner-facing words say **Input**. Internal paths, the `inbox` adapter name and `vault.INBOX_DIR` are unchanged.
- Property names on owner notes are exactly `include` (checkbox), `absorbed` (ISO date) and `projects` (list of project slugs, the same shape as a meeting's `projects`).
- The run **never** changes a note body, never moves or deletes a note, and never reads `95-private/`. Every write goes through `markdown.upsert_scalar_field` and `vault.atomic_write`.
- `projects` is written only when it is empty. The owner's choice always wins.
- A note is marked absorbed only when every project it was queued for returned `stateWritten: true`, or when it had no project. Otherwise `include` stays ticked and the note retries tomorrow.
- Existing daily notes are never rewritten. `daily-note read` accepts both `## Notes` and `## End of day`.
- Migration `010-structure-version-11`, `TARGET_VERSION = 11`. Evening-sync gates on `structure_version >= 11`, never on "no migrations pending".
- Bases filters that start with `!` must be quoted in YAML. `groupBy` must be the object form `{property, direction}`. Every `properties:` key is namespaced (`note.` / `file.` / `formula.`).
- Version: the next patch after whatever `main` carries at merge time (0.13.8 today, so 0.13.9). Rebase on `origin/main` before bumping.
- Run the repo checks before every commit that touches the template or skills: `python scripts/lint_plugin.py`, `python scripts/validate_template.py` and `python -m pytest scripts/tests -q`.

## Review Focus

1. **A note in a subfolder of `80-thoughts-ideas/`.** Obsidian lets owners make folders, and Bases' `file.inFolder` includes subfolders. Harvest must find it too, or the table says "picked up tonight" and the run never reads it. The test is in Task 1 (`test_harvest_reads_subfolders`).
2. **`projects` written by Obsidian as a block list or `[]`.** The property editor rewrites inline lists as block lists. Assign must treat `projects: []` and an empty block list as empty, and must never orphan list items. The test is in Task 1 (`test_assign_treats_an_empty_block_list_as_empty`).
3. **A note naming a project that is not active (closed, mistyped).** It must not crash the queue or block absorption. It is warned about, ignored for queueing, and the note is treated as unlinked. The tests are in Task 1 (`test_harvest_drops_unknown_projects_with_a_warning`) and Task 2.
4. **The note vanishes or is unticked between harvest and write-back.** The owner may be editing during the run. `mark-absorbed` on a missing file reports `missing` and does not crash. The test is in Task 1 (`test_mark_absorbed_on_a_missing_note_reports_missing`).
5. **Non-markdown files in Thoughts & ideas** (a pasted image, a PDF). They are never harvested and never show in Input. The test is in Task 1 (`test_harvest_ignores_non_markdown`) and the Input filter in Task 6.

---

### Task 1: `vaultlib.notes`: harvest, assign, mark-absorbed (+ CLI)

**Files:**
- Modify: `plugin/lib/vaultlib/vault.py:28-35` (add `THOUGHTS_DIR`)
- Create: `plugin/lib/vaultlib/notes.py`
- Modify: `plugin/lib/vaultlib/cli.py` (import, parser group `notes`, dispatch, error handler)
- Test: `scripts/tests/test_vaultlib_notes.py`

**Interfaces:**
- Produces:
  - `vault.THOUGHTS_DIR = "80-thoughts-ideas"`
  - `notes.harvest(root: Path) -> {"notes": [{"path": str, "title": str, "projects": [str], "modified": "YYYY-MM-DDTHH:MM", "body": str | None}], "warnings": [str]}`. `body` is `None` when the note exceeds `MAX_BODY_CHARS`. Only notes with `include: true` are listed.
  - `notes.assign(root: Path, rel: str, projects: list[str]) -> {"path", "projects", "written": bool}`
  - `notes.mark_absorbed(root: Path, rel: str, date_iso: str) -> {"path", "status": "marked" | "unchanged" | "missing"}`
  - `notes.NotesError`
  - CLI: `notes harvest --vault V`, `notes assign --vault V --path P --projects a,b`, `notes mark-absorbed --vault V --path P --date YYYY-MM-DD`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_notes.py`:

```python
"""The owner's own notes (80-thoughts-ideas): Include, assign, absorbed.
Made-up vaults only."""
import json
from pathlib import Path

import pytest

from vaultlib import cli, notes

from test_vaultlib_vault import make_vault


def write_project(root: Path, slug: str, status: str = "active") -> None:
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text(
        f'---\ntype: project\nproject-name: "{slug}"\nslug: {slug}\n'
        f"status: {status}\n---\n", encoding="utf-8")


def write_note(root: Path, rel: str, frontmatter: str, body: str = "My own words.\n") -> Path:
    path = root / "80-thoughts-ideas" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (f"---\n{frontmatter}---\n" if frontmatter else "") + body
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm")
    write_project(root, "acme-old", status="closed")
    return root


def test_harvest_lists_only_ticked_notes(root):
    write_note(root, "ticked.md", "include: true\n")
    write_note(root, "unticked.md", "include: false\n")
    write_note(root, "plain.md", "")
    result = notes.harvest(root)
    assert [n["path"] for n in result["notes"]] == ["80-thoughts-ideas/ticked.md"]
    entry = result["notes"][0]
    assert entry["title"] == "ticked" and entry["projects"] == []
    assert entry["body"] == "My own words.\n"


def test_harvest_reads_subfolders(root):
    write_note(root, "client/idea.md", "include: true\n")
    assert [n["path"] for n in notes.harvest(root)["notes"]] == [
        "80-thoughts-ideas/client/idea.md"]


def test_harvest_ignores_non_markdown(root):
    (root / "80-thoughts-ideas").mkdir(exist_ok=True)
    (root / "80-thoughts-ideas" / "photo.png").write_bytes(b"\x89PNG")
    assert notes.harvest(root)["notes"] == []


def test_harvest_drops_unknown_projects_with_a_warning(root):
    write_note(root, "n.md", "include: true\nprojects: [acme-crm, acme-old, typo]\n")
    result = notes.harvest(root)
    assert result["notes"][0]["projects"] == ["acme-crm"]
    assert any("acme-old" in w and "typo" in w for w in result["warnings"])


def test_harvest_withholds_an_oversized_body(root):
    write_note(root, "long.md", "include: true\n", body="x" * (notes.MAX_BODY_CHARS + 1))
    result = notes.harvest(root)
    assert result["notes"][0]["body"] is None
    assert any("long.md" in w and "cap" in w for w in result["warnings"])


def test_harvest_warns_on_broken_frontmatter_and_continues(root):
    path = root / "80-thoughts-ideas" / "broken.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("---\ninclude: true\n", encoding="utf-8")   # never closed
    write_note(root, "ok.md", "include: true\n")
    result = notes.harvest(root)
    assert [n["path"] for n in result["notes"]] == ["80-thoughts-ideas/ok.md"]


def test_harvest_on_a_vault_without_the_folder(tmp_path):
    root = make_vault(tmp_path)
    assert notes.harvest(root) == {"notes": [], "warnings": []}


def test_assign_writes_projects_only_when_empty(root):
    path = write_note(root, "n.md", "include: true\n")
    body_before = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    result = notes.assign(root, "80-thoughts-ideas/n.md", ["acme-crm"])
    assert result == {"path": "80-thoughts-ideas/n.md", "projects": ["acme-crm"], "written": True}
    text = path.read_text(encoding="utf-8")
    assert "projects: [acme-crm]" in text
    assert text.split("---\n", 2)[2] == body_before


def test_assign_never_overrides_the_owners_choice(root):
    write_project(root, "acme-erp")
    path = write_note(root, "n.md", "include: true\nprojects: [acme-erp]\n")
    before = path.read_bytes()
    result = notes.assign(root, "80-thoughts-ideas/n.md", ["acme-crm"])
    assert result["written"] is False and result["projects"] == ["acme-erp"]
    assert path.read_bytes() == before


def test_assign_treats_an_empty_block_list_as_empty(root):
    path = write_note(root, "n.md", "include: true\nprojects: []\n")
    notes.assign(root, "80-thoughts-ideas/n.md", ["acme-crm"])
    text = path.read_text(encoding="utf-8")
    assert text.count("projects:") == 1 and "projects: [acme-crm]" in text
    path = write_note(root, "m.md", "include: true\nprojects:\n")
    notes.assign(root, "80-thoughts-ideas/m.md", ["acme-crm"])
    assert "projects: [acme-crm]" in path.read_text(encoding="utf-8")


def test_assign_refuses_an_inactive_project_and_a_path_outside_the_folder(root):
    write_note(root, "n.md", "include: true\n")
    with pytest.raises(notes.NotesError, match="acme-old"):
        notes.assign(root, "80-thoughts-ideas/n.md", ["acme-old"])
    with pytest.raises(notes.NotesError, match="80-thoughts-ideas"):
        notes.assign(root, "95-private/secret.md", ["acme-crm"])


def test_mark_absorbed_flips_include_and_stamps_the_date_body_untouched(root):
    path = write_note(root, "n.md", "include: true\nprojects: [acme-crm]\n")
    body_before = path.read_text(encoding="utf-8").split("---\n", 2)[2]
    result = notes.mark_absorbed(root, "80-thoughts-ideas/n.md", "2026-10-06")
    assert result == {"path": "80-thoughts-ideas/n.md", "status": "marked"}
    text = path.read_text(encoding="utf-8")
    assert "include: false" in text and "absorbed: 2026-10-06" in text
    assert text.split("---\n", 2)[2] == body_before
    assert notes.mark_absorbed(root, "80-thoughts-ideas/n.md", "2026-10-06")["status"] == "unchanged"


def test_mark_absorbed_on_a_missing_note_reports_missing(root):
    assert notes.mark_absorbed(root, "80-thoughts-ideas/gone.md", "2026-10-06") == {
        "path": "80-thoughts-ideas/gone.md", "status": "missing"}


def test_mark_absorbed_refuses_a_bad_date(root):
    write_note(root, "n.md", "include: true\n")
    with pytest.raises(notes.NotesError, match="YYYY-MM-DD"):
        notes.mark_absorbed(root, "80-thoughts-ideas/n.md", "06-10-2026")


def run(capsys, argv):
    code = cli.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_round_trip(capsys, root):
    write_note(root, "n.md", "include: true\n")
    code, out = run(capsys, ["notes", "harvest", "--vault", str(root)])
    assert code == 0 and out["result"]["notes"][0]["path"] == "80-thoughts-ideas/n.md"
    code, out = run(capsys, ["notes", "assign", "--vault", str(root),
                             "--path", "80-thoughts-ideas/n.md", "--projects", "acme-crm"])
    assert code == 0 and out["result"]["written"] is True
    code, out = run(capsys, ["notes", "mark-absorbed", "--vault", str(root),
                             "--path", "80-thoughts-ideas/n.md", "--date", "2026-10-06"])
    assert code == 0 and out["result"]["status"] == "marked"
    code, out = run(capsys, ["notes", "assign", "--vault", str(root),
                             "--path", "80-thoughts-ideas/n.md", "--projects", "acme-old"])
    assert code == 1 and "acme-old" in out["error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_notes.py -q`
Expected: collection error, `ImportError: cannot import name 'notes'`.

- [ ] **Step 3: Implement**

In `plugin/lib/vaultlib/vault.py`, add after `DAILY_NOTES_DIR = "60-daily-notes"`:

```python
THOUGHTS_DIR = "80-thoughts-ideas"
```

Create `plugin/lib/vaultlib/notes.py`:

```python
"""The owner's own notes in 80-thoughts-ideas: which are ticked Include, which
projects they belong to, and the stamp once the evening run has read them.

Only frontmatter is ever written, one field node at a time; the body is the
owner's own writing and stays byte-identical. A note is never moved or
deleted — absorbing it is a stamp, not a filing step.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Set

from . import markdown, naming, vault

THOUGHTS_DIR = vault.THOUGHTS_DIR
PROJECTS_DIR = vault.PROJECTS_DIR
# A note longer than this is listed but not handed to the run: one runaway
# paste must not blow a project subagent's context.
MAX_BODY_CHARS = 40_000


class NotesError(Exception):
    """A notes argument the caller must fix."""


def _active_projects(root: Path) -> Set[str]:
    active: Set[str] = set()
    folder = root / PROJECTS_DIR
    for index in sorted(folder.glob("*/index.md")) if folder.is_dir() else []:
        try:
            data, _ = markdown.split_frontmatter(index.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if data.get("status") == "active" and data.get("slug"):
            active.add(str(data["slug"]))
    return active


def _project_list(value) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if str(item or "").strip()]


def _note_path(root: Path, rel: str) -> Path:
    folder = (root / THOUGHTS_DIR).resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(folder)
    except ValueError as exc:
        raise NotesError(f"--path {rel!r} is not a note under {THOUGHTS_DIR}/") from exc
    if path.suffix != ".md":
        raise NotesError(f"--path {rel!r} is not a markdown note")
    return root / rel


def harvest(root: Path) -> dict:
    found: List[dict] = []
    warnings: List[str] = []
    folder = root / THOUGHTS_DIR
    active = _active_projects(root)
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc} — not read tonight")
            continue
        if data.get("include") is not True:
            continue
        projects = _project_list(data.get("projects"))
        unknown = [p for p in projects if p not in active]
        if unknown:
            warnings.append(f"{rel}: projects {unknown} name no active project — ignored")
        entry = {
            "path": rel,
            "title": path.stem,
            "projects": [p for p in projects if p in active],
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"),
            "body": body,
        }
        if len(body) > MAX_BODY_CHARS:
            entry["body"] = None
            warnings.append(f"{rel}: {len(body)} characters, over the {MAX_BODY_CHARS} "
                            "cap — not read tonight; split it into shorter notes")
        found.append(entry)
    return {"notes": found, "warnings": warnings}


def assign(root: Path, rel: str, projects: List[str]) -> dict:
    path = _note_path(root, rel)
    active = _active_projects(root)
    for slug in projects:
        try:
            naming.validate_slug(slug)
        except ValueError as exc:
            raise NotesError(f"project {slug!r}: {exc}") from exc
        if slug not in active:
            raise NotesError(f"project {slug!r} is not an active project")
    if not path.is_file():
        raise NotesError(f"--path {rel!r} does not exist")
    text = path.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    current = _project_list(data.get("projects"))
    if current or not projects:
        return {"path": rel, "projects": current, "written": False}
    vault.atomic_write(path, markdown.upsert_scalar_field(
        text, "projects", "[{}]".format(", ".join(projects))))
    return {"path": rel, "projects": list(projects), "written": True}


def mark_absorbed(root: Path, rel: str, date_iso: str) -> dict:
    if not vault.ISO_DATE_RE.match(str(date_iso or "")):
        raise NotesError(f"--date {date_iso!r} must be ISO YYYY-MM-DD")
    path = _note_path(root, rel)
    if not path.is_file():
        return {"path": rel, "status": "missing"}
    text = path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "include", "false")
    updated = markdown.upsert_scalar_field(updated, "absorbed", date_iso)
    if updated == text:
        return {"path": rel, "status": "unchanged"}
    vault.atomic_write(path, updated)
    return {"path": rel, "status": "marked"}
```

In `plugin/lib/vaultlib/cli.py`:
- add `notes` to the `from vaultlib import …` line (alphabetical, after `msgstate`)
- add the parser group next to `daily-note`:

```python
    notes_group = top.add_parser("notes", help="the owner's own notes: Include and absorbed")
    notes_sub = notes_group.add_subparsers(dest="action", required=True)
    notes_harvest = notes_sub.add_parser("harvest", help="list notes ticked Include")
    _add_vault_argument(notes_harvest)
    notes_assign = notes_sub.add_parser(
        "assign", help="write projects on a note whose projects is empty")
    _add_vault_argument(notes_assign)
    notes_assign.add_argument("--path", required=True)
    notes_assign.add_argument("--projects", required=True, help="comma-separated slugs")
    notes_mark = notes_sub.add_parser(
        "mark-absorbed", help="untick Include and stamp absorbed: <date>")
    _add_vault_argument(notes_mark)
    notes_mark.add_argument("--path", required=True)
    notes_mark.add_argument("--date", required=True)
```

- in `_dispatch`, before `if args.group == "migrate":`:

```python
    if args.group == "notes":
        if args.action == "harvest":
            return _ok(notes.harvest(root))
        if args.action == "assign":
            slugs = [s.strip() for s in args.projects.split(",") if s.strip()]
            return _ok(notes.assign(root, args.path, slugs))
        return _ok(notes.mark_absorbed(root, args.path, args.date))
```

- in `main`'s `try`, next to the other handlers:

```python
    except notes.NotesError as exc:
        return _fail(str(exc), "Fix the named path, project or date and retry.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_notes.py -q`
Expected: all pass. If `split_frontmatter` returns a different shape for a note without frontmatter (`plain.md`), adapt `harvest` (not the test): such a note is simply not included.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/vault.py plugin/lib/vaultlib/notes.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_notes.py
git commit -m "feat(notes): harvest, assign and mark-absorbed for the owner's own notes"
```

---

### Task 2: Update queue: an included note queues its projects

**Files:**
- Modify: `plugin/lib/vaultlib/updatequeue.py` (imports; `run()` around the queue loop at `:395-415`)
- Test: `scripts/tests/test_vaultlib_updatequeue.py`

**Interfaces:**
- Consumes: `notes.harvest(root)` from Task 1
- Produces: each `projectsNeedingUpdate` entry gains `"newNotes": [vault-relative paths]`. `newCount` includes them.

- [ ] **Step 1: Write the failing tests** (append to `scripts/tests/test_vaultlib_updatequeue.py`)

```python
def write_owner_note(root: Path, name: str, frontmatter: str) -> None:
    folder = root / "80-thoughts-ideas"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(f"---\n{frontmatter}---\nthought\n", encoding="utf-8")


def test_an_included_note_queues_a_project_with_no_new_meetings(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    write_owner_note(root, "idea.md", "include: true\nprojects: [acme-crm]\n")
    result = updatequeue.run(root, "2026-06-21", "owner-morgan")
    [entry] = result["projectsNeedingUpdate"]
    assert entry["slug"] == "acme-crm"
    assert entry["newNotes"] == ["80-thoughts-ideas/idea.md"]
    assert entry["newFiles"] == [] and entry["newCount"] == 1


def test_unticked_unlinked_and_inactive_notes_queue_nothing(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    write_project(root, "acme-old", status="closed")
    write_owner_note(root, "a.md", "include: false\nprojects: [acme-crm]\n")
    write_owner_note(root, "b.md", "include: true\n")
    write_owner_note(root, "c.md", "include: true\nprojects: [acme-old]\n")
    assert updatequeue.run(root, "2026-06-21", "owner-morgan")["projectsNeedingUpdate"] == []


def test_an_oversized_note_does_not_queue(tmp_path):
    from vaultlib import notes
    root = make_vault(tmp_path)
    write_project(root, "acme-crm", last_updated="2026-06-20",
                  state_updated="2026-06-20T18:00")
    folder = root / "80-thoughts-ideas"
    folder.mkdir()
    (folder / "long.md").write_text(
        "---\ninclude: true\nprojects: [acme-crm]\n---\n" + "x" * (notes.MAX_BODY_CHARS + 1),
        encoding="utf-8")
    assert updatequeue.run(root, "2026-06-21", "owner-morgan")["projectsNeedingUpdate"] == []


def test_every_queue_entry_carries_new_notes(tmp_path):
    root = make_vault(tmp_path)
    write_project(root, "acme-crm")
    write_meeting(root, "10-06-26-x", projects=["acme-crm"])
    [entry] = updatequeue.run(root, "2026-06-21", "owner-morgan")["projectsNeedingUpdate"]
    assert entry["newNotes"] == []
```

- [ ] **Step 2: Run them and verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -q -k "note"`
Expected: FAIL with `KeyError: 'newNotes'` and an empty queue.

- [ ] **Step 3: Implement**

In `updatequeue.py`, add `notes` to the `from . import …` line. In `run()`, right after `warnings.extend(log_warnings)`:

```python
    # Notes the owner ticked Include. Harvest warnings are not repeated here:
    # stage 2 already ran `notes harvest` and carries them into the run.
    included = [n for n in notes.harvest(root)["notes"] if n["body"] is not None]
```

Inside the project loop, after `new_logs = …`:

```python
        new_notes = [n["path"] for n in included if slug in n["projects"]]
```

Change the queue condition and entry:

```python
        if new_meetings or new_logs or removed or new_notes:
            queue.append({
                ...
                "newCount": len(new_meetings) + len(new_logs) + len(new_notes),
                "newFiles": [m["file"] for m in new_meetings],
                "newLogs": new_logs,
                "newNotes": new_notes,
                ...
            })
```

- [ ] **Step 4: Run the whole file**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -q`
Expected: all pass. If an existing test asserts an entry dict with `==`, add `"newNotes": []` to its expectation.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/updatequeue.py scripts/tests/test_vaultlib_updatequeue.py
git commit -m "feat(update-queue): a note ticked Include queues its projects"
```

---

### Task 3: A decision may name an owner note as its source

**Files:**
- Modify: `plugin/lib/vaultlib/decision.py:234-255` (`_resolve_source`)
- Test: `scripts/tests/test_vaultlib_decision.py`

**Interfaces:**
- Consumes: `vault.THOUGHTS_DIR` (Task 1)
- Produces: `decision.write(..., payload={"source": "<note stem>"})` resolves notes in `80-thoughts-ideas/`, including subfolders

- [ ] **Step 1: Write the failing test** (append, next to `test_source_may_name_a_log`)

```python
def test_source_may_name_an_owner_note_even_in_a_subfolder(tmp_path):
    root = vault_with_project(tmp_path, "acme-industries-operating-model")
    folder = root / "80-thoughts-ideas" / "clients"
    folder.mkdir(parents=True)
    (folder / "Pricing idea.md").write_text("---\ninclude: true\n---\nx\n", encoding="utf-8")
    assert decision._resolve_source(root, "[[Pricing idea]]") == "Pricing idea"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest scripts/tests/test_vaultlib_decision.py -q -k owner_note`
Expected: FAIL with `DecisionError: source 'Pricing idea' matches no meeting note`.

- [ ] **Step 3: Implement.** Replace the lookup and message in `_resolve_source`:

```python
    found = _find_note(root / MEETINGS_DIR, stem)
    if found is None:
        found = _find_note(root / vault.MESSAGES_DIR, stem)
    if found is None:
        thoughts = root / vault.THOUGHTS_DIR
        lowered = stem.lower()
        found = next((p for p in sorted(thoughts.rglob("*.md"))
                      if p.stem.lower() == lowered), None) if thoughts.is_dir() else None
    if found is None:
        raise DecisionError(
            f"source {stem!r} matches no meeting note at {MEETINGS_DIR}/{stem}.md, "
            f"no log at {vault.MESSAGES_DIR}/{stem}.md and no note in "
            f"{vault.THOUGHTS_DIR}/ — omit 'source' and put the provenance in the 'why' text"
        )
    return found.stem
```

Update the docstring: "…a meeting, a message log or one of the owner's own notes."

- [ ] **Step 4: Run the decision tests**

Run: `python -m pytest scripts/tests/test_vaultlib_decision.py -q`
Expected: all pass. `test_a_source_that_matches_no_meeting_is_refused_with_the_alternative` still matches `omit 'source'`.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/decision.py scripts/tests/test_vaultlib_decision.py
git commit -m "feat(decision): an owner note can be a decision's source"
```

---

### Task 4: Daily note: `## End of day` becomes `## Notes`

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py:522` (render), `:753-825` (read)
- Modify: `plugin/template/99-workflow-config/reference/ontology.md:483` and `:500`
- Test: `scripts/tests/test_vaultlib_dailynote.py`, `scripts/tests/test_compile_ontology.py:40`

**Interfaces:**
- Produces: `dailynote.read(...)` returns `"notes": [str]`, with `"end_of_day"` as an alias carrying the same list for one release. A fresh note renders `## Notes`.

- [ ] **Step 1: Write and adjust the tests**

In `test_vaultlib_dailynote.py`:
- In the fresh-render contract text used by `test_fresh_render_matches_the_contract_exactly` (the block around line 126), change `## End of day` to `## Notes`.
- In the merge test around line 169, change the replace to `jotted.replace("## Notes\n- \n", "## Notes\n- long day; Meridian steady\n")`.
- Leave the read fixtures that write `## End of day` (lines 82, 358, 409, 474, 1069, 1388) **as they are**. They now exercise the legacy heading.
- Add:

```python
def test_read_takes_the_notes_heading_and_the_old_end_of_day_alike(tmp_path):
    root = make_vault(tmp_path)    # use this file's existing vault helper if it differs
    folder = root / "60-daily-notes"
    (folder / "2026-10-06.md").write_text(
        "---\ndate: 2026-10-06\ntype: daily-note\n---\n\n# 2026-10-06 · Tuesday\n\n"
        "## Notes\n- call Dana about the pilot\n", encoding="utf-8")
    (folder / "2026-10-05.md").write_text(
        "---\ndate: 2026-10-05\ntype: daily-note\n---\n\n# 2026-10-05 · Monday\n\n"
        "## End of day\n- wrap up\n", encoding="utf-8")
    new = dailynote.read(root, "2026-10-06")
    old = dailynote.read(root, "2026-10-05")
    assert new["notes"] == ["call Dana about the pilot"] == new["end_of_day"]
    assert old["notes"] == ["wrap up"] == old["end_of_day"]
```

In `test_compile_ontology.py:40`, expect `["Recap", "Meetings", "Notes"]`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_compile_ontology.py -q`
Expected: the contract test, the merge test, the new test and the ontology test fail.

- [ ] **Step 3: Implement**

In `dailynote._render`, change `parts += ["", "## End of day", "- ", ""]` to:

```python
    parts += ["", "## Notes", "- ", ""]
```

In `read`, rename the list and accept both headings:

```python
    day_notes: List[str] = []
    ...
        if section in ("Notes", "End of day"):     # End of day: before structure 11
            day_notes.append(content)
    ...
        "notes": day_notes, "end_of_day": day_notes, "other_lines": other_lines,
```

In `ontology.md`, change `body_sections: [Recap, Meetings, End of day]` to `body_sections: [Recap, Meetings, Notes]`. Change the human-territory bullet to: "jotting bullets under each meeting heading, `## Notes` (called `## End of day` on notes before structure 11; both are read), anything else."

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_compile_ontology.py -q`
Expected: all pass. If `compile_ontology` writes a generated artifact (check `scripts/compile_ontology.py` for an output path), regenerate it with that script and include it in the commit.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py plugin/template/99-workflow-config/reference/ontology.md scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_compile_ontology.py
git commit -m "feat(daily-note): End of day becomes Notes; both headings are read"
```

---

### Task 5: Recap: "your notes read" and "still in Input" lines

**Files:**
- Modify: `plugin/lib/vaultlib/recap.py` (`_ALLOWED`, `validate`, `render`, new `_input_waiting`)
- Test: `scripts/tests/test_vaultlib_recap.py` (create it if absent; otherwise append; check with `ls scripts/tests | grep recap`)

**Interfaces:**
- Consumes: `vault.THOUGHTS_DIR`, `vault.INBOX_DIR`
- Produces:
  - recap payload key `notes_read`: an optional list of `{"path": "80-thoughts-ideas/…md", "projects": [slug]}`. `validate` refuses a path outside the folder or a missing file. Unknown projects go through `_identity_link`, like every other identity.
  - `render` appends, inside the glance callout, `> - **Your notes:** read N → <project links or "not linked to a project">` when `notes_read` is non-empty, and `> - **Still in Input:** N item(s) the evening run could not process → [[99-workflow-config/views/Input.base|Input]]` when `10-inbox/` holds anything other than `README.md`, `*.base` and dotfiles.

- [ ] **Step 1: Write the failing tests**

```python
"""Recap lines the CLI computes: notes read, items still in Input."""
from pathlib import Path

import pytest

from vaultlib import recap

from test_vaultlib_vault import make_vault


def payload(**extra):
    base = {"glance": {"headlines": [{"label": "Quiet", "text": "A calm day."}], "entities": []}}
    base.update(extra)
    return base


def project(root: Path, slug: str):
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True)
    (folder / "index.md").write_text(
        f'---\ntype: project\nproject-name: "CRM rollout"\nslug: {slug}\nstatus: active\n---\n',
        encoding="utf-8")


def rendered(root, raw):
    clean, offenders, _ = recap.validate(root, raw)
    assert offenders == []
    return recap.render(root, clean, meetings=0, window_label="on Monday")


def test_notes_read_line_names_the_projects(tmp_path):
    root = make_vault(tmp_path)
    project(root, "acme-crm")
    (root / "80-thoughts-ideas").mkdir()
    (root / "80-thoughts-ideas" / "idea.md").write_text("x", encoding="utf-8")
    out = rendered(root, payload(notes_read=[{"path": "80-thoughts-ideas/idea.md",
                                              "projects": ["acme-crm"]}]))
    line = next(l for l in out.splitlines() if "**Your notes:**" in l)
    assert "read 1" in line and "CRM rollout" in line


def test_notes_read_without_projects_says_not_linked(tmp_path):
    root = make_vault(tmp_path)
    (root / "80-thoughts-ideas").mkdir()
    (root / "80-thoughts-ideas" / "idea.md").write_text("x", encoding="utf-8")
    out = rendered(root, payload(notes_read=[{"path": "80-thoughts-ideas/idea.md", "projects": []}]))
    assert "not linked to a project" in out


def test_notes_read_refuses_a_path_outside_the_folder(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(recap.RecapError, match="80-thoughts-ideas"):
        recap.validate(root, payload(notes_read=[{"path": "95-private/x.md", "projects": []}]))


def test_no_notes_no_line(tmp_path):
    root = make_vault(tmp_path)
    assert "**Your notes:**" not in rendered(root, payload())


def test_still_in_input_counts_real_files_only(tmp_path):
    root = make_vault(tmp_path)
    inbox = root / "10-inbox"
    (inbox / "README.md").write_text("x", encoding="utf-8")
    (inbox / ".DS_Store").write_bytes(b"\x00")
    assert "Still in Input" not in rendered(root, payload())
    (inbox / "call.txt").write_text("x", encoding="utf-8")
    (inbox / "deck.pdf").write_bytes(b"%PDF")
    line = next(l for l in rendered(root, payload()).splitlines() if "Still in Input" in l)
    assert "2 items" in line and "Input.base|Input" in line
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_recap.py -q`
Expected: FAIL with `RecapError: recap: unknown key(s) ['notes_read']` and the missing lines.

- [ ] **Step 3: Implement**

In `recap.py`:
- `from . import links, markdown, vault`
- add `"notes_read"` to `_ALLOWED`
- in `validate`, before building `clean`:

```python
    notes_read = []
    for i, item in enumerate(raw.get("notes_read") or []):
        if not isinstance(item, dict) or set(item) != {"path", "projects"}:
            raise RecapError(f"recap.notes_read[{i}] needs exactly path and projects")
        rel = str(item["path"])
        if not rel.startswith(vault.THOUGHTS_DIR + "/") or not (root / rel).is_file():
            raise RecapError(f"recap.notes_read[{i}].path {rel!r} is not a note in "
                             f"{vault.THOUGHTS_DIR}/")
        notes_read.append([_identity_link(root, "project", str(slug),
                                          f"recap.notes_read[{i}].projects",
                                          offenders, warnings)
                           for slug in item["projects"] or []])
```

and add `"notes_read": notes_read` to `clean`.

- in `render`, after the `Touched` line and before `parts.append("\n".join(glance))`:

```python
    if clean.get("notes_read"):
        linked = sorted({link for links_ in clean["notes_read"] for link in links_ if link})
        target = " · ".join(linked) if linked else "not linked to a project"
        glance.append(f"> - **Your notes:** read {len(clean['notes_read'])} → {target}")
    waiting = _input_waiting(root)
    if waiting:
        glance.append(f"> - **Still in Input:** {_plural(waiting, 'item')} the evening run "
                      "could not process → [[99-workflow-config/views/Input.base|Input]]")
```

- add:

```python
def _input_waiting(root: Path) -> int:
    """Files still in 10-inbox/ when the recap renders. The sync has already
    run by then, so anything left is something it could not process — a count,
    computed here, so it cannot be forgotten and needs no state."""
    folder = Path(root) / vault.INBOX_DIR
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.rglob("*") if p.is_file()
               and p.name != "README.md" and p.suffix != ".base"
               and not p.name.startswith("."))
```

Check what `_identity_link` returns for an unknown slug (it appends to `offenders`). The test for unknown projects relies on that existing behaviour, so don't special-case it.

- [ ] **Step 4: Run the recap tests, then the daily-note tests that render recaps**

Run: `python -m pytest scripts/tests/test_vaultlib_recap.py scripts/tests/test_vaultlib_dailynote.py -q`
Expected: all pass. A daily-note test whose vault has files in `10-inbox/` will now gain the *Still in Input* line. If an exact-text assertion breaks for that reason, remove the inbox file from that test's fixture. Don't weaken the assertion.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/recap.py scripts/tests/test_vaultlib_recap.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "feat(recap): say which of your notes were read and what is still in Input"
```

---

### Task 6: Template: Input table, Thoughts & ideas views, menu, words

**Files:**
- Delete: `plugin/template/99-workflow-config/views/Inbox.base`
- Create: `plugin/template/99-workflow-config/views/Input.base`
- Modify: `plugin/template/80-thoughts-ideas/Thoughts & ideas.base`
- Modify: `plugin/template/.obsidian/bookmarks.json` (the new menu order; see Step 3)
- Modify: `plugin/template/.obsidian/snippets/sb-accelerator.css:147,163,182` (`data-path="Inbox"` → `data-path="Input"`; keep colour and icon)
- Modify: `plugin/lib/vaultlib/template.py:80` (`Inbox.base` → `Input.base` in `MANAGED_SILENT`)
- Modify: `plugin/template/10-inbox/README.md`, `plugin/template/Start here.md:14`, `plugin/template/How it works.md:43,46`, `plugin/template/CLAUDE.md:26,33,84-95`
- Modify: `plugin/template/99-workflow-config/reference/ontology.md` (new section "Your note")
- Modify: `plugin/lib/vaultlib/health.py:482` (`## Inbox & sync` → `## Input & sync`) and the health test that pins it, if any
- Test: `scripts/tests/test_template_config.py` (`EXPECTED_MENU`, new tests)

**Interfaces:**
- Produces: template path `99-workflow-config/views/Input.base`; bookmark title `Input`. Migration 010 (Task 7) writes exactly this menu.

- [ ] **Step 1: Write the failing tests** in `test_template_config.py`

Replace `EXPECTED_MENU` and `EXPECTED_LIBRARY` with the menu the owner approved on 2026-10-06:

```python
EXPECTED_MENU = [
    ("Start here", "Start here.md"),
    ("Daily notes", "60-daily-notes/Daily notes.base"),
    ("Thoughts & ideas", "80-thoughts-ideas/Thoughts & ideas.base"),
    ("Meetings", "20-meetings/Meetings.base"),
    ("Projects", "30-projects/Projects.base"),
    ("People", "50-people/People.base"),
    ("Entities", "40-entities/Entities.base"),
    ("Decisions", "30-projects/Decisions.base"),
    ("Input", "99-workflow-config/views/Input.base"),
]
EXPECTED_LIBRARY = [
    ("Recent", "99-workflow-config/views/Recent.base"),
    ("Resources", "99-workflow-config/views/Resources.base"),
    ("Heavy assets", "99-workflow-config/views/Heavy assets.base"),
    ("Private", "99-workflow-config/views/Private.base"),
    ("Archive", "99-workflow-config/views/Archive.base"),
]
```

Then add:

```python
def test_input_shows_dropped_files_and_notes_ticked_include():
    import yaml
    base = yaml.safe_load((TEMPLATE / "99-workflow-config" / "views" / "Input.base")
                          .read_text(encoding="utf-8"))
    branches = base["filters"]["or"]
    flat = [" ".join(b["and"]) for b in branches]
    assert any('file.inFolder("10-inbox")' in f and 'file.name != "README"' in f for f in flat)
    assert any('file.inFolder("80-thoughts-ideas")' in f and "include == true" in f
               and 'file.ext == "md"' in f for f in flat)
    assert [v["name"] for v in base["views"]] == ["Tonight"]
    assert base["properties"]["formula.item"]["displayName"] == "Picked up tonight"


def test_thoughts_and_ideas_has_yours_and_absorbed_views():
    import yaml
    base = yaml.safe_load((TEMPLATE / "80-thoughts-ideas" / "Thoughts & ideas.base")
                          .read_text(encoding="utf-8"))
    views = {v["name"]: v for v in base["views"]}
    assert list(views) == ["Yours", "Absorbed"]
    assert "note.include" in views["Yours"]["order"]
    assert views["Absorbed"]["groupBy"] == {"property": "formula.project_group", "direction": "ASC"}
    assert base["properties"]["note.include"]["displayName"] == "Include"


def test_no_owner_facing_template_text_calls_it_the_inbox():
    for rel in ["Start here.md", "How it works.md", "10-inbox/README.md"]:
        text = (TEMPLATE / rel).read_text(encoding="utf-8")
        assert "**Inbox**" not in text and "# Inbox" not in text, rel
```

Update `test_menu_matches_what_migration_009_writes` to load `010-structure-version-11` and rename it `test_menu_matches_what_migration_010_writes`. It will fail until Task 7 lands; that is expected, and Task 7 makes it pass.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest scripts/tests/test_template_config.py -q`
Expected: failures on the menu, the Input base, the Thoughts views and the prose.

- [ ] **Step 3: Implement the template**

`plugin/template/99-workflow-config/views/Input.base`:

```yaml
# Input: everything tonight's evening run picks up — files dropped in
# 10-inbox/ and your own notes ticked Include. Empty the morning after.
filters:
  or:
    - and:
        - file.inFolder("10-inbox")
        - file.name != "README"
        - file.ext != "base"
    - and:
        - file.inFolder("80-thoughts-ideas")
        - file.ext == "md"
        - include == true
formulas:
  item: link(file.path, file.basename)
  kind: if(file.inFolder("80-thoughts-ideas"), "Your note", if(file.ext == "txt", "Text", if(file.ext == "md", "Note", file.ext.upper())))
properties:
  formula.item:
    displayName: Picked up tonight
  formula.kind:
    displayName: Kind
  file.ctime:
    displayName: Added
views:
  - type: table
    name: Tonight
    order:
      - formula.item
      - formula.kind
      - file.ctime
    sort:
      - property: file.ctime
        direction: DESC
    columnSize:
      formula.item: 460
```

`plugin/template/80-thoughts-ideas/Thoughts & ideas.base`:

```yaml
filters:
  and:
    - file.inFolder("80-thoughts-ideas")
    - file.ext == "md"
formulas:
  note: link(file.path, file.basename)
  # Names, not slugs (#240): the project's name, or "Not linked".
  project_group: if(projects, projects.map(if(file("30-projects/" + value + "/index.md"), file("30-projects/" + value + "/index.md").properties["project-name"], value)).join(" · "), "Not linked")
properties:
  formula.note:
    displayName: Note
  formula.project_group:
    displayName: Project
  note.include:
    displayName: Include
  note.absorbed:
    displayName: Absorbed
  file.mtime:
    displayName: Last edited
  file.ctime:
    displayName: Created
views:
  - type: table
    name: Yours
    # Not absorbed yet, or edited on a later day than it was absorbed.
    filters:
      or:
        - absorbed.isEmpty()
        - file.mtime >= absorbed + "1d"
    order:
      - formula.note
      - note.include
      - file.mtime
      - file.ctime
    sort:
      - property: file.mtime
        direction: DESC
    columnSize:
      formula.note: 320
  - type: table
    name: Absorbed
    filters:
      and:
        - "!absorbed.isEmpty()"
    groupBy:
      property: formula.project_group
      direction: ASC
    order:
      - formula.note
      - note.absorbed
      - note.include
    sort:
      - property: note.absorbed
        direction: DESC
    columnSize:
      formula.note: 320
```

`bookmarks.json`: write it as exactly `{"items": <migration 010's shipped_menu()>}` with `json.dumps(..., indent=2, ensure_ascii=False)` plus a trailing newline. That gives the order above, with `ctime` = `1759000000000 + position` for menu entries, `+50` for the Library group and `+60 + position` inside it. Keep any other top-level keys the current file has. CSS: replace the three `data-path="Inbox"` selectors with `data-path="Input"`. `template.py`: `"99-workflow-config/views/Input.base"` in place of `Inbox.base`. `git rm plugin/template/99-workflow-config/views/Inbox.base`.

Prose (owner-facing; plain words, no codes):
- `10-inbox/README.md`: title `# Input`. Opening: "Drop files here — transcripts, voice memos, forwarded emails, documents. The evening run picks them up and moves each one out once it is handled, so this folder (and the **Input** table) is empty the morning after. Your own notes ticked **Include** in Thoughts & ideas show in the same table." Keep the existing rules list, replacing "the inbox" with "Input" where it addresses the owner.
- `Start here.md:14`: replace `**Inbox** — what is waiting to be filed` with `**Input** — what the evening run picks up tonight`. Replace `**Thoughts & ideas** — your own notes; a new note lands here` with `**Thoughts & ideas** — your own notes; tick **Include** to have one read tonight`.
- `How it works.md:43`: "`10-inbox` — **Input**: drop files here; the evening run picks them up." Line 46: "…your own notes. Tick **Include** on a note and the evening run reads it into your projects; the note stays where it is." Add one sentence wherever the daily note is described: "Jot anything under **Notes** on today's note; it is read that evening."
- Template `CLAUDE.md`: the table row for `10-inbox/` gets "Input: unprocessed capture…". The row for `80-thoughts-ideas/` gets "The owner's own notes; read by the evening run when ticked `include`". Retitle `## Inbox Discipline` to `## Input Discipline` and add one paragraph: "The owner's own notes are not capture: they are never moved. Ticking `include` asks the evening run to read one; the run stamps `absorbed: <date>` and unticks it, and never changes the text."
- `ontology.md`: add a section after Daily note:

```markdown
### Your note — `80-thoughts-ideas/**.md` · Base: `Thoughts & ideas.base`

The owner's own writing. Not an object the vault creates; the run only reads
it when asked.

```yaml
object: owner-note
required: []
optional: [include, absorbed, projects]
```

- `include` (checkbox) — the owner's request to read the note tonight.
- `absorbed` (ISO date) — stamped by the evening run when it read the note;
  `include` is unticked in the same write.
- `projects` (project slugs) — set by the owner, or by the run when empty;
  never overwritten.
- The body is never edited, and the note is never moved or deleted.
```

`health.py:482`: `## Input & sync`. Update any test asserting the old heading (`grep -rn "Inbox & sync" scripts/tests`).

- [ ] **Step 4: Run the template checks**

Run: `python scripts/validate_template.py && python -m pytest scripts/tests/test_template_config.py scripts/tests/test_validate_template.py scripts/tests/test_vaultlib_health.py scripts/tests/test_compile_ontology.py -q`
Expected: all pass except `test_menu_matches_what_migration_010_writes` (Task 7). If `compile_ontology` rejects the new `owner-note` block, follow its error to the shape it expects.

- [ ] **Step 5: Commit**

```bash
git add -A plugin/template plugin/lib/vaultlib/template.py plugin/lib/vaultlib/health.py scripts/tests
git commit -m "feat(template): Input table, Include on your notes, plain words"
```

---

### Task 7: Migration 010 → structure 11 (Input, and the new menu order)

**Files:**
- Create: `plugin/migrations/010-structure-version-11/migrate.py`
- Modify: `plugin/template/structure-version` (`11`), `plugin/lib/instantiate_vault.py` (`EXPECTED_STRUCTURE_VERSION = "11"`)
- Test: create `scripts/tests/test_migration_010.py`. Also update:
  - the "run through the framework" expectations in `test_migration_00{1..9}.py`
  - the chain test in `test_migration_009.py`
  - `test_vaultlib_provenance.py`, `test_instantiate_vault.py` and `test_make_test_vault.py`
  - any other test pinning structure 10 (`grep -rn "structure_version\"\: \"10\"\|== 10\b\|\"10\"" scripts/tests`)

**Interfaces:**
- Consumes: the template from Task 6 (its `bookmarks.json` must equal `shipped_menu()` byte-for-value)
- Produces: `TARGET_VERSION = 11`, `LOSSY` (a string: the owner's menu order is reset), `MENU`, `LIBRARY`, `shipped_menu()`, `apply(root) -> dict`, `verify(root) -> dict`, `MigrationError`

The menu after 010, as the owner approved it on 2026-10-06:

```
Start here · Daily notes · Thoughts & ideas · Meetings · Projects · People · Entities · Decisions · Input
▸ Library: Recent · Resources · Heavy assets · Private · Archive
```

- [ ] **Step 1: Write the failing tests** in `scripts/tests/test_migration_010.py`:

```python
"""Migration 010: Inbox becomes Input, the menu takes its new order, and
Inbox.base is removed when unmodified. Made-up vaults only."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vaultlib import migrate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
MIGRATIONS = REPO_ROOT / "plugin" / "migrations"
OBS = Path(".obsidian")
OLD = Path("99-workflow-config/views/Inbox.base")


def load(slug="010-structure-version-11"):
    spec = importlib.util.spec_from_file_location(slug, MIGRATIONS / slug / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shipped_inbox_base() -> bytes:
    """Inbox.base exactly as 0.13.7 shipped it."""
    return subprocess.run(
        ["git", "show", "267043b:plugin/template/99-workflow-config/views/Inbox.base"],
        cwd=REPO_ROOT, capture_output=True, check=True).stdout


def vault_v10(tmp_path: Path, inbox_base: bytes = None) -> Path:
    root = tmp_path / "vault"
    (root / "99-workflow-config" / "views").mkdir(parents=True)
    (root / "structure-version").write_text("10\n", encoding="utf-8")
    (root / OLD).write_bytes(shipped_inbox_base() if inbox_base is None else inbox_base)
    items = load("009-structure-version-10").shipped_menu() + [
        {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}]
    (root / OBS).mkdir()
    (root / OBS / "bookmarks.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return root


def read_items(root):
    return json.loads((root / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 11 and module.LOSSY
    assert [t for t, _ in module.MENU] == [
        "Start here", "Daily notes", "Thoughts & ideas", "Meetings", "Projects",
        "People", "Entities", "Decisions", "Input"]
    assert [t for t, _ in module.LIBRARY] == [
        "Recent", "Resources", "Heavy assets", "Private", "Archive"]


def test_shipped_menu_is_the_template_menu():
    shipped = json.loads((TEMPLATE / OBS / "bookmarks.json").read_text(encoding="utf-8"))["items"]
    assert load().shipped_menu() == shipped


def test_apply_lands_the_new_menu_keeps_the_owners_own_and_removes_inbox_base(tmp_path):
    root = vault_v10(tmp_path)
    module = load()
    assert module.apply(root) == {"bookmarks": "merged", "inbox_base": "removed"}
    items = read_items(root)
    assert items[:len(module.shipped_menu())] == module.shipped_menu()
    assert items[len(module.shipped_menu()):] == [
        {"type": "file", "ctime": 1, "path": "70-resources/mine.md", "title": "Mine"}]
    assert all(i.get("path") != OLD.as_posix() for i in items)
    assert not (root / OLD).exists()


def test_the_owners_own_library_entries_survive_in_my_library(tmp_path):
    root = vault_v10(tmp_path)
    items = read_items(root)
    items[-2]["items"].append({"type": "file", "ctime": 7, "path": "70-resources/x.md", "title": "X"})
    (root / OBS / "bookmarks.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    load().apply(root)
    mine = [i for i in read_items(root) if i.get("title") == "My library"]
    assert mine and mine[0]["items"] == [
        {"type": "file", "ctime": 7, "path": "70-resources/x.md", "title": "X"}]


def test_a_modified_inbox_base_is_kept_and_reported(tmp_path):
    root = vault_v10(tmp_path, inbox_base=shipped_inbox_base() + b"# my tweak\n")
    result = load().apply(root)
    assert result["inbox_base"].startswith("kept")
    assert (root / OLD).is_file()


def test_crlf_copy_of_the_shipped_inbox_base_still_counts_as_unmodified(tmp_path):
    root = vault_v10(tmp_path, inbox_base=shipped_inbox_base().replace(b"\n", b"\r\n"))
    assert load().apply(root)["inbox_base"] == "removed"


def test_apply_is_idempotent(tmp_path):
    root = vault_v10(tmp_path)
    module = load()
    module.apply(root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert module.apply(root) == {"bookmarks": "unchanged", "inbox_base": "absent"}
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_unreadable_bookmarks_stop_the_migration(tmp_path):
    root = vault_v10(tmp_path)
    (root / OBS / "bookmarks.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(load().MigrationError):
        load().apply(root)


def test_the_whole_chain_lands_on_the_shipped_template(tmp_path):
    root = tmp_path / "fresh"
    shutil.copytree(TEMPLATE / ".obsidian", root / ".obsidian")
    (root / "60-daily-notes").mkdir()
    shipped = read_items(root)
    load("009-structure-version-10").apply(root)
    load().apply(root)
    assert read_items(root) == shipped


def test_run_through_the_framework_bumps_to_11(tmp_path):
    root = vault_v10(tmp_path)
    result = migrate.run(root, "2026-10-06", stamp="2026-10-06-120000")
    assert [a["slug"] for a in result["applied"]] == ["structure-version-11"]
    assert result["structure_version"] == 11
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest scripts/tests/test_migration_010.py -q`
Expected: FAIL, the migration file does not exist.

- [ ] **Step 3: Implement** `plugin/migrations/010-structure-version-11/migrate.py`

```python
"""Structure-version 11: Inbox becomes Input, and the menu takes its new order.

The owner approved this menu on 2026-10-06: the places you write sit at the
top (Daily notes, then Thoughts & ideas), the tables you browse follow, and
Input — what tonight's run picks up — closes the main list. The Library
leads with Recent and ends with Archive. In an existing vault this migration:

- writes that menu into `.obsidian/bookmarks.json`, exactly as 009 did: the
  shipped entries first, every bookmark the owner made kept after them, and
  the owner's own entries in the Library group kept in a "My library" group;
- removes `99-workflow-config/views/Inbox.base` when it is identical to what
  0.13.7 shipped (line endings ignored). A copy the owner changed is kept
  and reported — it is theirs.

`Input.base`, the new Thoughts & ideas views, the menu colours, and the
wording in Start here, How it works, the inbox README, CLAUDE.md and the
ontology arrive with the template refresh, like every other managed file.
No note is touched: daily notes keep their `## End of day` heading, which
the reader still accepts. `LOSSY` because a menu order the owner chose
themselves is reset.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 11
LOSSY = ("resets the sidebar menu to its new order (Input last, Thoughts & "
         "ideas under Daily notes); the owner's own bookmarks are kept, after the menu")

BOOKMARKS = Path(".obsidian") / "bookmarks.json"
CTIME = 1759000000000
VIEWS = "99-workflow-config/views"
OLD_INBOX = f"{VIEWS}/Inbox.base"
MENU = [
    ("Start here", "Start here.md"),
    ("Daily notes", "60-daily-notes/Daily notes.base"),
    ("Thoughts & ideas", "80-thoughts-ideas/Thoughts & ideas.base"),
    ("Meetings", "20-meetings/Meetings.base"),
    ("Projects", "30-projects/Projects.base"),
    ("People", "50-people/People.base"),
    ("Entities", "40-entities/Entities.base"),
    ("Decisions", "30-projects/Decisions.base"),
    ("Input", f"{VIEWS}/Input.base"),
]
LIBRARY_TITLE = "Library"
LIBRARY = [
    ("Recent", f"{VIEWS}/Recent.base"),
    ("Resources", f"{VIEWS}/Resources.base"),
    ("Heavy assets", f"{VIEWS}/Heavy assets.base"),
    ("Private", f"{VIEWS}/Private.base"),
    ("Archive", f"{VIEWS}/Archive.base"),
]
# sha256 of Inbox.base as shipped in 0.13.7–0.13.8, LF line endings.
SHIPPED_INBOX_SHA256 = "36d6ea25994b87d932aaf7e1e286313ef27b662a5073c72d6f0c986ffa3eb161"


class MigrationError(Exception):
    """bookmarks.json exists but does not parse."""


def shipped_menu() -> list:
    """The menu exactly as the template's bookmarks.json carries it."""
    items = [{"type": "file", "ctime": CTIME + i, "path": p, "title": t}
             for i, (t, p) in enumerate(MENU)]
    items.append({"type": "group", "ctime": CTIME + 50, "title": LIBRARY_TITLE,
                  "items": [{"type": "file", "ctime": CTIME + 60 + i, "path": p, "title": t}
                            for i, (t, p) in enumerate(LIBRARY)]})
    return items


def _shipped_paths() -> set:
    # The old Inbox entry counts as shipped, so it is replaced, never kept.
    return {p for _, p in MENU} | {p for _, p in LIBRARY} | {OLD_INBOX}


def _merge(data) -> dict:
    existing = data.get("items") if isinstance(data, dict) else None
    existing = existing if isinstance(existing, list) else []
    shipped = _shipped_paths()
    kept = []
    for item in existing:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "group" and item.get("title") == LIBRARY_TITLE:
            extra = [x for x in item.get("items") or []
                     if isinstance(x, dict) and x.get("path") not in shipped]
            if extra:
                kept.append({**item, "title": "My library", "items": extra})
            continue
        if item.get("path") in shipped:
            continue
        kept.append(item)
    out = dict(data) if isinstance(data, dict) else {}
    out["items"] = shipped_menu() + kept
    return out


def _load_bookmarks(root: Path):
    path = root / BOOKMARKS
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MigrationError(
            f"{BOOKMARKS.as_posix()} is not readable JSON ({exc}) — fix or delete it "
            "(the template refresh writes a fresh one) and re-run") from exc


def apply(root: Path) -> dict:
    root = Path(root)
    result = {}
    text = json.dumps(_merge(_load_bookmarks(root)), indent=2, ensure_ascii=False) + "\n"
    path = root / BOOKMARKS
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        result["bookmarks"] = "unchanged"
    else:
        vault.atomic_write(path, text)
        result["bookmarks"] = "merged"

    old = root / OLD_INBOX
    if not old.is_file():
        result["inbox_base"] = "absent"
    elif hashlib.sha256(old.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == SHIPPED_INBOX_SHA256:
        old.unlink()
        result["inbox_base"] = "removed"
    else:
        result["inbox_base"] = (f"kept: {OLD_INBOX} was changed by hand — "
                                "Input.base replaces it in the menu")
    return result


def verify(root: Path) -> dict:
    items = (_load_bookmarks(Path(root)) or {}).get("items") or []
    if items[:len(shipped_menu())] != shipped_menu():
        raise MigrationError(f"{BOOKMARKS.as_posix()}: the new menu did not land")
    return {"checked": ["bookmarks"]}
```

The digest is already pinned. Confirm it once, because the test builds its fixture from the same commit:

```bash
git show 267043b:plugin/template/99-workflow-config/views/Inbox.base | python -c "import sys,hashlib;print(hashlib.sha256(sys.stdin.buffer.read().replace(b'\r\n',b'\n')).hexdigest())"
```

Expected: `36d6ea25994b87d932aaf7e1e286313ef27b662a5073c72d6f0c986ffa3eb161`.

- [ ] **Step 4: Bump the structure version and cascade**

- `plugin/template/structure-version` → `11`
- `plugin/lib/instantiate_vault.py` → `EXPECTED_STRUCTURE_VERSION = "11"`
- In each `test_migration_00N.py` "run through the framework" test, append `"structure-version-11"` to the applied list and expect `structure_version == 11`. Do this the same way #264 did for 10. Where a fixture vault lacks `.obsidian/`, 010 creates `bookmarks.json`; that is intended (009 does the same).
- In `test_migration_009.py`:
  - `test_the_whole_chain_lands_on_the_shipped_template` compares 009's output to the *current* template. Append `load("010-structure-version-11").apply(root)` after 009 in its loop.
  - `test_apply_lands_the_menu_and_keeps_the_owners_own` and `verify` compare against 009's own `shipped_menu()`, which stays historical. Leave them.
- `test_vaultlib_provenance.py`, `test_instantiate_vault.py`, `test_make_test_vault.py`: `"10"` → `"11"`. The managed-file count is unchanged (Inbox.base → Input.base).

Run: `python -m pytest scripts/tests -q`
Expected: all pass, including `test_menu_matches_what_migration_010_writes` from Task 6.

- [ ] **Step 5: Commit**

```bash
git add -A plugin/migrations/010-structure-version-11 plugin/template/structure-version plugin/lib/instantiate_vault.py scripts/tests
git commit -m "feat(migrate): 010 — Inbox becomes Input, menu in its new order (structure 11)"
```

---

### Task 8: Evening-sync wiring, skill prose, version, changelog

**Files:**
- Modify: `plugin/skills/evening-sync/SKILL.md` (stage 2, a new stage-2 paragraph on notes, stage 3c, stage 4 instructions 1/4, a new "after stage 4" write-back paragraph, stage 6 `notes_read`, and the payload example if it carries recap keys)
- Modify: `plugin/skills/sync-recordings/SKILL.md` (owner-facing "inbox" words in report lines only: `**Parked:**` line target text stays a path; the human summary says "Input")
- Modify: `plugin/skills/report-feedback/SKILL.md:154` and `plugin/skills/health-check/SKILL.md:64,171`: owner-facing "inbox" → "Input" (paths unchanged)
- Modify: `plugin/.claude-plugin/plugin.json` (version), `CHANGELOG.md` (Unreleased), plus whatever `scripts/check-plugin-version.sh` and `test_marketplace_manifest.py` require
- Test: `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Consumes: CLI from Task 1, `newNotes` from Task 2, `notes_read` from Task 5, `source` from Task 3

- [ ] **Step 1: Write the failing contract tests** (append to `test_skill_contracts.py`, using the file's existing helper for reading a skill; it is the function the other `test_evening_sync_*` tests call)

```python
def test_evening_sync_absorbs_notes_ticked_include():
    text = _skill("evening-sync")            # use the file's existing reader
    flat = " ".join(text.split())
    assert 'python3 "$VAULTLIB" notes harvest --vault "$VAULT"' in text
    assert 'python3 "$VAULTLIB" notes assign --vault "$VAULT"' in text
    assert 'python3 "$VAULTLIB" notes mark-absorbed --vault "$VAULT"' in text
    assert "newNotes" in text and "(note · [[" in text
    assert "`structure_version` is below 11" in flat
    assert "never changes a note's text" in flat


def test_evening_sync_marks_a_note_only_after_its_projects_were_written():
    flat = " ".join(_skill("evening-sync").split())
    assert "only when every project it was queued for came back with `stateWritten: true`" in flat


def test_evening_sync_reads_the_notes_section_of_the_daily_note():
    text = _skill("evening-sync")
    assert "`notes`" in text and "## Notes" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k "include or notes_section or only_after"`
Expected: FAIL.

- [ ] **Step 3: Write the skill prose** in `evening-sync/SKILL.md`

Stage 2 harvest paragraph: replace "plus the `end_of_day` bullets" with "plus the `notes` bullets (the day's `## Notes` section — `## End of day` on notes written before structure 11; the CLI reads both)".

New paragraph at the end of Stage 2:

````markdown
**Your notes ticked Include.** Run `python3 "$VAULTLIB" migrate status --vault "$VAULT"`.
While `structure_version` is below 11, skip this paragraph — the vault has no
Include yet. Otherwise:

```bash
python3 "$VAULTLIB" notes harvest --vault "$VAULT"
```

Each listed note with a `body` is input tonight, read like a jotting but
longer; a `body: null` note is over the size cap and its warning goes to
`sync_notes`. For a note whose `projects` is empty, pick zero or more active
projects it is about — the same signals as for a meeting that are available
in free text: the project `keywords`, the project and entity names. Then:

```bash
python3 "$VAULTLIB" notes assign --vault "$VAULT" --path "<path>" --projects "<slug>[,<slug>]"
```

Zero projects is a valid answer: skip `assign`, and the note still informs
the recap. `assign` only writes an empty `projects` — never second-guess the
owner's choice. The run never changes a note's text, never moves a note, and
never reads `95-private/`.
````

Stage 3c: in the sentence listing the entry fields, add "`newNotes` (owner notes ticked Include that belong to the project)".

Stage 4, instruction 1: add "When the entry has `newNotes`, read each note end-to-end next to the meetings. Every state item you take from one ends with `(note · [[<note stem>]])`." Instruction 4: change "the new meetings, the harvest jottings AND the message log groups" to "…, the message log groups AND the `newNotes`". Add: "A decision from a note carries `source: <note stem>`."

New paragraph after Stage 4's return-block instruction:

````markdown
**Write-back for your notes.** After every stage-4 batch has returned, mark each
harvested note with a `body` — but only when every project it was queued for
came back with `stateWritten: true`, or when it had no project:

```bash
python3 "$VAULTLIB" notes mark-absorbed --vault "$VAULT" --path "<path>" --date <today>
```

A note whose project failed keeps `include` ticked and is read again tomorrow;
say so in `sync_notes`. `missing` (the owner deleted or moved it during the run)
is not an error.
````

Stage 6: add to the field list "- `notes_read` — one `{path, projects}` per note marked absorbed tonight; the CLI renders the line. Omit it when none were."

If the skill carries a recap payload example that `test_evening_sync_payload_example_is_the_v2_contract` validates, leave the example as it is (`notes_read` is optional).

Other skills: change only owner-facing words, e.g. "saved to the inbox" → "saved to Input (the `10-inbox/` folder)". Run `python -m pytest scripts/tests/test_skill_contracts.py -q`; if a contract test pins the old sentence (e.g. `test_skill_contracts.py:1950`, about mail's Outlook *Inbox* folder, which is **not** ours), leave the Outlook wording alone.

- [ ] **Step 4: Version and changelog**

`git fetch origin && git rebase origin/main`, then bump `plugin/.claude-plugin/plugin.json` to the next patch and anything `scripts/check-plugin-version.sh` checks. Add under `## Unreleased` in `CHANGELOG.md`:

```markdown
- **Inbox is now Input**: the table shows everything the evening run picks up tonight — files you drop in, and your own notes ticked **Include**. It is empty the morning after; if something could not be processed, the recap says so with a link. Your own notes in **Thoughts & ideas** now have an **Include** tick: the evening run reads the note into its project (and logs any decision in it), then unticks it and stamps the date. The note itself is never changed or moved; **Absorbed** shows them by project. On the daily note, **End of day** is now **Notes** — jot anything there, any time. Needs `/upgrade-vault` (structure 11). (#266)
```

Run the full checks:

```bash
python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add -A plugin/skills plugin/.claude-plugin CHANGELOG.md scripts/tests
git commit -m "feat(evening-sync): absorb notes ticked Include; Input in the owner's words"
```

---

### Task 9: Visual verification in a preview vault (manual, required by repo CLAUDE.md)

**Files:** none (verification only)

- [ ] **Step 1:** Build a preview vault from this branch: `python scripts/make_test_vault.py <dir>`. Then run `migrate run` on a copy of `C:\Users\danneelm\sb-preview-latest` (structure 10) to check the upgrade path, followed by `template refresh --all-pending --consent`.
- [ ] **Step 2:** Open each one in the isolated Obsidian instance (off-screen CDP recipe; never the owner's running Obsidian) and screenshot:
  - the menu shows **Input** with the old colour and icon
  - **Input** lists a dropped `.txt` and a note after ticking Include in Thoughts & ideas, with *Kind* = `Your note`
  - **Thoughts & ideas → Yours** shows the Include checkbox column and ticking works from the table
  - after a `notes mark-absorbed`, the note leaves *Yours* and appears in **Absorbed** under the project's **name** (not its slug), and a note without a project groups under *Not linked*
  - editing that note the next day (set its `absorbed` to yesterday to simulate) brings it back into *Yours*
  - a fresh daily note shows `## Notes`
- [ ] **Step 3:** If `file.mtime >= absorbed + "1d"` or `.join(" · ")` doesn't evaluate in Bases, fix the `.base` file (keep the behaviour from the spec) and re-run Task 6's tests. Record what Obsidian accepted in the PR description.
- [ ] **Step 4:** Open the PR with the screenshots. File the two out-of-scope issues from the spec (drag-to-attach; `/report-feedback` saving into `10-inbox/`).
