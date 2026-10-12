# Facts about people ("What I know") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Person pages get a `## What I know` section that the evening run (and on-demand runs) fills with dated, sourced facts the person said about themselves, append-only.

**Architecture:** A new CLI writer (`person write --automatic`, `person touch`) in `vaultlib/person.py`; `update-queue` gains a person queue grouped by material (`peopleNeedingUpdate`, `peopleWork`); a new section E in the shared processing part dispatches one subagent per meeting/day log; migration 014 merges `## Notes from <entity>` into `## What I know` and stamps the no-look-back start point.

**Tech Stack:** Python 3 stdlib (`plugin/lib/vaultlib`), pytest (`scripts/tests`), Markdown skills (`plugin/skills`).

**Spec:** `docs/superpowers/specs/2026-10-12-person-facts-design.md`

## Global Constraints

- Plugin version 0.13.18 (`plugin/.claude-plugin/plugin.json` and `scripts/tests/test_marketplace_manifest.py`); structure version 15.
- Automatic line format: `- <YYYY-MM-DD> — <fact> (<marker>)`; markers `(meeting · …)`, `(mail · …)`, `(chat · …)`, `(session · …)`, `(note · …)` — the regex is `entity._SOURCE_MARKER_RE`, imported, never copied.
- `## What I know` sits directly after the `# {person-name}` H1 (after the body preamble).
- Append-only: no writer ever edits or removes a line in `## What I know`.
- Privacy rule 1: facts never go into anything that leaves the vault. Rule 2: only what the person said about themselves.
- No look-back: start point is `person-updated`, else `created` at 00:00, else skipped with a warning.
- Session records are not a people-queue source.
- Every vault write goes through `vault.atomic_write` (LF).
- Never say "jot/jotting" in user-facing text; say "entity", not "organisation".
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests: `python -m pytest scripts/tests -q` from the worktree root (conftest puts `plugin/lib` on the path).

## Review Focus

1. A person page whose body has text before the H1, or no H1 at all → section still lands right after the preamble, no text lost. (Task 1 test `test_write_facts_without_h1_goes_after_the_preamble`.)
2. A fact containing a newline (model output) → refused into `skipped`, never splits the page. (Task 1 test `test_write_facts_refuses_a_multiline_fact`.)
3. A `## What I know` section followed by owner sections → appended line lands inside the section, the blank line before the next heading kept. (Task 1 test `test_write_facts_appends_inside_the_section_before_the_next_heading`.)
4. A `## Notes from X` section that holds a dataview fence or owner prose → moved verbatim, nothing dropped. (Task 3 test `test_non_bullet_text_moves_too`.)
5. A person who appears in a meeting from before their `created` date (attendee added later) → not queued. (Task 2 test `test_created_is_the_start_point_without_a_stamp`.)

---

### Task 1: `person write --automatic` and `person touch`

**Files:**
- Modify: `plugin/lib/vaultlib/person.py` (docstring + new functions at end)
- Modify: `plugin/lib/vaultlib/cli.py` (parser near line 175, dispatch near line 1058)
- Test: `scripts/tests/test_vaultlib_person.py` (append)

**Interfaces:**
- Produces: `person.FACTS_HEADING = "What I know"`; `person.write_facts(root: Path, slug: str, facts: list, today: str) -> dict` returning `{"slug", "path", "written": int, "skipped": [str], "duplicates": [str]}`; `person.touch(root: Path, slug: str, *, timestamp: Optional[str]) -> dict` returning `{"slug", "path", "person-updated", "changed"}`; `person.insert_section_after_preamble(body: str, heading: str, lines: List[str]) -> str` (reused by Task 3's migration via a frozen copy, not an import).
- CLI: `person write --vault V --slug S --automatic --facts F|- [--today D]`; `person touch --vault V --slug S [--timestamp T]`.

- [ ] **Step 1: Write the failing tests** (append to `scripts/tests/test_vaultlib_person.py`)

```python
# --- What I know (#273 piece 4) -------------------------------------------

DANA = ('---\nperson-name: "Dana Whitfield"\nslug: dana-whitfield\nrelationship: external\n'
        'created: 2026-03-02\nlast-updated: 2026-03-02\n---\n\n# Dana Whitfield\n\n'
        '## Context\n\n- Owner wrote this.\n')
M = "(meeting · [[08-10-26-weekly]])"


def _dana(tmp_path, text=DANA):
    root = make_vault(tmp_path)
    path = root / "50-people" / "dana-whitfield.md"
    path.write_text(text, encoding="utf-8", newline="")
    return root, path


def test_write_facts_creates_the_section_after_the_h1(tmp_path):
    root, path = _dana(tmp_path)
    result = person.write_facts(root, "dana-whitfield",
                                [{"date": "2026-10-08", "fact": f"Is selling her house. {M}"}],
                                "2026-10-12")
    assert result["written"] == 1 and result["skipped"] == [] and result["duplicates"] == []
    text = path.read_text(encoding="utf-8")
    assert ("# Dana Whitfield\n\n## What I know\n\n"
            f"- 2026-10-08 — Is selling her house. {M}\n\n## Context\n\n- Owner wrote this.\n") in text
    assert "last-updated: 2026-10-12" in text


def test_write_facts_appends_inside_the_section_before_the_next_heading(tmp_path):
    start = DANA.replace("# Dana Whitfield\n\n",
                         "# Dana Whitfield\n\n## What I know\n\n- Mine, undated.\n\n")
    root, path = _dana(tmp_path, start)
    person.write_facts(root, "dana-whitfield",
                       [{"date": "2026-10-08", "fact": f"New fact. {M}"}], "2026-10-12")
    body = md.split_frontmatter(path.read_text(encoding="utf-8"))[1]
    assert ("## What I know\n\n- Mine, undated.\n- 2026-10-08 — New fact. "
            f"{M}\n\n## Context\n\n- Owner wrote this.\n") in body


def test_write_facts_after_owner_prose_leaves_a_blank_line(tmp_path):
    start = DANA.replace("# Dana Whitfield\n\n",
                         "# Dana Whitfield\n\n## What I know\n\nSome prose.\n\n")
    root, path = _dana(tmp_path, start)
    person.write_facts(root, "dana-whitfield",
                       [{"date": "2026-10-08", "fact": f"New fact. {M}"}], "2026-10-12")
    assert f"Some prose.\n\n- 2026-10-08 — New fact. {M}\n" in path.read_text(encoding="utf-8")


def test_write_facts_without_h1_goes_after_the_preamble(tmp_path):
    root, path = _dana(tmp_path, DANA.replace("# Dana Whitfield\n\n", "Intro line.\n\n"))
    person.write_facts(root, "dana-whitfield",
                       [{"date": "2026-10-08", "fact": f"X. {M}"}], "2026-10-12")
    body = md.split_frontmatter(path.read_text(encoding="utf-8"))[1]
    assert body.index("Intro line.") < body.index("## What I know") < body.index("## Context")


def test_write_facts_refuses_a_fact_without_a_marker(tmp_path):
    root, path = _dana(tmp_path)
    before = path.read_bytes()
    result = person.write_facts(root, "dana-whitfield",
                                [{"date": "2026-10-08", "fact": "No source here."}], "2026-10-12")
    assert result["written"] == 0 and len(result["skipped"]) == 1
    assert "source marker" in result["skipped"][0]
    assert path.read_bytes() == before          # nothing written, not even last-updated


@pytest.mark.parametrize("item", [
    {"date": "2026-13-01", "fact": f"Bad date. {M}"},
    {"date": "", "fact": f"No date. {M}"},
    {"date": "2026-10-08", "fact": ""},
    {"date": "2026-10-08"},
    "not an object",
])
def test_write_facts_refuses_malformed_items(tmp_path, item):
    root, _ = _dana(tmp_path)
    result = person.write_facts(root, "dana-whitfield", [item], "2026-10-12")
    assert result["written"] == 0 and len(result["skipped"]) == 1


def test_write_facts_refuses_a_multiline_fact(tmp_path):
    root, path = _dana(tmp_path)
    result = person.write_facts(root, "dana-whitfield",
                                [{"date": "2026-10-08", "fact": f"Line one\n## Boom {M}"}],
                                "2026-10-12")
    assert result["written"] == 0 and "one line" in result["skipped"][0]
    assert "## Boom" not in path.read_text(encoding="utf-8")


def test_write_facts_skips_an_exact_duplicate(tmp_path):
    root, path = _dana(tmp_path)
    item = {"date": "2026-10-08", "fact": f"Is selling her house. {M}"}
    person.write_facts(root, "dana-whitfield", [item], "2026-10-12")
    result = person.write_facts(root, "dana-whitfield", [item, item], "2026-10-12")
    assert result["written"] == 0 and len(result["duplicates"]) == 2
    assert path.read_text(encoding="utf-8").count("Is selling her house.") == 1


def test_write_facts_never_touches_other_sections_or_frontmatter(tmp_path):
    root, path = _dana(tmp_path)
    person.write_facts(root, "dana-whitfield",
                       [{"date": "2026-10-08", "fact": f"X. {M}"}], "2026-10-12")
    after = path.read_text(encoding="utf-8")
    assert after.replace("last-updated: 2026-10-12", "last-updated: 2026-03-02").replace(
        f"## What I know\n\n- 2026-10-08 — X. {M}\n\n", "") == DANA


def test_write_facts_reads_a_crlf_file(tmp_path):
    root, path = _dana(tmp_path, DANA.replace("\n", "\r\n"))
    result = person.write_facts(root, "dana-whitfield",
                                [{"date": "2026-10-08", "fact": f"X. {M}"}], "2026-10-12")
    assert result["written"] == 1
    text = path.read_text(encoding="utf-8")
    assert "\r" not in text and "- Owner wrote this." in text and "## What I know" in text


def test_write_facts_unknown_person_raises(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="no person 'nobody'"):
        person.write_facts(root, "nobody", [{"date": "2026-10-08", "fact": f"X. {M}"}], "2026-10-12")


def test_write_facts_needs_a_list(tmp_path):
    root, _ = _dana(tmp_path)
    with pytest.raises(ValueError, match="list"):
        person.write_facts(root, "dana-whitfield", {"date": "2026-10-08"}, "2026-10-12")


def test_touch_sets_person_updated_and_is_idempotent(tmp_path):
    root, path = _dana(tmp_path)
    first = person.touch(root, "dana-whitfield", timestamp="2026-10-12T21:05")
    assert first["changed"] is True and "person-updated: 2026-10-12T21:05" in path.read_text(encoding="utf-8")
    assert person.touch(root, "dana-whitfield", timestamp="2026-10-12T21:05")["changed"] is False


def test_touch_rejects_a_malformed_timestamp(tmp_path):
    root, _ = _dana(tmp_path)
    with pytest.raises(ValueError, match="YYYY-MM-DDTHH:MM"):
        person.touch(root, "dana-whitfield", timestamp="2026-10-12")


def test_cli_person_write_requires_automatic_and_writes(tmp_path):
    import json, subprocess, sys
    from pathlib import Path
    cli = Path(__file__).resolve().parents[2] / "plugin/lib/vaultlib/cli.py"
    root, path = _dana(tmp_path)
    payload = tmp_path / "facts.json"
    payload.write_text(json.dumps({"facts": [{"date": "2026-10-08", "fact": f"X. {M}"}]}),
                       encoding="utf-8")
    base = [sys.executable, str(cli), "person", "write", "--vault", str(root),
            "--slug", "dana-whitfield", "--facts", str(payload), "--today", "2026-10-12"]
    refused = json.loads(subprocess.run(base, capture_output=True, text=True,
                                        encoding="utf-8").stdout)
    assert refused["ok"] is False and "--automatic" in refused["error"]
    done = json.loads(subprocess.run(base + ["--automatic"], capture_output=True, text=True,
                                     encoding="utf-8").stdout)
    assert done["ok"] is True and done["data"]["written"] == 1
    touched = json.loads(subprocess.run(
        [sys.executable, str(cli), "person", "touch", "--vault", str(root),
         "--slug", "dana-whitfield", "--timestamp", "2026-10-12T21:05"],
        capture_output=True, text=True, encoding="utf-8").stdout)
    assert touched["ok"] is True and touched["data"]["person-updated"] == "2026-10-12T21:05"
```

Before running, check the CLI envelope keys: `grep -n "def _ok\|def _fail" plugin/lib/vaultlib/cli.py` and adapt `["data"]`/`["error"]` to the real envelope shape if it differs.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_person.py -q -k "facts or touch or person_write"`
Expected: FAIL — `AttributeError: module 'vaultlib.person' has no attribute 'write_facts'`.

- [ ] **Step 3: Implement** (append to `plugin/lib/vaultlib/person.py`; update the module docstring)

Docstring first paragraph becomes:

```python
"""Person notes.

Auto-created from a display name. The frontmatter is curated through
People.base. The body holds one machine-written part: `## What I know`
(#273 piece 4), dated facts the person said about themselves, each ending in
its source marker, appended by `write_facts` and never edited or removed by
it. Every other line on the page is the owner's.
"""
```

Add `import datetime` and `from typing import List` to the imports, then:

```python
FACTS_HEADING = "What I know"
_STAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")


def _require_note(root: Path, slug: str) -> Path:
    found = _existing_note(root, slug)
    if found is None:
        raise ValueError(f"no person {slug!r} in {PEOPLE_DIR}/")
    return found


def _is_iso_date(value: str) -> bool:
    if not vault.ISO_DATE_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def insert_section_after_preamble(body: str, heading: str, lines: List[str]) -> str:
    """Append `lines` to `## heading`, creating the section right after the
    body's preamble (the `# Name` H1 and anything before the first `##`)
    when it is missing. Nothing else in the body changes."""
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title == heading:
            kept = content.rstrip("\n")
            last = kept.split("\n")[-1].strip() if kept.strip() else ""
            gap = "\n" if (not last or last.startswith("- ")) else "\n\n"
            if not kept.strip():
                kept, gap = "", "\n"
            sections[i] = (title, kept + gap + "\n".join(lines) + "\n")
            return markdown.render_sections(sections)
    preamble = sections[0][1]
    if not preamble.endswith("\n"):
        preamble += "\n"
    sections[0] = ("", preamble)
    sections.insert(1, (heading, "\n" + "\n".join(lines) + "\n"))
    return markdown.render_sections(sections)


def write_facts(root: Path, slug: str, facts, today: str) -> dict:
    """Append dated, sourced facts under `## What I know` (#273 piece 4).

    Only appends. An item that is not `{date, fact}` with a real ISO date and
    a one-line fact ending in a source marker is listed in `skipped`; a line
    already in the section is listed in `duplicates`. Nothing is written —
    not even `last-updated` — when no item survives."""
    from .entity import _SOURCE_MARKER_RE
    if not isinstance(facts, list):
        raise ValueError("facts must be a list of {date, fact} objects")
    path = _require_note(root, slug)
    text = path.read_text(encoding="utf-8")
    _, body = markdown.split_frontmatter(text)
    head = markdown._normalize(text)[: len(markdown._normalize(text)) - len(body)]
    existing = set()
    for title, content in markdown.split_sections(body):
        if title == FACTS_HEADING:
            existing = {line.strip() for line in content.split("\n") if line.strip()}
    lines, skipped, duplicates = [], [], []
    for index, item in enumerate(facts):
        if not isinstance(item, dict):
            skipped.append(f"facts[{index}]: not an object with date and fact")
            continue
        day = str(item.get("date") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if not _is_iso_date(day):
            skipped.append(f"facts[{index}]: date {day!r} is not YYYY-MM-DD")
        elif not fact:
            skipped.append(f"facts[{index}]: empty fact")
        elif "\n" in fact or "\r" in fact:
            skipped.append(f"facts[{index}]: a fact must be one line")
        elif not _SOURCE_MARKER_RE.search(fact):
            skipped.append(f"facts[{index}]: no source marker at the end — an "
                           "automatic line must say where it came from; not written")
        else:
            line = f"- {day} — {fact}"
            if line in existing:
                duplicates.append(line)
            else:
                existing.add(line)
                lines.append(line)
    rel = path.relative_to(root).as_posix()
    if lines:
        new_body = insert_section_after_preamble(body, FACTS_HEADING, lines)
        updated = markdown.upsert_scalar_field(head + new_body, "last-updated", today)
        vault.atomic_write(path, updated)
    return {"slug": path.stem, "path": rel, "written": len(lines),
            "skipped": skipped, "duplicates": duplicates}


def touch(root: Path, slug: str, *, timestamp: Optional[str] = None) -> dict:
    """Stamp `person-updated`: the automatic update has read every piece of
    new material naming this person up to this minute (#273 piece 4)."""
    if timestamp is None:
        timestamp = datetime.datetime.now().isoformat(timespec="minutes")
    if not _STAMP_RE.match(str(timestamp)):
        raise ValueError(f"timestamp {timestamp!r} must be YYYY-MM-DDTHH:MM")
    path = _require_note(root, slug)
    text = path.read_text(encoding="utf-8")
    updated = markdown.upsert_scalar_field(text, "person-updated", timestamp)
    if updated != text:
        vault.atomic_write(path, updated)
    return {"slug": path.stem, "path": path.relative_to(root).as_posix(),
            "person-updated": timestamp, "changed": updated != text}
```

If `markdown._normalize` turns out not to strip `\r` (check it), compute `head` as `text.replace("\r\n", "\n")` minus body length instead. Verify the duplicate check against an existing line written by an earlier call (test above).

CLI parser (after `person_set`):

```python
    person_write = people_sub.add_parser(
        "write", help="append dated, sourced facts under ## What I know (#273)")
    _add_vault_argument(person_write)
    person_write.add_argument("--slug", required=True)
    person_write.add_argument("--facts", required=True,
                              help="path to a JSON file {\"facts\": [...]}, or - for stdin")
    person_write.add_argument("--today", help="ISO date; defaults to today")
    person_write.add_argument(
        "--automatic", action="store_true",
        help="required: the unattended writer — appends only, every fact ends "
             "in a source marker")
    person_touch = people_sub.add_parser(
        "touch", help="stamp person-updated after the automatic update read new material")
    _add_vault_argument(person_touch)
    person_touch.add_argument("--slug", required=True)
    person_touch.add_argument("--timestamp", help="YYYY-MM-DDTHH:MM; defaults to now")
```

Dispatch (inside `if args.group == "person":`, before the `ensure` fallthrough):

```python
        if args.action == "touch":
            return _ok(person.touch(root, args.slug, timestamp=args.timestamp))
        if args.action == "write":
            if not args.automatic:
                return _fail("person write needs --automatic",
                             "It is the unattended writer; the owner edits the page by hand.")
            payload = (json.load(sys.stdin) if args.facts == "-"
                       else json.loads(Path(args.facts).read_text(encoding="utf-8")))
            facts = payload.get("facts") if isinstance(payload, dict) else payload
            return _ok(person.write_facts(root, args.slug, facts,
                                          vault.today_iso(args.today)))
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_person.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/person.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_person.py
git commit -m "feat(#273): person write --automatic and person touch for What I know"
```

---

### Task 2: People queue in `update-queue`

**Files:**
- Modify: `plugin/lib/vaultlib/updatequeue.py` (`_index_logs` keeps per-group people; new `_people_queue`; `run` returns two new keys)
- Test: `scripts/tests/test_vaultlib_updatequeue.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `run(...)["peopleNeedingUpdate"]: [{"slug", "path", "personName"}]` sorted by slug; `run(...)["peopleWork"]: [{"kind": "meeting", "path": "20-meetings/x.md", "date": "YYYY-MM-DD", "people": [slug…]} | {"kind": "log", "path": "_messages/<stem>.md", "stem", "date", "groups": [gid…], "people": [slug…]}]` sorted by (date, path).

- [ ] **Step 1: Write the failing tests** (append; reuses the file's `make_vault`, `write_meeting`, `write_log`, `g`)

```python
# --- people queue (#273 piece 4) --------------------------------------------

def write_person_full(root, slug, *, created="2026-09-01", stamp=None):
    lines = ["---", f'person-name: "{slug.title()}"', f"slug: {slug}", "relationship:",
             f"created: {created}"]
    if stamp:
        lines.append(f"person-updated: {stamp}")
    (root / "50-people" / f"{slug}.md").write_text("\n".join(lines + ["---", ""]),
                                                    encoding="utf-8")


def people_run(root, today="2026-10-12"):
    result = updatequeue.run(root, today, "owner-morgan")
    return result["peopleNeedingUpdate"], result["peopleWork"], result["warnings"]


def test_a_meeting_after_the_stamp_queues_its_attendees(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-10T20:00")
    write_person_full(root, "sam", stamp="2026-10-12T09:00")
    write_meeting(root, "11-10-26-weekly", date_value="2026-10-11T10:00",
                  attendees=["dana", "sam", "owner-morgan"])
    queued, work, _ = people_run(root)
    assert [p["slug"] for p in queued] == ["dana"]
    assert work == [{"kind": "meeting", "path": "20-meetings/11-10-26-weekly.md",
                     "date": "2026-10-11", "people": ["dana"]}]


def test_the_owner_is_never_queued(tmp_path):
    root = make_vault(tmp_path)
    write_meeting(root, "m", date_value="2026-10-11T10:00", attendees=["owner-morgan"])
    queued, work, _ = people_run(root)
    assert queued == [] and work == []


def test_a_note_capture_with_attendees_counts(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-10T20:00")
    write_meeting(root, "fwd", date_value="2026-10-11T10:00", type_value="note",
                  attendees=["dana"])
    assert [w["path"] for w in people_run(root)[1]] == ["20-meetings/fwd.md"]


def test_unconfirmed_meetings_do_not_count(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-10T20:00")
    write_meeting(root, "m", date_value="2026-10-11T10:00", review_status="pending",
                  attendees=["dana"])
    assert people_run(root)[0] == []


def test_created_is_the_start_point_without_a_stamp(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", created="2026-10-11")
    write_meeting(root, "old", date_value="2026-10-01T10:00", attendees=["dana"])
    write_meeting(root, "new", date_value="2026-10-11T10:00", attendees=["dana"])
    _, work, _ = people_run(root)
    assert [w["path"] for w in work] == ["20-meetings/new.md"]


def test_no_stamp_and_no_created_warns_and_skips(tmp_path):
    root = make_vault(tmp_path)
    write_person(root, "dana")                       # no created, no stamp
    write_meeting(root, "m", date_value="2026-10-11T10:00", attendees=["dana"])
    queued, _, warnings = people_run(root)
    assert queued == []
    assert any("50-people/dana.md" in w and "person-updated" in w for w in warnings)


def test_unparseable_stamp_warns_and_falls_back_to_created(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", created="2026-10-11", stamp="yesterday")
    write_meeting(root, "m", date_value="2026-10-11T10:00", attendees=["dana"])
    queued, _, warnings = people_run(root)
    assert [p["slug"] for p in queued] == ["dana"]
    assert any("person-updated" in w and "dana" in w for w in warnings)


def test_a_log_group_naming_a_person_queues_them_with_its_gid(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-10T20:00")
    write_person_full(root, "sam", stamp="2026-10-10T20:00")
    write_log(root, "2026-10-11", [g("a1", people=["dana"]), g("a2", people=["sam"]),
                                   g("a3", people=["nobody"])], "2026-10-11T18:52")
    queued, work, _ = people_run(root)
    assert [p["slug"] for p in queued] == ["dana", "sam"]
    assert work == [{"kind": "log", "path": "_messages/2026-10-11-messages.md",
                     "stem": "2026-10-11-messages", "date": "2026-10-11",
                     "groups": ["a1", "a2"], "people": ["dana", "sam"]}]


def test_a_log_older_than_the_stamp_does_not_queue(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-12T09:00")
    write_log(root, "2026-10-11", [g("a1", people=["dana"])], "2026-10-11T18:52")
    assert people_run(root)[0] == []


def test_start_points_are_per_person_within_one_meeting(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-01T00:00")
    write_person_full(root, "sam", stamp="2026-10-12T09:00")
    write_meeting(root, "a", date_value="2026-10-05T10:00", attendees=["dana", "sam"])
    write_meeting(root, "b", date_value="2026-10-11T10:00", attendees=["sam"])
    queued, work, _ = people_run(root)
    assert [p["slug"] for p in queued] == ["dana"]
    assert work == [{"kind": "meeting", "path": "20-meetings/a.md", "date": "2026-10-05",
                     "people": ["dana"]}]


def test_session_records_are_not_a_people_source(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-10T20:00")
    folder = root / "_messages" / "sessions"
    folder.mkdir(parents=True)
    (folder / "s.md").write_text(
        "---\ntitle: \"x\"\ndate: 2026-10-11\nprojects: [p]\npeople: [dana]\n"
        "updated-at: 2026-10-11T12:00\n---\n- x\n", encoding="utf-8")
    assert people_run(root)[0] == []


def test_people_queue_writes_nothing(tmp_path):
    root = make_vault(tmp_path)
    write_person_full(root, "dana", stamp="2026-10-10T20:00")
    write_meeting(root, "m", date_value="2026-10-11T10:00", attendees=["dana"])
    updatequeue.run(root, "2026-10-12", "owner-morgan")
    text = (root / "50-people" / "dana.md").read_text(encoding="utf-8")
    assert "person-updated: 2026-10-10T20:00" in text
```

`write_log` creates `_messages/`; if `make_vault` lacks it, `msglog.save_log` creates it — check, and `mkdir` in the test if not.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -q -k "people_queue or queues_its or owner_is_never or note_capture or unconfirmed_meetings or created_is or no_stamp_and or unparseable_stamp or log_group_naming or log_older or start_points or session_records_are_not"`
Expected: FAIL with `KeyError: 'peopleNeedingUpdate'`.

- [ ] **Step 3: Implement**

In `_index_logs`, alongside `people_groups`, collect per-group people and add to the appended dict:

```python
        groups: List[Tuple[str, List[str]]] = []
        for group in data["groups"]:
            people = group.get("people")
            if (isinstance(people, list)
                    and all(isinstance(p, str) for p in people)):
                people_groups.extend(people)
                groups.append((str(group.get("gid")), list(people)))
            else:
                ...  # existing warning unchanged
        out.append({..., "people_groups": people_groups, "groups": groups})
```

New function after `_entity_queue`:

```python
def _people_queue(root: Path, confirmed: List[dict], logs: List[dict],
                  owner_slug: str, warnings: List[str]) -> Tuple[List[dict], List[dict]]:
    """People with material newer than their `person-updated` stamp (#273
    piece 4), and that material grouped per meeting and per day log so one
    reader handles everyone in it.

    No look-back: without a stamp the start point is the `created` day at
    00:00 (a person created tonight still gets tonight's meeting); without
    either the person is skipped and named in `warnings`. Session records are
    not a source — /add writes session facts on the spot. Confirmed meetings
    of every type count, `type: note` captures included."""
    starts: Dict[str, datetime] = {}
    names: Dict[str, Tuple[str, str]] = {}
    folder = root / PEOPLE_DIR
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = path.relative_to(root).as_posix()
        try:
            data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue      # the metrics pass already warned about this file
        slug = str(data.get("slug") or "")
        if not slug or slug == owner_slug:
            continue
        raw = data.get("person-updated")
        stamp = _parse_iso_datetime(raw)
        if raw is not None and stamp is None:
            warnings.append(f"{rel}: unparseable person-updated {raw!r} — falling "
                            "back to created; rewrite it as YYYY-MM-DDTHH:MM or delete it")
        if stamp is None:
            day = _parse_first_iso_date(data.get("created"))
            if day is None:
                warnings.append(f"{rel}: no usable person-updated or created — "
                                "facts about this person are not read")
                continue
            stamp = datetime.combine(day, time.min)
        starts[slug] = stamp
        names[slug] = (rel, str(data.get("person-name") or slug))

    work: List[dict] = []
    queued: Set[str] = set()
    for m in confirmed:
        people = sorted({a for a in m["attendees"]
                         if a in starts and _activity(m) >= starts[a]})
        if people:
            work.append({"kind": "meeting", "path": m["file"],
                         "date": m["date"].isoformat(), "people": people})
            queued.update(people)
    for d in logs:
        if d["updated"] is None:
            continue
        gids, people = [], set()
        for gid, members in d["groups"]:
            hit = {p for p in members if p in starts and d["updated"] >= starts[p]}
            if hit:
                gids.append(gid)
                people |= hit
        if people:
            work.append({"kind": "log", "path": f"{vault.MESSAGES_DIR}/{d['stem']}.md",
                         "stem": d["stem"],
                         "date": d["date"].isoformat() if d["date"] else None,
                         "groups": gids, "people": sorted(people)})
            queued |= people
    work.sort(key=lambda w: (w["date"] or "", w["path"]))
    entries = [{"slug": s, "path": names[s][0], "personName": names[s][1]}
               for s in sorted(queued)]
    return entries, work
```

In `run`, after `entities_queue = ...`:

```python
    people_queue, people_work = _people_queue(root, confirmed, logs, owner_slug, warnings)
```

and add to the returned dict after `"entitiesNeedingUpdate"`:

```python
        "peopleNeedingUpdate": people_queue,
        "peopleWork": people_work,
```

Update the `queuedAt` comment: "Sections D and E stamp `entity-updated` / `person-updated` with it".

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -q`
Expected: all pass, including `test_fixture_vault_is_a_fixed_point_of_update_queue` and the CLI envelope test.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/updatequeue.py scripts/tests/test_vaultlib_updatequeue.py
git commit -m "feat(#273): update-queue lists people with new material, grouped per meeting and day log"
```

---

### Task 3: Migration 014 → structure 15 (separate reviewer)

**Files:**
- Create: `plugin/migrations/014-structure-version-15/migrate.py`
- Create: `scripts/tests/test_migration_014.py`
- Modify: `plugin/template/structure-version` (`15`), `scripts/validate_template.py:27` and `plugin/lib/instantiate_vault.py:75` (`EXPECTED_STRUCTURE_VERSION = "15"`)
- Modify: `scripts/tests/test_migration_003.py` … `test_migration_013.py` (every `structure_version == 14` / `.strip() == "14"` chain-end assertion → 15; `test_migration_013.py:303` too), `scripts/tests/test_validate_template.py:88,94,233`, `scripts/tests/test_vaultlib_provenance.py:259`
- Modify: `scripts/tests/test_fixtures_ontology.py:710-721` (filter `What I know` too)
- Modify: `fixtures/demo-vault/50-people/*.md` (migrated by running the migration)

**Interfaces:**
- Consumes: the section-placement behaviour of Task 1's `insert_section_after_preamble`, **frozen as a copy** inside the migration (a migration must keep producing what it produced when it shipped).
- Produces: every readable person page has `person-updated`, no `## Notes from ` heading.

- [ ] **Step 1: Write the failing tests** (`scripts/tests/test_migration_014.py`)

```python
"""Migration 014: Notes from <entity> merge into What I know (#273 piece 4)."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from vaultlib import markdown as md
from vaultlib import migrate

REPO = Path(__file__).resolve().parents[2]
MIG = REPO / "plugin/migrations/014-structure-version-15/migrate.py"
DEMO = REPO / "fixtures/demo-vault"


def load():
    spec = importlib.util.spec_from_file_location("m014", MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEAD = '---\nperson-name: "Dana Whitfield"\nslug: dana\nrelationship: external\ncreated: 2026-03-02\n---\n'


def vault(tmp_path, files):
    root = tmp_path / "vault"
    (root / "50-people").mkdir(parents=True)
    (root / "99-workflow-config").mkdir()
    for name, text in files.items():
        (root / "50-people" / name).write_text(text, encoding="utf-8", newline="")
    return root


def body(root, name="dana.md"):
    return md.split_frontmatter((root / "50-people" / name).read_text(encoding="utf-8"))


def test_notes_from_moves_under_what_i_know_after_the_h1(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana Whitfield\n\n## Context\n\n- mine\n\n"
                            "## Notes from Acme\n\n- Wants numbers. (moved from the Acme page, 2026-10-12)\n"})
    result = load().apply(root)
    data, text = body(root)
    assert "## Notes from" not in text
    assert text.index("## What I know") < text.index("## Context")
    assert "## What I know\n\n- Wants numbers. (moved from the Acme page, 2026-10-12)\n" in text
    assert "- mine" in text
    assert result["notes_moved"] == 1 and result["people"] == 1
    assert data["person-updated"]


def test_several_notes_from_sections_keep_their_order(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n- b\n\n"
                            "## Context\n\n- c\n\n## Notes from Beta\n\n- d\n"})
    load().apply(root)
    _, text = body(root)
    section = text.split("## What I know", 1)[1].split("## Context", 1)[0]
    assert [l for l in section.split("\n") if l.strip()] == ["- a", "- b", "- d"]
    assert text.count("## ") == 2


def test_non_bullet_text_moves_too(tmp_path):
    raw = (HEAD + "\n# Dana\n\n## Notes from Acme\n\nSome prose.\n\n```dataview\nLIST\n```\n\n- x\n")
    root = vault(tmp_path, {"dana.md": raw})
    load().apply(root)
    _, text = body(root)
    for piece in ("Some prose.", "```dataview\nLIST\n```", "- x"):
        assert piece in text.split("## What I know", 1)[1]


def test_existing_what_i_know_is_appended_to(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## What I know\n\n- kept\n\n"
                            "## Notes from Acme\n\n- moved\n"})
    load().apply(root)
    _, text = body(root)
    assert "## What I know\n\n- kept\n- moved\n" in text


def test_every_page_gets_a_stamp_but_no_empty_section(tmp_path):
    root = vault(tmp_path, {"sam.md": HEAD.replace("slug: dana", "slug: sam") + "\n# Sam\n"})
    load().apply(root)
    data, text = body(root, "sam.md")
    assert data["person-updated"] and "## What I know" not in text


def test_an_existing_stamp_is_kept(tmp_path):
    raw = HEAD.replace("created:", "person-updated: 2026-10-01T10:00\ncreated:") + "\n# Dana\n"
    root = vault(tmp_path, {"dana.md": raw})
    load().apply(root)
    assert body(root)[0]["person-updated"] == "2026-10-01T10:00"


def test_apply_is_idempotent(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n"})
    module = load()
    module.apply(root)
    first = (root / "50-people/dana.md").read_bytes()
    result = module.apply(root)
    assert (root / "50-people/dana.md").read_bytes() == first
    assert result["notes_moved"] == 0


def test_an_unreadable_page_is_left_and_reported(tmp_path):
    broken = '---\nperson-name: "Half\n  open\n---\n## Notes from Acme\n\n- a\n'
    root = vault(tmp_path, {"broken.md": broken})
    module = load()
    result = module.apply(root)
    assert (root / "50-people/broken.md").read_text(encoding="utf-8") == broken
    assert any("50-people/broken.md" in item for item in result["needs_human"])
    module.verify(root)


def test_verify_raises_when_notes_from_remains(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD.replace("created:", "person-updated: 2026-10-01T10:00\ncreated:")
                            + "\n# Dana\n\n## Notes from Acme\n\n- a\n"})
    with pytest.raises(Exception, match="Notes from"):
        load().verify(root)


def test_crlf_page_migrates(tmp_path):
    raw = (HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n").replace("\n", "\r\n")
    root = vault(tmp_path, {"dana.md": raw})
    load().apply(root)
    _, text = body(root)
    assert "## What I know\n\n- a\n" in text and "## Notes from" not in text


def test_the_whole_chain_ends_at_15(tmp_path):
    root = vault(tmp_path, {"dana.md": HEAD + "\n# Dana\n\n## Notes from Acme\n\n- a\n"})
    (root / "structure-version").write_text("14\n", encoding="utf-8")
    result = migrate.run(root, "2026-10-12", stamp="2026-10-12-120000")
    assert result["structure_version"] == 15


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_demo_vault_is_already_migrated(tmp_path):
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    module = load()
    before = files(root)
    result = module.apply(root)
    assert files(root) == before and result["notes_moved"] == 0
    module.verify(root)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_migration_014.py -q`
Expected: FAIL — migration file missing.

- [ ] **Step 3: Implement** `plugin/migrations/014-structure-version-15/migrate.py`

```python
"""Structure-version 15: `## Notes from <entity>` becomes `## What I know` (#273 piece 4).

Person pages now carry one section of facts about the person, `## What I
know`, placed right after the `# Name` heading; the evening run appends to
it. The structure-14 upgrade and /update-entity wrote such notes under
`## Notes from <entity>`, one heading per entity. This migration, for every
person page:

- moves everything under each `## Notes from …` heading — bullets, prose,
  code blocks, in page order, each line verbatim — to the end of `## What I
  know` (created after the H1 when missing), and drops the emptied headings;
- stamps `person-updated` with the upgrade moment when the page has none, so
  the first evening reads nothing older than the upgrade (the owner chose no
  look-back).

A page whose frontmatter will not parse is left byte-identical and named in
`needs_human`. Running it twice changes nothing. Not lossy: every line is
kept; only the `Notes from` headings go.

The section placement is frozen here (a copy of person.py's at ship time): a
migration must keep producing what it produced when it shipped.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import markdown, vault  # noqa: E402

TARGET_VERSION = 15
LOSSY = None

HEADING = "What I know"
PREFIX = "Notes from "


class MigrationError(Exception):
    """A readable person page still has a Notes from heading or no stamp."""


def _split_head(text: str) -> Tuple[str, str]:
    _, body = markdown.split_frontmatter(text)
    return text[:len(text) - len(body)], body


def _trim(content: str) -> List[str]:
    lines = content.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _insert(body: str, lines: List[str]) -> str:
    sections = markdown.split_sections(body)
    for i, (title, content) in enumerate(sections):
        if title == HEADING:
            kept = content.rstrip("\n")
            last = kept.split("\n")[-1].strip() if kept.strip() else ""
            gap = "\n" if (not last or last.startswith("- ")) else "\n\n"
            if not kept.strip():
                kept, gap = "", "\n"
            first = lines[0].strip() if lines else ""
            if not first.startswith("- "):
                gap = "\n\n" if kept else "\n"
            sections[i] = (title, kept + gap + "\n".join(lines) + "\n")
            return markdown.render_sections(sections)
    preamble = sections[0][1]
    if not preamble.endswith("\n"):
        preamble += "\n"
    sections[0] = ("", preamble)
    sections.insert(1, (HEADING, "\n" + "\n".join(lines) + "\n"))
    return markdown.render_sections(sections)


def _people(root: Path):
    folder = root / vault.PEOPLE_DIR
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def apply(root: Path) -> dict:
    root = Path(root)
    stamp = datetime.now().isoformat(timespec="minutes")
    result = {"people": 0, "notes_moved": 0, "stamped": 0, "needs_human": []}
    for path in _people(root):
        rel = path.relative_to(root).as_posix()
        try:
            original = path.read_text(encoding="utf-8")
            text = original.replace("\r\n", "\n")
            data, _ = markdown.split_frontmatter(text)
            head, body = _split_head(text)
        except (ValueError, OSError) as exc:
            result["needs_human"].append(
                f"{rel}: not readable ({exc}) — left as it is; move any "
                f"'## Notes from' text under '## {HEADING}' by hand")
            continue
        result["people"] += 1
        sections = markdown.split_sections(body)
        moved: List[str] = []
        kept = []
        for title, content in sections:
            if title.startswith(PREFIX):
                lines = _trim(content)
                if moved and lines:
                    if not (moved[-1].startswith("- ") and lines[0].startswith("- ")):
                        moved.append("")
                moved.extend(lines)
                result["notes_moved"] += sum(1 for l in lines if l.startswith("- "))
            else:
                kept.append((title, content))
        if len(kept) != len(sections):
            body = markdown.render_sections(kept)
            if moved:
                body = _insert(body, moved)
        text = head + body
        if data.get("person-updated") in (None, ""):
            text = markdown.upsert_scalar_field(text, "person-updated", stamp)
            result["stamped"] += 1
        # Compared against the LF text: a CRLF page with nothing to do stays
        # byte-identical, as in migration 013.
        if text != original.replace("
", "
"):
            vault.atomic_write(path, text)
    return result


def verify(root: Path) -> dict:
    problems, checked = [], 0
    for path in _people(Path(root)):
        rel = path.relative_to(root).as_posix()
        try:
            data, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue          # reported by apply; the owner's to fix
        checked += 1
        if any(t.startswith(PREFIX) for t, _ in markdown.split_sections(body)):
            problems.append(f"{rel}: still has a '## Notes from' heading")
        if data.get("person-updated") in (None, ""):
            problems.append(f"{rel}: no person-updated")
    if problems:
        raise MigrationError("; ".join(problems))
    return {"people": checked}
```

When the removal of `Notes from` sections leaves the previous section's content without its trailing blank line, `render_sections` already joins with `\n` — check `test_several_notes_from_sections_keep_their_order` and the demo fixture diff for doubled or missing blank lines and fix in `_insert`/removal, not in the tests.

- [ ] **Step 4: Bump the structure chain**

```bash
printf '15\n' > plugin/template/structure-version   # match the existing file's trailing-newline style first: cat -A it
sed -i 's/EXPECTED_STRUCTURE_VERSION = "14"/EXPECTED_STRUCTURE_VERSION = "15"/' scripts/validate_template.py plugin/lib/instantiate_vault.py
grep -rln 'structure_version"\] == 14\|strip() == "14"' scripts/tests | xargs sed -i 's/structure_version"\] == 14/structure_version"] == 15/; s/strip() == "14"/strip() == "15"/'
```

Then by hand: `scripts/tests/test_validate_template.py` lines 88, 94 (the "14" literals), `scripts/tests/test_vaultlib_provenance.py:259` (`"structure_version": "15"`), and any `applied` slug list (`grep -rn "013-structure-version-14" scripts/tests`) gets `"014-structure-version-15"` appended. In `scripts/tests/test_fixtures_ontology.py:710-721`, change both filters to `if not t.startswith("Notes from ") and t != "What I know"` and the comment to say the structure-15 upgrade merged them into `## What I know`.

- [ ] **Step 5: Migrate the demo fixture**

Write `$SCRATCH/migrate_fixture.py` with the Write tool:

```python
import importlib.util, sys
from pathlib import Path
repo = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("m014", repo / "plugin/migrations/014-structure-version-15/migrate.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.apply(repo / "fixtures/demo-vault")); print(m.verify(repo / "fixtures/demo-vault"))
```

Run: `python "$SCRATCH/migrate_fixture.py" .` and inspect `git diff fixtures/demo-vault/50-people/dana-whitfield.md`.

- [ ] **Step 6: Run the migration and fixture tests**

Run: `python -m pytest scripts/tests/test_migration_0*.py scripts/tests/test_validate_template.py scripts/tests/test_vaultlib_provenance.py scripts/tests/test_fixtures_ontology.py -q`
Expected: all pass (`test_migration_001` indented-key flake on Windows is known).

- [ ] **Step 7: Commit**

```bash
git add plugin/migrations/014-structure-version-15 scripts/tests plugin/template/structure-version scripts/validate_template.py plugin/lib/instantiate_vault.py fixtures/demo-vault
git commit -m "feat(#273): migration 014 merges Notes from into What I know and stamps person-updated (structure 15)"
```

---

### Task 4: Ontology, vault rule and privacy guards

**Files:**
- Modify: `plugin/template/99-workflow-config/reference/ontology.md` (Person block ~line 226-265)
- Modify: `plugin/lib/vaultlib/schema.json` (regenerated)
- Modify: `plugin/template/CLAUDE.md` (Key Patterns)
- Modify: `plugin/lib/vaultlib/feedback.py` (`_blocklist`)
- Test: `scripts/tests/test_vaultlib_feedback.py`, `scripts/tests/test_vaultlib_tables_export.py` (append)

**Interfaces:**
- Consumes: `person.FACTS_HEADING` (Task 1).
- Produces: `feedback.lint` blocks any fact text (kind `"fact"`).

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_feedback.py` (use the file's existing vault helper — check its name with `grep -n "^def " scripts/tests/test_vaultlib_feedback.py`; below assumes `make_vault(tmp_path)` returning the root with `50-people/`):

```python
def test_a_fact_from_what_i_know_is_blocked(tmp_path):
    root = make_vault(tmp_path)
    (root / "50-people" / "zed.md").write_text(
        '---\nperson-name: "Zed Q"\nslug: zed\n---\n# Zed Q\n\n## What I know\n\n'
        "- 2026-10-08 — Is selling the house in Ghent. (meeting · [[m]])\n"
        "- Plays chess on Sundays.\n", encoding="utf-8")
    result = feedback.lint(root, "The sync crashed; also is selling the house in ghent lol")
    assert result["ok"] is False
    assert {"kind": "fact", "fragment": "Is selling the house in Ghent."} in result["blocked"]
    assert feedback.lint(root, "plays chess on sundays")["ok"] is False
    assert feedback.lint(root, "The sync crashed on step 6.")["ok"] is True
```

Append to `scripts/tests/test_vaultlib_tables_export.py`:

```python
def test_people_export_carries_no_page_text(tmp_path):
    root = make_vault(tmp_path)
    path = root / "50-people/jan-peeters.md"
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n## What I know\n\n- 2026-10-08 — Secret fact. (meeting · [[m]])\n",
                    encoding="utf-8")
    result = tables.export(root, "people", today="2026-10-12")
    book = xlsx.read(root / result["path"])
    cells = [str(c) for sheet in book.values() for row in sheet for c in row]
    assert not any("Secret fact" in c for c in cells)
```

- [ ] **Step 2: Run to verify the feedback test fails** (the export test should already pass — it pins today's behaviour)

Run: `python -m pytest scripts/tests/test_vaultlib_feedback.py scripts/tests/test_vaultlib_tables_export.py -q`
Expected: `test_a_fact_from_what_i_know_is_blocked` FAILS; export test passes.

- [ ] **Step 3: Implement the feedback guard**

In `feedback._blocklist`, inside the people loop, read the body too:

```python
    for path in sorted((root / vault.PEOPLE_DIR).glob("*.md")):
        terms.append(("person", path.stem))
        try:
            front, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            front, body = {}, ""
        if front.get("person-name"):
            terms.append(("person", str(front["person-name"])))
        terms.extend(("fact", fact) for fact in _facts(body))
```

and add above `_blocklist`:

```python
_FACT_DATE_RE = re.compile(r"\A- (?:\d{4}-\d{2}-\d{2} — )?")
_FACT_MARKER_RE = re.compile(r"\s*\((?:meeting|mail|chat|session|note|moved from|from) [^()]*\)\s*\Z")


def _facts(body: str) -> list:
    """The text of each line under `## What I know` (#273 piece 4), without
    its date and source marker: facts about a person never leave the vault."""
    out = []
    for title, content in markdown.split_sections(body):
        if title != "What I know":
            continue
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            text = _FACT_MARKER_RE.sub("", _FACT_DATE_RE.sub("", line)).strip()
            if text:
                out.append(text)
    return out
```

(`_MIN_TERM_LEN` already drops fragments under 4 characters.) Update the module docstring's first paragraph to mention person facts.

- [ ] **Step 4: Ontology + schema + vault rule**

In `ontology.md`'s Person yaml block, add `person-updated` to `optional` (after `last-updated`). Below the `company` bullet add:

```markdown
- `person-updated` — when the automatic update last read new material naming
  this person (ISO `YYYY-MM-DDTHH:MM`, written by `person touch`). The
  structure-15 upgrade stamps every page, so nothing older is read.
- **`## What I know`** (#273 piece 4) — directly after the `# Name` heading:
  facts about the person. The evening run and on-demand runs append
  `- <YYYY-MM-DD> — <fact> (<source marker>)` lines via `person write
  --automatic`; it never edits or removes a line. A line without a marker is
  the owner's. Two rules: (1) **it never leaves the vault** — no prep note,
  brief, email or feedback report uses it, and the daily note shows nothing
  from it; (2) **only what the person said about themselves** — never what
  others said about them, never an interpretation. Removing a fact = deleting
  its line.
```

Replace "Auto-created from meeting attendees; enriched manually via People Base." paragraph's neighbour if it says the body is empty (grep "body" in that block). Then run `python scripts/compile_ontology.py` and check `git diff plugin/lib/vaultlib/schema.json` shows only `person-updated` added.

In `plugin/template/CLAUDE.md`, under `## Key Patterns`, add:

```markdown
### Facts about people

A person page's `## What I know` holds what that person said about
themselves. It never goes into anything meant for someone else — prep
notes, briefs, emails, feedback reports — and the daily note shows nothing
from it. Add a fact by telling Claude (`/add`) or by writing the line
yourself; delete a line to remove it.
```

- [ ] **Step 5: Run**

Run: `python -m pytest scripts/tests/test_vaultlib_feedback.py scripts/tests/test_vaultlib_tables_export.py scripts/tests/test_validate_template.py scripts/tests/test_fixtures_ontology.py scripts/tests/test_vaultlib_schema*.py -q`
Expected: pass. If a template-provenance/hash test fails because CLAUDE.md changed, follow its message (usually regenerating a baseline — `grep -rn "CLAUDE.md" scripts/tests/test_vaultlib_provenance.py`).

- [ ] **Step 6: Commit**

```bash
git add plugin/template plugin/lib/vaultlib/schema.json plugin/lib/vaultlib/feedback.py scripts/tests
git commit -m "feat(#273): What I know in the ontology and vault rules; feedback scrub blocks person facts"
```

---

### Task 5: Skills — section E, /add, /update-entity, summaries

**Files:**
- Modify: `plugin/skills/evening-sync/references/process.md` (Inputs table, new `## E. Facts about people` before `## Returns`, Returns list)
- Modify: `plugin/skills/evening-sync/SKILL.md` (Stage 5 prep rule; summary line)
- Modify: `plugin/skills/sync-recordings/SKILL.md` (step 9: "sections A–E", lock release after E; summary line)
- Modify: `plugin/skills/add/SKILL.md` (step 3 people facts; step 5 write; step 6 "A–E"; summary line)
- Modify: `plugin/skills/update-entity/SKILL.md` (people step ~line 224)
- Test: `scripts/tests/test_skill_contracts.py` (update 2 existing tests, add new ones)

**Interfaces:**
- Consumes: `person write --automatic --facts`, `person touch --timestamp` (Task 1); `peopleNeedingUpdate`, `peopleWork`, `queuedAt` (Task 2).

- [ ] **Step 1: Write the failing contract tests** (append to `scripts/tests/test_skill_contracts.py`; update the two existing ones as shown)

Change `test_update_entity_bash_blocks_continue_lines_properly`'s last two asserts to:

```python
    assert "## What I know" in _people_step()
    assert "person write" in _people_step() and "--automatic" in _people_step()
    assert "## Notes from <entity name>" not in _people_step()
```

Change `test_on_demand_runs_release_the_lock_after_entity_updates` to check `"section E"` instead of `"section D"` (rename to `..._after_people_updates`).

New tests:

```python
def _process_e():
    text = read_ref("evening-sync", "process.md")
    return " ".join(text.split("## E. Facts about people", 1)[1].split("## Returns", 1)[0].split())


def test_process_has_people_updates_after_entity_updates():
    text = read_ref("evening-sync", "process.md")
    assert (text.index("## D. Entity updates") < text.index("## E. Facts about people")
            < text.index("## Returns"))
    e = _process_e()
    for needle in ("peopleWork", "peopleNeedingUpdate", "person write", "--automatic",
                   "person touch", "queuedAt", "(meeting · ", "(mail · ", "(chat · ",
                   "section C"):
        assert needle in e, needle


def test_people_updates_keep_only_what_the_person_said():
    e = _process_e().lower()
    assert "said about themselves" in e
    assert "what others said" in e and "interpretation" in e


def test_people_updates_show_nothing_personal():
    e = _process_e().lower()
    assert "counts only" in e and "daily note" in e
    stage5 = read_skill("evening-sync").split("## Stage 5", 1)[1].split("## Stage 6", 1)[0]
    assert "What I know" in stage5


def test_summaries_count_people_facts():
    for skill in ("evening-sync", "sync-recordings", "add"):
        assert "**People pages:**" in read_skill(skill), skill


def test_add_writes_person_facts_at_once():
    text = read_skill("add")
    step5 = text.split("### 5. Write", 1)[1].split("### 6.", 1)[0]
    assert "person write" in step5 and "--automatic" in step5 and "(session · " in step5
    assert "said about themselves" in " ".join(text.split()).lower()


def test_process_inputs_table_names_people_updates():
    text = read_ref("evening-sync", "process.md")
    table = text.split("## Inputs", 1)[1].split("## A.", 1)[0]
    assert "Facts about people (E)" in table
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k "people or person_facts or entity_bash or release_the_lock or inputs_table"`
Expected: FAIL.

- [ ] **Step 3: Write section E** in `process.md`, between D and `## Returns`:

````markdown
## E. Facts about people

After section D has returned. `update-queue`'s result from B carries
`peopleNeedingUpdate` (`slug`, `path`, `personName`) and `peopleWork`: one
item per meeting (`kind: meeting`, `path`, `date`, `people`) and per day log
(`kind: log`, `path`, `stem`, `date`, `groups`, `people`) that names someone
with material newer than their `person-updated` stamp. `peopleWork` empty →
record "no people pages to update" and go on.

Otherwise dispatch one subagent per item (`model: sonnet`), in the same
blocking batches of at most 3 as section C — the rule written there applies
here unchanged. There is no cap. Each subagent carries its item, the
`personName` of each of its `people`, today's date and these instructions:

1. Read the material end to end — for a meeting, its note (Key Takeaways,
   Debrief, transcript excerpts when present); for a log, the day log file
   at `path`, only the groups whose id is in `groups`. Read each listed
   person's page (`50-people/<slug>.md`) for its `## What I know`.
2. For each listed person, keep only what **that person said about
   themselves** — personal or working: "I'm selling my house", "I prefer a
   written business case", "I'm moving to the Antwerp office", "I'm having a
   hard time with this topic". Never what others said about them, never an
   interpretation of tone or mood ("seemed stressed"), nothing invented,
   nothing already on their page. Writing nothing is a valid outcome — most
   meetings hold no such fact.
3. Write per person, one line per fact, the date being the material's own
   `date`:

```bash
cat > "$SCRATCH/person-facts-<slug>.payload.json" <<'JSON'
{"facts": [{"date": "2026-10-08", "fact": "Is selling her house, wants to move closer to Ghent. (meeting · [[08-10-26-weekly]])"}]}
JSON
python3 "$VAULTLIB" person write --vault "$VAULT" --slug <slug> --automatic --facts "$SCRATCH/person-facts-<slug>.payload.json"
```

   The marker is `(meeting · [[<meeting stem>]])` for a meeting, or
   `(mail · <link>)` / `(chat · <link>)` for a log group (the group's `link`,
   `mail` or `chat` per its `kind`). `person write` refuses a fact without a
   marker or on more than one line and lists it in `skipped`; fix it and
   retry once, then drop it and report it in `notes`.
4. Return a fenced JSON block: `{"path", "written": {"<slug>": N, …},
   "skipped": [...], "notes"}`. A subagent that fails or returns no block
   becomes a warning.

When every batch has returned, stamp each person in `peopleNeedingUpdate`
whose items all returned a block — also when nothing was written:

```bash
python3 "$VAULTLIB" person touch --vault "$VAULT" --slug <slug> --timestamp <queuedAt>
```

A person with a failed item is not stamped, so the next run reads the
material again (`person write` skips exact duplicates).

What reaches the caller is **counts only**: facts written and people
touched. No fact text goes into the summary, the recap or the daily note —
facts about people never leave their page.
````

Inputs table: add a row after Entity updates:

```markdown
| Facts about people (E) | yes | yes — every person with new material since their last update |
```

Returns: add after `entitiesUpdated`:

```markdown
- `peopleFacts`: `{facts: N, people: M}` from E — counts only, never names or fact text. The summary's **People pages:** line reads "N facts added for M people", or none
```

Also update the opening line's/Inputs wording that says "sections A–D" (grep `A, B, C and D` / `section D has returned` in all three skills and process.md) to include E, and move each "When section D has returned, release the lock" to "When section E has returned".

**evening-sync/SKILL.md:** Stage 5 — add one line where prep is described: "Prep never reads a person page's `## What I know`: facts about people stay on their page." Summary block: after the `**Entity pages updated:**` line add `**People pages:** {N} facts added for {M} people | none`.

**sync-recordings/SKILL.md** step 9 and summary: same E wording and summary line.

**add/SKILL.md:**
- Step 3, after the **people** bullet: `- **facts about people**: anything the owner tells you a person said about themselves ("Jan told me he's moving to Antwerp") — kept only as the person said it, never your interpretation. A conversation that holds only such facts needs no project and no session record.`
- Step 4: the session line lists them under the bullets as `Jan Peeters: moving to Antwerp`.
- Step 5, after `session write` (and as the whole write when there is no session record):

````markdown
**Facts about people** (each confirmed in step 4), per person:

```bash
cat > "$SCRATCH/person-facts-<slug>.payload.json" <<'JSON'
{"facts": [{"date": "<today>", "fact": "Is moving to the Antwerp office. (session · [[_messages/sessions/<stem>|<title>]])"}]}
JSON
python3 "$VAULTLIB" person write --vault "$VAULT" --slug <slug> --automatic --facts "$SCRATCH/person-facts-<slug>.payload.json"
```

With no session record the marker is `(session · /add, <today>)`. A fact
listed in `skipped`: fix and retry once, else say so in step 8's Warnings.
````

- Step 6: "sections A, B, C, D and E", release after E.
- Step 8 summary: add `**People pages:** {N} facts added for {M} people | none`.

**update-entity/SKILL.md** people step (~line 224): replace the `## Notes from <entity name>` paragraph and block with:

````markdown
A note about a person ("wants numbers, not narrative") goes onto the
person's page under `## What I know`, as something the person said or
showed about themselves — never your interpretation:

```bash
cat > "$SCRATCH/person-facts-<slug>.payload.json" <<'JSON'
{"facts": [{"date": "<today>", "fact": "Wants numbers, not narrative. (session · /update-entity, <today>)"}]}
JSON
python3 "$VAULTLIB" person write --vault "$VAULT" --slug <slug> --automatic --facts "$SCRATCH/person-facts-<slug>.payload.json"
```
````

- [ ] **Step 4: Run**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q` then `python scripts/lint_plugin.py`
Expected: pass / lint clean. Fix any older contract test that pinned "section D has returned" wording by updating it to E, not by weakening it.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills scripts/tests/test_skill_contracts.py
git commit -m "feat(#273): section E writes facts about people; /add and /update-entity write What I know"
```

---

### Task 6: Version, changelog, full suite

**Files:**
- Modify: `plugin/.claude-plugin/plugin.json` (`0.13.18`), `scripts/tests/test_marketplace_manifest.py` (`0.13.18`), `CHANGELOG.md` (`## Unreleased`)

- [ ] **Step 1: Bump**

```bash
sed -i 's/"version": "0.13.17"/"version": "0.13.18"/' plugin/.claude-plugin/plugin.json
grep -n "0.13.17" scripts/tests/test_marketplace_manifest.py   # replace each with 0.13.18
```

CHANGELOG under `## Unreleased` (one line, client-facing; PR number added after `gh pr create`):

```markdown
- Person pages get **What I know**: facts people said about themselves, added every evening from meetings, mail and Teams, and when you tell Claude — each line dated and naming its source. These facts never leave the vault and never appear in the daily note. The upgrade (structure 15) moves your existing "Notes from …" lines into it. (#273, #<PR>)
```

- [ ] **Step 2: Full suite**

Run: `python -m pytest scripts/tests -q > "$SCRATCH/pytest.txt" 2>&1; tail -30 "$SCRATCH/pytest.txt"` and `python scripts/lint_plugin.py`
Expected: all pass except the two known Windows flakes (`test_migration_001` indented key; `test_vaultlib_entity.py::test_context_bullets_written_across_calls_are_never_dropped_by_the_cap`) — re-run those alone to confirm flakiness.

- [ ] **Step 3: Commit**

```bash
git add plugin/.claude-plugin/plugin.json scripts/tests/test_marketplace_manifest.py CHANGELOG.md
git commit -m "chore(#273): 0.13.18"
```

- [ ] **Step 4: Final whole-branch review** on the most capable model; fix Critical/Important test-first. Then push, `gh pr create`, add the PR number to the CHANGELOG line, commit, `python scripts/check_changelog_entry.py --pr <n> --base origin/main`, push. Build a demo vault (`python scripts/make_test_vault.py --demo-day 2026-10-12 --with-plugins <dir>`) and ask the owner to check one person page in Obsidian.
