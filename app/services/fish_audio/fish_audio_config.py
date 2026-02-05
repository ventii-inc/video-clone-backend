"""Fish Audio service configuration"""

import os
from pydantic_settings import BaseSettings


class FishAudioSettings(BaseSettings):
    """Settings for Fish Audio voice cloning service"""

    # Fish Audio API key
    FISH_AUDIO_API_KEY: str = os.getenv("FISH_AUDIO_API_KEY", "")

    # Base URL for Fish Audio API
    FISH_AUDIO_BASE_URL: str = os.getenv(
        "FISH_AUDIO_BASE_URL", "https://api.fish.audio"
    )

    # Timeout for API requests (seconds)
    FISH_AUDIO_TIMEOUT: int = int(os.getenv("FISH_AUDIO_TIMEOUT", "120"))

    # Default visibility for created voice models
    FISH_AUDIO_DEFAULT_VISIBILITY: str = os.getenv(
        "FISH_AUDIO_DEFAULT_VISIBILITY", "private"
    )

    # Whether to enhance audio quality during voice cloning
    FISH_AUDIO_ENHANCE_QUALITY: bool = (
        os.getenv("FISH_AUDIO_ENHANCE_QUALITY", "true").lower() == "true"
    )

    # TTS generation parameters (low values = more deterministic, less repetition)
    FISH_AUDIO_TEMPERATURE: float = float(os.getenv("FISH_AUDIO_TEMPERATURE", "0.01"))
    FISH_AUDIO_TOP_P: float = float(os.getenv("FISH_AUDIO_TOP_P", "0.01"))
    FISH_AUDIO_CHUNK_LENGTH: int = int(os.getenv("FISH_AUDIO_CHUNK_LENGTH", "200"))
    FISH_AUDIO_SPEED: float = float(os.getenv("FISH_AUDIO_SPEED", "1.0"))
    FISH_AUDIO_VOLUME: float = float(os.getenv("FISH_AUDIO_VOLUME", "0.0"))
    FISH_AUDIO_NORMALIZE: bool = (
        os.getenv("FISH_AUDIO_NORMALIZE", "true").lower() == "true"
    )
    FISH_AUDIO_LATENCY: str = os.getenv("FISH_AUDIO_LATENCY", "normal")

    class Config:
        env_prefix = ""
