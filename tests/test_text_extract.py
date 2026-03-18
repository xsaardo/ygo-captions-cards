"""Tests for text extraction and candidate generation."""

from resolver.text_extract import extract_candidates


def test_extract_single_card():
    """Test extracting a single card mention."""
    text = "he activates Ash Blossom in response"
    candidates = extract_candidates(text)

    # Should include both "ash" and "ash blossom"
    assert "ash" in candidates
    assert "ash blossom" in candidates


def test_extract_multiple_cards():
    """Test extracting multiple card mentions."""
    text = "chains Nibiru after the fifth summon and also has Imperm set"
    candidates = extract_candidates(text)

    assert "nibiru" in candidates
    assert "imperm" in candidates


def test_ngram_limit():
    """Test that n-grams are limited to max_ngram tokens."""
    text = " ".join(["word"] * 20)
    candidates = extract_candidates(text, max_ngram=6)

    # No candidate should be longer than 6 tokens
    for candidate in candidates:
        token_count = len(candidate.split())
        assert token_count <= 6


def test_normalization():
    """Test that extracted candidates are normalized."""
    text = "He activates Ash Blossom!"
    candidates = extract_candidates(text)

    # Punctuation should be removed, text lowercased
    assert "he activates ash blossom" in candidates


def test_empty_text():
    """Test extracting from empty text."""
    candidates = extract_candidates("")
    assert len(candidates) == 0


def test_single_word():
    """Test extracting from single word."""
    candidates = extract_candidates("ash")
    assert "ash" in candidates
    assert len(candidates) == 1
