"""Frontmatter and section handling. The parser is ours because PyYAML is not
verified present in the Cowork VM, so its narrow subset is pinned here."""
import pytest
import yaml

from vaultlib import markdown as md

DOSSIER = """---
type: entity
entity-name: "Meridian Freight Holdings"
slug: meridian-freight-holdings
entity-type: client
status: active
industry: "Freight & logistics"
owner: priya-nathan
created: 2025-09-15
last-updated: 2026-06-01
---

## Context

- **Industry:** freight — matters for yard scope.

## Stakeholders

| Name | Title |
|------|-------|
"""


def test_split_frontmatter_returns_data_and_body():
    data, body = md.split_frontmatter(DOSSIER)
    assert data["slug"] == "meridian-freight-holdings"
    assert data["entity-name"] == "Meridian Freight Holdings"
    assert body.startswith("\n## Context")


def test_dates_stay_verbatim_strings():
    data, _ = md.split_frontmatter(DOSSIER)
    assert data["created"] == "2025-09-15"
    assert data["last-updated"] == "2026-06-01"


def test_missing_frontmatter_raises():
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        md.split_frontmatter("# Just a heading\n")


def test_unterminated_frontmatter_raises():
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        md.split_frontmatter("---\nslug: x\n")


def test_crlf_input_parses():
    data, body = md.split_frontmatter("---\r\nslug: x\r\n---\r\n\r\nbody\r\n")
    assert data["slug"] == "x"
    assert "body" in body


def test_inline_list_parses():
    data = md.parse_frontmatter_block("stakeholders: [priya-nathan, leo-marchetti]")
    assert data["stakeholders"] == ["priya-nathan", "leo-marchetti"]


def test_empty_inline_list_parses():
    assert md.parse_frontmatter_block("stakeholders: []")["stakeholders"] == []


def test_inline_list_respects_quoted_commas():
    data = md.parse_frontmatter_block('tags: ["a, b", c]')
    assert data["tags"] == ["a, b", "c"]


def test_block_list_parses():
    data = md.parse_frontmatter_block("tags:\n  - platform\n  - commercial")
    assert data["tags"] == ["platform", "commercial"]


def test_bare_key_is_null_not_empty_list():
    # People.base's "Uncurated" view filters on relationship being null, so
    # this distinction is load-bearing.
    assert md.parse_frontmatter_block("relationship:")["relationship"] is None


def test_explicit_null_is_null():
    assert md.parse_frontmatter_block("parent: null")["parent"] is None


def test_integers_parse_as_integers():
    data = md.parse_frontmatter_block("meetings-7d: 0\nmeetings-30d: 12")
    assert data["meetings-7d"] == 0
    assert data["meetings-30d"] == 12


def test_booleans_parse_as_booleans():
    data = md.parse_frontmatter_block("reviewed: true\narchived: false")
    assert data["reviewed"] is True
    assert data["archived"] is False


def test_quoted_colon_value_survives():
    # An unquoted 1:1 would parse as the integer 61 in real YAML; ours keeps
    # the quoted form intact.
    assert md.parse_frontmatter_block('type: "1:1"')["type"] == "1:1"


def test_wikilink_value_survives():
    data = md.parse_frontmatter_block('source: "[[20-05-26-vendor-strategy]]"')
    assert data["source"] == "[[20-05-26-vendor-strategy]]"


def test_comments_and_blank_lines_are_ignored():
    data = md.parse_frontmatter_block("# a comment\n\nslug: x\n")
    assert data == {"slug": "x"}


def test_unparseable_line_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="unparseable"):
        md.parse_frontmatter_block("this has no colon")


def test_emit_frontmatter_round_trips():
    data = {"slug": "x", "stakeholders": ["a", "b"], "parent": None,
            "meetings-7d": 0, "reviewed": True}
    text = md.emit_frontmatter(data)
    assert text.startswith("---\n") and text.endswith("---\n")
    assert md.parse_frontmatter_block(text[4:-4]) == data


def test_emit_quotes_only_the_requested_keys():
    text = md.emit_frontmatter(
        {"project-name": "Yard Program", "slug": "yard-program"},
        quote_keys={"project-name"},
    )
    assert 'project-name: "Yard Program"' in text
    assert "slug: yard-program" in text


def test_emit_writes_null_as_a_bare_key():
    assert "parent:\n" in md.emit_frontmatter({"parent": None})


def test_emit_escapes_embedded_quotes():
    text = md.emit_frontmatter({"n": 'a "quoted" word'}, quote_keys={"n"})
    assert md.parse_frontmatter_block(text[4:-4])["n"] == 'a "quoted" word'


def test_emit_escapes_backslashes_so_real_yaml_parsers_survive(tmp_path):
    # Issue #47: an unescaped backslash inside a double-quoted scalar is an
    # escape sequence to PyYAML/js-yaml — `\new` becomes a newline, `\s`
    # raises. The note would vanish from every .base view.
    text = md.emit_frontmatter({"summary": r"the C:\new path"},
                               quote_keys={"summary"})
    assert r'summary: "the C:\\new path"' in text
    data, _ = md.split_frontmatter(text)
    assert data["summary"] == r"the C:\new path"
    assert yaml.safe_load(text.split("---")[1])["summary"] == r"the C:\new path"


def test_parser_leaves_legacy_lone_backslashes_verbatim():
    # Files written before the escaping fix carry `\s`-style sequences; only
    # \\ and \" are unescaped, anything else stays as-is.
    data = md.parse_frontmatter_block(r'summary: "a back\slash"')
    assert data["summary"] == r"a back\slash"


def test_emit_refuses_a_newline_even_inside_a_quoted_value():
    # Writing frontmatter nothing can parse and reporting success bricks the
    # object: every later read of that file fails permanently. Quoting does not
    # save it — YAML ends the scalar at the newline either way.
    with pytest.raises(ValueError, match="newline"):
        md.emit_frontmatter({"entity-name": "Acme\nInc"},
                            quote_keys={"entity-name"})


def test_emit_refuses_an_unquoted_value_that_would_parse_as_a_mapping():
    # `owner: jordan: reyes` is a ScannerError in PyYAML, which is Obsidian's,
    # Dataview's, Bases' and CI's conformance parser.
    with pytest.raises(ValueError, match="nested mapping"):
        md.emit_frontmatter({"owner": "jordan: reyes"})


def test_emit_still_accepts_a_colon_inside_a_quoted_value():
    text = md.emit_frontmatter({"entity-name": "Acme: The Sequel"},
                               quote_keys={"entity-name"})
    assert 'entity-name: "Acme: The Sequel"' in text
    data, _ = md.split_frontmatter(text)
    assert data["entity-name"] == "Acme: The Sequel"


def test_replace_scalar_field_preserves_everything_else():
    updated = md.replace_scalar_field(DOSSIER, "last-updated", "2026-08-23")
    assert "last-updated: 2026-08-23" in updated
    assert 'entity-name: "Meridian Freight Holdings"' in updated
    assert updated.count("---") == DOSSIER.count("---")
    # body untouched
    assert updated.split("---\n", 2)[2] == DOSSIER.split("---\n", 2)[2]


def test_replace_scalar_field_raises_on_absent_field():
    with pytest.raises(ValueError, match="not present"):
        md.replace_scalar_field(DOSSIER, "nope", "x")


def test_replace_scalar_field_ignores_body_matches():
    text = "---\nstatus: active\n---\n\nstatus: decoy in the body\n"
    updated = md.replace_scalar_field(text, "status", "dormant")
    assert "status: dormant" in updated
    assert "status: decoy in the body" in updated


def test_split_sections_returns_titles_and_content():
    _, body = md.split_frontmatter(DOSSIER)
    sections = md.split_sections(body)
    assert [title for title, _ in sections] == ["", "Context", "Stakeholders"]
    assert "Industry" in dict(sections)["Context"]


def test_split_sections_ignores_h2_inside_fenced_code():
    body = "## Real\n\n```\n## Not a heading\n```\n\n## Also Real\n"
    assert [t for t, _ in md.split_sections(body)] == ["", "Real", "Also Real"]


def test_render_sections_round_trips():
    body = "\n## One\n\nalpha\n\n## Two\n\nbeta\n"
    assert md.render_sections(md.split_sections(body)) == body


def test_upsert_scalar_field_replaces_in_place():
    text = "---\nslug: x\nmeetings-7d: 3\n---\nBody stays.\n"
    result = md.upsert_scalar_field(text, "meetings-7d", "0")
    assert result == "---\nslug: x\nmeetings-7d: 0\n---\nBody stays.\n"


def test_upsert_scalar_field_inserts_before_the_closing_fence():
    text = "---\nslug: x\n---\nBody stays.\n"
    result = md.upsert_scalar_field(text, "meetings-7d", "2")
    assert result == "---\nslug: x\nmeetings-7d: 2\n---\nBody stays.\n"


def test_upsert_scalar_field_requires_frontmatter():
    with pytest.raises(ValueError):
        md.upsert_scalar_field("no fences here", "a", "b")


# Obsidian's property editor rewrites the whole frontmatter block on any edit:
# quotes stripped, flow lists expanded to block lists. The replace/upsert paths
# must treat such a block list as one node, or the write orphans the
# continuation lines and the file stops parsing (issue #53, finding G4).

OBSIDIAN_EXPANDED = """---
slug: x
key-people:
  - priya-nathan
  - stale-slug
status: active
---
Body stays.
"""


def test_replace_scalar_field_collapses_an_obsidian_block_list():
    updated = md.replace_scalar_field(
        OBSIDIAN_EXPANDED, "key-people", "[leo-marchetti, priya-nathan]")
    assert updated == ("---\nslug: x\n"
                       "key-people: [leo-marchetti, priya-nathan]\n"
                       "status: active\n---\nBody stays.\n")
    data, _ = md.split_frontmatter(updated)
    assert data["key-people"] == ["leo-marchetti", "priya-nathan"]


def test_upsert_scalar_field_collapses_an_obsidian_block_list():
    updated = md.upsert_scalar_field(
        OBSIDIAN_EXPANDED, "key-people", "[leo-marchetti]")
    data, _ = md.split_frontmatter(updated)
    assert data["key-people"] == ["leo-marchetti"]
    assert "stale-slug" not in updated


def test_replace_scalar_field_repairs_the_orphaned_continuation_shape():
    # The corrupted-in-the-wild form G4 produced: a rewritten key line with the
    # old block items left dangling under it. A write to that field must
    # consume the orphans, never stack a second generation of them.
    corrupted = ("---\nslug: x\n"
                 "key-people: [leo-marchetti, priya-nathan]\n"
                 "  - priya-nathan\n"
                 "status: active\n---\n")
    updated = md.replace_scalar_field(corrupted, "key-people", "[priya-nathan]")
    data, _ = md.split_frontmatter(updated)
    assert data["key-people"] == ["priya-nathan"]
    assert "leo-marchetti" not in updated


def test_replace_scalar_field_consumes_blanks_inside_the_node_only():
    # The parser keeps the current key across blank lines, so an item after a
    # blank still belongs to the node — but a trailing blank line before the
    # next key is layout, not node, and must survive.
    text = ("---\nkey-people:\n\n  - priya-nathan\n\nstatus: active\n---\n")
    updated = md.replace_scalar_field(text, "key-people", "[a-b]")
    assert updated == "---\nkey-people: [a-b]\n\nstatus: active\n---\n"


def test_orphaned_continuation_error_names_the_field_and_hints():
    # A file we only read (not write) can still carry the corrupted shape;
    # rejection must say which field and what to do, not just "list item".
    with pytest.raises(ValueError, match=r"key-people.*orphan"):
        md.parse_frontmatter_block(
            "key-people: [leo-marchetti]\n  - priya-nathan")


def test_list_item_with_no_key_at_all_still_raises():
    with pytest.raises(ValueError, match="before any key"):
        md.parse_frontmatter_block("- floating item")


def test_unquoted_wikilink_value_reads_as_the_wikilink_string():
    # Wikilink fields are written quoted, but an Obsidian property edit strips
    # the quotes (issue #53, finding C2). The shape can only mean a wikilink —
    # a vault inline list never starts `[[` — so repair on read rather than
    # returning the silently mangled ['[stem]'].
    data = md.parse_frontmatter_block(
        "supersedes: [[2026-03-10-phased-rollout-adopted]]")
    assert data["supersedes"] == "[[2026-03-10-phased-rollout-adopted]]"


def test_unquoted_wikilink_with_alias_reads_as_a_string_too():
    data = md.parse_frontmatter_block("source: [[stem|Display Name]]")
    assert data["source"] == "[[stem|Display Name]]"


def test_inline_lists_still_parse_after_wikilink_repair():
    data = md.parse_frontmatter_block("key-people: [a-b, c-d]")
    assert data["key-people"] == ["a-b", "c-d"]


def test_replace_scalar_field_leaves_a_following_scalar_key_alone():
    updated = md.replace_scalar_field(
        OBSIDIAN_EXPANDED, "status", "dormant")
    assert "status: dormant" in updated
    assert "  - priya-nathan\n" in updated  # other nodes untouched


def test_remove_field_drops_the_whole_node_and_nothing_else():
    text = ("---\nperson-name: \"Jan\"\ncompany:\n  - a\n\n  - b\n# note\nrole: \"CFO\"\n---\n\nbody\n")
    out = md.remove_field(text, "company")
    assert out == "---\nperson-name: \"Jan\"\n# note\nrole: \"CFO\"\n---\n\nbody\n"


def test_remove_field_matches_only_the_top_level_key():
    text = "---\nslug: x\nother:\n  company: y\nmy-company: z\n---\n"
    assert md.remove_field(text, "company") == text


def test_remove_field_absent_is_byte_identical():
    text = "---\r\nslug: x\r\n---\r\nbody\r\n"
    assert md.remove_field(text, "company") == text


def test_remove_field_needs_frontmatter():
    with pytest.raises(ValueError):
        md.remove_field("no frontmatter\n", "company")
