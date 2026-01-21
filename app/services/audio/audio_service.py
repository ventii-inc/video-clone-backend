"""Audio processing service for trimming and analyzing audio using FFmpeg"""

import asyncio
import json
import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum duration for training audio (in seconds)
MAX_TRAINING_AUDIO_DURATION = 60


async def get_audio_duration(file_path: str) -> Optional[float]:
    """
    Get audio duration in seconds using ffprobe.

    Args:
        file_path: Path to the audio file

    Returns:
        Duration in seconds, or None if unable to determine
    """
    if not os.path.exists(file_path):
        logger.error(f"Audio file not found: {file_path}")
        return None

    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"ffprobe failed: {stderr.decode()}")
            return None

        data = json.loads(stdout.decode())
        duration = float(data["format"]["duration"])
        logger.info(f"Audio duration: {duration:.2f}s for {file_path}")
        return duration

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse ffprobe output: {e}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe not found. Please install FFmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error getting audio duration: {e}")
        return None


async def trim_audio(
    input_path: str,
    output_path: str,
    max_duration: int = MAX_TRAINING_AUDIO_DURATION,
) -> bool:
    """
    Trim audio to specified max duration using FFmpeg.

    Uses stream copy (-c copy) for fast trimming without re-encoding.

    Args:
        input_path: Path to input audio file
        output_path: Path for trimmed output audio
        max_duration: Maximum duration in seconds (default: 60)

    Returns:
        True if audio was trimmed, False if no trimming needed or error
    """
    duration = await get_audio_duration(input_path)

    if duration is None:
        logger.error(f"Could not determine duration for {input_path}")
        return False

    if duration <= max_duration:
        logger.info(f"Audio is {duration:.2f}s, no trimming needed (max: {max_duration}s)")
        return False

    logger.info(f"Trimming audio from {duration:.2f}s to {max_duration}s")

    try:
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", input_path,
            "-t", str(max_duration),
            "-c", "copy",  # Stream copy (no re-encoding)
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg trim failed: {stderr.decode()}")
            return False

        # Verify output file exists
        if not os.path.exists(output_path):
            logger.error(f"Trimmed audio not created: {output_path}")
            return False

        logger.info(f"Audio trimmed successfully: {output_path}")
        return True

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install FFmpeg.")
        return False
    except Exception as e:
        logger.error(f"Error trimming audio: {e}")
        return False


class AudioService:
    """Service for audio processing operations"""

    def __init__(self):
        self.max_training_duration = MAX_TRAINING_AUDIO_DURATION

    async def process_training_audio(
        self,
        input_path: str,
        output_path: Optional[str] = None,
    ) -> tuple[str, float, bool]:
        """
        Process a training audio: trim if necessary.

        Args:
            input_path: Path to the input audio
            output_path: Optional path for output (defaults to temp file)

        Returns:
            Tuple of (output_path, duration_seconds, was_trimmed)

        Raises:
            ValueError: If audio cannot be processed
        """
        duration = await get_audio_duration(input_path)

        if duration is None:
            raise ValueError(f"Could not determine audio duration: {input_path}")

        # If audio is short enough, no processing needed
        if duration <= self.max_training_duration:
            return input_path, duration, False

        # Generate output path if not provided
        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_trimmed{ext}"

        # Trim the audio
        success = await trim_audio(input_path, output_path, self.max_training_duration)

        if not success:
            raise ValueError(f"Failed to trim audio: {input_path}")

        return output_path, float(self.max_training_duration), True

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if FFmpeg is available on the system"""
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# Global instance
audio_service = AudioService()
