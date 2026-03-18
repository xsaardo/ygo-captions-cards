"""Card database loader and search index.

This module provides the CardDatabase class which loads card data from YGOProDeck
and maintains efficient lookup indexes by ID, name, and archetype.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Card:
    """Represents a Yu-Gi-Oh! card with all relevant metadata."""

    id: int
    name: str
    type: str
    desc: str
    archetype: Optional[str] = None
    atk: Optional[int] = None
    def_: Optional[int] = None
    level: Optional[int] = None
    race: Optional[str] = None
    attribute: Optional[str] = None


class CardDatabase:
    """Card database with efficient lookup indexes.

    Loads card data from local cache (data/cards.json) and builds indexes
    for fast lookups by ID, name, and archetype.
    """

    def __init__(self, db_path: str = "data/cards.json"):
        """Initialize the card database.

        Args:
            db_path: Path to the local card database JSON file
        """
        self.db_path = Path(db_path)
        self._cards: dict[int, Card] = {}  # id -> Card
        self._by_name: dict[str, Card] = {}  # lowercase name -> Card
        self._names: list[str] = []  # for fuzzy matching
        self._archetype_index: dict[str, list[Card]] = {}  # archetype -> [Cards]

    def initialize(self) -> None:
        """Load card database from local cache if available.

        For Part 1, this only loads from the local cache. The YGOProDeck
        download functionality is implemented in scripts/download_cards.py.
        """
        if self.db_path.exists():
            self._load_from_cache()
            self._build_indexes()
        else:
            # Create an empty database for Part 1
            # In Part 2, this would trigger a download
            pass

    def _load_from_cache(self) -> None:
        """Load card data from local JSON cache."""
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # YGOProDeck API returns {"data": [cards...]}
        cards_data = data.get("data", [])

        for card_dict in cards_data:
            card = Card(
                id=card_dict["id"],
                name=card_dict["name"],
                type=card_dict["type"],
                desc=card_dict.get("desc", ""),
                archetype=card_dict.get("archetype"),
                atk=card_dict.get("atk"),
                def_=card_dict.get("def"),
                level=card_dict.get("level"),
                race=card_dict.get("race"),
                attribute=card_dict.get("attribute"),
            )
            self._cards[card.id] = card

    def _build_indexes(self) -> None:
        """Build lookup indexes after loading cards."""
        for card in self._cards.values():
            # Name index (lowercase for case-insensitive lookup)
            self._by_name[card.name.lower()] = card
            self._names.append(card.name)

            # Archetype index
            if card.archetype:
                if card.archetype not in self._archetype_index:
                    self._archetype_index[card.archetype] = []
                self._archetype_index[card.archetype].append(card)

    def get_by_id(self, card_id: int) -> Optional[Card]:
        """Get a card by its YGOProDeck ID.

        Args:
            card_id: The card's password/ID

        Returns:
            Card object if found, None otherwise
        """
        return self._cards.get(card_id)

    def get_by_name(self, name: str) -> Optional[Card]:
        """Get a card by its name (case-insensitive).

        Args:
            name: The card name

        Returns:
            Card object if found, None otherwise
        """
        return self._by_name.get(name.lower())

    def all_names(self) -> list[str]:
        """Get list of all card names for fuzzy matching.

        Returns:
            List of all card names in the database
        """
        return self._names

    def cards_in_archetype(self, archetype: str) -> list[Card]:
        """Get all cards belonging to an archetype.

        Args:
            archetype: The archetype name (e.g., "Snake-Eye")

        Returns:
            List of cards in that archetype
        """
        return self._archetype_index.get(archetype, [])
