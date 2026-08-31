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


@pytest.mark.parametrize("field", ["role", "stance"])
@pytest.mark.parametrize("value", [["sponsor"], 7, {"x": 1}])
def test_a_non_string_role_or_stance_is_a_structured_error(tmp_path, field, value):
    # These were the only two caller values in the module not str()-wrapped
    # before .strip(), so a non-string raised AttributeError — which the
    # backstop did not catch either. `"role": ["sponsor"]` instead of
    # `"sponsor"` is a routine LLM JSON slip, not an exotic input.
    #
    # The error is now the payload-shape refusal rather than the vocabulary
    # one: a non-string never reaches the vocabulary check, and naming the type
    # is more actionable than reporting `['sponsor']` as an unknown role. The
    # vocabulary check still owns off-vocabulary *strings* — see
    # test_off_vocabulary_role_is_refused and its stance twin.
    root = seeded(tmp_path)
    with pytest.raises(entity.EntityError, match="must be a string"):
        entity.write(root, "meridian-freight-holdings", {"stakeholders": [
            dict({"name": "Dana Whitfield"}, **{field: value})]}, TODAY)


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


def test_omitting_status_does_not_reset_a_stored_one(tmp_path):
    # `or "Active"` was applied to the MERGE input, which made the Status cell
    # unconditionally truthy — so the fill-only guard could never protect a
    # stored value, and a follow-up note carrying no status turned a Completed
    # engagement back into Active while reporting ok.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "meridian-yard-automation-program", "status": "Completed",
         "one_liner": "Three-yard rollout"}]}, TODAY)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "meridian-yard-automation-program",
         "one_liner": "Closed out in Q3"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    row = next(line for line in text.splitlines()
               if line.startswith("|") and "meridian-yard-automation-program" in line)
    assert "Completed" in row
    assert "Closed out in Q3" in row


def test_a_first_engagement_still_defaults_to_active(tmp_path):
    # The other half of the fix: the default belongs on the append branch, so a
    # brand-new row with no status must still say Active.
    root = seeded(tmp_path)
    entity.write(root, "meridian-freight-holdings", {"engagements": [
        {"project": "meridian-yard-automation-program",
         "one_liner": "Three-yard rollout"}]}, TODAY)
    text = entity.read(root, "meridian-freight-holdings")["sections"]["Engagements"]
    row = next(line for line in text.splitlines()
               if line.startswith("|") and "meridian-yard-automation-program" in line)
    assert "Active" in row


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
    entity.write(root, "meridian-freight-holdings", {"stakeholders": [
        {"name": "Leo Marchetti"}]}, TODAY)
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
    ({"engagements": [{"status": "Active"}]}, "project"),
    ({"meeting_log": [{"topic": "only a topic", "dynamics": "d"}]}, "date"),
    ({"meeting_log": [{"date": "2026-01-01", "topic": "T"}]}, "dynamics"),
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


def test_an_unescaped_human_pipe_never_truncates_the_row(tmp_path):
    # The #40 repro. A raw `|` typed into a Notes cell in Obsidian read as a
    # column delimiter, the row split into six cells, and everything past
    # column five was dropped on the next write — reporting ok: true.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "title": "CFO",
         "notes": "placeholder note"}]}, TODAY)
    _hand_edit(root, "placeholder note", "wants a | b comparison before Q4")

    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Stakeholders"]
    row = [line for line in section.splitlines() if "Whitfield" in line][0]
    assert r"wants a \| b comparison before Q4" in row, (
        f"the hand-typed pipe truncated the cell: {row!r}")
    assert len(re.findall(r"(?<!\\)\|", row)) == 6  # 5 columns => 6 delimiters
    assert "Leo Marchetti" in section


def test_parse_table_rejoins_surplus_cells():
    # The issue's repro table, verbatim.
    tbl = (
        "| Name | Role | Stance | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| [[dana-whitfield]] | CFO | supportive | wants a | b comparison "
        "before Q4 |\n"
    )
    _preamble, rows, _postamble, repairs = entity._parse_table(tbl, 4)
    assert rows == [["[[dana-whitfield]]", "CFO", "supportive",
                     r"wants a \| b comparison before Q4"]]
    assert any("re-joined" in note for note in repairs), (
        f"a repair this destructive must be reported: {repairs}")


def test_pipe_repair_is_reported_in_the_result(tmp_path):
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "notes": "placeholder note"}]}, TODAY)
    _hand_edit(root, "placeholder note", "wants a | b comparison")

    result = entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)

    assert result["repairs"], "the repair was applied but never reported"
    assert any("Stakeholders" in note for note in result["repairs"])


def test_a_hand_deleted_separator_row_does_not_eat_the_first_data_row(tmp_path):
    # _parse_table skipped the first two pipe-prefixed lines unconditionally.
    # Obsidian renders a separator-less table fine, so the human saw nothing
    # wrong — and lost the first stakeholder on the next write.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "title": "CFO"}]}, TODAY)
    _hand_edit(root, "|------|-------|------------------|--------|-------|\n", "")

    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Stakeholders"]
    assert "Dana Whitfield" in section, "the first data row was eaten"
    assert entity.STAKEHOLDER_HEADER in section, (
        "the canonical separator row was not restored")


def test_pipe_prefixed_prose_survives_verbatim_not_as_a_row(tmp_path):
    # `startswith("|")` was the only thing separating structure from prose, so
    # a human's note beginning with a pipe became a padded one-cell row.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "title": "CFO"}]}, TODAY)
    note = "| route all scheduling through Sam"
    _hand_edit(root, "## Relationship History",
               f"{note}\n\n## Relationship History")

    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Stakeholders"]
    assert note in section.splitlines(), (
        f"the annotation was reshaped into a row: {section!r}")


def test_a_row_whose_trailing_pipe_was_deleted_is_still_a_row(tmp_path):
    # GFM makes the trailing pipe optional and Obsidian renders such a line as
    # a row, so a shape-based row test demoted it to prose: the payload then
    # missed the existing row, appended a duplicate person, and stranded the
    # human's stance and note below the table — on every write, forever.
    # SKILL.md tells the user to clear the needs-review marker themselves, and
    # selecting from `<!--` to end of line takes the ` |` with it.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Sam Okafor", "title": "Executive Assistant",
         "stance": "champion"}]}, TODAY)
    _hand_edit(root, " <!-- needs-review --> |", "  schedules Leo")

    result = entity.write(root, SLUG, {"stakeholders": [
        {"name": "Sam Okafor", "title": "EA"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Stakeholders"]
    rows = [line for line in section.splitlines() if "Okafor" in line]
    assert len(rows) == 1, f"the stakeholder was duplicated: {rows}"
    assert "schedules Leo" in rows[0], "the human's note was stranded"
    assert "champion" in rows[0], "the human's stance was stranded"
    assert "EA" in rows[0]
    assert result["repairs"] == [], (
        f"a row missing its optional trailing pipe is not a repair: {result}")


@pytest.mark.parametrize("gap", ["\n\n", "\n"],
                         ids=["blank-line-between", "no-blank-line-between"])
def test_a_pipe_note_above_the_stakeholder_table_is_not_taken_for_the_header(
        tmp_path, gap):
    # Taking the first pipe-prefixed line as the header regardless of what
    # follows it put the note where the header belonged: the note was dropped
    # as "the header row", the blank after it closed the table, and the real
    # header, separator and every row fell through to prose. The payload then
    # had no row to match, so it appended a duplicate Dana and stranded the
    # original table below her. GFM opens a table at a header followed by a
    # delimiter row, so Obsidian renders this input as a paragraph plus an
    # intact table — the parser has to agree.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "title": "CFO", "stance": "champion"}]},
        TODAY)
    note = "| a note: the CFO's assistant is Sam (reach him first)"
    _hand_edit(root, entity.STAKEHOLDER_HEADER,
               note + gap + entity.STAKEHOLDER_HEADER)

    result = entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "title": "Group CFO"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Stakeholders"]
    rows = [line for line in section.splitlines() if "Whitfield" in line]
    assert len(rows) == 1, f"the stakeholder was duplicated: {rows}"
    assert "Group CFO" in rows[0]
    assert "champion" in rows[0], "the stored stance was stranded"
    assert note in section.splitlines(), "the human's note was not kept"
    assert section.count("| Name | Title |") == 1, (
        f"the original table was stranded as prose: {section!r}")
    assert result["repairs"] == [], (
        f"a note above the table is not a repair: {result['repairs']}")


@pytest.mark.parametrize("gap", ["\n\n", "\n"],
                         ids=["blank-line-between", "no-blank-line-between"])
def test_a_pipe_note_above_the_engagements_table_is_not_taken_for_the_header(
        tmp_path, gap):
    # _merge_engagements shares _parse_table, so both tables carry the defect.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"engagements": [
        {"project": "meridian-yard-automation-program", "status": "Completed",
         "one_liner": "Three-yard rollout"}]}, TODAY)
    note = "| a note: procurement owns the renewal calendar"
    _hand_edit(root, entity.ENGAGEMENT_HEADER,
               note + gap + entity.ENGAGEMENT_HEADER)

    result = entity.write(root, SLUG, {"engagements": [
        {"project": "meridian-yard-automation-program",
         "one_liner": "Closed out in Q3"}]}, TODAY)

    section = entity.read(root, SLUG)["sections"]["Engagements"]
    rows = [line for line in section.splitlines()
            if "meridian-yard-automation-program" in line]
    assert len(rows) == 1, f"the engagement was duplicated: {rows}"
    assert "Closed out in Q3" in rows[0]
    assert "Completed" in rows[0], "the stored status was stranded"
    assert note in section.splitlines(), "the human's note was not kept"
    assert section.count("| Project | Status |") == 1, (
        f"the original table was stranded as prose: {section!r}")
    assert result["repairs"] == []


def test_a_reported_repair_never_fires_twice(tmp_path):
    # Every reported repair changes bytes and leaves the file canonical, so the
    # second write over the same content has nothing to report. A note that
    # recurs on every write of a healthy dossier is noise the skill would
    # relay to the user forever.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Dana Whitfield", "notes": "placeholder note"}]}, TODAY)
    _hand_edit(root, "placeholder note", "wants a | b comparison")
    _hand_edit(root, "|------|-------|------------------|--------|-------|\n", "")

    first = entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    assert len(first["repairs"]) == 2, first["repairs"]

    second = entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "Group COO"}]}, TODAY)
    assert second["repairs"] == [], (
        f"the repair did not converge: {second['repairs']}")


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
    for pattern in ("titel", "'title'"):
        with pytest.raises(entity.EntityError, match=pattern):
            entity.write(root, SLUG, {"stakeholders": [
                {"name": "Dana Whitfield", "titel": "CFO"}]}, TODAY)


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


def test_none_optional_field_is_still_a_no_op(tmp_path):
    # The non-string check must not turn an explicit null into an error: None
    # means "no update" for every fill-only merge.
    root = seeded(tmp_path)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": "COO"}]}, TODAY)
    entity.write(root, SLUG, {"stakeholders": [
        {"name": "Leo Marchetti", "title": None, "notes": "wants numbers"}]},
        TODAY)
    section = entity.read(root, SLUG)["sections"]["Stakeholders"]
    row = [line for line in section.splitlines() if "Marchetti" in line][0]
    assert "COO" in row
    assert "wants numbers" in row


def test_second_identical_write_is_byte_identical(tmp_path):
    # A spacing guard across the table and bullet mergers together: the
    # rendered file is a fixed point of re-applying the same payload, so no
    # write drifts the blank-line layout of a section it did not change.
    root = seeded(tmp_path)
    edits = {
        "context": [{"label": "Fleet", "fact": "three yards",
                     "why": "sets the automation scope"}],
        "stakeholders": [{"name": "Leo Marchetti", "title": "COO"}],
        "sensitivities": [{"topic": "Incumbent integrator", "detail": "d",
                           "implications": "i"}],
        "engagements": [{"project": "meridian-yard-automation-program",
                         "status": "Active",
                         "one_liner": "Three-yard rollout"}],
    }
    entity.write(root, SLUG, edits, TODAY)
    first = _dossier(root).read_bytes()
    entity.write(root, SLUG, edits, TODAY)
    assert _dossier(root).read_bytes() == first
