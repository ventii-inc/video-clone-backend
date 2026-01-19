"""LiveTalking service configuration"""

import os
from pydantic_settings import BaseSettings


class LiveTalkingSettings(BaseSettings):
    """Settings for LiveTalking server connection"""

    # LiveTalking server URL (e.g., http://localhost:8010 or https://livetalking.example.com)
    LIVETALKING_URL: str = os.getenv("LIVETALKING_URL", "http://localhost:8010")

    # Optional API key for securing communication between backends
    LIVETALKING_API_KEY: str = os.getenv("LIVETALKING_API_KEY", "")

    # Timeout for HTTP requests to LiveTalking (seconds)
    LIVETALKING_TIMEOUT: int = int(os.getenv("LIVETALKING_TIMEOUT", "30"))

    # Timeout for downloading recordings (seconds)
    LIVETALKING_DOWNLOAD_TIMEOUT: int = int(os.getenv("LIVETALKING_DOWNLOAD_TIMEOUT", "120"))

    class Config:
        env_prefix = ""
