"""RunPod serverless client for avatar generation"""

import os
from typing import Optional

import httpx

from app.utils import logger


class RunPodResponse:
    """Response from RunPod avatar generation"""

    def __init__(
        self,
        success: bool,
        avatar_id: Optional[str] = None,
        upload_url: Optional[str] = None,
        error: Optional[str] = None,
        job_id: Optional[str] = None,
        num_frames: Optional[int] = None,
    ):
        self.success = success
        self.avatar_id = avatar_id
        self.upload_url = upload_url
        self.error = error
        self.job_id = job_id
        self.num_frames = num_frames


class RunPodClient:
    """Client for communicating with RunPod serverless avatar generation"""

    def __init__(self):
        self._api_key: Optional[str] = None
        self._endpoint_id: Optional[str] = None

    @property
    def api_key(self) -> str:
        if self._api_key is None:
            self._api_key = os.getenv("RUNPOD_API_KEY", "")
        return self._api_key

    @property
    def endpoint_id(self) -> str:
        if self._endpoint_id is None:
            self._endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID", "")
        return self._endpoint_id

    @property
    def base_url(self) -> str:
        return f"https://api.runpod.ai/v2/{self.endpoint_id}"

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate_avatar(
        self,
        video_url: str,
        avatar_id: str,
        model: str = "wav2lip",
        s3_bucket: Optional[str] = None,
        s3_prefix: str = "avatars",
        options: Optional[dict] = None,
    ) -> RunPodResponse:
        """
        Trigger avatar generation on RunPod serverless.

        Args:
            video_url: Presigned S3 URL to download the source video
            avatar_id: Unique identifier for the avatar (usually model_id)
            model: Model to use ("wav2lip" or "musetalk")
            s3_bucket: S3 bucket for output (if not provided, returns base64)
            s3_prefix: S3 prefix for output path
            options: Additional model-specific options

        Returns:
            RunPodResponse with success status and result data
        """
        if not self.api_key or not self.endpoint_id:
            logger.error("RunPod credentials not configured")
            return RunPodResponse(
                success=False, error="RunPod credentials not configured"
            )

        payload = {
            "input": {
                "video_url": video_url,
                "avatar_id": avatar_id,
                "model": model,
            }
        }

        if s3_bucket:
            payload["input"]["s3_bucket"] = s3_bucket
            payload["input"]["s3_prefix"] = s3_prefix

        if options:
            payload["input"]["options"] = options

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                logger.info(
                    f"Triggering RunPod avatar generation for {avatar_id}, "
                    f"model={model}"
                )

                # Use runsync for synchronous execution
                response = await client.post(
                    f"{self.base_url}/runsync",
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code != 200:
                    error_msg = f"RunPod API error: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return RunPodResponse(success=False, error=error_msg)

                data = response.json()

                # Check for RunPod-level errors
                if data.get("status") == "FAILED":
                    error_msg = data.get("error", "Unknown RunPod error")
                    logger.error(f"RunPod job failed: {error_msg}")
                    return RunPodResponse(
                        success=False, error=error_msg, job_id=data.get("id")
                    )

                # Extract output from successful response
                output = data.get("output", {})

                if output.get("status") == "error":
                    error_msg = output.get("error", "Avatar generation failed")
                    logger.error(f"Avatar generation error: {error_msg}")
                    return RunPodResponse(
                        success=False, error=error_msg, job_id=data.get("id")
                    )

                logger.info(
                    f"Avatar generation successful for {avatar_id}, "
                    f"frames={output.get('num_frames')}"
                )

                return RunPodResponse(
                    success=True,
                    avatar_id=output.get("avatar_id"),
                    upload_url=output.get("upload_url"),
                    job_id=data.get("id"),
                    num_frames=output.get("num_frames"),
                )

        except httpx.TimeoutException:
            error_msg = "RunPod request timed out"
            logger.error(error_msg)
            return RunPodResponse(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"RunPod request failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return RunPodResponse(success=False, error=error_msg)

    async def check_job_status(self, job_id: str) -> RunPodResponse:
        """
        Check the status of a RunPod job (for async jobs).

        Args:
            job_id: The RunPod job ID to check

        Returns:
            RunPodResponse with current status
        """
        if not self.api_key or not self.endpoint_id:
            return RunPodResponse(
                success=False, error="RunPod credentials not configured"
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/status/{job_id}",
                    headers=self._get_headers(),
                )

                if response.status_code != 200:
                    return RunPodResponse(
                        success=False,
                        error=f"Status check failed: {response.status_code}",
                    )

                data = response.json()
                status = data.get("status")

                if status == "COMPLETED":
                    output = data.get("output", {})
                    return RunPodResponse(
                        success=True,
                        avatar_id=output.get("avatar_id"),
                        upload_url=output.get("upload_url"),
                        job_id=job_id,
                        num_frames=output.get("num_frames"),
                    )
                elif status == "FAILED":
                    return RunPodResponse(
                        success=False,
                        error=data.get("error", "Job failed"),
                        job_id=job_id,
                    )
                else:
                    # Still processing
                    return RunPodResponse(
                        success=False,
                        error=f"Job still {status}",
                        job_id=job_id,
                    )

        except Exception as e:
            return RunPodResponse(success=False, error=str(e))


# Singleton instance
runpod_client = RunPodClient()
