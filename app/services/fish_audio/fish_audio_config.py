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

    class Config:
        env_prefix = ""
