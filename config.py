"""Runtime configuration for the YGO card overlay system.

This module defines the configuration dataclass that controls all runtime behavior
including STT settings, resolver parameters, overlay display, and audio capture.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Configuration for the YGO card overlay system.

    Supports loading from environment variables and CLI arguments.
    """

    # STT
    stt_provider: str = "deepgram"  # "deepgram" | "assemblyai"
    stt_api_key: str = field(default_factory=lambda: os.getenv("STT_API_KEY", ""))
    stt_model: str = "nova-3"

    # Resolver
    alias_path: str = "data/aliases.json"
    fuzzy_threshold: int = 80  # Minimum score for fuzzy match
    fuzzy_single_token_threshold: int = 90  # Higher threshold for 1-word queries
    phonetic_enabled: bool = True
    dedup_cooldown_s: float = 10.0  # Seconds before same card can re-trigger
    min_display_confidence: float = 0.75  # Suppress matches below this threshold
    interim_debounce_ms: int = 200  # Min age of interim transcript before resolving
    interim_finalization_timeout_s: float = 2.0  # Treat stale interim as final after this

    # Context
    player1_deck: str = ""  # Archetype name, set per match
    player2_deck: str = ""

    # Overlay
    overlay_port: int = 9090
    display_mode: str = "latest"  # "latest" | "queue" | "stack"
    hold_duration_ms: int = 5000
    max_visible_cards: int = 3  # For "stack" mode
    card_images_baseline_path: str = "data/cards_baseline.json"  # Fallback if API down

    # Audio
    audio_source: str = "default"  # PulseAudio source name
    audio_sample_rate: int = 16000
    audio_chunk_ms: int = 100  # Chunk size in milliseconds

    @classmethod
    def from_cli_args(cls, **kwargs) -> "Config":
        """Create a Config instance from CLI arguments.

        Args:
            **kwargs: CLI arguments to override defaults

        Returns:
            Config instance with CLI args applied
        """
        config = cls()
        for key, value in kwargs.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)
        return config

    @classmethod
    def from_env(cls) -> "Config":
        """Create a Config instance from environment variables.

        Returns:
            Config instance with environment variables applied
        """
        return cls(
            stt_api_key=os.getenv("STT_API_KEY", ""),
            stt_provider=os.getenv("STT_PROVIDER", "deepgram"),
            overlay_port=int(os.getenv("OVERLAY_PORT", "9090")),
            player1_deck=os.getenv("PLAYER1_DECK", ""),
            player2_deck=os.getenv("PLAYER2_DECK", ""),
        )
