"""daily-note write/read: the machine half of the daily-note contract.

The CLI owns the marker-region merge; bytes outside markers are untouchable
(design decision 10) — pinned here by exact byte comparisons.
"""
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from vaultlib import dailynote

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "cli.py"
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo-vault"


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "60-daily-notes").mkdir()
    folder = tmp_path / "40-entities" / "acme-industries"
    folder.mkdir(parents=True)
    (folder / "dossier.md").write_text(
        "---\ntype: entity\nentity-name: \"Acme\"\nslug: acme-industries\n"
        "status: active\n---\n", encoding="utf-8")
    return tmp_path


def make_linkable_vault(tmp_path: Path) -> Path:
    root = make_vault(tmp_path)
    (root / "50-people").mkdir()
    (root / "50-people" / "taylor-brooks.md").write_text(
        "---\nperson-name: Taylor Brooks\nslug: taylor-brooks\n"
        "relationship: external\n---\n", encoding="utf-8")
    project = root / "30-projects" / "yard-automation"
    project.mkdir(parents=True)
    (project / "index.md").write_text(
        "---\ntype: project\nproject-name: Yard Automation Program\n"
        "slug: yard-automation\n---\n", encoding="utf-8")
    (project / "decisions").mkdir()
    (project / "decisions" / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\n---\n", encoding="utf-8")
    (root / "20-meetings").mkdir()
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n",
        encoding="utf-8")
    return root


def payload(**overrides) -> dict:
    base = {
        "date": "2026-06-15",
        "recap": ("> [!info] At a glance\n"
                  "> 1 meeting Friday · quiet weekend ahead\n"
                  "- Recap bullet one."),
        "meetings": [
            {"time": "09:00", "subject": "Weekly Status",
             "entity": "acme-industries",
             "prep": "**Attendees:** Sam · **Last meeting:** 2026-06-08 · **Context:** cadence."},
            {"time": "14:00", "subject": "Deep dive — vendor scoring",
             "entity": None,
             "prep": "**Attendees:** Omar · **Last meeting:** none · **Context:** first session."},
        ],
    }
    base.update(overrides)
    return base


def make_windowed_vault(tmp_path: Path) -> Path:
    """A vault whose recap window 2026-06-12..2026-06-12 has real inputs."""
    root = make_vault(tmp_path)
    (root / "20-meetings").mkdir()
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n\n"
        "## Key Takeaways\n- Shortlist approved.\n", encoding="utf-8")
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        "---\ndate: 2026-06-12\ntype: daily-note\n---\n\n"
        "## End of day\n- Ran long.\n", encoding="utf-8")
    return root


def windowed_payload(**overrides) -> dict:
    base = payload(date="2026-06-15",
                   recap_window={"from": "2026-06-12", "to": "2026-06-12"})
    base.update(overrides)
    return base


EXPECTED_FRESH = """---
date: 2026-06-15
type: daily-note
---

# 2026-06-15 · Monday

> [!review] Waiting for you
> ![[20-meetings/Meetings.base#To review]]
>
> ![[30-projects/Decisions.base#To review]]

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> 1 meeting Friday · quiet weekend ahead
- Recap bullet one.
<!-- evening-sync:recap:end -->

## Meetings

### 09:00 — Weekly Status · [[acme-industries]]
<!-- evening-sync:prep:begin -->
**Attendees:** Sam · **Last meeting:** 2026-06-08 · **Context:** cadence.
<!-- evening-sync:prep:end -->
- 

### 14:00 — Deep dive — vendor scoring
<!-- evening-sync:prep:begin -->
**Attendees:** Omar · **Last meeting:** none · **Context:** first session.
<!-- evening-sync:prep:end -->
- 

## Notes
- 
"""


def test_fresh_render_matches_the_contract_exactly(tmp_path):
    root = make_vault(tmp_path)
    result = dailynote.write(root, payload())
    assert result["created"] is True
    assert result["day_name"] == "Monday"
    assert result["regions_replaced"] == 3
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert text == EXPECTED_FRESH


def test_empty_calendar_renders_the_no_meetings_region(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload(meetings=[]))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "### " not in text
    assert ("<!-- evening-sync:prep:begin -->\n*No meetings scheduled.*\n"
            "<!-- evening-sync:prep:end -->") in text


def test_meetings_note_replaces_the_default_line(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload(
        meetings=[], meetings_note="*Calendar unavailable — check Outlook directly.*"))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "*Calendar unavailable — check Outlook directly.*" in text
    with pytest.raises(dailynote.DailyNoteError, match="meetings_note"):
        dailynote.write(root, payload(meetings_note="x"))  # meetings non-empty


def test_merge_replaces_regions_and_preserves_every_other_byte(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    # The user jots into the note by hand — outside the markers.
    jotted = path.read_text(encoding="utf-8")
    jotted = jotted.replace(
        "<!-- evening-sync:prep:end -->\n- \n\n### 14:00",
        "<!-- evening-sync:prep:end -->\n- shortlist approved, log it\n\n### 14:00")
    jotted = jotted.replace("## Notes\n- \n",
                            "## Notes\n- long day; Meridian steady\n")
    path.write_text(jotted, encoding="utf-8")

    updated = payload()
    updated["recap"] = "- A completely regenerated recap."
    updated["meetings"][1]["prep"] = "**Attendees:** Omar, Taylor · fresh prep."
    result = dailynote.write(root, updated)
    assert result["created"] is False and result["changed"] is True
    text = path.read_text(encoding="utf-8")
    assert "- shortlist approved, log it" in text
    assert "- long day; Meridian steady" in text
    assert "- A completely regenerated recap." in text
    assert "fresh prep." in text
    # Byte-level pin: strip region interiors from both sides; the remainder
    # (markers included) must be identical.
    def skeleton(raw):
        lines, keep, inside = raw.split("\n"), [], False
        for line in lines:
            if line.startswith("<!-- evening-sync:") and line.endswith(":begin -->"):
                inside = True
                keep.append(line)
                continue
            if line.startswith("<!-- evening-sync:") and line.endswith(":end -->"):
                inside = False
            if not inside:
                keep.append(line)
        return "\n".join(keep)
    assert skeleton(text) == skeleton(jotted)


def test_merge_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    first = path.read_text(encoding="utf-8")
    result = dailynote.write(root, payload())
    assert result["changed"] is False
    assert path.read_text(encoding="utf-8") == first


def test_merge_refuses_a_structural_change(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())   # two meetings -> two prep regions
    smaller = payload()
    smaller["meetings"] = smaller["meetings"][:1]
    with pytest.raises(dailynote.DailyNoteError, match="structure"):
        dailynote.write(root, smaller)


def test_merge_refuses_one_meeting_to_empty_calendar(tmp_path):
    root = make_vault(tmp_path)
    one_meeting = payload()
    one_meeting["meetings"] = one_meeting["meetings"][:1]
    dailynote.write(root, one_meeting)   # one meeting -> one headed prep region
    with pytest.raises(dailynote.DailyNoteError, match="structure"):
        dailynote.write(root, payload(
            meetings=[], meetings_note="*Calendar unavailable.*"))


def test_merge_refuses_empty_calendar_to_meetings(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload(
        meetings=[], meetings_note="*Calendar unavailable.*"))
    one_meeting = payload()
    one_meeting["meetings"] = one_meeting["meetings"][:1]
    with pytest.raises(dailynote.DailyNoteError, match="structure"):
        dailynote.write(root, one_meeting)


def test_merge_refuses_an_equal_count_meeting_swap(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())   # two meetings, standard payload
    swapped = payload()
    swapped["meetings"][1]["subject"] = "Deep dive — completely different topic"
    with pytest.raises(dailynote.DailyNoteError, match="structure"):
        dailynote.write(root, swapped)


def test_merge_tolerates_a_line_between_heading_and_marker(tmp_path):
    """The gap between a heading and its prep marker is outside the markers,
    so it is the user's: a blank line from an Obsidian formatter, or a note
    typed under the heading, must not read as "this region has no heading"
    and refuse every run from then on."""
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "### 09:00 — Weekly Status · [[acme-industries]]\n"
            "<!-- evening-sync:prep:begin -->",
            "### 09:00 — Weekly Status · [[acme-industries]]\n\n"
            "moved to room 3\n"
            "<!-- evening-sync:prep:begin -->"),
        encoding="utf-8")
    fresh = payload()
    fresh["meetings"][0]["prep"] = "**Attendees:** Sam, Dana · **Context:** new."
    result = dailynote.write(root, fresh)
    assert result["changed"] is True
    text = path.read_text(encoding="utf-8")
    assert "moved to room 3" in text
    assert "**Attendees:** Sam, Dana · **Context:** new." in text


def test_merge_ignores_a_heading_inside_recap_content(tmp_path):
    """A `### ` line inside the recap region is content, not a meeting heading:
    the search stops at the region above the prep region."""
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-15.md").write_text(
        "---\ndate: 2026-06-15\ntype: daily-note\n---\n\n"
        "# 2026-06-15 · Monday\n\n"
        "<!-- evening-sync:recap:begin -->\n"
        "### 08:00 — a line the user pasted into the recap\n"
        "<!-- evening-sync:recap:end -->\n\n"
        "<!-- evening-sync:prep:begin -->\n*No meetings scheduled.*\n"
        "<!-- evening-sync:prep:end -->\n", encoding="utf-8")
    result = dailynote.write(root, payload(meetings=[]))
    assert result["changed"] is True


def test_merge_refuses_an_entity_only_heading_change(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    dropped = payload()
    dropped["meetings"][0]["entity"] = None
    with pytest.raises(dailynote.DailyNoteError, match="structure"):
        dailynote.write(root, dropped)


def test_rejects_markers_inside_payload_content(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="markers"):
        dailynote.write(root, payload(
            recap="sneaky <!-- evening-sync:recap:end --> escape"))


def test_rejects_bad_time_unknown_entity_and_unknown_keys(tmp_path):
    root = make_vault(tmp_path)
    bad_time = payload()
    bad_time["meetings"][0]["time"] = "9am"
    with pytest.raises(dailynote.DailyNoteError, match="HH:MM"):
        dailynote.write(root, bad_time)
    bad_entity = payload()
    bad_entity["meetings"][0]["entity"] = "ghost-corp"
    with pytest.raises(dailynote.DailyNoteError, match="dossier"):
        dailynote.write(root, bad_entity)
    with pytest.raises(dailynote.DailyNoteError, match="unknown payload key"):
        dailynote.write(root, payload(extra="nope"))
    with pytest.raises(dailynote.DailyNoteError):
        dailynote.write(root, payload(date="15-06-2026"))


def test_cli_write_envelope(tmp_path):
    root = make_vault(tmp_path)
    note_file = tmp_path / "payload.json"
    note_file.write_text(json.dumps(payload()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "daily-note", "write",
         "--vault", str(root), "--note", str(note_file)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["result"]["path"] == "60-daily-notes/2026-06-15.md"


def jotted_note_text() -> str:
    return """---
date: 2026-06-12
type: daily-note
---

# 2026-06-12 · Friday

## Recap
<!-- evening-sync:recap:begin -->
> [!info] At a glance
> recap content here
<!-- evening-sync:recap:end -->

## Meetings

### 10:00 — 1:1 — Jordan Vance · [[acme-industries]]
<!-- evening-sync:prep:begin -->
**Attendees:** Jordan Vance · **Context:** rollout proposal.
<!-- evening-sync:prep:end -->
- Proposal on track for September submission.
- 

## End of day
- Follow up with Dana next week.
"""


def test_read_extracts_regions_meetings_and_jottings(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        jotted_note_text(), encoding="utf-8")
    result = dailynote.read(root, "2026-06-12")
    assert result["exists"] is True
    assert result["frontmatter"]["type"] == "daily-note"
    assert result["recap"].startswith("> [!info] At a glance")
    assert len(result["meetings"]) == 1
    meeting = result["meetings"][0]
    assert meeting["time"] == "10:00"
    assert meeting["subject"] == "1:1 — Jordan Vance"
    assert meeting["entity"] == "acme-industries"
    assert meeting["prep"].startswith("**Attendees:** Jordan Vance")
    # The empty '- ' affordance is dropped; the real jotting survives.
    assert meeting["jottings"] == ["Proposal on track for September submission."]
    assert result["end_of_day"] == ["Follow up with Dana next week."]
    assert result["warnings"] == []


def test_read_returns_actions_written_outside_a_meeting(tmp_path):
    """#257: a task under ## Notes (or anywhere outside a meeting block) is an
    action too. The meeting's own actions stay where they were."""
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        "---\ndate: 2026-06-12\ntype: daily-note\n---\n\n"
        "## Meetings\n### 10:00 — Sync · [[acme-industries]]\n"
        "#### Your to do's\n- [ ] send the deck Friday\n- [x] book the room\n\n"
        "## Notes\n- a thought\n- [ ] call the bank\n- [x] pay the invoice\n"
        "- [ ] \n", encoding="utf-8")
    result = dailynote.read(root, "2026-06-12")
    assert result["meetings"][0]["actions"] == [
        {"text": "send the deck Friday", "done": False},
        {"text": "book the room", "done": True}]
    assert result["loose_actions"] == [
        {"text": "call the bank", "done": False},
        {"text": "pay the invoice", "done": True}]


def test_read_surfaces_the_no_meetings_prep_region(tmp_path):
    """A prep region with no meeting heading above it is the no-meetings line
    (or the calendar-unavailable note) — it comes back rather than vanishing."""
    root = make_vault(tmp_path)
    dailynote.write(root, payload(
        meetings=[], meetings_note="*Calendar unavailable — check Outlook.*"))
    result = dailynote.read(root, "2026-06-15")
    assert result["meetings"] == []
    assert result["meetings_note"] == "*Calendar unavailable — check Outlook.*"


def test_read_leaves_meetings_note_null_when_meetings_are_prepped(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    result = dailynote.read(root, "2026-06-15")
    assert len(result["meetings"]) == 2
    assert result["meetings_note"] is None


def test_read_warns_on_unparseable_frontmatter_and_keeps_going(tmp_path):
    """Frontmatter is the one part of a note a human may mangle without the
    region markers noticing. The harvest still needs the jottings, so the
    failure is a warning and frontmatter comes back empty."""
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        "---\ndate: 2026-06-12\nthis line has no colon\n---\n\n"
        "# 2026-06-12 · Friday\n\n## End of day\n- wrap up\n", encoding="utf-8")
    result = dailynote.read(root, "2026-06-12")
    assert result["exists"] is True
    assert result["frontmatter"] == {}
    assert result["warnings"] == [
        "60-daily-notes/2026-06-12.md: unparseable frontmatter line: "
        "'this line has no colon'"]
    assert result["end_of_day"] == ["wrap up"]


def test_read_on_a_missing_note_is_a_normal_state(tmp_path):
    root = make_vault(tmp_path)
    result = dailynote.read(root, "2026-06-12")
    assert result == {"exists": False, "path": "60-daily-notes/2026-06-12.md"}


def test_a_blank_note_obsidian_opened_is_written_over_and_read_as_missing(tmp_path):
    """#263: Obsidian opens today's note on startup and creates it, empty,
    when the evening run has not written it yet. That note is not a note: the
    catch-up run writes the real one over it, and a harvest reads it as absent."""
    root = make_vault(tmp_path)
    blank = root / "60-daily-notes" / "2026-06-15.md"
    blank.parent.mkdir(parents=True, exist_ok=True)
    blank.write_text("\n  \n", encoding="utf-8")
    assert dailynote.read(root, "2026-06-15") == {
        "exists": False, "path": "60-daily-notes/2026-06-15.md"}
    result = dailynote.write(root, payload())
    assert result["created"] is True
    assert blank.read_text(encoding="utf-8") == EXPECTED_FRESH


def test_a_vault_whose_meetings_table_still_says_triage_embeds_triage(tmp_path):
    """#263: until /upgrade-vault refreshes Meetings.base, its queue is still
    called Triage; embedding "To review" would show an error in its place."""
    root = make_vault(tmp_path)
    base = root / "20-meetings" / "Meetings.base"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text("views:\n  - type: table\n    name: Triage\n  - type: table\n    name: All Meetings\n",
                    encoding="utf-8")
    dailynote.write(root, payload())
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert dailynote.LEGACY_TRIAGE_EMBED in text.split("\n")
    assert "Meetings.base#To review" not in text
    assert text.replace(dailynote.LEGACY_TRIAGE_EMBED, "> ![[20-meetings/Meetings.base#To review]]") == EXPECTED_FRESH
    base.write_text(base.read_text(encoding="utf-8").replace("name: Triage", "name: To review"), encoding="utf-8")
    (root / "60-daily-notes" / "2026-06-15.md").unlink()
    dailynote.write(root, payload())
    assert (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8") == EXPECTED_FRESH


def test_a_daily_note_without_regions_is_still_merged_not_replaced(tmp_path):
    # A note that says it is a daily note but lost its regions is merged, so
    # it is refused rather than guessed at. (Owner-typed text with no
    # `type: daily-note` is wrapped instead — see the test at the end.)
    root = make_vault(tmp_path)
    note = root / "60-daily-notes" / "2026-06-15.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    original = "---\ndate: 2026-06-15\ntype: daily-note\n---\n- a thought I typed\n"
    note.write_text(original, encoding="utf-8")
    with pytest.raises(dailynote.DailyNoteError):
        dailynote.write(root, payload())
    assert note.read_text(encoding="utf-8") == original


def test_read_tolerates_a_hand_written_note_without_markers(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        "---\ndate: 2026-06-12\ntype: daily-note\n---\n\n"
        "# 2026-06-12 · Friday\n\n## Recap\n- hand recap line\n\n"
        "## Meetings\n\n## End of day\n- wrap up\n", encoding="utf-8")
    result = dailynote.read(root, "2026-06-12")
    assert result["recap"] is None
    assert result["meetings"] == []
    assert result["end_of_day"] == ["wrap up"]
    assert "hand recap line" in result["other_lines"]


def test_read_parses_every_daily_note_fixture():
    for path in sorted((FIXTURE_ROOT / "60-daily-notes").glob("*.md")):
        result = dailynote.read(FIXTURE_ROOT, path.stem)
        assert result["exists"] is True
        assert result["recap"], f"{path}: fixture recap region is empty"


def _fixture_daily_notes():
    return sorted((FIXTURE_ROOT / "60-daily-notes").glob("*.md"))


def test_only_the_newest_fixture_daily_note_is_v2():
    """The mix of contract versions in the fixture is deliberate, not drift.

    `plugin/CLAUDE.md`: a v2 payload merging into a v1 note replaces region
    interiors and never retro-fits the `#### Prep` / `#### Notes` /
    `#### Actions` sub-headings. So a demo vault where every note was v2
    would assert a migration the product does not perform — and would leave
    `dailynote.read`'s v1 path with no real artifact to parse. The newest
    note is what a demo opens on and what `obsidian_probe.surfaces()` tours,
    so that one is current; the days behind it are history, and a vault
    upgraded mid-life genuinely holds both shapes.

    Converting the older three is therefore a decision to take deliberately,
    not a tidy-up — which is what this assertion is here to force.
    """
    notes = _fixture_daily_notes()
    v2 = [p.stem for p in notes
          if dailynote.PREP_HEADING in p.read_text(encoding="utf-8")]
    assert v2 == [notes[-1].stem], (
        "exactly the newest daily-note fixture carries the v2 sub-headings; "
        f"found {v2} against a newest note of {notes[-1].stem}")


def test_read_returns_notes_and_actions_from_the_v2_fixture():
    """The reader's `notes[]`/`actions[]` split, against a real artifact.

    Every other test of it builds its own note, so nothing would notice if
    the fixture stopped exercising the tick states the vault owner actually
    types.
    """
    newest = _fixture_daily_notes()[-1]
    result = dailynote.read(FIXTURE_ROOT, newest.stem)
    meetings = result["meetings"]
    assert [len(m["notes"]) for m in meetings] == [2, 2, 1, 2, 0, 1]
    assert [len(m["actions"]) for m in meetings] == [1, 2, 1, 1, 0, 1]
    done = [a for m in meetings for a in m["actions"] if a["done"]]
    assert len(done) == 1, "one ticked action, so the done path has an artifact"
    assert len(result["end_of_day"]) == 3


def test_cli_read_envelope(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text(
        jotted_note_text(), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "daily-note", "read",
         "--vault", str(root), "--date", "2026-06-12"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["result"]["meetings"][0]["jottings"] == [
        "Proposal on track for September submission."]


import shutil


FRESH_FIXTURE_PAYLOAD = {
    "date": "2026-06-15",
    # A fully v2 payload: `recap` is a recap.validate() object (and
    # `recap_window` is mandatory with it, because the CLI composes the
    # glance's meeting count and window label itself rather than trusting
    # prose), and every `prep` is {attendees, last_meeting, context}. This is
    # what the product emits today, so it is what the newest fixture note —
    # the one `obsidian_probe.surfaces()` tours — has to be.
    "recap_window": {"from": "2026-06-12", "to": "2026-06-12"},
    "recap": {
        "glance": {
            "headlines": [
                {"label": "Decided",
                 "text": "Phase 1 site nomination handed to Nordbridge, around their ERP freeze"},
                {"label": "Needs your hand",
                 "text": "a duplicate recorder capture is still waiting in triage"},
                {"label": "Quiet",
                 "text": "no Meridian or CRM meeting fell in this window"},
            ],
            "entities": ["nordbridge-components"],
        },
        "themes": [
            {"headline": "Phase 1 site choice moves to Nordbridge",
             "body": "The proposal now asks Nordbridge to nominate the plant their ERP freeze can absorb first, rather than naming one for them — which unblocks the September submission without committing to a sequence nobody has validated.",
             "sources": [{"stem": "12-06-26-jordan-1on1", "label": "Jordan 1:1"}]},
            {"headline": "One conversation was captured twice",
             "body": "Friday's 1:1 arrived from both the recorder and the calendar adapter, so it is written twice; the second copy needs dispositioning in triage before it double-counts in the Nordbridge meeting log.",
             "sources": [{"stem": "12-06-26-jordan-1on1-v2", "label": "duplicate capture"}]},
        ],
        "pulse": [
            {"project": "nordbridge-regional-rollout-proposal", "signal": "green",
             "text": "Site nomination handed to Nordbridge; proposal drafting on track for the September submission."},
            {"project": "commercial-ops-crm-modernization", "signal": "amber",
             "text": "Untouched this window — the scoring weights agreed at the dry run still need a governance answer on stage definitions."},
            {"project": "meridian-yard-automation-program", "signal": "quiet",
             "text": "Nothing moved; the revised commissioning schedule is still owed."},
        ],
        "decisions": ["2026-06-12-phase-1-site-nomination-deferred"],
        "watch": [
            "The duplicate Jordan capture is still in triage; until it is dispositioned the Nordbridge meeting log double-counts Friday.",
        ],
        "carried_forward": [
            "Follow up with Dana Whitfield on rollout scope this week.",
        ],
        "sync_notes": [
            "1 duplicate recorder capture written as a `-v2` sibling rather than merged — needs an interactive call in triage.",
        ],
    },
    "meetings": [
        {
            "time": "08:30",
            "subject": "Commercial Operations — Monday Forecast Call",
            "entity": "commercial-operations",
            "prep": {
                "attendees": "Sam Okafor, Taylor Brooks",
                "last_meeting": "[[05-06-26-pipeline-governance-review|2026-06-05 — pipeline governance review; cadence held at monthly]]",
                "context": "[[commercial-ops-pipeline-governance]] · first forecast call since the governance review; regional stage definitions still diverge.",
            },
        },
        {
            "time": "10:00",
            "subject": "Meridian Freight — Yard 2 Re-scope Working Session",
            "entity": "meridian-freight-holdings",
            "prep": {
                "attendees": "Priya Nathan, Renee Castillo",
                "last_meeting": "[[20-05-26-meridian-vendor-strategy-brainstorm|2026-05-20 — vendor strategy brainstorm; single-vendor consolidation adopted]]",
                "context": "[[meridian-yard-automation-program]] · revised commissioning schedule for yards 2–3 owed to Leo Marchetti; Renee was not in the room when consolidation was agreed.",
            },
        },
        {
            "time": "11:30",
            "subject": "1:1 — Taylor Brooks",
            "entity": "commercial-operations",
            "prep": {
                "attendees": "Taylor Brooks",
                "last_meeting": "[[05-06-26-pipeline-governance-review|2026-06-05 — pipeline governance review]]",
                "context": "[[commercial-ops-pipeline-governance]] · quarterly board pack outline due end of month; Taylor owns the draft.",
            },
        },
        {
            "time": "13:00",
            "subject": "CRM Modernization — RFP Scoring Dry Run",
            "entity": "commercial-operations",
            "prep": {
                "attendees": "Sam Okafor, Omar Siddiqui",
                "last_meeting": "[[01-06-26-commercial-ops-status-update|2026-06-01 — weekly status update; shortlist approved, phased migration adopted]]",
                "context": "[[commercial-ops-crm-modernization]] · scoring criteria draft was owed Friday; vendor selection target 2026-08-30.",
            },
        },
        {
            "time": "15:00",
            "subject": "Nordbridge — Proposal Working Session",
            "entity": "nordbridge-components",
            "prep": {
                "attendees": "Jordan Vance",
                "last_meeting": "[[12-06-26-jordan-1on1|2026-06-12 — 1:1; site nomination deferred to Nordbridge]]",
                "context": "[[nordbridge-regional-rollout-proposal]] · September submission; Friday's duplicate capture still in triage.",
            },
        },
        {
            "time": "16:30",
            "subject": "Exec Leadership Weekly",
            "entity": "commercial-operations",
            # The one meeting that takes both of the prep contract's fallback
            # branches: no note on file for a standing exec weekly, and no
            # single project it belongs to. A demo vault where every prep has
            # a tidy link on every field would hide what the skill actually
            # writes when the lookups come back empty.
            "prep": {
                "attendees": "Taylor Brooks, Sam Okafor, Priya Nathan",
                "last_meeting": "none on file",
                "context": "No tracked project. Standing agenda; Meridian's renewal cycle expected to surface before the September commercial review.",
            },
        },
    ],
}


def test_fresh_fixture_is_exactly_what_daily_note_write_renders(tmp_path):
    """60-daily-notes/2026-06-15.md is the just-written artifact of the
    2026-06-12 evening run — structure (headings, markers, section order) and
    all machine-generated content must match the renderer byte-for-byte. Only
    the vault owner's own bullets (under `#### Notes`, `#### Actions` and
    `## Notes`) are permitted to differ, since those are not generated
    by the renderer."""
    # The three headings the renderer hands to the vault owner with an empty
    # affordance under them and never writes into again. Everything else in
    # the note is machine-generated and must match byte-for-byte.
    jot_headings = {"#### notes", "#### actions", "#### your notes",
                    "#### your actions", "#### your to do's", "## notes", "## end of day"}

    def strip_hand_jottings(text: str) -> str:
        """Blank the vault owner's bullets, keeping every other byte.

        Under each of `jot_headings` the renderer emits exactly one empty
        affordance — `- ` for prose, `- [ ] ` for a task — and the fixture
        fills it in. So the first bullet in such a section is reduced to its
        own marker and the rest are dropped, which leaves the surrounding
        structure (headings, blank lines, markers) to be compared as written.
        Region interiors are never touched: those *are* machine content.
        """
        lines = text.split("\n")
        region_lines = set()
        for region in dailynote._find_regions(lines):
            region_lines.update(range(region["begin"], region["end"] + 1))

        output = []
        in_jot_section = False
        kept_affordance = False

        for index, line in enumerate(lines):
            if index in region_lines:
                output.append(line)
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                # Any heading ends the previous section — including the next
                # `### {HH:MM} — …`, so one meeting's Actions cannot swallow
                # the following meeting's Notes.
                in_jot_section = stripped.lower() in jot_headings
                kept_affordance = False
                output.append(line)
                continue
            if in_jot_section and stripped.startswith("- "):
                if kept_affordance:
                    continue
                kept_affordance = True
                indent = " " * (len(line) - len(line.lstrip()))
                marker = "- [ ] " if stripped.startswith("- [") else "- "
                output.append(indent + marker)
                continue
            output.append(line)

        return "\n".join(output)

    target = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, target)
    # The recap says "Still in Input" when 10-inbox/ holds files. The demo vault
    # ships unprocessed captures for the sync demo, but the fixture note is a day
    # the inbox was empty, so the copy renders against an emptied inbox.
    for stray in (target / "10-inbox").iterdir():
        if stray.is_file() and stray.name != "README.md":
            stray.unlink()
    fixture_path = target / "60-daily-notes" / "2026-06-15.md"
    fixture_text = fixture_path.read_text(encoding="utf-8")
    fixture_path.unlink()
    dailynote.write(target, dict(FRESH_FIXTURE_PAYLOAD))
    rendered = fixture_path.read_text(encoding="utf-8")

    # Compare fixture with jottings stripped against fresh render.
    # This verifies headings, markers, prep/recap content, and structure exactly.
    fixture_stripped = strip_hand_jottings(fixture_text)
    assert rendered == fixture_stripped, (
        "rendered output must match fixture structure and all machine-generated "
        "content (headings, markers, prep/recap content); hand-written jottings "
        "outside markers are the only exemption"
    )


def test_recap_fingerprint_ignores_line_endings(tmp_path):
    """The stamp must not fork on CRLF.

    It hashes the recap's input notes, and hashing raw bytes made a Windows
    host — or a Mac<->Windows synced vault — compute a different digest for
    byte-identical content. Since a mismatched stamp regenerates the region,
    that meant overwriting a recap the vault owner had already read on every
    single run. `provenance.digest` normalises CRLF to LF for exactly this
    reason and is the repo's stated convention for a vault-content hash.

    The Windows CI job caught it the first time a fixture carried a stamp at
    all (PR #206): macOS and Ubuntu agreed on 1f298595a5c7118b while Windows,
    whose checkout has core.autocrlf=true, computed ce0435975b22effb.
    """
    window = {"from": date(2026, 6, 12), "to": date(2026, 6, 12)}

    def fingerprint_of(crlf: bool) -> str:
        root = tmp_path / ("crlf" if crlf else "lf")
        shutil.copytree(FIXTURE_ROOT, root)
        if crlf:
            for path in root.rglob("*.md"):
                raw = path.read_bytes().replace(b"\r\n", b"\n")
                path.write_bytes(raw.replace(b"\n", b"\r\n"))
        return dailynote.recap_fingerprint(root, window)

    lf = fingerprint_of(False)
    assert fingerprint_of(True) == lf, (
        "the recap stamp changed with line endings — a CRLF checkout or a "
        "Windows host will regenerate the recap on every run")
    # Normalisation is a no-op on LF content, so the digest every already
    # stamped vault holds must be unchanged by this. Moved once on purpose in
    # #258: migration 008 adds a heading to every meeting note (the fixture
    # included), so each vault's recap regenerates once after that upgrade.
    # Moved again when the demo daily notes' `## End of day` became `## Notes`
    # (fixture text only; the hash code is unchanged, and real notes on disk
    # are never rewritten).
    assert lf == "80b7dd83162fce05", (
        f"the LF digest moved to {lf} — every stamped vault would regenerate "
        "its recap once. If that is intended, say so in the PR.")


def test_find_regions_reads_an_inputs_attribute():
    lines = [
        "<!-- evening-sync:recap:begin inputs=a1b2c3d4e5f6a7b8 -->",
        "recap prose",
        "<!-- evening-sync:recap:end -->",
    ]
    regions = dailynote._find_regions(lines)
    assert regions[0]["attrs"] == {"inputs": "a1b2c3d4e5f6a7b8"}


def test_find_regions_defaults_attrs_to_empty():
    lines = ["<!-- evening-sync:recap:begin -->", "x",
             "<!-- evening-sync:recap:end -->"]
    assert dailynote._find_regions(lines)[0]["attrs"] == {}


def test_find_regions_refuses_an_unknown_attribute():
    lines = ["<!-- evening-sync:recap:begin mode=terse -->", "x",
             "<!-- evening-sync:recap:end -->"]
    with pytest.raises(dailynote.DailyNoteError, match="mode"):
        dailynote._find_regions(lines)


def test_find_regions_refuses_an_attribute_on_an_end_marker():
    lines = ["<!-- evening-sync:recap:begin -->", "x",
             "<!-- evening-sync:recap:end inputs=a1b2c3d4e5f6a7b8 -->"]
    with pytest.raises(dailynote.DailyNoteError, match="inputs"):
        dailynote._find_regions(lines)


def test_find_regions_refuses_an_attribute_on_a_prep_region():
    lines = ["<!-- evening-sync:prep:begin inputs=a1b2c3d4e5f6a7b8 -->", "x",
             "<!-- evening-sync:prep:end -->"]
    with pytest.raises(dailynote.DailyNoteError, match="inputs"):
        dailynote._find_regions(lines)


def test_region_without_attrs_renders_exactly_as_before():
    assert dailynote._region("recap", "body") == (
        "<!-- evening-sync:recap:begin -->\nbody\n"
        "<!-- evening-sync:recap:end -->")


def test_region_with_attrs_renders_them_on_the_begin_marker():
    assert dailynote._region("recap", "body", {"inputs": "abc123"}) == (
        "<!-- evening-sync:recap:begin inputs=abc123 -->\nbody\n"
        "<!-- evening-sync:recap:end -->")


def test_marker_line_renders_one_line():
    assert dailynote._marker_line("recap", "begin", {"inputs": "abc123"}) == (
        "<!-- evening-sync:recap:begin inputs=abc123 -->")
    assert dailynote._marker_line("recap", "end") == (
        "<!-- evening-sync:recap:end -->")


def test_fresh_render_stamps_the_recap_inputs(tmp_path):
    root = make_windowed_vault(tmp_path)
    result = dailynote.write(root, windowed_payload())
    assert re.fullmatch(r"[0-9a-f]{16}", result["recap_inputs"])
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert f"<!-- evening-sync:recap:begin inputs={result['recap_inputs']} -->" in text


def test_second_write_over_unchanged_inputs_leaves_the_file_byte_identical(tmp_path):
    """The H2 repro: a re-run must not regenerate the recap with LLM variance."""
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    path = root / "60-daily-notes" / "2026-06-15.md"
    before = path.read_bytes()
    result = dailynote.write(root, windowed_payload(
        recap="> [!info] At a glance\n> synced from Teams transcript"))
    assert result["recap_skipped"] is True
    assert result["changed"] is False
    assert path.read_bytes() == before


def test_a_changed_meeting_inside_the_window_regenerates_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n\n"
        "## Key Takeaways\n- Shortlist approved.\n- TCO comparison owed.\n",
        encoding="utf-8")
    result = dailynote.write(root, windowed_payload(
        recap="> [!info] At a glance\n> 1 meeting · TCO comparison now owed"))
    assert result["recap_skipped"] is False
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "TCO comparison now owed" in text


def test_a_meeting_outside_the_window_does_not_invalidate_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    (root / "20-meetings" / "01-06-26-older-call.md").write_text(
        "---\ndate: 2026-06-01T09:00\ntype: status-update\n---\n",
        encoding="utf-8")
    assert dailynote.write(root, windowed_payload())["recap_skipped"] is True


def test_a_new_jotting_in_the_window_regenerates_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    note_path = root / "60-daily-notes" / "2026-06-12.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8") + "- Call Dana about scope.\n",
        encoding="utf-8")
    assert dailynote.write(root, windowed_payload())["recap_skipped"] is False


def test_a_decision_written_in_the_window_regenerates_the_recap(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    decisions = root / "30-projects" / "yard-automation" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "2026-06-12-phase-1-deferred.md").write_text(
        "---\ntype: decision\n---\n", encoding="utf-8")
    assert dailynote.write(root, windowed_payload())["recap_skipped"] is False


def test_prep_regions_still_merge_when_the_recap_is_skipped(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    updated = windowed_payload()
    updated["meetings"][0]["prep"] = "**Attendees:** Sam · **Context:** rescheduled."
    result = dailynote.write(root, updated)
    assert result["recap_skipped"] is True
    assert result["changed"] is True
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "**Context:** rescheduled." in text
    assert "Recap bullet one." in text          # the recap survived untouched


def test_a_write_without_a_window_strips_a_stale_stamp(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload())
    result = dailynote.write(root, payload(date="2026-06-15"))
    assert result["recap_inputs"] is None
    assert result["recap_skipped"] is False
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "<!-- evening-sync:recap:begin -->" in text
    assert "inputs=" not in text


def test_read_returns_the_recap_inputs(tmp_path):
    root = make_windowed_vault(tmp_path)
    written = dailynote.write(root, windowed_payload())
    assert dailynote.read(root, "2026-06-15")["recap_inputs"] == written["recap_inputs"]


def test_read_returns_a_null_recap_inputs_for_an_unstamped_note(tmp_path):
    root = make_vault(tmp_path)
    dailynote.write(root, payload())
    assert dailynote.read(root, "2026-06-15")["recap_inputs"] is None


def test_window_must_end_before_the_note_it_recaps(tmp_path):
    root = make_windowed_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="before the note"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-15"}))


def test_window_rejects_a_reversed_range_and_unknown_keys(tmp_path):
    root = make_windowed_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="after"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-10"}))
    with pytest.raises(dailynote.DailyNoteError, match="unknown key"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-12",
                          "until": "2026-06-12"}))
    with pytest.raises(dailynote.DailyNoteError, match="required"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12"}))


def test_no_banner_when_no_business_days_were_missed(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        recap_window={"from": "2026-06-12", "to": "2026-06-12"}))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "Catch-up note" not in text
    # The recap interior is exactly the payload's prose.
    assert ("<!-- evening-sync:recap:begin inputs=" in text
            and "-->\n> [!info] At a glance" in text)


def test_banner_states_the_window_and_the_no_back_fill_rule(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window={"from": "2026-06-15", "to": "2026-08-21"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert "> [!warning] Catch-up note" in text
    assert "Covers 2026-06-15 → 2026-08-21" in text
    assert "49 business days without an evening run" in text
    assert "not back-filled" in text
    assert "Detailed from" not in text


def test_banner_adds_the_detail_line_only_when_capped(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window={"from": "2026-06-15", "to": "2026-08-21",
                      "detailed_from": "2026-08-17"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert ("Detailed from 2026-08-17; the 45 earlier business days are "
            "counted, not recapped in detail.") in text


def test_banner_omits_the_detail_line_when_it_covers_the_whole_window(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window={"from": "2026-06-15", "to": "2026-08-21",
                      "detailed_from": "2026-06-15"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert "[!warning] Catch-up note" in text
    assert "Detailed from" not in text


def test_banner_is_singular_for_one_missed_day(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        recap_window={"from": "2026-06-12", "to": "2026-06-13",
                      "detailed_from": "2026-06-13"}))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "1 business day without an evening run" in text
    assert "the 1 earlier business day is counted" in text


def test_banner_sits_above_the_payload_prose_inside_the_region(tmp_path):
    root = make_windowed_vault(tmp_path)
    dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap="> [!info] At a glance\n> quiet stretch",
        recap_window={"from": "2026-06-15", "to": "2026-08-21"}))
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    region = text.split("<!-- evening-sync:recap:begin", 1)[1]
    region = region.split("-->", 1)[1].split("<!-- evening-sync:recap:end", 1)[0]
    assert region.strip().startswith("> [!warning] Catch-up note")
    assert region.strip().endswith("> quiet stretch")


def test_banner_renders_through_the_merge_path_too(tmp_path):
    """A banner wired into only _render (and not _merge) would drop silently
    on a re-run — the path a stale note actually takes. The first write here
    goes through _render (the note does not exist yet); the meeting note
    inside the window is then edited so the fingerprint changes, and the
    second write goes through _merge with the recap actually regenerated
    (not skipped) — the banner must still be there afterward.

    The window starts Wed 2026-06-10 so that one run really is missing:
    nbd(Wed 06-10) = Thu 06-11 is not on disk, while nbd(Thu 06-11) = Fri
    06-12 is (the vault's jottings note), so the count is 1."""
    root = make_windowed_vault(tmp_path)
    window = {"from": "2026-06-10", "to": "2026-06-12"}
    dailynote.write(root, windowed_payload(recap_window=dict(window)))
    (root / "20-meetings" / "12-06-26-weekly-status.md").write_text(
        "---\ndate: 2026-06-12T09:00\ntype: status-update\n---\n\n"
        "## Key Takeaways\n- Shortlist approved.\n- TCO comparison owed.\n",
        encoding="utf-8")
    result = dailynote.write(root, windowed_payload(
        recap="> [!info] At a glance\n> 1 meeting · TCO comparison now owed",
        recap_window=dict(window)))
    assert result["recap_skipped"] is False
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert "> [!warning] Catch-up note" in text
    assert "1 business day without an evening run" in text


def make_weekend_vault(tmp_path: Path) -> Path:
    """The Finding-1 repro as the write path sees it.

    A vault whose Friday 2026-08-21 has one meeting and one note with
    jottings. Friday's run writes 2026-08-24.md — and so does a Saturday or
    Sunday run, because the next business day is the same Monday.
    """
    root = make_vault(tmp_path)
    (root / "20-meetings").mkdir()
    (root / "20-meetings" / "21-08-26-weekly-status.md").write_text(
        "---\ndate: 2026-08-21T09:00\ntype: status-update\n---\n\n"
        "## Key Takeaways\n- Scoring criteria signed off.\n", encoding="utf-8")
    (root / "60-daily-notes" / "2026-08-21.md").write_text(
        "---\ndate: 2026-08-21\ntype: daily-note\n---\n\n"
        "## End of day\n- Chase the TCO comparison.\n", encoding="utf-8")
    return root


def weekend_payload(**overrides) -> dict:
    base = payload(date="2026-08-24")
    base.update(overrides)
    return base


def test_a_weekend_rerun_over_an_unchanged_vault_leaves_the_note_alone(tmp_path):
    """Finding 1 end to end. Friday's run writes Monday's note; the Saturday
    and Sunday runs see a window that has widened (08-21..08-22, then
    ..08-23) but not one changed input file. Hashing the raw bounds made both
    of those look changed and regenerated a recap the vault owner had already
    read, with LLM variance — two nights in seven."""
    root = make_weekend_vault(tmp_path)
    path = root / "60-daily-notes" / "2026-08-24.md"
    friday = dailynote.write(root, weekend_payload(
        recap_window={"from": "2026-08-21", "to": "2026-08-21"}))
    assert friday["created"] is True
    before = path.read_bytes()
    assert b"Catch-up note" not in before

    for last_day in ("2026-08-22", "2026-08-23"):
        result = dailynote.write(root, weekend_payload(
            recap=("> [!info] At a glance\n"
                   f"> a differently worded recap on {last_day}"),
            recap_window={"from": "2026-08-21", "to": last_day}))
        assert result["recap_skipped"] is True, last_day
        assert result["changed"] is False, last_day
        assert result["recap_inputs"] == friday["recap_inputs"], last_day
        assert path.read_bytes() == before, last_day
    # And the banner never appears on a weekend run over a healthy vault:
    # nbd(Fri 08-21) is this very note, so no run was missed.
    assert "Catch-up note" not in path.read_text(encoding="utf-8")


def test_a_missed_friday_still_banners_on_the_monday_run(tmp_path):
    """The other half of the same rule: the count follows the vault. Monday's
    note is absent, so Friday's run really did not happen, and the Monday
    run — writing Tuesday's note — says so."""
    root = make_weekend_vault(tmp_path)
    dailynote.write(root, weekend_payload(
        date="2026-08-25",
        recap_window={"from": "2026-08-21", "to": "2026-08-24"}))
    text = (root / "60-daily-notes" / "2026-08-25.md").read_text(encoding="utf-8")
    assert "> [!warning] Catch-up note" in text
    assert "1 business day without an evening run" in text


def test_changing_only_detailed_from_changes_the_digest(tmp_path):
    """`detailed_from` changes the rendered banner, so it has to change the
    digest. Under the old recipe it did not — a run that moved only its
    detail bound kept a stamp describing a banner the note no longer had."""
    root = make_windowed_vault(tmp_path)
    wide = {"from": "2026-06-15", "to": "2026-08-21"}
    first = dailynote.write(root, windowed_payload(
        date="2026-08-24", recap_window=dict(wide)))
    capped = dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window=dict(wide, detailed_from="2026-08-17")))
    assert capped["recap_skipped"] is False
    assert capped["recap_inputs"] != first["recap_inputs"]
    text = (root / "60-daily-notes" / "2026-08-24.md").read_text(encoding="utf-8")
    assert "Detailed from 2026-08-17" in text
    # Re-running the capped window is a no-op, as it must be.
    assert dailynote.write(root, windowed_payload(
        date="2026-08-24",
        recap_window=dict(wide, detailed_from="2026-08-17"),
    ))["recap_skipped"] is True


def test_a_recap_link_to_no_vault_object_is_refused(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError,
                       match="resolves to no vault object"):
        dailynote.write(root, payload(
            recap="- [[meridian-industrial-holdings]] wants a comparison."))


def test_links_to_every_object_kind_resolve(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(recap=(
        "- [[acme-industries]] · [[taylor-brooks]] · [[yard-automation]]\n"
        "- [[12-06-26-weekly-status]] · [[2026-06-12-phase-1-deferred]]")))
    assert result["created"] is True
    assert result["warnings"] == []


def test_an_entity_alias_that_contradicts_the_vault_is_refused(tmp_path):
    """The H2 name defect: a display name the model invented."""
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="called 'Acme'"):
        dailynote.write(root, payload(
            recap="- [[acme-industries|Acme Industrial Holdings]] escalated."))


def test_a_person_alias_that_contradicts_the_vault_is_refused(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="Taylor Brooks"):
        dailynote.write(root, payload(
            recap="- [[taylor-brooks|Tyler Brooks]] owns the draft."))


def test_a_project_alias_that_contradicts_the_vault_is_refused(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError,
                       match="Yard Automation Program"):
        dailynote.write(root, payload(
            recap="- [[yard-automation|Yard Automation Programme]] slipped."))


def test_an_identity_alias_that_matches_the_vault_is_accepted(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(
        recap="- [[taylor-brooks|Taylor Brooks]] owns the board pack draft."))
    assert result["created"] is True


def test_an_event_object_alias_is_free_prose(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(recap=(
        "- [[12-06-26-weekly-status|Friday's status call]] — shortlist "
        "approved.\n- [[2026-06-12-phase-1-deferred|the deferral]] is queued.")))
    assert result["created"] is True


def test_a_heading_anchor_is_stripped_before_resolution(tmp_path):
    root = make_linkable_vault(tmp_path)
    result = dailynote.write(root, payload(
        recap="- [[acme-industries#Sensitivities|Acme]] needs care."))
    assert result["created"] is True
    with pytest.raises(dailynote.DailyNoteError,
                       match="resolves to no vault object"):
        dailynote.write(root, payload(
            date="2026-06-16", recap="- [[nope#Context]] is nothing."))


def test_an_embed_is_checked_like_a_link(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError,
                       match="resolves to no vault object"):
        dailynote.write(root, payload(recap="- ![[not-a-thing]]"))


def test_links_in_prep_and_in_meetings_note_are_checked_too(tmp_path):
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="meeting 1 prep"):
        bad = payload()
        bad["meetings"][0]["prep"] = "**Context:** [[ghost-entity]] escalated."
        dailynote.write(root, bad)
    with pytest.raises(dailynote.DailyNoteError, match="meetings_note"):
        dailynote.write(root, payload(
            meetings=[], meetings_note="*Calendar down; see [[ghost-entity]].*"))


def test_an_unreadable_dossier_warns_instead_of_blocking_the_note(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "40-entities" / "acme-industries" / "dossier.md").write_text(
        "no frontmatter here\n", encoding="utf-8")
    result = dailynote.write(root, payload(
        recap="- [[acme-industries|Acme]] escalated."))
    assert result["created"] is True
    assert len(result["warnings"]) == 1
    assert "display name not verified" in result["warnings"][0]


def test_a_missing_display_name_warns_instead_of_blocking(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "50-people" / "taylor-brooks.md").write_text(
        "---\nslug: taylor-brooks\nrelationship: external\n---\n",
        encoding="utf-8")
    result = dailynote.write(root, payload(
        recap="- [[taylor-brooks|Taylor Brooks]] owns the draft."))
    assert result["created"] is True
    assert "person-name" in result["warnings"][0]


def test_two_bad_links_in_one_recap_are_reported_together(tmp_path):
    """Issue #78: raising on the first offender exhausts the single retry
    the skill allows, so a second independently-bad link in the same recap
    still means no note. One error must name every offender at once."""
    root = make_linkable_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError) as excinfo:
        dailynote.write(root, payload(
            recap=("- [[meridian-industrial-holdings]] wants a comparison.\n"
                  "- [[phantom-project]] is also mentioned.")))
    message = str(excinfo.value)
    assert "meridian-industrial-holdings" in message
    assert "phantom-project" in message


def test_bad_links_in_different_regions_are_reported_together(tmp_path):
    """Offenders in the recap and in a meeting's prep must land in the same
    error, each still carrying its own region label, so the retry can fix
    both without a second round trip."""
    root = make_linkable_vault(tmp_path)
    bad = payload(
        recap="- [[meridian-industrial-holdings]] wants a comparison.")
    bad["meetings"][0]["prep"] = "**Context:** [[ghost-entity]] escalated."
    with pytest.raises(dailynote.DailyNoteError) as excinfo:
        dailynote.write(root, bad)
    message = str(excinfo.value)
    assert "recap" in message
    assert "meridian-industrial-holdings" in message
    assert "meeting 1 prep" in message
    assert "ghost-entity" in message


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

> [!review] Waiting for you
> ![[20-meetings/Meetings.base#To review]]
>
> ![[30-projects/Decisions.base#To review]]

## Recap
<!-- evening-sync:recap:begin inputs={digest} -->
> [!glance] At a glance
> **1 meeting** Friday · 1 entity · 0 themes · 1 decision logged
> - **Moved:** Shortlist approved
> - **Touched:** [[40-entities/acme-industries/dossier|Acme]]

**Themes** — none this window.

**Project pulse**

🔴 needs your hand · 🟠 watch · 🟢 moving · ⚪ quiet

| | Project | What moved |
|:-:|---|---|
| 🟢 | [[30-projects/yard-automation/index\\|Yard Automation Program]] · [[40-entities/acme-industries/dossier\\|Acme]] | Shortlist approved. |

**Decisions logged**
- [[2026-06-12-phase-1-deferred|Phase 1 site nomination deferred]] · Yard Automation Program

> [!hot] Watch
> - nothing needs your hand this window

> [!sync]- Sync notes — 1 item
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

#### Your notes
- 

#### Your to do's
- [ ] 

### 14:00 — Deep dive — vendor scoring
#### Prep
<!-- evening-sync:prep:begin -->
**Attendees** — Omar
**Last meeting** — none on file
**Context** — first session
<!-- evening-sync:prep:end -->

#### Your notes
- 

#### Your to do's
- [ ] 

## Notes
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
    assert "#### Your notes" not in merged   # sub-headings are never retro-fitted


def test_read_splits_notes_and_actions_under_a_v2_meeting(tmp_path):
    root = v2_vault(tmp_path)
    dailynote.write(root, v2_payload())
    note = root / "60-daily-notes" / "2026-06-15.md"
    text = note.read_text(encoding="utf-8")
    filled = text.replace("#### Your notes\n- \n\n#### Your to do's\n- [ ] \n\n### 14:00",
                          "#### Your notes\n- shortlist looks final\n- Sam wants a demo\n\n"
                          "#### Your to do's\n- [ ] send the scoring sheet\n- [x] book the demo\n\n### 14:00")
    assert filled != text
    text = filled
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


def test_a_log_in_the_window_feeds_the_fingerprint(tmp_path):
    root = make_vault(tmp_path)
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-messages.md").write_text(
        "---\ntype: message-log\n---\n", encoding="utf-8")
    (root / "_messages" / "2026-09-01-messages.md").write_text(
        "---\ntype: message-log\n---\n", encoding="utf-8")
    names = [n for n, _ in dailynote._fingerprint_inputs(root, date(2026, 9, 30), date(2026, 9, 30))]
    assert "_messages/2026-09-30-messages.md" in names
    assert "_messages/2026-09-01-messages.md" not in names


def test_a_oddly_named_log_never_enters_the_fingerprint(tmp_path):
    root = make_vault(tmp_path)
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-backup-messages.md").write_text("x", encoding="utf-8")
    names = [n for n, _ in dailynote._fingerprint_inputs(root, date(2026, 9, 30), date(2026, 9, 30))]
    assert names == []


def test_review_block_is_not_read_as_the_owners_words(tmp_path):
    # #238: the embedded queues sit above the recap, where any other line
    # would land in other_lines and be fed back to the evening run.
    root = v2_vault(tmp_path)
    dailynote.write(root, v2_payload())
    data = dailynote.read(root, "2026-06-15")
    assert data["other_lines"] == []
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert text.index(dailynote.REVIEW_BLOCK) < text.index("## Recap")


def test_mail_and_teams_sits_under_at_a_glance_below_the_review_queues(tmp_path):
    # #249 on the #238 layout: the review queues stay on top; the feed's
    # block is the recap's second callout, before Themes and the meetings.
    root = v2_vault(tmp_path)
    recap_payload = dict(v2_payload()["recap"], messages={
        "items": [{"kind": "needs-you", "text": "Sam is waiting for your budget figures."}],
        "status": [], "decisions_to_confirm": 1, "keyword_proposal": None})
    dailynote.write(root, v2_payload(recap=recap_payload))
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert (text.index(dailynote.REVIEW_BLOCK) < text.index("At a glance")
            < text.index("> [!info] Mail and Teams") < text.index("Themes")
            < text.index("## Meetings"))
    assert "→ Decisions, To review" in text
    assert dailynote.read(root, "2026-06-15")["other_lines"] == []


def test_old_notes_headings_still_read_as_notes_and_actions(tmp_path):
    # Notes written before #238 say "#### Notes"/"#### Actions"; the reader
    # goes by position under the meeting, so they read the same.
    root = v2_vault(tmp_path)
    dailynote.write(root, v2_payload())
    note = root / "60-daily-notes" / "2026-06-15.md"
    text = note.read_text(encoding="utf-8").replace("#### Your notes\n- \n\n#### Your to do's\n- [ ] \n\n### 14:00",
                                                    "#### Notes\n- old style\n\n#### Actions\n- [ ] old task\n\n### 14:00")
    note.write_text(text, encoding="utf-8")
    first = dailynote.read(root, "2026-06-15")["meetings"][0]
    assert first["notes"] == ["old style"]
    assert first["actions"] == [{"text": "old task", "done": False}]


def test_read_takes_the_notes_heading_and_the_old_end_of_day_alike(tmp_path):
    root = make_vault(tmp_path)
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


def test_a_for_today_banner_counts_the_same_missed_runs_as_the_plan(tmp_path):
    # Review 2026-10-12: last note Monday, caught up Thursday morning. The
    # plan counts Mon, Tue and Wed evenings; the banner said 2.
    root = make_windowed_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-15.md").write_text(
        "---\ndate: 2026-06-15\ntype: daily-note\n---\n", encoding="utf-8")
    from vaultlib import dates
    plan = dates.plan(root, "2026-06-18", for_today=True)
    dailynote.write(root, windowed_payload(
        date="2026-06-18",
        recap_window={"from": plan["recap_from"], "to": plan["recap_to"],
                      "plan_for": plan["plan_for"]}))
    text = (root / "60-daily-notes" / "2026-06-18.md").read_text(encoding="utf-8")
    assert plan["business_days_missed"] == 3
    assert "3 business days without an evening run" in text


def test_plan_for_must_be_the_plans_own_value(tmp_path):
    root = make_windowed_vault(tmp_path)
    with pytest.raises(dailynote.DailyNoteError, match="plan_for"):
        dailynote.write(root, windowed_payload(
            recap_window={"from": "2026-06-12", "to": "2026-06-12", "plan_for": "tonight"}))


def test_a_vault_whose_decisions_table_still_says_needs_review_embeds_it(tmp_path):
    """Review 2026-10-12: a 0.12.x vault (La Lorraine) still calls its
    Decisions queue Needs review until its tables are refreshed."""
    root = make_vault(tmp_path)
    base = root / "30-projects" / "Decisions.base"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text("views:\n  - type: table\n    name: Needs review\n  - type: table\n    name: All\n",
                    encoding="utf-8")
    dailynote.write(root, payload())
    text = (root / "60-daily-notes" / "2026-06-15.md").read_text(encoding="utf-8")
    assert dailynote.LEGACY_DECISIONS_EMBED in text.split("\n")
    assert text.replace(dailynote.LEGACY_DECISIONS_EMBED,
                        "> ![[30-projects/Decisions.base#To review]]") == EXPECTED_FRESH
    # and the legacy line is the machine's, never read back as the owner's
    assert "Needs review" not in str(dailynote.read(root, "2026-06-15"))


def test_the_real_note_is_written_around_the_owners_typed_text(tmp_path):
    # Review 2026-10-12: the owner typed into the empty note Obsidian made;
    # the run used to refuse it ("expected exactly one recap region").
    root = make_vault(tmp_path)
    note = root / "60-daily-notes" / "2026-06-15.md"
    note.write_text("call Jan back\n- [ ] send the deck\n", encoding="utf-8")
    result = dailynote.write(root, payload())
    text = note.read_text(encoding="utf-8")
    assert result["created"] is True
    assert "type: daily-note" in text and "<!-- evening-sync:recap:begin" in text
    assert text.endswith("## Notes\ncall Jan back\n- [ ] send the deck\n")
    # and from now on it is an ordinary note: a re-run merges
    again = dailynote.write(root, payload())
    assert again["created"] is False
    assert "call Jan back" in note.read_text(encoding="utf-8")
