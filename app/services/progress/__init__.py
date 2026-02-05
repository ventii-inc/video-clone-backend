"""Progress tracking service for video model processing."""

from app.services.progress.progress_service import (
    VideoModelProgressTracker,
    update_video_model_progress,
    calculate_training_progress,
    calculate_expected_generation_time,
)
from app.services.progress.model_progress import (
    calculate_video_model_progress,
    calculate_voice_model_progress,
    VIDEO_MODEL_ESTIMATED_DURATION,
    VOICE_MODEL_ESTIMATED_DURATION,
)

__all__ = [
    "VideoModelProgressTracker",
    "update_video_model_progress",
    "calculate_training_progress",
    "calculate_expected_generation_time",
    "calculate_video_model_progress",
    "calculate_voice_model_progress",
    "VIDEO_MODEL_ESTIMATED_DURATION",
    "VOICE_MODEL_ESTIMATED_DURATION",
]
