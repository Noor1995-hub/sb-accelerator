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


# --- ensure: updates on an existing dossier (#97) --------------------------

def test_ensure_applies_owner_to_an_existing_dossier(tmp_path):
    # The regression this closes: --owner on an existing entity used to be a
    # silent no-op that still returned created: false with no other signal.
    root = seeded(tmp_path)
    result = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-01",
                           owner="morgan-ellery")
    assert result["created"] is False
    assert result["changed"] is True
    assert result["updated"] == ["owner"]
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md")
        .read_text(encoding="utf-8"))
    assert data["owner"] == "morgan-ellery"
    assert data["last-updated"] == "2026-09-01"


def test_ensure_applies_multiple_provided_fields_at_once(tmp_path):
    root = seeded(tmp_path)
    result = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-01",
                           owner="morgan-ellery", status="active",
                           entity_type="client")
    assert result["changed"] is True
    assert sorted(result["updated"]) == ["entity-type", "owner", "status"]
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md")
        .read_text(encoding="utf-8"))
    assert data["owner"] == "morgan-ellery"
    assert data["status"] == "active"
    assert data["entity-type"] == "client"


def test_ensure_reports_changed_false_when_nothing_differs(tmp_path):
    root = seeded(tmp_path, status="active", owner="morgan-ellery")
    result = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-01",
                           owner="morgan-ellery", status="active")
    assert result["created"] is False
    assert result["changed"] is False
    assert result["updated"] == []


def test_ensure_omitted_fields_touch_nothing(tmp_path):
    # Absent flags must not be treated as "clear this field" — only fields the
    # caller actually passed are candidates for an update.
    root = seeded(tmp_path, status="active", owner="morgan-ellery",
                 entity_type="client")
    result = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-01")
    assert result["changed"] is False
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md")
        .read_text(encoding="utf-8"))
    assert data["owner"] == "morgan-ellery"
    assert data["status"] == "active"
    assert data["entity-type"] == "client"


def test_ensure_does_not_rewrite_the_file_when_nothing_changed(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    before = target.read_text(encoding="utf-8")
    entity.ensure(root, slug="meridian-freight-holdings",
                 name="Meridian Freight Holdings", today="2026-09-01")
    assert target.read_text(encoding="utf-8") == before


def test_ensure_update_does_not_touch_the_body(tmp_path):
    root = seeded(tmp_path)
    target = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nhand edit\n",
                      encoding="utf-8")
    entity.ensure(root, slug="meridian-freight-holdings",
                 name="Meridian Freight Holdings", today="2026-09-01",
                 owner="morgan-ellery")
    assert "hand edit" in target.read_text(encoding="utf-8")


def test_ensure_update_validates_the_resulting_frontmatter(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="status"):
        entity.ensure(root, slug="meridian-freight-holdings",
                     name="Meridian Freight Holdings", today=TODAY,
                     status="lapsed")
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md")
        .read_text(encoding="utf-8"))
    assert data["status"] == "prospect"


def test_ensure_update_still_validates_a_bad_owner_slug(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="person slug"):
        entity.ensure(root, slug="meridian-freight-holdings",
                     name="Meridian Freight Holdings", today=TODAY,
                     owner="jordan: reyes")


def test_ensure_is_idempotent_a_second_time_with_the_same_fields(tmp_path):
    root = seeded(tmp_path)
    entity.ensure(root, slug="meridian-freight-holdings",
                 name="Meridian Freight Holdings", today=TODAY,
                 owner="morgan-ellery")
    second = entity.ensure(root, slug="meridian-freight-holdings",
                           name="Meridian Freight Holdings", today="2026-09-02",
                           owner="morgan-ellery")
    assert second["changed"] is False
    assert second["updated"] == []


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
    assert len([line for line in text.splitlines()
                if line.startswith("> - **")]) == 8


def test_context_bullets_written_across_calls_are_never_dropped_by_the_cap(tmp_path):
    root = seeded(tmp_path)
    for i in range(5):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": f"L{i}", "fact": f"f{i}", "why": "w"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": f"L{i}", "fact": f"f{i}", "why": "w"} for i in range(5, 8)]},
        TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    bullets = [line for line in text.splitlines() if line.startswith("> - **")]
    assert len(bullets) == 8
    for i in range(8):
        assert f"L{i}" in text


# --- write: callout sections ---------------------------------------------

def test_a_fresh_dossier_titles_itself_with_the_entity_name(tmp_path):
    # Every dossier file is named dossier.md, so with no H1 the only title
    # Obsidian shows for the note is the word "dossier".
    root = seeded(tmp_path)
    body = (root / "40-entities" / "meridian-freight-holdings"
            / "dossier.md").read_text(encoding="utf-8").split("---\n", 2)[2]
    assert body.lstrip().startswith("# Meridian Freight Holdings")


@pytest.mark.parametrize("section, callout", [
    ("Context", entity.CONTEXT_CALLOUT),
    ("Sensitivities", entity.SENSITIVITIES_CALLOUT),
])
def test_a_fresh_dossier_opens_those_sections_as_callouts(tmp_path, section, callout):
    root = seeded(tmp_path)
    assert callout in entity.read(
        root, "meridian-freight-holdings")["sections"][section]


@pytest.mark.parametrize("edits, section, needle", [
    ({"context": [{"label": "Industry", "fact": "freight", "why": "scope"}]},
     "Context", "- **Industry:**"),
    ({"sensitivities": [{"topic": "Board pressure", "detail": "d",
                         "implications": "i"}]},
     "Sensitivities", "- **Board pressure:**"),
])
def test_a_new_bullet_lands_inside_the_callout(tmp_path, edits, section, needle):
    # The failure this guards: appended past the callout's last `>` line, the
    # bullet renders as loose text under the box rather than inside it. It
    # looks like a rendering bug and is really a write-path bug.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", edits, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"][section]
    line = [ln for ln in text.splitlines() if needle in ln][0]
    assert line.startswith("> "), f"bullet fell outside the callout: {line!r}"


def test_the_callout_placeholder_is_replaced_not_kept(tmp_path):
    # `> *No entries yet.*` only matches the placeholder once the `> ` is
    # stripped, so a prefix-blind strip leaves it above the first real bullet.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight", "why": "scope"}]}, TODAY)
    assert "*No entries yet.*" not in entity.read(
        root, "meridian-freight-holdings")["sections"]["Context"]


def test_a_matching_label_inside_a_callout_updates_rather_than_duplicates(tmp_path):
    root = seeded(tmp_path)
    for fact in ("three yards", "three yards, 240 trailers"):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": "Scale", "fact": fact, "why": "sizing"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert text.count("- **Scale:**") == 1
    assert "240 trailers" in text


def test_a_context_callout_unwrapped_by_hand_still_merges(tmp_path):
    # A human may delete the callout and leave plain bullets. The matcher keys
    # on the label after stripping any prefix, so both shapes keep working —
    # otherwise an unwrapped section silently appends duplicates forever.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Scale", "fact": "three yards", "why": "sizing"}]}, TODAY)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(entity.CONTEXT_CALLOUT + "\n", "")
                    .replace("> - **Scale:**", "- **Scale:**"), encoding="utf-8")
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Scale", "fact": "three yards, 240 trailers", "why": "sizing"}]},
        TODAY)
    section = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert section.count("- **Scale:**") == 1
    assert "240 trailers" in section


def test_the_context_cap_still_counts_bullets_inside_the_callout(tmp_path):
    # A prefix-blind count reads zero bullets, so the ceiling stops enforcing
    # and Context grows without limit — silently.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": f"L{i}", "fact": "f", "why": "w"} for i in range(8)]}, TODAY)
    with pytest.raises(entity.EntityError, match="Consolidate"):
        entity.write(root, "meridian-freight-holdings", {"context": [
            {"label": "L8", "fact": "f", "why": "w"}]}, TODAY)


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


def test_relationship_history_merge_is_a_fixed_point(tmp_path):
    # Merging nothing into already-rendered content must return it byte for
    # byte. The tail branch used to add a separator blank line the tail
    # already carried, so the gap grew by one line on every single write —
    # monotonic and unbounded, and only when trailing content was present,
    # which is exactly the case the preservation fix was added to protect.
    rendered = "\n- **2026-01-05:** intro call — opened the door\n\n<!-- note -->\n"
    once, _, _ = entity._merge_relationship_history(rendered, [])
    assert once == rendered, "merging zero entries changed the section"
    twice, _, _ = entity._merge_relationship_history(once, [])
    assert twice == once, "the merge is not a fixed point"


def test_repeated_writes_never_grow_the_gap_before_trailing_content(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-01-05", "what": "intro call",
         "significance": "opened the door"}]}, TODAY)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    note = "<!-- sourced from the 2026 referral thread -->"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "opened the door", f"opened the door\n{note}", 1),
        encoding="utf-8")

    seen = set()
    for index in range(6):
        entity.write(root, "meridian-freight-holdings", {"relationship_history": [
            {"date": "2026-03-01", "what": f"steerco {index}",
             "significance": "scope agreed"}]}, TODAY)
        section = entity.read(
            root, "meridian-freight-holdings")["sections"]["Relationship History"]
        assert note in section, "the trailing note was lost"
        assert "\n\n\n" not in section, (
            f"blank lines accumulated on write {index + 1}: {section!r}")
        seen.add(section.count("\n\n"))
    assert seen == {1}, f"the blank-run count drifted across writes: {sorted(seen)}"


def test_meeting_log_dynamics_are_newest_first(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01",
         "dynamics": "warm; Leo wanted a total"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-05-20", "topic": "Vendor strategy",
         "dynamics": "tense; Renee absent"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert text.index("Vendor strategy") < text.index("SteerCo 01")
    assert "*No entries yet.*" not in text


def test_meeting_log_keeps_its_dataview_index_byte_for_byte(tmp_path):
    # The table above ### Dynamics is a query, not content. A merge that
    # reflowed or dropped a line of it would empty the section in Obsidian
    # while every assertion about the bullets still passed.
    root = seeded(tmp_path)
    for date in ("2026-03-10", "2026-05-20"):
        entity.write(root, "meridian-freight-holdings", {"meeting_log": [
            {"date": date, "topic": "T", "dynamics": "d"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert entity.MEETING_LOG_QUERY in text
    assert text.index(entity.MEETING_LOG_QUERY) < text.index(entity.DYNAMICS_HEADING)


def test_meeting_log_entries_are_never_modified(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "dynamics": "scope agreed"}]},
        TODAY)
    before = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    entity.write(root, "meridian-freight-holdings", {"meeting_log": [
        {"date": "2026-03-10", "topic": "SteerCo 01", "dynamics": "different"}]},
        TODAY)
    after = entity.read(root, "meridian-freight-holdings")["sections"]["Meeting Log"]
    assert "scope agreed" in after
    assert before.strip() in after


def test_meeting_log_refuses_the_retired_narrative_fields(tmp_path):
    # Attendees/outcomes/follow-ups now live in the meeting note. Ignoring
    # them would return an ok envelope for content that was never written.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="outcomes belongs in"):
        entity.write(root, "meridian-freight-holdings", {"meeting_log": [
            {"date": "2026-03-10", "topic": "SteerCo 01", "dynamics": "warm",
             "outcomes": "scope agreed"}]}, TODAY)


def test_meeting_log_without_its_dynamics_heading_refuses_the_write(tmp_path):
    root = seeded(tmp_path)
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(entity.DYNAMICS_HEADING, "### Notes"),
        encoding="utf-8")
    with pytest.raises(entity.EntityError, match="Dynamics"):
        entity.write(root, "meridian-freight-holdings", {"meeting_log": [
            {"date": "2026-03-10", "topic": "SteerCo 01", "dynamics": "warm"}]},
            TODAY)


# --- write: sensitivities ---------------------------------

def test_sensitivity_with_a_matching_topic_is_updated(tmp_path):
    root = seeded(tmp_path)
    for detail in ("old detail", "new detail"):
        entity.write(root, "meridian-freight-holdings", {"sensitivities": [
            {"topic": "Incumbent vendor", "detail": detail,
             "implications": "tread carefully"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Sensitivities"]
    assert text.count("**Incumbent vendor:**") == 1
    assert "new detail" in text


# --- write: cross-cutting ------------------------------------------------

def test_a_newline_in_free_text_cannot_fabricate_a_section_header(tmp_path):
    # Free-text sections (Context, Sensitivities, Relationship History,
    # Meeting Log) need newline protection via _text(), or an embedded "## Heading" fabricates a
    # section and read() would surface only the LAST section of that title.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-01-05", "what": "intro call",
         "significance": "opened the door"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "Incumbent vendor",
         "detail": "d\n## Relationship History\ninjected",
         "implications": "tread carefully"}]}, TODAY)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert "intro call" in parsed["sections"]["Relationship History"]
    # The injected text is still present as literal words, but must never sit
    # at the start of its own line — that is what would fabricate a heading.
    sensitivities_lines = parsed["sections"]["Sensitivities"].splitlines()
    assert not any(line.startswith("## ") for line in sensitivities_lines)
    assert "injected" in parsed["sections"]["Sensitivities"]


def test_writing_a_section_clears_its_own_unvalidated_marker_but_not_the_banner(
        tmp_path):
    # Defect (#97): a Context write used to strip the whole-document banner as
    # a side effect, silently upgrading the dossier's trust status. The
    # section's own per-row marker is still consumed here — that half of the
    # behavior is correct and unchanged — but the banner now survives content
    # writes unconditionally; clearing it is a separate, explicit act
    # (entity.validate).
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight", "why": "scope"}]}, TODAY)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert "Context" not in parsed["unvalidated"]
    assert parsed["banner"] is True


def test_banner_survives_repeated_writes_across_sections(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight", "why": "scope"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"relationship_history": [
        {"date": "2026-01-05", "what": "intro call",
         "significance": "opened the door"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "T", "detail": "d", "implications": "i"}]}, TODAY)
    parsed = entity.read(root, "meridian-freight-holdings")
    assert parsed["banner"] is True


# --- validate: the explicit banner-clear act (#97) -------------------------

def test_validate_clears_the_banner(tmp_path):
    root = seeded(tmp_path)
    result = entity.validate(root, "meridian-freight-holdings", "2026-09-01")
    assert result["changed"] is True
    parsed = entity.read(root, "meridian-freight-holdings")
    assert parsed["banner"] is False


def test_validate_bumps_last_updated(tmp_path):
    root = seeded(tmp_path)
    entity.validate(root, "meridian-freight-holdings", "2026-09-01")
    data, _ = md.split_frontmatter(
        (root / "40-entities" / "meridian-freight-holdings" / "dossier.md")
        .read_text(encoding="utf-8"))
    assert data["last-updated"] == "2026-09-01"


def test_validate_is_idempotent(tmp_path):
    root = seeded(tmp_path)
    entity.validate(root, "meridian-freight-holdings", TODAY)
    result = entity.validate(root, "meridian-freight-holdings", "2026-09-01")
    assert result["changed"] is False
    parsed = entity.read(root, "meridian-freight-holdings")
    assert parsed["banner"] is False


def test_validate_does_not_touch_section_content(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight", "why": "scope"}]}, TODAY)
    entity.validate(root, "meridian-freight-holdings", "2026-09-01")
    parsed = entity.read(root, "meridian-freight-holdings")
    assert "freight" in parsed["sections"]["Context"]


def test_validate_raises_on_a_missing_dossier(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(entity.EntityError, match="no dossier"):
        entity.validate(root, "nobody", TODAY)


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
        "relationship_history": [{"date": "2026-01-05", "what": "intro call",
                                  "significance": "opened the door"}],
    }, TODAY)
    joined = " ".join(result["changes"])
    assert "Context" in joined and "Relationship History" in joined
    assert result["repairs"] == []


def test_an_empty_edit_payload_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="no edits"):
        entity.write(root, "meridian-freight-holdings", {}, TODAY)


def test_an_unknown_edit_key_is_refused(tmp_path):
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="invented"):
        entity.write(root, "meridian-freight-holdings",
                     {"invented": [{"a": 1}]}, TODAY)


def _drop_section(root, title):
    path = root / "40-entities" / "meridian-freight-holdings" / "dossier.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(rf"## {title}\n.*?(?=\n## |\Z)", "", text, flags=re.S),
                    encoding="utf-8")
    return path


def test_an_edit_for_a_missing_heading_is_refused(tmp_path):
    # The merge loop walks the sections the FILE has, so an edit key whose
    # heading a human deleted in Obsidian was never visited: no merge, no
    # changes entry, and an ok envelope over a write that did not happen.
    root = seeded(tmp_path)
    _drop_section(root, "Sensitivities")
    with pytest.raises(entity.EntityError, match=re.escape("## Sensitivities")):
        entity.write(root, "meridian-freight-holdings", {"sensitivities": [
            {"topic": "board pressure", "detail": "capex freeze through Q4",
             "implications": "do not open with the expansion case"}]}, TODAY)


def test_a_missing_heading_does_not_half_apply_the_rest(tmp_path):
    # The partial payload is the dangerous shape: one section lands, one goes
    # nowhere, and the envelope reads like an ordinary success. All or nothing.
    root = seeded(tmp_path)
    path = _drop_section(root, "Sensitivities")
    with pytest.raises(entity.EntityError):
        entity.write(root, "meridian-freight-holdings", {
            "sensitivities": [{"topic": "board pressure", "detail": "d",
                               "implications": "i"}],
            "context": [{"label": "Headquarters", "fact": "Rotterdam",
                         "why": "every site visit starts there"}]}, TODAY)
    assert "Rotterdam" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("edits, expected", [
    ({"context": [{"label": "L", "fact": "f"}]}, "why"),
    ({"context": ["a plain string"]}, "got str"),
    ({"sensitivities": [{"detail": "d", "implications": "i"}]}, "topic"),
    ({"meeting_log": [{"topic": "only a topic", "dynamics": "d"}]}, "date"),
    ({"meeting_log": [{"date": "2026-01-01", "topic": "T"}]}, "dynamics"),
    ({"sensitivities": [{"topic": "T", "detail": "d"}]}, "implications"),
    ({"relationship_history": [{"date": "2026-01-01", "what": "w"}]},
     "significance"),
    ({"context": [{"fact": "f", "why": "w"}]}, "label"),
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


def test_write_uses_lf_endings(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"sensitivities": [
        {"topic": "T", "detail": "d", "implications": "i"}]}, TODAY)
    raw = (root / "40-entities" / "meridian-freight-holdings" / "dossier.md").read_bytes()
    assert b"\r\n" not in raw


# --- repair: hand-edited file content (#40, #41) ---------------------------
#
# The policy these pin: hand-edited FILE content is repaired — never lost,
# never blocking a write — and every repair is reported. The refusal tests
# further down pin the other half: an off-shape model PAYLOAD is refused loudly.

SLUG = "meridian-freight-holdings"


def _dossier(root):
    return root / "40-entities" / SLUG / "dossier.md"


def _hand_edit(root, old, new):
    """Simulate a human editing the dossier in Obsidian."""
    path = _dossier(root)
    text = path.read_text(encoding="utf-8")
    assert old in text, f"the fixture no longer contains {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_indented_line_after_tail_content_stays_in_the_tail(tmp_path):
    # _merge_dated_bullets sent every indented non-blank line to blocks[-1],
    # even once the loop had moved past the entries into trailing content — so
    # the line was reattributed to the last dated entry instead of staying put.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"relationship_history": [
        {"date": "2026-01-05", "what": "intro call",
         "significance": "opened the door"}]}, TODAY)
    comment = "<!-- sourced from the referral thread -->"
    remark = "  - Morgan owns the relationship from here."
    _hand_edit(root, "opened the door", f"opened the door\n{comment}\n{remark}")

    entity.write(root, SLUG, {"relationship_history": [
        {"date": "2026-03-01", "what": "steerco",
         "significance": "scope agreed"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Relationship History"]
    for kept in (comment, remark):
        assert kept in section, f"lost existing content: {kept!r}"
    assert section.index(comment) < section.index(remark), (
        "the indented remark was pulled back under a dated entry")


# --- refuse: off-shape model payloads (#41) --------------------------------

def test_unknown_entry_field_is_refused_naming_the_field(tmp_path):
    # An unknown key used to be dropped silently with ok: true, so the model
    # had no way to learn it had guessed the shape wrong.
    root = seeded(tmp_path)
    for pattern in ("whyy", "'why'"):
        with pytest.raises(entity.EntityError, match=pattern):
            entity.write(root, SLUG, {"context": [
                {"label": "L", "fact": "f", "why": "w", "whyy": "x"}]}, TODAY)


def test_non_string_entry_value_is_refused_not_reprd(tmp_path):
    # _text() str()s whatever it is handed, so a list landed in the note as
    # its Python repr — a corrupt-looking note reported as a success.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="must be a string"):
        entity.write(root, SLUG, {"relationship_history": [
            {"date": "2026-01-05", "what": ["a", "b"],
             "significance": "opened the door"}]}, TODAY)
    assert "['a', 'b']" not in _dossier(root).read_text(encoding="utf-8")


@pytest.mark.parametrize("edit_key, rest", [
    ("relationship_history", {"what": "w", "significance": "s"}),
    ("meeting_log", {"topic": "t", "dynamics": "d"}),
])
@pytest.mark.parametrize("bad_date", ["21-08-2026", "2026-13-40",
                                      "sometime in June"])
def test_invalid_date_is_refused_on_dated_sections(tmp_path, edit_key, rest,
                                                   bad_date):
    # _date_key sorts on a fixed slice of the rendered bullet, so a date that
    # is not YYYY-MM-DD sorted into an arbitrary position and stayed there.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="YYYY-MM-DD"):
        entity.write(root, SLUG, {edit_key: [dict(rest, date=bad_date)]}, TODAY)


def test_read_returns_human_added_sections(tmp_path):
    # Both skills read before writing, so a section read() cannot see makes
    # the model plan against a partial picture of the dossier.
    root = seeded(tmp_path)
    path = _dossier(root)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n## Procurement Notes\n\nFramework agreement renews in March.\n",
        encoding="utf-8")

    parsed = entity.read(root, SLUG)

    assert "Procurement Notes" in parsed["extra_sections"]
    assert "Framework agreement" in parsed["extra_sections"]["Procurement Notes"]
    assert list(parsed["sections"]) == schema.body_sections("entity")
    assert "Procurement Notes" not in parsed["sections"]


def test_second_identical_write_is_byte_identical(tmp_path):
    # A spacing guard across the bullet mergers together: the
    # rendered file is a fixed point of re-applying the same payload, so no
    # write drifts the blank-line layout of a section it did not change.
    root = seeded(tmp_path)
    edits = {
        "context": [{"label": "Fleet", "fact": "three yards",
                     "why": "sets the automation scope"}],
        "sensitivities": [{"topic": "Incumbent integrator", "detail": "d",
                           "implications": "i"}],
    }
    entity.write(root, SLUG, edits, TODAY)
    first = _dossier(root).read_bytes()
    entity.write(root, SLUG, edits, TODAY)
    assert _dossier(root).read_bytes() == first


# --- #253: teams and departments as a level under an entity ----------------

def two_entities(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme Industries", today="2026-10-02",
                  entity_type="client")
    return root


def dossier(root, slug):
    return (root / "40-entities" / slug / "dossier.md").read_text(encoding="utf-8")


def test_a_team_is_created_under_its_entity(tmp_path):
    root = two_entities(tmp_path)
    result = entity.ensure(root, slug="acme-finance", name="Finance", today="2026-10-02",
                           entity_type="business-unit", parent="acme")
    assert result["created"] is True
    fm, body = md.split_frontmatter(dossier(root, "acme-finance"))
    assert fm["parent"] == "acme"
    assert not schema.validate("entity", fm)
    assert "**Part of** [[40-entities/acme/dossier|Acme Industries]]" in body
    assert body.index("# Finance") < body.index("**Part of**") < body.index("## Context")
    # the parent learns about its teams once, through live queries
    parent = dossier(root, "acme")
    assert parent.count("## Teams") == 1
    assert "WHERE parent = this.slug" in parent
    entity.ensure(root, slug="acme-legal", name="Legal", today="2026-10-02", parent="acme")
    assert dossier(root, "acme").count("## Teams") == 1


def test_teams_section_survives_a_dossier_write(tmp_path):
    root = two_entities(tmp_path)
    entity.ensure(root, slug="acme-finance", name="Finance", today="2026-10-02", parent="acme")
    entity.write(root, "acme", {"sensitivities": [
        {"topic": "Budget", "detail": "Tight this year", "implications": "Keep scope small"}]},
        "2026-10-03")
    assert "## Teams" in dossier(root, "acme")
    assert "Teams" in entity.read(root, "acme")["extra_sections"]


@pytest.mark.parametrize("parent, message", [
    ("nobody", "no dossier"),
    ("acme-finance", "itself a team"),
    ("acme-legal", "own parent"),
])
def test_a_bad_parent_is_refused(tmp_path, parent, message):
    root = two_entities(tmp_path)
    entity.ensure(root, slug="acme-finance", name="Finance", today="2026-10-02", parent="acme")
    with pytest.raises(entity.EntityError, match=message):
        entity.ensure(root, slug="acme-legal", name="Legal", today="2026-10-02", parent=parent)
    assert not (root / "40-entities" / "acme-legal").exists() or parent == "acme-legal"


def test_an_existing_entity_can_be_attached_as_a_team(tmp_path):
    root = two_entities(tmp_path)
    entity.ensure(root, slug="finance-dept", name="Finance", today="2026-10-02")
    result = entity.ensure(root, slug="finance-dept", name="Finance", today="2026-10-03", parent="acme")
    assert "parent" in result["updated"]
    fm, body = md.split_frontmatter(dossier(root, "finance-dept"))
    assert fm["parent"] == "acme" and "**Part of** [[40-entities/acme/dossier|Acme Industries]]" in body
    assert "## Teams" in dossier(root, "acme")
    # attaching again changes nothing
    again = entity.ensure(root, slug="finance-dept", name="Finance", today="2026-10-04", parent="acme")
    assert again["changed"] is False


def test_an_entity_with_teams_cannot_become_a_team(tmp_path):
    root = two_entities(tmp_path)
    entity.ensure(root, slug="acme-finance", name="Finance", today="2026-10-02", parent="acme")
    entity.ensure(root, slug="holding", name="Holding", today="2026-10-02")
    with pytest.raises(entity.EntityError, match="has teams of its own"):
        entity.ensure(root, slug="acme", name="Acme Industries", today="2026-10-02", parent="holding")


def test_a_new_dossier_carries_the_live_sections(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    body = (root / "40-entities/acme/dossier.md").read_text(encoding="utf-8")
    assert entity.STAKEHOLDERS_QUERY in body and entity.ENGAGEMENTS_QUERY in body
    assert "| Name | Title |" not in body and "| Project | Status | One-liner |" not in body


def test_writing_stakeholders_or_engagements_is_refused_with_a_pointer(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    with pytest.raises(entity.EntityError, match="person set"):
        entity.write(root, "acme", {"stakeholders": [{"name": "Jan"}]}, "2026-10-12")
    with pytest.raises(entity.EntityError, match="live list"):
        entity.write(root, "acme", {"engagements": [{"project": "x"}]}, "2026-10-12")


def test_the_teams_section_no_longer_lists_projects():
    assert 'FROM "30-projects"' not in entity.TEAMS_SECTION


def test_read_returns_the_live_queries_as_raw_text(tmp_path):
    root = seeded(tmp_path)
    sections = entity.read(root, SLUG)["sections"]
    assert entity.STAKEHOLDERS_QUERY in sections["Stakeholders"]
    assert entity.ENGAGEMENTS_QUERY in sections["Engagements"]



def test_touch_stamps_entity_updated_and_nothing_else(tmp_path):
    """#273 piece 3: the automatic update marks what it has read."""
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    path = root / "40-entities/acme/dossier.md"
    before = path.read_text(encoding="utf-8")
    result = entity.touch(root, "acme", timestamp="2026-10-12T21:05")
    after = path.read_text(encoding="utf-8")
    assert result["entity-updated"] == "2026-10-12T21:05" and result["changed"]
    assert after.replace("entity-updated: 2026-10-12T21:05\n", "") == before


def test_touch_refuses_a_bad_timestamp_and_defaults_to_now(tmp_path):
    root = make_vault(tmp_path)
    entity.ensure(root, slug="acme", name="Acme", today="2026-10-12")
    with pytest.raises(entity.EntityError):
        entity.touch(root, "acme", timestamp="12/10 21h")
    stamped = entity.touch(root, "acme")["entity-updated"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", stamped)


# --- #273 final review: an automatic write never overwrites the owner ------

def test_automatic_write_cannot_replace_an_owner_bullet(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Size", "fact": "1,200 staff", "why": "scale"}],
        "sensitivities": [{"topic": "Union", "detail": "strike in 2024",
                           "implications": "avoid headcount talk"}]}, TODAY)
    result = entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Size", "fact": "1,400 staff", "why": "scale (meeting · [[12-10-26-steerco]])"}],
        "sensitivities": [{"topic": "Union", "detail": "calm now",
                           "implications": "fine (mail · [[_messages/2026-10-12-messages|12 Oct]])"}]},
        TODAY, automatic=True)
    sections = entity.read(root, "meridian-freight-holdings")["sections"]
    assert "1,200 staff" in sections["Context"] and "1,400 staff" not in sections["Context"]
    assert "strike in 2024" in sections["Sensitivities"] and "calm now" not in sections["Sensitivities"]
    assert len(result["skipped"]) == 2
    assert any("Size" in s for s in result["skipped"]) and any("Union" in s for s in result["skipped"])


def test_automatic_write_can_replace_an_automatic_bullet(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Size", "fact": "1,200 staff",
         "why": "scale (meeting · [[01-10-26-kickoff]])"}]}, TODAY, automatic=True)
    result = entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Size", "fact": "1,400 staff",
         "why": "scale (meeting · [[01-10-26-kickoff]]) (meeting · [[12-10-26-steerco]])"}]},
        TODAY, automatic=True)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Context"]
    assert text.count("**Size:**") == 1 and "1,400 staff" in text
    assert result["skipped"] == []


def test_automatic_write_keeps_the_unvalidated_marker(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Industry", "fact": "freight",
         "why": "scope (meeting · [[12-10-26-steerco]])"}]}, TODAY, automatic=True)
    assert "Context" in entity.read(root, "meridian-freight-holdings")["unvalidated"]


def test_cli_entity_write_automatic_flag(tmp_path):
    import json, subprocess, sys
    from pathlib import Path
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"context": [
        {"label": "Size", "fact": "1,200 staff", "why": "scale"}]}, TODAY)
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps({"context": [
        {"label": "Size", "fact": "1,400 staff", "why": "scale (meeting · [[x]])"}]}), encoding="utf-8")
    cli = Path(__file__).resolve().parents[2] / "plugin" / "lib" / "vaultlib" / "cli.py"
    out = subprocess.run([sys.executable, str(cli), "entity", "write", "--vault", str(root),
                          "--slug", "meridian-freight-holdings", "--edits", str(edits),
                          "--automatic", "--today", TODAY],
                         capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(out.stdout)
    assert payload["ok"] and payload["result"]["skipped"], out.stdout + out.stderr
