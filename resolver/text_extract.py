"""Text extraction for candidate card mentions.

This module provides functions to extract candidate card name phrases from
free-form transcript text using a sliding n-gram window approach.
"""

from resolver.alias_dict import normalize


def extract_candidates(text: str, max_ngram: int = 6) -> list[str]:
    """Generate candidate phrases from transcript text using n-grams.

    Given "he activates Ash Blossom in response to the Snake Eye play",
    yields: ["he", "he activates", "he activates ash", ...,
             "ash", "ash blossom", "ash blossom in", ...,
             "snake", "snake eye", "snake eye play", ...]

    The resolver tests each candidate against the alias dict and card DB.
    Short-circuits on alias dict hits to avoid unnecessary fuzzy matching.

    Args:
        text: The transcript text to extract candidates from
        max_ngram: Maximum n-gram size (default: 6 for card names like
                   "Number 86: Heroic Champion Rhongomyniad")

    Returns:
        List of candidate phrases (normalized)
    """
    # Normalize and tokenize
    normalized_text = normalize(text)
    tokens = normalized_text.split()

    if not tokens:
        return []

    candidates = []

    # Generate all n-grams from 1 to max_ngram
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + max_ngram + 1, len(tokens) + 1)):
            candidate = " ".join(tokens[i:j])
            candidates.append(candidate)

    return candidates


def prefilter_candidates(
    query_tokens: set[str], card_name_tokens: dict[str, set[int]]
) -> list[str]:
    """Pre-filter card names to those sharing at least one token with the query.

    This is a performance optimization for Tier 2 fuzzy matching. Instead of
    comparing against all 13k cards, we first filter to ~500 candidates that
    share at least one word with the query.

    This function is not used in Part 1 (alias-dict only), but is set up for
    future Tier 2 implementation.

    Args:
        query_tokens: Set of tokens from the query (normalized)
        card_name_tokens: Map of token -> set of card indices that contain that token

    Returns:
        List of card names that share at least one token with the query
    """
    # NOTE: This function signature is included per the spec, but is not
    # implemented or used in Part 1. It will be wired up when fuzzy matching
    # is added in Part 2.
    raise NotImplementedError(
        "prefilter_candidates will be implemented in Part 2 (Tier 2 fuzzy matching)"
    )
