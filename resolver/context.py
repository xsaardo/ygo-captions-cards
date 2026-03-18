"""Context-aware disambiguation for Tier 4 card resolution.

This module provides context-based disambiguation when multiple cards match
with similar scores. It prefers cards from active deck archetypes.
"""

from typing import Optional


class ContextResolver:
    """Context-aware card resolver.

    Uses match context (player deck archetypes) to disambiguate between
    multiple candidate cards with similar fuzzy match scores.
    """

    def __init__(self):
        """Initialize the context resolver."""
        self._active_archetypes: list[str] = []

    def set_match_context(self, player1_deck: str, player2_deck: str) -> None:
        """Set the match context with player deck archetypes.

        This should be called at the start of each match to enable
        context-aware disambiguation.

        Args:
            player1_deck: Player 1's deck archetype (e.g., "Snake-Eye")
            player2_deck: Player 2's deck archetype (e.g., "Yubel")
        """
        self._active_archetypes = [
            deck for deck in [player1_deck, player2_deck] if deck
        ]

    def disambiguate(self, candidates: list[tuple[str, float]], card_db) -> Optional[str]:
        """Disambiguate between multiple candidate cards.

        Given multiple fuzzy match candidates with similar scores, prefer
        cards belonging to currently active deck archetypes.

        Args:
            candidates: List of (card_name, score) tuples from fuzzy matching
            card_db: CardDatabase instance for looking up card archetypes

        Returns:
            The best card name, or None if no candidates
        """
        if not candidates:
            return None

        # If no active archetypes are set, return the highest-scoring candidate
        if not self._active_archetypes:
            return candidates[0][0]

        # Check candidates in order for archetype matches
        for name, score in candidates:
            card = card_db.get_by_name(name)
            if card and card.archetype in self._active_archetypes:
                return name

        # No archetype match — return highest-scoring candidate
        return candidates[0][0]
