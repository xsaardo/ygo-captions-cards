"""AssemblyAI STT client implementation using WebSockets directly.

This client connects to AssemblyAI's real-time streaming API using the
websockets library for direct WebSocket control.
"""

import asyncio
import json
import time
from typing import AsyncIterator, Optional

import websockets

from stt.base import STTClient, TranscriptEvent


class AssemblyAIClient(STTClient):
    """AssemblyAI streaming STT client.

    Connects to AssemblyAI's real-time WebSocket API and handles
    interim/final transcripts with automatic reconnection.
    """

    def __init__(self, api_key: str):
        """Initialize the AssemblyAI client.

        Args:
            api_key: AssemblyAI API key

        Raises:
            ValueError: If api_key is empty or None
        """
        if not api_key:
            raise ValueError(
                "AssemblyAI API key is required. Set STT_API_KEY environment variable."
            )

        self.api_key = api_key
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._reconnect_delay = 2.0
        self._max_reconnect_delay = 16.0

    async def connect(self, keyterms: list[str]) -> None:
        """Connect to AssemblyAI's real-time streaming API.

        Args:
            keyterms: List of card names (not currently used by AssemblyAI)
        """
        # AssemblyAI WebSocket URL with sample rate parameter
        url = "wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"

        # Authorization header
        extra_headers = {"Authorization": self.api_key}

        try:
            self.ws = await websockets.connect(url, extra_headers=extra_headers)
            self._connected = True
            self._reconnect_delay = 2.0  # Reset backoff

            # Wait for session_begins message
            message = await self.ws.recv()
            data = json.loads(message)
            if data.get("message_type") != "SessionBegins":
                raise ConnectionError(
                    f"Expected SessionBegins, got {data.get('message_type')}"
                )

        except Exception as e:
            raise ConnectionError(f"Failed to connect to AssemblyAI: {e}")

    async def send_audio(self, chunk: bytes) -> None:
        """Send audio chunk to AssemblyAI.

        Args:
            chunk: Raw PCM audio data (16-bit signed little-endian, mono, 16kHz)
        """
        if not self.ws or not self._connected:
            raise ConnectionError("Not connected to AssemblyAI")

        try:
            # AssemblyAI expects base64-encoded audio in JSON format
            import base64

            audio_b64 = base64.b64encode(chunk).decode("utf-8")
            message = json.dumps({"audio_data": audio_b64})
            await self.ws.send(message)
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to send audio: {e}")

    async def receive_transcripts(self) -> AsyncIterator[TranscriptEvent]:
        """Receive transcript events from AssemblyAI.

        Yields:
            TranscriptEvent objects for interim and final transcripts
        """
        if not self.ws or not self._connected:
            raise ConnectionError("Not connected to AssemblyAI")

        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")

                # Parse JSON response
                data = json.loads(message)
                message_type = data.get("message_type")

                # Handle partial transcripts (interim)
                if message_type == "PartialTranscript":
                    transcript = data.get("text", "")
                    confidence = data.get("confidence", 0.0)

                    if transcript.strip():
                        yield TranscriptEvent(
                            text=transcript,
                            is_final=False,
                            timestamp=time.time(),
                            confidence=confidence,
                        )

                # Handle final transcripts
                elif message_type == "FinalTranscript":
                    transcript = data.get("text", "")
                    confidence = data.get("confidence", 0.0)

                    if transcript.strip():
                        yield TranscriptEvent(
                            text=transcript,
                            is_final=True,
                            timestamp=time.time(),
                            confidence=confidence,
                        )

        except websockets.exceptions.ConnectionClosed:
            self._connected = False
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
            await self.connect([])
        except Exception as e:
            print(f"Reconnection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from AssemblyAI."""
        if self.ws:
            try:
                # Send terminate message
                await self.ws.send(json.dumps({"terminate_session": True}))
                await self.ws.close()
            except Exception:
                pass  # Ignore errors during disconnect
            finally:
                self._connected = False
                self.ws = None
