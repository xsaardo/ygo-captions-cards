"""Tests for STT client implementations.

Tests the DeepgramClient and AssemblyAIClient classes without making
real API calls. Uses mock WebSocket objects to simulate responses.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stt.assemblyai_client import AssemblyAIClient
from stt.deepgram_client import DeepgramClient


class TestDeepgramClient:
    """Tests for the DeepgramClient class."""

    def test_init_validates_api_key(self):
        """Test that initialization requires a valid API key."""
        with pytest.raises(ValueError, match="API key is required"):
            DeepgramClient("")

        with pytest.raises(ValueError, match="API key is required"):
            DeepgramClient(None)

    def test_init_with_valid_key(self):
        """Test initialization with valid API key."""
        client = DeepgramClient("test-api-key")
        assert client.api_key == "test-api-key"
        assert client.model == "nova-3"
        assert client.ws is None
        assert client._connected is False

    def test_init_custom_model(self):
        """Test initialization with custom model."""
        client = DeepgramClient("test-api-key", model="nova-2")
        assert client.model == "nova-2"

    @pytest.mark.asyncio
    async def test_connect_builds_correct_url(self):
        """Test that connect() builds the correct WebSocket URL."""
        client = DeepgramClient("test-api-key")

        mock_ws = AsyncMock()
        with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)) as mock_connect:
            await client.connect(["Ash Blossom", "Nibiru"])

            # Verify connection was attempted
            assert mock_connect.called
            url = mock_connect.call_args[0][0]

            # Verify URL contains expected parameters
            assert "wss://api.deepgram.com/v1/listen" in url
            assert "model=nova-3" in url
            assert "language=en" in url
            assert "interim_results=true" in url
            assert "keywords=" in url

            # Verify authorization header
            headers = mock_connect.call_args[1]["extra_headers"]
            assert headers["Authorization"] == "Token test-api-key"

    @pytest.mark.asyncio
    async def test_connect_limits_keywords_to_100(self):
        """Test that connect() limits keywords to 100."""
        client = DeepgramClient("test-api-key")

        # Generate 150 keywords
        many_keywords = [f"card_{i}" for i in range(150)]

        mock_ws = AsyncMock()
        with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)) as mock_connect:
            await client.connect(many_keywords)

            url = mock_connect.call_args[0][0]
            # Count keywords in URL (separated by :)
            keywords_param = [p for p in url.split("&") if p.startswith("keywords=")][0]
            keyword_count = keywords_param.count(":") + 1
            assert keyword_count == 100

    @pytest.mark.asyncio
    async def test_send_audio_requires_connection(self):
        """Test that send_audio() raises error when not connected."""
        client = DeepgramClient("test-api-key")

        with pytest.raises(ConnectionError, match="Not connected"):
            await client.send_audio(b"audio data")

    @pytest.mark.asyncio
    async def test_send_audio_sends_bytes(self):
        """Test that send_audio() sends raw bytes to WebSocket."""
        client = DeepgramClient("test-api-key")

        mock_ws = AsyncMock()
        client.ws = mock_ws
        client._connected = True

        test_audio = b"test audio chunk"
        await client.send_audio(test_audio)

        # Verify bytes were sent
        assert mock_ws.send.called
        assert mock_ws.send.call_args[0][0] == test_audio

    @pytest.mark.asyncio
    async def test_receive_transcripts_parses_interim_results(self):
        """Test that receive_transcripts() correctly parses interim results."""
        client = DeepgramClient("test-api-key")

        # Mock WebSocket with interim transcript response
        interim_response = json.dumps({
            "channel": {
                "alternatives": [{
                    "transcript": "he activates ash",
                    "confidence": 0.95,
                }]
            },
            "is_final": False,
        })

        async def mock_aiter():
            yield interim_response

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda _: mock_aiter()
        client.ws = mock_ws
        client._connected = True

        # Collect transcripts
        transcripts = []
        async for event in client.receive_transcripts():
            transcripts.append(event)

        # Verify
        assert len(transcripts) == 1
        assert transcripts[0].text == "he activates ash"
        assert transcripts[0].is_final is False
        assert transcripts[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_receive_transcripts_parses_final_results(self):
        """Test that receive_transcripts() correctly parses final results."""
        client = DeepgramClient("test-api-key")

        # Mock WebSocket with final transcript response
        final_response = json.dumps({
            "channel": {
                "alternatives": [{
                    "transcript": "he activates ash blossom",
                    "confidence": 0.98,
                }]
            },
            "is_final": True,
        })

        async def mock_aiter():
            yield final_response

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda _: mock_aiter()
        client.ws = mock_ws
        client._connected = True

        # Collect transcripts
        transcripts = []
        async for event in client.receive_transcripts():
            transcripts.append(event)

        # Verify
        assert len(transcripts) == 1
        assert transcripts[0].text == "he activates ash blossom"
        assert transcripts[0].is_final is True
        assert transcripts[0].confidence == 0.98

    @pytest.mark.asyncio
    async def test_receive_transcripts_skips_empty_transcripts(self):
        """Test that empty transcripts are not yielded."""
        client = DeepgramClient("test-api-key")

        # Mock responses with empty transcript
        responses = [
            json.dumps({
                "channel": {
                    "alternatives": [{
                        "transcript": "",
                        "confidence": 0.0,
                    }]
                },
                "is_final": False,
            }),
            json.dumps({
                "channel": {
                    "alternatives": [{
                        "transcript": "  ",  # Whitespace only
                        "confidence": 0.0,
                    }]
                },
                "is_final": False,
            }),
        ]

        async def mock_aiter():
            for r in responses:
                yield r

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda _: mock_aiter()
        client.ws = mock_ws
        client._connected = True

        # Collect transcripts
        transcripts = []
        async for event in client.receive_transcripts():
            transcripts.append(event)

        # Should have no transcripts
        assert len(transcripts) == 0

    @pytest.mark.asyncio
    async def test_disconnect_closes_websocket(self):
        """Test that disconnect() closes the WebSocket."""
        client = DeepgramClient("test-api-key")

        mock_ws = AsyncMock()
        client.ws = mock_ws
        client._connected = True

        await client.disconnect()

        # Verify WebSocket was closed
        assert mock_ws.close.called
        assert client.ws is None
        assert client._connected is False


class TestAssemblyAIClient:
    """Tests for the AssemblyAIClient class."""

    def test_init_validates_api_key(self):
        """Test that initialization requires a valid API key."""
        with pytest.raises(ValueError, match="API key is required"):
            AssemblyAIClient("")

        with pytest.raises(ValueError, match="API key is required"):
            AssemblyAIClient(None)

    def test_init_with_valid_key(self):
        """Test initialization with valid API key."""
        client = AssemblyAIClient("test-api-key")
        assert client.api_key == "test-api-key"
        assert client.ws is None
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_connect_builds_correct_url(self):
        """Test that connect() builds the correct WebSocket URL."""
        client = AssemblyAIClient("test-api-key")

        # Mock WebSocket with SessionBegins message
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps({"message_type": "SessionBegins"})
        )

        with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)) as mock_connect:
            await client.connect([])

            # Verify connection was attempted
            assert mock_connect.called
            url = mock_connect.call_args[0][0]

            # Verify URL
            assert url == "wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000"

            # Verify authorization header
            headers = mock_connect.call_args[1]["extra_headers"]
            assert headers["Authorization"] == "test-api-key"

    @pytest.mark.asyncio
    async def test_connect_waits_for_session_begins(self):
        """Test that connect() waits for SessionBegins message."""
        client = AssemblyAIClient("test-api-key")

        # Mock WebSocket with SessionBegins message
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps({"message_type": "SessionBegins"})
        )

        with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)):
            await client.connect([])

            # Verify SessionBegins was received
            assert mock_ws.recv.called
            assert client._connected is True

    @pytest.mark.asyncio
    async def test_send_audio_encodes_base64(self):
        """Test that send_audio() base64-encodes audio data."""
        client = AssemblyAIClient("test-api-key")

        mock_ws = AsyncMock()
        client.ws = mock_ws
        client._connected = True

        test_audio = b"test audio chunk"
        await client.send_audio(test_audio)

        # Verify JSON with base64 audio was sent
        assert mock_ws.send.called
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert "audio_data" in sent_data

        # Verify base64 encoding
        import base64
        decoded = base64.b64decode(sent_data["audio_data"])
        assert decoded == test_audio

    @pytest.mark.asyncio
    async def test_receive_transcripts_parses_partial_transcript(self):
        """Test that receive_transcripts() parses PartialTranscript messages."""
        client = AssemblyAIClient("test-api-key")

        # Mock WebSocket with PartialTranscript response
        partial_response = json.dumps({
            "message_type": "PartialTranscript",
            "text": "he activates ash",
            "confidence": 0.92,
        })

        async def mock_aiter():
            yield partial_response

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda _: mock_aiter()
        client.ws = mock_ws
        client._connected = True

        # Collect transcripts
        transcripts = []
        async for event in client.receive_transcripts():
            transcripts.append(event)

        # Verify
        assert len(transcripts) == 1
        assert transcripts[0].text == "he activates ash"
        assert transcripts[0].is_final is False
        assert transcripts[0].confidence == 0.92

    @pytest.mark.asyncio
    async def test_receive_transcripts_parses_final_transcript(self):
        """Test that receive_transcripts() parses FinalTranscript messages."""
        client = AssemblyAIClient("test-api-key")

        # Mock WebSocket with FinalTranscript response
        final_response = json.dumps({
            "message_type": "FinalTranscript",
            "text": "he activates ash blossom",
            "confidence": 0.97,
        })

        async def mock_aiter():
            yield final_response

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda _: mock_aiter()
        client.ws = mock_ws
        client._connected = True

        # Collect transcripts
        transcripts = []
        async for event in client.receive_transcripts():
            transcripts.append(event)

        # Verify
        assert len(transcripts) == 1
        assert transcripts[0].text == "he activates ash blossom"
        assert transcripts[0].is_final is True
        assert transcripts[0].confidence == 0.97

    @pytest.mark.asyncio
    async def test_receive_transcripts_skips_empty_transcripts(self):
        """Test that empty transcripts are not yielded."""
        client = AssemblyAIClient("test-api-key")

        # Mock responses with empty transcripts
        responses = [
            json.dumps({
                "message_type": "PartialTranscript",
                "text": "",
                "confidence": 0.0,
            }),
            json.dumps({
                "message_type": "FinalTranscript",
                "text": "  ",  # Whitespace only
                "confidence": 0.0,
            }),
        ]

        async def mock_aiter():
            for r in responses:
                yield r

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda _: mock_aiter()
        client.ws = mock_ws
        client._connected = True

        # Collect transcripts
        transcripts = []
        async for event in client.receive_transcripts():
            transcripts.append(event)

        # Should have no transcripts
        assert len(transcripts) == 0

    @pytest.mark.asyncio
    async def test_disconnect_sends_terminate_message(self):
        """Test that disconnect() sends terminate message."""
        client = AssemblyAIClient("test-api-key")

        mock_ws = AsyncMock()
        client.ws = mock_ws
        client._connected = True

        await client.disconnect()

        # Verify terminate message was sent
        assert mock_ws.send.called
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["terminate_session"] is True

        # Verify WebSocket was closed
        assert mock_ws.close.called
        assert client.ws is None
        assert client._connected is False
