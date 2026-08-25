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
