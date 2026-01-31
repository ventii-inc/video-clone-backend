"""Worker service for executing avatar/video generation jobs"""

import asyncio
import os
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Optional
from uuid import UUID

from app.services.livetalking import livetalking_cli_service
from app.services.s3 import s3_service
from app.services.worker.api_callback_client import api_callback_client
from app.utils import logger


# Directory for downloaded source videos
WORKER_TEMP_DIR = "/tmp/worker_jobs"


class WorkerService:
    """Service for executing jobs on the worker instance"""

    def __init__(self):
        self._max_concurrent: Optional[int] = None
        self._current_jobs: int = 0
        self._job_lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        """Maximum concurrent jobs allowed on this worker"""
        if self._max_concurrent is None:
            self._max_concurrent = int(os.getenv("AVATAR_MAX_CONCURRENT", "3"))
        return self._max_concurrent

    @property
    def current_jobs(self) -> int:
        """Number of jobs currently being processed"""
        return self._current_jobs

    @property
    def available_slots(self) -> int:
        """Number of slots available for new jobs"""
        return max(0, self.max_concurrent - self._current_jobs)

    async def can_accept_job(self) -> bool:
        """Check if worker can accept a new job"""
        return self._current_jobs < self.max_concurrent

    async def _increment_jobs(self) -> bool:
        """Increment job counter if slot available. Returns True if successful."""
        async with self._job_lock:
            if self._current_jobs < self.max_concurrent:
                self._current_jobs += 1
                return True
            return False

    async def _decrement_jobs(self) -> None:
        """Decrement job counter"""
        async with self._job_lock:
            self._current_jobs = max(0, self._current_jobs - 1)

    def _ensure_temp_dir(self) -> None:
        """Ensure temp directory exists"""
        Path(WORKER_TEMP_DIR).mkdir(parents=True, exist_ok=True)

    async def execute_avatar_job(
        self,
        job_id: UUID,
        video_model_id: UUID,
        user_id: int,
        video_url: str,
        callback_url: str,
        options: Optional[dict] = None,
    ) -> dict:
        """
        Execute an avatar generation job.

        This is the main entry point for avatar jobs sent from the API server.
        It downloads the video, runs CLI generation, uploads results, and sends callbacks.

        Args:
            job_id: Unique job identifier
            video_model_id: Video model being processed
            user_id: Owner of the job
            video_url: Presigned URL to download source video
            callback_url: URL for completion callback (not used - we use configured API server)
            options: Processing options (max_frames, img_size, model)

        Returns:
            Dict with job execution result
        """
        start_time = time.time()
        avatar_id = str(video_model_id)
        video_path = None

        # Check if we can accept the job
        if not await self._increment_jobs():
            return {
                "success": False,
                "error": "Worker at capacity",
                "available_slots": 0,
            }

        try:
            logger.info(f"Starting avatar job {job_id} for video_model {video_model_id}")

            # Parse options
            options = options or {}
            max_frames = options.get("max_frames", 1800)
            img_size = options.get("img_size", 256)

            # Send initial progress
            await api_callback_client.send_progress(
                job_id=job_id,
                stage="preparing",
                progress_percent=5,
                message="Downloading source video",
            )

            # Download video from presigned URL
            self._ensure_temp_dir()
            video_path = os.path.join(WORKER_TEMP_DIR, f"{job_id}_source.mp4")

            download_success = await self._download_video(video_url, video_path)
            if not download_success:
                raise ValueError("Failed to download source video")

            await api_callback_client.send_progress(
                job_id=job_id,
                stage="preparing",
                progress_percent=15,
                message="Video downloaded, starting avatar generation",
            )

            # Execute avatar generation via CLI
            await api_callback_client.send_progress(
                job_id=job_id,
                stage="training",
                progress_percent=20,
                message="Generating avatar frames",
            )

            result = await livetalking_cli_service.generate_avatar(
                video_path=video_path,
                avatar_id=avatar_id,
                user_id=user_id,
                img_size=img_size,
                max_frames=max_frames,
                upload_to_s3=False,  # We'll handle S3 upload ourselves
            )

            if not result.success:
                raise ValueError(result.error or "Avatar generation failed")

            await api_callback_client.send_progress(
                job_id=job_id,
                stage="finalizing",
                progress_percent=80,
                message="Uploading avatar to S3",
            )

            # Upload avatar TAR to S3
            s3_key = await self._upload_avatar_to_s3(
                avatar_id=avatar_id,
                user_id=user_id,
                avatar_path=result.avatar_path,
            )

            if not s3_key:
                raise ValueError("Failed to upload avatar to S3")

            # Calculate processing time
            processing_time = time.time() - start_time

            # Send completion callback
            await api_callback_client.send_completion(
                job_id=job_id,
                status="completed",
                s3_key=s3_key,
                frame_count=result.frame_count,
                processing_time_seconds=processing_time,
            )

            logger.info(
                f"Avatar job {job_id} completed successfully in {processing_time:.1f}s, "
                f"frames={result.frame_count}, s3_key={s3_key}"
            )

            return {
                "success": True,
                "job_id": str(job_id),
                "s3_key": s3_key,
                "frame_count": result.frame_count,
                "processing_time_seconds": processing_time,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Avatar job {job_id} failed: {error_msg}", exc_info=True)

            # Send failure callback
            await api_callback_client.send_completion(
                job_id=job_id,
                status="failed",
                error_message=error_msg,
                error_code="GENERATION_FAILED",
            )

            return {
                "success": False,
                "job_id": str(job_id),
                "error": error_msg,
            }

        finally:
            # Clean up temp video file
            if video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception as e:
                    logger.warning(f"Failed to clean up temp video: {e}")

            await self._decrement_jobs()

    async def execute_video_job(
        self,
        video_id: UUID,
        avatar_id: UUID,
        text: str,
        user_id: int,
        voice_model_id: Optional[UUID] = None,
        callback_url: str = "",
        options: Optional[dict] = None,
    ) -> dict:
        """
        Execute a video generation job.

        Args:
            video_id: Generated video ID
            avatar_id: Avatar (video model) to use
            text: Text to synthesize
            user_id: Owner of the job
            voice_model_id: Voice model for TTS
            callback_url: URL for completion callback
            options: Generation options

        Returns:
            Dict with job execution result
        """
        start_time = time.time()
        output_path = None

        # Check if we can accept the job
        if not await self._increment_jobs():
            return {
                "success": False,
                "error": "Worker at capacity",
                "available_slots": 0,
            }

        try:
            logger.info(f"Starting video job {video_id} with avatar {avatar_id}")

            # Ensure avatar is available locally
            avatar_available = await livetalking_cli_service.ensure_avatar_local(
                avatar_id=str(avatar_id),
                user_id=user_id,
            )

            if not avatar_available:
                raise ValueError(f"Avatar {avatar_id} not available")

            # Generate output path
            self._ensure_temp_dir()
            output_path = os.path.join(WORKER_TEMP_DIR, f"{video_id}.mp4")

            # Execute video generation
            ref_file = str(voice_model_id) if voice_model_id else None
            result = await livetalking_cli_service.generate_video(
                avatar_id=str(avatar_id),
                text=text,
                output_path=output_path,
                user_id=user_id,
                ref_file=ref_file,
                upload_to_s3=True,  # Upload via CLI service
            )

            if not result.success:
                raise ValueError(result.error or "Video generation failed")

            processing_time = time.time() - start_time

            logger.info(
                f"Video job {video_id} completed in {processing_time:.1f}s, "
                f"duration={result.duration}s, s3_key={result.s3_key}"
            )

            # Send completion callback to API server
            await api_callback_client.send_video_completion(
                video_id=video_id,
                s3_key=result.s3_key,
                duration=result.duration or 0,
                processing_time_seconds=processing_time,
            )

            return {
                "success": True,
                "video_id": str(video_id),
                "s3_key": result.s3_key,
                "duration": result.duration,
                "processing_time_seconds": processing_time,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Video job {video_id} failed: {error_msg}", exc_info=True)

            # Send failure callback to API server
            await api_callback_client.send_video_failure(
                video_id=video_id,
                error_message=error_msg,
            )

            return {
                "success": False,
                "video_id": str(video_id),
                "error": error_msg,
            }

        finally:
            # Clean up output file (already uploaded to S3)
            if output_path and os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception as e:
                    logger.warning(f"Failed to clean up output video: {e}")

            await self._decrement_jobs()

    async def _download_video(self, url: str, local_path: str) -> bool:
        """
        Download video from presigned URL.

        Args:
            url: Presigned S3 URL
            local_path: Local path to save video

        Returns:
            True if successful
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                logger.info(f"Downloading video to {local_path}")

                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        logger.error(f"Download failed: {response.status_code}")
                        return False

                    with open(local_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)

            file_size = os.path.getsize(local_path)
            logger.info(f"Downloaded video: {file_size / 1024 / 1024:.1f}MB")
            return True

        except Exception as e:
            logger.error(f"Failed to download video: {e}", exc_info=True)
            return False

    async def _upload_avatar_to_s3(
        self,
        avatar_id: str,
        user_id: int,
        avatar_path: str,
    ) -> Optional[str]:
        """
        TAR and upload avatar directory to S3.

        Args:
            avatar_id: Avatar identifier
            user_id: User ID for S3 path
            avatar_path: Local avatar directory path

        Returns:
            S3 key if successful, None otherwise
        """
        tar_path = None
        try:
            # Create TAR file
            tar_path = f"{avatar_path}.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(avatar_path, arcname=avatar_id)

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
            # Clean up TAR file
            if tar_path and os.path.exists(tar_path):
                os.remove(tar_path)

    def get_gpu_info(self) -> dict:
        """
        Get GPU information for health check.

        Returns:
            Dict with gpu_available and gpu_name
        """
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gpu_name = result.stdout.strip().split("\n")[0]
                return {"gpu_available": True, "gpu_name": gpu_name}
        except Exception:
            pass

        return {"gpu_available": False, "gpu_name": None}

    async def health_check(self) -> dict:
        """
        Perform health check on worker.

        Returns:
            Dict with health status information
        """
        gpu_info = self.get_gpu_info()
        cli_health = await livetalking_cli_service.health_check()

        status = "healthy"
        if not gpu_info["gpu_available"]:
            status = "degraded"
        if not cli_health.get("cli_available"):
            status = "unhealthy"

        return {
            "status": status,
            "mode": "worker",
            "gpu_available": gpu_info["gpu_available"],
            "gpu_name": gpu_info["gpu_name"],
            "processing_slots": self.available_slots,
            "current_jobs": self.current_jobs,
            "max_concurrent": self.max_concurrent,
            "cli_available": cli_health.get("cli_available", False),
            "livetalking_root_exists": cli_health.get("livetalking_root_exists", False),
        }


# Singleton instance
worker_service = WorkerService()
