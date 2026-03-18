"""Main entry point for the YGO card overlay system.

This module initializes all components (alias dict, fuzzy matcher, phonetic matcher,
context resolver, resolution pipeline, and optionally STT client) and starts the
overlay server with full 4-tier card resolution.
"""

import argparse
import asyncio
import signal
import sys
from typing import Optional

from config import Config
from data.card_db import CardDatabase
from data.image_cache import ImageCache
from overlay.server import OverlayServer
from resolver.alias_dict import AliasDictionary
from resolver.context import ContextResolver
from resolver.fuzzy import FuzzyMatcher
from resolver.phonetic import PhoneticMatcher
from resolver.pipeline import ResolutionPipeline
from telemetry.logger import ResolverLogger


async def shutdown(server: OverlayServer, stt_client: Optional = None) -> None:
    """Gracefully shut down the server and STT client.

    Args:
        server: The overlay server to shut down
        stt_client: Optional STT client to disconnect
    """
    print("\nShutting down...")

    if stt_client:
        try:
            await stt_client.disconnect()
        except Exception as e:
            print(f"Error disconnecting STT client: {e}")

    await server.stop()


async def main() -> None:
    """Main entry point."""
    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="YGO Commentary Card Overlay - Part 2"
    )
    parser.add_argument(
        "--overlay-port",
        type=int,
        default=9090,
        help="Port for the overlay server (default: 9090)",
    )
    parser.add_argument(
        "--player1-deck", type=str, default="", help="Player 1 deck archetype"
    )
    parser.add_argument(
        "--player2-deck", type=str, default="", help="Player 2 deck archetype"
    )
    parser.add_argument(
        "--stt-provider",
        type=str,
        choices=["deepgram", "assemblyai"],
        help="STT provider to use (requires STT_API_KEY environment variable)",
    )
    parser.add_argument(
        "--stt-api-key",
        type=str,
        help="STT API key (or set STT_API_KEY environment variable)",
    )

    args = parser.parse_args()

    # Load configuration
    config = Config.from_cli_args(
        overlay_port=args.overlay_port,
        player1_deck=args.player1_deck,
        player2_deck=args.player2_deck,
        stt_provider=args.stt_provider or config.Config().stt_provider,
        stt_api_key=args.stt_api_key or config.Config().stt_api_key,
    )

    print("YGO Card Overlay - Part 2")
    print("=" * 50)

    # Initialize components
    print("Loading alias dictionary...")
    alias_dict = AliasDictionary(config.alias_path)

    print("Initializing card database...")
    card_db = CardDatabase()
    card_db.initialize()

    print("Initializing image cache...")
    image_cache = ImageCache()

    print("Building fuzzy matcher...")
    fuzzy_matcher = FuzzyMatcher(card_db.all_names())

    print("Building phonetic matcher...")
    phonetic_matcher = PhoneticMatcher(card_db.all_names())

    print("Initializing context resolver...")
    context_resolver = ContextResolver()

    print("Initializing telemetry logger...")
    logger = ResolverLogger()

    print("Initializing resolution pipeline...")
    pipeline = ResolutionPipeline(
        alias_dict=alias_dict,
        fuzzy_matcher=fuzzy_matcher,
        phonetic_matcher=phonetic_matcher,
        context_resolver=context_resolver,
        card_db=card_db,
        logger=logger,
        min_display_confidence=config.min_display_confidence,
        dedup_cooldown_s=config.dedup_cooldown_s,
    )

    # Update the overlay server to use the full pipeline
    # Note: We need to modify the server to accept the pipeline
    # For now, create a wrapper that provides the old interface
    class PipelineWrapper:
        """Wrapper to provide backward compatibility with old server interface."""
        def __init__(self, pipeline, card_db):
            self.pipeline = pipeline
            self.card_db = card_db

        async def resolve_and_broadcast(self, transcript: str, server):
            """Resolve transcript and broadcast card events."""
            events = self.pipeline.resolve(transcript)
            for event in events:
                await server._show_card(
                    event.card_id,
                    event.card_name,
                    event.match_source,
                    event.match_score,
                )
            return events

    pipeline_wrapper = PipelineWrapper(pipeline, card_db)

    # Start overlay server
    print(f"Starting overlay server on port {config.overlay_port}...")
    server = OverlayServer(
        alias_dict=alias_dict,
        card_db=card_db,
        image_cache=image_cache,
        logger=logger,
        port=config.overlay_port,
    )

    # Monkey-patch the server to use the full pipeline for /api/resolve
    original_resolve = server._resolve_transcript

    async def new_resolve_transcript(request):
        """Updated resolve endpoint using full pipeline."""
        import time
        from aiohttp import web

        data = await request.json()
        transcript = data.get("transcript", "")

        if not transcript:
            return web.json_response(
                {"status": "error", "message": "No transcript provided"}, status=400
            )

        start_time = time.time()
        events = pipeline.resolve(transcript)

        matched_cards = []
        for event in events:
            matched_cards.append({
                "card_id": event.card_id,
                "card_name": event.card_name,
                "match_source": event.match_source,
                "match_score": event.match_score,
            })

            # Show the card
            await server._show_card(
                event.card_id,
                event.card_name,
                event.match_source,
                event.match_score,
            )

        return web.json_response(
            {"status": "ok", "matched_cards": matched_cards, "transcript": transcript}
        )

    server._resolve_transcript = new_resolve_transcript

    # Set match context if provided
    if config.player1_deck or config.player2_deck:
        server.player1_deck = config.player1_deck
        server.player2_deck = config.player2_deck
        context_resolver.set_match_context(config.player1_deck, config.player2_deck)
        print(f"Match context: {config.player1_deck} vs {config.player2_deck}")

    # Update /api/match to also update context resolver
    original_set_match = server._set_match_context

    async def new_set_match_context(request):
        response = await original_set_match(request)
        context_resolver.set_match_context(server.player1_deck, server.player2_deck)
        return response

    server._set_match_context = new_set_match_context

    await server.start()

    print("=" * 50)
    print(f"Overlay URL: http://localhost:{config.overlay_port}/overlay")
    print(f"Test API: POST http://localhost:{config.overlay_port}/api/resolve")
    print('  Example: curl -X POST -H "Content-Type: application/json" \\')
    print(
        f'    -d \'{{"transcript": "he activates ash blossom"}}\' \\'
    )
    print(f"    http://localhost:{config.overlay_port}/api/resolve")

    # Initialize STT client if configured
    stt_client = None
    if args.stt_provider and config.stt_api_key:
        print(f"\nInitializing {args.stt_provider} STT client...")

        if args.stt_provider == "deepgram":
            from stt.deepgram_client import DeepgramClient
            stt_client = DeepgramClient(config.stt_api_key, config.stt_model)
        elif args.stt_provider == "assemblyai":
            from stt.assemblyai_client import AssemblyAIClient
            stt_client = AssemblyAIClient(config.stt_api_key)

        # TODO: Wire up audio capture and transcript processing
        # This would involve:
        # 1. Starting ffmpeg to capture system audio
        # 2. Piping audio chunks to stt_client.send_audio()
        # 3. Processing transcripts from stt_client.receive_transcripts()
        # 4. Running them through the pipeline
        # 5. Broadcasting card events

        print("STT client initialized (audio capture not yet implemented)")
    else:
        print("\nNo STT configured — use /api/resolve for testing")

    print("\nPress Ctrl+C to stop")
    print("=" * 50)

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def handle_signal():
        asyncio.create_task(shutdown(server, stt_client))

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    # Keep the server running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
        sys.exit(0)
