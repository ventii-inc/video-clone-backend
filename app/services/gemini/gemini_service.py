"""Gemini AI service for video end-frame analysis"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from app.services.gemini.gemini_config import GeminiSettings

logger = logging.getLogger(__name__)


class EndFrameAnalysis(BaseModel):
    """Structured output schema for Gemini end-frame analysis"""

    has_anomaly: bool
    trim_to_seconds: Optional[float] = None
    description: str


@dataclass
class GeminiAnalysisResponse:
    """Response from Gemini end-frame analysis"""

    success: bool
    analysis: Optional[EndFrameAnalysis] = None
    error: Optional[str] = None


ANALYSIS_PROMPT = """Analyze this training video that will be used to create a digital avatar.

Focus on the LAST FEW SECONDS of the video. Detect if there is any anomalous end behavior such as:
- The person reaching toward the camera to stop recording
- The person pressing a button to stop recording
- The person looking away or breaking character at the end
- Sudden movement toward the camera
- The person standing up or leaving frame
- Any other unnatural ending behavior that would look bad in a looped video

If you detect anomalous end behavior, determine the EXACT timestamp (in seconds) where the
good/natural portion of the video ends and the anomalous behavior begins.

Rules:
- If no anomaly is detected, set has_anomaly to false and trim_to_seconds to null
- If anomaly detected, set has_anomaly to true and trim_to_seconds to the timestamp where
  the good part ends (the video will be trimmed to this point)
- trim_to_seconds must be at least 3.0 seconds (we need enough video to work with)
- Be conservative: only flag clear anomalies, not subtle natural movements
- The description should briefly explain what was detected (or that nothing was found)"""


class GeminiService:
    """Service for analyzing videos using Google Gemini AI"""

    def __init__(self):
        self._settings: Optional[GeminiSettings] = None
        self._client = None

    @property
    def settings(self) -> GeminiSettings:
        if self._settings is None:
            self._settings = GeminiSettings()
        return self._settings

    @property
    def client(self):
        if self._client is None:
            from google import genai

            if not self.settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not configured")
            self._client = genai.Client(api_key=self.settings.GEMINI_API_KEY)
        return self._client

    async def analyze_end_frames(self, video_path: str) -> GeminiAnalysisResponse:
        """
        Upload video to Gemini and analyze end frames for anomalous behavior.

        Args:
            video_path: Path to the video file to analyze

        Returns:
            GeminiAnalysisResponse with analysis results or error
        """
        uploaded_file = None

        try:
            # Upload video file (SDK is synchronous, wrap in thread)
            logger.info(f"Uploading video to Gemini for analysis: {video_path}")
            uploaded_file = await asyncio.to_thread(
                self.client.files.upload, file=video_path
            )
            logger.info(
                f"File uploaded: {uploaded_file.name}, state={uploaded_file.state}"
            )

            # Poll until file is ACTIVE
            start_time = time.time()
            timeout = self.settings.GEMINI_FILE_PROCESSING_TIMEOUT
            poll_interval = self.settings.GEMINI_FILE_POLL_INTERVAL

            while uploaded_file.state == "PROCESSING":
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(
                        f"File processing timed out after {timeout}s"
                    )

                logger.debug(
                    f"Waiting for file processing... "
                    f"(elapsed: {elapsed:.0f}s/{timeout}s)"
                )
                await asyncio.sleep(poll_interval)
                uploaded_file = await asyncio.to_thread(
                    self.client.files.get, name=uploaded_file.name
                )

            if uploaded_file.state == "FAILED":
                raise RuntimeError(
                    f"Gemini file processing failed: {uploaded_file.state}"
                )

            logger.info(f"File ready for analysis: {uploaded_file.name}")

            # Generate analysis with structured output
            from google.genai import types

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.settings.GEMINI_MODEL,
                contents=[uploaded_file, ANALYSIS_PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EndFrameAnalysis,
                ),
            )

            # Parse structured response
            analysis = EndFrameAnalysis.model_validate_json(response.text)
            logger.info(
                f"Gemini analysis complete: has_anomaly={analysis.has_anomaly}, "
                f"trim_to={analysis.trim_to_seconds}s, desc={analysis.description}"
            )

            return GeminiAnalysisResponse(success=True, analysis=analysis)

        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            return GeminiAnalysisResponse(success=False, error=str(e))

        finally:
            # Clean up uploaded file
            if uploaded_file and uploaded_file.name:
                try:
                    await asyncio.to_thread(
                        self.client.files.delete, name=uploaded_file.name
                    )
                    logger.info(f"Cleaned up Gemini file: {uploaded_file.name}")
                except Exception as e:
                    logger.warning(
                        f"Failed to clean up Gemini file {uploaded_file.name}: {e}"
                    )


# Global instance
gemini_service = GeminiService()
