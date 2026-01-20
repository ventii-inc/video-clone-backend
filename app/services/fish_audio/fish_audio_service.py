"""Fish Audio service for voice cloning and text-to-speech"""

import tempfile
from typing import Optional
from dataclasses import dataclass

import httpx

from app.utils import logger
from app.services.fish_audio.fish_audio_config import FishAudioSettings


@dataclass
class VoiceCloneResponse:
    """Response from Fish Audio voice cloning"""

    success: bool
    model_id: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None


@dataclass
class TTSResponse:
    """Response from Fish Audio text-to-speech"""

    success: bool
    audio_path: Optional[str] = None
    error: Optional[str] = None


class FishAudioService:
    """Service for interacting with Fish Audio API for voice cloning and TTS"""

    def __init__(self):
        self._settings: Optional[FishAudioSettings] = None

    @property
    def settings(self) -> FishAudioSettings:
        if self._settings is None:
            self._settings = FishAudioSettings()
        return self._settings

    @property
    def api_key(self) -> str:
        return self.settings.FISH_AUDIO_API_KEY

    @property
    def base_url(self) -> str:
        return self.settings.FISH_AUDIO_BASE_URL

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def is_configured(self) -> bool:
        """Check if Fish Audio is properly configured"""
        return bool(self.api_key)

    async def clone_voice(
        self,
        audio_data: bytes,
        title: str,
        description: Optional[str] = None,
        transcript: Optional[str] = None,
        enhance_quality: Optional[bool] = None,
        visibility: Optional[str] = None,
    ) -> VoiceCloneResponse:
        """
        Clone a voice from audio data.

        Args:
            audio_data: Raw audio bytes (WAV, MP3, M4A)
            title: Name for the voice model
            description: Optional description
            transcript: Optional transcript of what's spoken in the audio
            enhance_quality: Whether to enhance audio quality (default from settings)
            visibility: Model visibility ("private", "public", "unlist")

        Returns:
            VoiceCloneResponse with model_id on success
        """
        if not self.is_configured():
            logger.error("Fish Audio API key not configured")
            return VoiceCloneResponse(
                success=False, error="Fish Audio API key not configured"
            )

        if enhance_quality is None:
            enhance_quality = self.settings.FISH_AUDIO_ENHANCE_QUALITY
        if visibility is None:
            visibility = self.settings.FISH_AUDIO_DEFAULT_VISIBILITY

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.FISH_AUDIO_TIMEOUT
            ) as client:
                # Prepare multipart form data
                files = {"voices": ("audio.wav", audio_data, "audio/wav")}

                data = {
                    "title": title,
                    "visibility": visibility,
                    "enhance_audio_quality": str(enhance_quality).lower(),
                }

                if description:
                    data["description"] = description

                if transcript:
                    data["texts"] = transcript

                logger.info(f"Creating voice clone with Fish Audio: {title}")

                response = await client.post(
                    f"{self.base_url}/model",
                    headers=self._get_headers(),
                    data=data,
                    files=files,
                )

                if response.status_code not in (200, 201):
                    error_msg = f"Fish Audio API error: {response.status_code}"
                    try:
                        error_data = response.json()
                        if "detail" in error_data:
                            error_msg = f"{error_msg} - {error_data['detail']}"
                        elif "message" in error_data:
                            error_msg = f"{error_msg} - {error_data['message']}"
                    except Exception:
                        error_msg = f"{error_msg} - {response.text[:200]}"
                    logger.error(error_msg)
                    return VoiceCloneResponse(success=False, error=error_msg)

                result = response.json()
                model_id = result.get("_id") or result.get("id")

                logger.info(f"Voice clone created successfully: {model_id}")

                return VoiceCloneResponse(
                    success=True,
                    model_id=model_id,
                    title=result.get("title", title),
                )

        except httpx.TimeoutException:
            error_msg = "Fish Audio request timed out"
            logger.error(error_msg)
            return VoiceCloneResponse(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Fish Audio request failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return VoiceCloneResponse(success=False, error=error_msg)

    async def clone_voice_from_url(
        self,
        audio_url: str,
        title: str,
        description: Optional[str] = None,
        transcript: Optional[str] = None,
        enhance_quality: Optional[bool] = None,
        visibility: Optional[str] = None,
    ) -> VoiceCloneResponse:
        """
        Clone a voice by downloading audio from a URL first.

        Args:
            audio_url: URL to download audio from (e.g., presigned S3 URL)
            title: Name for the voice model
            description: Optional description
            transcript: Optional transcript of what's spoken
            enhance_quality: Whether to enhance audio quality
            visibility: Model visibility

        Returns:
            VoiceCloneResponse with model_id on success
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                logger.info(f"Downloading audio from URL for voice cloning")
                response = await client.get(audio_url)

                if response.status_code != 200:
                    return VoiceCloneResponse(
                        success=False,
                        error=f"Failed to download audio: {response.status_code}",
                    )

                audio_data = response.content

        except Exception as e:
            return VoiceCloneResponse(
                success=False, error=f"Failed to download audio: {str(e)}"
            )

        return await self.clone_voice(
            audio_data=audio_data,
            title=title,
            description=description,
            transcript=transcript,
            enhance_quality=enhance_quality,
            visibility=visibility,
        )

    async def text_to_speech(
        self,
        text: str,
        reference_id: str,
        output_path: Optional[str] = None,
        format: str = "mp3",
    ) -> TTSResponse:
        """
        Generate speech from text using a cloned voice.

        Args:
            text: Text to convert to speech
            reference_id: Fish Audio model ID to use for voice
            output_path: Optional path to save audio file
            format: Output format (mp3, wav)

        Returns:
            TTSResponse with audio_path on success
        """
        if not self.is_configured():
            logger.error("Fish Audio API key not configured")
            return TTSResponse(success=False, error="Fish Audio API key not configured")

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.FISH_AUDIO_TIMEOUT
            ) as client:
                headers = self._get_headers()
                headers["Content-Type"] = "application/json"

                payload = {
                    "text": text,
                    "reference_id": reference_id,
                    "format": format,
                }

                logger.info(
                    f"Generating TTS with Fish Audio, "
                    f"reference_id={reference_id}, text_length={len(text)}"
                )

                response = await client.post(
                    f"{self.base_url}/v1/tts",
                    headers=headers,
                    json=payload,
                )

                if response.status_code != 200:
                    error_msg = f"Fish Audio TTS error: {response.status_code}"
                    try:
                        error_data = response.json()
                        if "detail" in error_data:
                            error_msg = f"{error_msg} - {error_data['detail']}"
                    except Exception:
                        pass
                    logger.error(error_msg)
                    return TTSResponse(success=False, error=error_msg)

                # Save audio to file
                if output_path is None:
                    output_path = tempfile.mktemp(suffix=f".{format}")

                with open(output_path, "wb") as f:
                    f.write(response.content)

                logger.info(f"TTS audio saved to: {output_path}")

                return TTSResponse(success=True, audio_path=output_path)

        except httpx.TimeoutException:
            error_msg = "Fish Audio TTS request timed out"
            logger.error(error_msg)
            return TTSResponse(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Fish Audio TTS request failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return TTSResponse(success=False, error=error_msg)

    async def get_model(self, model_id: str) -> Optional[dict]:
        """
        Get details of a voice model.

        Args:
            model_id: Fish Audio model ID

        Returns:
            Model details dict or None if not found
        """
        if not self.is_configured():
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/model/{model_id}",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    return response.json()
                return None

        except Exception as e:
            logger.error(f"Failed to get Fish Audio model: {e}")
            return None

    async def delete_model(self, model_id: str) -> bool:
        """
        Delete a voice model.

        Args:
            model_id: Fish Audio model ID

        Returns:
            True if deleted successfully
        """
        if not self.is_configured():
            return False

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{self.base_url}/model/{model_id}",
                    headers=self._get_headers(),
                )
                return response.status_code in (200, 204)

        except Exception as e:
            logger.error(f"Failed to delete Fish Audio model: {e}")
            return False


# Singleton instance
fish_audio_service = FishAudioService()
