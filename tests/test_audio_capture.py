"""Tests for audio capture module.

Tests the AudioCapture class that wraps ffmpeg for system audio streaming.
Uses mock subprocess to avoid actually running ffmpeg.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from audio.capture import AudioCapture


class TestAudioCapture:
    """Tests for the AudioCapture class."""

    def test_init_defaults(self):
        """Test initialization with default parameters."""
        capture = AudioCapture()
        assert capture.sample_rate == 16000
        assert capture.chunk_ms == 100
        # 16000 samples/sec * 0.1 sec * 2 bytes/sample = 3200 bytes
        assert capture.chunk_size == 3200
        assert capture.process is None

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        capture = AudioCapture(sample_rate=8000, chunk_ms=200)
        assert capture.sample_rate == 8000
        assert capture.chunk_ms == 200
        # 8000 samples/sec * 0.2 sec * 2 bytes/sample = 3200 bytes
        assert capture.chunk_size == 3200

    @patch("sys.platform", "darwin")
    def test_build_ffmpeg_command_macos(self):
        """Test that ffmpeg command is correct for macOS."""
        capture = AudioCapture()
        command = capture._build_ffmpeg_command()

        assert command[0] == "ffmpeg"
        assert "-f" in command
        assert "avfoundation" in command
        assert "-i" in command
        assert ":0" in command
        assert "-ac" in command and "1" in command
        assert "-ar" in command and "16000" in command
        assert "-f" in command and "s16le" in command
        assert "pipe:1" in command

    @patch("sys.platform", "linux")
    def test_build_ffmpeg_command_linux(self):
        """Test that ffmpeg command is correct for Linux."""
        capture = AudioCapture()
        command = capture._build_ffmpeg_command()

        assert command[0] == "ffmpeg"
        assert "-f" in command
        assert "pulse" in command
        assert "-i" in command
        assert "default" in command
        assert "-ac" in command and "1" in command
        assert "-ar" in command and "16000" in command

    @patch("sys.platform", "win32")
    def test_build_ffmpeg_command_windows(self):
        """Test that ffmpeg command is correct for Windows."""
        capture = AudioCapture()
        command = capture._build_ffmpeg_command()

        assert command[0] == "ffmpeg"
        assert "-f" in command
        assert "dshow" in command
        assert "-i" in command
        assert "audio=Stereo Mix" in command

    @patch("sys.platform", "unsupported_os")
    def test_build_ffmpeg_command_unsupported_platform(self):
        """Test that unsupported platform raises RuntimeError."""
        capture = AudioCapture()
        with pytest.raises(RuntimeError, match="Unsupported platform"):
            capture._build_ffmpeg_command()

    @pytest.mark.asyncio
    async def test_start_creates_subprocess(self):
        """Test that start() creates an ffmpeg subprocess."""
        capture = AudioCapture()

        # Mock the subprocess
        mock_process = MagicMock()
        mock_process.stdout = AsyncMock()
        mock_process.stderr = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_create:
            await capture.start()

            # Verify subprocess was created
            assert mock_create.called
            assert capture.process is mock_process

            # Verify command includes ffmpeg
            call_args = mock_create.call_args[0]
            assert call_args[0] == "ffmpeg"

    @pytest.mark.asyncio
    async def test_start_already_started_raises_error(self):
        """Test that calling start() twice raises RuntimeError."""
        capture = AudioCapture()
        capture.process = MagicMock()  # Simulate already started

        with pytest.raises(RuntimeError, match="already started"):
            await capture.start()

    @pytest.mark.asyncio
    async def test_start_ffmpeg_not_found(self):
        """Test that missing ffmpeg raises RuntimeError."""
        capture = AudioCapture()

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="ffmpeg not found"):
                await capture.start()

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self):
        """Test that stop() terminates the ffmpeg process."""
        capture = AudioCapture()

        # Mock the process
        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()
        capture.process = mock_process

        await capture.stop()

        # Verify process was terminated
        assert mock_process.terminate.called
        assert mock_process.wait.called
        assert capture.process is None

    @pytest.mark.asyncio
    async def test_stop_kills_process_on_timeout(self):
        """Test that stop() kills process if it doesn't exit gracefully."""
        capture = AudioCapture()

        # Mock process that times out on wait()
        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), None])
        capture.process = mock_process

        await capture.stop()

        # Verify process was killed after timeout
        assert mock_process.kill.called

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """Test that stop() is safe to call when not started."""
        capture = AudioCapture()
        await capture.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_audio_chunks_yields_correct_size(self):
        """Test that audio_chunks() yields chunks of the correct size."""
        capture = AudioCapture(sample_rate=16000, chunk_ms=100)
        expected_chunk_size = 3200  # 16000 * 0.1 * 2

        # Mock the process and stdout
        mock_stdout = AsyncMock()
        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        capture.process = mock_process

        # Simulate reading 3 chunks, then EOF
        test_chunks = [
            b"x" * expected_chunk_size,
            b"y" * expected_chunk_size,
            b"z" * expected_chunk_size,
        ]

        async def mock_readexactly(size):
            if test_chunks:
                return test_chunks.pop(0)
            raise asyncio.IncompleteReadError(b"", size)

        mock_stdout.readexactly = mock_readexactly

        # Collect chunks
        collected_chunks = []
        async for chunk in capture.audio_chunks():
            collected_chunks.append(chunk)

        # Verify
        assert len(collected_chunks) == 3
        assert all(len(chunk) == expected_chunk_size for chunk in collected_chunks)

    @pytest.mark.asyncio
    async def test_audio_chunks_not_started_raises_error(self):
        """Test that audio_chunks() raises error when not started."""
        capture = AudioCapture()

        with pytest.raises(RuntimeError, match="not started"):
            async for _ in capture.audio_chunks():
                pass

    @pytest.mark.asyncio
    async def test_audio_chunks_handles_incomplete_read(self):
        """Test that audio_chunks() handles end of stream gracefully."""
        capture = AudioCapture()

        # Mock the process with EOF immediately
        mock_stdout = AsyncMock()
        mock_stdout.readexactly = AsyncMock(
            side_effect=asyncio.IncompleteReadError(b"", 3200)
        )
        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        capture.process = mock_process

        # Should return no chunks without error
        collected_chunks = []
        async for chunk in capture.audio_chunks():
            collected_chunks.append(chunk)

        assert len(collected_chunks) == 0
