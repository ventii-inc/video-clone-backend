"""Worker client for API server → worker communication"""

import os
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import httpx

from app.utils import logger


@dataclass
class WorkerResponse:
    """Response from worker service"""

    success: bool
    job_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    queue_position: Optional[int] = None


@dataclass
class WorkerCapacity:
    """Worker capacity information"""

    available_slots: int
    max_concurrent: int
    current_jobs: int
    queue_depth: int = 0


class WorkerClient:
    """Client for API server to communicate with worker instances"""

    def __init__(self):
        self._worker_url: Optional[str] = None
        self._api_key: Optional[str] = None
        self._timeout: int = 30
        self._max_retries: int = 3

    @property
    def worker_url(self) -> str:
        if self._worker_url is None:
            self._worker_url = os.getenv("WORKER_SERVICE_URL", "").rstrip("/")
        return self._worker_url

    @property
    def api_key(self) -> str:
        if self._api_key is None:
            self._api_key = os.getenv("WORKER_API_KEY", "")
        return self._api_key

    @property
    def timeout(self) -> int:
        return int(os.getenv("WORKER_CLIENT_TIMEOUT", str(self._timeout)))

    @property
    def is_enabled(self) -> bool:
        """Check if worker service is configured and enabled"""
        return bool(self.worker_url) and bool(self.api_key)

    def _get_headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def submit_avatar_job(
        self,
        job_id: UUID,
        video_model_id: UUID,
        user_id: int,
        video_url: str,
        callback_url: str,
        options: Optional[dict] = None,
    ) -> WorkerResponse:
        """
        Submit an avatar generation job to the worker.

        Args:
            job_id: Unique job identifier
            video_model_id: Video model being processed
            user_id: Owner of the job
            video_url: Presigned S3 URL to download source video
            callback_url: URL for completion callback
            options: Processing options (max_frames, img_size, etc.)

        Returns:
            WorkerResponse with submission status
        """
        if not self.is_enabled:
            return WorkerResponse(
                success=False,
                error="Worker service not configured",
            )

        payload = {
            "job_id": str(job_id),
            "video_model_id": str(video_model_id),
            "user_id": user_id,
            "video_url": video_url,
            "callback_url": callback_url,
        }
        if options:
            payload["options"] = options

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    logger.info(
                        f"Submitting avatar job {job_id} to worker "
                        f"(attempt {attempt + 1}/{self._max_retries})"
                    )

                    response = await client.post(
                        f"{self.worker_url}/api/v1/worker/jobs/avatar",
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code in (200, 201):
                        data = response.json()
                        logger.info(f"Avatar job {job_id} submitted to worker")
                        return WorkerResponse(
                            success=data.get("success", True),
                            job_id=data.get("job_id", str(job_id)),
                            message=data.get("message", "Job accepted"),
                            queue_position=data.get("queue_position"),
                        )

                    # Worker at capacity - don't retry
                    if response.status_code == 503:
                        logger.warning(f"Worker at capacity, job {job_id} not accepted")
                        return WorkerResponse(
                            success=False,
                            job_id=str(job_id),
                            error="Worker at capacity",
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"Worker API error: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        return WorkerResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"Worker returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"Worker request timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to worker: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"Worker request failed: {e}", exc_info=True)
                return WorkerResponse(success=False, error=str(e))

        return WorkerResponse(
            success=False,
            error=f"Failed to submit job after {self._max_retries} attempts",
        )

    async def submit_video_job(
        self,
        video_id: UUID,
        avatar_id: UUID,
        text: str,
        user_id: int,
        voice_model_id: Optional[UUID] = None,
        voice_reference_id: Optional[str] = None,
        callback_url: str = "",
        options: Optional[dict] = None,
    ) -> WorkerResponse:
        """
        Submit a video generation job to the worker.

        Args:
            video_id: Generated video ID
            avatar_id: Avatar to use for generation
            text: Text to synthesize
            user_id: Owner of the job
            voice_model_id: Voice model for TTS
            voice_reference_id: Fish Audio model ID for TTS (from VoiceModel.reference_id)
            callback_url: URL for completion callback
            options: Generation options

        Returns:
            WorkerResponse with submission status
        """
        if not self.is_enabled:
            return WorkerResponse(
                success=False,
                error="Worker service not configured",
            )

        payload = {
            "video_id": str(video_id),
            "avatar_id": str(avatar_id),
            "text": text,
            "callback_url": callback_url,
        }
        if voice_model_id:
            payload["voice_model_id"] = str(voice_model_id)
        if voice_reference_id:
            payload["voice_reference_id"] = voice_reference_id

        # Include user_id in options for worker
        options = options or {}
        options["user_id"] = user_id
        payload["options"] = options

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    logger.info(
                        f"Submitting video job {video_id} to worker "
                        f"(attempt {attempt + 1}/{self._max_retries})"
                    )

                    response = await client.post(
                        f"{self.worker_url}/api/v1/worker/jobs/video",
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code in (200, 201):
                        data = response.json()
                        logger.info(f"Video job {video_id} submitted to worker")
                        return WorkerResponse(
                            success=data.get("success", True),
                            job_id=data.get("job_id", str(video_id)),
                            message=data.get("message", "Job accepted"),
                            queue_position=data.get("queue_position"),
                        )

                    # Worker at capacity
                    if response.status_code == 503:
                        logger.warning(f"Worker at capacity, video job {video_id} not accepted")
                        return WorkerResponse(
                            success=False,
                            job_id=str(video_id),
                            error="Worker at capacity",
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"Worker API error: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        return WorkerResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"Worker returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"Worker request timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to worker: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"Worker request failed: {e}", exc_info=True)
                return WorkerResponse(success=False, error=str(e))

        return WorkerResponse(
            success=False,
            error=f"Failed to submit job after {self._max_retries} attempts",
        )

    async def check_capacity(self) -> Optional[WorkerCapacity]:
        """
        Check available capacity on the worker.

        Returns:
            WorkerCapacity if successful, None if failed
        """
        if not self.is_enabled:
            return None

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                response = await client.get(
                    f"{self.worker_url}/api/v1/worker/capacity",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    data = response.json()
                    return WorkerCapacity(
                        available_slots=data.get("available_slots", 0),
                        max_concurrent=data.get("max_concurrent", 0),
                        current_jobs=data.get("current_jobs", 0),
                        queue_depth=data.get("queue_depth", 0),
                    )

                logger.warning(f"Capacity check failed: {response.status_code}")
                return None

        except Exception as e:
            logger.warning(f"Failed to check worker capacity: {e}")
            return None

    async def health_check(self) -> bool:
        """
        Check if the worker is healthy.

        Returns:
            True if worker is healthy, False otherwise
        """
        if not self.worker_url:
            logger.warning("[DEBUG] health_check: no worker_url configured")
            return False

        try:
            url = f"{self.worker_url}/api/v1/worker/health"
            logger.info(f"[DEBUG] health_check: checking {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                logger.info(f"[DEBUG] health_check: status={response.status_code}, body={response.text[:200]}")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("status") in ("healthy", "degraded")
                return False
        except Exception as e:
            logger.warning(f"[DEBUG] health_check failed: {e}")
            return False


# Singleton instance
worker_client = WorkerClient()
