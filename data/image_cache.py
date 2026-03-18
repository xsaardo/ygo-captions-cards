"""Card image downloader and local cache manager.

This module provides the ImageCache class which manages downloading and caching
card images from YGOProDeck's CDN.
"""

import asyncio
from pathlib import Path
from typing import Optional

import aiohttp


class ImageCache:
    """Manages card image downloads and local caching.

    Downloads card images from YGOProDeck's CDN and caches them locally.
    Uses the cards_small size (168x245px) for optimal performance.
    """

    def __init__(self, cache_dir: str = "data/card_images"):
        """Initialize the image cache.

        Args:
            cache_dir: Directory to store cached card images
        """
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def has(self, card_id: int) -> bool:
        """Check if a card image is cached locally.

        Args:
            card_id: The YGOProDeck card ID

        Returns:
            True if the image is cached, False otherwise
        """
        return (self._cache_dir / f"{card_id}.jpg").exists()

    async def ensure_cached(self, card_ids: list[int]) -> None:
        """Download missing card images, respecting rate limits.

        Args:
            card_ids: List of card IDs to ensure are cached
        """
        missing = [cid for cid in card_ids if not self.has(cid)]

        if not missing:
            return

        # Max 10 concurrent downloads to respect rate limits
        semaphore = asyncio.Semaphore(10)

        async with aiohttp.ClientSession() as session:
            tasks = [
                self._download_one(session, cid, semaphore) for cid in missing
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _download_one(
        self,
        session: aiohttp.ClientSession,
        card_id: int,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Download a single card image.

        Args:
            session: aiohttp session
            card_id: The card ID to download
            semaphore: Semaphore to limit concurrent downloads
        """
        async with semaphore:
            # Use cards_small for 168x245px images (optimal for overlay)
            url = f"https://images.ygoprodeck.com/images/cards_small/{card_id}.jpg"

            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        (self._cache_dir / f"{card_id}.jpg").write_bytes(data)
            except Exception:
                # Silently fail for missing images
                # They will be logged in the main application
                pass

            # Stay under 20 req/s rate limit
            await asyncio.sleep(0.05)

    def get_path(self, card_id: int) -> Optional[str]:
        """Get the local path to a cached card image.

        Args:
            card_id: The card ID

        Returns:
            Path to the cached image if it exists, None otherwise
        """
        path = self._cache_dir / f"{card_id}.jpg"
        return str(path) if path.exists() else None
