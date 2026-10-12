# On-demand processing in `/sync-recordings` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calling `/sync-recordings` interactively gets new meetings, asks the owner to accept / dismiss / change them in the chat, processes the accepted ones and the notes ticked Include into project pages and decisions, then asks keep / dismiss on the captured decisions. It never writes a daily note.

**Architecture:** Three small CLI additions (`meeting triage-list` / `triage-apply`, `decision review`, `runlock`) so every write the chat triggers goes through vaultlib, never hand-edited frontmatter. The evening run's processing (Include harvest, stage 3c refresh, stage 4 project-state + decisions, note write-back) moves into one shared reference file, `plugin/skills/evening-sync/references/process.md`, that both skills follow. `/sync-recordings` gains steps 8–11 in interactive mode only.

**Tech Stack:** Python 3 stdlib (`plugin/lib/vaultlib`), pytest (`scripts/tests`), skill markdown.

**Spec:** `docs/superpowers/specs/2026-10-12-on-demand-processing-design.md`

## Global Constraints

- Worktree `C:\Users\danneelm\projects\sb-accelerator-271`, branch `feat/271-on-demand-processing`, base `origin/main` 0.13.11. Never stack on another PR (repo has `delete_branch_on_merge=false`).
- Any PR touching `plugin/` bumps `plugin/.claude-plugin/plugin.json` → **0.13.12** (CI version guard). One CHANGELOG line under `## Unreleased`, client-facing, in the owner's words.
- No vault structure change, no migration. `Start here.md` changes reach vaults through `/upgrade-vault` template refresh.
- CLI output contract: every command prints `{"ok": true, "result": {...}}` or `{"ok": false, "error", "hint"}` via `_ok` / `_fail` in `cli.py`. New error classes must be caught in `cli.main`'s except chain.
- Frontmatter edits use `markdown.replace_scalar_field` / `upsert_scalar_field` (byte-preserving), writes use `vault.atomic_write`. Never re-emit a whole frontmatter block on an existing note.
- `/sync-recordings` never names `60-daily-notes` and never calls `daily-note write`. Steps 8–11 never run under `--unattended`. The on-demand run never reads mail or Teams.
- User-facing wording: "to do's", never "actions"; never "jot"/"jotting"; "entity", not "organisation".
- Windows: set `PYTHONIOENCODING=utf-8` when printing non-ASCII. Two known Windows-flaky tests (`test_migration_001` indented key, `test_vaultlib_entity.py::test_context_bullets_written_across_calls_are_never_dropped_by_the_cap`) are not caused by this work.
- Run tests with: `python -m pytest scripts/tests -q` from the worktree root.

## Review Focus

1. **Owner answers with a project or person that does not exist** ("4 is acme-finanse"): `triage-apply` refuses that item naming the slug, writes nothing for it, and applies the others. Test in Task 1.
2. **Owner accepts a meeting that is a possible duplicate (`conflicts-with` set)**: refused with how to settle it, never confirmed. Test in Task 1.
3. **A previous interactive call crashed holding the lock**: the next interactive call must not be locked out for two hours; the same routine takes its own lock over. Test in Task 3.
4. **Evening run starts while the owner's call is processing**: evening waits, then runs with a warning; the owner's call refused by an evening lock leaves everything in triage. Test (lock semantics) in Task 3; prose contract in Task 6.
5. **A project processed at noon and mail read that evening**: the evening queue re-queues the project because the log's `updated-at` is later; with no new input it does not. Test in Task 4.

---

### Task 1: `meeting triage-list` and `meeting triage-apply`

**Files:**
- Create: `plugin/lib/vaultlib/triage.py`
- Modify: `plugin/lib/vaultlib/cli.py` (import, parser under the `meeting` group, dispatch, except chain)
- Test: `scripts/tests/test_vaultlib_triage.py`

**Interfaces:**
- Produces:
  - `triage.list_queue(root: Path) -> {"items": [item], "warnings": [str]}` where item = `{"path", "title", "date", "type", "projects": [slug], "project_names": [str], "attendees": [slug], "attendee_names": [str], "confidence", "conflicts_with": str|None}`
  - `triage.apply(root: Path, items: list[dict]) -> {"applied": [{"path", "action"}], "refused": [{"path", "reason"}]}`; item = `{"path", "action": "accept"|"dismiss"|"change", "projects"?: [slug], "attendees"?: [slug], "accept"?: bool (change only, default true)}`
  - `triage.TriageError`
  - CLI: `meeting triage-list --vault V`, `meeting triage-apply --vault V --items <file|->`
  - The `meeting` group today dispatches only `write` without checking `args.action`; the dispatch must now branch on it.

- [ ] **Step 1: Write the failing tests**

```python
"""Triage in the chat (#271): the CLI half of accept / dismiss / change."""
from pathlib import Path

import pytest

from vaultlib import triage


def make_vault(tmp_path: Path) -> Path:
    for folder in ("20-meetings", "50-people", "99-workflow-config"):
        (tmp_path / folder).mkdir()
    for slug, name in (("acme-erp", "Acme ERP rollout"),
                       ("acme-finance-close", "Finance close")):
        (tmp_path / "30-projects" / slug).mkdir(parents=True)
        (tmp_path / "30-projects" / slug / "index.md").write_text(
            f'---\ntype: project\nproject-name: "{name}"\nslug: {slug}\n---\n',
            encoding="utf-8")
    for slug, name in (("jan-peeters", "Jan Peeters"), ("sofie-maes", "Sofie Maes")):
        (tmp_path / "50-people" / f"{slug}.md").write_text(
            f'---\nperson-name: "{name}"\nslug: {slug}\n---\n', encoding="utf-8")
    return tmp_path


def write_meeting(root, stem, *, status="needs-review", archived=False,
                  projects="[acme-erp]", conflicts=None, h1="Weekly with Acme"):
    lines = ["---", "date: 2026-10-12T09:00", "type: meeting",
             'calendar-subject: "Weekly"', "attendees: [jan-peeters, sofie-maes]",
             f"projects: {projects}", f"review_status: {status}",
             "reviewed: false", f"archived: {'true' if archived else 'false'}",
             "confidence: medium"]
    if conflicts:
        lines.append(f'conflicts-with: "[[{conflicts}]]"')
    lines += ["---", f"# {h1}", "", "## Key Takeaways", "- x", ""]
    path = root / "20-meetings" / f"{stem}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_list_shows_only_open_triage_with_names(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a-open")
    write_meeting(root, "b-confirmed", status="confirmed")
    write_meeting(root, "c-dismissed", archived=True)
    result = triage.list_queue(root)
    assert [i["path"] for i in result["items"]] == ["20-meetings/a-open.md"]
    item = result["items"][0]
    assert item["title"] == "Weekly with Acme"
    assert item["project_names"] == ["Acme ERP rollout"]
    assert item["attendee_names"] == ["Jan Peeters", "Sofie Maes"]
    assert item["conflicts_with"] is None


def test_list_falls_back_to_calendar_subject_and_reports_conflicts(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a-dup", conflicts="b-other", h1="")
    item = triage.list_queue(root)["items"][0]
    assert item["title"] == "Weekly"
    assert item["conflicts_with"] == "[[b-other]]"


def test_accept_and_dismiss_set_the_same_ticks_as_obsidian(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    b = write_meeting(root, "b")
    result = triage.apply(root, [
        {"path": "20-meetings/a.md", "action": "accept"},
        {"path": "20-meetings/b.md", "action": "dismiss"},
    ])
    assert result["refused"] == []
    assert "reviewed: true" in a.read_text(encoding="utf-8")
    assert "archived: true" in b.read_text(encoding="utf-8")
    assert "reviewed: false" in b.read_text(encoding="utf-8")


def test_change_rewrites_projects_and_accepts_by_default(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "change",
                         "projects": ["acme-finance-close"]}])
    text = a.read_text(encoding="utf-8")
    assert "projects: [acme-finance-close]" in text
    assert "reviewed: true" in text


def test_change_without_accept_leaves_it_in_triage(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "change",
                         "attendees": ["jan-peeters"], "accept": False}])
    text = a.read_text(encoding="utf-8")
    assert "attendees: [jan-peeters]" in text
    assert "reviewed: false" in text


def test_unknown_slug_refuses_that_item_only(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    b = write_meeting(root, "b")
    before = a.read_text(encoding="utf-8")
    result = triage.apply(root, [
        {"path": "20-meetings/a.md", "action": "change", "projects": ["acme-finanse"]},
        {"path": "20-meetings/b.md", "action": "accept"},
    ])
    assert result["refused"][0]["path"] == "20-meetings/a.md"
    assert "acme-finanse" in result["refused"][0]["reason"]
    assert a.read_text(encoding="utf-8") == before
    assert result["applied"] == [{"path": "20-meetings/b.md", "action": "accept"}]


def test_conflicted_note_cannot_be_accepted(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a", conflicts="b-other")
    result = triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    assert "Duplicate" in result["refused"][0]["reason"]
    assert "reviewed: false" in a.read_text(encoding="utf-8")


def test_refuses_paths_outside_meetings_and_bad_actions(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a")
    result = triage.apply(root, [
        {"path": "../outside.md", "action": "accept"},
        {"path": "20-meetings/missing.md", "action": "accept"},
        {"path": "20-meetings/a.md", "action": "approve"},
    ])
    assert len(result["refused"]) == 3
    assert result["applied"] == []


def test_apply_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    a = write_meeting(root, "a")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    once = a.read_text(encoding="utf-8")
    triage.apply(root, [{"path": "20-meetings/a.md", "action": "accept"}])
    assert a.read_text(encoding="utf-8") == once


def test_items_must_be_a_list(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(triage.TriageError):
        triage.apply(root, {"path": "x"})
```

Also add a CLI round-trip in the same file:

```python
import json
import subprocess
import sys

CLI = Path(__file__).resolve().parents[2] / "plugin" / "lib" / "vaultlib" / "cli.py"


def test_cli_round_trip(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "a")
    listed = json.loads(subprocess.run(
        [sys.executable, str(CLI), "meeting", "triage-list", "--vault", str(root)],
        capture_output=True, text=True, check=True).stdout)
    assert listed["ok"] and listed["result"]["items"][0]["path"] == "20-meetings/a.md"
    payload = tmp_path / "triage.payload.json"
    payload.write_text(json.dumps([{"path": "20-meetings/a.md", "action": "accept"}]))
    applied = json.loads(subprocess.run(
        [sys.executable, str(CLI), "meeting", "triage-apply", "--vault", str(root),
         "--items", str(payload)], capture_output=True, text=True, check=True).stdout)
    assert applied["result"]["applied"] == [{"path": "20-meetings/a.md", "action": "accept"}]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_triage.py -q`
Expected: FAIL, `ImportError: cannot import name 'triage'`.

- [ ] **Step 3: Implement `triage.py`**

```python
"""Triage in the chat (#271): list the meetings waiting for review, and apply
the owner's answers to them.

The same three moves as Meetings.base — Keep, Dismiss, edit the row — written
by the CLI, so an answer typed in the chat never becomes a hand edit of
frontmatter. Confirming is still `sync reconcile-reviews`' job: this module
only sets the tick, exactly as Obsidian would, so there is one confirm path.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from . import markdown, naming, vault

MEETINGS_DIR = vault.MEETINGS_DIR
ACTIONS = ("accept", "dismiss", "change")


class TriageError(Exception):
    """An argument the caller must fix (not a per-item refusal)."""


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _title(data: dict, body: str, stem: str) -> str:
    for line in body.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return str(data.get("calendar-subject") or stem)


def _project_index(root: Path, slug: str) -> Path:
    return root / vault.PROJECTS_DIR / slug / "index.md"


def _person_note(root: Path, slug: str) -> Path:
    return root / vault.PEOPLE_DIR / f"{slug}.md"


def _name(path: Path, key: str, slug: str) -> str:
    try:
        data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return slug
    return str(data.get(key) or slug)


def list_queue(root: Path) -> dict:
    items: List[dict] = []
    warnings: List[str] = []
    folder = root / MEETINGS_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            warnings.append(f"{rel}: {exc}")
            continue
        if data.get("review_status") != "needs-review" or data.get("archived") is True:
            continue
        projects = _as_list(data.get("projects"))
        attendees = _as_list(data.get("attendees"))
        items.append({
            "path": rel,
            "title": _title(data, body, path.stem),
            "date": str(data.get("date") or ""),
            "type": data.get("type"),
            "projects": projects,
            "project_names": [_name(_project_index(root, s), "project-name", s)
                              for s in projects],
            "attendees": attendees,
            "attendee_names": [_name(_person_note(root, s), "person-name", s)
                               for s in attendees],
            "confidence": data.get("confidence"),
            "conflicts_with": data.get("conflicts-with") or None,
        })
    items.sort(key=lambda item: (item["date"], item["path"]))
    return {"items": items, "warnings": warnings}


def _flow_list(values: List[str]) -> str:
    return "[" + ", ".join(values) + "]"


def _check_slugs(root: Path, values, key: str, exists) -> Optional[str]:
    if not isinstance(values, list):
        return f"{key} must be a list of slugs"
    for value in values:
        try:
            naming.validate_slug(str(value))
        except ValueError as exc:
            return f"{key} entry {value!r}: {exc}"
        if not exists(root, str(value)).is_file():
            return f"{key} entry {value!r} matches no note — check the spelling"
    return None


def _apply_one(root: Path, item) -> Optional[str]:
    """Returns a refusal reason, or None once the item is written."""
    if not isinstance(item, dict):
        return "each item must be an object"
    action = item.get("action")
    if action not in ACTIONS:
        return f"action {action!r} is not one of {list(ACTIONS)}"
    raw = str(item.get("path") or "")
    target = (root / raw).resolve()
    meetings = (root / MEETINGS_DIR).resolve()
    if target.parent != meetings or target.suffix != ".md":
        return f"{raw!r} is not a meeting note in {MEETINGS_DIR}/"
    if not target.is_file():
        return f"{raw!r} does not exist"
    text = target.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    if data.get("review_status") != "needs-review":
        return f"{raw!r} is not waiting for review"
    accept = action == "accept" or (action == "change" and item.get("accept", True))
    if accept and data.get("conflicts-with"):
        return ("possible Duplicate of another note — merge or delete one of "
                "the two, clear '⚠ Duplicate of' in Obsidian, then accept")
    updated = text
    if action == "change":
        if "projects" not in item and "attendees" not in item:
            return "change needs projects and/or attendees"
        if "projects" in item:
            problem = _check_slugs(root, item["projects"], "projects", _project_index)
            if problem:
                return problem
            updated = markdown.upsert_scalar_field(
                updated, "projects", _flow_list(item["projects"]))
        if "attendees" in item:
            problem = _check_slugs(root, item["attendees"], "attendees", _person_note)
            if problem:
                return problem
            updated = markdown.upsert_scalar_field(
                updated, "attendees", _flow_list(item["attendees"]))
    if accept:
        updated = markdown.upsert_scalar_field(updated, "reviewed", "true")
    if action == "dismiss":
        updated = markdown.upsert_scalar_field(updated, "archived", "true")
    if updated != text:
        vault.atomic_write(target, updated)
    return None


def apply(root: Path, items) -> dict:
    if not isinstance(items, list):
        raise TriageError("--items must be a JSON array of {path, action, ...}")
    applied: List[dict] = []
    refused: List[dict] = []
    for item in items:
        try:
            reason = _apply_one(root, item)
        except (ValueError, OSError) as exc:
            reason = str(exc)
        path = item.get("path") if isinstance(item, dict) else None
        if reason is None:
            applied.append({"path": path, "action": item["action"]})
        else:
            refused.append({"path": path, "reason": reason})
    return {"applied": applied, "refused": refused}
```

Note: `projects` written `[]` when the owner removes every project is valid (`_flow_list([])` → `[]`).

- [ ] **Step 4: Wire the CLI**

In `cli.py`: add `triage` to the `from vaultlib import ...` line (alphabetical). In `build_parser`, under the `meeting` group next to `meeting_write`:

```python
    triage_list = meetings_sub.add_parser(
        "triage-list", help="meetings waiting for review, with names (#271)")
    _add_vault_argument(triage_list)
    triage_apply = meetings_sub.add_parser(
        "triage-apply", help="apply the owner's accept / dismiss / change answers")
    _add_vault_argument(triage_apply)
    triage_apply.add_argument("--items", required=True,
                              help="path to a JSON array, or - to read stdin")
```

Replace the `meeting` dispatch:

```python
    if args.group == "meeting":
        if args.action == "triage-list":
            return _ok(triage.list_queue(root))
        if args.action == "triage-apply":
            items = (json.load(sys.stdin) if args.items == "-"
                     else json.loads(Path(args.items).read_text(encoding="utf-8")))
            return _ok(triage.apply(root, items))
        payload = (json.load(sys.stdin) if args.note == "-"
                   else json.loads(Path(args.note).read_text(encoding="utf-8")))
        return _ok(meeting.write(root, payload,
                                 accept_collision=args.accept_collision))
```

Check that `meetings_sub` uses `dest="action"`; if it does not, add it. In the except chain, after `meeting.MeetingError`:

```python
    except triage.TriageError as exc:
        return _fail(str(exc), "Pass a JSON array of {path, action} items.")
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_triage.py scripts/tests/test_vaultlib_cli.py scripts/tests/test_vaultlib_meeting.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/triage.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_triage.py
git commit -m "feat(#271): meeting triage-list / triage-apply for triage in the chat"
```

---

### Task 2: `decision review --keep|--dismiss`

**Files:**
- Modify: `plugin/lib/vaultlib/decision.py` (new `review` function)
- Modify: `plugin/lib/vaultlib/cli.py` (parser + dispatch under `decision`)
- Test: `scripts/tests/test_vaultlib_decision.py` (append)

**Interfaces:**
- Produces: `decision.review(root: Path, path: str, *, keep: bool) -> {"path", "project", "summary", "reviewed": bool, "dismissed": bool, "supersedes": str|None}`. CLI: `decision review --vault V --path <rel> (--keep | --dismiss)`.

- [ ] **Step 1: Write the failing tests** (append to `test_vaultlib_decision.py`; reuse that file's existing vault/project fixture helper if it has one, otherwise this local one)

```python
def _decision_vault(tmp_path):
    folder = tmp_path / "30-projects" / "acme-erp" / "decisions"
    folder.mkdir(parents=True)
    (tmp_path / "30-projects" / "acme-erp" / "index.md").write_text(
        "---\ntype: project\nslug: acme-erp\n---\n", encoding="utf-8")
    note = folder / "2026-10-12-go-live-moves.md"
    note.write_text(
        '---\ntype: decision\nproject: acme-erp\ndate: 2026-10-12\nstatus: active\n'
        'summary: "Go-live moves to 3 Nov"\nsupersedes: "2026-09-01-go-live-oct"\n'
        'reviewed: false\n---\n# Go-live moves to 3 Nov\n', encoding="utf-8")
    return tmp_path, note


def test_review_keep_sets_reviewed(tmp_path):
    root, note = _decision_vault(tmp_path)
    result = decision.review(root, note.relative_to(root).as_posix(), keep=True)
    assert result["reviewed"] is True and result["dismissed"] is False
    assert "reviewed: true" in note.read_text(encoding="utf-8")


def test_review_dismiss_sets_archived_and_names_what_it_replaced(tmp_path):
    root, note = _decision_vault(tmp_path)
    result = decision.review(root, note.relative_to(root).as_posix(), keep=False)
    text = note.read_text(encoding="utf-8")
    assert "archived: true" in text and "reviewed: false" in text
    assert result["supersedes"] == "2026-09-01-go-live-oct"


def test_review_refuses_a_non_decision(tmp_path):
    root, _ = _decision_vault(tmp_path)
    with pytest.raises(decision.DecisionError):
        decision.review(root, "30-projects/acme-erp/index.md", keep=True)
    with pytest.raises(decision.DecisionError):
        decision.review(root, "../elsewhere.md", keep=True)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_decision.py -q -k review`
Expected: FAIL, `AttributeError: module 'vaultlib.decision' has no attribute 'review'`.

- [ ] **Step 3: Implement** (append to `decision.py`)

```python
def review(root: Path, path: str, *, keep: bool) -> dict:
    """The owner's Keep or Dismiss on one decision, given in the chat (#271).

    The same two ticks as Decisions.base: Keep is `reviewed: true`, Dismiss is
    `archived: true`. Dismissing never touches a decision this one superseded
    — that one stays `superseded`, as with Dismiss in Obsidian — so the result
    names it for the caller to tell the owner.
    """
    target = (root / path).resolve()
    projects = (root / vault.PROJECTS_DIR).resolve()
    if (target.suffix != ".md" or target.parent.name != "decisions"
            or target.parent.parent.parent != projects):
        raise DecisionError(f"{path!r} is not a decision note under "
                            f"{vault.PROJECTS_DIR}/<project>/decisions/")
    if not target.is_file():
        raise DecisionError(f"{path!r} does not exist")
    text = target.read_text(encoding="utf-8")
    data, _ = markdown.split_frontmatter(text)
    if data.get("type") != "decision":
        raise DecisionError(f"{path!r} is not a decision note (type is "
                            f"{data.get('type')!r})")
    field = "reviewed" if keep else "archived"
    updated = markdown.upsert_scalar_field(text, field, "true")
    if updated != text:
        vault.atomic_write(target, updated)
    data, _ = markdown.split_frontmatter(updated)
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "project": data.get("project"),
        "summary": data.get("summary"),
        "reviewed": data.get("reviewed") is True,
        "dismissed": data.get("archived") is True,
        "supersedes": _unwrap(data.get("supersedes")),
    }
```

If `_unwrap` returns the stem with `[[ ]]` stripped, the test value matches. Otherwise use `canonical_stem`, and keep the test as written.

- [ ] **Step 4: Wire the CLI.** Under `decisions_sub`:

```python
    dec_review = decisions_sub.add_parser(
        "review", help="Keep or Dismiss one decision, as the owner answered (#271)")
    _add_vault_argument(dec_review)
    dec_review.add_argument("--path", required=True, help="vault-relative path")
    verdict = dec_review.add_mutually_exclusive_group(required=True)
    verdict.add_argument("--keep", action="store_true")
    verdict.add_argument("--dismiss", action="store_true")
```

In the `decision` dispatch, after `list`:

```python
        if args.action == "review":
            return _ok(decision.review(root, args.path, keep=args.keep))
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_decision.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/decision.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_decision.py
git commit -m "feat(#271): decision review --keep|--dismiss for decisions in the chat"
```

---

### Task 3: `runlock`

**Files:**
- Create: `plugin/lib/vaultlib/runlock.py`
- Modify: `plugin/lib/vaultlib/cli.py` (new top-level group `runlock`)
- Test: `scripts/tests/test_vaultlib_runlock.py`

**Interfaces:**
- Produces:
  - `runlock.acquire(root, routine: str, *, now: datetime|None=None) -> {"acquired": bool, "took_over": bool, "stale": bool, "holder": {"routine", "started_at", "host"}|None}`
  - `runlock.release(root, routine: str) -> {"released": bool, "holder": {...}|None}`
  - `runlock.LOCK_RELPATH = Path("99-workflow-config") / "sync-state" / "run.lock.json"`, `runlock.MAX_AGE = timedelta(hours=2)`, `runlock.RunLockError`
  - CLI: `runlock acquire --vault V --routine <name> [--now ISO]`, `runlock release --vault V --routine <name>`
- Semantics: no lock, a stale lock (older than 2 h) or a lock held by the **same** routine → acquired (`took_over` true when a lock existed). A fresh lock held by another routine → `acquired: false` with the holder. Release deletes only a lock held by the given routine.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime, timedelta

import pytest

from vaultlib import runlock

T0 = datetime(2026, 10, 12, 12, 0)


def test_acquire_on_free_vault(tmp_path):
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0)
    assert result["acquired"] and not result["took_over"]
    assert (tmp_path / runlock.LOCK_RELPATH).is_file()


def test_fresh_lock_of_another_routine_refuses(tmp_path):
    runlock.acquire(tmp_path, "evening-sync", now=T0)
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0 + timedelta(minutes=30))
    assert result["acquired"] is False
    assert result["holder"]["routine"] == "evening-sync"


def test_stale_lock_is_taken_over(tmp_path):
    runlock.acquire(tmp_path, "evening-sync", now=T0)
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0 + timedelta(hours=3))
    assert result["acquired"] and result["stale"] and result["took_over"]


def test_same_routine_takes_its_own_lock_over(tmp_path):
    """A crashed interactive call must not lock the owner out for two hours."""
    runlock.acquire(tmp_path, "sync-recordings", now=T0)
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0 + timedelta(minutes=5))
    assert result["acquired"] and result["took_over"]


def test_release_only_removes_own_lock(tmp_path):
    runlock.acquire(tmp_path, "evening-sync", now=T0)
    assert runlock.release(tmp_path, "sync-recordings")["released"] is False
    assert (tmp_path / runlock.LOCK_RELPATH).is_file()
    assert runlock.release(tmp_path, "evening-sync")["released"] is True
    assert not (tmp_path / runlock.LOCK_RELPATH).exists()


def test_unreadable_lock_counts_as_stale(tmp_path):
    path = tmp_path / runlock.LOCK_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0)
    assert result["acquired"] and result["stale"]


def test_routine_name_is_validated(tmp_path):
    with pytest.raises(runlock.RunLockError):
        runlock.acquire(tmp_path, "Evening Sync", now=T0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_runlock.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement `runlock.py`**

```python
"""One run at a time (#271).

The owner's on-demand processing and the evening run both rewrite project
pages. Nothing stopped them overlapping before; this lock does, for runs that
see the same vault folder. Two OneDrive copies on two machines each have their
own lock — that case is out of reach of a file lock and is accepted.

A lock older than MAX_AGE is stale (a run that crashed), and a routine may
always take over its own lock (a crashed interactive call must not lock the
owner out for two hours).
"""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from . import vault

LOCK_RELPATH = Path("99-workflow-config") / "sync-state" / "run.lock.json"
MAX_AGE = timedelta(hours=2)
_ROUTINE_RE = re.compile(r"\A[a-z][a-z0-9]*(-[a-z0-9]+)*\Z")


class RunLockError(Exception):
    """An argument the caller must fix."""


def _check(routine: str) -> None:
    if not _ROUTINE_RE.match(routine or ""):
        raise RunLockError(f"routine {routine!r} must be a lowercase slug")


def _read(root: Path) -> Optional[dict]:
    path = root / LOCK_RELPATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        datetime.fromisoformat(data["started_at"])
        return data
    except (ValueError, KeyError, TypeError, OSError):
        return {"routine": None, "started_at": None, "host": None}


def acquire(root: Path, routine: str, *, now: Optional[datetime] = None) -> dict:
    _check(routine)
    now = now or datetime.now()
    holder = _read(root)
    stale = False
    if holder is not None:
        started = holder.get("started_at")
        stale = started is None or now - datetime.fromisoformat(started) > MAX_AGE
        if not stale and holder.get("routine") != routine:
            return {"acquired": False, "took_over": False, "stale": False,
                    "holder": holder}
    mine = {"routine": routine, "started_at": now.isoformat(timespec="minutes"),
            "host": socket.gethostname()}
    path = root / LOCK_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    vault.atomic_write(path, json.dumps(mine, indent=2) + "\n")
    return {"acquired": True, "took_over": holder is not None, "stale": stale,
            "holder": mine}


def release(root: Path, routine: str) -> dict:
    _check(routine)
    holder = _read(root)
    if holder is None or holder.get("routine") != routine:
        return {"released": False, "holder": holder}
    (root / LOCK_RELPATH).unlink()
    return {"released": True, "holder": holder}
```

- [ ] **Step 4: Wire the CLI.** Add `runlock` to the import line. Parser:

```python
    lock = top.add_parser("runlock", help="one run at a time (#271)")
    lock_sub = lock.add_subparsers(dest="action", required=True)
    lock_acquire = lock_sub.add_parser("acquire", help="take the run lock")
    _add_vault_argument(lock_acquire)
    lock_acquire.add_argument("--routine", required=True)
    lock_acquire.add_argument("--now", help="ISO datetime override (tests)")
    lock_release = lock_sub.add_parser("release", help="drop this routine's lock")
    _add_vault_argument(lock_release)
    lock_release.add_argument("--routine", required=True)
```

Dispatch, next to `runlog`:

```python
    if args.group == "runlock":
        if args.action == "acquire":
            now = datetime.fromisoformat(args.now) if args.now else None
            return _ok(runlock.acquire(root, args.routine, now=now))
        return _ok(runlock.release(root, args.routine))
```

Import `datetime` at the top of `cli.py` if it is not already imported. Except chain:

```python
    except runlock.RunLockError as exc:
        return _fail(str(exc), "Pass the routine's slug, e.g. sync-recordings.")
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_runlock.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/runlock.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_runlock.py
git commit -m "feat(#271): runlock so on-demand processing and the evening run never overlap"
```

---

### Task 4: Pin the queue behaviour the design relies on

**Files:**
- Test: `scripts/tests/test_vaultlib_updatequeue.py` (append)

This is a test-only task. It pins existing behaviour (spec "Why the evening run does not redo or lose anything"). If either test fails, stop and report: the design's assumption is wrong.

- [ ] **Step 1: Write the tests** (append to `test_vaultlib_updatequeue.py`; they use the file's own `make_vault`, `write_project`, `write_meeting`, `vault_with_project_and_owner`, `write_log` and `g` helpers)

```python
def test_project_written_at_noon_is_not_requeued_without_new_input(tmp_path):
    """#271: the on-demand run wrote state at 12:00 after the 09:00 meeting
    was accepted at 11:30; the evening run has nothing new for it."""
    root = make_vault(tmp_path)
    write_project(root, "alpha", last_updated="2026-10-12",
                  state_updated="2026-10-12T12:00")
    write_meeting(root, "morning", date_value="2026-10-12T09:00",
                  projects=["alpha"], confirmed_at="2026-10-12T11:30")
    result = updatequeue.run(root, "2026-10-12", "owner-morgan")
    assert result["projectsNeedingUpdate"] == []
    assert not [w for w in result["warnings"] if "SELF-CHECK" in w]


def test_mail_read_in_the_evening_requeues_a_project_written_at_noon(tmp_path):
    """#271: mail from this morning is read by the evening run; its log is
    stamped with the evening write time, so the project queues again."""
    root = vault_with_project_and_owner(
        tmp_path, "acme-industries-rollout", "2026-10-12T12:00")
    write_log(root, "2026-10-12",
              [g("m1", projects=["acme-industries-rollout"])],
              "2026-10-12T21:05")
    queue = updatequeue.run(root, "2026-10-12", "morgan-ellery")[
        "projectsNeedingUpdate"]
    assert [e["slug"] for e in queue] == ["acme-industries-rollout"]
    assert queue[0]["newLogs"] == ["2026-10-12-messages"]
```

- [ ] **Step 2: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -q`
Expected: PASS without any product change.

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/test_vaultlib_updatequeue.py
git commit -m "test(#271): pin that a noon state write neither repeats nor drops evening input"
```

---

### Task 5: Move processing into `evening-sync/references/process.md`

**Files:**
- Create: `plugin/skills/evening-sync/references/process.md`
- Modify: `plugin/skills/evening-sync/SKILL.md` (stage 2 Include paragraph, stage 3c, stage 4)
- Test: `scripts/tests/test_skill_contracts.py` (append; also update any existing assertion that `read_skill("evening-sync")` contains text that moved, by pointing it at `read_ref("evening-sync", "process.md")`)

**Interfaces:**
- Produces: `process.md` with these headings, which the callers refer to by name:
  - `## Inputs` — a table: caller × input. Columns *Evening* and *On demand*. Rows: ticks folded; notes ticked Include; daily-note jottings; To Do's; mail and Teams logs; update-queue.
  - `## A. Your notes ticked Include` — moved verbatim from evening-sync stage 2.
  - `## B. Refresh` — moved verbatim from stage 3c (both `reconcile-reviews` + `update-queue`, including the "second reconcile-reviews is deliberate" paragraph).
  - `## C. Project-state updates` — moved verbatim from stage 4, including the batching rule, the subagent instructions 1–5, "Pin the model", "Why this is a hard batching rule", the straggler paragraph, and the write-back for notes.
  - `## Returns` — what the caller carries into its summary: folded ticks, `projectsNeedingUpdate` slugs, per-project `stateWritten` / `decisionsWritten` / `decisionsSkipped`, notes absorbed / kept, warnings.

- [ ] **Step 1: Write the failing contract tests**

```python
BATCHING_RULE = "Dispatch in blocking batches of at most 3"


def test_processing_lives_in_one_shared_reference():
    """#271: the evening run and the on-demand meeting sync follow the same
    processing text — never two copies that drift."""
    process = read_ref("evening-sync", "process.md")
    for heading in ("## Inputs", "## A. Your notes ticked Include",
                    "## B. Refresh", "## C. Project-state updates", "## Returns"):
        assert heading in process, heading
    assert BATCHING_RULE in process
    for name in ("evening-sync", "sync-recordings"):
        assert "references/process.md" in read_skill(name), name


def test_batching_rule_has_exactly_one_home():
    hits = [p for p in SKILLS_DIR.rglob("*.md")
            if BATCHING_RULE in p.read_text(encoding="utf-8")]
    assert [p.name for p in hits] == ["process.md"]
```

(`sync-recordings` will only point at `process.md` after Task 6, so `test_processing_lives_in_one_shared_reference` stays red until then. That is expected. Commit Task 5 with that one test marked `@pytest.mark.xfail(reason="sync-recordings wired in Task 6", strict=True)`, and remove the mark in Task 6.)

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k "shared_reference or one_home"`
Expected: FAIL (file missing).

- [ ] **Step 3: Create `process.md`.**
  - Header paragraph: "Followed by `/evening-sync` (after stage 3b) and by `/sync-recordings` step 9 (on demand). Everything here runs the same for both callers. Only the inputs differ — see Inputs."
  - Move the three blocks verbatim under sections A–C.
  - Inside them, change only cross-references that named evening stages: "stage 4" → "section C", "stage 6" → "the evening run's stage 6 (recap; on demand: nothing)". "harvest jottings" stays, with "(evening only; on demand there are none)" added at its first mention in C.
  - Write `## Inputs`:

```markdown
## Inputs

| Input | Evening | On demand |
|---|---|---|
| Ticks folded (`reconcile-reviews`, in B) | yes | yes — after the chat triage |
| Notes ticked Include (A) | yes | yes |
| Daily-note jottings (context for C) | yes — from stage 2 | no — they are read in the evening |
| To Do's | yes — evening stage 2 | no |
| Mail and Teams | evening stage 3b runs first | not read; `update-queue` still sees any log already on disk that is newer than a project's last state write |
| Project-state updates and decisions (C) | yes | yes |

On demand, C's subagents get no harvest jottings. Everything else in A–C is
identical: same caps, same batching, same `--background` decision capture.
```

- [ ] **Step 4: Replace the moved text in `evening-sync/SKILL.md`.**
  - Stage 2's *Your notes ticked Include* paragraph becomes one line: "**Your notes ticked Include:** follow section A of `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md`."
  - Stage 3c's body becomes: "Follow section B of `references/process.md`." (keep the heading and the "Runs every evening, whatever stage 3b did" line).
  - Stage 4's body becomes: "Follow section C of `references/process.md`, passing the stage-2 harvest jottings. Record its Returns for stage 7."
  - Keep every stage heading, so stage numbering elsewhere stays valid.

- [ ] **Step 5: Fix any contract test that read moved text from `read_skill("evening-sync")`.** Run the whole file and repoint each failure at `read_ref("evening-sync", "process.md")`. Do not weaken an assertion; only change where it reads.

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS apart from the strict xfail.

- [ ] **Step 6: Run the full suite and the plugin linter**

Run: `python -m pytest scripts/tests -q` and `python scripts/lint_plugin.py`
Expected: PASS (only the two known Windows flakes may fail; note them, do not "fix" them).

- [ ] **Step 7: Commit**

```bash
git add plugin/skills/evening-sync scripts/tests/test_skill_contracts.py
git commit -m "refactor(#271): evening processing moves to one shared reference, behaviour unchanged"
```

---

### Task 6: `/sync-recordings` steps 8–11, no step 5 in interactive mode, rules, lock

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md`
- Modify: `plugin/skills/evening-sync/SKILL.md` (stage 1 acquire, stage 7 release)
- Test: `scripts/tests/test_skill_contracts.py` (append; remove Task 5's xfail)

- [ ] **Step 1: Write the failing contract tests**

```python
def test_sync_recordings_never_touches_daily_notes():
    """#271: safe to call any number of times a day."""
    text = read_skill("sync-recordings")
    assert "60-daily-notes" not in text.replace(
        "never creates, writes or edits anything under `60-daily-notes/`", "")
    assert "daily-note write" not in text
    assert "never creates, writes or edits anything under `60-daily-notes/`" in text


def test_only_evening_sync_writes_daily_notes():
    writers = [p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md")
               if "daily-note write" in p.read_text(encoding="utf-8")]
    assert writers == ["evening-sync"]


def test_on_demand_steps_are_interactive_only():
    text = read_skill("sync-recordings")
    for heading in ("### 8. Triage in the chat", "### 9. Process",
                    "### 10. Decisions in the chat", "### 11. Summary"):
        assert heading in text, heading
    for cli in ("meeting triage-list", "meeting triage-apply",
                "decision review", "runlock acquire", "runlock release"):
        assert cli in text, cli
    unattended = text.split("## Unattended mode", 1)[1]
    assert "steps 8–11" in unattended


def test_evening_sync_holds_the_run_lock():
    text = read_skill("evening-sync")
    assert "runlock acquire --vault \"$VAULT\" --routine evening-sync" in text
    assert "runlock release --vault \"$VAULT\" --routine evening-sync" in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k "daily_notes or interactive_only or run_lock or shared_reference"`
Expected: FAIL.

- [ ] **Step 3: Edit `sync-recordings/SKILL.md`.**

(a) In `## Rules`, add:

```markdown
- **This skill never creates, writes or edits anything under `60-daily-notes/`.**
  The daily note belongs to `/evening-sync` stage 6. Safe to call any number
  of times a day.
- **Steps 8–11 run only when the owner called this skill** (interactive mode).
  `--unattended` — and `/evening-sync` stage 3 — stops after step 7. This skill
  never reads mail or Teams.
```

(b) Replace the body of `### 5. Confirm the plan (interactive mode only)` with:

```markdown
**No plan is shown — in either mode (#271).** Interactive mode extracts like
unattended mode: ambiguous routing becomes `projects: []` and low confidence,
and the owner settles every note in step 8 on the real titles. The drop
mechanics below are still how step 8 and the summary undo a recording.
```

Keep the existing "For a recording the user says to permanently drop" block and the m365 two-write drop under it unchanged. Also delete the "probe wave runs before this step ever shows anything" ordering paragraph and the provisional-columns paragraphs: they describe a table that is no longer shown. Check step 6 for references to "the plan the user confirmed" and change them to "the step-4 plan".

(c) After `### 7. Summarize` (before `## Sync Complete`'s template ends and `## Scratch hygiene` starts), insert:

````markdown
### 8. Triage in the chat

Interactive mode only. Take the run lock first:

```bash
python3 "$VAULTLIB" runlock acquire --vault "$VAULT" --routine sync-recordings
```

`acquired: false` → stop here, say: *"Your evening run is busy; your meetings
stay in triage and that run picks up what you tick."* Then scratch sweep and end.

```bash
python3 "$VAULTLIB" meeting triage-list --vault "$VAULT"
```

Empty `items` → say "nothing waiting for you", go to step 9 (notes ticked
Include may still be waiting). Otherwise show ONE numbered list, one line per
item, dry, no commentary:

`1. Weekly with Acme · Mon 12 Oct 09:00 · Acme ERP rollout · Jan Peeters, Sofie Maes`

Use `title`, `date` (weekday, day, month, time), `project_names` (or "no
project") and `attendee_names`. Add ` · ⚠ possible duplicate` when
`conflicts_with` is set. Ask once: **"Accept, dismiss or change?"** Accept
any free-text answer ("all accept", "1 3 accept, 2 dismiss, 4 project is
finance close"). "Not now" or no clear answer → release the lock and end;
everything stays in triage.

Translate the answer into a list of `{path, action[, projects][, attendees][, accept]}`.
Projects and people are slugs: match the owner's words to existing project and
people names. Never invent a slug. If a name matches nothing, or matches two,
ask about that one item. When the answer changed a project or attendees, read
your interpretation back in one line and wait for a yes. Then:

```bash
cat > "$SCRATCH/triage.payload.json" <<'JSON'
[{"path": "20-meetings/…", "action": "accept"}]
JSON
python3 "$VAULTLIB" meeting triage-apply --vault "$VAULT" --items "$SCRATCH/triage.payload.json"
python3 "$VAULTLIB" sync reconcile-reviews --vault "$VAULT"
python3 "$VAULTLIB" sync rederive-entities --vault "$VAULT"
```

Report each `refused` item with its reason, in one line each. A duplicate is
settled in Obsidian, as the reason says.

### 9. Process

Follow `${CLAUDE_PLUGIN_ROOT}/skills/evening-sync/references/process.md`
with the **On demand** column of its Inputs table: sections A, B and C, no
harvest jottings, no mail or Teams. Keep its Returns for steps 10 and 11.

### 10. Decisions in the chat

From C's returns, list every `decisionsWritten` stem (read each note's
`summary`), one line each: `1. Acme ERP rollout · Go-live moves to 3 Nov`.
None → skip to step 11. Ask once: **"Keep or dismiss?"** "Not now" → they
stay in Decisions › To review. For each answer:

```bash
python3 "$VAULTLIB" decision review --vault "$VAULT" --path "<path>" --keep
python3 "$VAULTLIB" decision review --vault "$VAULT" --path "<path>" --dismiss
```

A dismissed decision whose result has `supersedes` set: say *"It had replaced
<that decision>, which stays marked replaced — reopen it in Decisions if it
still holds."*

### 11. Summary

Release the lock, then summarize from disk:

```bash
python3 "$VAULTLIB" runlock release --vault "$VAULT" --routine sync-recordings
```

```
## Brain updated
**Meetings:** {N} accepted · {N} dismissed · {N} changed · {N} left in triage
**Your notes:** {N} absorbed ({titles}) · {N} kept for tonight ({why})
**Project pages rewritten:** {project names}
**Decisions:** {N} kept · {N} dismissed · {N} left in Decisions › To review
**Not done now:** mail and Teams, and tomorrow's daily note — tonight's run
**Warnings:** {verbatim} | none
```

Release the lock on every exit after step 8 took it: refusal, "not now", or an
error.
````

(d) In `## Unattended mode`, add rule 5:

```markdown
5. **Steps 8–11 never run.** Unattended stops after step 7: no triage, no
   processing, no lock. The evening run processes in its own stage 4.
```

(e) In `## Usage`, add one line: "Called by the owner, it also asks about the meetings waiting for review, brings the accepted ones and your notes ticked Include into the brain, and asks about the decisions it found (steps 8–11)."

- [ ] **Step 4: Edit `evening-sync/SKILL.md`.**

At the start of stage 1:

````markdown
Take the run lock:

```bash
python3 "$VAULTLIB" runlock acquire --vault "$VAULT" --routine evening-sync
```

`acquired: false` means the owner's on-demand processing is running. Retry
once a minute, up to 10 times (a CLI call each, never a model check-in). Then
continue anyway and add to the warnings: "ran while the meeting sync held the
lock (since <started_at>)".
````

At the end of stage 7, before the summary, and on every early exit:

````markdown
```bash
python3 "$VAULTLIB" runlock release --vault "$VAULT" --routine evening-sync
```
````

Waiting: `Bash` sleep is not available to the model in some hosts. Use `python3 -c "import time; time.sleep(60)"` per retry, or the host's own wait. Write it as one call per retry, not a loop the model polls.

- [ ] **Step 5: Remove the strict xfail** from Task 5's test. Run:

`python -m pytest scripts/tests/test_skill_contracts.py -q` → PASS
`python -m pytest scripts/tests -q` and `python scripts/lint_plugin.py` → PASS (known flakes aside)

- [ ] **Step 6: Commit**

```bash
git add plugin/skills scripts/tests/test_skill_contracts.py
git commit -m "feat(#271): meeting sync asks, processes and asks about decisions when you call it"
```

---

### Task 7: Start here, CHANGELOG, version, docs

**Files:**
- Modify: `plugin/template/Start here.md` (find the section that explains the evening run / triage; check with `grep -n "evening" "plugin/template/Start here.md"`)
- Modify: `CHANGELOG.md` (`## Unreleased`, top)
- Modify: `plugin/.claude-plugin/plugin.json` → `"version": "0.13.12"`
- Modify: `plugin/CLAUDE.md` (the CLI command list, if it enumerates commands: add `meeting triage-list`, `meeting triage-apply`, `decision review`, `runlock acquire|release`)

- [ ] **Step 1: Start here paragraph** (plain language, next to where triage is explained):

```markdown
**Need today's meetings in now?** Ask Claude for the meeting sync
(`/sync-recordings`). It fetches what's new, asks you per meeting — accept,
dismiss or change — and then updates your project pages, including your notes
ticked Include. Then it asks about the decisions it found. Mail and Teams, and
tomorrow's daily note, still come with the evening run.
```

- [ ] **Step 2: CHANGELOG line** (top of Unreleased):

```markdown
- **Today's meetings, today.** Call the meeting sync (`/sync-recordings`) whenever you need it: it fetches new meetings, asks you in the chat per meeting — accept, dismiss or change the project or people — and then updates the project pages straight away, together with your notes ticked Include. It then asks keep or dismiss on the decisions it found. You no longer wait for the evening run and the next day's triage. Mail and Teams, and tomorrow's daily note, stay with the evening run; the meeting sync never writes a daily note. If the evening run is busy, the meeting sync leaves your meetings in triage and says so. No `/upgrade-vault` needed, except for the new line in Start here. (#271)
```

- [ ] **Step 3: Version bump** to `0.13.12` in `plugin/.claude-plugin/plugin.json`. Check whether other manifests carry the version: `grep -rn "0.13.11" --include=*.json .`. Bump every plugin-version occurrence the version guard checks.

- [ ] **Step 4: Run everything**

Run: `python -m pytest scripts/tests -q`, `python scripts/lint_plugin.py`, `python scripts/check_changelog_entry.py` (if it takes args, read its `--help`).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "plugin/template/Start here.md" CHANGELOG.md plugin/.claude-plugin/plugin.json plugin/CLAUDE.md
git commit -m "docs(#271): Start here, changelog and 0.13.12"
```

---

### Task 8: End-to-end check on a preview vault, then PR

No code. This verifies the real flow before asking the owner to merge.

- [ ] **Step 1:** Make a fresh preview vault from this branch's template (`scripts/make_test_vault.py`, see its `--help`) with the demo fixture. Put one transcript file in `10-inbox/` dated today 09:00 and linked to a demo project. Tick Include on one Thoughts & ideas note for the same project.
- [ ] **Step 2:** In a Claude session on that vault with this branch's plugin, run `/sync-recordings`. Check:
  - one list appears;
  - accept → `reviewed: true` → `review_status: confirmed`;
  - the project page shows the meeting in "Where it stands";
  - the note is absorbed;
  - the decisions list appears; keep → `reviewed: true`;
  - nothing new in `60-daily-notes/`;
  - the lock file is gone afterwards.
- [ ] **Step 3:** Run `/evening-sync` in the same vault. Check:
  - the project processed at noon is **not** rewritten (no new `state-updated`) unless new input exists;
  - the daily note is written;
  - the lock file is gone afterwards.
- [ ] **Step 4:** Push the branch and open the PR: title `On-demand processing: today's meetings in the brain today (#271)`, body with what changed, test evidence, and "Closes #271". End the body with the attribution line. Report the CI status to the owner and wait for their merge; never merge yourself.
