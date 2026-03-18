"""Pytest fixtures for the YGO card overlay tests."""

import json
from pathlib import Path

import pytest

from resolver.alias_dict import AliasDictionary


@pytest.fixture
def alias_dict():
    """Load the test alias dictionary fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "aliases_test.json"
    return AliasDictionary(str(fixture_path))


@pytest.fixture
def sample_transcripts():
    """Load sample transcripts for integration tests."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_transcripts.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)
