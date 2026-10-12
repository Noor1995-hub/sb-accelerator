"""Person notes. The vault owner's own note is created here, because a
project owner that joins to nothing is a hole in the relationship graph."""
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
    assert body.strip() == "# Morgan Ellery"   # the name is the page heading (#258)


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


def test_ensure_reports_ignored_name_when_it_differs_from_the_note(tmp_path):
    # (#97) person notes are curated through People.base and are never
    # rewritten — that is deliberate. But the old envelope silently dropped a
    # differing --name with no signal at all, which reads as an ordinary
    # success. The caller must be told the name was not applied.
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    # Same slug ("morgan-ellery"), different display text — the collision
    # this exercises, not a different person.
    result = person.ensure(root, "morgan ellery", "2026-08-24")
    assert result["created"] is False
    assert result["ignored"] == ["name"]
    assert result["reason"]
    text = (root / "50-people" / "morgan-ellery.md").read_text(encoding="utf-8")
    assert 'person-name: "Morgan Ellery"' in text


def test_ensure_reports_no_ignored_fields_when_name_matches(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Morgan Ellery", "2026-08-23")
    result = person.ensure(root, "Morgan Ellery", "2026-08-24")
    assert result["created"] is False
    assert "ignored" not in result


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


def test_a_new_person_from_the_feed_carries_their_address(tmp_path):
    root = make_vault(tmp_path)
    result = person.ensure(root, "Jordan Reyes", "2026-09-30", email="Jordan.Reyes@acme.example")
    fm, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert fm["email"] == "jordan.reyes@acme.example"


def test_an_existing_person_gets_a_missing_email_once_and_never_overwritten(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Jordan Reyes", "2026-09-30")
    assert person.set_email_if_missing(root, "jordan-reyes", "jordan.reyes@acme.example") is True
    assert person.set_email_if_missing(root, "jordan-reyes", "other@acme.example") is False
    assert person.address_book(root) == {"jordan.reyes@acme.example": "jordan-reyes"}


def test_enrichment_of_an_unknown_slug_is_a_no_op(tmp_path):
    root = make_vault(tmp_path)
    assert person.set_email_if_missing(root, "nobody", "x@acme.example") is False


def test_enrichment_never_raises_on_a_note_without_frontmatter(tmp_path):
    root = make_vault(tmp_path)
    note = root / "50-people" / "plain.md"
    note.write_text("just a body" + chr(10), encoding="utf-8")
    assert person.set_email_if_missing(root, "plain", "x@acme.example") is False
    assert note.read_text(encoding="utf-8") == "just a body" + chr(10)


def test_enrichment_refuses_an_address_that_would_not_parse_back(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Jordan Reyes", "2026-09-30")
    note = root / "50-people" / "jordan-reyes.md"
    before = note.read_text(encoding="utf-8")
    assert person.set_email_if_missing(root, "jordan-reyes", "a: b@acme.example") is False
    assert note.read_text(encoding="utf-8") == before


# --- #242: the M365 attendee address is kept ---

def test_ensure_stores_the_email_on_creation(tmp_path):
    root = make_vault(tmp_path)
    result = person.ensure(root, "Ana Fields", "2026-06-12", email="ana.fields@client.example")
    data, _ = md.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert data["email"] == "ana.fields@client.example"
    assert not schema.validate("person", data)


def test_ensure_fills_an_empty_email_on_an_existing_note(tmp_path):
    root = make_vault(tmp_path)
    created = person.ensure(root, "Ana Fields", "2026-06-12")
    path = root / created["path"]
    result = person.ensure(root, "Ana Fields", "2026-06-13", email="ana@client.example")
    assert result["created"] is False and result["updated"] == ["email"]
    data, _ = md.split_frontmatter(path.read_text(encoding="utf-8"))
    assert data["email"] == "ana@client.example"
    assert data["last-updated"] is not None and str(data["created"]) == "2026-06-12"


def test_ensure_never_overwrites_a_set_email(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Ana Fields", "2026-06-12", email="ana@client.example")
    path = root / "50-people" / "ana-fields.md"
    before = path.read_bytes()
    result = person.ensure(root, "Ana Fields", "2026-06-13", email="other@client.example")
    assert path.read_bytes() == before
    assert "email" in result.get("ignored", [])
    assert "updated" not in result


@pytest.mark.parametrize("bad", ["not-an-address", "a b@c.example", "a@b.example\nx: y"])
def test_ensure_refuses_a_malformed_email(tmp_path, bad):
    root = make_vault(tmp_path)
    with pytest.raises(ValueError, match="email"):
        person.ensure(root, "Ana Fields", "2026-06-12", email=bad)
    assert not (root / "50-people" / "ana-fields.md").exists()


def _entity(root, slug="acme"):
    (root / "40-entities" / slug).mkdir(parents=True, exist_ok=True)
    (root / "40-entities" / slug / "dossier.md").write_text(
        f'---\ntype: entity\nentity-name: "Acme"\nslug: {slug}\nstatus: active\n---\n', encoding="utf-8")


def test_ensure_links_a_new_person_and_writes_no_company(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    made = person.ensure(root, "Jan Peeters", "2026-10-12", entity="acme")
    text = (root / made["path"]).read_text(encoding="utf-8")
    assert "entity: acme" in text and "company" not in text


def test_ensure_fills_an_empty_entity_only(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    _entity(root, "beta")
    person.ensure(root, "Jan Peeters", "2026-10-12")
    assert "entity" in person.ensure(root, "Jan Peeters", "2026-10-12", entity="acme")["updated"]
    again = person.ensure(root, "Jan Peeters", "2026-10-12", entity="beta")
    assert "entity" in again["ignored"]


def test_set_fields_writes_and_validates(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    person.ensure(root, "Jan Peeters", "2026-10-12")
    got = person.set_fields(root, "jan-peeters", entity="acme", role="CFO",
                            decision_role="sponsor", stance="champion")
    assert got["changed"] == ["entity", "role", "decision-role", "stance"]
    text = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    assert 'role: "CFO"' in text and "decision-role: sponsor" in text
    with pytest.raises(ValueError, match="stance"):
        person.set_fields(root, "jan-peeters", stance="hostile")
    with pytest.raises(ValueError, match="entity"):
        person.set_fields(root, "jan-peeters", entity="nobody")


def test_set_fields_says_what_each_changed_field_was(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    _entity(root, "acme-finance")
    person.ensure(root, "Jan Peeters", "2026-10-12", entity="acme-finance")
    got = person.set_fields(root, "jan-peeters", entity="acme", role="CFO")
    assert got["was"] == {"entity": "acme-finance", "role": ""}
    assert person.set_fields(root, "jan-peeters", entity="acme")["was"] == {}


def test_set_fields_lowercases_the_vocabulary_words(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Jan Peeters", "2026-10-12")
    got = person.set_fields(root, "jan-peeters", decision_role="Champion", stance=" Neutral ")
    assert got["changed"] == ["decision-role", "stance"]
    text = (root / "50-people/jan-peeters.md").read_text(encoding="utf-8")
    assert "decision-role: champion" in text and "stance: neutral" in text


def test_set_fields_entity_removes_the_legacy_company(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    path = root / "50-people/jan-peeters.md"
    path.write_text('---\nperson-name: "Jan Peeters"\nslug: jan-peeters\ncompany: "LLBG"\n'
                    'role:\n---\n\n# Jan Peeters\n', encoding="utf-8")
    person.set_fields(root, "jan-peeters", entity="acme")
    data, _ = md.split_frontmatter(path.read_text(encoding="utf-8"))
    assert data["entity"] == "acme" and "company" not in data


def test_ensure_filling_an_entity_removes_the_legacy_company(tmp_path):
    root = make_vault(tmp_path)
    _entity(root)
    path = root / "50-people/jan-peeters.md"
    path.write_text('---\nperson-name: "Jan Peeters"\nslug: jan-peeters\ncompany: "LLBG"\n'
                    'role:\n---\n\n# Jan Peeters\n', encoding="utf-8")
    person.ensure(root, "Jan Peeters", "2026-10-12", entity="acme")
    data, _ = md.split_frontmatter(path.read_text(encoding="utf-8"))
    assert data["entity"] == "acme" and "company" not in data
