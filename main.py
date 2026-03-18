"""Main entry point for the YGO card overlay system.

This module initializes all components and starts the overlay server.
For Part 1, the STT client and full async pipeline are NOT wired up yet.
The server's /api/resolve endpoint handles card resolution for testing.
"""

import argparse
import asyncio
import signal
import sys

from config import Config
from data.card_db import CardDatabase
from data.image_cache import ImageCache
from overlay.server import OverlayServer
from resolver.alias_dict import AliasDictionary
from telemetry.logger import ResolverLogger


async def shutdown(server: OverlayServer) -> None:
    """Gracefully shut down the server.

    Args:
        server: The overlay server to shut down
    """
    print("\nShutting down...")
    await server.stop()


async def main() -> None:
    """Main entry point."""
    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description="YGO Commentary Card Overlay - Part 1"
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

    args = parser.parse_args()

    # Load configuration
    config = Config.from_cli_args(
        overlay_port=args.overlay_port,
        player1_deck=args.player1_deck,
        player2_deck=args.player2_deck,
    )

    print("YGO Card Overlay - Part 1")
    print("=" * 50)

    # Initialize components
    print("Loading alias dictionary...")
    alias_dict = AliasDictionary(config.alias_path)

    print("Initializing card database...")
    card_db = CardDatabase()
    card_db.initialize()

    print("Initializing image cache...")
    image_cache = ImageCache()

    print("Initializing telemetry logger...")
    logger = ResolverLogger()

    # Start overlay server
    print(f"Starting overlay server on port {config.overlay_port}...")
    server = OverlayServer(
        alias_dict=alias_dict,
        card_db=card_db,
        image_cache=image_cache,
        logger=logger,
        port=config.overlay_port,
    )

    # Set match context if provided
    if config.player1_deck or config.player2_deck:
        server.player1_deck = config.player1_deck
        server.player2_deck = config.player2_deck
        print(f"Match context: {config.player1_deck} vs {config.player2_deck}")

    await server.start()

    print("=" * 50)
    print(f"Overlay URL: http://localhost:{config.overlay_port}/overlay")
    print(f"Test API: POST http://localhost:{config.overlay_port}/api/resolve")
    print('  Example: curl -X POST -H "Content-Type: application/json" \\')
    print(
        f'    -d \'{{"transcript": "he activates ash blossom"}}\' \\'
    )
    print(f"    http://localhost:{config.overlay_port}/api/resolve")
    print("\nPress Ctrl+C to stop")
    print("=" * 50)

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def handle_signal():
        asyncio.create_task(shutdown(server))

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
