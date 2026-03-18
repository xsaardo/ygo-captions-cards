"""Abstract base classes for STT client implementations.

This module defines the interface that all STT clients must implement,
as well as the TranscriptEvent dataclass for transcript results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class TranscriptEvent:
    """Represents a transcript event from the STT service.

    Attributes:
        text: The transcribed text segment
        is_final: True if this is a finalized transcript (not interim)
        timestamp: Time of utterance (from STT or wall clock)
        confidence: STT confidence score (0.0 - 1.0)
    """

    text: str
    is_final: bool
    timestamp: float
    confidence: float


class STTClient(ABC):
    """Abstract base class for STT client implementations.

    All STT clients (Deepgram, AssemblyAI, etc.) must implement this interface
    to enable swappable STT providers.
    """

    @abstractmethod
    async def connect(self, keyterms: list[str]) -> None:
        """Connect to the STT service and start streaming.

        Args:
            keyterms: List of keyterms to boost recognition (e.g., card names)
        """
        pass

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Send an audio chunk to the STT service.

        Args:
            chunk: Raw audio data (PCM 16-bit signed little-endian)
        """
        pass

    @abstractmethod
    async def receive_transcripts(self) -> AsyncIterator[TranscriptEvent]:
        """Receive transcript events from the STT service.

        Yields:
            TranscriptEvent objects as they arrive
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the STT service and clean up resources."""
        pass


def build_keyterm_list(
    player1_deck_cards: list[str],
    player2_deck_cards: list[str],
    staples: list[str],
    limit: int = 100,
) -> list[str]:
    """Build a prioritized keyterm list for STT keyword boosting.

    Priority ordering when deck size exceeds limit:
    1. Main deck archetype cards (both players)
    2. Extra deck boss monsters (both players)
    3. Universal staples (hand traps, board breakers)
    4. Side deck tech cards
    5. Generic utility cards (lowest priority)

    Args:
        player1_deck_cards: Card names from player 1's deck
        player2_deck_cards: Card names from player 2's deck
        staples: Universal staple card names
        limit: Maximum number of keyterms (default: 100)

    Returns:
        List of keyterm strings, prioritized and deduplicated
    """
    # For simplicity, just concatenate and deduplicate
    # In a real implementation, you'd prioritize by card type
    priority_ordered = player1_deck_cards + player2_deck_cards + staples

    seen = set()
    result = []

    for card in priority_ordered:
        if card not in seen and len(result) < limit:
            seen.add(card)
            result.append(card)

    return result
