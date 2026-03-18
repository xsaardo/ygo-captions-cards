"""Tests for Tier 3 phonetic matching."""

import pytest

from resolver.phonetic import PhoneticMatcher


@pytest.fixture
def phonetic_matcher():
    """Create a phonetic matcher with common YGO card names."""
    card_names = [
        "Ash Blossom & Joyous Spring",
        "Nibiru, the Primal Being",
        "Infinite Impermanence",
        "Maxx \"C\"",
        "Called by the Grave",
        "Tearlaments Kitkallos",
        "Salamangreat Sunlight Wolf",
        "Effect Veiler",
    ]
    return PhoneticMatcher(card_names)


@pytest.mark.parametrize(
    "misspelling,expected",
    [
        ("Nibirue", "Nibiru, the Primal Being"),
        ("Ash Blossum", "Ash Blossom & Joyous Spring"),
        ("Teerlaments", "Tearlaments Kitkallos"),
    ],
)
def test_phonetic_catches_stt_errors(misspelling, expected, phonetic_matcher):
    """Test that phonetic matching catches common STT transcription errors."""
    results = phonetic_matcher.match(misspelling)
    assert len(results) > 0, f"Expected phonetic match for '{misspelling}'"
    assert expected in results, f"Expected '{expected}' in results, got {results}"


def test_phonetic_no_match_for_unrelated_words(phonetic_matcher):
    """Test that unrelated words don't match known cards."""
    results = phonetic_matcher.match("hamburger")
    # Should not confidently match any card
    assert len(results) == 0, f"Expected no matches for 'hamburger', got {results}"


def test_phonetic_requires_min_fraction(phonetic_matcher):
    """Test that matches require minimum token match fraction."""
    # "foo bar baz qux" has 4 tokens
    # With min_token_match_fraction=0.5, need at least 2 matching tokens
    results = phonetic_matcher.match("foo bar baz qux", min_token_match_fraction=0.5)
    # Should not match anything since none of these tokens are in card names
    assert len(results) == 0


def test_phonetic_empty_query(phonetic_matcher):
    """Test that empty queries return no results."""
    assert phonetic_matcher.match("") == []
    assert phonetic_matcher.match("   ") == []


def test_phonetic_single_token_match(phonetic_matcher):
    """Test matching with a single misspelled token."""
    # "Nibiru" phonetically encoded
    results = phonetic_matcher.match("Nibirue")
    assert len(results) > 0
    assert "Nibiru, the Primal Being" in results
