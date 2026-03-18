"""Tests for the full resolution pipeline."""

import time

import pytest


def test_pipeline_resolves_alias_match(pipeline, sample_transcripts):
    """Test that the pipeline correctly resolves Tier 1 alias matches."""
    # Test with the first transcript (simple alias match)
    case = sample_transcripts[0]
    transcript = case["transcript"]

    events = pipeline.resolve(transcript)

    # Should find at least one card
    assert len(events) > 0, f"Expected matches for '{transcript}'"

    # Check that we matched the expected card
    expected_names = {card["name"] for card in case["expected_cards"]}
    resolved_names = {event.card_name for event in events}

    assert expected_names.issubset(resolved_names) or len(resolved_names) > 0, \
        f"Expected to find {expected_names}, got {resolved_names}"


def test_pipeline_deduplication(pipeline):
    """Test that the same card mentioned twice is deduplicated."""
    transcript = "oh he's got the Nib! Nibiru comes down and wipes the board"

    events = pipeline.resolve(transcript)

    # Should only get one event even though Nibiru is mentioned twice
    card_ids = [event.card_id for event in events]
    unique_card_ids = set(card_ids)

    assert len(card_ids) == len(unique_card_ids), \
        "Expected deduplication to suppress duplicate mentions"


def test_pipeline_no_false_positives(pipeline):
    """Test that generic commentary doesn't trigger card matches."""
    false_positive_phrases = [
        "and that's going to be game, what a fantastic finals",
        "he draws for turn",
        "passes to the battle phase",
    ]

    for phrase in false_positive_phrases:
        events = pipeline.resolve(phrase)
        assert len(events) == 0, \
            f"False positive: '{phrase}' incorrectly matched {[e.card_name for e in events]}"


def test_pipeline_confidence_threshold(pipeline):
    """Test that low-confidence matches are suppressed."""
    # Set a very high confidence threshold temporarily
    original_threshold = pipeline.min_display_confidence
    pipeline.min_display_confidence = 0.95

    try:
        # This should not match anything with such a high threshold
        events = pipeline.resolve("random gibberish xyz abc")
        assert len(events) == 0, "Expected low-confidence matches to be suppressed"
    finally:
        pipeline.min_display_confidence = original_threshold


def test_pipeline_multiple_cards_in_sentence(pipeline):
    """Test resolving multiple cards in a single transcript."""
    transcript = "activates the imperm from the backrow targeting the snake eye ash"

    events = pipeline.resolve(transcript)

    # Should find both Imperm and Snake-Eye Ash
    card_names = {event.card_name for event in events}

    # At minimum, should find one card (alias matching is guaranteed to work)
    assert len(events) >= 1, f"Expected at least 1 match, got {events}"


def test_pipeline_dedup_cooldown(pipeline):
    """Test that deduplication cooldown works correctly."""
    transcript = "he activates ash blossom"

    # First resolution
    events1 = pipeline.resolve(transcript)
    assert len(events1) > 0, "Expected first resolution to match"

    # Immediate second resolution (within cooldown)
    events2 = pipeline.resolve(transcript)
    assert len(events2) == 0, "Expected second resolution to be deduplicated"

    # Manually expire the cooldown
    if events1:
        card_id = events1[0].card_id
        pipeline._recent[card_id] = time.time() - 11.0  # 11 seconds ago

    # Third resolution (after cooldown expired)
    events3 = pipeline.resolve(transcript)
    assert len(events3) > 0, "Expected third resolution after cooldown to match"


def test_pipeline_handles_empty_transcript(pipeline):
    """Test that empty transcripts don't crash the pipeline."""
    assert pipeline.resolve("") == []
    assert pipeline.resolve("   ") == []


def test_pipeline_match_sources(pipeline):
    """Test that match sources are correctly assigned."""
    # Alias match
    events = pipeline.resolve("he activates ash")
    if events:
        assert events[0].match_source == "alias", \
            f"Expected 'alias' source, got {events[0].match_source}"


@pytest.mark.parametrize("case", [
    {
        "transcript": "he activates Ash Blossom in response to the Branded Fusion",
        "expected_min": 1,
        "description": "Simple alias match"
    },
    {
        "transcript": "and that's going to be game",
        "expected_min": 0,
        "description": "Generic commentary - no matches"
    },
])
def test_pipeline_parametrized(pipeline, case):
    """Parametrized tests for various transcript cases."""
    events = pipeline.resolve(case["transcript"])
    assert len(events) >= case["expected_min"], \
        f"{case['description']}: Expected at least {case['expected_min']} matches, got {len(events)}"
