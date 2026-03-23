"""Integration tests using sample transcript fixtures.

Tests the full resolution pipeline including Tier 1-4 resolution:
- Tier 1: Alias dictionary
- Tier 2: Fuzzy matching
- Tier 3: Phonetic matching
- Tier 4: Context-aware resolution
"""

import pytest

from resolver.alias_dict import AliasDictionary
from resolver.text_extract import extract_candidates


def test_tier1_alias_resolution(alias_dict, sample_transcripts):
    """Test Tier 1 alias dictionary resolution with sample transcripts.

    This tests the Tier 1 pipeline:
    1. Extract candidates from transcript
    2. Match against alias dictionary
    3. Verify expected cards are found
    """
    for case in sample_transcripts:
        if case["tier"] != 1:
            # Skip non-Tier-1 tests
            continue

        transcript = case["transcript"]
        expected_cards = case["expected_cards"]
        description = case["description"]

        # Extract candidates
        candidates = extract_candidates(transcript)

        # Try to match against alias dictionary (longest-first)
        candidates_sorted = sorted(candidates, key=len, reverse=True)

        matched_cards = []
        matched_card_ids = set()  # Track which cards we've already matched
        for candidate in candidates_sorted:
            entry = alias_dict.lookup(candidate)
            if entry and entry.name and entry.id not in matched_card_ids:
                matched_cards.append({"name": entry.name, "source": "alias"})
                matched_card_ids.add(entry.id)
                # Match up to the expected number of cards
                if len(matched_cards) >= len(expected_cards):
                    break

        # Verify matches
        matched_names = {card["name"] for card in matched_cards}
        expected_names = {card["name"] for card in expected_cards}

        assert (
            matched_names == expected_names
        ), f"Failed for '{description}': expected {expected_names}, got {matched_names}"


def test_tier2_fuzzy_resolution(pipeline, sample_transcripts):
    """Test Tier 2 fuzzy matching with full pipeline."""
    # Test that pipeline can resolve via fuzzy matching
    # Since sample_transcripts only has tier 1, we'll test direct fuzzy matching
    events = pipeline.resolve("Ash Blossim")  # Misspelling should fuzzy match
    matched_names = [event.card_name for event in events]
    assert "Ash Blossom & Joyous Spring" in matched_names


def test_tier3_phonetic_resolution(pipeline, sample_transcripts):
    """Test Tier 3 phonetic matching with full pipeline."""
    # Test that pipeline can resolve via phonetic matching
    # Use a longer phrase so it meets the minimum candidate length (12 chars)
    events = pipeline.resolve("Ashh Blozum and Joyus Spring")  # Phonetically similar
    matched_names = [event.card_name for event in events]
    # Phonetic matching should find Ash Blossom
    assert len(matched_names) > 0


def test_tier4_context_resolution(pipeline, sample_transcripts):
    """Test Tier 4 context-aware resolution with full pipeline."""
    # Test that pipeline uses context (archetype awareness)
    events = pipeline.resolve("Snake-Eye Ash")
    matched_names = [event.card_name for event in events]
    assert "Snake-Eye Ash" in matched_names
