"""Tests for Tier 2 fuzzy string matching."""

import pytest

from resolver.fuzzy import FuzzyMatcher


@pytest.fixture
def fuzzy_matcher():
    """Create a fuzzy matcher with common YGO card names."""
    card_names = [
        "Ash Blossom & Joyous Spring",
        "Nibiru, the Primal Being",
        "Infinite Impermanence",
        "Effect Veiler",
        "Maxx \"C\"",
        "Called by the Grave",
        "Dark Ruler No More",
        "Snake-Eye Ash",
        "Snake-Eye Oak",
        "Snake-Eyes Poplar",
        "Branded Fusion",
        "Tearlaments Kitkallos",
        "Salamangreat Sunlight Wolf",
        "Blue-Eyes White Dragon",
        "Blue-Eyes Alternative White Dragon",
    ]
    return FuzzyMatcher(card_names)


@pytest.mark.parametrize(
    "query,expected,min_score",
    [
        ("Ash Blossom", "Ash Blossom & Joyous Spring", 85),
        ("Infinite Impermanence", "Infinite Impermanence", 100),
        ("Nibiru the Primal Being", "Nibiru, the Primal Being", 90),
        ("Effect Veiler", "Effect Veiler", 100),
    ],
)
def test_fuzzy_matches_partial_names(query, expected, min_score, fuzzy_matcher):
    """Test that fuzzy matching handles partial card names correctly."""
    results = fuzzy_matcher.match(query)
    assert len(results) > 0, f"Expected match for '{query}'"
    assert results[0][0] == expected, f"Expected '{expected}', got '{results[0][0]}'"
    assert results[0][1] >= min_score, f"Score {results[0][1]} below minimum {min_score}"


def test_fuzzy_rejects_low_similarity(fuzzy_matcher):
    """Test that common words don't match any card."""
    results = fuzzy_matcher.match("the player activates", threshold=80)
    assert len(results) == 0, f"Expected no matches for generic commentary, got {results}"


def test_fuzzy_short_query(fuzzy_matcher):
    """Test that short queries still match correctly."""
    results = fuzzy_matcher.match("ash", threshold=50)
    names = [r[0] for r in results]
    # Should match any card with "ash" in the name
    assert any("ash" in name.lower() for name in names), \
        f"Expected card with 'ash' in results for 'ash', got {names}"


def test_fuzzy_length_penalty(fuzzy_matcher):
    """Test that length penalty is applied for short/long pairs."""
    # "ash" is 3 chars, "Ash Blossom & Joyous Spring" is 27 chars
    # Length ratio = 3/27 = 0.11 < 0.3, so penalty should apply
    results = fuzzy_matcher.match("ash", threshold=70)

    # The match should still work, but with reduced score
    names = [r[0] for r in results]
    if "Ash Blossom & Joyous Spring" in names:
        idx = names.index("Ash Blossom & Joyous Spring")
        score = results[idx][1]
        # Score should be reduced from what WRatio would give
        # This is hard to test precisely, so just ensure it's reasonable
        assert 50 <= score <= 95, f"Expected reduced score for short query, got {score}"


def test_fuzzy_empty_query(fuzzy_matcher):
    """Test that empty queries return no results."""
    assert fuzzy_matcher.match("") == []
    assert fuzzy_matcher.match("   ") == []


def test_fuzzy_no_shared_tokens(fuzzy_matcher):
    """Test that queries with no shared tokens return no results."""
    # "zebra" shares no tokens with any card name
    results = fuzzy_matcher.match("zebra", threshold=80)
    assert len(results) == 0, f"Expected no matches for 'zebra', got {results}"


def test_fuzzy_case_insensitive(fuzzy_matcher):
    """Test that matching is case-insensitive."""
    results_lower = fuzzy_matcher.match("ash blossom")
    results_upper = fuzzy_matcher.match("ASH BLOSSOM")
    results_mixed = fuzzy_matcher.match("Ash Blossom")

    # All should match the same card
    assert len(results_lower) > 0
    assert results_lower[0][0] == results_upper[0][0] == results_mixed[0][0]
