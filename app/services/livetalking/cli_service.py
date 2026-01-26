"""LiveTalking CLI service for local subprocess execution.

This service executes LiveTalking commands via CLI when both backends
are deployed on the same server.
"""

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.services.s3 import s3_service
from app.services.video import get_video_duration

logger = logging.getLogger(__name__)

# Frame limits for avatar generation
MAX_FRAMES_DEFAULT = 1000  # For normal avatars (with speech)
MAX_FRAMES_SILENT = 100    # For silent/idle avatars


@dataclass
class AvatarGenerationResult:
    """Result from avatar generation CLI"""
    success: bool
    avatar_id: str
    avatar_path: Optional[str] = None
    frame_count: Optional[int] = None
    generation_time: Optional[float] = None
    error: Optional[str] = None
    s3_key: Optional[str] = None


@dataclass
class VideoGenerationResult:
    """Result from video generation CLI"""
    success: bool
    output_path: Optional[str] = None
    duration: Optional[float] = None
    inference_time: Optional[float] = None
    total_time: Optional[float] = None
    error: Optional[str] = None
    s3_key: Optional[str] = None


class LiveTalkingCLIService:
    """Service for executing LiveTalking operations via CLI subprocess."""

    def __init__(self):
        self._settings: Optional[LiveTalkingSettings] = None

    def _get_settings(self) -> LiveTalkingSettings:
        """Get fresh settings from environment."""
        if self._settings is None:
            self._settings = LiveTalkingSettings()
        return self._settings

    @property
    def livetalking_root(self) -> str:
        """Root directory of LiveTalking installation."""
        return self._get_settings().LIVETALKING_ROOT

    @property
    def livetalking_venv(self) -> str:
        """Path to LiveTalking virtual environment."""
        return self._get_settings().LIVETALKING_VENV

    @property
    def avatar_local_path(self) -> str:
        """Local path for storing avatars."""
        return self._get_settings().AVATAR_LOCAL_PATH

    def _get_venv_python(self) -> str:
        """Get path to Python in LiveTalking venv."""
        return os.path.join(self.livetalking_venv, "bin", "python")

    def _get_activate_command(self) -> str:
        """Get command to activate LiveTalking venv."""
        return f"source {self.livetalking_venv}/bin/activate"

    async def _run_cli_command(
        self,
        command: list[str],
        timeout: int = 600,
        cwd: Optional[str] = None,
    ) -> tuple[int, str, str]:
        """
        Run a CLI command in LiveTalking's venv.

        Args:
            command: Command and arguments to run
            timeout: Timeout in seconds
            cwd: Working directory (defaults to livetalking_root)

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        work_dir = cwd or self.livetalking_root

        # Set up environment with PYTHONPATH for LiveTalking modules
        # face_detection and other modules are in wav2lip/ directory
        env = os.environ.copy()
        wav2lip_path = os.path.join(self.livetalking_root, "wav2lip")
        pythonpath = f"{self.livetalking_root}:{wav2lip_path}"
        if "PYTHONPATH" in env:
            pythonpath = f"{pythonpath}:{env['PYTHONPATH']}"
        env["PYTHONPATH"] = pythonpath

        # Build command using venv Python directly (avoids shell compatibility issues)
        # Replace "python" with the venv's Python path
        venv_python = self._get_venv_python()
        modified_command = command.copy()
        if modified_command[0] == "python":
            modified_command[0] = venv_python
        full_command = " ".join(modified_command)

        logger.info(f"Running CLI command: {full_command}")
        logger.info(f"Working directory: {work_dir}")
        logger.info(f"PYTHONPATH: {pythonpath}")

        try:
            process = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            stdout_str = stdout.decode("utf-8") if stdout else ""
            stderr_str = stderr.decode("utf-8") if stderr else ""

            logger.info(f"Command exit code: {process.returncode}")
            if stdout_str:
                logger.info(f"stdout (first 1000 chars): {stdout_str[:1000]}")
            if stderr_str:
                # Always log stderr for debugging
                log_level = logger.warning if process.returncode != 0 else logger.info
                log_level(f"stderr (first 1000 chars): {stderr_str[:1000]}")

            return process.returncode, stdout_str, stderr_str

        except asyncio.TimeoutError:
            logger.error(f"Command timed out after {timeout}s: {cmd_str}")
            return -1, "", f"Command timed out after {timeout} seconds"
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return -1, "", str(e)

    def _run_cli_command_detached(
        self,
        command: list[str],
        output_file: str,
        cwd: Optional[str] = None,
    ) -> int:
        """
        Run command as a detached process that survives parent termination.

        The process writes stdout/stderr to output_file and continues running
        even if the parent process (FastAPI server) is killed.

        Args:
            command: Command and arguments to run
            output_file: Path to file for stdout/stderr output
            cwd: Working directory (defaults to livetalking_root)

        Returns:
            PID of the spawned process
        """
        work_dir = cwd or self.livetalking_root

        # Set up environment with PYTHONPATH for LiveTalking modules
        env = os.environ.copy()
        wav2lip_path = os.path.join(self.livetalking_root, "wav2lip")
        pythonpath = f"{self.livetalking_root}:{wav2lip_path}"
        if "PYTHONPATH" in env:
            pythonpath = f"{pythonpath}:{env['PYTHONPATH']}"
        env["PYTHONPATH"] = pythonpath

        # Replace "python" with the venv's Python path
        venv_python = self._get_venv_python()
        modified_command = command.copy()
        if modified_command[0] == "python":
            modified_command[0] = venv_python

        logger.info(f"Running detached CLI command: {' '.join(modified_command)}")
        logger.info(f"Output file: {output_file}")
        logger.info(f"Working directory: {work_dir}")

        # Ensure output directory exists
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)

        # Open output file for writing
        with open(output_file, 'w') as outfile:
            # Start the process fully detached:
            # - start_new_session=True creates new process group (won't receive parent's signals)
            # - stdout/stderr go to file instead of being captured
            # - We don't wait for completion
            process = subprocess.Popen(
                modified_command,
                stdout=outfile,
                stderr=subprocess.STDOUT,
                cwd=work_dir,
                env=env,
                start_new_session=True,  # Detach from parent process group
            )

        logger.info(f"Started detached process with PID: {process.pid}")
        return process.pid

    def is_process_running(self, pid: int) -> bool:
        """
        Check if a process with the given PID is still running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is running, False otherwise
        """
        if pid is None:
            return False
        try:
            # Send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def read_process_output(self, output_file: str) -> Optional[dict]:
        """
        Read and parse JSON output from process output file.

        The genavatar.py script outputs JSON lines. This method reads the file
        and returns the parsed JSON result if found.

        Args:
            output_file: Path to the output file

        Returns:
            Parsed JSON dict if successful result found, None otherwise
        """
        if not output_file or not os.path.exists(output_file):
            return None

        try:
            with open(output_file, 'r') as f:
                content = f.read()

            # Look for JSON output in the file
            for line in content.strip().split("\n"):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        # Return if it looks like a result (has avatar_id or success field)
                        if "avatar_id" in data or "success" in data:
                            return data
                    except json.JSONDecodeError:
                        continue

            return None
        except Exception as e:
            logger.error(f"Error reading process output file {output_file}: {e}")
            return None

    def check_avatar_generation_result(
        self,
        pid: int,
        output_file: str,
        avatar_id: str,
    ) -> tuple[bool, Optional[dict], Optional[str]]:
        """
        Check if avatar generation has completed and get the result.

        Args:
            pid: Process ID to check
            output_file: Path to output file
            avatar_id: Avatar ID being generated

        Returns:
            Tuple of (is_complete, result_data, error_message)
            - is_complete: True if process finished (success or failure)
            - result_data: Dict with result info if successful
            - error_message: Error string if failed
        """
        # FIRST: Check output file for final result
        # This handles PID reuse - if output has result, process is done
        # When a CLI process fails quickly, the PID gets freed and reused by
        # another process. By checking output first, we detect completion
        # regardless of what process currently has that PID.
        output_data = self.read_process_output(output_file)

        # If output indicates explicit failure, return immediately
        if output_data and output_data.get("success") is False:
            error_msg = output_data.get("error", "Avatar generation failed")
            logger.info(f"Avatar {avatar_id} failed: {error_msg}")
            return (True, output_data, error_msg)

        # If output indicates success, verify avatar exists
        if output_data and output_data.get("success") is True:
            # Process completed successfully per output - verify avatar directory
            livetalking_avatar_path = os.path.join(
                self.livetalking_root, "data", "avatars", avatar_id
            )
            local_avatar_dir = self._get_avatar_local_dir(avatar_id)
            avatar_exists = os.path.exists(livetalking_avatar_path) or os.path.exists(local_avatar_dir)

            if avatar_exists:
                frame_count = output_data.get("frame_count", 0)
                check_path = local_avatar_dir if os.path.exists(local_avatar_dir) else livetalking_avatar_path
                return (True, {
                    "success": True,
                    "avatar_id": avatar_id,
                    "frame_count": frame_count,
                    "avatar_path": check_path,
                }, None)

        # No definitive result in output - check if process is still running
        process_running = self.is_process_running(pid)

        if process_running:
            # Process still running, no result yet
            return (False, None, None)

        # Check if avatar directory was created (indicates success)
        livetalking_avatar_path = os.path.join(
            self.livetalking_root, "data", "avatars", avatar_id
        )
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)

        avatar_exists = os.path.exists(livetalking_avatar_path) or os.path.exists(local_avatar_dir)

        if avatar_exists:
            # Count frames to verify generation worked
            frame_count = 0
            check_path = local_avatar_dir if os.path.exists(local_avatar_dir) else livetalking_avatar_path
            face_imgs_dir = os.path.join(check_path, "face_imgs")
            if os.path.exists(face_imgs_dir):
                frame_count = len([f for f in os.listdir(face_imgs_dir) if f.endswith(".png")])

            if frame_count > 0:
                return (True, {
                    "success": True,
                    "avatar_id": avatar_id,
                    "frame_count": frame_count,
                    "avatar_path": check_path,
                }, None)

        # Process finished but no valid avatar found - read error from output
        error_msg = "Avatar generation failed - no frames generated"
        if output_file and os.path.exists(output_file):
            try:
                with open(output_file, 'r') as f:
                    content = f.read()
                    # Get last 500 chars as error context
                    if content:
                        error_msg = content[-500:] if len(content) > 500 else content
            except Exception:
                pass

        return (True, None, error_msg)

    def _ensure_avatar_directory(self) -> None:
        """Ensure local avatar directory exists."""
        Path(self.avatar_local_path).mkdir(parents=True, exist_ok=True)

    def _get_avatar_local_dir(self, avatar_id: str) -> str:
        """Get local directory path for an avatar."""
        return os.path.join(self.avatar_local_path, avatar_id)

    async def generate_avatar(
        self,
        video_path: str,
        avatar_id: str,
        user_id: int,
        img_size: int = 256,
        pads: str = "0 10 0 0",
        face_det_batch_size: int = 16,
        upload_to_s3: bool = True,
        max_frames: int = MAX_FRAMES_DEFAULT,
        silent: bool = False,
    ) -> AvatarGenerationResult:
        """
        Generate an avatar from a video file using CLI.

        Args:
            video_path: Path to source video file (local)
            avatar_id: Unique identifier for the avatar
            user_id: User ID for S3 path organization
            img_size: Face crop size (96 for wav2lip, 256 for wav2lip256)
            pads: Padding values "top bottom left right"
            face_det_batch_size: Batch size for face detection
            upload_to_s3: Whether to upload avatar TAR to S3
            max_frames: Maximum frames to extract (default: 1000)
            silent: If True, uses reduced frame count (100) for idle avatars

        Returns:
            AvatarGenerationResult with status and paths
        """
        # Use reduced frame count for silent/idle avatars
        if silent:
            max_frames = MAX_FRAMES_SILENT

        self._ensure_avatar_directory()

        # Build command
        # The genavatar.py outputs to ./data/avatars/{avatar_id} by default
        # We'll move it to our avatar_local_path after generation
        command = [
            "python",
            "wav2lip/genavatar.py",
            "--avatar_id", avatar_id,
            "--video_path", video_path,
            "--img_size", str(img_size),
            "--pads", *pads.split(),
            "--face_det_batch_size", str(face_det_batch_size),
            "--max_frames", str(max_frames),
        ]

        logger.info(f"Generating avatar with max_frames={max_frames} (silent={silent})")

        # Execute command
        return_code, stdout, stderr = await self._run_cli_command(
            command,
            timeout=self._get_settings().LIVETALKING_AVATAR_TIMEOUT,
        )

        if return_code != 0:
            error_msg = stderr or stdout or "Unknown error during avatar generation"
            logger.error(f"Avatar generation failed for {avatar_id}: {error_msg}")
            return AvatarGenerationResult(
                success=False,
                avatar_id=avatar_id,
                error=error_msg[:500],
            )

        # Parse output if JSON
        result_data = {}
        try:
            # Try to find JSON in output
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    result_data = json.loads(line)
                    break
        except json.JSONDecodeError:
            logger.debug("Could not parse JSON from stdout, using defaults")

        # Default avatar path from LiveTalking
        livetalking_avatar_path = os.path.join(
            self.livetalking_root, "data", "avatars", avatar_id
        )

        # Our local avatar path
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)

        # Resolve paths to handle symlinks and normalize
        livetalking_resolved = os.path.realpath(livetalking_avatar_path)
        local_resolved = os.path.realpath(local_avatar_dir)

        # Move avatar from LiveTalking's location to our avatar storage
        # Skip move if paths are the same (AVATAR_LOCAL_PATH == LIVETALKING_ROOT/data/avatars)
        if livetalking_resolved == local_resolved:
            # Same path - just check it exists
            if os.path.exists(local_avatar_dir):
                logger.info(f"Avatar already at correct location: {local_avatar_dir}")
            else:
                return AvatarGenerationResult(
                    success=False,
                    avatar_id=avatar_id,
                    error=f"Avatar directory not found after generation: {local_avatar_dir}",
                )
        elif os.path.exists(livetalking_avatar_path):
            if os.path.exists(local_avatar_dir):
                shutil.rmtree(local_avatar_dir)
            shutil.move(livetalking_avatar_path, local_avatar_dir)
            logger.info(f"Moved avatar to {local_avatar_dir}")
        elif os.path.exists(local_avatar_dir):
            logger.info(f"Avatar already at {local_avatar_dir}")
        else:
            return AvatarGenerationResult(
                success=False,
                avatar_id=avatar_id,
                error=f"Avatar directory not found after generation: {livetalking_avatar_path}",
            )

        # Count frames
        frame_count = 0
        face_imgs_dir = os.path.join(local_avatar_dir, "face_imgs")
        if os.path.exists(face_imgs_dir):
            frame_count = len([f for f in os.listdir(face_imgs_dir) if f.endswith(".png")])

        result = AvatarGenerationResult(
            success=True,
            avatar_id=avatar_id,
            avatar_path=local_avatar_dir,
            frame_count=result_data.get("frame_count", frame_count),
            generation_time=result_data.get("generation_time"),
        )

        # Upload to S3 if requested
        if upload_to_s3:
            s3_key = await self._upload_avatar_to_s3(
                avatar_id=avatar_id,
                user_id=user_id,
                local_avatar_dir=local_avatar_dir,
            )
            if s3_key:
                result.s3_key = s3_key
            else:
                logger.warning(f"Failed to upload avatar {avatar_id} to S3")

        return result

    def start_avatar_generation_detached(
        self,
        video_path: str,
        avatar_id: str,
        output_file: str,
        img_size: int = 256,
        pads: str = "0 10 0 0",
        face_det_batch_size: int = 16,
        max_frames: int = MAX_FRAMES_DEFAULT,
        silent: bool = False,
    ) -> int:
        """
        Start avatar generation as a detached process.

        This method returns immediately after spawning the process.
        The process continues running even if the parent server is restarted.

        Args:
            video_path: Path to source video file (local)
            avatar_id: Unique identifier for the avatar
            output_file: Path for stdout/stderr output
            img_size: Face crop size (96 for wav2lip, 256 for wav2lip256)
            pads: Padding values "top bottom left right"
            face_det_batch_size: Batch size for face detection
            max_frames: Maximum frames to extract (default: 1000)
            silent: If True, uses reduced frame count (100) for idle avatars

        Returns:
            PID of the spawned process
        """
        # Use reduced frame count for silent/idle avatars
        if silent:
            max_frames = MAX_FRAMES_SILENT

        self._ensure_avatar_directory()

        # Build command
        command = [
            "python",
            "wav2lip/genavatar.py",
            "--avatar_id", avatar_id,
            "--video_path", video_path,
            "--img_size", str(img_size),
            "--pads", *pads.split(),
            "--face_det_batch_size", str(face_det_batch_size),
            "--max_frames", str(max_frames),
        ]

        logger.info(f"Starting detached avatar generation with max_frames={max_frames} (silent={silent})")

        # Execute command in detached mode
        return self._run_cli_command_detached(command, output_file)

    async def _upload_avatar_to_s3(
        self,
        avatar_id: str,
        user_id: int,
        local_avatar_dir: str,
    ) -> Optional[str]:
        """
        TAR the avatar directory and upload to S3.

        Args:
            avatar_id: Avatar identifier
            user_id: User ID for S3 path
            local_avatar_dir: Local directory containing avatar files

        Returns:
            S3 key if successful, None otherwise
        """
        tar_path = None
        try:
            # Create TAR file
            tar_path = f"{local_avatar_dir}.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(local_avatar_dir, arcname=avatar_id)

            logger.info(f"Created TAR archive: {tar_path}")

            # Upload to S3
            s3_key = f"avatars/{user_id}/{avatar_id}.tar"
            await s3_service.upload_file(
                tar_path,
                s3_key,
                content_type="application/x-tar",
            )

            logger.info(f"Uploaded avatar TAR to S3: {s3_key}")
            return s3_key

        except Exception as e:
            logger.error(f"Failed to upload avatar to S3: {e}")
            return None
        finally:
            # Clean up TAR file (keep local avatar directory)
            if tar_path and os.path.exists(tar_path):
                os.remove(tar_path)

    async def generate_video(
        self,
        avatar_id: str,
        text: str,
        output_path: str,
        user_id: int,
        ref_file: Optional[str] = None,
        upload_to_s3: bool = True,
    ) -> VideoGenerationResult:
        """
        Generate a lip-synced video from avatar and text.

        Args:
            avatar_id: Avatar ID to use (must exist locally)
            text: Text to synthesize for lip-sync
            output_path: Local path for output video
            user_id: User ID for S3 path organization
            ref_file: Fish TTS reference voice ID
            upload_to_s3: Whether to upload video to S3

        Returns:
            VideoGenerationResult with status and paths
        """
        # Ensure avatar exists locally
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)
        if not os.path.exists(local_avatar_dir):
            # Try to download from S3
            downloaded = await self._download_avatar_from_s3(avatar_id, user_id)
            if not downloaded:
                return VideoGenerationResult(
                    success=False,
                    error=f"Avatar {avatar_id} not found locally or in S3",
                )

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build command
        command = [
            "python",
            "benchmark_e2e.py",
            "--mode", "cold",
            "--avatar_id", avatar_id,
            "--text", f'"{text}"',
            "--output", output_path,
        ]

        if ref_file:
            command.extend(["--ref_file", ref_file])

        # Execute command
        return_code, stdout, stderr = await self._run_cli_command(
            command,
            timeout=self._get_settings().LIVETALKING_VIDEO_TIMEOUT,
        )

        if return_code != 0:
            error_msg = stderr or stdout or "Unknown error during video generation"
            logger.error(f"Video generation failed for {avatar_id}: {error_msg}")
            return VideoGenerationResult(
                success=False,
                error=error_msg[:500],
            )

        # Check output file exists
        if not os.path.exists(output_path):
            return VideoGenerationResult(
                success=False,
                error="Output video file not created",
            )

        # Parse output for metrics
        result_data = {}
        try:
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    result_data = json.loads(line)
                    break
        except json.JSONDecodeError:
            pass

        # Get duration from CLI output or from the actual video file
        duration = result_data.get("audio_duration")
        if duration is None:
            try:
                duration = await get_video_duration(output_path)
                logger.info(f"Got video duration from file: {duration}s")
            except Exception as e:
                logger.warning(f"Failed to get video duration: {e}")

        result = VideoGenerationResult(
            success=True,
            output_path=output_path,
            duration=duration,
            inference_time=result_data.get("inference_time"),
            total_time=result_data.get("total_time"),
        )

        # Upload to S3 if requested
        if upload_to_s3:
            video_filename = os.path.basename(output_path)
            s3_key = f"generated-videos/{user_id}/{video_filename}"
            try:
                await s3_service.upload_file(
                    output_path,
                    s3_key,
                    content_type="video/mp4",
                )
                result.s3_key = s3_key
                logger.info(f"Uploaded video to S3: {s3_key}")
            except Exception as e:
                logger.warning(f"Failed to upload video to S3: {e}")

        return result

    async def _download_avatar_from_s3(
        self,
        avatar_id: str,
        user_id: int,
    ) -> bool:
        """
        Download and extract avatar TAR from S3.

        Args:
            avatar_id: Avatar identifier
            user_id: User ID for S3 path

        Returns:
            True if successful, False otherwise
        """
        s3_key = f"avatars/{user_id}/{avatar_id}.tar"
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)

        try:
            # Download TAR to temp file
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
                tmp_path = tmp.name

            success = await s3_service.download_file(s3_key, tmp_path)
            if not success:
                logger.warning(f"Avatar TAR not found in S3: {s3_key}")
                return False

            # Extract TAR
            self._ensure_avatar_directory()
            with tarfile.open(tmp_path, "r") as tar:
                tar.extractall(self.avatar_local_path)

            logger.info(f"Extracted avatar from S3: {avatar_id}")
            return os.path.exists(local_avatar_dir)

        except Exception as e:
            logger.error(f"Failed to download avatar from S3: {e}")
            return False
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def ensure_avatar_local(
        self,
        avatar_id: str,
        user_id: int,
    ) -> bool:
        """
        Ensure avatar is available locally, downloading from S3 if needed.

        Args:
            avatar_id: Avatar identifier
            user_id: User ID for S3 path

        Returns:
            True if avatar is available locally
        """
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)
        if os.path.exists(local_avatar_dir):
            return True
        return await self._download_avatar_from_s3(avatar_id, user_id)

    def avatar_exists_locally(self, avatar_id: str) -> bool:
        """Check if avatar exists in local storage."""
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)
        return os.path.exists(local_avatar_dir)

    def get_avatar_frame_count(self, avatar_id: str) -> int:
        """Get the number of frames in a local avatar."""
        local_avatar_dir = self._get_avatar_local_dir(avatar_id)
        face_imgs_dir = os.path.join(local_avatar_dir, "face_imgs")
        if os.path.exists(face_imgs_dir):
            return len([f for f in os.listdir(face_imgs_dir) if f.endswith(".png")])
        return 0

    async def health_check(self) -> dict:
        """
        Check if LiveTalking CLI is accessible and working.

        Returns:
            Dict with health status information
        """
        result = {
            "cli_available": False,
            "livetalking_root_exists": os.path.exists(self.livetalking_root),
            "venv_exists": os.path.exists(self._get_venv_python()),
            "avatar_path_exists": os.path.exists(self.avatar_local_path),
            "error": None,
        }

        if not result["livetalking_root_exists"]:
            result["error"] = f"LiveTalking root not found: {self.livetalking_root}"
            return result

        if not result["venv_exists"]:
            result["error"] = f"LiveTalking venv not found: {self.livetalking_venv}"
            return result

        # Test running a simple command
        return_code, stdout, stderr = await self._run_cli_command(
            ["python", "--version"],
            timeout=10,
        )

        if return_code == 0:
            result["cli_available"] = True
            result["python_version"] = stdout.strip()
        else:
            result["error"] = stderr or "Failed to execute Python in venv"

        return result


# Singleton instance
livetalking_cli_service = LiveTalkingCLIService()
