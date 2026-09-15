# Vault Readability (daily note v2, project index v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the evening run's daily note and the project index scannable by a human, by moving their formatting into the CLI (structured payloads with caps), fixing dangling identity links and the duplicated catch-up banner, and folding sync mechanics away from content.

**Architecture:** Two new pure-rendering modules (`recap.py`, `projectstate.py`) and one shared link module (`links.py`) sit beside the existing `dailynote.py`/`project.py`. `daily-note write` accepts a v2 structured recap and prep while still rendering v1 payloads byte-identically; a new `project state write` renders the whole project index body from JSON. Migration 002 reshapes existing indexes to the v2 headings (structure-version 3). Skills stop editing Markdown and send JSON.

**Tech Stack:** Python 3.10 stdlib only (Cowork floor), pytest, the repo's `obsidian_probe.py` visual tier, Obsidian 1.13 / Minimal 9 rendering.

**Spec:** `docs/superpowers/specs/2026-09-15-vault-readability-design.md` — read it first; every task below argues from it.

## Global Constraints

- **Execution model (Michael's standing rule):** dispatch every task to an implementer subagent with `model: sonnet`; the orchestrator (session model) reviews between tasks. Never let a subagent inherit the session model.
- Python **3.10 syntax floor**, **stdlib only** in `plugin/lib/` (no PyYAML, no `match` statements are fine but no 3.11-only APIs such as `datetime.UTC` or `tomllib`).
- Writes are UTF-8 with `newline="\n"`; use `vault.atomic_write`.
- **Clean-room rule:** nothing under `plugin/` may name a delaware client, Michael, or busdev content. Test fixtures use the demo cast (Acme, Meridian, Nordbridge…). `python scripts/lint_plugin.py` enforces a denylist; the rule is broader than the lint.
- Every byte outside daily-note region markers is the user's. Never regenerate `#### Notes`, `#### Actions`, `## End of day`.
- A **v1 payload must render byte-identically** to today (pinned by `scripts/tests/test_vaultlib_dailynote.py::test_fresh_fixture_is_exactly_what_daily_note_write_renders`). Do not edit that test or the fixture daily notes to make it pass.
- Any PR touching `plugin/` must bump `plugin/.claude-plugin/plugin.json`; this PR ships as **0.11.0**.
- Run from the worktree root: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q` must be green at the end of every task.
- Commit after every task with a conventional message and the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `plugin/lib/vaultlib/links.py` (new) | Resolve a wikilink target to a vault object; normalise identity links to `[[path\|Display Name]]`; collect offenders. Shared by daily notes and project state. |
| `plugin/lib/vaultlib/recap.py` (new) | Validate and render the v2 structured recap (glance, themes, pulse, decisions, watch, carried forward, sync notes). Pure functions. |
| `plugin/lib/vaultlib/dailynote.py` (modify) | Accept v2 recap/prep, render Prep/Notes/Actions sub-headings, path-form entity heading, strip a model-written banner, read notes/actions. |
| `plugin/lib/vaultlib/projectstate.py` (new) | Validate and render the v2 project index body; `write()` replaces the body and updates frontmatter through `project.touch`. |
| `plugin/lib/vaultlib/project.py` (modify) | `scaffold` renders the v2 body with placeholders via `projectstate.render_body`. |
| `plugin/lib/vaultlib/cli.py` (modify) | `project state write` subcommand; `ProjectStateError` mapping. |
| `plugin/migrations/002-structure-version-3/migrate.py` (new) | Reshape v1 project index bodies into the v2 sections. `LOSSY = None`. |
| `plugin/template/99-workflow-config/reference/ontology.md`, `plugin/lib/vaultlib/schema.json` | `body_sections` for project → `[Coming up, Recent meetings, Recent decisions, Background]`; daily-note section documents v2. |
| `fixtures/demo-vault/30-projects/*/index.md` | Rewritten to v2 by running migration 002 on the fixture tree. |
| `plugin/template/.obsidian/snippets/sb-accelerator.css` | Four callout types: `glance`, `theme`, `hot`, `sync`. |
| `plugin/template/Start here.md`, `plugin/CLAUDE.md`, `docs/local-setup.md` | Prose that describes the note's parts and the region contract. |
| `plugin/skills/evening-sync/SKILL.md`, `plugin/skills/new-project/SKILL.md` | Stages 2/4/5/6 speak v2; new-project describes the v2 index. |
| `scripts/tests/test_vaultlib_links.py`, `test_vaultlib_recap.py`, `test_vaultlib_projectstate.py`, `test_migration_002.py` (new); `test_vaultlib_dailynote.py`, `test_vaultlib_project.py`, `test_skill_contracts.py` (modify) | Tests. |

---

### Task 1: `links.py` — shared link resolution and identity-link normalisation

**Files:**
- Create: `plugin/lib/vaultlib/links.py`
- Modify: `plugin/lib/vaultlib/dailynote.py:123-199` (replace `_resolve_link`/`_check_links` bodies with calls into `links`)
- Test: `scripts/tests/test_vaultlib_links.py` (new)

**Interfaces:**
- Consumes: `vault.ENTITIES_DIR`, `vault.PEOPLE_DIR`, `vault.PROJECTS_DIR`, `vault.MEETINGS_DIR`, `vault.DAILY_NOTES_DIR`, `markdown.split_frontmatter`.
- Produces:
  - `links.resolve(root: Path, target: str) -> tuple[Optional[str], Optional[Path], Optional[str]]` — `(kind, path, name_key)`; accepts bare slugs/stems **and** path targets (`40-entities/acme/dossier`, `30-projects/x/index`, `50-people/y`, `20-meetings/z`, `60-daily-notes/2026-06-15`, `30-projects/x/decisions/stem`).
  - `links.display_name(path: Path, name_key: str) -> Optional[str]`
  - `links.path_target(root: Path, path: Path) -> str` — vault-relative, no `.md`.
  - `links.normalise(root: Path, text: str, label: str) -> tuple[str, list[str], list[str]]` — `(rewritten_text, offenders, warnings)`. Every identity link (entity/project/person) becomes `[[<path_target>|<display_name>]]`; an alias that disagrees with the vault is an offender; an unresolvable target is an offender; non-identity links are left as written (existence-checked only).
  - `links.WIKILINK_RE` — the regex `dailynote` used, exported.

- [ ] **Step 1: Write the failing tests**

```python
# scripts/tests/test_vaultlib_links.py
"""links: one resolver for every writer, and the identity-link normaliser.

Obsidian resolves [[name]] by file name only, and entities/projects are
folders, so a bare [[acme-industries]] dangles in the app. The normaliser
rewrites identity links to the path form with the vault's display name.
"""
from pathlib import Path

from vaultlib import links

from test_vaultlib_dailynote import make_linkable_vault


def test_resolve_bare_entity_project_person_meeting_decision_daily(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text("---\n---\n", encoding="utf-8")
    assert links.resolve(root, "acme-industries")[0] == "entity"
    assert links.resolve(root, "yard-automation")[0] == "project"
    assert links.resolve(root, "taylor-brooks")[0] == "person"
    assert links.resolve(root, "12-06-26-weekly-status")[0] == "meeting"
    assert links.resolve(root, "2026-06-12-phase-1-deferred")[0] == "decision"
    assert links.resolve(root, "2026-06-12")[0] == "daily note"
    assert links.resolve(root, "nope") == (None, None, None)


def test_resolve_accepts_path_targets(tmp_path):
    root = make_linkable_vault(tmp_path)
    kind, path, key = links.resolve(root, "40-entities/acme-industries/dossier")
    assert (kind, key) == ("entity", "entity-name")
    assert path == root / "40-entities" / "acme-industries" / "dossier.md"
    kind, _, key = links.resolve(root, "30-projects/yard-automation/index")
    assert (kind, key) == ("project", "project-name")
    kind, _, _ = links.resolve(root, "30-projects/yard-automation/decisions/2026-06-12-phase-1-deferred")
    assert kind == "decision"
    assert links.resolve(root, "../etc/passwd") == (None, None, None)


def test_normalise_rewrites_identity_links_to_path_form(tmp_path):
    root = make_linkable_vault(tmp_path)
    text, offenders, warnings = links.normalise(
        root, "see [[acme-industries]] and [[yard-automation|Yard Automation Program]] "
              "and [[taylor-brooks]]", "recap")
    assert offenders == [] and warnings == []
    assert text == ("see [[40-entities/acme-industries/dossier|Acme]] and "
                    "[[30-projects/yard-automation/index|Yard Automation Program]] "
                    "and [[50-people/taylor-brooks|Taylor Brooks]]")


def test_normalise_is_idempotent_on_path_form(tmp_path):
    root = make_linkable_vault(tmp_path)
    once, _, _ = links.normalise(root, "[[acme-industries]]", "x")
    twice, offenders, _ = links.normalise(root, once, "x")
    assert twice == once and offenders == []


def test_normalise_leaves_event_links_alone_but_checks_existence(tmp_path):
    root = make_linkable_vault(tmp_path)
    text, offenders, _ = links.normalise(
        root, "[[12-06-26-weekly-status|Friday's status]] [[2026-06-12-phase-1-deferred]]", "x")
    assert text == "[[12-06-26-weekly-status|Friday's status]] [[2026-06-12-phase-1-deferred]]"
    assert offenders == []
    _, offenders, _ = links.normalise(root, "[[no-such-meeting]]", "recap")
    assert len(offenders) == 1 and "[[no-such-meeting]]" in offenders[0]


def test_normalise_refuses_a_wrong_identity_alias(tmp_path):
    root = make_linkable_vault(tmp_path)
    _, offenders, _ = links.normalise(root, "[[acme-industries|ACME Corp]]", "recap")
    assert len(offenders) == 1
    assert "'Acme'" in offenders[0]


def test_normalise_keeps_heading_anchors_and_embeds(tmp_path):
    root = make_linkable_vault(tmp_path)
    text, offenders, _ = links.normalise(
        root, "![[12-06-26-weekly-status#Key Takeaways]] [[acme-industries#Context]]", "x")
    assert offenders == []
    assert "![[12-06-26-weekly-status#Key Takeaways]]" in text
    assert "[[40-entities/acme-industries/dossier#Context|Acme]]" in text


def test_normalise_warns_when_display_name_is_missing(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "40-entities" / "acme-industries" / "dossier.md").write_text(
        "---\ntype: entity\nslug: acme-industries\n---\n", encoding="utf-8")
    text, offenders, warnings = links.normalise(root, "[[acme-industries]]", "recap")
    assert offenders == []
    assert len(warnings) == 1 and "entity-name" in warnings[0]
    # falls back to the slug as display so the link still opens the object
    assert text == "[[40-entities/acme-industries/dossier|acme-industries]]"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_links.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vaultlib.links'`

- [ ] **Step 3: Write `links.py`**

```python
# plugin/lib/vaultlib/links.py
"""Wikilink resolution and identity-link normalisation, shared by writers.

Obsidian resolves `[[name]]` by file name only. Entities and projects are
folders (`<slug>/dossier.md`, `<slug>/index.md`), so a bare `[[acme]]`
passes an existence check here and still dangles in the app — clicking it
spawns an empty note in the vault root. Every writer that emits prose
therefore routes it through `normalise`, which rewrites identity links to
`[[<vault path>|<display name>]]` and keeps decision 19's alias check.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from . import markdown, vault

# `#heading` is stripped before resolution; `|alias` is the display-name
# claim. `!?` catches embeds, which make the same claim as a plain link.
WIKILINK_RE = re.compile(
    r"(!?)\[\[([^\[\]|#]+)(#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")

_IDENTITY = ("entity", "person", "project")
_SAFE_TARGET_RE = re.compile(r"\A[A-Za-z0-9._ -]+(?:/[A-Za-z0-9._ -]+)*\Z")


def _classify(root: Path, path: Path) -> Tuple[Optional[str], Optional[str]]:
    """(kind, display-name key) for a vault file by where it sits."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None, None
    parts = rel.split("/")
    if parts[0] == vault.ENTITIES_DIR and len(parts) == 3 and parts[2] == "dossier.md":
        return "entity", "entity-name"
    if parts[0] == vault.PEOPLE_DIR and len(parts) == 2:
        return "person", "person-name"
    if parts[0] == vault.PROJECTS_DIR and len(parts) == 3 and parts[2] == "index.md":
        return "project", "project-name"
    if parts[0] == vault.PROJECTS_DIR and len(parts) == 4 and parts[2] == "decisions":
        return "decision", None
    if parts[0] == vault.MEETINGS_DIR and len(parts) == 2:
        return "meeting", None
    if parts[0] == vault.DAILY_NOTES_DIR and len(parts) == 2:
        return "daily note", None
    return None, None


def resolve(root: Path, target: str):
    """(kind, path, display-name key) for a wikilink target, or three Nones.

    A bare slug/stem is looked up in the layout order identity objects
    first (they are the ones whose *name* an alias claims). A target with a
    `/` is a vault path without `.md` and is classified by where it sits.
    """
    target = str(target or "").strip()
    if not target or not _SAFE_TARGET_RE.match(target):
        return None, None, None
    if any(segment in (".", "..") for segment in target.split("/")):
        return None, None, None
    if "/" in target:
        path = (root / f"{target}.md")
        if path.is_file():
            kind, key = _classify(root, path)
            if kind is not None:
                return kind, path, key
        return None, None, None
    candidates = (
        ("entity", root / vault.ENTITIES_DIR / target / "dossier.md", "entity-name"),
        ("person", root / vault.PEOPLE_DIR / f"{target}.md", "person-name"),
        ("project", root / vault.PROJECTS_DIR / target / "index.md", "project-name"),
        ("meeting", root / vault.MEETINGS_DIR / f"{target}.md", None),
        ("daily note", root / vault.DAILY_NOTES_DIR / f"{target}.md", None),
    )
    for kind, path, name_key in candidates:
        if path.is_file():
            return kind, path, name_key
    projects = root / vault.PROJECTS_DIR
    for folder in sorted(projects.glob("*/decisions")) if projects.is_dir() else []:
        path = folder / f"{target}.md"
        if path.is_file():
            return "decision", path, None
    return None, None, None


def path_target(root: Path, path: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return rel[:-3] if rel.endswith(".md") else rel


def display_name(path: Path, name_key: str) -> Optional[str]:
    """The object's display name, None when the frontmatter cannot say."""
    try:
        frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    value = str(frontmatter.get(name_key) or "").strip()
    return value or None


def normalise(root: Path, text: str, label: str) -> Tuple[str, List[str], List[str]]:
    """Rewrite identity links to path form; collect offenders and warnings.

    Offenders (the caller refuses the write): an unresolvable target, or an
    identity alias that is not the object's display name. Warnings (the
    write proceeds): an identity object whose display name cannot be read,
    in which case the slug stands in so the link still opens the object.
    """
    offenders: List[str] = []
    warnings: List[str] = []

    def replace(match: re.Match) -> str:
        bang, raw_target, anchor, alias = match.groups()
        target = raw_target.strip()
        kind, path, name_key = resolve(root, target)
        if kind is None:
            offenders.append(
                f"{label}: [[{target}]] resolves to no vault object — link "
                "only to objects that exist (create one with /update-entity "
                "or /new-project first), or leave the name out. Never write "
                "a name you have not looked up.")
            return match.group(0)
        if kind not in _IDENTITY:
            return match.group(0)
        actual = display_name(path, name_key)
        if actual is None:
            warnings.append(
                f"{label}: [[{target}]] carries no readable {name_key} — "
                "display name not verified; the slug stands in")
            shown = path.parent.name if kind != "person" else path.stem
        else:
            shown = actual
            if alias is not None and alias.strip() != actual:
                offenders.append(
                    f"{label}: [[{target}|{alias}]] — that {kind} is called "
                    f"{actual!r}. Display names come from the vault, never "
                    "from the model.")
                return match.group(0)
        return f"{bang}[[{path_target(root, path)}{anchor or ''}|{shown}]]"

    return WIKILINK_RE.sub(replace, text), offenders, warnings
```

- [ ] **Step 4: Point `dailynote.py` at `links`**

In `plugin/lib/vaultlib/dailynote.py`: delete `_WIKILINK_RE` and the body of `_resolve_link`, and make `_check_links` delegate. Keep the function names so the rest of the module and existing tests are untouched:

```python
from . import dates, links, markdown, meeting, naming, vault

_WIKILINK_RE = links.WIKILINK_RE   # kept for callers/tests that import it


def _resolve_link(root: Path, target: str):
    return links.resolve(root, target)


def _check_links(root: Path, text: str, label: str,
                 warnings: List[str]) -> List[str]:
    """Every wikilink resolves; every identity alias matches the vault.

    v1 payloads are *checked* here and left as written (byte-identical
    rendering is pinned); v2 payloads are normalised by `recap.py` and the
    prep renderer, which call `links.normalise` and pass its offenders
    through the same single-raise path.
    """
    _, offenders, new_warnings = links.normalise(root, text, label)
    warnings.extend(new_warnings)
    return offenders
```

Note the v1 behaviour change is limited to warning text; the existing tests assert on offenders, not warning wording. If `test_vaultlib_dailynote.py` has an assertion on the exact "carries no" warning text, adjust `links.normalise`'s warning to keep the phrase `carries no` and `display name not verified` (it does above).

- [ ] **Step 5: Run the links tests and the daily-note suite**

Run: `python3 -m pytest scripts/tests/test_vaultlib_links.py scripts/tests/test_vaultlib_dailynote.py -q`
Expected: all PASS. If a daily-note test fails on `_WIKILINK_RE` group indexes (the old regex had 2 groups; the new one has 4), search `dailynote.py` for other uses of `_WIKILINK_RE` — there are none besides `_check_links`.

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/links.py plugin/lib/vaultlib/dailynote.py scripts/tests/test_vaultlib_links.py
git commit -m "feat(vaultlib): links module — path-form identity links so [[slug]] opens the object

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `recap.py` — validate and render the v2 structured recap

**Files:**
- Create: `plugin/lib/vaultlib/recap.py`
- Test: `scripts/tests/test_vaultlib_recap.py` (new)

**Interfaces:**
- Consumes: `links.normalise`, `links.resolve`, `links.display_name`, `markdown.split_frontmatter`, `dates.DAY_NAMES`.
- Produces:
  - `recap.RecapError(Exception)`
  - `recap.SIGNALS = {"red": "🔴", "amber": "🟠", "green": "🟢", "quiet": "⚪"}`
  - `recap.LABELS = ("Needs your hand", "Moved", "New", "Decided", "Quiet")`
  - `recap.validate(root, raw: dict) -> tuple[dict, list[str], list[str]]` — `(clean, offenders, warnings)`; raises `RecapError` on shape/cap violations; link offenders are *returned*, not raised (the caller merges them with prep offenders and raises once).
  - `recap.render(root, clean: dict, *, meetings: int, window_label: str) -> str`
  - `recap.word_count(text) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# scripts/tests/test_vaultlib_recap.py
"""recap v2: the CLI renders the recap from fields; the model supplies facts."""
import pytest

from vaultlib import recap

from test_vaultlib_dailynote import make_linkable_vault


def full_payload():
    return {
        "glance": {
            "entities": ["acme-industries"],
            "headlines": [
                {"label": "Needs your hand", "text": "Vendor scoring has no owner past Friday"},
                {"label": "Moved", "text": "Yard 2 re-scope agreed"},
            ],
        },
        "themes": [
            {"headline": "Vendor scoring needs an owner",
             "body": "Two sessions this week circled the same gap. Nobody holds the sheet.",
             "sources": [{"stem": "12-06-26-weekly-status", "label": "Friday status"}]},
        ],
        "pulse": [
            {"project": "yard-automation", "signal": "green", "text": "Yard 2 re-scope agreed; schedule owed to Leo."},
        ],
        "decisions": ["2026-06-12-phase-1-deferred"],
        "watch": ["Vendor scoring has no owner past Friday."],
        "carried_forward": ["Follow up with Dana on rollout scope."],
        "sync_notes": ["One duplicate recorder capture flagged in triage."],
    }


def make_vault(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "30-projects" / "yard-automation" / "decisions" / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\nproject: yard-automation\ndate: 2026-06-12\nstatus: active\n"
        'summary: "Phase 1 site nomination deferred to Nordbridge"\n---\n', encoding="utf-8")
    (root / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\nslug: yard-automation\n"
        "entity: acme-industries\n---\n", encoding="utf-8")
    return root


EXPECTED = """> [!glance] At a glance
> **1 meeting** Friday · 1 organisation · 1 theme · 1 decision logged
> - **Needs your hand:** Vendor scoring has no owner past Friday
> - **Moved:** Yard 2 re-scope agreed
> - **Touched:** [[40-entities/acme-industries/dossier|Acme]]

**Themes**

> [!theme]- Vendor scoring needs an owner
> Two sessions this week circled the same gap. Nobody holds the sheet.
>
> Sources: [[12-06-26-weekly-status|Friday status]]

**Project pulse**

| | Project | What moved |
|:-:|---|---|
| 🟢 | [[30-projects/yard-automation/index\\|Yard Automation Program]] · [[40-entities/acme-industries/dossier\\|Acme]] | Yard 2 re-scope agreed; schedule owed to Leo. |

🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet

**Decisions logged**
- [[2026-06-12-phase-1-deferred|Phase 1 site nomination deferred to Nordbridge]] · Yard Automation Program

> [!hot] Watch
> - Vendor scoring has no owner past Friday.

> [!quote]- Carried forward — your jottings
> - Follow up with Dana on rollout scope.

> [!sync]- Sync notes — 1 item, also in the run log
> - One duplicate recorder capture flagged in triage."""


def test_render_matches_the_contract_exactly(tmp_path):
    root = make_vault(tmp_path)
    clean, offenders, warnings = recap.validate(root, full_payload())
    assert offenders == [] and warnings == []
    assert recap.render(root, clean, meetings=1, window_label="Friday") == EXPECTED


def test_empty_lists_render_their_none_phrasing(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, {"glance": {"entities": [], "headlines": [
        {"label": "Quiet", "text": "Nothing moved"}]}})
    text = recap.render(root, clean, meetings=0, window_label="Monday–Friday")
    assert "**0 meetings** Monday–Friday · 0 organisations · 0 themes · 0 decisions logged" in text
    assert "**Touched:**" not in text
    assert "**Themes** — none this window." in text
    assert "**Project pulse** — no project touched this window." in text
    assert "**Decisions logged** — none this run." in text
    assert "> [!hot] Watch\n> - nothing needs your hand this window" in text
    assert "Carried forward" not in text and "Sync notes" not in text


def test_plurals(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, {"glance": {"entities": ["acme-industries"], "headlines": [
        {"label": "Moved", "text": "x"}]}, "sync_notes": ["a", "b"]})
    text = recap.render(root, clean, meetings=3, window_label="Friday")
    assert "**3 meetings** Friday · 1 organisation · 0 themes · 0 decisions logged" in text
    assert "Sync notes — 2 items, also in the run log" in text


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p["glance"]["headlines"].clear(), "glance.headlines: 1–4"),
    (lambda p: p["glance"]["headlines"].append({"label": "Odd", "text": "x"}), "label"),
    (lambda p: p["glance"]["headlines"].__setitem__(0, {"label": "Moved", "text": " ".join(["w"] * 21)}), "≤ 20 words"),
    (lambda p: p["themes"].extend([p["themes"][0]] * 4), "themes: 0–4"),
    (lambda p: p["themes"][0].__setitem__("headline", " ".join(["w"] * 13)), "≤ 12 words"),
    (lambda p: p["themes"][0].__setitem__("body", " ".join(["w"] * 81)), "≤ 80 words"),
    (lambda p: p["pulse"][0].__setitem__("signal", "purple"), "signal"),
    (lambda p: p["pulse"][0].__setitem__("text", " ".join(["w"] * 41)), "≤ 40 words"),
    (lambda p: p["watch"].append(" ".join(["w"] * 41)), "≤ 40 words"),
    (lambda p: p.__setitem__("unknown", 1), "unknown"),
    (lambda p: p["glance"].__setitem__("meetings", 19), "computed"),
])
def test_caps_and_shapes_are_refused_by_field(tmp_path, mutate, message):
    root = make_vault(tmp_path)
    payload = full_payload()
    mutate(payload)
    with pytest.raises(recap.RecapError, match=message):
        recap.validate(root, payload)


def test_link_offenders_are_returned_not_raised(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["pulse"][0]["project"] = "no-such-project"
    payload["themes"][0]["sources"][0]["stem"] = "no-such-meeting"
    payload["decisions"] = ["no-such-decision"]
    payload["watch"] = ["mentions [[acme-industries|Wrong Name]]"]
    clean, offenders, _ = recap.validate(root, payload)
    assert len(offenders) == 4
    assert any("no-such-project" in o for o in offenders)
    assert any("no-such-meeting" in o for o in offenders)
    assert any("no-such-decision" in o for o in offenders)
    assert any("'Acme'" in o for o in offenders)


def test_free_text_identity_links_are_normalised(tmp_path):
    root = make_vault(tmp_path)
    payload = full_payload()
    payload["watch"] = ["[[acme-industries]] owes the scoring sheet"]
    clean, offenders, _ = recap.validate(root, payload)
    assert offenders == []
    text = recap.render(root, clean, meetings=1, window_label="Friday")
    assert "> - [[40-entities/acme-industries/dossier|Acme]] owes the scoring sheet" in text


def test_pulse_project_without_entity_omits_the_entity_link(tmp_path):
    root = make_vault(tmp_path)
    (root / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\nslug: yard-automation\n---\n",
        encoding="utf-8")
    clean, _, warnings = recap.validate(root, full_payload())
    text = recap.render(root, clean, meetings=1, window_label="Friday")
    assert "| 🟢 | [[30-projects/yard-automation/index\\|Yard Automation Program]] | Yard 2" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_recap.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vaultlib.recap'`

- [ ] **Step 3: Write `recap.py`**

```python
# plugin/lib/vaultlib/recap.py
"""The v2 recap: fields in, a scannable region out.

Formatting is code, content is judgment. The model supplies headlines,
themes, a pulse and lists; this module enforces the caps a skill's prose
never managed to ("exactly 5 bullets" did not stop 600-word bullets) and
renders the callouts and the table. Every free-text field goes through
`links.normalise`, so identity links open their objects in Obsidian.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import links, markdown, vault

SIGNALS = {"red": "🔴", "amber": "🟠", "green": "🟢", "quiet": "⚪"}
LABELS = ("Needs your hand", "Moved", "New", "Decided", "Quiet")
LEGEND = "🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet"

_ALLOWED = ("glance", "themes", "pulse", "decisions", "watch",
            "carried_forward", "sync_notes")
_GLANCE_ALLOWED = ("entities", "headlines")
_LINE_WORDS = 40


class RecapError(Exception):
    """A recap field the caller must fix."""


def word_count(text: str) -> int:
    return len(str(text).split())


def _one_line(value, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise RecapError(f"{label} must be a non-empty string")
    if "\n" in text or "\r" in text:
        raise RecapError(f"{label} must be one line")
    if word_count(text) > limit:
        raise RecapError(f"{label}: ≤ {limit} words (got {word_count(text)})")
    return text


def _lines(raw, label: str, limit: int = _LINE_WORDS) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RecapError(f"{label} must be a list of one-line strings")
    return [_one_line(item, f"{label}[{i}]", limit) for i, item in enumerate(raw)]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _norm(root: Path, text: str, label: str,
          offenders: List[str], warnings: List[str]) -> str:
    out, bad, warn = links.normalise(root, text, label)
    offenders.extend(bad)
    warnings.extend(warn)
    return out


def _identity_link(root: Path, kind: str, target: str, label: str,
                   offenders: List[str], warnings: List[str]) -> Optional[str]:
    found_kind, path, name_key = links.resolve(root, target)
    if found_kind != kind:
        offenders.append(
            f"{label}: [[{target}]] is not a {kind} that exists — look the "
            "slug up; never write one you recalled.")
        return None
    shown = links.display_name(path, name_key)
    if shown is None:
        warnings.append(f"{label}: [[{target}]] carries no readable {name_key}")
        shown = target
    return f"[[{links.path_target(root, path)}|{shown}]]"


def validate(root: Path, raw) -> Tuple[dict, List[str], List[str]]:
    """Shape and caps raise; link problems are collected and returned."""
    if not isinstance(raw, dict):
        raise RecapError("recap must be a JSON object (v2) or a string (v1)")
    unknown = sorted(set(raw) - set(_ALLOWED))
    if unknown:
        raise RecapError(f"recap: unknown key(s) {unknown}")
    offenders: List[str] = []
    warnings: List[str] = []

    glance = raw.get("glance")
    if not isinstance(glance, dict):
        raise RecapError("recap.glance must be an object")
    stray = sorted(set(glance) - set(_GLANCE_ALLOWED))
    if stray:
        raise RecapError(
            f"recap.glance: unknown key(s) {stray} — the first line "
            "(meeting count, window, theme and decision counts) is computed "
            "by the CLI, never supplied")
    headlines = glance.get("headlines")
    if not isinstance(headlines, list) or not 1 <= len(headlines) <= 4:
        raise RecapError("recap.glance.headlines: 1–4 items required")
    clean_headlines = []
    for i, item in enumerate(headlines):
        if not isinstance(item, dict) or set(item) != {"label", "text"}:
            raise RecapError(f"recap.glance.headlines[{i}] needs exactly label and text")
        if item["label"] not in LABELS:
            raise RecapError(
                f"recap.glance.headlines[{i}].label {item['label']!r} is not one of {list(LABELS)}")
        text = _one_line(item["text"], f"recap.glance.headlines[{i}].text", 20)
        clean_headlines.append({
            "label": item["label"],
            "text": _norm(root, text, f"recap.glance.headlines[{i}]", offenders, warnings)})
    entities_raw = glance.get("entities") or []
    if not isinstance(entities_raw, list):
        raise RecapError("recap.glance.entities must be a list of entity slugs")
    entity_links = []
    for slug in dict.fromkeys(str(s) for s in entities_raw):
        link = _identity_link(root, "entity", slug, "recap.glance.entities", offenders, warnings)
        if link:
            entity_links.append(link)

    themes_raw = raw.get("themes") or []
    if not isinstance(themes_raw, list) or len(themes_raw) > 4:
        raise RecapError("recap.themes: 0–4 items")
    themes = []
    for i, theme in enumerate(themes_raw):
        if not isinstance(theme, dict) or set(theme) - {"headline", "body", "sources"}:
            raise RecapError(f"recap.themes[{i}] allows headline, body, sources")
        headline = _one_line(theme.get("headline"), f"recap.themes[{i}].headline", 12)
        body = str(theme.get("body") or "").strip()
        if not body:
            raise RecapError(f"recap.themes[{i}].body must be a non-empty string")
        if word_count(body) > 80:
            raise RecapError(f"recap.themes[{i}].body: ≤ 80 words (got {word_count(body)})")
        sources = []
        for j, src in enumerate(theme.get("sources") or []):
            if not isinstance(src, dict) or set(src) != {"stem", "label"}:
                raise RecapError(f"recap.themes[{i}].sources[{j}] needs exactly stem and label")
            kind, _, _ = links.resolve(root, str(src["stem"]))
            if kind not in ("meeting", "daily note"):
                offenders.append(
                    f"recap.themes[{i}].sources[{j}]: [[{src['stem']}]] is not a "
                    "meeting or daily note that exists")
                continue
            sources.append(f"[[{src['stem']}|{_one_line(src['label'], 'source label', 12)}]]")
        themes.append({
            "headline": _norm(root, headline, f"recap.themes[{i}].headline", offenders, warnings),
            "body": _norm(root, body, f"recap.themes[{i}].body", offenders, warnings),
            "sources": sources})

    pulse_raw = raw.get("pulse") or []
    if not isinstance(pulse_raw, list):
        raise RecapError("recap.pulse must be a list")
    pulse = []
    for i, row in enumerate(pulse_raw):
        if not isinstance(row, dict) or set(row) != {"project", "signal", "text"}:
            raise RecapError(f"recap.pulse[{i}] needs exactly project, signal, text")
        if row["signal"] not in SIGNALS:
            raise RecapError(
                f"recap.pulse[{i}].signal {row['signal']!r} is not one of {sorted(SIGNALS)}")
        text = _one_line(row["text"], f"recap.pulse[{i}].text", 40)
        kind, path, _ = links.resolve(root, str(row["project"]))
        if kind != "project":
            offenders.append(
                f"recap.pulse[{i}]: [[{row['project']}]] is not a project that exists")
            continue
        project_link = _identity_link(root, "project", str(row["project"]),
                                      f"recap.pulse[{i}]", offenders, warnings)
        frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        entity_slug = str(frontmatter.get("entity") or "").strip()
        entity_link = None
        if entity_slug:
            entity_link = _identity_link(root, "entity", entity_slug,
                                         f"recap.pulse[{i}].entity", offenders, warnings)
        pulse.append({"signal": row["signal"], "project": project_link,
                      "entity": entity_link,
                      "text": _norm(root, text, f"recap.pulse[{i}].text", offenders, warnings)})

    decisions = []
    for i, stem in enumerate(raw.get("decisions") or []):
        kind, path, _ = links.resolve(root, str(stem))
        if kind != "decision":
            offenders.append(f"recap.decisions[{i}]: [[{stem}]] is not a decision that exists")
            continue
        frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        summary = str(frontmatter.get("summary") or "").strip() or str(stem)
        project_slug = str(frontmatter.get("project") or path.parent.parent.name)
        _, index_path, _ = links.resolve(root, project_slug)
        project_name = (links.display_name(index_path, "project-name")
                        if index_path is not None else None) or project_slug
        decisions.append(f"[[{stem}|{summary}]] · {project_name}")

    lists = {}
    for key in ("watch", "carried_forward", "sync_notes"):
        lists[key] = [_norm(root, line, f"recap.{key}[{i}]", offenders, warnings)
                      for i, line in enumerate(_lines(raw.get(key), f"recap.{key}"))]

    clean = {"headlines": clean_headlines, "entities": entity_links,
             "themes": themes, "pulse": pulse, "decisions": decisions, **lists}
    return clean, offenders, warnings


def _callout_list(kind: str, title: str, items: List[str], folded: bool) -> str:
    fold = "-" if folded else ""
    lines = [f"> [!{kind}]{fold} {title}"] + [f"> - {item}" for item in items]
    return "\n".join(lines)


def render(root: Path, clean: dict, *, meetings: int, window_label: str) -> str:
    parts: List[str] = []
    first = (f"**{_plural(meetings, 'meeting')}** {window_label} · "
             f"{_plural(len(clean['entities']), 'organisation')} · "
             f"{_plural(len(clean['themes']), 'theme')} · "
             f"{_plural(len(clean['decisions']), 'decision')} logged")
    glance = ["> [!glance] At a glance", f"> {first}"]
    glance += [f"> - **{h['label']}:** {h['text']}" for h in clean["headlines"]]
    if clean["entities"]:
        glance.append("> - **Touched:** " + " · ".join(clean["entities"]))
    parts.append("\n".join(glance))

    if clean["themes"]:
        parts.append("**Themes**")
        for theme in clean["themes"]:
            block = [f"> [!theme]- {theme['headline']}", f"> {theme['body']}"]
            if theme["sources"]:
                block += [">", "> Sources: " + " · ".join(theme["sources"])]
            parts.append("\n".join(block))
    else:
        parts.append("**Themes** — none this window.")

    if clean["pulse"]:
        rows = ["**Project pulse**", "", "| | Project | What moved |", "|:-:|---|---|"]
        for row in clean["pulse"]:
            project = row["project"].replace("|", "\\|")
            if row["entity"]:
                project += " · " + row["entity"].replace("|", "\\|")
            rows.append(f"| {SIGNALS[row['signal']]} | {project} | {row['text']} |")
        parts.append("\n".join(rows))
        parts.append(LEGEND)
    else:
        parts.append("**Project pulse** — no project touched this window.")

    if clean["decisions"]:
        parts.append("**Decisions logged**\n" + "\n".join(f"- {d}" for d in clean["decisions"]))
    else:
        parts.append("**Decisions logged** — none this run.")

    watch = clean["watch"] or ["nothing needs your hand this window"]
    parts.append(_callout_list("hot", "Watch", watch, folded=False))
    if clean["carried_forward"]:
        parts.append(_callout_list("quote", "Carried forward — your jottings",
                                   clean["carried_forward"], folded=True))
    if clean["sync_notes"]:
        title = f"Sync notes — {_plural(len(clean['sync_notes']), 'item')}, also in the run log"
        parts.append(_callout_list("sync", title, clean["sync_notes"], folded=True))
    return "\n\n".join(parts)
```

Note the table escapes `|` inside link aliases as `\|` (Obsidian's table rule). The golden string in the test writes `\\|` because it is a Python string.

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_recap.py -q`
Expected: PASS. If `test_render_matches_the_contract_exactly` fails on whitespace, diff the two strings with `difflib.unified_diff` and fix the renderer, not the golden — the golden is the contract from the spec.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/recap.py scripts/tests/test_vaultlib_recap.py
git commit -m "feat(vaultlib): recap v2 — structured glance/themes/pulse/watch rendered by the CLI with caps

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `daily-note write` v2 — structured recap and prep, Prep/Notes/Actions layout, banner strip

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py` (`_validate`, `_render`, `_heading`, `_HEADING_RE`, `_merge` heading comparison, `_recap_body`)
- Test: `scripts/tests/test_vaultlib_dailynote.py` (append)

**Interfaces:**
- Consumes: `recap.validate`, `recap.render`, `links.normalise`, `links.resolve`, `links.display_name`, `links.path_target`.
- Produces: `dailynote.write(root, payload)` accepting
  - `recap`: `str` (v1) **or** `dict` (v2, requires `recap_window`);
  - `meetings[].prep`: `str` (v1) **or** `{"attendees","last_meeting","context"}` (v2). All meetings must use the same form.
  - result gains `"contract": "v1" | "v2"` (v2 when either recap or prep is structured).
  - `dailynote.meetings_in_window(root, start: date, end: date) -> int`.
  - `dailynote.parse_heading(text) -> Optional[tuple[str, str, Optional[str]]]` — `(time, subject, entity_slug)` for both heading forms.
  - `dailynote.PREP_HEADING = "#### Prep"`, `NOTES_BLOCK = "#### Notes\n- "`, `ACTIONS_BLOCK = "#### Actions\n- [ ] "`.

- [ ] **Step 1: Write the failing tests** (append to `scripts/tests/test_vaultlib_dailynote.py`)

```python
# --- v2 contract ----------------------------------------------------------

def v2_vault(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\nslug: yard-automation\n"
        "entity: acme-industries\n---\n", encoding="utf-8")
    (root / "30-projects" / "yard-automation" / "decisions" / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\nproject: yard-automation\ndate: 2026-06-12\nstatus: active\n"
        'summary: "Phase 1 site nomination deferred"\n---\n', encoding="utf-8")
    return root


def v2_payload(**overrides):
    base = {
        "date": "2026-06-15",
        "recap_window": {"from": "2026-06-12", "to": "2026-06-12"},
        "recap": {
            "glance": {"entities": ["acme-industries"],
                       "headlines": [{"label": "Moved", "text": "Shortlist approved"}]},
            "themes": [],
            "pulse": [{"project": "yard-automation", "signal": "green", "text": "Shortlist approved."}],
            "decisions": ["2026-06-12-phase-1-deferred"],
            "watch": [],
            "carried_forward": [],
            "sync_notes": ["One duplicate flagged."],
        },
        "meetings": [
            {"time": "09:00", "subject": "Weekly Status", "entity": "acme-industries",
             "prep": {"attendees": "Sam Okafor, Taylor Brooks",
                      "last_meeting": "[[12-06-26-weekly-status|Friday — status]] · shortlist approved",
                      "context": "[[yard-automation]] · vendor selection target 2026-08-30"}},
            {"time": "14:00", "subject": "Deep dive — vendor scoring", "entity": None,
             "prep": {"attendees": "Omar", "last_meeting": "none on file", "context": "first session"}},
        ],
    }
    base.update(overrides)
    return base


EXPECTED_V2 = """---
date: 2026-06-15
type: daily-note
---

# 2026-06-15 · Monday

## Recap
<!-- evening-sync:recap:begin inputs={digest} -->
> [!glance] At a glance
> **1 meeting** Friday · 1 organisation · 0 themes · 1 decision logged
> - **Moved:** Shortlist approved
> - **Touched:** [[40-entities/acme-industries/dossier|Acme]]

**Themes** — none this window.

**Project pulse**

| | Project | What moved |
|:-:|---|---|
| 🟢 | [[30-projects/yard-automation/index\\|Yard Automation Program]] · [[40-entities/acme-industries/dossier\\|Acme]] | Shortlist approved. |

🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet

**Decisions logged**
- [[2026-06-12-phase-1-deferred|Phase 1 site nomination deferred]] · Yard Automation Program

> [!hot] Watch
> - nothing needs your hand this window

> [!sync]- Sync notes — 1 item, also in the run log
> - One duplicate flagged.
<!-- evening-sync:recap:end -->

## Meetings

### 09:00 — Weekly Status · [[40-entities/acme-industries/dossier|Acme]]
#### Prep
<!-- evening-sync:prep:begin -->
**Attendees** — Sam Okafor, Taylor Brooks
**Last meeting** — [[12-06-26-weekly-status|Friday — status]] · shortlist approved
**Context** — [[30-projects/yard-automation/index|Yard Automation Program]] · vendor selection target 2026-08-30
<!-- evening-sync:prep:end -->

#### Notes
- 

#### Actions
- [ ] 

### 14:00 — Deep dive — vendor scoring
#### Prep
<!-- evening-sync:prep:begin -->
**Attendees** — Omar
**Last meeting** — none on file
**Context** — first session
<!-- evening-sync:prep:end -->

#### Notes
- 

#### Actions
- [ ] 

## End of day
- 
"""


def test_v2_fresh_render_matches_the_contract_exactly(tmp_path):
    root = v2_vault(tmp_path)
    result = dailynote.write(root, v2_payload())
    assert result["contract"] == "v2"
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert text == EXPECTED_V2.replace("{digest}", result["recap_inputs"])


def test_v2_recap_requires_a_window(tmp_path):
    root = v2_vault(tmp_path)
    payload = v2_payload()
    del payload["recap_window"]
    with pytest.raises(dailynote.DailyNoteError, match="recap_window"):
        dailynote.write(root, payload)


def test_v2_link_offenders_across_recap_and_prep_raise_once(tmp_path):
    root = v2_vault(tmp_path)
    payload = v2_payload()
    payload["recap"]["pulse"][0]["project"] = "ghost-project"
    payload["meetings"][1]["prep"]["context"] = "[[ghost-meeting]]"
    with pytest.raises(dailynote.DailyNoteError) as info:
        dailynote.write(root, payload)
    assert "ghost-project" in str(info.value) and "ghost-meeting" in str(info.value)
    assert not (root / "60-daily-notes" / "2026-06-15.md").exists()


def test_v2_prep_requires_three_fields_and_one_form(tmp_path):
    root = v2_vault(tmp_path)
    payload = v2_payload()
    del payload["meetings"][0]["prep"]["context"]
    with pytest.raises(dailynote.DailyNoteError, match="context"):
        dailynote.write(root, payload)
    payload = v2_payload()
    payload["meetings"][1]["prep"] = "**Attendees:** Omar"
    with pytest.raises(dailynote.DailyNoteError, match="same form"):
        dailynote.write(root, payload)


def test_v1_string_recap_with_a_model_written_banner_is_stripped_with_a_warning(tmp_path):
    root = make_windowed_vault(tmp_path)
    text = ("> [!warning] Catch-up note\n> Covers 2026-06-12 → 2026-06-12 — 1 business day.\n\n"
            "> [!info] At a glance\n> 1 meeting Friday")
    result = dailynote.write(root, payload(
        date="2026-06-15", recap=text,
        recap_window={"from": "2026-06-12", "to": "2026-06-12"}))
    written = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert written.count("Catch-up note") <= 1
    assert "> [!info] At a glance\n> 1 meeting Friday" in written
    assert any("Catch-up" in w and "stripped" in w for w in result["warnings"])


def test_v2_payload_merges_into_a_v1_note(tmp_path):
    """A note written by the previous plugin version (bare heading, prep
    directly under it, a `- ` jot line) must accept a v2 re-run: regions are
    replaced, headings compared by (time, subject, entity), nothing else moves."""
    root = v2_vault(tmp_path)
    v1 = payload(date="2026-06-15", meetings=[
        {"time": "09:00", "subject": "Weekly Status", "entity": "acme-industries",
         "prep": "**Attendees:** Sam · **Last meeting:** none · **Context:** x."},
        {"time": "14:00", "subject": "Deep dive — vendor scoring", "entity": None,
         "prep": "**Attendees:** Omar · **Last meeting:** none · **Context:** first session."}])
    dailynote.write(root, v1)
    note = root / "60-daily-notes" / "2026-06-15.md"
    original = note.read_text(encoding="utf-8").replace("<!-- evening-sync:prep:end -->\n- \n\n### 14:00",
                                                        "<!-- evening-sync:prep:end -->\n- my jotting\n\n### 14:00")
    note.write_text(original, encoding="utf-8")
    result = dailynote.write(root, v2_payload())
    merged = note.read_text(encoding="utf-8")
    assert result["created"] is False
    assert "- my jotting" in merged
    assert "### 09:00 — Weekly Status · [[acme-industries]]" in merged   # heading is the user's now
    assert "**Attendees** — Sam Okafor, Taylor Brooks" in merged
    assert "#### Notes" not in merged   # sub-headings are never retro-fitted


def test_parse_heading_accepts_both_forms():
    assert dailynote.parse_heading("09:00 — Weekly Status · [[acme-industries]]") == (
        "09:00", "Weekly Status", "acme-industries")
    assert dailynote.parse_heading(
        "09:00 — Weekly Status · [[40-entities/acme-industries/dossier|Acme]]") == (
        "09:00", "Weekly Status", "acme-industries")
    assert dailynote.parse_heading("09:00 — Weekly Status") == ("09:00", "Weekly Status", None)
    assert dailynote.parse_heading("no time here") is None


def test_meetings_in_window_counts_meeting_notes_only(tmp_path):
    from datetime import date
    root = make_windowed_vault(tmp_path)
    assert dailynote.meetings_in_window(root, date(2026, 6, 12), date(2026, 6, 12)) == 1
    assert dailynote.meetings_in_window(root, date(2026, 6, 13), date(2026, 6, 14)) == 0
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py -q -k "v2 or banner_is_stripped or parse_heading or meetings_in_window"`
Expected: FAIL (`KeyError: 'contract'`, `AttributeError: parse_heading`, etc.)

- [ ] **Step 3: Implement in `dailynote.py`**

Add imports and constants near the top:

```python
from . import dates, links, markdown, meeting, naming, recap, vault

PREP_HEADING = "#### Prep"
NOTES_BLOCK = "#### Notes\n- "
ACTIONS_BLOCK = "#### Actions\n- [ ] "
_PREP_KEYS = ("attendees", "last_meeting", "context")
_PREP_LABELS = (("attendees", "Attendees"), ("last_meeting", "Last meeting"),
                ("context", "Context"))
_BANNER_FIRST_LINE = "> [!warning] Catch-up note"
```

Replace `_HEADING_RE` and add `parse_heading`:

```python
_HEADING_RE = re.compile(
    r"\A(\d{2}:\d{2}) — (.*?)"
    r"(?: · \[\[(?:40-entities/)?([a-z0-9-]+)(?:/dossier)?(?:\|[^\]]*)?\]\])?\Z")


def parse_heading(text: str):
    """(time, subject, entity slug) for a v1 `· [[slug]]` or v2
    `· [[40-entities/slug/dossier|Name]]` heading; None when not a meeting heading."""
    match = _HEADING_RE.match(str(text).strip())
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)
```

Prep validation — replace the `prep = _clean_region_text(...)` lines inside the meetings loop of `_validate`:

```python
        raw_prep = entry.get("prep")
        if isinstance(raw_prep, dict):
            unknown_prep = sorted(set(raw_prep) - set(_PREP_KEYS))
            missing_prep = [k for k in _PREP_KEYS if not str(raw_prep.get(k) or "").strip()]
            if unknown_prep or missing_prep:
                raise DailyNoteError(
                    f"meeting {position} prep: needs exactly attendees, last_meeting, "
                    f"context (missing {missing_prep}, unknown {unknown_prep})")
            fields = {}
            for key in _PREP_KEYS:
                text = str(raw_prep[key]).strip()
                if "\n" in text or "evening-sync:" in text:
                    raise DailyNoteError(f"meeting {position} prep.{key} must be one line without markers")
                text, bad, warn = links.normalise(root, text, f"meeting {position} prep.{key}")
                link_offenders.extend(bad)
                warnings.extend(warn)
                fields[key] = text
            prep = "\n".join(f"**{label}** — {fields[key]}" for key, label in _PREP_LABELS)
            prep_forms.add("v2")
        else:
            prep = _clean_region_text(raw_prep, f"meeting {position} prep")
            link_offenders.extend(
                _check_links(root, prep, f"meeting {position} prep", warnings))
            prep_forms.add("v1")
```

Initialise `prep_forms: set = set()` before the loop and after it:

```python
    if len(prep_forms) > 1:
        raise DailyNoteError(
            "meetings: every prep must use the same form — all strings (v1) "
            "or all {attendees, last_meeting, context} objects (v2)")
    v2_prep = prep_forms == {"v2"}
```

Recap validation — replace `recap = _clean_region_text(payload.get("recap"), "recap")` and its link check:

```python
    raw_recap = payload.get("recap")
    recap_clean = None
    recap_text = None
    if isinstance(raw_recap, dict):
        if window is None:
            raise DailyNoteError(
                "recap_window is required with a structured (v2) recap — the "
                "CLI computes the glance's meeting count and window label from it")
        try:
            recap_clean, bad, warn = recap.validate(root, raw_recap)
        except recap.RecapError as exc:
            raise DailyNoteError(str(exc)) from exc
        link_offenders.extend(bad)
        warnings.extend(warn)
    else:
        recap_text = _clean_region_text(raw_recap, "recap")
        recap_text, stripped = _strip_model_banner(recap_text)
        if stripped:
            warnings.append(
                "recap: a Catch-up note callout in the payload was stripped — "
                "the CLI writes the banner itself")
        link_offenders.extend(_check_links(root, recap_text, "recap", warnings))
```

with the helper:

```python
def _strip_model_banner(text: str) -> Tuple[str, bool]:
    """Drop a model-written catch-up callout from a v1 recap string."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != _BANNER_FIRST_LINE:
        return text, False
    index = 1
    while index < len(lines) and lines[index].startswith(">"):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    rest = "\n".join(lines[index:]).rstrip()
    if not rest.strip():
        raise DailyNoteError(
            "recap held only a Catch-up note callout — the CLI writes that "
            "banner itself; the payload must carry the recap content")
    return rest, True
```

Return the extra keys from `_validate` (`"recap_clean"`, `"recap_text"`, `"v2_prep"`) inside the returned dict, and compute `contract = "v2" if recap_clean is not None or v2_prep else "v1"`.

Meeting count and window label helpers:

```python
def meetings_in_window(root: Path, start: date, end: date) -> int:
    """Meeting notes dated inside [start, end] — the same set the recap
    fingerprint hashes, so the glance never disagrees with the digest."""
    return sum(1 for relpath, _ in _fingerprint_inputs(root, start, end)
               if relpath.startswith(f"{vault.MEETINGS_DIR}/"))


def _window_label(window: dict) -> str:
    start, end = window["from"], window["to"]
    first = dates.DAY_NAMES[start.weekday()]
    last = dates.DAY_NAMES[end.weekday()]
    return first if start == end else f"{first}–{last}"
```

`_recap_body` becomes:

```python
def _recap_body(root: Path, data: dict) -> str:
    banner = _catchup_banner(root, data["recap_window"])
    if data["recap_clean"] is not None:
        window = data["recap_window"]
        body = recap.render(
            root, data["recap_clean"],
            meetings=meetings_in_window(root, window["from"], window["to"]),
            window_label=_window_label(window))
    else:
        body = data["recap_text"]
    return f"{banner}\n\n{body}" if banner else body
```

Heading and render:

```python
def _heading(meeting: dict, root: Optional[Path] = None, v2: bool = False) -> str:
    heading = f"{meeting['time']} — {meeting['subject']}"
    if meeting["entity"]:
        if v2 and root is not None:
            path = root / vault.ENTITIES_DIR / meeting["entity"] / "dossier.md"
            shown = links.display_name(path, "entity-name") or meeting["entity"]
            heading += f" · [[{links.path_target(root, path)}|{shown}]]"
        else:
            heading += f" · [[{meeting['entity']}]]"
    return heading
```

In `_render`, replace the per-meeting chunk:

```python
        for meeting in data["meetings"]:
            heading = f"### {_heading(meeting, root, data['v2_prep'])}"
            if data["v2_prep"]:
                chunks.append("\n".join([
                    heading, PREP_HEADING, _region("prep", meeting["prep"]), "",
                    NOTES_BLOCK, "", ACTIONS_BLOCK]))
            else:
                chunks.append("\n".join([heading, _region("prep", meeting["prep"]), "- "]))
```

In `_merge`, compare parsed headings instead of raw strings:

```python
        expected = [(m["time"], m["subject"], m["entity"]) for m in data["meetings"]]
        actual = [parse_heading(h) for h in prep_headings]
        if actual != expected:
            raise DailyNoteError(
                "the note's meeting headings don't match the payload — the "
                f"meeting structure changed since this note was written. "
                f"{_STRUCTURAL_HINT}")
```

In `write`, add `"contract": data["contract"]` to the returned dict, and pass `data` through unchanged otherwise.

- [ ] **Step 4: Run the whole daily-note suite**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py -q`
Expected: every test passes, including `test_fresh_fixture_is_exactly_what_daily_note_write_renders` (v1 byte-identity) and `test_merge_refuses_an_entity_only_heading_change` (parsed comparison still detects an entity change).

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "feat(daily-note): v2 write — structured recap and prep, Prep/Notes/Actions layout, banner strip

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `daily-note read` — notes and actions per meeting

**Files:**
- Modify: `plugin/lib/vaultlib/dailynote.py:611-705` (`read`)
- Test: `scripts/tests/test_vaultlib_dailynote.py` (append)

**Interfaces:**
- Produces: each entry of `read()["meetings"]` gains `notes: list[str]`, `actions: list[{"text": str, "done": bool}]`; `jottings` stays as the union (notes then action texts) for backward compatibility.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_splits_notes_and_actions_under_a_v2_meeting(tmp_path):
    root = v2_vault(tmp_path)
    dailynote.write(root, v2_payload())
    note = root / "60-daily-notes" / "2026-06-15.md"
    text = note.read_text(encoding="utf-8")
    text = text.replace("#### Notes\n- \n\n#### Actions\n- [ ] \n\n### 14:00",
                        "#### Notes\n- shortlist looks final\n- Sam wants a demo\n\n"
                        "#### Actions\n- [ ] send the scoring sheet\n- [x] book the demo\n\n### 14:00")
    note.write_text(text, encoding="utf-8")
    data = dailynote.read(root, "2026-06-15")
    first = data["meetings"][0]
    assert first["time"] == "09:00" and first["entity"] == "acme-industries"
    assert first["notes"] == ["shortlist looks final", "Sam wants a demo"]
    assert first["actions"] == [{"text": "send the scoring sheet", "done": False},
                                {"text": "book the demo", "done": True}]
    assert first["jottings"] == ["shortlist looks final", "Sam wants a demo",
                                 "send the scoring sheet", "book the demo"]
    assert first["prep"].startswith("**Attendees** — Sam Okafor")
    second = data["meetings"][1]
    assert second["notes"] == [] and second["actions"] == []


def test_read_keeps_v1_bullets_as_notes(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    note = root / "60-daily-notes" / "2026-06-15.md"
    text = note.read_text(encoding="utf-8").replace(
        "<!-- evening-sync:prep:end -->\n- \n\n### 14:00",
        "<!-- evening-sync:prep:end -->\n- old style jot\n\n### 14:00")
    note.write_text(text, encoding="utf-8")
    data = dailynote.read(root, "2026-06-15")
    assert data["meetings"][0]["notes"] == ["old style jot"]
    assert data["meetings"][0]["actions"] == []
    assert data["meetings"][0]["jottings"] == ["old style jot"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py -q -k "splits_notes or v1_bullets_as_notes"`
Expected: FAIL with `KeyError: 'notes'`

- [ ] **Step 3: Implement in `read`**

Add a checkbox regex near the top of the module:

```python
_TASK_RE = re.compile(r"\A- \[( |x|X)\]\s*(.*)\Z")
```

In `read`, when a meeting heading is parsed, initialise `"notes": [], "actions": []` alongside `"jottings": []`, and track a `sub` state per meeting. Replace the body-line handling after the `### ` branch:

```python
        if section == "Meetings" and line.startswith("#### ") and current is not None:
            sub = line[5:].strip().lower()      # "prep" | "notes" | "actions" | anything
            continue
        stripped = line.strip()
        if not stripped:
            continue
        task = _TASK_RE.match(stripped)
        if task and section == "Meetings" and current is not None:
            text_value = task.group(2).strip()
            if text_value:
                current["actions"].append({"text": text_value, "done": task.group(1) != " "})
                current["jottings"].append(text_value)
            continue
        content = stripped[2:].strip() if stripped.startswith("- ") else (
            "" if stripped == "-" else stripped)
        if not content:
            continue
        if section == "End of day":
            end_of_day.append(content)
        elif section == "Meetings" and current is not None:
            if sub == "prep":
                continue            # a prep line outside the markers is still prep
            current["notes"].append(content)
            current["jottings"].append(content)
        else:
            other_lines.append(content)
```

Reset `sub = ""` whenever a new `### ` meeting heading or a `## ` section starts. Use `parse_heading` for the `### ` branch:

```python
            parsed = parse_heading(heading)
            current = {
                "heading": heading,
                "time": parsed[0] if parsed else None,
                "subject": parsed[1] if parsed else heading,
                "entity": parsed[2] if parsed else None,
                "prep": None, "notes": [], "actions": [], "jottings": [],
            }
```

- [ ] **Step 4: Run the suite**

Run: `python3 -m pytest scripts/tests/test_vaultlib_dailynote.py -q`
Expected: PASS (including `test_read_parses_every_daily_note_fixture`).

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/dailynote.py scripts/tests/test_vaultlib_dailynote.py
git commit -m "feat(daily-note): read returns notes and checkbox actions per meeting

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `projectstate.py` and `project state write`

**Files:**
- Create: `plugin/lib/vaultlib/projectstate.py`
- Modify: `plugin/lib/vaultlib/cli.py:170-200` (subparser), `:644-660` (dispatch), `:845-870` (error mapping)
- Test: `scripts/tests/test_vaultlib_projectstate.py` (new)

**Interfaces:**
- Consumes: `project.touch`, `links.*`, `markdown.split_frontmatter`, `vault.atomic_write`, `naming.validate_slug`.
- Produces:
  - `projectstate.ProjectStateError(Exception)`
  - `projectstate.render_body(name: str, slug: str, state: dict) -> str` — no validation, used by `scaffold` and migration 002. `state` keys (all optional except `as_of`): `as_of` (ISO date), `stage`, `hot_potatoes: [{"signal","text"}]`, `insights: [str]`, `defining_decision: Optional[str]` (already a rendered link or None), `coming_up: [{"when","what"}]`, `owe: [{"owner","items":[str]}]`, `awaiting`, `questions`, `pending`, `watch` (lists of str), `context: {"contacts","source"}`, `notes_tail: Optional[str]` (verbatim text after `## Notes`).
  - `projectstate.validate(root, slug, raw) -> tuple[dict, list[str], list[str]]` — caps; link normalisation; returns `(state_for_render, offenders, warnings)`; also returns `raw["next_milestone"]` untouched under `state["next_milestone"]`.
  - `projectstate.write(root, *, slug, payload, today, timestamp=None) -> dict`.
  - `projectstate.split_notes_tail(body: str) -> tuple[str, Optional[str]]`.
  - `projectstate.display_long_date(iso) -> str` → `"15 September"`.
  - CLI: `project state write --vault V --slug S --state <file|-> [--today ISO] [--timestamp ISO-datetime]`.

- [ ] **Step 1: Write the failing tests**

```python
# scripts/tests/test_vaultlib_projectstate.py
"""project state write: the index body is rendered from JSON, never edited."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import project, projectstate

from test_vaultlib_project import vault_with_entity

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"


def scaffolded(tmp_path):
    root = vault_with_entity(tmp_path)
    (root / "50-people").mkdir(exist_ok=True)
    (root / "50-people" / "priya-nathan.md").write_text(
        "---\nperson-name: Priya Nathan\nslug: priya-nathan\nrelationship: internal\n---\n",
        encoding="utf-8")
    result = project.scaffold(root, name="Yard Automation Program", project_type="initiative",
                              entity="meridian-freight-holdings", owner="priya-nathan",
                              today="2026-06-01")
    slug = result["slug"]
    (root / "30-projects" / slug / "decisions" / "2026-05-20-single-vendor-strategy-adopted.md").write_text(
        "---\ntype: decision\nproject: " + slug + "\ndate: 2026-05-20\nstatus: active\n"
        'summary: "Single-vendor consolidation adopted"\n---\n', encoding="utf-8")
    return root, slug


def state():
    return {
        "as_of": "2026-06-15",
        "stage": "Yard 1 commissioned; yards 2–3 being re-scoped after the May consolidation.",
        "hot_potatoes": [{"signal": "red", "text": "Renee owns the integration work and was not in the room."}],
        "insights": ["The six-week slip is schedule, not scope."],
        "defining_decision": "2026-05-20-single-vendor-strategy-adopted",
        "coming_up": [{"when": "Tue 1 Sept", "what": "Vendor contract signature", "date": "2026-09-01"},
                      {"when": "Mon 22 June", "what": "Commissioning schedule to Leo", "date": "2026-06-22"}],
        "owe": [{"owner": "Priya Nathan", "items": ["Revised commissioning schedule to Leo Marchetti."]}],
        "awaiting": ["Consolidated integration estimate from the yard-1 vendor."],
        "questions": ["Does yard 3's PLC refresh sit inside this scope?"],
        "pending": ["Single-vendor contract signature, target 1 Sept."],
        "watch": ["Roughly six weeks of slip against the phased plan."],
        "context": {"contacts": "Leo Marchetti (COO)", "source": "Follow-on from Phase 0"},
        "next_milestone": {"text": "Vendor contract signature", "date": "2026-09-01"},
    }


def test_write_renders_the_v2_body_and_touches_frontmatter(tmp_path):
    root, slug = scaffolded(tmp_path)
    result = projectstate.write(root, slug=slug, payload=state(), today="2026-06-15",
                                timestamp="2026-06-15T20:30")
    text = (root / "30-projects" / slug / "index.md").read_text(encoding="utf-8")
    fm, body = md.split_frontmatter(text)
    assert fm["last-updated"] == "2026-06-15" and fm["state-updated"] == "2026-06-15T20:30"
    assert fm["next-milestone"] == "Vendor contract signature"
    assert body.startswith("\n# Yard Automation Program\n\n> [!summary] Where it stands — 15 June\n")
    assert "> - **Stage** — Yard 1 commissioned" in body
    assert "> - **Hot potato** — 🔴 Renee owns" in body
    assert "> - **Insight** — The six-week slip" in body
    assert ("> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted|"
            "Single-vendor consolidation adopted]] (20 May)") in body
    # coming up is sorted by date, earliest first
    assert body.index("Commissioning schedule to Leo") < body.index("Vendor contract signature |")
    assert "## Coming up\n\n| When | What |\n|---|---|\n| Mon 22 June | Commissioning schedule to Leo |" in body
    assert "## Recent meetings" in body and 'dateformat(date, "ccc dd-MM")' in body and "LIMIT 10" in body
    assert "## Recent decisions" in body and f'FROM "30-projects/{slug}/decisions"' in body
    assert "## Background" in body
    assert "> [!todo]- 📤 Owe — by owner\n> - **Priya Nathan**\n>   - Revised commissioning schedule" in body
    assert "> [!info]- 👤 Awaiting\n> - Consolidated" in body
    assert "> [!question]- ❓ Open questions\n> - Does yard 3" in body
    assert "> [!note]- ⏳ Pending\n> - Single-vendor" in body
    assert "> [!warning]- Watch list\n> - Roughly six weeks" in body
    assert "> [!info]- Context\n> - **Contacts** — Leo Marchetti (COO)\n> - **Source** — Follow-on from Phase 0" in body
    assert [t for t, _ in md.split_sections(body)][1:] == [
        "Coming up", "Recent meetings", "Recent decisions", "Background"]
    assert result["changed"] is True and result["slug"] == slug


def test_write_preserves_a_human_notes_tail(tmp_path):
    root, slug = scaffolded(tmp_path)
    path = root / "30-projects" / slug / "index.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## Notes\n\n- my own note\n", encoding="utf-8")
    projectstate.write(root, slug=slug, payload=state(), today="2026-06-15")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n## Notes\n\n- my own note\n")
    assert text.count("## Notes") == 1


def test_write_is_idempotent(tmp_path):
    root, slug = scaffolded(tmp_path)
    projectstate.write(root, slug=slug, payload=state(), today="2026-06-15", timestamp="2026-06-15T20:30")
    before = (root / "30-projects" / slug / "index.md").read_bytes()
    result = projectstate.write(root, slug=slug, payload=state(), today="2026-06-15", timestamp="2026-06-15T20:30")
    assert (root / "30-projects" / slug / "index.md").read_bytes() == before
    assert result["changed"] is False


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s.__setitem__("stage", " ".join(["w"] * 61)), "stage: ≤ 60 words"),
    (lambda s: s["hot_potatoes"].extend([s["hot_potatoes"][0]] * 3), "hot_potatoes: ≤ 3"),
    (lambda s: s["hot_potatoes"][0].__setitem__("signal", "green"), "signal"),
    (lambda s: s["insights"].extend(["a", "b"]), "insights: ≤ 2"),
    (lambda s: s["coming_up"].extend([{"when": "x", "what": "y"}] * 9), "coming_up: ≤ 10"),
    (lambda s: s["owe"][0]["items"].append("a; b; c; d; e; f; g; h"), "one item per bullet"),
    (lambda s: s["awaiting"].append(" ".join(["w"] * 41)), "≤ 40 words"),
    (lambda s: s.__setitem__("defining_decision", "not-a-decision"), "defining_decision"),
    (lambda s: s.__setitem__("next_milestone", {"text": "x"}), "next_milestone"),
    (lambda s: s.__setitem__("bogus", 1), "unknown"),
])
def test_caps_are_refused_by_field(tmp_path, mutate, message):
    root, slug = scaffolded(tmp_path)
    payload = state()
    mutate(payload)
    with pytest.raises(projectstate.ProjectStateError, match=message):
        projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")


def test_identity_links_in_free_text_are_normalised_and_bad_ones_refused(tmp_path):
    root, slug = scaffolded(tmp_path)
    payload = state()
    payload["watch"] = ["[[meridian-freight-holdings]] wants a date"]
    projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")
    body = (root / "30-projects" / slug / "index.md").read_text(encoding="utf-8")
    assert "[[40-entities/meridian-freight-holdings/dossier|" in body
    payload["watch"] = ["[[no-such-thing]]"]
    with pytest.raises(projectstate.ProjectStateError, match="no-such-thing"):
        projectstate.write(root, slug=slug, payload=payload, today="2026-06-15")


def test_scaffold_renders_the_v2_body_with_placeholders(tmp_path):
    root, slug = scaffolded(tmp_path)
    body = md.split_frontmatter((root / "30-projects" / slug / "index.md").read_text(encoding="utf-8"))[1]
    assert "> [!summary] Where it stands — 1 June" in body
    assert "> - **Stage** — _newly created; awaiting first meeting or intake_" in body
    assert "> - **Defining decision** — _none yet_" in body
    assert "## Coming up\n\n_none scheduled_" in body
    assert "> [!todo]- 📤 Owe — by owner\n> - _none yet_" in body


def test_cli_state_write_envelope(tmp_path):
    root, slug = scaffolded(tmp_path)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state()), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(CLI), "project", "state", "write", "--vault", str(root),
                           "--slug", slug, "--state", str(state_file), "--today", "2026-06-15"],
                          capture_output=True, text=True)
    envelope = json.loads(proc.stdout)
    assert proc.returncode == 0 and envelope["ok"] is True
    assert envelope["result"]["slug"] == slug and envelope["result"]["changed"] is True
    bad = state(); bad["stage"] = " ".join(["w"] * 61)
    state_file.write_text(json.dumps(bad), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(CLI), "project", "state", "write", "--vault", str(root),
                           "--slug", slug, "--state", str(state_file)], capture_output=True, text=True)
    envelope = json.loads(proc.stdout)
    assert proc.returncode != 0 and envelope["ok"] is False and "stage" in envelope["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_vaultlib_projectstate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vaultlib.projectstate'`

- [ ] **Step 3: Write `projectstate.py`**

```python
# plugin/lib/vaultlib/projectstate.py
"""The project index body, rendered from a state object.

Stage-4 subagents used to edit the index's Markdown by hand, and a skill
saying "exactly 5 bullets" did not stop 600-word bullets. Here the model
returns JSON and the CLI renders: caps are refused by field, identity links
are normalised, and the one human area (a trailing `## Notes` section) is
preserved verbatim. `render_body` has no validation on purpose — `scaffold`
renders placeholders through it and migration 002 renders legacy prose that
may exceed the caps; only `write` (the evening run) enforces them.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from . import links, markdown, naming, project, vault

PLACEHOLDER = "_none yet_"
SIGNALS = {"red": "🔴", "amber": "🟠"}
_LIST_KEYS = ("awaiting", "questions", "pending", "watch")
_ALLOWED = ("as_of", "stage", "hot_potatoes", "insights", "defining_decision",
            "coming_up", "owe") + _LIST_KEYS + ("context", "next_milestone")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_NOTES_MARKER = "\n## Notes\n"


class ProjectStateError(Exception):
    """A state field the caller must fix."""


def display_long_date(iso: str) -> str:
    day = datetime.strptime(iso, "%Y-%m-%d")
    return f"{day.day} {_MONTHS[day.month - 1]}"


def _words(text: str) -> int:
    return len(str(text).split())


def _line(value, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProjectStateError(f"{label} must be a non-empty string")
    if "\n" in text or "\r" in text:
        raise ProjectStateError(f"{label} must be one line")
    if _words(text) > limit:
        raise ProjectStateError(f"{label}: ≤ {limit} words (got {_words(text)})")
    return text


def _list(raw, label: str, limit_words: int = 40) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProjectStateError(f"{label} must be a list of one-line strings")
    return [_line(item, f"{label}[{i}]", limit_words) for i, item in enumerate(raw)]


def split_notes_tail(body: str) -> Tuple[str, Optional[str]]:
    """(machine body, verbatim `## Notes` tail or None)."""
    index = body.find(_NOTES_MARKER)
    if index < 0:
        return body, None
    return body[:index], body[index:]


def _dataview_meetings(slug: str) -> str:
    return "\n".join([
        "```dataview", "TABLE WITHOUT ID",
        '  link(file.path, dateformat(date, "ccc dd-MM")) AS "Date",',
        '  calendar-subject AS "Subject",',
        '  slice(attendees, 0, 3) AS "With",',
        '  recording-duration AS "Min"',
        f'FROM "{vault.MEETINGS_DIR}"',
        "WHERE econtains(projects, this.slug)",
        "SORT date DESC", "LIMIT 10", "```"])


def _dataview_decisions(slug: str) -> str:
    return "\n".join([
        "```dataview", "TABLE WITHOUT ID",
        '  link(file.path, dateformat(date, "dd-MM")) AS "Date",',
        '  summary AS "Decision",',
        '  status AS "Status"',
        f'FROM "{vault.PROJECTS_DIR}/{slug}/decisions"',
        "SORT date DESC", "LIMIT 10", "```"])


def _folded(kind: str, title: str, lines: List[str]) -> str:
    body = lines or [f"- {PLACEHOLDER}"]
    return "\n".join([f"> [!{kind}]- {title}"] + [f"> {line}" for line in body])


def render_body(name: str, slug: str, state: dict) -> str:
    """The v2 body from `# name` to the end of `## Background` (plus the
    preserved notes tail). No caps here — see the module docstring."""
    stand = [f"> [!summary] Where it stands — {display_long_date(state['as_of'])}"]
    stand.append(f"> - **Stage** — {state.get('stage') or '_newly created; awaiting first meeting or intake_'}")
    for potato in state.get("hot_potatoes") or []:
        stand.append(f"> - **Hot potato** — {SIGNALS.get(potato['signal'], '🟠')} {potato['text']}")
    for insight in state.get("insights") or []:
        stand.append(f"> - **Insight** — {insight}")
    stand.append(f"> - **Defining decision** — {state.get('defining_decision') or PLACEHOLDER}")

    coming = state.get("coming_up") or []
    if coming:
        table = ["| When | What |", "|---|---|"]
        table += [f"| {row['when']} | {row['what']} |" for row in coming]
        coming_block = "\n".join(table)
    else:
        coming_block = "_none scheduled_"

    owe_lines: List[str] = []
    for group in state.get("owe") or []:
        owe_lines.append(f"- **{group['owner']}**")
        owe_lines += [f"  - {item}" for item in group["items"]]
    context = state.get("context") or {}
    background = "\n\n".join([
        "Reference material for the evening run and for when you need the detail. Folded by default.",
        _folded("todo", "📤 Owe — by owner", owe_lines),
        _folded("info", "👤 Awaiting", [f"- {x}" for x in state.get("awaiting") or []]),
        _folded("question", "❓ Open questions", [f"- {x}" for x in state.get("questions") or []]),
        _folded("note", "⏳ Pending", [f"- {x}" for x in state.get("pending") or []]),
        _folded("warning", "Watch list", [f"- {x}" for x in state.get("watch") or []]),
        _folded("info", "Context", [
            f"- **Contacts** — {context.get('contacts') or PLACEHOLDER}",
            f"- **Source** — {context.get('source') or PLACEHOLDER}"]),
    ])
    body = "\n".join([
        "", f"# {name}", "", "\n".join(stand), "",
        "## Coming up", "", coming_block, "",
        "## Recent meetings", "", _dataview_meetings(slug), "",
        "## Recent decisions", "", _dataview_decisions(slug), "",
        "## Background", "", background, ""])
    tail = state.get("notes_tail")
    return body + (tail if tail else "")


def _norm(root, text, label, offenders, warnings) -> str:
    out, bad, warn = links.normalise(root, text, label)
    offenders.extend(bad)
    warnings.extend(warn)
    return out


def validate(root: Path, slug: str, raw) -> Tuple[dict, List[str], List[str]]:
    if not isinstance(raw, dict):
        raise ProjectStateError("state must be a JSON object")
    unknown = sorted(set(raw) - set(_ALLOWED))
    if unknown:
        raise ProjectStateError(f"state: unknown key(s) {unknown}")
    offenders: List[str] = []
    warnings: List[str] = []
    as_of = str(raw.get("as_of") or "").strip()
    if not vault.ISO_DATE_RE.match(as_of):
        raise ProjectStateError("as_of must be ISO YYYY-MM-DD")
    datetime.strptime(as_of, "%Y-%m-%d")
    state = {"as_of": as_of}
    state["stage"] = _norm(root, _line(raw.get("stage"), "stage", 60), "stage", offenders, warnings)

    potatoes = raw.get("hot_potatoes") or []
    if not isinstance(potatoes, list) or len(potatoes) > 3:
        raise ProjectStateError("hot_potatoes: ≤ 3 items")
    state["hot_potatoes"] = []
    for i, potato in enumerate(potatoes):
        if not isinstance(potato, dict) or set(potato) != {"signal", "text"}:
            raise ProjectStateError(f"hot_potatoes[{i}] needs exactly signal and text")
        if potato["signal"] not in SIGNALS:
            raise ProjectStateError(f"hot_potatoes[{i}].signal must be red or amber")
        state["hot_potatoes"].append({
            "signal": potato["signal"],
            "text": _norm(root, _line(potato["text"], f"hot_potatoes[{i}].text", 30),
                          f"hot_potatoes[{i}]", offenders, warnings)})
    insights = raw.get("insights") or []
    if len(insights) > 2:
        raise ProjectStateError("insights: ≤ 2 items")
    state["insights"] = [_norm(root, x, f"insights[{i}]", offenders, warnings)
                         for i, x in enumerate(_list(insights, "insights", 30))]

    decision = raw.get("defining_decision")
    state["defining_decision"] = None
    if decision:
        kind, path, _ = links.resolve(root, str(decision))
        if kind != "decision" or path.parent.parent.name != slug:
            raise ProjectStateError(
                f"defining_decision {decision!r} is not a decision under "
                f"{vault.PROJECTS_DIR}/{slug}/decisions/")
        fm, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        summary = str(fm.get("summary") or "").strip() or str(decision)
        when = str(fm.get("date") or "")[:10]
        suffix = f" ({display_long_date(when)})" if vault.ISO_DATE_RE.match(when) else ""
        state["defining_decision"] = f"[[{decision}|{summary}]]{suffix}"

    coming = raw.get("coming_up") or []
    if not isinstance(coming, list) or len(coming) > 10:
        raise ProjectStateError("coming_up: ≤ 10 rows")
    rows = []
    for i, row in enumerate(coming):
        if not isinstance(row, dict) or not {"when", "what"} <= set(row) or set(row) - {"when", "what", "date"}:
            raise ProjectStateError(f"coming_up[{i}] needs when, what and optionally date")
        date_value = str(row.get("date") or "")
        if date_value and not vault.ISO_DATE_RE.match(date_value):
            raise ProjectStateError(f"coming_up[{i}].date must be ISO YYYY-MM-DD")
        rows.append((date_value or "9999-12-31", i, {
            "when": _line(row["when"], f"coming_up[{i}].when", 8),
            "what": _norm(root, _line(row["what"], f"coming_up[{i}].what", 40),
                          f"coming_up[{i}]", offenders, warnings)}))
    state["coming_up"] = [row for _, _, row in sorted(rows, key=lambda r: (r[0], r[1]))]

    owe = raw.get("owe") or []
    if not isinstance(owe, list):
        raise ProjectStateError("owe must be a list of {owner, items}")
    state["owe"] = []
    for i, group in enumerate(owe):
        if not isinstance(group, dict) or set(group) != {"owner", "items"}:
            raise ProjectStateError(f"owe[{i}] needs exactly owner and items")
        items = _list(group["items"], f"owe[{i}].items")
        for j, item in enumerate(items):
            if item.count(";") >= 3:
                raise ProjectStateError(
                    f"owe[{i}].items[{j}] chains several tasks with ';' — one item per bullet")
        state["owe"].append({
            "owner": _line(group["owner"], f"owe[{i}].owner", 8),
            "items": [_norm(root, x, f"owe[{i}].items[{j}]", offenders, warnings)
                      for j, x in enumerate(items)]})
    for key in _LIST_KEYS:
        state[key] = [_norm(root, x, f"{key}[{i}]", offenders, warnings)
                      for i, x in enumerate(_list(raw.get(key), key))]

    context = raw.get("context") or {}
    if not isinstance(context, dict) or set(context) - {"contacts", "source"}:
        raise ProjectStateError("context allows contacts and source")
    state["context"] = {k: (_norm(root, _line(v, f"context.{k}", 60), f"context.{k}", offenders, warnings)
                            if str(v or "").strip() else None) for k, v in context.items()}

    milestone = raw.get("next_milestone")
    if milestone is not None:
        if not isinstance(milestone, dict) or set(milestone) != {"text", "date"}:
            raise ProjectStateError("next_milestone needs exactly text and date")
        state["next_milestone"] = {"text": _line(milestone["text"], "next_milestone.text", 40),
                                   "date": str(milestone["date"])}
    else:
        state["next_milestone"] = None
    return state, offenders, warnings


def write(root: Path, *, slug: str, payload, today: str,
          timestamp: Optional[str] = None) -> dict:
    try:
        naming.validate_slug(str(slug or "").strip())
    except ValueError as exc:
        raise ProjectStateError(f"slug {slug!r}: {exc}") from exc
    index_path = root / vault.PROJECTS_DIR / slug / "index.md"
    if not index_path.is_file():
        raise ProjectStateError(
            f"no project {slug!r} at {vault.PROJECTS_DIR}/{slug}/index.md — create it first with /new-project")
    state, offenders, warnings = validate(root, slug, payload)
    if offenders:
        raise ProjectStateError("\n".join(offenders))
    # split_frontmatter normalises CRLF before matching and returns the body
    # as a suffix of the *normalised* text, so normalise first or `head`
    # would be sliced off the wrong string.
    text = index_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    frontmatter, body = markdown.split_frontmatter(text)
    assert text.endswith(body)
    head = text[:len(text) - len(body)]
    name = str(frontmatter.get("project-name") or slug)
    _, tail = split_notes_tail(body)
    state["notes_tail"] = tail
    new_text = head + render_body(name, slug, state)
    changed = new_text != text
    if changed:
        vault.atomic_write(index_path, new_text)
    milestone = state["next_milestone"]
    try:
        touched = project.touch(
            root, slug=slug, date_iso=today, timestamp=timestamp,
            next_milestone=milestone["text"] if milestone else None,
            next_milestone_date=milestone["date"] if milestone else None)
    except project.ProjectError as exc:
        raise ProjectStateError(str(exc)) from exc
    return {"slug": slug, "path": f"{vault.PROJECTS_DIR}/{slug}/index.md",
            "changed": changed or touched["changed"], "warnings": warnings,
            "last-updated": touched["last-updated"], "state-updated": touched["state-updated"],
            "next-milestone": touched["next-milestone"]}
```

`markdown.split_frontmatter` runs `_normalize` (CRLF → LF) and returns the body as a suffix of the normalised text, which is why `write` normalises before slicing `head`.

- [ ] **Step 4: Make `scaffold` use the renderer**

In `plugin/lib/vaultlib/project.py`, delete `_render_body` and the `_PLACEHOLDER` constant; in `scaffold` replace the `body = _render_body(...)` line with:

```python
    from . import projectstate   # local import: projectstate imports project for touch
    body = projectstate.render_body(name, slug, {
        "as_of": today, "stage": stage,
        "context": {"contacts": contacts, "source": source}})
```

Keep `_display_date` only if something else uses it (grep; delete if not).

- [ ] **Step 5: Wire the CLI**

In `cli.py` after the `proj_touch` block:

```python
    proj_state = projects_sub.add_parser(
        "state", help="project state: render the index body from JSON")
    proj_state_sub = proj_state.add_subparsers(dest="state_action", required=True)
    proj_state_write = proj_state_sub.add_parser(
        "write", help="replace the index body from a state JSON and touch the frontmatter")
    _add_vault_argument(proj_state_write)
    proj_state_write.add_argument("--slug", required=True)
    proj_state_write.add_argument("--state", required=True,
                                  help="path to a JSON file, or - to read stdin")
    proj_state_write.add_argument("--today", help="ISO date; defaults to today")
    proj_state_write.add_argument("--timestamp",
                                  help="ISO datetime YYYY-MM-DDTHH:MM; defaults to now")
```

In the dispatch, before the `touch` branch:

```python
        if args.action == "state":
            payload = (json.load(sys.stdin) if args.state == "-"
                       else json.loads(Path(args.state).read_text(encoding="utf-8")))
            return _ok(projectstate.write(
                root, slug=args.slug, payload=payload,
                today=vault.today_iso(args.today), timestamp=args.timestamp))
```

Add `projectstate` to the `from vaultlib import …` line and an error mapping next to the project one:

```python
    except projectstate.ProjectStateError as exc:
        return _fail(str(exc), "Fix the named state field and retry.")
```

- [ ] **Step 6: Update `test_vaultlib_project.py` for the v2 body**

Change `test_body_carries_the_three_ontology_sections` to assert the H2 titles equal `["Coming up", "Recent meetings", "Recent decisions", "Background"]` (rename it `test_body_carries_the_four_ontology_sections`). In `test_decisions_dataview_hardcodes_this_project_slug` and `test_related_meetings_dataview_matches_on_this_slug` keep the assertions (`FROM "30-projects/<slug>/decisions"` and `econtains(projects, this.slug)`) — both still hold. `test_supplied_context_reaches_the_context_callout` now looks for `> - **Contacts** — …` inside the folded `Context` callout; `test_absent_context_falls_back_to_placeholders` looks for `_none yet_`. Run the file and fix any assertion that pins the old `**Now**` text.

- [ ] **Step 7: Run the tests**

Run: `python3 -m pytest scripts/tests/test_vaultlib_projectstate.py scripts/tests/test_vaultlib_project.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS. (`test_fixtures_ontology` will fail until Task 7 — that is expected here and is why Task 7 changes the ontology and fixtures together.)

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/vaultlib/projectstate.py plugin/lib/vaultlib/project.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_projectstate.py scripts/tests/test_vaultlib_project.py
git commit -m "feat(project): state write — v2 index body rendered from JSON with caps; scaffold uses it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Migration 002 — reshape v1 project indexes (structure-version 3)

**Files:**
- Create: `plugin/migrations/002-structure-version-3/migrate.py`
- Test: `scripts/tests/test_migration_002.py` (new)

**Interfaces:**
- Consumes: `projectstate.render_body`, `markdown.split_frontmatter`, `markdown.split_sections`, `vault.atomic_write`.
- Produces: `TARGET_VERSION = 3`, `LOSSY = None`, `apply(root) -> {"reshaped": [slugs], "skipped": [slugs], "unparsed": [paths]}`, `verify(root) -> {"checked": N}` raising `RuntimeError` when a v1 heading survives. Also exports `parse_v1_body(body: str) -> dict` for tests.

- [ ] **Step 1: Write the failing tests**

```python
# scripts/tests/test_migration_002.py
"""Migration 002: project index v1 (Now / Decisions / Open Items / Related
Meetings) → v2 (Where it stands / Coming up / Recent meetings / Recent
decisions / Background). Reshape only — every sentence survives."""
import importlib.util
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import migrate

from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
M002 = REPO_ROOT / "plugin" / "migrations" / "002-structure-version-3" / "migrate.py"
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"


def load():
    spec = importlib.util.spec_from_file_location("m002", M002)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1_INDEX = """---
type: project
project-name: "Yard Automation Program"
slug: meridian-yard-automation-program
status: active
project-type: initiative
entity: meridian-freight-holdings
owner: priya-nathan
created: 2026-02-15
last-updated: 2026-06-01
---

# Yard Automation Program

> [!summary]+ **Now** — as of 01-06-26
> - **Stage** — Yard 1 commissioned; yards 2–3 being re-scoped.
> - **Defining decision** — [[2026-05-20-single-vendor-strategy-adopted]]
> - **Next event** — Vendor contract signature, target 2026-09-01; steering call, Thursday 4 June
> - **Owe** — 📤 Priya Nathan: revised commissioning schedule to Leo; align with Renee · 📤 Leo Marchetti: confirm the sponsor date
> - **Watch** — Roughly six weeks of slip; Renee was not in the room when it was agreed

> [!info]- **Context**
> - **Contacts** — Leo Marchetti (COO), Renee Castillo (IT Director)
> - **Source** — Follow-on from the Phase 0 warehouse pilot

## Decisions

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM-yy")) AS "Date"
FROM "30-projects/meridian-yard-automation-program/decisions"
```

## Open Items

- **📤 Owe** — Priya Nathan: revised commissioning schedule to Leo (by 2026-06-15); Jamie Ellwood: floor walk with the vendor
- **👤 Awaiting** — Consolidated integration estimate from the yard-1 vendor; Renee's availability for the July cut-over
- **❓ Question** — Whether yard 3's PLC refresh sits inside this scope
- **⏳ Pending** — _none yet_

## Related Meetings

```dataview
TABLE WITHOUT ID
  link(file.path, dateformat(date, "dd-MM HH:mm")) AS "Date"
FROM "20-meetings"
WHERE econtains(projects, this.slug)
```
"""


def vault_with_v1_index(tmp_path):
    root = make_vault(tmp_path)
    folder = root / "30-projects" / "meridian-yard-automation-program"
    (folder / "decisions").mkdir(parents=True)
    (folder / "index.md").write_text(V1_INDEX, encoding="utf-8")
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    return root


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 3
    assert module.LOSSY is None


def test_discover_chains_001_then_002():
    found = migrate.discover()
    assert [m["number"] for m in found][:2] == [1, 2]
    assert [m["module"].TARGET_VERSION for m in found][:2] == [2, 3]


def test_parse_v1_body_splits_the_mega_lines():
    module = load()
    _, body = md.split_frontmatter(V1_INDEX)
    parsed = module.parse_v1_body(body)
    assert parsed["stage"] == "Yard 1 commissioned; yards 2–3 being re-scoped."
    assert parsed["defining_decision"] == "[[2026-05-20-single-vendor-strategy-adopted]]"
    assert [r["what"] for r in parsed["coming_up"]] == [
        "Vendor contract signature, target 2026-09-01", "steering call, Thursday 4 June"]
    owe = {g["owner"]: g["items"] for g in parsed["owe"]}
    assert owe["Priya Nathan"] == ["revised commissioning schedule to Leo", "align with Renee",
                                   "revised commissioning schedule to Leo (by 2026-06-15)"]
    assert owe["Leo Marchetti"] == ["confirm the sponsor date"]
    assert owe["Jamie Ellwood"] == ["floor walk with the vendor"]
    assert parsed["awaiting"] == ["Consolidated integration estimate from the yard-1 vendor",
                                  "Renee's availability for the July cut-over"]
    assert parsed["questions"] == ["Whether yard 3's PLC refresh sits inside this scope"]
    assert parsed["pending"] == []
    assert parsed["watch"] == ["Roughly six weeks of slip", "Renee was not in the room when it was agreed"]
    assert parsed["context"] == {"contacts": "Leo Marchetti (COO), Renee Castillo (IT Director)",
                                 "source": "Follow-on from the Phase 0 warehouse pilot"}


def test_apply_reshapes_and_keeps_every_sentence(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    result = module.apply(root)
    assert result["reshaped"] == ["meridian-yard-automation-program"]
    text = (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_text(encoding="utf-8")
    fm, body = md.split_frontmatter(text)
    assert fm["last-updated"] == "2026-06-01"          # frontmatter untouched
    assert [t for t, _ in md.split_sections(body)][1:] == [
        "Coming up", "Recent meetings", "Recent decisions", "Background"]
    assert "> [!summary] Where it stands — 1 June" in body
    for sentence in ("Yard 1 commissioned", "[[2026-05-20-single-vendor-strategy-adopted]]",
                     "steering call, Thursday 4 June", "confirm the sponsor date",
                     "floor walk with the vendor", "Renee's availability for the July cut-over",
                     "PLC refresh", "Renee was not in the room", "Renee Castillo (IT Director)"):
        assert sentence in body, sentence
    assert "| Vendor contract signature, target 2026-09-01 |" in body
    assert "> - **Priya Nathan**\n>   - revised commissioning schedule to Leo\n" in body
    assert "LIMIT 10" in body and 'dateformat(date, "ccc dd-MM")' in body
    module.verify(root)


def test_apply_is_idempotent_and_skips_v2(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    module.apply(root)
    once = (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_bytes()
    result = module.apply(root)
    assert result["reshaped"] == [] and result["skipped"] == ["meridian-yard-automation-program"]
    assert (root / "30-projects" / "meridian-yard-automation-program" / "index.md").read_bytes() == once


def test_verify_fails_when_a_v1_heading_survives(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    with pytest.raises(RuntimeError, match="Open Items"):
        module.verify(root)


def test_apply_flags_an_unparseable_index_and_leaves_it(tmp_path):
    module = load()
    root = vault_with_v1_index(tmp_path)
    broken = root / "30-projects" / "broken" / "index.md"
    broken.parent.mkdir()
    broken.write_text("---\nnot: [closed\n", encoding="utf-8")
    result = module.apply(root)
    assert "30-projects/broken/index.md" in result["unparsed"]
    assert broken.read_text(encoding="utf-8") == "---\nnot: [closed\n"


def test_run_through_the_framework_bumps_to_3(tmp_path):
    root = vault_with_v1_index(tmp_path)   # structure-version 2, so only 002 is pending
    result = migrate.run(root, "2026-06-15", stamp="2026-06-15-120000")
    assert (root / "structure-version").read_text(encoding="utf-8").strip() == "3"
    assert [a["slug"] for a in result["applied"]] == ["structure-version-3"]
    assert result["applied"][0]["target_version"] == 3
    assert result["applied"][0]["apply"]["reshaped"] == ["meridian-yard-automation-program"]
    assert result["structure_version"] == 3
```

`migrate.discover()` returns `[{"number", "slug", "path", "module"}]` sorted by number; `migrate.run()` returns `{"snapshot", "applied": [{"number", "slug", "target_version", "apply", "verify"}], "structure_version"}` (see `plugin/lib/vaultlib/migrate.py:50-230`). `run` snapshots the vault into `99-workflow-config/snapshots/` first, which `make_vault` already provides a parent for.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_migration_002.py -q`
Expected: FAIL (`FileNotFoundError` on the module path).

- [ ] **Step 3: Write the migration**

```python
# plugin/migrations/002-structure-version-3/migrate.py
"""Structure-version 3: project index v2 (readability).

Reshapes each `30-projects/*/index.md` that still carries the v1 sections
(`## Decisions`, `## Open Items`, `## Related Meetings`) into the v2 body:
a `Where it stands` card, a `Coming up` table, `Recent meetings` and
`Recent decisions` Dataview blocks capped at 10 rows, and a folded
`Background` (Owe by owner, Awaiting, Open questions, Pending, Watch list,
Context). Text is moved and re-bulleted, never dropped: the `·`/`;`-joined
mega-lines become one bullet per item. The next evening run then rewrites
the prose through `project state write`, which is where it gets short.

Touches no template-managed file. Frontmatter is untouched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, projectstate, vault  # noqa: E402

TARGET_VERSION = 3
LOSSY = None

V1_SECTIONS = ("Decisions", "Open Items", "Related Meetings")
V2_SECTIONS = ("Coming up", "Recent meetings", "Recent decisions", "Background")
_PLACEHOLDERS = {"_none yet_", "_none scheduled_", "none yet", ""}
_CALLOUT_BULLET_RE = re.compile(r"\A>\s*-\s*\*\*(.+?)\*\*\s*[—:-]\s*(.*)\Z")
_OPEN_ITEM_RE = re.compile(r"\A-\s*\*\*(?:[^\w\s]+\s*)?(Owe|Awaiting|Question|Pending)\*\*\s*[—:-]\s*(.*)\Z")
_OWNER_RE = re.compile(r"\A(?:📤\s*)?([A-Z][\w'’.\- ]{1,40}?)\s*:\s+(.*)\Z")
_LEGACY_CALLOUT_RE = re.compile(r"\A>\s*\[!\w+\][+-]?\s*\*\*(Now|Context)\*\*")


def _split_items(text: str) -> List[str]:
    """One bullet per item: split on ` · ` first, then on `; `."""
    items: List[str] = []
    for chunk in re.split(r"\s·\s", text):
        for piece in re.split(r";\s+", chunk):
            piece = piece.strip().rstrip(";").strip()
            if piece and piece not in _PLACEHOLDERS:
                items.append(piece)
    return items


def _collect_owe(text: str, groups: Dict[str, List[str]]) -> None:
    """Fold a v1 Owe line into `groups` (owner -> tasks), insertion-ordered.

    ` · ` separates owner chunks; `; ` separates tasks. A task that itself
    opens with `Name:` starts a new owner (Open Items wrote
    `Priya: a; Jamie: b`); one that does not inherits the chunk's owner
    (the Now callout wrote `📤 Priya: a; b · 📤 Leo: c`). A task with no
    owner anywhere lands under "Unassigned". A task phrased `Anthropic:
    push harder` reads as owner "Anthropic" — acceptable for a reshape the
    next evening run rewrites.
    """
    for chunk in re.split(r"\s·\s", text or ""):
        owner = "Unassigned"
        for piece in re.split(r";\s+", chunk):
            piece = piece.strip().rstrip(";").strip()
            if not piece or piece in _PLACEHOLDERS:
                continue
            match = _OWNER_RE.match(piece)
            if match:
                owner, piece = match.group(1).strip(), match.group(2).strip()
                if not piece:
                    continue
            groups.setdefault(owner, [])
            if piece not in groups[owner]:
                groups[owner].append(piece)


def _callout_bullets(preamble: str, title: str) -> Dict[str, str]:
    """`label -> text` for the bullets of the `**title**` callout in the preamble."""
    out: Dict[str, str] = {}
    inside = False
    for line in preamble.split("\n"):
        header = _LEGACY_CALLOUT_RE.match(line)
        if header:
            inside = header.group(1) == title
            continue
        if not line.startswith(">"):
            inside = False
            continue
        if inside:
            bullet = _CALLOUT_BULLET_RE.match(line.strip())
            if bullet:
                out[bullet.group(1).strip()] = bullet.group(2).strip()
    return out


def parse_v1_body(body: str) -> dict:
    sections = markdown.split_sections(body, level=2)
    preamble = sections[0][1]
    now = _callout_bullets(preamble, "Now")
    context = _callout_bullets(preamble, "Context")
    open_items: Dict[str, str] = {}
    for title, content in sections[1:]:
        if title == "Open Items":
            for line in content.split("\n"):
                match = _OPEN_ITEM_RE.match(line.strip())
                if match:
                    open_items[match.group(1)] = match.group(2).strip()
    stage = now.get("Stage", "").strip()
    decision = now.get("Defining decision", "").strip()
    owe_groups: Dict[str, List[str]] = {}
    _collect_owe(now.get("Owe", ""), owe_groups)
    _collect_owe(open_items.get("Owe", ""), owe_groups)
    return {
        "stage": stage if stage not in _PLACEHOLDERS else None,
        "defining_decision": decision if decision not in _PLACEHOLDERS else None,
        "coming_up": [{"when": "", "what": item} for item in _split_items(now.get("Next event", ""))],
        "owe": [{"owner": owner, "items": tasks} for owner, tasks in owe_groups.items()],
        "awaiting": _split_items(open_items.get("Awaiting", "")),
        "questions": _split_items(open_items.get("Question", "")),
        "pending": _split_items(open_items.get("Pending", "")),
        "watch": _split_items(now.get("Watch", "")),
        "context": {
            "contacts": (context.get("Contacts") or "").strip() or None,
            "source": (context.get("Source") or "").strip() or None,
        },
    }


def _is_v1(body: str) -> bool:
    titles = {title for title, _ in markdown.split_sections(body, level=2)}
    return bool(titles & set(V1_SECTIONS)) and not ({"Background"} <= titles)


def _reshape(path: Path, root: Path) -> None:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    frontmatter, body = markdown.split_frontmatter(text)
    head = text[:len(text) - len(body)]
    slug = path.parent.name
    name = str(frontmatter.get("project-name") or slug)
    as_of = str(frontmatter.get("last-updated") or frontmatter.get("created") or "1970-01-01")[:10]
    if not vault.ISO_DATE_RE.match(as_of):
        as_of = "1970-01-01"
    state = parse_v1_body(body)
    state["as_of"] = as_of
    for row in state["coming_up"]:
        row["when"] = row["when"] or "—"
    _, tail = projectstate.split_notes_tail(body)
    state["notes_tail"] = tail
    vault.atomic_write(path, head + projectstate.render_body(name, slug, state))


def apply(root: Path) -> dict:
    reshaped: List[str] = []
    skipped: List[str] = []
    unparsed: List[str] = []
    projects = root / vault.PROJECTS_DIR
    for path in sorted(projects.glob("*/index.md")) if projects.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            _, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            unparsed.append(rel)
            continue
        if not _is_v1(body):
            skipped.append(path.parent.name)
            continue
        try:
            _reshape(path, root)
        except (ValueError, KeyError) as exc:
            unparsed.append(f"{rel}: {exc}")
            continue
        reshaped.append(path.parent.name)
    return {"reshaped": reshaped, "skipped": skipped, "unparsed": unparsed}


def verify(root: Path) -> dict:
    checked = 0
    projects = root / vault.PROJECTS_DIR
    for path in sorted(projects.glob("*/index.md")) if projects.is_dir() else []:
        try:
            _, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue   # apply already reported it as unparsed; not this step's failure
        titles = [title for title, _ in markdown.split_sections(body, level=2)]
        stale = [t for t in titles if t in V1_SECTIONS]
        if stale:
            raise RuntimeError(
                f"{path.relative_to(root).as_posix()} still carries v1 section(s) {stale}")
        missing = [t for t in V2_SECTIONS if t not in titles]
        if missing:
            raise RuntimeError(
                f"{path.relative_to(root).as_posix()} lacks v2 section(s) {missing}")
        checked += 1
    return {"checked": checked}
```

The `Now` bullet regex accepts `—`, `:` or `-` as the separator because hand-edited vaults vary. The `Owe` item test expects the Now-callout items *before* the Open Items ones for the same owner, which `_collect_owe` preserves by insertion order (the Now line is folded in first).

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest scripts/tests/test_migration_002.py scripts/tests/test_vaultlib_migrate.py scripts/tests/test_migration_001.py -q`
Expected: PASS. If `test_vaultlib_migrate.py` has a test asserting "exactly one migration is discovered", update its expectation to two and keep the chain assertion (`[2, 3]`).

- [ ] **Step 5: Commit**

```bash
git add plugin/migrations/002-structure-version-3/migrate.py scripts/tests/test_migration_002.py scripts/tests/test_vaultlib_migrate.py
git commit -m "feat(migrations): 002 — reshape project indexes to the v2 sections (structure-version 3)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Ontology, schema, fixtures, CSS snippet

**Files:**
- Modify: `plugin/template/99-workflow-config/reference/ontology.md` (project block lines ~153-166; daily-note section ~400-445)
- Regenerate: `plugin/lib/vaultlib/schema.json` via `python3 scripts/compile_ontology.py`
- Rewrite: `fixtures/demo-vault/30-projects/*/index.md` (5 files) by running migration 002 over the fixture tree
- Modify: `plugin/template/.obsidian/snippets/sb-accelerator.css`
- Modify: `plugin/template/structure-version` → `3`; `scripts/make_test_vault.py` / `validate_template.py` if either pins the number (grep `structure-version`)

- [ ] **Step 1: Update the ontology project block**

Replace `body_sections: [Decisions, Open Items, Related Meetings]` with `body_sections: [Coming up, Recent meetings, Recent decisions, Background]` and add under the bullets:

```markdown
- **Body is machine-rendered** by `project state write` from a state object:
  a `> [!summary] Where it stands — {d Month}` card (Stage · up to three
  Hot potatoes 🔴/🟠 · up to two Insights · Defining decision), `## Coming up`
  (a When/What table, ≤ 10 rows), `## Recent meetings` and
  `## Recent decisions` (Dataview, `LIMIT 10`), and `## Background` — folded
  callouts for 📤 Owe (grouped by owner, one item per bullet), 👤 Awaiting,
  ❓ Open questions, ⏳ Pending, Watch list and Context. A trailing
  `## Notes` section, if the owner adds one, is the single human area and
  is preserved verbatim.
```

- [ ] **Step 2: Update the ontology daily-note section**

After the existing marker bullets, add:

```markdown
- **Recap v2 is rendered from fields**: `[!glance]` (first line computed by
  the CLI: meeting count, window, theme and decision counts; then 1–4
  labelled headlines and the entities touched), folded `[!theme]-` callouts
  (≤ 4, headline ≤ 12 words, body ≤ 80), a Project pulse table with a
  🔴/🟠/🟢/⚪ signal per project, Decisions logged as `[[stem|summary]]`,
  `[!hot] Watch` (content risks only), folded `[!quote]- Carried forward`
  and folded `[!sync]- Sync notes` (mechanics: duplicates, fetch errors,
  refusals, SELF-CHECK lines). A `[!warning] Catch-up note` callout is the
  CLI's; one supplied in a payload is stripped.
- **Meeting blocks v2**: `### {HH:MM} — {Subject}[ · [[40-entities/{slug}/dossier|{Entity name}]]]`,
  then `#### Prep` holding the prep region (three lines: **Attendees**,
  **Last meeting**, **Context**), then `#### Notes` (`- `) and `#### Actions`
  (`- [ ] `). Notes and Actions are written once at creation and never
  regenerated; the harvest returns them separately, actions with done state.
- **Identity links are path links.** Entities and projects are folders, and
  Obsidian resolves `[[name]]` by file name only, so writers emit
  `[[40-entities/{slug}/dossier|{Name}]]` / `[[30-projects/{slug}/index|{Name}]]`;
  the CLI normalises a bare `[[slug]]` to that form.
```

- [ ] **Step 3: Regenerate the schema and check**

Run: `python3 scripts/compile_ontology.py && git diff --stat plugin/lib/vaultlib/schema.json`
Expected: the project `body_sections` array shows the four new titles.

- [ ] **Step 4: Rewrite the demo fixtures through migration 002**

```bash
python3 - <<'EOF'
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("m002", "plugin/migrations/002-structure-version-3/migrate.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = pathlib.Path("fixtures/demo-vault")
print(m.apply(root)); print(m.verify(root))
EOF
```

Expected: `reshaped` lists all five fixture slugs, `unparsed` is empty. Open one rewritten index (`fixtures/demo-vault/30-projects/meridian-yard-automation-program/index.md`) and check the Coming up row reads `| — | Vendor contract signature, target 2026-09-01 |`; hand-edit the fixture rows' `when` cells to a readable form (`Tue 1 Sept`) — fixtures are demo content, and the migration cannot invent a weekday. If the fixture has a `structure-version` file, set it to `3`.

- [ ] **Step 5: CSS snippet**

Append to `plugin/template/.obsidian/snippets/sb-accelerator.css`:

```css
/* Daily-note recap v2 callout types. Obsidian's documented mechanism:
   --callout-color (r, g, b) and --callout-icon (a Lucide icon id). An
   unknown type falls back to the default "note" look, so a vault whose
   snippet is behind still renders — just without the accents. */
.callout[data-callout="glance"] { --callout-color: 14, 165, 233; --callout-icon: lucide-eye; }
.callout[data-callout="theme"]  { --callout-color: 168, 85, 247; --callout-icon: lucide-git-merge; }
.callout[data-callout="hot"]    { --callout-color: 239, 68, 68;  --callout-icon: lucide-flame; }
.callout[data-callout="sync"]   { --callout-color: 148, 163, 184; --callout-icon: lucide-wrench; opacity: 0.85; }
```

- [ ] **Step 6: Template structure-version and validators**

Run: `grep -rn "structure-version\|structure_version" plugin/template/structure-version scripts/validate_template.py scripts/make_test_vault.py plugin/lib/vaultlib/template.py scripts/tests/test_validate_template.py | head`
Set `plugin/template/structure-version` to `3` and update any validator/test that pins `2` as the shipped value (the template must match the newest migration's `TARGET_VERSION`, otherwise a fresh vault would be offered migration 002 on its first `/upgrade-vault`).

- [ ] **Step 7: Run the three CI checks**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: all green — in particular `test_fixtures_ontology.py::test_body_sections_present_in_every_fixture[project]`, `test_dataview_refs.py`, `test_compile_ontology.py`, `test_vaultlib_updatequeue.py` (its synthetic index still uses v1 headings; nothing there asserts on them — if something does, switch the strings to the v2 titles).

- [ ] **Step 8: Commit**

```bash
git add plugin/template fixtures/demo-vault plugin/lib/vaultlib/schema.json
git commit -m "feat(template): project body_sections v2, daily-note v2 ontology, recap callout styles; fixtures reshaped

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Skills and prose — evening-sync, new-project, plugin/CLAUDE.md, Start here, local-setup

**Files:**
- Modify: `plugin/skills/evening-sync/SKILL.md` (stages 2, 4, 5, 6; payload example; Rules)
- Modify: `plugin/skills/new-project/SKILL.md:100-104, 185-190`
- Modify: `plugin/CLAUDE.md` (section "Daily-note regions")
- Modify: `plugin/template/Start here.md:16`
- Modify: `docs/local-setup.md:170`
- Modify: `plugin/lib/vaultlib/entity.py:55` (comment only)
- Test: `scripts/tests/test_skill_contracts.py` (append)

- [ ] **Step 1: Write the failing contract tests**

```python
def _heredoc_json(text: str, filename: str) -> dict:
    """The JSON body of `cat > "$SCRATCH/<filename>" <<'JSON' … JSON`."""
    start = text.index(filename)
    open_tag = text.index("<<'JSON'\n", start) + len("<<'JSON'\n")
    close_tag = text.index("\nJSON\n", open_tag)
    return json.loads(text[open_tag:close_tag])


def test_evening_sync_payload_example_is_the_v2_contract():
    text = (SKILLS / "evening-sync" / "SKILL.md").read_text(encoding="utf-8")
    payload = _heredoc_json(text, "daily-note.payload.json")
    assert isinstance(payload["recap"], dict), "recap must be the structured v2 object"
    assert {"glance", "themes", "pulse", "decisions", "watch", "carried_forward", "sync_notes"} <= set(payload["recap"])
    assert "meetings" not in payload["recap"]["glance"], "the glance's first line is computed by the CLI"
    assert set(payload["meetings"][0]["prep"]) == {"attendees", "last_meeting", "context"}
    assert "recap_window" in payload


def test_evening_sync_project_state_example_matches_the_cli():
    text = (SKILLS / "evening-sync" / "SKILL.md").read_text(encoding="utf-8")
    state = _heredoc_json(text, "project-state")
    assert {"as_of", "stage", "hot_potatoes", "coming_up", "owe"} <= set(state)
    assert "project state write" in text
    assert "Rewrite the `> [!summary]+ **Now**` callout" not in text


def test_evening_sync_routes_mechanics_to_sync_notes():
    text = (SKILLS / "evening-sync" / "SKILL.md").read_text(encoding="utf-8")
    assert "sync_notes" in text
    assert "Watch is content only" in text or "**Watch** is content only" in text
```

Use the module's existing `SKILLS` constant (or whatever name the file uses for the skills directory) and add `import json` if missing.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py -q -k "evening_sync_payload or project_state_example or sync_notes"`
Expected: FAIL.

- [ ] **Step 3: Rewrite `evening-sync/SKILL.md` stage 2**

Replace the harvest paragraph with:

```markdown
`exists: false` is a normal first-run state — note it and move on. Otherwise
collect, per meeting, `notes` (the owner's bullets under `#### Notes`, or
bullets directly under the heading on a note written before v2) and
`actions` (`{text, done}` from the `- [ ]` / `- [x]` list under
`#### Actions`), plus the `end_of_day` bullets. All of it is context for the
recap (stage 6) and decision candidates (stage 4); an action is a jotting
the owner marked as a task, nothing routes it anywhere yet. The note itself
is the archive of the day — **never modify it**.
```

- [ ] **Step 4: Rewrite stage 4's subagent instructions (items 2–3)**

Replace items 2 and 3 with:

````markdown
2. Compose the project's **state** as JSON and write it to
   `$SCRATCH/project-state-<slug>.json`. The CLI renders the whole index body
   from it and refuses anything over its caps, naming the field:

```bash
cat > "$SCRATCH/project-state-<slug>.json" <<'JSON'
{
  "as_of": "<today>",
  "stage": "one or two sentences, ≤ 60 words",
  "hot_potatoes": [{"signal": "red", "text": "≤ 30 words — needs the owner's hand this week"},
                   {"signal": "amber", "text": "≤ 30 words — a risk building, nothing to do yet"}],
  "insights": ["≤ 30 words, at most two"],
  "defining_decision": "<decision stem under this project, or null>",
  "coming_up": [{"when": "Wed 16 Sept", "what": "≤ 40 words", "date": "2026-09-16"}],
  "owe": [{"owner": "Full Name", "items": ["one task per item — never chain with ';'"]}],
  "awaiting": ["…"], "questions": ["…"], "pending": ["…"], "watch": ["…"],
  "context": {"contacts": "…", "source": "…"},
  "next_milestone": {"text": "one line", "date": "<ISO>"}
}
JSON
python3 "$VAULTLIB" project state write --vault "$VAULT" --slug <slug> \
  --state "$SCRATCH/project-state-<slug>.json" --today <today>
```

   Start from the index as it stands (read it: the current card, Coming up,
   and every Background list are your prior state) and fold the new meetings
   in — carry items that are still open, drop the ones the meetings closed,
   never invent. `hot_potatoes` are the ≤ 3 things the owner must act on or
   watch this week; `insights` are patterns, not events. `coming_up` holds
   dated events only, ≤ 10 rows, the `date` sorts them. Omit
   `next_milestone` when no concrete next event exists. Identity names
   (entities, projects, people) go in as `[[slug]]` wikilinks — the CLI
   rewrites them to links that open. A refusal names the field and the cap;
   fix that field and retry once. `state write` also stamps `last-updated`
   and `state-updated`, so do **not** call `project touch` separately.
3. Never edit `index.md` with your editor — the body is machine-rendered and
   a hand edit is overwritten on the next run; the owner's own `## Notes`
   section at the bottom, if present, is the one thing the CLI preserves.
````

Renumber the following items. Update the summary line in item 5 to `{"slug", "stateWritten": bool, …}`.

- [ ] **Step 5: Rewrite stage 5's prep sentence**

Replace "For each event, build one prep line — **Attendees:** names · **Last meeting:** date + one-liner · **Context:** one line from the entity dossier and the project's Now callout." with:

```markdown
For each event, build the prep as **three fields**: `attendees` (names,
organizer first), `last_meeting` (a wikilink to the most recent note for
this entity or project with a one-line what-happened, or `none on file`),
and `context` (one line from the entity dossier and the project's *Where it
stands* card, or, with no confident match, one line from the event alone and
`No tracked project.`). Each field is one line; the CLI renders them under
`#### Prep` and adds empty `#### Notes` and `#### Actions` lists for the
owner.
```

- [ ] **Step 6: Rewrite stage 6's shape and payload**

Replace the "**A flat list of meetings is not a recap.** Required shape…" list and the payload heredoc with:

````markdown
**A flat list of meetings is not a recap.** The CLI renders the recap from
fields; you supply the judgment. Caps are enforced by field, and a refusal
names the field, so one retry always suffices.

- `glance.headlines` — 1–4 items, each `{label, text ≤ 20 words}` with
  `label` one of `Needs your hand` · `Moved` · `New` · `Decided` · `Quiet`.
  `glance.entities` — the entity slugs touched. The first line (meeting
  count, window, theme and decision counts) is computed by the CLI; never
  write it.
- `themes` — 0–4 patterns *across* meetings: `headline` ≤ 12 words, `body`
  ≤ 80 words, `sources` as `{stem, label}` meeting or daily-note stems. With
  one meeting, say what it means, not that it happened.
- `pulse` — one row per project touched: `project` slug, `signal`, `text`
  ≤ 40 words on where it stands and what moved. Signals: **red** = needs the
  owner's hand this week · **amber** = a risk building, nothing to do yet ·
  **green** = moved forward · **quiet** = no activity in the window.
- `decisions` — the stems stage 4 wrote; the CLI renders each with its
  summary and project.
- `watch` — **content risks only**, one line each (≤ 40 words). **Watch is
  content only**: every conflict, unresolved duplicate, fetch error, refusal,
  out-of-reach transcript and `SELF-CHECK` line goes in `sync_notes`, which
  renders folded, and never in `watch`.
- `carried_forward` — jottings worth carrying, one line each.
- `sync_notes` — the mechanics, one line each; also in the run summary.

The catch-up banner is the CLI's: `dates plan`'s `is_catchup` becomes the
callout on write, and a banner you put in a payload is stripped with a
warning.

```bash
cat > "$SCRATCH/daily-note.payload.json" <<'JSON'
{
  "date": "<next_business_day>",
  "recap_window": {"from": "<recap_from>", "to": "<recap_to>",
                   "detailed_from": "<recap_detail_from, only when capped>"},
  "recap": {
    "glance": {
      "entities": ["<entity-slug>"],
      "headlines": [{"label": "Needs your hand", "text": "<≤ 20 words>"},
                    {"label": "Moved", "text": "<≤ 20 words>"}]
    },
    "themes": [{"headline": "<≤ 12 words>", "body": "<≤ 80 words>",
                "sources": [{"stem": "<meeting-stem>", "label": "<short label>"}]}],
    "pulse": [{"project": "<project-slug>", "signal": "green", "text": "<≤ 40 words>"}],
    "decisions": ["<decision-stem>"],
    "watch": ["<content risk, one line>"],
    "carried_forward": ["<jotting worth carrying>"],
    "sync_notes": ["<mechanical item, one line>"]
  },
  "meetings": [
    {"time": "09:00", "subject": "Weekly Status", "entity": "<entity-slug>",
     "prep": {"attendees": "<names>",
              "last_meeting": "[[<meeting-stem>|<date — one-liner>]]",
              "context": "[[<project-slug>]] · <one line>"}}
  ]
}
JSON
python3 "$VAULTLIB" daily-note write --vault "$VAULT" --note "$SCRATCH/daily-note.payload.json"
```
````

Keep the paragraphs that follow (region merge, `structure changed`, refused links, `recap_window` idempotence) — they are unchanged in meaning. In the "Every entity, person and project you name is a wikilink" paragraph, add one sentence: "Write them as `[[slug]]`; the CLI rewrites identity links to the path form that opens the object in Obsidian." Rule 11 gains the same sentence.

- [ ] **Step 7: The smaller prose edits**

- `new-project/SKILL.md`: line ~102 "`--stage` … one line for the Now callout" → "one line for the *Where it stands* card"; in Rules, "`index.md` is the queryable object" gains "its body is machine-rendered by `project state write`; the owner's own notes go under a trailing `## Notes` heading."
- `plugin/CLAUDE.md`, section "Daily-note regions": add a paragraph:

  ```markdown
  Two payload forms are accepted. **v1** — `recap` and every `prep` are
  Markdown strings — renders byte-identically to earlier versions (pinned by
  test). **v2** — `recap` is an object (`recap.validate`/`render`) and every
  `prep` is `{attendees, last_meeting, context}` — renders the recap as
  callouts and a pulse table, and each meeting as `### heading` → `#### Prep`
  (region) → `#### Notes` → `#### Actions`. Mixing prep forms in one payload
  is refused. A v2 payload merges into a v1 note (regions only; the
  sub-headings are never retro-fitted), and headings are compared as
  `(time, subject, entity)` so the v1 `· [[slug]]` and v2 `· [[path|Name]]`
  forms match. A v1 recap that opens with a `Catch-up note` callout has it
  stripped with a warning — the CLI writes the banner. `daily-note read`
  returns `notes[]` and `actions[] = {text, done}` per meeting; `jottings[]`
  is their union for older callers.
  ```

  And a new sub-section "Project index body is CLI-rendered" stating that `project state write` replaces everything between the H1 and the end of `## Background`, preserves a trailing `## Notes`, and calls `project touch` itself.
- `plugin/template/Start here.md:16`: "Each note has three parts. **Recap** is written for you. **Meetings** is one heading per meeting, with **Prep** written for you and **Notes** and **Actions** left for you — tick an action when it is done. **End of day** is yours. …"
- `docs/local-setup.md:170`: "the three H2 sections" → "the four H2 sections".
- `plugin/lib/vaultlib/entity.py:55` comment: "opens with `> [!summary]+ **Now**`" → "opens with `> [!summary] Where it stands`".

- [ ] **Step 8: Run the contract tests and the full suite**

Run: `python3 -m pytest scripts/tests/test_skill_contracts.py scripts/tests/test_template_prose.py -q && python3 scripts/lint_plugin.py`
Expected: PASS. `test_every_cli_invocation_named_by_a_skill_exists` must recognise `project state write` — if it tokenises `<group> <action>`, extend its allow-list the way it handles other two-word actions.

- [ ] **Step 9: Commit**

```bash
git add plugin/skills plugin/CLAUDE.md plugin/template/Start\ here.md docs/local-setup.md plugin/lib/vaultlib/entity.py scripts/tests/test_skill_contracts.py
git commit -m "docs(skills): evening-sync speaks the v2 payloads; project state via CLI; prose updates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Version, changelog, visual verification

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json` → `"version": "0.11.0"`; `.claude-plugin/marketplace.json` if it carries the plugin version (`grep -n '"version"' .claude-plugin/marketplace.json`)
- Modify: `CHANGELOG.md` under `## Unreleased`
- Run: the visual tier

- [ ] **Step 1: Bump and log**

```bash
python3 - <<'EOF'
import json, pathlib, re
p = pathlib.Path("plugin/.claude-plugin/plugin.json"); d = json.loads(p.read_text()); d["version"] = "0.11.0"
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
m = pathlib.Path(".claude-plugin/marketplace.json")
if m.exists() and '"version"' in m.read_text():
    m.write_text(re.sub(r'"version":\s*"0\.10\.\d+"', '"version": "0.11.0"', m.read_text()))
EOF
```

CHANGELOG line under `## Unreleased` (fill the PR number after opening the PR):

```markdown
- **The daily note and project pages are rewritten for reading, not just for the model.** The recap opens with an at-a-glance card, themes fold behind a headline, the project pulse is a table with a 🔴🟠🟢⚪ signal, Watch holds only real risks and the sync mechanics fold away; each meeting now has a **Prep** block plus **Notes** and **Actions** lists for you. Project pages lead with a five-bullet *Where it stands* card, a dated *Coming up* table and the last ten meetings and decisions, with everything else folded under *Background*. Links to projects and organisations now open the right page. Run `/upgrade-vault` to reshape existing project pages (structure-version 3). (#PR)
```

- [ ] **Step 2: Full CI trio**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q`
Expected: green.

- [ ] **Step 3: Visual tier — fresh vault, tour, assertions**

```bash
python3 scripts/make_test_vault.py test-vaults/$(date +%F)-readability --with-plugins
python3 scripts/obsidian_probe.py doctor
python3 scripts/obsidian_probe.py up --vault test-vaults/$(date +%F)-readability
python3 scripts/obsidian_probe.py tour --out .obsidian-probe-out
python3 -m pytest scripts/tests -q -m obsidian
```

If `up` prints `fresh probe profile`, the "trust author and enable plugins" dialog is up in the cloaked window; accept it once with:

```bash
python3 - <<'EOF'
import sys, time; sys.path.insert(0, "scripts"); import obsidian_probe as P
kw = {"home": P.derive_probe_home()}
print(P.eval_js("(()=>{const b=[...document.querySelectorAll('.modal button')].find(b=>b.innerText.includes('Trust author'));if(b){b.click();return 'clicked'}return 'no-modal'})()", **kw))
EOF
```

then re-run `tour`. Read every PNG in `.obsidian-probe-out/`.

- [ ] **Step 4: Visual tier — a v2 daily note and a migrated index**

Write a v2 note into the test vault with the fixture cast (the fixture project slugs are `meridian-yard-automation-program` and `commercial-ops-crm-modernization`; entities `meridian-freight-holdings`, `commercial-operations`; a decision stem exists under `fixtures/demo-vault/30-projects/meridian-yard-automation-program/decisions/` — pick one with `ls`), then screenshot Reading view and Live Preview of the note and of `30-projects/meridian-yard-automation-program/index.md`:

```bash
V=test-vaults/$(date +%F)-readability
cat > /tmp/v2.json <<'JSON'
{"date": "2026-06-16",
 "recap_window": {"from": "2026-06-15", "to": "2026-06-15"},
 "recap": {"glance": {"entities": ["meridian-freight-holdings", "commercial-operations"],
                      "headlines": [{"label": "Needs your hand", "text": "Yard 2 commissioning schedule still owed to Leo"},
                                    {"label": "Moved", "text": "RFP scoring dry run completed"}]},
           "themes": [{"headline": "Two programmes wait on one schedule", "body": "Both the yard re-scope and the CRM scoring depend on dates nobody has committed. The pattern repeats from last week.", "sources": []}],
           "pulse": [{"project": "meridian-yard-automation-program", "signal": "red", "text": "Schedule for yards 2–3 still owed; Renee not yet aligned."},
                     {"project": "commercial-ops-crm-modernization", "signal": "green", "text": "Scoring dry run done; vendor selection on track for 30 August."}],
           "decisions": [], "watch": ["No owner for the yard-3 PLC question."],
           "carried_forward": ["Dana on rollout scope."], "sync_notes": ["One duplicate recorder capture flagged."]},
 "meetings": [{"time": "09:00", "subject": "Monday Forecast Call", "entity": "commercial-operations",
               "prep": {"attendees": "Sam Okafor, Taylor Brooks", "last_meeting": "none on file", "context": "[[commercial-ops-crm-modernization]] · scoring criteria due Friday"}}]}
JSON
python3 plugin/lib/vaultlib/cli.py daily-note write --vault "$V" --note /tmp/v2.json
python3 - "$V" <<'EOF'
import sys, time; sys.path.insert(0, "scripts"); import obsidian_probe as P
from pathlib import Path
kw = {"home": P.derive_probe_home()}; P.guard(**kw); P.cloak_window(**kw); P.set_window_size(1440, 900, **kw)
out = Path(".obsidian-probe-out/readability"); out.mkdir(parents=True, exist_ok=True)
for key, rel in {"daily-v2": "60-daily-notes/2026-06-16.md",
                 "project-v2": "30-projects/meridian-yard-automation-program/index.md"}.items():
    for mode in ("preview", "source"):
        P.cli(["open", f"path={rel}"], **kw); time.sleep(1.2)
        P.eval_js(f"app.workspace.rightSplit.collapse(); app.workspace.activeLeaf.view.setState({{mode:'{mode}'}},{{}}); 'ok'", **kw); time.sleep(1.5)
        P.capture_png(out / f"{key}-{mode}.png", **kw)
    print(key, P.eval_js("JSON.stringify({callouts:[...document.querySelectorAll('.workspace-leaf.mod-active .callout')].map(c=>c.dataset.callout), unresolved:[...document.querySelectorAll('.workspace-leaf.mod-active a.internal-link.is-unresolved')].map(a=>a.innerText), dv:document.querySelectorAll('.workspace-leaf.mod-active .block-language-dataview table').length})", **kw))
python3 scripts/obsidian_probe.py down
EOF
```

Expected in the printed JSON: `callouts` includes `glance`, `theme`, `hot`, `sync` for the note and `summary`, `todo`, `info`, `question`, `note`, `warning` for the index; `unresolved` is `[]` on both; `dv` is `2` on the index. Read the four PNGs and confirm: callout icons render (eye, git-merge, flame, wrench), the pulse table has two rows with coloured dots, `#### Prep` / `#### Notes` / `#### Actions` show as sub-headings with a checkbox under Actions, the Live Preview shows the same shape, the index's `Where it stands` card lists Stage and Defining decision and the two Dataview tables render with `Mon 15-06`-style dates. Attach the four PNGs to the PR description.

- [ ] **Step 5: Commit and open the PR**

```bash
git add plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json CHANGELOG.md
git commit -m "chore: release-file trio for 0.11.0 — readability contract

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push -u origin claude/vault-content-readability-0ea97c
gh pr create --title "feat: daily note v2 and project index v2 — readable by humans (0.11.0)" --body-file - <<'EOF'
Implements docs/superpowers/specs/2026-09-15-vault-readability-design.md.

- daily-note write v2: structured recap (glance / folded themes / pulse table / decisions / hot Watch / folded carried-forward and sync notes), prep as three fields under `#### Prep`, `#### Notes` and `#### Actions` for the owner; v1 payloads render byte-identically; a model-written catch-up banner is stripped.
- links.py: identity links normalised to `[[path|Display Name]]` so they open in Obsidian.
- project state write: index body rendered from JSON with caps; scaffold uses the same renderer.
- migration 002 → structure-version 3 reshapes existing indexes; fixtures reshaped through it.
- ontology/schema, CSS callout types, skills and prose updated.

Visual tier: probe tour green; screenshots attached (daily v2 + project v2, Reading and Live Preview).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

Then edit the CHANGELOG line's `(#PR)` to the real number, amend, push.

---

## Post-merge checklist (DryRunVault, Michael's machine — not a plan task)

1. `/upgrade-vault` on DryRunVault: migration 002 applies, template refresh carries the snippet and `Start here.md`.
2. Delete the three stray root notes (`bta-leadership.md`, `delaware-imagine-more.md`, `deme-supply-chain-transformation.md`), the `80-thoughts-ideas/readability-proposals/` folder and `.obsidian/snippets/sb-readability-proposals.css`; remove it from `appearance.json`'s `enabledCssSnippets`.
3. Run `/evening-sync` interactively once; read tomorrow's note and the Imagine More index in Obsidian.
4. Bump the dryrun `plugin_version` in `registry.yaml` (its own chore PR, as usual).
