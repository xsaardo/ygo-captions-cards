"""Main entry point for the YGO card overlay system.

This module initializes all components (alias dict, fuzzy matcher, phonetic matcher,
context resolver, resolution pipeline, and optionally STT client) and starts the
overlay server with full 4-tier card resolution.
"""

import argparse
import asyncio
import signal
import sys
import time
from typing import Optional

from audio.capture import AudioCapture
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


async def shutdown(
    server: OverlayServer,
    stt_client: Optional = None,
    audio_capture: Optional[AudioCapture] = None,
) -> None:
    """Gracefully shut down the server, STT client, and audio capture.

    Args:
        server: The overlay server to shut down
        stt_client: Optional STT client to disconnect
        audio_capture: Optional audio capture to stop
    """
    print("\nShutting down...")

    # Stop audio capture first
    if audio_capture:
        try:
            await audio_capture.stop()
        except Exception as e:
            print(f"Error stopping audio capture: {e}")

    # Disconnect STT client
    if stt_client:
        try:
            await stt_client.disconnect()
        except Exception as e:
            print(f"Error disconnecting STT client: {e}")

    # Stop overlay server
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
        stt_provider=args.stt_provider or Config().stt_provider,
        stt_api_key=args.stt_api_key or Config().stt_api_key,
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

    # Initialize STT client and audio capture if configured
    stt_client = None
    audio_capture = None

    if args.stt_provider and config.stt_api_key:
        print(f"\nInitializing {args.stt_provider} STT client...")

        if args.stt_provider == "deepgram":
            from stt.deepgram_client import DeepgramClient
            stt_client = DeepgramClient(config.stt_api_key, config.stt_model)
        elif args.stt_provider == "assemblyai":
            from stt.assemblyai_client import AssemblyAIClient
            stt_client = AssemblyAIClient(config.stt_api_key)

        # Initialize audio capture
        print("Initializing audio capture...")
        audio_capture = AudioCapture(
            sample_rate=config.audio_sample_rate,
            chunk_ms=config.audio_chunk_ms,
        )

        # Connect STT client
        print("Connecting to STT service...")
        await stt_client.connect([])  # TODO: Add keyterms based on deck context

        # Start audio capture
        print("Starting audio capture...")
        await audio_capture.start()

        # Track pending interim transcripts for debouncing
        pending_interims = {}  # transcript_id -> (transcript, timestamp)

        async def audio_sender_task():
            """Task A: Read audio chunks and send to STT client."""
            try:
                async for chunk in audio_capture.audio_chunks():
                    await stt_client.send_audio(chunk)
            except Exception as e:
                print(f"Error in audio sender task: {e}")

        async def transcript_receiver_task():
            """Task B: Receive transcripts, resolve cards, and broadcast."""
            nonlocal pending_interims
            try:
                async for transcript_event in stt_client.receive_transcripts():
                    # Handle interim transcripts with debouncing
                    if not transcript_event.is_final:
                        # Only resolve interim transcripts that are old enough
                        now = time.time()

                        # Check if we should debounce this interim
                        if config.interim_debounce_ms > 0:
                            # Store interim for later processing
                            transcript_id = transcript_event.text[:50]  # Use prefix as ID
                            pending_interims[transcript_id] = (transcript_event, now)

                            # Check for stale interims that should be treated as final
                            stale_threshold = config.interim_finalization_timeout_s
                            for tid, (tevt, ts) in list(pending_interims.items()):
                                age = now - ts

                                # Process if old enough for debouncing
                                if age >= config.interim_debounce_ms / 1000.0:
                                    # Resolve the transcript
                                    events = pipeline.resolve(tevt.text)
                                    for event in events:
                                        await server._show_card(
                                            event.card_id,
                                            event.card_name,
                                            event.match_source,
                                            event.match_score,
                                        )

                                    # If it's very stale, treat as final
                                    if age >= stale_threshold:
                                        del pending_interims[tid]
                        else:
                            # No debouncing - resolve immediately
                            events = pipeline.resolve(transcript_event.text)
                            for event in events:
                                await server._show_card(
                                    event.card_id,
                                    event.card_name,
                                    event.match_source,
                                    event.match_score,
                                )
                    else:
                        # Final transcript - resolve immediately and log
                        events = pipeline.resolve(transcript_event.text)
                        for event in events:
                            await server._show_card(
                                event.card_id,
                                event.card_name,
                                event.match_source,
                                event.match_score,
                            )

                        # Clear any pending interims for this transcript
                        transcript_id = transcript_event.text[:50]
                        if transcript_id in pending_interims:
                            del pending_interims[transcript_id]

                        # Log final transcripts
                        if events:
                            print(f"[FINAL] '{transcript_event.text}' -> {[e.card_name for e in events]}")
                        else:
                            print(f"[FINAL] '{transcript_event.text}' -> No matches")
            except Exception as e:
                print(f"Error in transcript receiver task: {e}")

        # Launch both tasks concurrently
        print("Starting live audio pipeline...")
        audio_task = asyncio.create_task(audio_sender_task())
        transcript_task = asyncio.create_task(transcript_receiver_task())

        print("Live audio pipeline started!")
    else:
        print("\nNo STT configured — use /api/resolve for testing")

    print("\nPress Ctrl+C to stop")
    print("=" * 50)

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def handle_signal():
        asyncio.create_task(shutdown(server, stt_client, audio_capture))

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
