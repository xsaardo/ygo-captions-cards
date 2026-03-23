"""Audio capture using ffmpeg for system audio streaming.

This module provides the AudioCapture class that wraps ffmpeg subprocess
to capture system audio and provide it as 16kHz mono PCM chunks.
"""

import asyncio
import sys
from typing import AsyncIterator, Optional


class AudioCapture:
    """Captures system audio using ffmpeg and yields audio chunks.

    Handles platform-specific audio input sources and provides async
    interface for reading audio chunks at a configurable sample rate.
    """

    def __init__(self, sample_rate: int = 16000, chunk_ms: int = 100):
        """Initialize the audio capture.

        Args:
            sample_rate: Audio sample rate in Hz (default: 16000)
            chunk_ms: Chunk size in milliseconds (default: 100ms)
        """
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.process: Optional[asyncio.subprocess.Process] = None

        # Calculate chunk size in bytes
        # PCM 16-bit = 2 bytes per sample, mono = 1 channel
        # samples_per_chunk = (sample_rate * chunk_ms) / 1000
        # bytes_per_chunk = samples_per_chunk * 2
        self.chunk_size = (sample_rate * chunk_ms * 2) // 1000

    def _build_ffmpeg_command(self) -> list[str]:
        """Build the ffmpeg command for the current platform.

        Returns:
            List of command arguments for subprocess

        Raises:
            RuntimeError: If the platform is not supported
        """
        # Detect platform
        platform = sys.platform

        if platform == "darwin":
            # macOS - use avfoundation
            input_args = ["-f", "avfoundation", "-i", ":0"]
        elif platform.startswith("linux"):
            # Linux - use PulseAudio
            input_args = ["-f", "pulse", "-i", "default"]
        elif platform == "win32":
            # Windows - use DirectShow
            input_args = ["-f", "dshow", "-i", "audio=Stereo Mix"]
        else:
            raise RuntimeError(f"Unsupported platform: {platform}")

        # Build full command
        # Output: mono, 16kHz, 16-bit PCM signed little-endian to stdout
        return [
            "ffmpeg",
            *input_args,
            "-ac", "1",  # mono
            "-ar", str(self.sample_rate),  # sample rate
            "-f", "s16le",  # 16-bit signed little-endian PCM
            "pipe:1",  # output to stdout
        ]

    async def start(self) -> None:
        """Start the ffmpeg subprocess for audio capture.

        Raises:
            RuntimeError: If audio capture is already started or ffmpeg fails
        """
        if self.process is not None:
            raise RuntimeError("Audio capture already started")

        command = self._build_ffmpeg_command()

        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg not found. Please install ffmpeg and ensure it's in PATH."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start audio capture: {e}")

    async def stop(self) -> None:
        """Stop the ffmpeg subprocess gracefully.

        Terminates the process and waits for it to exit.
        """
        if self.process is None:
            return

        try:
            # Send termination signal
            self.process.terminate()

            # Wait for process to exit (with timeout)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # Force kill if it doesn't exit gracefully
                self.process.kill()
                await self.process.wait()
        except Exception:
            # Ignore errors during cleanup
            pass
        finally:
            self.process = None

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        """Yield audio chunks as they're captured.

        Yields:
            bytes: Audio data chunks (PCM 16-bit signed LE, mono, 16kHz)

        Raises:
            RuntimeError: If audio capture is not started
        """
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("Audio capture not started. Call start() first.")

        try:
            while True:
                # Read exactly chunk_size bytes
                chunk = await self.process.stdout.readexactly(self.chunk_size)
                yield chunk
        except asyncio.IncompleteReadError:
            # End of stream - ffmpeg process terminated
            return
        except Exception as e:
            # Log error but don't crash
            print(f"Error reading audio chunk: {e}")
            return
