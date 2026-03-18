"""Pytest fixtures for the YGO card overlay tests."""

import json
from pathlib import Path

import pytest

from data.card_db import CardDatabase
from resolver.alias_dict import AliasDictionary
from resolver.context import ContextResolver
from resolver.fuzzy import FuzzyMatcher
from resolver.phonetic import PhoneticMatcher
from resolver.pipeline import ResolutionPipeline
from telemetry.logger import ResolverLogger


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


@pytest.fixture
def card_db():
    """Create a card database with test data."""
    # Create a minimal card database for testing
    db = CardDatabase("data/cards.json")
    db.initialize()
    return db


@pytest.fixture
def fuzzy_matcher(card_db):
    """Create a fuzzy matcher with card names from the database."""
    return FuzzyMatcher(card_db.all_names())


@pytest.fixture
def phonetic_matcher(card_db):
    """Create a phonetic matcher with card names from the database."""
    return PhoneticMatcher(card_db.all_names())


@pytest.fixture
def context_resolver():
    """Create a context resolver."""
    return ContextResolver()


@pytest.fixture
def logger():
    """Create a telemetry logger."""
    return ResolverLogger()


@pytest.fixture
def pipeline(alias_dict, fuzzy_matcher, phonetic_matcher, context_resolver, card_db, logger):
    """Create a full resolution pipeline."""
    return ResolutionPipeline(
        alias_dict=alias_dict,
        fuzzy_matcher=fuzzy_matcher,
        phonetic_matcher=phonetic_matcher,
        context_resolver=context_resolver,
        card_db=card_db,
        logger=logger,
    )
