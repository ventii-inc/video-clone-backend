"""API Callback Client for worker → API server communication"""

import os
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import httpx

from app.utils import logger


@dataclass
class CallbackResponse:
    """Response from API server callback"""

    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


class APICallbackClient:
    """Client for sending callbacks from worker to API server"""

    def __init__(self):
        self._api_server_url: Optional[str] = None
        self._api_key: Optional[str] = None
        self._timeout: int = 30
        self._max_retries: int = 3

    @property
    def api_server_url(self) -> str:
        if self._api_server_url is None:
            self._api_server_url = os.getenv("API_SERVER_URL", "").rstrip("/")
        return self._api_server_url

    @property
    def api_key(self) -> str:
        if self._api_key is None:
            self._api_key = os.getenv("API_SERVER_API_KEY", "")
        return self._api_key

    @property
    def timeout(self) -> int:
        return int(os.getenv("API_CALLBACK_TIMEOUT", str(self._timeout)))

    @property
    def is_configured(self) -> bool:
        """Check if API server connection is configured"""
        return bool(self.api_server_url) and bool(self.api_key)

    def _get_headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def send_progress(
        self,
        job_id: UUID,
        stage: str,
        progress_percent: int,
        message: Optional[str] = None,
    ) -> CallbackResponse:
        """
        Send progress update to API server.

        Args:
            job_id: The job ID
            stage: Current processing stage (preparing, training, finalizing)
            progress_percent: Progress percentage (0-100)
            message: Optional status message

        Returns:
            CallbackResponse with success/error status
        """
        if not self.is_configured:
            return CallbackResponse(
                success=False,
                error="API server not configured",
            )

        payload = {
            "stage": stage,
            "progress_percent": progress_percent,
        }
        if message:
            payload["message"] = message

        url = f"{self.api_server_url}/api/v1/internal/avatar/jobs/{job_id}/progress"

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    response = await client.post(
                        url,
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        return CallbackResponse(
                            success=data.get("success", True),
                            message="Progress update sent",
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"Progress callback failed: {response.status_code} - {response.text}"
                        logger.warning(error_msg)
                        return CallbackResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"Progress callback returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"Progress callback timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to API server: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"Progress callback failed: {e}", exc_info=True)
                return CallbackResponse(success=False, error=str(e))

        return CallbackResponse(
            success=False,
            error=f"Failed to send progress after {self._max_retries} attempts",
        )

    async def send_completion(
        self,
        job_id: UUID,
        status: str,
        s3_key: Optional[str] = None,
        frame_count: Optional[int] = None,
        processing_time_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> CallbackResponse:
        """
        Send job completion callback to API server.

        Args:
            job_id: The job ID
            status: Job status ('completed' or 'failed')
            s3_key: S3 key where result was uploaded (on success)
            frame_count: Number of frames generated
            processing_time_seconds: Total processing time
            error_message: Error message if failed
            error_code: Error code for categorization

        Returns:
            CallbackResponse with success/error status
        """
        if not self.is_configured:
            return CallbackResponse(
                success=False,
                error="API server not configured",
            )

        payload = {
            "status": status,
        }
        if s3_key:
            payload["s3_key"] = s3_key
        if frame_count is not None:
            payload["frame_count"] = frame_count
        if processing_time_seconds is not None:
            payload["processing_time_seconds"] = processing_time_seconds
        if error_message:
            payload["error_message"] = error_message
        if error_code:
            payload["error_code"] = error_code

        url = f"{self.api_server_url}/api/v1/internal/avatar/jobs/{job_id}/callback"

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    logger.info(
                        f"Sending completion callback for job {job_id} "
                        f"(attempt {attempt + 1}/{self._max_retries})"
                    )

                    response = await client.post(
                        url,
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"Completion callback sent for job {job_id}")
                        return CallbackResponse(
                            success=data.get("success", True),
                            message=data.get("message", "Callback processed"),
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"Completion callback failed: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        return CallbackResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"Completion callback returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"Completion callback timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to API server: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"Completion callback failed: {e}", exc_info=True)
                return CallbackResponse(success=False, error=str(e))

        return CallbackResponse(
            success=False,
            error=f"Failed to send completion after {self._max_retries} attempts",
        )

    async def send_video_completion(
        self,
        video_id: UUID,
        s3_key: str,
        duration: float,
        processing_time_seconds: Optional[float] = None,
    ) -> CallbackResponse:
        """
        Send video generation completion callback to API server.

        Args:
            video_id: The video ID
            s3_key: S3 key where video was uploaded
            duration: Video duration in seconds
            processing_time_seconds: Total processing time

        Returns:
            CallbackResponse with success/error status
        """
        if not self.is_configured:
            return CallbackResponse(
                success=False,
                error="API server not configured",
            )

        payload = {
            "status": "completed",
            "s3_key": s3_key,
            "duration": duration,
        }
        if processing_time_seconds is not None:
            payload["processing_time_seconds"] = processing_time_seconds

        url = f"{self.api_server_url}/api/v1/internal/videos/{video_id}/callback"

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    logger.info(
                        f"Sending video completion callback for {video_id} "
                        f"(attempt {attempt + 1}/{self._max_retries})"
                    )

                    response = await client.post(
                        url,
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"Video completion callback sent for {video_id}")
                        return CallbackResponse(
                            success=data.get("success", True),
                            message=data.get("message", "Callback processed"),
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"Video completion callback failed: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        return CallbackResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"Video completion callback returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"Video completion callback timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to API server: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"Video completion callback failed: {e}", exc_info=True)
                return CallbackResponse(success=False, error=str(e))

        return CallbackResponse(
            success=False,
            error=f"Failed to send video completion after {self._max_retries} attempts",
        )

    async def send_video_failure(
        self,
        video_id: UUID,
        error_message: str,
    ) -> CallbackResponse:
        """
        Send video generation failure callback to API server.

        Args:
            video_id: The video ID
            error_message: Error message describing the failure

        Returns:
            CallbackResponse with success/error status
        """
        if not self.is_configured:
            return CallbackResponse(
                success=False,
                error="API server not configured",
            )

        payload = {
            "status": "failed",
            "error_message": error_message,
        }

        url = f"{self.api_server_url}/api/v1/internal/videos/{video_id}/callback"

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                    logger.info(
                        f"Sending video failure callback for {video_id} "
                        f"(attempt {attempt + 1}/{self._max_retries})"
                    )

                    response = await client.post(
                        url,
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"Video failure callback sent for {video_id}")
                        return CallbackResponse(
                            success=data.get("success", True),
                            message=data.get("message", "Callback processed"),
                        )

                    # Non-retryable client errors
                    if 400 <= response.status_code < 500:
                        error_msg = f"Video failure callback failed: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        return CallbackResponse(success=False, error=error_msg)

                    # Server error - retry
                    logger.warning(
                        f"Video failure callback returned {response.status_code}, "
                        f"retrying... ({attempt + 1}/{self._max_retries})"
                    )

            except httpx.TimeoutException:
                logger.warning(
                    f"Video failure callback timed out (attempt {attempt + 1}/{self._max_retries})"
                )
            except httpx.ConnectError as e:
                logger.warning(
                    f"Failed to connect to API server: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries})"
                )
            except Exception as e:
                logger.error(f"Video failure callback failed: {e}", exc_info=True)
                return CallbackResponse(success=False, error=str(e))

        return CallbackResponse(
            success=False,
            error=f"Failed to send video failure after {self._max_retries} attempts",
        )

    async def health_check(self) -> bool:
        """
        Check if the API server is reachable.

        Returns:
            True if API server is healthy, False otherwise
        """
        if not self.api_server_url:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.api_server_url}/health")
                return response.status_code == 200
        except Exception:
            return False


# Singleton instance
api_callback_client = APICallbackClient()
