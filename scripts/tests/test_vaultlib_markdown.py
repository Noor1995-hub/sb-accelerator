"""Frontmatter and section handling. The parser is ours because PyYAML is not
verified present in the Cowork VM, so its narrow subset is pinned here."""
import pytest

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
