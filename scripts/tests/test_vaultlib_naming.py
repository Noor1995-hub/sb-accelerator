"""Slug rules. Pure string logic, so this is where the edge cases live."""
import pytest

from vaultlib import naming


@pytest.mark.parametrize("text,expected", [
    ("Yard Automation Program", "yard-automation-program"),
    ("AI Delivery Platform Choice", "ai-delivery-platform-choice"),
    ("  leading and trailing  ", "leading-and-trailing"),
    ("Multiple   spaces", "multiple-spaces"),
    ("Punctuation: it's here!", "punctuation-it-s-here"),
    ("Already-Hyphenated", "already-hyphenated"),
    ("Numbers 123 stay", "numbers-123-stay"),
    ("Ampersand & more", "ampersand-more"),
    ("Em — dash", "em-dash"),
])
def test_slugify_shapes(text, expected):
    assert naming.slugify(text) == expected


def test_slugify_folds_accents_to_ascii():
    assert naming.slugify("Café Zürich naïve") == "cafe-zurich-naive"


def test_slugify_truncates_without_leaving_a_partial_word():
    text = "quarterly commercial operations pipeline governance review programme"
    result = naming.slugify(text, max_length=40)
    assert len(result) <= 40
    assert not result.endswith("-")
    # every segment survives whole
    assert all(segment in text.lower().split() for segment in result.split("-"))


def test_slugify_respects_an_exact_length_boundary():
    # 'abcde-fghij' is 11 chars; a limit of 11 keeps both segments
    assert naming.slugify("abcde fghij", max_length=11) == "abcde-fghij"
    # a limit of 10 cuts mid-segment, so the partial segment is dropped
    assert naming.slugify("abcde fghij", max_length=10) == "abcde"


def test_slugify_raises_when_nothing_survives():
    with pytest.raises(ValueError, match="produced an empty slug"):
        naming.slugify("!!! ???")


@pytest.mark.parametrize("slug", [
    "meridian-freight-holdings", "a", "a1", "yard-2", "one-two-three",
])
def test_validate_slug_accepts_well_formed(slug):
    naming.validate_slug(slug)


@pytest.mark.parametrize("slug,message", [
    ("", "empty"),
    ("Has-Upper", "lowercase"),
    ("has space", "lowercase"),
    ("has_underscore", "lowercase"),
    ("-leading", "lowercase"),
    ("trailing-", "lowercase"),
    ("double--hyphen", "lowercase"),
    ("con", "reserved"),
    ("NUL", "lowercase"),        # rejected on shape before reservation
    ("com1", "reserved"),
    ("lpt9", "reserved"),
    ("a" * 61, "exceeds"),
])
def test_validate_slug_rejects(slug, message):
    with pytest.raises(ValueError, match=message):
        naming.validate_slug(slug)


def test_find_collision_is_case_insensitive():
    existing = ["Meridian-Freight", "other-project"]
    assert naming.find_collision("meridian-freight", existing) == "Meridian-Freight"


def test_find_collision_returns_none_when_clear():
    assert naming.find_collision("new-thing", ["a", "b"]) is None


def test_find_collision_tolerates_an_empty_vault():
    assert naming.find_collision("first-project", []) is None
