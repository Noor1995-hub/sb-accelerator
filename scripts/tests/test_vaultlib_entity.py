"""Dossier creation and merges.

The hard rule under test throughout: never remove existing content. Everything
else is section-specific placement.
"""
import pytest

import re

from vaultlib import entity, markdown as md, schema

from test_vaultlib_vault import make_vault

TODAY = "2026-08-23"


def seeded(tmp_path, **kwargs):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="meridian-freight-holdings",
                  name="Meridian Freight Holdings", today=TODAY, **kwargs)
    return root


# --- ensure ---------------------------------------------------------------

def test_ensure_creates_a_conformant_dossier(tmp_path):
    root = seeded(tmp_path, entity_type="client", status="active")
    text = (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_text(
        encoding="utf-8")
    data, body = md.split_frontmatter(text)
    assert schema.validate("entity", data) == []
    assert data["slug"] == "meridian-freight-holdings"
    assert data["type"] == "entity"
    assert data["status"] == "active"
    assert [t for t, _ in md.split_sections(body) if t] == schema.body_sections("entity")


def test_ensure_slug_equals_the_folder_name(tmp_path):
    root = seeded(tmp_path)
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_text(
            encoding="utf-8"))
    assert data["slug"] == "meridian-freight-holdings"


def test_ensure_defaults_to_prospect(tmp_path):
    root = seeded(tmp_path)
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_text(
            encoding="utf-8"))
    assert data["status"] == "prospect"


def test_ensure_seeds_empty_sections_with_the_placeholder(tmp_path):
    root = seeded(tmp_path)
    sections = entity.read(root, "meridian-freight-holdings")["sections"]
    for title in ("Relationship History", "Meeting Log", "Sensitivities"):
        assert "*No entries yet.*" in sections[title]


def test_ensure_marks_generated_context_unvalidated(tmp_path):
    root = seeded(tmp_path)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert parsed["banner"] is True
    assert "Context" in parsed["unvalidated"]


def test_ensure_is_idempotent(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nhand edit\n",
                      encoding="utf-8")
    result = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-01")
    assert result["created"] is False
    assert "hand edit" in target.read_text(encoding="utf-8")


def test_ensure_rejects_an_off_enum_status(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(entity.EntityError, match="status"):
        entity.ensure(root, slug="x", name="X", today=TODAY, status="lapsed")


def test_ensure_rejects_a_malformed_slug(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="lowercase"):
        entity.ensure(root, slug="Bad Slug", name="X", today=TODAY)


def test_ensure_refuses_a_newline_in_the_display_name(tmp_path):
    # This used to return created: true and then fail every later read with
    # "unparseable frontmatter line" — the CLI bricking an object it created.
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="newline"):
        entity.ensure(root, slug="acme", name="Acme\nInc", today=TODAY)
    assert not (root / "40-entities" / "acme" / "dossier.md").exists()


def test_ensure_refuses_an_owner_that_is_not_a_person_slug(tmp_path):
    # owner is a slug join to 50-people/{slug}.md and was never validated, so
    # a display name emitted YAML that PyYAML rejects with a ScannerError.
    root = make_vault(tmp_path)
    with pytest.raises(entity.EntityError, match="person slug"):
        entity.ensure(root, slug="acme", name="Acme", today=TODAY,
                      owner="jordan: reyes")
    assert not (root / "40-entities" / "acme" / "dossier.md").exists()


# --- read -----------------------------------------------------------------

def test_read_raises_on_a_missing_dossier(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(entity.EntityError, match="no dossier"):
        entity.read(root, "nobody")


def test_read_returns_all_six_sections(tmp_path):
    root = seeded(tmp_path)
    assert list(entity.read(root, "meridian-freight-holdings")["sections"]) == \
        schema.body_sections("entity")


def test_read_refuses_a_dossier_with_a_duplicate_section_header(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    text = target.read_text(encoding="utf-8")
    corrupted = text.replace("## Stakeholders", "## Context", 1)
    target.write_text(corrupted, encoding="utf-8")
    with pytest.raises(entity.EntityError, match="Context"):
        entity.read(root, "meridian-freight-holdings")


# --- write: context -------------------------------------------------------

def test_context_bullet_is_appended(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "regional freight, three yards",
         "why": "sets the yard-automation scope"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert "**Industry:** regional freight, three yards — sets the yard-automation scope" in text


def test_context_bullet_with_a_matching_label_is_replaced_not_duplicated(tmp_path):
    root = seeded(tmp_path)
    for fact in ("1,200 staff", "1,400 staff"):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": "Size", "fact": fact, "why": "scale"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert text.count("**Size:**") == 1
    assert "1,400 staff" in text
    assert "1,200 staff" not in text


def test_context_over_the_cap_in_one_call_is_refused(tmp_path):
    root = seeded(tmp_path)
    edits = {"context": [{"label": f"L{i}", "fact": f"f{i}", "why": "w"}
                         for i in range(12)]}
    with pytest.raises(entity.EntityError, match="Consolidate"):
        entity.write(root, "meridian-freight-holdings", edits, TODAY)


def test_context_at_exactly_the_cap_succeeds(tmp_path):
    root = seeded(tmp_path)
    edits = {"context": [{"label": f"L{i}", "fact": f"f{i}", "why": "w"}
                         for i in range(8)]}
    entity.write(root, "meridian-freight-holdings", edits, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert len([line for line in text.splitlines() if line.startswith("- **")]) == 8


def test_context_bullets_written_across_calls_are_never_dropped_by_the_cap(tmp_path):
    root = seeded(tmp_path)
    for i in range(5):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": f"L{i}", "fact": f"f{i}", "why": "w"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": f"L{i}", "fact": f"f{i}", "why": "w"} for i in range(5, 8)]},
        TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    bullets = [line for line in text.splitlines() if line.startswith("- **")]
    assert len(bullets) == 8
    for i in range(8):
        assert f"L{i}" in text


# --- write: stakeholders --------------------------------------------------

def test_new_stakeholder_row_is_flagged_for_review(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO", "role": "sponsor",
         "stance": "champion", "notes": "direct, wants numbers"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert "Leo Marchetti" in text
    assert "<!-- needs-review -->" in text


def test_needs_review_marker_is_not_duplicated_when_notes_already_contain_it(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti",
         "notes": "already flagged <!-- needs-review -->"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    assert row.count("<!-- needs-review -->") == 1


def test_a_blank_stakeholder_name_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="name"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            {"name": "   ", "title": "COO"}]}, TODAY)


def test_existing_stakeholder_is_matched_case_insensitively(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "leo marchetti", "stance": "neutral"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert text.count("Marchetti") == 1
    assert "neutral" in text
    assert "COO" in text  # the earlier field survived


def test_a_wikilinked_stakeholder_matches_a_plain_display_name(tmp_path):
    # Dossiers carry `[[slug]]` in the Name column; the skill's documented
    # payload passes a display name. They must be the same person.
    root = seeded(tmp_path)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    text = path.read_text(encoding="utf-8").replace(
        "| Name | Title | Role in Decision | Stance | Notes |\n"
        "|------|-------|------------------|--------|-------|",
        "| Name | Title | Role in Decision | Stance | Notes |\n"
        "|------|-------|------------------|--------|-------|\n"
        "| [[leo-marchetti]] | COO | sponsor | champion | established |",
    )
    path.write_text(text, encoding="utf-8")

    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "stance": "neutral"}]}, TODAY)

    section = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    rows = [line for line in section.splitlines()
            if line.startswith("|") and "archetti" in line]
    assert len(rows) == 1, f"duplicate stakeholder row: {rows}"
    assert "[[leo-marchetti]]" in rows[0], "the existing cell format was rewritten"
    assert "neutral" in rows[0]
    assert "established" in rows[0], "an existing note was lost"
    assert "<!-- needs-review -->" not in rows[0]


@pytest.mark.parametrize("cell", [
    "[[leo-marchetti]]",
    "[[leo-marchetti|Leo Marchetti]]",
    r"[[leo-marchetti\|Leo Marchetti]]",   # as _cell() stores an aliased link
    "Leo Marchetti",
    "  Leo Marchetti  ",
])
def test_name_key_normalises_every_stored_form(cell):
    # A dossier may store a stakeholder as a plain name, a wikilink, or an
    # aliased wikilink whose pipe _cell() has escaped. All are one person.
    assert entity._name_key(cell) == "leo-marchetti"


def test_name_key_does_not_lean_on_slugify_to_strip_the_escape(monkeypatch):
    # Pins the mechanism, not just the outcome. _name_key must unescape the
    # pipe so the pattern captures a clean slug; if it does not, the stray
    # backslash only disappears because slugify discards non-alphanumerics.
    # Neutralise slugify and the difference becomes visible: without the
    # unescape this returns "leo-marchetti\\".
    monkeypatch.setattr(entity.naming, "slugify", lambda text, **kw: text)
    assert entity._name_key(r"[[leo-marchetti\|Leo Marchetti]]") == "leo-marchetti"


def test_the_wikilink_pattern_captures_a_bare_and_an_aliased_target():
    assert entity._WIKILINK_RE.match("[[leo-marchetti]]").group(1) == "leo-marchetti"
    assert entity._WIKILINK_RE.match(
        "[[leo-marchetti|Leo Marchetti]]").group(1) == "leo-marchetti"
    # The raw stored form is why the unescape above exists: the pattern cannot
    # see an escaped separator, so the capture picks up the backslash.
    assert entity._WIKILINK_RE.match(
        r"[[leo-marchetti\|Leo Marchetti]]").group(1) == "leo-marchetti\\"


def test_an_aliased_wikilink_also_matches(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "[[leo-marchetti|Leo Marchetti]]", "title": "COO"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "stance": "champion"}]}, TODAY)
    section = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    rows = [line for line in section.splitlines()
            if line.startswith("|") and "archetti" in line]
    assert len(rows) == 1, f"duplicate row: {rows}"


def test_blank_stakeholder_field_never_overwrites_a_filled_one(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": ""}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert "COO" in text


def test_stakeholder_rows_are_never_removed(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti"}, {"name": "Renee Castillo"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert "Renee Castillo" in text


def test_off_vocabulary_role_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="role"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            {"name": "X", "role": "kingmaker"}]}, TODAY)


def test_off_vocabulary_stance_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="stance"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            {"name": "X", "stance": "hostile"}]}, TODAY)


def test_a_notes_update_does_not_clear_the_needs_review_marker(tmp_path):
    # /update-entity Rule 4: leave the marker for a human. Replacing the Notes
    # cell used to carry the marker away with the text it replaced.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "wants a payback inside 18 months"}]},
        TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "signed off on the discovery budget"}]},
        TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    assert "signed off on the discovery budget" in row
    assert row.count("<!-- needs-review -->") == 1, (
        f"the marker was cleared on the user's behalf: {row}")


def test_a_marker_a_human_cleared_is_not_reinstated(tmp_path):
    # The other half of Rule 4: re-appending must only preserve a marker that
    # is still there, never resurrect one a human removed in Obsidian.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "wants numbers"}]}, TODAY)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(" <!-- needs-review -->", ""),
        encoding="utf-8")
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "wants numbers and a payback"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    assert "<!-- needs-review -->" not in row


def test_a_note_under_the_stakeholder_table_survives_a_write(tmp_path):
    # _parse_table used to collect only the lines BEFORE the table; anything
    # after it matched neither branch and was silently dropped.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Dana Whitfield", "title": "CFO"}]}, TODAY)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    note = "Note: Dana's assistant is Sam Okafor — route scheduling through him."
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "## Relationship History", f"{note}\n\n## Relationship History", 1),
        encoding="utf-8")

    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)

    section = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert note in section, "a human's note under the table was deleted"


def test_notes_above_and_below_the_table_both_survive_in_position(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Dana Whitfield", "title": "CFO"}]}, TODAY)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    above = "Owners: the commercial team maintains this table."
    below = "Note: route scheduling for Dana through Sam Okafor."
    text = path.read_text(encoding="utf-8")
    text = text.replace(entity.STAKEHOLDER_HEADER,
                        f"{above}\n\n{entity.STAKEHOLDER_HEADER}", 1)
    text = text.replace("## Relationship History",
                        f"{below}\n\n## Relationship History", 1)
    path.write_text(text, encoding="utf-8")

    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)

    section = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    assert above in section and below in section
    assert section.index(above) < section.index("| Name |") < section.index(below)
    assert "Leo Marchetti" in section


def test_a_pipe_in_a_field_cannot_break_the_table(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "says a | b"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    # An escaped pipe is still a "|" character, so count only UNescaped ones.
    assert len(re.findall(r"(?<!\\)\|", row)) == 6  # 5 columns => 6 delimiters
    assert r"says a \| b" in row


# --- write: relationship history & meeting log ---------------------------

def test_relationship_history_is_date_ordered(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-06-01", "what": "second", "significance": "b"},
        {"date": "2026-02-01", "what": "first", "significance": "a"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Relationship History"]
    assert text.index("first") < text.index("second")
    assert "*No entries yet.*" not in text


def test_relationship_history_keeps_prose_sub_bullets_and_comments(tmp_path):
    # The merge used to filter the section down to its `- **` bullets, which
    # deleted every other line a human had written in it.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-01-05", "what": "intro call",
         "significance": "opened the door"}]}, TODAY)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    lead = "Relationship owned by Morgan since the referral."
    sub = "  - Referrer was Jamie Ellwood at Nordbridge."
    trailing = "<!-- sourced from the 2026 referral thread -->"
    text = path.read_text(encoding="utf-8")
    text = text.replace("- **2026-01-05:**", f"{lead}\n\n- **2026-01-05:**", 1)
    text = text.replace("opened the door", f"opened the door\n{sub}\n{trailing}", 1)
    path.write_text(text, encoding="utf-8")

    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-03-01", "what": "steerco", "significance": "scope agreed"}]},
        TODAY)

    section = entity.read(
        root, "meridian-freight-holdings")["sections"]["Relationship History"]
    for kept in (lead, sub, trailing):
        assert kept in section, f"lost existing content: {kept!r}"
    # Lead-in above the entries, sub-bullet still under the entry it annotates,
    # the new entry sorted after it.
    assert section.index(lead) < section.index("intro call")
    assert section.index("intro call") < section.index(sub) < section.index("steerco")


def test_meeting_log_prepends_newest_first(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "attendees": "Leo",
         "outcomes": "scope agreed", "followups": "send plan",
         "dynamics": "warm"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-05-20", "topic": "Vendor strategy", "attendees": "Leo, Renee",
         "outcomes": "consolidate", "followups": "draft memo", "dynamics": "tense"}]},
        TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert text.index("Vendor strategy") < text.index("SteerCo 01")
    assert "*No entries yet.*" not in text


def test_meeting_log_entries_are_never_modified(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "outcomes": "scope agreed"}]},
        TODAY)
    before = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "outcomes": "different"}]},
        TODAY)
    after = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert "scope agreed" in after
    assert before.strip() in after


# --- write: sensitivities & engagements ---------------------------------

def test_sensitivity_with_a_matching_topic_is_updated(tmp_path):
    root = seeded(tmp_path)
    for detail in ("old detail", "new detail"):
        entity.write(root, "meridian-freight-holdings", {"sensitivities": [
            {"topic": "Incumbent vendor", "detail": detail,
             "implications": "tread carefully"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Sensitivities"]
    assert text.count("**Incumbent vendor:**") == 1
    assert "new detail" in text


def test_engagement_row_links_to_the_project_index(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "meridian-yard-automation-program", "status": "Active",
         "one_liner": "Three-yard rollout"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    assert "../../30-projects/meridian-yard-automation-program/index.md" in text


def test_engagement_row_is_updated_not_duplicated(tmp_path):
    root = seeded(tmp_path)
    for status in ("Active", "Completed"):
        entity.write(root, "meridian-freight-holdings", {"engagements": [
            {"project": "meridian-yard-automation-program", "status": status,
             "one_liner": "Three-yard rollout"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    # The slug appears twice per row (link text and href), so count ROWS.
    rows = [line for line in text.splitlines()
            if line.startswith("|") and "meridian-yard-automation-program" in line]
    assert len(rows) == 1
    assert "Completed" in rows[0]


def test_an_engagement_project_with_a_pipe_is_refused(tmp_path):
    # The Project cell is built as a raw markdown link and is the one cell
    # _cell() never sees, so an unescaped pipe used to destroy the Status and
    # One-liner cells on the next write.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match=re.escape("atlas | depot")):
        entity.write(root, "meridian-freight-holdings", {"engagements": [
            {"project": "atlas | depot", "status": "Active",
             "one_liner": "consolidation"}]}, TODAY)


def test_an_engagement_project_given_as_a_display_name_is_refused(tmp_path):
    # A display name links at 30-projects/Atlas Depot Consolidation/index.md,
    # which cannot exist, and appends a duplicate row beside the real one.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "atlas-depot-consolidation", "one_liner": "consolidation"}]},
        TODAY)
    with pytest.raises(entity.EntityError, match="project slug"):
        entity.write(root, "meridian-freight-holdings", {"engagements": [
            {"project": "Atlas Depot Consolidation"}]}, TODAY)
    section = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    assert len(rows) == 3, f"expected header, separator and one row: {rows}"


def test_engagement_slugs_with_a_shared_prefix_get_separate_rows(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "alpha-program-v2", "status": "Active",
         "one_liner": "v2 rollout"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "alpha-program", "status": "Active",
         "one_liner": "original rollout"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    rows = [line for line in text.splitlines() if line.startswith("|")]
    v2_rows = [row for row in rows if "[alpha-program-v2]" in row]
    base_rows = [row for row in rows if "[alpha-program]" in row]
    assert len(v2_rows) == 1
    assert len(base_rows) == 1
    assert "v2 rollout" in v2_rows[0]
    assert "original rollout" in base_rows[0]


# --- write: cross-cutting ------------------------------------------------

def test_a_newline_in_free_text_cannot_fabricate_a_section_header(tmp_path):
    # _cell() collapses newlines for table sections; free-text sections
    # (Context, Sensitivities, Relationship History, Meeting Log) need the
    # same protection via _text(), or an embedded "## Heading" fabricates a
    # section and read() would surface only the LAST section of that title.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "Incumbent vendor", "detail": "d\n## Stakeholders\ninjected",
         "implications": "tread carefully"}]}, TODAY)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert "Leo Marchetti" in parsed["sections"]["Stakeholders"]
    # The injected text is still present as literal words, but must never sit
    # at the start of its own line — that is what would fabricate a heading.
    sensitivities_lines = parsed["sections"]["Sensitivities"].splitlines()
    assert not any(line.startswith("## ") for line in sensitivities_lines)
    assert "injected" in parsed["sections"]["Sensitivities"]


def test_writing_a_section_clears_its_unvalidated_marker(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight", "why": "scope"}]}, TODAY)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert "Context" not in parsed["unvalidated"]
    assert parsed["banner"] is False


def test_last_updated_is_bumped_without_reordering_frontmatter(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    before = target.read_text(encoding="utf-8").split("---")[1].splitlines()
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "T", "detail": "d", "implications": "i"}]}, "2026-09-01")
    after = target.read_text(encoding="utf-8").split("---")[1].splitlines()
    assert [line.split(":")[0] for line in before if line.strip()] == \
           [line.split(":")[0] for line in after if line.strip()]
    assert "last-updated: 2026-09-01" in target.read_text(encoding="utf-8")


def test_write_reports_what_changed(tmp_path):
    root = seeded(tmp_path)
    result = entity.write(root, "meridian-freight-holdings", {
        "context": [{"label": "Industry", "fact": "freight", "why": "scope"}],
        "stakeholders": [{"name": "Leo Marchetti"}],
    }, TODAY)
    joined = " ".join(result["changes"])
    assert "Context" in joined and "Stakeholders" in joined


def test_an_empty_edit_payload_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="no edits"):
        entity.write(root, "meridian-freight-holdings", {}, TODAY)


def test_an_unknown_edit_key_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="invented"):
        entity.write(root, "meridian-freight-holdings",
                     {"invented": [{"a": 1}]}, TODAY)


@pytest.mark.parametrize("edits, expected", [
    ({"context": [{"label": "L", "fact": "f"}]}, "why"),
    ({"context": ["a plain string"]}, "got str"),
    ({"engagements": [{"status": "Active"}]}, "project"),
    ({"meeting_log": [{"topic": "only a topic"}]}, "date"),
    ({"sensitivities": [{"topic": "T", "detail": "d"}]}, "implications"),
    ({"relationship_history": [{"date": "2026-01-01", "what": "w"}]},
     "significance"),
    ({"stakeholders": [{"title": "COO"}]}, "name"),
    ({"context": {"label": "L", "fact": "f", "why": "w"}}, "must be a list"),
])
def test_a_malformed_edit_entry_raises_entity_error_not_key_or_type_error(
        tmp_path, edits, expected):
    # The mergers index required keys directly, so these used to surface as a
    # KeyError or TypeError traceback with no JSON envelope at all.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match=expected):
        entity.write(root, "meridian-freight-holdings", edits, TODAY)


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_required_field_is_refused_not_rendered_as_garbage(tmp_path, blank):
    # A whitespace-only label rendered "- **:**  — ". The strip in the shape
    # check catches it for every section with a required label-like field.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="label"):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": blank, "fact": "f", "why": "w"}]}, TODAY)


def test_an_escaped_pipe_survives_a_later_write(tmp_path):
    # _cell() escapes pipes on write; _parse_table must honour that escape on
    # the next write, or an unrelated edit silently truncates the cell.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO",
         "notes": "wants numbers | not narrative"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Renee Castillo", "title": "IT Director"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    assert "not narrative" in row, "the escaped-pipe cell was truncated"
    assert "<!-- needs-review -->" in row, "the review marker was lost"
    assert len(re.findall(r"(?<!\\)\|", row)) == 6


def test_repeated_writes_do_not_accumulate_escapes(tmp_path):
    # The pipe-bearing note is supplied ONCE and then never again, so it is
    # read back out of the file and re-rendered on each of the writes that
    # follow. Re-supplying the same value every round — as this test used to —
    # would overwrite the previous round's corruption with the correct value,
    # which made it structurally incapable of observing accumulation.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti", "notes": "a | b"}]}, TODAY)
    for title in ("COO", "Chief Operating Officer", "Group COO"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            {"name": "Leo Marchetti", "title": title}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Stakeholders"]
    row = [line for line in text.splitlines() if "Marchetti" in line][0]
    assert row.count("\\\\") == 0, f"backslashes accumulated: {row}"
    assert r"a \| b" in row
    assert "Group COO" in row


def test_write_uses_lf_endings(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "T", "detail": "d", "implications": "i"}]}, TODAY)
    raw = (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_bytes()
    assert b"\r\n" not in raw
