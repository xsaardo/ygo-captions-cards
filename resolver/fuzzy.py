"""Fuzzy string matching for Tier 2 card name resolution.

This module provides fuzzy matching using rapidfuzz's WRatio scorer with
length-based penalties for short query / long candidate pairs.
"""

from rapidfuzz import fuzz, process


def score_match(query: str, candidate: str, **kwargs) -> float:
    """Score a fuzzy match between query and candidate with length penalty.

    Uses WRatio (weighted combination) which handles both short and long queries
    well, but adds an explicit length penalty for short query / long candidate
    pairs to avoid false positives.

    Args:
        query: The query string
        candidate: The candidate string to match against
        **kwargs: Additional kwargs from rapidfuzz (ignored)

    Returns:
        Match score from 0-100
    """
    base_score = fuzz.WRatio(query.lower(), candidate.lower())

    # Penalize short queries matching long candidates
    # e.g. "Ash" (3 chars) vs "Ash Blossom & Joyous Spring" (27 chars)
    length_ratio = len(query) / max(len(candidate), 1)
    if length_ratio < 0.3:
        penalty = 20 * (1 - length_ratio)
        return max(0, base_score - penalty)

    return base_score


class FuzzyMatcher:
    """Fuzzy string matcher for card names using rapidfuzz.

    Pre-builds a token index for fast pre-filtering before fuzzy matching,
    reducing the search space from ~13k cards to ~500 candidates.

    Performance note: With pre-filtering, fuzzy matching completes in ~0.5ms
    instead of ~5ms for the full card database.
    """

    def __init__(self, card_names: list[str]):
        """Initialize the fuzzy matcher with card names.

        Args:
            card_names: List of all card names from the card database
        """
        self._names = card_names
        self._names_lower = [n.lower() for n in card_names]

        # Build token index for pre-filtering: token -> set of card indices
        self._token_index: dict[str, set[int]] = {}
        for idx, name in enumerate(self._names_lower):
            tokens = name.split()
            for token in tokens:
                if token not in self._token_index:
                    self._token_index[token] = set()
                self._token_index[token].add(idx)

    def _prefilter(self, query: str) -> list[tuple[str, int]]:
        """Pre-filter candidates to those sharing at least one token with query.

        Args:
            query: The query string

        Returns:
            List of (candidate_name, index) tuples that share tokens with query
        """
        query_tokens = set(query.lower().split())
        candidate_indices: set[int] = set()

        for token in query_tokens:
            candidate_indices |= self._token_index.get(token, set())

        # Return candidates with their original indices for mapping back
        return [(self._names_lower[idx], idx) for idx in candidate_indices]

    def match(self, query: str, threshold: int = 80) -> list[tuple[str, float]]:
        """Find fuzzy matches for a query string.

        Args:
            query: The query string to match
            threshold: Minimum score (0-100) to include in results

        Returns:
            List of (card_name, score) tuples sorted by score (highest first)
        """
        if not query or not query.strip():
            return []

        # Pre-filter candidates
        candidates = self._prefilter(query)

        # If no candidates share tokens, return empty
        if not candidates:
            return []

        # Extract just the names for fuzzy matching
        candidate_names = [name for name, _ in candidates]
        candidate_indices = [idx for _, idx in candidates]

        # Run fuzzy matching on pre-filtered candidates
        results = process.extract(
            query.lower(),
            candidate_names,
            scorer=score_match,
            limit=5,
            score_cutoff=threshold,
        )

        # Map back to original-cased names using the indices
        return [
            (self._names[candidate_indices[idx]], score)
            for _, score, idx in results
        ]
