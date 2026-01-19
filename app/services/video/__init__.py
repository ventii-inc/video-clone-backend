"""Video processing service"""

from app.services.video.video_service import (
    get_video_duration,
    trim_video,
    video_service,
)

__all__ = ["get_video_duration", "trim_video", "video_service"]
