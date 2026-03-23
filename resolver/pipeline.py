"""Resolution pipeline orchestrating all 4 tiers of card matching.

This module provides the ResolutionPipeline class which orchestrates:
- Tier 1: Exact alias lookup
- Tier 2: Fuzzy string matching
- Tier 3: Phonetic matching
- Tier 4: Context-aware disambiguation

It also handles deduplication, confidence thresholds, and telemetry logging.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from resolver.alias_dict import AliasDictionary, AliasEntry
from resolver.context import ContextResolver
from resolver.fuzzy import FuzzyMatcher
from resolver.phonetic import PhoneticMatcher
from resolver.text_extract import extract_candidates


@dataclass
class CardEvent:
    """Event representing a card match to be displayed.

    Attributes:
        action: "show" | "hide" | "clear"
        card_id: YGOProDeck card ID (passwd)
        card_name: Official card name
        image_path: Local path to cached card image
        match_source: "alias" | "fuzzy" | "phonetic" | "context"
        match_score: Confidence of the match (0.0 - 1.0)
        timestamp: Time of the match
    """

    action: str
    card_id: int
    card_name: str
    image_path: str
    match_source: str
    match_score: float
    timestamp: float


class ResolutionPipeline:
    """Orchestrates the full 4-tier card resolution pipeline.

    The pipeline processes transcript text through:
    1. Text extraction (n-gram candidate generation)
    2. Tier 1: Alias dictionary lookup
    3. Tier 2: Fuzzy string matching (if no alias hit)
    4. Tier 3: Phonetic matching (if no fuzzy hit)
    5. Tier 4: Context disambiguation (if multiple close matches)
    6. Deduplication (suppress same card within cooldown window)
    7. Confidence filtering (suppress low-confidence matches)
    """

    def __init__(
        self,
        alias_dict: AliasDictionary,
        fuzzy_matcher: FuzzyMatcher,
        phonetic_matcher: PhoneticMatcher,
        context_resolver: ContextResolver,
        card_db,
        logger,
        min_display_confidence: float = 0.75,
        dedup_cooldown_s: float = 10.0,
    ):
        """Initialize the resolution pipeline.

        Args:
            alias_dict: Alias dictionary for Tier 1 lookups
            fuzzy_matcher: Fuzzy matcher for Tier 2
            phonetic_matcher: Phonetic matcher for Tier 3
            context_resolver: Context resolver for Tier 4
            card_db: Card database for metadata lookups
            logger: Telemetry logger for resolution events
            min_display_confidence: Minimum confidence to display a match
            dedup_cooldown_s: Seconds before same card can re-trigger
        """
        self.alias = alias_dict
        self.fuzzy = fuzzy_matcher
        self.phonetic = phonetic_matcher
        self.context = context_resolver
        self.card_db = card_db
        self.logger = logger
        self.min_display_confidence = min_display_confidence
        self.dedup_cooldown_s = dedup_cooldown_s

        # Deduplication window
        self._recent: OrderedDict[int, float] = OrderedDict()

    def resolve(self, transcript: str) -> list[CardEvent]:
        """Resolve card mentions in a transcript.

        Args:
            transcript: The transcript text to resolve

        Returns:
            List of CardEvent objects for matched cards
        """
        events = []
        candidates = extract_candidates(transcript)
        matched_spans: set[str] = set()

        # Sort candidates longest-first for greedy matching
        candidates_sorted = sorted(candidates, key=len, reverse=True)

        for candidate in candidates_sorted:
            # Skip if already matched by a longer span
            if self._overlaps(candidate, matched_spans):
                continue

            # Tier 1: Alias dictionary
            alias_hit = self.alias.lookup(candidate)
            if alias_hit:
                event = self._make_event(alias_hit, "alias", 1.0)
                if event:
                    events.append(event)
                    matched_spans.add(candidate)
                    self.logger.log_resolved(
                        transcript=transcript,
                        card_name=alias_hit.name or "",
                        card_id=alias_hit.id or 0,
                        match_source="alias",
                        match_score=1.0,
                        latency_ms=0.0,  # Alias lookup is negligible
                    )
                continue

            # Skip short candidates for fuzzy/phonetic (too noisy)
            # Require at least 12 characters to avoid false positives on common words
            # This ensures we only fuzzy-match meaningful card name fragments
            if len(candidate) < 12:
                continue

            # Tier 2: Fuzzy matching
            # Use threshold of 88 to avoid false positives on common phrases
            fuzzy_hits = self.fuzzy.match(candidate, threshold=88)
            if fuzzy_hits:
                # Check if there's a clear winner
                if len(fuzzy_hits) == 1 or (
                    len(fuzzy_hits) > 1 and fuzzy_hits[0][1] - fuzzy_hits[1][1] > 10
                ):
                    # Clear winner
                    card_name, score = fuzzy_hits[0]
                    match_score = score / 100.0

                    # Confidence threshold check
                    if match_score < self.min_display_confidence:
                        self.logger.log_unresolved(
                            transcript=transcript,
                            candidates_tried=[candidate],
                            best_fuzzy=(card_name, score),
                        )
                        continue

                    card = self.card_db.get_by_name(card_name)
                    if card:
                        event = self._make_card_event(
                            card, "fuzzy", match_score
                        )
                        if event:
                            events.append(event)
                            matched_spans.add(candidate)
                            self.logger.log_resolved(
                                transcript=transcript,
                                card_name=card_name,
                                card_id=card.id,
                                match_source="fuzzy",
                                match_score=match_score,
                                latency_ms=0.0,
                            )
                    continue

                # Multiple close matches — use context disambiguation (Tier 4)
                # But only if the top match has sufficient confidence
                top_score = fuzzy_hits[0][1] / 100.0
                if top_score < self.min_display_confidence:
                    self.logger.log_unresolved(
                        transcript=transcript,
                        candidates_tried=[candidate],
                        best_fuzzy=fuzzy_hits[0],
                    )
                    continue

                best_name = self.context.disambiguate(fuzzy_hits, self.card_db)
                if best_name:
                    card = self.card_db.get_by_name(best_name)
                    if card:
                        event = self._make_card_event(card, "context", top_score)
                        if event:
                            events.append(event)
                            matched_spans.add(candidate)
                            self.logger.log_resolved(
                                transcript=transcript,
                                card_name=best_name,
                                card_id=card.id,
                                match_source="context",
                                match_score=top_score,
                                latency_ms=0.0,
                            )
                continue

            # Tier 3: Phonetic fallback
            # Phonetic has lower confidence (0.6), only use if above threshold
            if 0.6 >= self.min_display_confidence:
                phonetic_hits = self.phonetic.match(candidate)
                if phonetic_hits:
                    card_name = phonetic_hits[0]
                    card = self.card_db.get_by_name(card_name)
                    if card:
                        event = self._make_card_event(card, "phonetic", 0.6)
                        if event:
                            events.append(event)
                            matched_spans.add(candidate)
                            self.logger.log_resolved(
                                transcript=transcript,
                                card_name=card_name,
                                card_id=card.id,
                                match_source="phonetic",
                                match_score=0.6,
                                latency_ms=0.0,
                            )
                    continue

        # Deduplicate events
        return self._dedup(events)

    def _overlaps(self, candidate: str, matched_spans: set[str]) -> bool:
        """Check if a candidate overlaps with already-matched spans.

        Args:
            candidate: The candidate string
            matched_spans: Set of already-matched spans

        Returns:
            True if the candidate overlaps with any matched span
        """
        for span in matched_spans:
            if candidate in span or span in candidate:
                return True
        return False

    def _make_event(
        self, alias_entry: AliasEntry, source: str, score: float
    ) -> Optional[CardEvent]:
        """Create a CardEvent from an alias entry.

        Args:
            alias_entry: The alias entry
            source: Match source ("alias", "fuzzy", etc.)
            score: Match confidence score

        Returns:
            CardEvent if the alias has a card ID, None otherwise
        """
        if not alias_entry.id or not alias_entry.name:
            return None

        return CardEvent(
            action="show",
            card_id=alias_entry.id,
            card_name=alias_entry.name,
            image_path=f"data/card_images/{alias_entry.id}.jpg",
            match_source=source,
            match_score=score,
            timestamp=time.time(),
        )

    def _make_card_event(
        self, card, source: str, score: float
    ) -> Optional[CardEvent]:
        """Create a CardEvent from a Card object.

        Args:
            card: The Card object
            source: Match source
            score: Match confidence score

        Returns:
            CardEvent
        """
        return CardEvent(
            action="show",
            card_id=card.id,
            card_name=card.name,
            image_path=f"data/card_images/{card.id}.jpg",
            match_source=source,
            match_score=score,
            timestamp=time.time(),
        )

    def _dedup(self, events: list[CardEvent]) -> list[CardEvent]:
        """Deduplicate card events within the cooldown window.

        Args:
            events: List of card events

        Returns:
            Filtered list with duplicates removed
        """
        result = []
        now = time.time()

        for event in events:
            last_shown = self._recent.get(event.card_id)

            # Skip if shown recently
            if last_shown and now - last_shown < self.dedup_cooldown_s:
                continue

            self._recent[event.card_id] = now
            result.append(event)

        # Evict old entries from dedup window
        while self._recent and next(iter(self._recent.values())) < now - 30:
            self._recent.popitem(last=False)

        return result
