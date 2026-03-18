"""Deepgram STT client implementation using WebSockets directly.

This client connects to Deepgram's streaming API using the websockets library
(not the deepgram-sdk) for direct WebSocket control and reconnection handling.
"""

import asyncio
import json
import time
from typing import AsyncIterator, Optional

import websockets

from stt.base import STTClient, TranscriptEvent


class DeepgramClient(STTClient):
    """Deepgram streaming STT client.

    Connects to Deepgram's WebSocket API with the Nova-3 model and handles
    interim/final transcripts, keyword boosting, and automatic reconnection.
    """

    def __init__(self, api_key: str, model: str = "nova-3"):
        """Initialize the Deepgram client.

        Args:
            api_key: Deepgram API key
            model: Deepgram model to use (default: "nova-3")

        Raises:
            ValueError: If api_key is empty or None
        """
        if not api_key:
            raise ValueError(
                "Deepgram API key is required. Set STT_API_KEY environment variable."
            )

        self.api_key = api_key
        self.model = model
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._reconnect_delay = 2.0  # Start with 2 seconds
        self._max_reconnect_delay = 16.0

    async def connect(self, keyterms: list[str]) -> None:
        """Connect to Deepgram's streaming API.

        Args:
            keyterms: List of card names to boost in recognition
        """
        # Build query parameters
        params = {
            "model": self.model,
            "language": "en",
            "smart_format": "true",
            "interim_results": "true",
            "utterance_end_ms": "1000",
            "vad_events": "true",
        }

        # Add keywords (limit to 100)
        if keyterms:
            keywords_str = ":".join(keyterms[:100])
            params["keywords"] = keywords_str

        # Build WebSocket URL
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"wss://api.deepgram.com/v1/listen?{query_string}"

        # Connect with authorization header
        extra_headers = {"Authorization": f"Token {self.api_key}"}

        try:
            self.ws = await websockets.connect(url, extra_headers=extra_headers)
            self._connected = True
            self._reconnect_delay = 2.0  # Reset backoff on successful connect
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Deepgram: {e}")

    async def send_audio(self, chunk: bytes) -> None:
        """Send audio chunk to Deepgram.

        Args:
            chunk: Raw PCM audio data (16-bit signed little-endian, mono, 16kHz)
        """
        if not self.ws or not self._connected:
            raise ConnectionError("Not connected to Deepgram")

        try:
            await self.ws.send(chunk)
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to send audio: {e}")

    async def receive_transcripts(self) -> AsyncIterator[TranscriptEvent]:
        """Receive transcript events from Deepgram.

        Yields:
            TranscriptEvent objects for interim and final transcripts
        """
        if not self.ws or not self._connected:
            raise ConnectionError("Not connected to Deepgram")

        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    continue  # Skip binary messages

                # Parse JSON response
                data = json.loads(message)

                # Check for transcript results
                if "channel" in data:
                    channel = data["channel"]
                    if "alternatives" in channel and channel["alternatives"]:
                        alternative = channel["alternatives"][0]
                        transcript = alternative.get("transcript", "")
                        confidence = alternative.get("confidence", 0.0)
                        is_final = data.get("is_final", False)

                        # Only yield non-empty transcripts
                        if transcript.strip():
                            yield TranscriptEvent(
                                text=transcript,
                                is_final=is_final,
                                timestamp=time.time(),
                                confidence=confidence,
                            )

        except websockets.exceptions.ConnectionClosed:
            self._connected = False
            # Implement reconnection logic
            await self._reconnect()
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"Error receiving transcripts: {e}")

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        print(f"Connection lost. Reconnecting in {self._reconnect_delay}s...")
        await asyncio.sleep(self._reconnect_delay)

        # Exponential backoff
        self._reconnect_delay = min(
            self._reconnect_delay * 2, self._max_reconnect_delay
        )

        try:
            await self.connect([])  # Reconnect without keyterms
        except Exception as e:
            print(f"Reconnection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from Deepgram."""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass  # Ignore errors during disconnect
            finally:
                self._connected = False
                self.ws = None
