"""Gemini AI service configuration"""

import os
from pydantic_settings import BaseSettings


class GeminiSettings(BaseSettings):
    """Settings for Google Gemini AI service"""

    # Gemini API key (required)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Model to use for video analysis
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Timeout for Gemini API requests (seconds)
    GEMINI_TIMEOUT: int = int(os.getenv("GEMINI_TIMEOUT", "60"))

    # Timeout for file upload processing (seconds)
    GEMINI_FILE_PROCESSING_TIMEOUT: int = int(
        os.getenv("GEMINI_FILE_PROCESSING_TIMEOUT", "120")
    )

    # Poll interval when waiting for file to become ACTIVE (seconds)
    GEMINI_FILE_POLL_INTERVAL: int = int(
        os.getenv("GEMINI_FILE_POLL_INTERVAL", "3")
    )

    class Config:
        env_prefix = ""
