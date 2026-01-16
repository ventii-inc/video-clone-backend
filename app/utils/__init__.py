"""Utility modules for the video-clone-backend application."""

from app.utils.logger import logger, setup_logger
from app.utils.environment import is_production, is_staging, is_debug, get_environment
from app.utils.sentry_utils import configure_sentry, wrap_with_sentry
from app.utils.response_utils import success, error_response
from app.utils.constants import (
    API_VERSION,
    API_PREFIX,
    MAX_VIDEO_SIZE_MB,
    MAX_AUDIO_SIZE_MB,
    ALLOWED_VIDEO_TYPES,
    ALLOWED_AUDIO_TYPES,
)

__all__ = [
    # Logger
    "logger",
    "setup_logger",
    # Environment
    "is_production",
    "is_staging",
    "is_debug",
    "get_environment",
    # Sentry
    "configure_sentry",
    "wrap_with_sentry",
    # Response
    "success",
    "error_response",
    # Constants
    "API_VERSION",
    "API_PREFIX",
    "MAX_VIDEO_SIZE_MB",
    "MAX_AUDIO_SIZE_MB",
    "ALLOWED_VIDEO_TYPES",
    "ALLOWED_AUDIO_TYPES",
]
