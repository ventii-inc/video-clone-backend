"""LipSync remote service client for avatar generation"""

import os
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import httpx

from app.utils import logger


@dataclass
class LipSyncResponse:
    """Response from LipSync service"""

    success: bool
    job_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    s3_key: Optional[str] = None
    frame_count: Optional[int] = None
    processing_time_seconds: Optional[float] = None


@dataclass
class LipSyncJobOptions:
    """Options for avatar generation job"""

    max_frames: int = 1800
    img_size: int = 256
    model: str = "wav2lip"


class LipSyncClient:
    """Client for communicating with remote Lip-Sync-Experiment service"""

    def __init__(self):
        self._service_url: Optional[str] = None
        self._api_key: Optional[str] = None
        self._timeout: int = 30
        self._max_retries: int = 3

    @property
    def service_url(self) -> str:
        if self._service_url is None:
            self._service_url = os.getenv("LIPSYNC_SERVICE_URL", "").rstrip("/")
        return self._service_url

    @property
    def api_key(self) -> str:
        if self._api_key is None:
            self._api_key = os.getenv("LIPSYNC_API_KEY", "")
        return self._api_key

    @property
    def timeout(self) -> int:
        return int(os.getenv("LIPSYNC_TIMEOUT", str(self._timeout)))

    @property
    def is_enabled(self) -> bool:
        """Check if remote LipSync service is configured and enabled"""
        enabled = os.getenv("LIPSYNC_ENABLED", "false").lower() == "true"
        return enabled and bool(self.service_url) and bool(self.api_key)

    def _get_headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def submit_job(
        self,
        job_id: UUID,
        video_model_id: UUID,
        user_id: int,
        video_url: str,
        callback_url: str,
        options: Optional[LipSyncJobOptions] = None,
    ) -> LipSyncResponse:
        """
        Submit a new avatar generation job to the remote LipSync service.

        Args:
            job_id: Unique job identifier
            video_model_id: The video model being processed
            user_id: Owner of the job
            video_url: Presigned S3 URL to download the source video
            callback_url: URL to call back when processing is complete
            options: Avatar generation options

        Returns:
            LipSyncResponse with job submission status
        """
        if not self.is_enabled:
            return LipSyncResponse(
                success=False,
                error="LipSync service not configured or disabled",
            )

        if options is None:
            options = LipSyncJobOptions()

        payload = {
            "job_id": str(job_id),
            "video_model_id": str(video_model_id),
            "user_id": user_id,
            "video_url": video_url,
            "callback_url": callback_url,
            "options": {
                "max_frames": options.max_frames,
                "img_size": options.img_size,
                "model": options.model,
            },
        }

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    logger.info(
                        f"Submitting job {job_id} to LipSync service "
                        f"(attempt {attempt + 1}/{self._max_retries})"
                    )

                    response = await client.post(
                        f"{self.service_url}/api/v1/jobs",
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 200 or response.status_code == 201:
                        data = response.json()
                        logger.info(f"Job {job_id} submitted successfully to LipSync service")
                        return LipSyncResponse(
                            success=True,
                            job_id=data.get("job_id", str(job_id)),
                            status=data.get("status", "queued"),
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"LipSync API error: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        return LipSyncResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"LipSync service returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"LipSync request timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to LipSync service: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"LipSync request failed: {e}", exc_info=True)
                return LipSyncResponse(success=False, error=str(e))

        return LipSyncResponse(
            success=False,
            error=f"Failed to submit job after {self._max_retries} attempts",
        )

    async def get_job_status(self, job_id: UUID) -> LipSyncResponse:
        """
        Get the current status of a job from the LipSync service.

        Args:
            job_id: The job ID to check

        Returns:
            LipSyncResponse with current job status
        """
        if not self.is_enabled:
            return LipSyncResponse(
                success=False,
                error="LipSync service not configured or disabled",
            )

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                response = await client.get(
                    f"{self.service_url}/api/v1/jobs/{job_id}",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    data = response.json()
                    return LipSyncResponse(
                        success=True,
                        job_id=str(job_id),
                        status=data.get("status"),
                        s3_key=data.get("s3_key"),
                        frame_count=data.get("frame_count"),
                        processing_time_seconds=data.get("processing_time_seconds"),
                    )

                if response.status_code == 404:
                    return LipSyncResponse(
                        success=False,
                        error=f"Job {job_id} not found",
                    )

                return LipSyncResponse(
                    success=False,
                    error=f"Status check failed: {response.status_code} - {response.text}",
                )

        except httpx.TimeoutException:
            return LipSyncResponse(success=False, error="Request timed out")
        except Exception as e:
            return LipSyncResponse(success=False, error=str(e))

    async def cancel_job(self, job_id: UUID) -> LipSyncResponse:
        """
        Cancel a running job on the LipSync service.

        Args:
            job_id: The job ID to cancel

        Returns:
            LipSyncResponse indicating cancellation result
        """
        if not self.is_enabled:
            return LipSyncResponse(
                success=False,
                error="LipSync service not configured or disabled",
            )

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                response = await client.delete(
                    f"{self.service_url}/api/v1/jobs/{job_id}",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    logger.info(f"Job {job_id} cancelled on LipSync service")
                    return LipSyncResponse(
                        success=True,
                        job_id=str(job_id),
                        status="cancelled",
                    )

                return LipSyncResponse(
                    success=False,
                    error=f"Cancel failed: {response.status_code} - {response.text}",
                )

        except Exception as e:
            return LipSyncResponse(success=False, error=str(e))

    async def check_capacity(self) -> dict:
        """
        Check available processing capacity on the LipSync service.

        Returns:
            Dict with capacity info: available_slots, max_concurrent, queue_depth
        """
        if not self.is_enabled:
            return {"error": "LipSync service not configured or disabled"}

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                response = await client.get(
                    f"{self.service_url}/api/v1/capacity",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    return response.json()

                return {"error": f"Capacity check failed: {response.status_code}"}

        except Exception as e:
            return {"error": str(e)}

    async def health_check(self) -> bool:
        """
        Check if the LipSync service is healthy.

        Returns:
            True if service is healthy, False otherwise
        """
        if not self.service_url:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.service_url}/api/v1/health")
                return response.status_code == 200
        except Exception:
            return False


# Singleton instance
lipsync_client = LipSyncClient()
