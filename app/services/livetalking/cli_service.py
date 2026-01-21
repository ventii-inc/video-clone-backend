"""LiveTalking CLI service for local subprocess execution.

This service executes LiveTalking commands via CLI when both backends
are deployed on the same server.
"""

import asyncio
import json
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.services.s3 import s3_service

logger = logging.getLogger(__name__)


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

        Returns:
            AvatarGenerationResult with status and paths
        """
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
        ]

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

        # Move avatar from LiveTalking's location to our avatar storage
        if os.path.exists(livetalking_avatar_path):
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
                error="Avatar directory not found after generation",
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

        result = VideoGenerationResult(
            success=True,
            output_path=output_path,
            duration=result_data.get("audio_duration"),
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
