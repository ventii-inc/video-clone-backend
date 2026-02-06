"""Video processing service for trimming and analyzing videos using FFmpeg"""

import asyncio
import json
import os
import shutil
import tempfile
from typing import Optional

from app.utils.logger import logger

# Maximum duration for training videos (in seconds)
MAX_TRAINING_VIDEO_DURATION = 60

# Target FPS for training videos
TARGET_TRAINING_FPS = 25


async def get_video_info(file_path: str) -> Optional[dict]:
    """
    Get video information (duration, fps) using ffprobe.

    Args:
        file_path: Path to the video file

    Returns:
        Dict with 'duration' and 'fps' keys, or None if unable to determine
    """
    if not os.path.exists(file_path):
        logger.error(f"Video file not found: {file_path}")
        return None

    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-select_streams", "v:0",
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

        # Get FPS from video stream
        fps = None
        if data.get("streams"):
            stream = data["streams"][0]
            # Try r_frame_rate first (real frame rate), then avg_frame_rate
            frame_rate = stream.get("r_frame_rate") or stream.get("avg_frame_rate")
            if frame_rate and "/" in frame_rate:
                num, den = frame_rate.split("/")
                if int(den) != 0:
                    fps = int(num) / int(den)

        logger.info(f"Video info: duration={duration:.2f}s, fps={fps} for {file_path}")
        return {"duration": duration, "fps": fps}

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse ffprobe output: {e}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe not found. Please install FFmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return None


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


async def extract_thumbnail(
    video_path: str,
    output_path: Optional[str] = None,
    timestamp: float = 1.0,
) -> Optional[str]:
    """
    Extract a single frame from a video as a thumbnail.

    Args:
        video_path: Path to the video file
        output_path: Path for the output image (defaults to temp file)
        timestamp: Time in seconds to extract frame from (default: 1.0)

    Returns:
        Path to the generated thumbnail, or None if extraction failed
    """
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return None

    # Generate output path if not provided
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)

    try:
        # Get video duration first to ensure we don't seek past the end
        duration = await get_video_duration(video_path)
        if duration is not None and timestamp > duration:
            # Use 10% into the video if timestamp exceeds duration
            timestamp = min(1.0, duration * 0.1)

        # Using ffmpeg to extract a single frame
        # -ss before -i for fast seeking
        # -vframes 1 to extract only one frame
        # -q:v 2 for high quality JPEG
        # Arguments passed as list to create_subprocess_exec (not shell) for security
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg thumbnail extraction failed: {stderr.decode()}")
            return None

        # Verify output file exists and has content
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error(f"Thumbnail not created or empty: {output_path}")
            return None

        logger.info(f"Thumbnail extracted successfully: {output_path}")
        return output_path

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install FFmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error extracting thumbnail: {e}")
        return None


async def trim_video_to_timestamp(
    input_path: str,
    output_path: str,
    end_seconds: float,
) -> bool:
    """
    Trim video to an exact timestamp using re-encoding for frame-accurate cut.

    Args:
        input_path: Path to input video file
        output_path: Path for trimmed output video
        end_seconds: End timestamp in seconds

    Returns:
        True if successful, False on error
    """
    logger.info(f"Trimming video to {end_seconds:.2f}s: {input_path}")

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-t", str(end_seconds),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-an",
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg trim-to-timestamp failed: {stderr.decode()}")
            return False

        if not os.path.exists(output_path):
            logger.error(f"Trimmed video not created: {output_path}")
            return False

        logger.info(f"Video trimmed to {end_seconds:.2f}s: {output_path}")
        return True

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install FFmpeg.")
        return False
    except Exception as e:
        logger.error(f"Error trimming video to timestamp: {e}")
        return False


async def reverse_video(input_path: str, output_path: str, chunk_seconds: int = 5, timeout: int = 300) -> bool:
    """
    Create a reversed copy of a video using chunk-based reversal.

    Splits the video into small chunks, reverses each individually, then
    concatenates them in reverse order. This avoids buffering all frames
    in memory (~9GB for 60s 1080p) and instead uses ~750MB per chunk.

    Args:
        input_path: Path to input video file
        output_path: Path for reversed output video
        chunk_seconds: Duration of each chunk in seconds (default: 5)
        timeout: Timeout per ffmpeg operation in seconds (default: 300)

    Returns:
        True if successful, False on error
    """
    logger.info(f"Reversing video (chunked, {chunk_seconds}s chunks): {input_path}")

    video_info = await get_video_info(input_path)
    if video_info is None:
        logger.error(f"Could not get video info for reverse: {input_path}")
        return False

    duration = video_info["duration"]
    chunk_dir = None

    try:
        chunk_dir = tempfile.mkdtemp(prefix="reverse_chunks_")

        # Calculate chunk boundaries
        chunks = []
        start = 0.0
        while start < duration:
            end = min(start + chunk_seconds, duration)
            chunks.append((start, end - start))
            start = end

        logger.info(f"Splitting into {len(chunks)} chunks for reversal")

        # Step 1: Extract and reverse each chunk
        reversed_chunk_paths = []
        for i, (start_time, chunk_dur) in enumerate(chunks):
            chunk_path = os.path.join(chunk_dir, f"chunk_{i:04d}.mp4")
            reversed_chunk_paths.append(chunk_path)

            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_time),
                "-i", input_path,
                "-t", str(chunk_dur),
                "-vf", "reverse",
                "-an",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                chunk_path,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                logger.error(f"FFmpeg reverse chunk {i} timed out after {timeout}s")
                return False

            if process.returncode != 0:
                logger.error(f"FFmpeg reverse chunk {i} failed: {stderr.decode()}")
                return False

            logger.info(f"Reversed chunk {i + 1}/{len(chunks)}")

        # Step 2: Concatenate reversed chunks in REVERSE order
        reversed_chunk_paths.reverse()

        list_path = os.path.join(chunk_dir, "concat_list.txt")
        with open(list_path, "w") as f:
            for path in reversed_chunk_paths:
                escaped = path.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            logger.error(f"FFmpeg concat reversed chunks timed out after {timeout}s")
            return False

        if process.returncode != 0:
            logger.error(f"FFmpeg concat reversed chunks failed: {stderr.decode()}")
            return False

        if not os.path.exists(output_path):
            logger.error(f"Reversed video not created: {output_path}")
            return False

        logger.info(f"Video reversed (chunked): {output_path}")
        return True

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install FFmpeg.")
        return False
    except Exception as e:
        logger.error(f"Error reversing video: {e}")
        return False
    finally:
        if chunk_dir and os.path.exists(chunk_dir):
            try:
                shutil.rmtree(chunk_dir)
            except OSError as e:
                logger.warning(f"Failed to clean up chunk dir {chunk_dir}: {e}")


async def concat_videos(input_paths: list[str], output_path: str) -> bool:
    """
    Concatenate multiple videos using ffmpeg concat demuxer.

    All input videos must have the same codec, resolution, and framerate.

    Args:
        input_paths: List of paths to input video files
        output_path: Path for concatenated output video

    Returns:
        True if successful, False on error
    """
    if not input_paths:
        logger.error("No input paths provided for concatenation")
        return False

    logger.info(f"Concatenating {len(input_paths)} videos: {output_path}")

    # Create concat list file
    fd, list_path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as f:
            for path in input_paths:
                # Escape single quotes in path for ffmpeg concat format
                escaped = path.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg concat failed: {stderr.decode()}")
            return False

        if not os.path.exists(output_path):
            logger.error(f"Concatenated video not created: {output_path}")
            return False

        logger.info(f"Videos concatenated: {output_path}")
        return True

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install FFmpeg.")
        return False
    except Exception as e:
        logger.error(f"Error concatenating videos: {e}")
        return False
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)


class VideoService:
    """Service for video processing operations"""

    def __init__(self):
        self.max_training_duration = MAX_TRAINING_VIDEO_DURATION
        self.target_fps = TARGET_TRAINING_FPS

    async def process_training_video(
        self,
        input_path: str,
        output_path: Optional[str] = None,
    ) -> tuple[str, float, bool]:
        """
        Process a training video: trim to max duration, convert to 25fps, remove audio.

        Args:
            input_path: Path to the input video
            output_path: Optional path for output (defaults to temp file)

        Returns:
            Tuple of (output_path, duration_seconds, was_processed)

        Raises:
            ValueError: If video cannot be processed
        """
        video_info = await get_video_info(input_path)

        if video_info is None:
            raise ValueError(f"Could not determine video info: {input_path}")

        duration = video_info["duration"]
        current_fps = video_info.get("fps")

        # Check what processing is needed
        needs_trim = duration > self.max_training_duration
        needs_fps_convert = current_fps is None or abs(current_fps - self.target_fps) > 0.5
        # Always process to ensure audio is removed

        # Generate output path if not provided
        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_processed{ext}"

        # Build ffmpeg command for processing
        # Always re-encode since we need fps conversion and/or audio removal
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", input_path,
        ]

        # Add duration limit if needed
        if needs_trim:
            cmd.extend(["-t", str(self.max_training_duration)])

        # Add video filter for FPS conversion
        cmd.extend(["-vf", f"fps={self.target_fps}"])

        # Remove audio
        cmd.append("-an")

        # Output settings
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            output_path,
        ])

        logger.info(
            f"Processing video: trim={needs_trim}, fps_convert={needs_fps_convert}, remove_audio=True "
            f"(duration: {duration:.2f}s, current_fps: {current_fps}, target_fps: {self.target_fps})"
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"FFmpeg processing failed: {stderr.decode()}")
                raise ValueError(f"Failed to process video: {input_path}")

            # Verify output file exists
            if not os.path.exists(output_path):
                raise ValueError(f"Processed video not created: {output_path}")

            # Calculate final duration
            final_duration = min(duration, float(self.max_training_duration)) if needs_trim else duration

            logger.info(f"Video processed successfully: {output_path} ({final_duration:.2f}s, {self.target_fps}fps)")
            return output_path, final_duration, True

        except FileNotFoundError:
            raise ValueError("ffmpeg not found. Please install FFmpeg.")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Error processing video: {e}")

    async def analyze_and_loop_video(
        self,
        processed_path: str,
    ) -> tuple[str, float]:
        """
        Analyze video with Gemini for end-frame anomalies, optionally trim,
        then create a reverse-append loop.

        Steps:
        1. Upload to Gemini for end-frame analysis
        2. If anomaly detected, trim to the suggested timestamp
        3. Create reversed copy
        4. Concatenate original + reversed for seamless loop

        Args:
            processed_path: Path to the processed (trimmed/fps-converted) video

        Returns:
            Tuple of (looped_video_path, looped_duration_seconds)

        Raises:
            ValueError: If Gemini analysis or ffmpeg operations fail
        """
        from app.services.gemini import gemini_service

        intermediate_files = []

        try:
            # Step 1: Gemini analysis
            result = await gemini_service.analyze_end_frames(processed_path)
            if not result.success:
                raise ValueError(f"Gemini analysis failed: {result.error}")

            analysis = result.analysis
            source_path = processed_path

            # Step 2: Trim if anomaly detected
            if analysis.has_anomaly and analysis.trim_to_seconds is not None:
                trim_seconds = analysis.trim_to_seconds

                # Validate trim point
                video_info = await get_video_info(processed_path)
                if video_info is None:
                    raise ValueError("Could not determine video info for trimming")

                duration = video_info["duration"]
                if trim_seconds < 3.0:
                    trim_seconds = 3.0
                if trim_seconds >= duration:
                    logger.info(
                        f"Trim point ({trim_seconds}s) >= duration ({duration}s), "
                        f"skipping end trim"
                    )
                else:
                    base, ext = os.path.splitext(processed_path)
                    trimmed_path = f"{base}_trimmed{ext}"
                    intermediate_files.append(trimmed_path)

                    success = await trim_video_to_timestamp(
                        processed_path, trimmed_path, trim_seconds
                    )
                    if not success:
                        raise ValueError(
                            f"Failed to trim video to {trim_seconds}s"
                        )

                    source_path = trimmed_path
                    logger.info(
                        f"Trimmed anomalous end: {duration:.2f}s -> {trim_seconds:.2f}s"
                    )
            else:
                logger.info("No end-frame anomaly detected, skipping trim")

            # Step 3: Create reversed copy
            base, ext = os.path.splitext(source_path)
            reversed_path = f"{base}_reversed{ext}"
            intermediate_files.append(reversed_path)

            success = await reverse_video(source_path, reversed_path)
            if not success:
                raise ValueError("Failed to create reversed video")

            # Step 4: Concatenate original + reversed
            base, ext = os.path.splitext(processed_path)
            looped_path = f"{base}_looped{ext}"

            success = await concat_videos(
                [source_path, reversed_path], looped_path
            )
            if not success:
                raise ValueError("Failed to concatenate videos for loop")

            # Get final duration
            looped_duration = await get_video_duration(looped_path)
            if looped_duration is None:
                raise ValueError("Could not determine looped video duration")

            logger.info(
                f"Video loop created: {looped_path} ({looped_duration:.2f}s)"
            )
            return looped_path, looped_duration

        finally:
            # Clean up intermediate files
            for path in intermediate_files:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        logger.warning(f"Failed to clean up {path}: {e}")

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if FFmpeg is available on the system"""
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# Global instance
video_service = VideoService()
