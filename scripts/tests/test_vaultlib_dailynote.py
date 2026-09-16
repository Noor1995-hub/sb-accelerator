"""daily-note write/read: the machine half of the daily-note contract.

The CLI owns the marker-region merge; bytes outside markers are untouchable
(design decision 10) — pinned here by exact byte comparisons.
"""
import json
import re
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
        "> 1 meeting Friday · Nordbridge Components · 1 decision queued · 1 duplicate capture flagged\n"
        "- [[12-06-26-jordan-1on1]] — proposal drafting on track for the September submission; Phase 1 site nomination handed to Nordbridge.\n"
        "- Decision logged: [[2026-06-12-phase-1-site-nomination-deferred]] — unattended capture, waiting in the review queue.\n"
        "- Duplicate recorder capture written as [[12-06-26-jordan-1on1-v2]] — needs attention in triage.\n"
        "- Jotting carried forward: follow up with Dana Whitfield on rollout scope this week."
    ),
    "meetings": [
        {
            "time": "08:30",
            "subject": "Commercial Operations — Monday Forecast Call",
            "entity": "commercial-operations",
            "prep": (
                "**Attendees:** Sam Okafor, Taylor Brooks · **Last meeting:** 2026-06-05 — pipeline governance review; cadence held at monthly · **Context:** first forecast call since the governance review; regional stage definitions still diverge."
            ),
        },
        {
            "time": "10:00",
            "subject": "Meridian Freight — Yard 2 Re-scope Working Session",
            "entity": "meridian-freight-holdings",
            "prep": (
                "**Attendees:** Priya Nathan, Renee Castillo · **Last meeting:** 2026-05-20 — vendor strategy brainstorm; single-vendor consolidation adopted · **Context:** revised commissioning schedule for yards 2–3 owed to Leo Marchetti; Renee was not in the room when consolidation was agreed."
            ),
        },
        {
            "time": "11:30",
            "subject": "1:1 — Taylor Brooks",
            "entity": "commercial-operations",
            "prep": (
                "**Attendees:** Taylor Brooks · **Last meeting:** 2026-06-05 — pipeline governance review · **Context:** quarterly board pack outline due end of month; Taylor owns the draft."
            ),
        },
        {
            "time": "13:00",
            "subject": "CRM Modernization — RFP Scoring Dry Run",
            "entity": "commercial-operations",
            "prep": (
                "**Attendees:** Sam Okafor, Omar Siddiqui · **Last meeting:** 2026-06-01 — weekly status update; shortlist approved, phased migration adopted · **Context:** scoring criteria draft was owed Friday; vendor selection target 2026-08-30."
            ),
        },
        {
            "time": "15:00",
            "subject": "Nordbridge — Proposal Working Session",
            "entity": "nordbridge-components",
            "prep": (
                "**Attendees:** Jordan Vance · **Last meeting:** 2026-06-12 — 1:1; site nomination deferred to Nordbridge · **Context:** September submission; Friday's duplicate capture still in triage."
            ),
        },
        {
            "time": "16:30",
            "subject": "Exec Leadership Weekly",
            "entity": "commercial-operations",
            "prep": (
                "**Attendees:** Taylor Brooks, Sam Okafor, Priya Nathan · **Last meeting:** none on record · **Context:** standing agenda; Meridian's renewal cycle expected to surface before the September commercial review."
            ),
        },
    ],
}


def test_fresh_fixture_is_exactly_what_daily_note_write_renders(tmp_path):
    """60-daily-notes/2026-06-15.md is the just-written artifact of the
    2026-06-12 evening run — structure (headings, markers, section order) and
    all machine-generated content must match the renderer byte-for-byte. Only
    hand-written jottings (bullets outside markers) and end-of-day notes are
    permitted to differ, since those are not generated by the renderer."""
    def strip_hand_jottings(text: str) -> str:
        """Replace hand-written jottings with a single empty bullet, preserving
        structure. Strips bullets after prep:end markers and in the End of day
        section, keeping only the first '- ' as empty. Reuses dailynote module's
        marker parsing for prep region identification."""
        lines = text.split("\n")
        regions = dailynote._find_regions(lines)
        prep_ends = {region["end"] for region in regions if region["name"] == "prep"}
        region_lines = set()
        for region in regions:
            region_lines.update(range(region["begin"], region["end"] + 1))

        output = []
        after_prep_end = False
        in_end_of_day = False
        found_bullet_in_section = False

        for i, line in enumerate(lines):
            # Track End of day section
            if line.strip() == "## End of day":
                in_end_of_day = True
                found_bullet_in_section = False
                output.append(line)
                continue

            # Check if this line immediately follows a prep:end marker
            if i - 1 in prep_ends:
                after_prep_end = True
                found_bullet_in_section = False

            # If we hit a non-bullet line, stop the "after prep end" tracking
            if (after_prep_end or in_end_of_day) and not line.strip().startswith("- "):
                after_prep_end = False

            # Inside marker region, preserve exactly
            if i in region_lines:
                output.append(line)
            # After prep:end or in End of day, handle bullets specially
            elif (after_prep_end or in_end_of_day) and line.strip().startswith("- "):
                if not found_bullet_in_section:
                    # First bullet in section, keep as empty
                    indent = len(line) - len(line.lstrip())
                    output.append(" " * indent + "- ")
                    found_bullet_in_section = True
                # else: skip subsequent bullets (jottings)
            else:
                # All other lines (headings, sections, region markers, etc.)
                output.append(line)

        return "\n".join(output)

    target = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, target)
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
