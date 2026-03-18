"""Structured JSON logger for card resolution telemetry.

This module provides structured logging of resolution attempts (both successful
and failed) to a JSONL file for post-tournament analysis and alias dictionary
improvements.
"""

import json
import time
from pathlib import Path
from typing import Any, Optional


class ResolverLogger:
    """Structured JSON logger for card resolution events.

    Writes JSONL (JSON Lines) format logs to track:
    - Successful resolutions (for performance metrics)
    - Unresolved segments (for alias dictionary gap analysis)
    """

    def __init__(self, log_path: str = "logs/resolver.jsonl"):
        """Initialize the resolver logger.

        Args:
            log_path: Path to the JSONL log file
        """
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_resolved(
        self,
        transcript: str,
        card_name: str,
        card_id: int,
        match_source: str,
        match_score: float,
        latency_ms: float,
    ) -> None:
        """Log a successful card resolution.

        Args:
            transcript: The original transcript text
            card_name: The matched card name
            card_id: The matched card ID
            match_source: Source of the match (alias, fuzzy, phonetic, context)
            match_score: Confidence score (0.0-1.0)
            latency_ms: Resolution latency in milliseconds
        """
        entry = {
            "event": "card_resolved",
            "timestamp": time.time(),
            "transcript": transcript,
            "card_name": card_name,
            "card_id": card_id,
            "match_source": match_source,
            "match_score": match_score,
            "latency_ms": latency_ms,
        }

        self._write(entry)

    def log_unresolved(
        self,
        transcript: str,
        candidates_tried: list[str],
        best_fuzzy: Optional[tuple[str, float]] = None,
    ) -> None:
        """Log an unresolved transcript segment.

        This is valuable for identifying gaps in the alias dictionary.

        Args:
            transcript: The original transcript text
            candidates_tried: List of candidate phrases that were tried
            best_fuzzy: Best fuzzy match (name, score) if any, else None
        """
        entry = {
            "event": "unresolved_segment",
            "timestamp": time.time(),
            "transcript": transcript,
            "candidates_tried": candidates_tried,
        }

        if best_fuzzy:
            entry["best_fuzzy"] = {"name": best_fuzzy[0], "score": best_fuzzy[1]}

        self._write(entry)

    def _write(self, entry: dict[str, Any]) -> None:
        """Write a log entry to the JSONL file.

        Args:
            entry: The log entry to write
        """
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
