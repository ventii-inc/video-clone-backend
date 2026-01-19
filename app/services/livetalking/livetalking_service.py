"""LiveTalking service for real-time avatar streaming"""

import logging
import tempfile
from typing import Optional
from io import BytesIO

import httpx

from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.services.s3 import s3_service

logger = logging.getLogger(__name__)


class LiveTalkingService:
    """Service for communicating with LiveTalking server"""

    def __init__(self):
        self._settings = None

    def _get_settings(self) -> LiveTalkingSettings:
        """Get fresh settings from environment."""
        if self._settings is None:
            self._settings = LiveTalkingSettings()
        return self._settings

    @property
    def base_url(self) -> str:
        return self._get_settings().LIVETALKING_URL.rstrip("/")

    @property
    def timeout(self) -> int:
        return self._get_settings().LIVETALKING_TIMEOUT

    @property
    def download_timeout(self) -> int:
        return self._get_settings().LIVETALKING_DOWNLOAD_TIMEOUT

    def _get_headers(self) -> dict:
        """Get headers for LiveTalking requests."""
        headers = {"Content-Type": "application/json"}
        api_key = self._get_settings().LIVETALKING_API_KEY
        if api_key:
            headers["X-API-Key"] = api_key
        return headers

    async def create_session(self) -> dict:
        """
        Create a new WebRTC session with LiveTalking server.

        This initiates the WebRTC offer/answer exchange. The frontend
        will use the returned session info to establish direct WebRTC
        connection with LiveTalking.

        Returns:
            dict with session_id and webrtc_url for frontend connection
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Get the offer endpoint URL - frontend will use this
                webrtc_url = f"{self.base_url}/offer"

                logger.info(f"Created LiveTalking session reference, WebRTC URL: {webrtc_url}")

                return {
                    "webrtc_url": webrtc_url,
                    "human_url": f"{self.base_url}/human",
                    "record_url": f"{self.base_url}/record",
                }

        except httpx.RequestError as e:
            logger.error(f"Failed to connect to LiveTalking server: {e}")
            raise ConnectionError(f"LiveTalking server unavailable: {e}")

    async def send_text(self, session_id: int, text: str, interrupt: bool = True) -> bool:
        """
        Send text to LiveTalking for TTS processing.

        Args:
            session_id: The WebRTC session ID
            text: Text to speak
            interrupt: Whether to interrupt current speech

        Returns:
            True if successful
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/human",
                    headers=self._get_headers(),
                    json={
                        "text": text,
                        "type": "echo",
                        "interrupt": interrupt,
                        "sessionid": session_id,
                    },
                )
                response.raise_for_status()
                logger.info(f"Sent text to LiveTalking session {session_id}: {text[:50]}...")
                return True

        except httpx.RequestError as e:
            logger.error(f"Failed to send text to LiveTalking: {e}")
            raise ConnectionError(f"Failed to send text: {e}")

    async def start_recording(self, session_id: int) -> bool:
        """
        Start recording the LiveTalking session.

        Args:
            session_id: The WebRTC session ID

        Returns:
            True if recording started successfully
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/record",
                    headers=self._get_headers(),
                    json={
                        "type": "start_record",
                        "sessionid": session_id,
                    },
                )
                response.raise_for_status()
                logger.info(f"Started recording for LiveTalking session {session_id}")
                return True

        except httpx.RequestError as e:
            logger.error(f"Failed to start recording: {e}")
            raise ConnectionError(f"Failed to start recording: {e}")

    async def stop_recording(self, session_id: int) -> bool:
        """
        Stop recording the LiveTalking session.

        Args:
            session_id: The WebRTC session ID

        Returns:
            True if recording stopped successfully
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/record",
                    headers=self._get_headers(),
                    json={
                        "type": "end_record",
                        "sessionid": session_id,
                    },
                )
                response.raise_for_status()
                logger.info(f"Stopped recording for LiveTalking session {session_id}")
                return True

        except httpx.RequestError as e:
            logger.error(f"Failed to stop recording: {e}")
            raise ConnectionError(f"Failed to stop recording: {e}")

    async def download_recording(self, filename: str = "record_lasted.mp4") -> Optional[bytes]:
        """
        Download a recording from LiveTalking server.

        Args:
            filename: Name of the recording file

        Returns:
            Recording bytes if successful, None otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=self.download_timeout) as client:
                response = await client.get(
                    f"{self.base_url}/{filename}",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                logger.info(f"Downloaded recording: {filename} ({len(response.content)} bytes)")
                return response.content

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Recording not found: {filename}")
                return None
            logger.error(f"Failed to download recording: {e}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Failed to download recording: {e}")
            raise ConnectionError(f"Failed to download recording: {e}")

    async def download_and_upload_to_s3(
        self,
        user_id: str,
        recording_id: str,
        filename: str = "record_lasted.mp4",
    ) -> Optional[str]:
        """
        Download recording from LiveTalking and upload to S3.

        Args:
            user_id: User ID for S3 path
            recording_id: Unique ID for the recording
            filename: Name of the recording file on LiveTalking

        Returns:
            S3 presigned URL for the recording, or None if failed
        """
        recording_bytes = await self.download_recording(filename)
        if not recording_bytes:
            return None

        # Generate S3 key
        s3_key = s3_service.generate_s3_key(
            user_id=user_id,
            filename=f"{recording_id}.mp4",
            media_type="avatar-recordings",
        )

        # Upload to S3
        file_obj = BytesIO(recording_bytes)
        await s3_service.upload_fileobj(
            file_obj=file_obj,
            s3_key=s3_key,
            content_type="video/mp4",
        )

        # Generate presigned URL
        url = await s3_service.generate_presigned_url(s3_key)
        logger.info(f"Uploaded recording to S3: {s3_key}")
        return url

    async def health_check(self) -> bool:
        """
        Check if LiveTalking server is reachable.

        Returns:
            True if server is healthy
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/")
                return response.status_code == 200
        except Exception:
            return False


# Create singleton instance
livetalking_service = LiveTalkingService()
