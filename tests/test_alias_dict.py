"""Tests for alias dictionary lookup."""

import pytest


def test_exact_match(alias_dict):
    """Test exact alias match."""
    entry = alias_dict.lookup("ash")
    assert entry is not None
    assert entry.name == "Ash Blossom & Joyous Spring"
    assert entry.id == 14558127


def test_case_insensitive(alias_dict):
    """Test case-insensitive matching."""
    entry1 = alias_dict.lookup("ASH")
    entry2 = alias_dict.lookup("ash")
    entry3 = alias_dict.lookup("Ash")

    assert entry1 is not None
    assert entry2 is not None
    assert entry3 is not None
    assert entry1.id == entry2.id == entry3.id


def test_miss_returns_none(alias_dict):
    """Test that non-existent aliases return None."""
    entry = alias_dict.lookup("nonexistent card xyz")
    assert entry is None


def test_punctuation_normalized(alias_dict):
    """Test that punctuation is normalized."""
    # 'Maxx "C"' should match regardless of quotes
    entry = alias_dict.lookup("maxx c")
    assert entry is not None
    assert entry.name == 'Maxx "C"'


def test_archetype_entry(alias_dict):
    """Test archetype entries (no card ID, just archetype)."""
    entry = alias_dict.lookup("salads")
    assert entry is not None
    assert entry.archetype == "Salamangreat"
    assert entry.id is None


def test_multi_word_alias(alias_dict):
    """Test multi-word aliases."""
    entry = alias_dict.lookup("ash blossom")
    assert entry is not None
    assert entry.name == "Ash Blossom & Joyous Spring"


def test_acronym_match(alias_dict):
    """Test acronym matching."""
    entry = alias_dict.lookup("cbtg")
    assert entry is not None
    assert entry.name == "Called by the Grave"

    entry = alias_dict.lookup("drnm")
    assert entry is not None
    assert entry.name == "Dark Ruler No More"
