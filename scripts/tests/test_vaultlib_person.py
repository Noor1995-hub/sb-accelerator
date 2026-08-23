"""Person notes. The executive's own note is created here, because a project
owner that joins to nothing is a hole in the relationship graph."""
import pytest

from vaultlib import markdown as md
from vaultlib import person, schema

from test_vaultlib_vault import make_vault


def test_ensure_creates_a_conformant_note(tmp_path):
    root = make_vault(tmp_path)
    result = person.ensure(root, "Morgan Ellery", "2026-08-23")
    assert result == {
        "slug": "morgan-ellery",
        "path": "50-people/morgan-ellery.md",
        "created": True,
    }
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    data, body = md.split_frontmatter(text)
    assert schema.validate("person", data) == []
    assert body.strip() == ""


def test_ensure_writes_relationship_as_a_present_null_key(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    data, _ = md.split_frontmatter(text)
    # People.base's "Uncurated" view filters on this being null, so the key
    # must exist with an empty value rather than be absent.
    assert "relationship" in data
    assert data["relationship"] is None


def test_ensure_quotes_the_display_name_and_leaves_the_slug_bare(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    assert 'person-name: "Morgan Ellery"' in text
    assert "slug: morgan-ellery" in text


def test_ensure_is_idempotent_and_does_not_rewrite(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    target = root / "50-people" / "morgan-ellery.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("relationship:", "relationship: colleague"),
        encoding="utf-8",
    )
    result = person.ensure(root, "Morgan Ellery", "2026-08-24")
    assert result["created"] is False
    # curation survives a second call
    assert "relationship: colleague" in target.read_text(encoding="utf-8")


def test_ensure_matches_an_existing_note_case_insensitively(tmp_path):
    root = make_vault(tmp_path)
    (root / "50-people" / "Morgan-Ellery.md").write_text(
        '---\nperson-name: "Morgan Ellery"\nslug: Morgan-Ellery\nrelationship:\n---\n',
        encoding="utf-8",
    )
    result = person.ensure(root, "Morgan Ellery", "2026-08-23")
    assert result["created"] is False
    assert result["path"] == "50-people/Morgan-Ellery.md"


def test_ensure_rejects_a_name_that_slugifies_to_nothing(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="empty slug"):
        person.ensure(root, "!!!", "2026-08-23")


def test_ensure_uses_lf_endings(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    raw = (root / "50-people" / "morgan-ellery.md").read_bytes()
    assert b"\r\n" not in raw
