"""Video processing service"""

from app.services.video.video_service import (
    extract_thumbnail,
    get_video_duration,
    trim_video,
    video_service,
)

__all__ = ["extract_thumbnail", "get_video_duration", "trim_video", "video_service"]
