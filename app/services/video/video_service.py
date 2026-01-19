"""Video processing service for trimming and analyzing videos using FFmpeg"""

import asyncio
import json
import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum duration for training videos (in seconds)
MAX_TRAINING_VIDEO_DURATION = 60


async def get_video_duration(file_path: str) -> Optional[float]:
    """
    Get video duration in seconds using ffprobe.

    Args:
        file_path: Path to the video file

    Returns:
        Duration in seconds, or None if unable to determine
    """
    if not os.path.exists(file_path):
        logger.error(f"Video file not found: {file_path}")
        return None

    try:
        # Using create_subprocess_exec (not shell) for security - arguments passed as list
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
        logger.info(f"Video duration: {duration:.2f}s for {file_path}")
        return duration

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse ffprobe output: {e}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe not found. Please install FFmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return None


async def trim_video(
    input_path: str,
    output_path: str,
    max_duration: int = MAX_TRAINING_VIDEO_DURATION,
) -> bool:
    """
    Trim video to specified max duration using FFmpeg.

    Uses stream copy (-c copy) for fast trimming without re-encoding.

    Args:
        input_path: Path to input video file
        output_path: Path for trimmed output video
        max_duration: Maximum duration in seconds (default: 60)

    Returns:
        True if video was trimmed, False if no trimming needed or error
    """
    duration = await get_video_duration(input_path)

    if duration is None:
        logger.error(f"Could not determine duration for {input_path}")
        return False

    if duration <= max_duration:
        logger.info(f"Video is {duration:.2f}s, no trimming needed (max: {max_duration}s)")
        return False

    logger.info(f"Trimming video from {duration:.2f}s to {max_duration}s")

    try:
        # Using create_subprocess_exec (not shell) for security - arguments passed as list
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", input_path,
            "-t", str(max_duration),
            "-c", "copy",  # Stream copy (no re-encoding)
            "-avoid_negative_ts", "make_zero",
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
            logger.error(f"Trimmed video not created: {output_path}")
            return False

        logger.info(f"Video trimmed successfully: {output_path}")
        return True

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install FFmpeg.")
        return False
    except Exception as e:
        logger.error(f"Error trimming video: {e}")
        return False


class VideoService:
    """Service for video processing operations"""

    def __init__(self):
        self.max_training_duration = MAX_TRAINING_VIDEO_DURATION

    async def process_training_video(
        self,
        input_path: str,
        output_path: Optional[str] = None,
    ) -> tuple[str, float, bool]:
        """
        Process a training video: trim if necessary.

        Args:
            input_path: Path to the input video
            output_path: Optional path for output (defaults to temp file)

        Returns:
            Tuple of (output_path, duration_seconds, was_trimmed)

        Raises:
            ValueError: If video cannot be processed
        """
        duration = await get_video_duration(input_path)

        if duration is None:
            raise ValueError(f"Could not determine video duration: {input_path}")

        # If video is short enough, no processing needed
        if duration <= self.max_training_duration:
            return input_path, duration, False

        # Generate output path if not provided
        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_trimmed{ext}"

        # Trim the video
        success = await trim_video(input_path, output_path, self.max_training_duration)

        if not success:
            raise ValueError(f"Failed to trim video: {input_path}")

        return output_path, float(self.max_training_duration), True

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if FFmpeg is available on the system"""
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# Global instance
video_service = VideoService()
