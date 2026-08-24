"""daily-note write/read: the machine half of the daily-note contract.

The CLI owns the marker-region merge; bytes outside markers are untouchable
(design decision 10) — pinned here by exact byte comparisons.
"""
import json
import subprocess
import sys
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


EXPECTED_FRESH = """---
date: 2026-06-15
type: daily-note
---

# 2026-06-15 · Monday

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

## End of day
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
    jotted = jotted.replace("## End of day\n- \n",
                            "## End of day\n- long day; Meridian steady\n")
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
    "recap": (
        "> [!info] At a glance\n"
        "> 1 meeting Friday · Nordbridge Components · 1 duplicate capture flagged\n"
        "- [[12-06-26-jordan-1on1]] — proposal drafting on track for September submission.\n"
        "- Duplicate recorder capture written as [[12-06-26-jordan-1on1-v2]] — needs attention in triage.\n"
        "- Jotting carried forward: follow up with Dana Whitfield on rollout scope this week."
    ),
    "meetings": [],
}


def test_fresh_fixture_is_exactly_what_daily_note_write_renders(tmp_path):
    """60-daily-notes/2026-06-15.md is the just-written artifact of the
    2026-06-12 evening run — pinned byte-for-byte to the renderer."""
    target = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, target)
    fixture_path = target / "60-daily-notes" / "2026-06-15.md"
    expected = fixture_path.read_text(encoding="utf-8")
    fixture_path.unlink()
    dailynote.write(target, dict(FRESH_FIXTURE_PAYLOAD))
    assert fixture_path.read_text(encoding="utf-8") == expected
