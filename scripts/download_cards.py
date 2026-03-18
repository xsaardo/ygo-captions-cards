"""Download card database and images from YGOProDeck API.

This script downloads the full card database from YGOProDeck and optionally
creates a baseline copy for offline operation.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp


async def download_card_database(output_path: str = "data/cards.json") -> None:
    """Download the card database from YGOProDeck API.

    Args:
        output_path: Path to save the card database JSON
    """
    url = "https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes"

    print(f"Downloading card database from {url}...")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"Error: HTTP {resp.status}")
                    sys.exit(1)

                data = await resp.json()
                card_count = len(data.get("data", []))

                # Save to file
                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)

                with open(output, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

                print(f"Downloaded {card_count} cards to {output_path}")
                print(f"File size: {output.stat().st_size / 1024 / 1024:.2f} MB")

        except Exception as e:
            print(f"Error downloading card database: {e}")
            sys.exit(1)


def create_baseline(
    source: str = "data/cards.json", dest: str = "data/cards_baseline.json"
) -> None:
    """Create a baseline copy of the card database for offline operation.

    Args:
        source: Source card database file
        dest: Destination baseline file
    """
    source_path = Path(source)
    dest_path = Path(dest)

    if not source_path.exists():
        print(f"Error: Source file {source} does not exist")
        sys.exit(1)

    print(f"Creating baseline copy: {source} -> {dest}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(source_path.read_bytes())

    print(f"Baseline created: {dest}")


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download card database from YGOProDeck"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/cards.json",
        help="Output path for card database (default: data/cards.json)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Also copy to data/cards_baseline.json for offline use",
    )

    args = parser.parse_args()

    # Download the card database
    await download_card_database(args.output)

    # Create baseline if requested
    if args.update_baseline:
        create_baseline(args.output, "data/cards_baseline.json")

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
