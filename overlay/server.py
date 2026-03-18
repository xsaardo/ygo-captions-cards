"""Overlay HTTP and WebSocket server.

This module provides an aiohttp-based server that:
- Serves the overlay HTML/CSS/JS to OBS Browser Sources
- Accepts WebSocket connections from overlay clients
- Broadcasts card events to all connected clients
- Provides a control API for testing and manual card triggers
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Set

from aiohttp import web

from data.card_db import CardDatabase
from data.image_cache import ImageCache
from resolver.alias_dict import AliasDictionary
from resolver.text_extract import extract_candidates
from telemetry.logger import ResolverLogger


class OverlayServer:
    """HTTP + WebSocket server for the card overlay."""

    def __init__(
        self,
        alias_dict: AliasDictionary,
        card_db: CardDatabase,
        image_cache: ImageCache,
        logger: ResolverLogger,
        port: int = 9090,
    ):
        """Initialize the overlay server.

        Args:
            alias_dict: Alias dictionary for card resolution
            card_db: Card database
            image_cache: Image cache
            logger: Telemetry logger
            port: Port to listen on
        """
        self.alias_dict = alias_dict
        self.card_db = card_db
        self.image_cache = image_cache
        self.logger = logger
        self.port = port
        self.clients: Set[web.WebSocketResponse] = set()
        self.app = web.Application()
        self._setup_routes()

        # Match context
        self.player1_deck = ""
        self.player2_deck = ""

    def _setup_routes(self) -> None:
        """Set up HTTP routes."""
        self.app.router.add_get("/overlay", self._serve_overlay)
        self.app.router.add_get("/ws", self._websocket_handler)
        self.app.router.add_post("/api/match", self._set_match_context)
        self.app.router.add_post("/api/clear", self._clear_overlay)
        self.app.router.add_post("/api/show", self._manual_show)
        self.app.router.add_post("/api/resolve", self._resolve_transcript)
        self.app.router.add_get("/api/status", self._get_status)
        self.app.router.add_static(
            "/static", Path(__file__).parent / "static", name="static"
        )
        self.app.router.add_static(
            "/cards", Path("data/card_images"), name="cards"
        )

    async def _serve_overlay(self, request: web.Request) -> web.Response:
        """Serve the overlay HTML page.

        Args:
            request: HTTP request

        Returns:
            HTML response
        """
        overlay_path = Path(__file__).parent / "static" / "overlay.html"
        return web.FileResponse(overlay_path)

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections from overlay clients.

        Args:
            request: HTTP request

        Returns:
            WebSocket response
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.clients.add(ws)

        try:
            async for msg in ws:
                # Overlay clients don't send messages, just receive
                pass
        finally:
            self.clients.discard(ws)

        return ws

    async def _set_match_context(self, request: web.Request) -> web.Response:
        """Set match context (player decks).

        Request body: {"player1_deck": "Snake-Eye", "player2_deck": "Yubel"}

        Args:
            request: HTTP request

        Returns:
            JSON response
        """
        data = await request.json()
        self.player1_deck = data.get("player1_deck", "")
        self.player2_deck = data.get("player2_deck", "")

        return web.json_response(
            {"status": "ok", "player1_deck": self.player1_deck, "player2_deck": self.player2_deck}
        )

    async def _clear_overlay(self, request: web.Request) -> web.Response:
        """Clear all displayed cards.

        Args:
            request: HTTP request

        Returns:
            JSON response
        """
        await self._broadcast({"action": "clear"})
        return web.json_response({"status": "ok"})

    async def _manual_show(self, request: web.Request) -> web.Response:
        """Manually show a card.

        Request body: {"card_id": 14558127} or {"card_name": "Ash Blossom"}

        Args:
            request: HTTP request

        Returns:
            JSON response
        """
        data = await request.json()

        card_id = data.get("card_id")
        card_name = data.get("card_name")

        card = None
        if card_id:
            card = self.card_db.get_by_id(card_id)
        elif card_name:
            card = self.card_db.get_by_name(card_name)

        if not card:
            return web.json_response(
                {"status": "error", "message": "Card not found"}, status=404
            )

        await self._show_card(card.id, card.name, "manual", 1.0)
        return web.json_response({"status": "ok", "card_name": card.name})

    async def _resolve_transcript(self, request: web.Request) -> web.Response:
        """Resolve a transcript and show matched cards.

        This is the main endpoint for Part 1 testing.

        Request body: {"transcript": "he activates ash blossom"}

        Args:
            request: HTTP request

        Returns:
            JSON response with matched cards
        """
        data = await request.json()
        transcript = data.get("transcript", "")

        if not transcript:
            return web.json_response(
                {"status": "error", "message": "No transcript provided"}, status=400
            )

        start_time = time.time()

        # Extract candidates
        candidates = extract_candidates(transcript)

        # Try to match against alias dictionary
        # Sort longest-first for greedy matching
        candidates_sorted = sorted(candidates, key=len, reverse=True)

        matched_cards = []
        for candidate in candidates_sorted:
            entry = self.alias_dict.lookup(candidate)
            if entry and entry.id:
                # Found a card match
                card = self.card_db.get_by_id(entry.id)
                if card:
                    latency_ms = (time.time() - start_time) * 1000
                    matched_cards.append(
                        {
                            "card_id": card.id,
                            "card_name": card.name,
                            "match_source": "alias",
                            "match_score": entry.confidence,
                        }
                    )

                    # Log the resolution
                    self.logger.log_resolved(
                        transcript=transcript,
                        card_name=card.name,
                        card_id=card.id,
                        match_source="alias",
                        match_score=entry.confidence,
                        latency_ms=latency_ms,
                    )

                    # Show the card
                    await self._show_card(
                        card.id, card.name, "alias", entry.confidence
                    )

                    # For Part 1, only show the first match
                    break

        if not matched_cards:
            # Log unresolved
            self.logger.log_unresolved(
                transcript=transcript, candidates_tried=candidates_sorted[:10]
            )

        return web.json_response(
            {"status": "ok", "matched_cards": matched_cards, "transcript": transcript}
        )

    async def _get_status(self, request: web.Request) -> web.Response:
        """Get current server status.

        Args:
            request: HTTP request

        Returns:
            JSON response
        """
        return web.json_response(
            {
                "status": "ok",
                "connected_clients": len(self.clients),
                "player1_deck": self.player1_deck,
                "player2_deck": self.player2_deck,
            }
        )

    async def _show_card(
        self, card_id: int, card_name: str, match_source: str, match_score: float
    ) -> None:
        """Broadcast a showCard event to all connected clients.

        Args:
            card_id: The card ID
            card_name: The card name
            match_source: How the card was matched (alias, fuzzy, etc.)
            match_score: Confidence score (0.0-1.0)
        """
        message = {
            "action": "showCard",
            "cardId": card_id,
            "cardName": card_name,
            "imageUrl": f"/cards/{card_id}.jpg",
            "matchSource": match_source,
            "matchScore": match_score,
        }

        await self._broadcast(message)

    async def _broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected WebSocket clients.

        Uses the FIXED implementation from the design review that properly
        handles exceptions and evicts dead clients.

        Args:
            message: The message to broadcast
        """
        if not self.clients:
            return

        payload = json.dumps(message)
        dead_clients = set()

        # Gather all sends with return_exceptions=True
        results = await asyncio.gather(
            *(ws.send_str(payload) for ws in self.clients),
            return_exceptions=True,
        )

        # Evict clients that errored
        for ws, result in zip(list(self.clients), results):
            if isinstance(result, Exception):
                dead_clients.add(ws)

        self.clients -= dead_clients

    async def start(self) -> None:
        """Start the overlay server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self.port)
        await site.start()
        print(f"Overlay server started at http://localhost:{self.port}/overlay")

    async def stop(self) -> None:
        """Stop the overlay server and close all WebSocket connections."""
        # Close all WebSocket connections
        await asyncio.gather(
            *(ws.close() for ws in self.clients), return_exceptions=True
        )
        self.clients.clear()
