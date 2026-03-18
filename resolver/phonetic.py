"""Phonetic matching for Tier 3 card name resolution.

This module provides phonetic matching using Double Metaphone encoding to catch
STT transcription errors like "Nibirue" → "Nibiru" or "Ash Blossum" → "Ash Blossom".
"""

import jellyfish


class PhoneticMatcher:
    """Phonetic matcher using Double Metaphone encoding.

    Pre-encodes all card name tokens (unigrams and bigrams) with phonetic codes
    to enable fast matching of phonetically similar card names.

    The bigram encoding reduces false positives from unrelated cards that happen
    to share individual phonetic tokens.
    """

    def __init__(self, card_names: list[str]):
        """Initialize the phonetic matcher with card names.

        Args:
            card_names: List of all card names from the card database
        """
        self._index: dict[str, list[tuple[str, int]]] = {}  # phonetic_code -> [(card_name, token_pos)]

        for name in card_names:
            tokens = name.lower().split()

            # Encode individual tokens (unigrams)
            for i, token in enumerate(tokens):
                code = jellyfish.metaphone(token)
                if code:
                    if code not in self._index:
                        self._index[code] = []
                    self._index[code].append((name, i))

            # Encode consecutive token pairs (bigrams) to reduce false positives
            for i in range(len(tokens) - 1):
                bigram_code = jellyfish.metaphone(tokens[i]) + "_" + jellyfish.metaphone(tokens[i + 1])
                if bigram_code:
                    if bigram_code not in self._index:
                        self._index[bigram_code] = []
                    self._index[bigram_code].append((name, i))

    def match(self, query: str, min_token_match_fraction: float = 0.5) -> list[str]:
        """Find phonetically similar card names.

        Args:
            query: The query string to match phonetically
            min_token_match_fraction: Minimum fraction of query tokens that must
                                       match phonetically (default: 0.5)

        Returns:
            List of card names that match phonetically, sorted by match count
        """
        if not query or not query.strip():
            return []

        query_tokens = query.lower().split()
        if not query_tokens:
            return []

        # Count phonetic matches per card
        candidates: dict[str, int] = {}  # card_name -> matching_token_count

        for token in query_tokens:
            code = jellyfish.metaphone(token)
            if code and code in self._index:
                for card_name, _ in self._index[code]:
                    candidates[card_name] = candidates.get(card_name, 0) + 1

        # Filter by minimum match fraction
        min_matches = max(1, int(len(query_tokens) * min_token_match_fraction))
        filtered = [
            (name, count)
            for name, count in candidates.items()
            if count >= min_matches
        ]

        # Sort by match count (highest first)
        filtered.sort(key=lambda x: x[1], reverse=True)

        return [name for name, _ in filtered]
