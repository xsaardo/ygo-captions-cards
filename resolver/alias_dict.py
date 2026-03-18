"""Alias dictionary for Tier 1 card name resolution.

This module provides exact O(1) lookup of card names from community aliases,
abbreviations, slang, and common STT transcription errors.
"""

import json
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AliasEntry:
    """Represents an alias dictionary entry.

    An entry can either map to a specific card (with id and name fields)
    or to an archetype (with archetype field).
    """

    id: Optional[int] = None
    name: Optional[str] = None
    archetype: Optional[str] = None
    confidence: float = 1.0
    source: str = "unknown"
    added: str = ""
    last_verified: str = ""


def normalize(text: str) -> str:
    """Normalize text for case-insensitive, punctuation-agnostic matching.

    Lowercases and removes punctuation (except spaces) for consistent matching.
    This allows "Maxx C" to match "maxx c", "Ash Blossom" to match "ash blossom", etc.

    Args:
        text: The text to normalize

    Returns:
        Normalized text (lowercase, no punctuation except spaces)
    """
    # Lowercase
    text = text.lower()

    # Remove all punctuation except spaces
    # This handles quotes, apostrophes, ampersands, etc.
    text = re.sub(f"[{re.escape(string.punctuation)}]", "", text)

    # Collapse multiple spaces into one
    text = re.sub(r"\s+", " ", text)

    return text.strip()


class AliasDictionary:
    """Dictionary for exact alias lookups.

    Provides O(1) lookup of card names from aliases, with normalization
    to handle case-insensitivity and punctuation variations.

    Note: For Tier 2 fuzzy matching, use the FuzzyMatcher class (not yet implemented).
    """

    def __init__(self, path: str = "data/aliases.json"):
        """Initialize the alias dictionary from a JSON file.

        Args:
            path: Path to the aliases.json file
        """
        self.path = Path(path)
        self._map: dict[str, AliasEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load and index the alias dictionary."""
        if not self.path.exists():
            return

        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract entries from the JSON structure
        entries = data.get("entries", {})

        for alias, entry_data in entries.items():
            # Normalize the alias for consistent lookup
            normalized_alias = normalize(alias)

            # Create an AliasEntry from the JSON data
            entry = AliasEntry(
                id=entry_data.get("id"),
                name=entry_data.get("name"),
                archetype=entry_data.get("archetype"),
                confidence=entry_data.get("confidence", 1.0),
                source=entry_data.get("source", "unknown"),
                added=entry_data.get("added", ""),
                last_verified=entry_data.get("last_verified", ""),
            )

            self._map[normalized_alias] = entry

    def lookup(self, text: str) -> Optional[AliasEntry]:
        """Look up a card or archetype by alias.

        Args:
            text: The alias to look up (will be normalized)

        Returns:
            AliasEntry if found, None otherwise
        """
        normalized = normalize(text)
        return self._map.get(normalized)
