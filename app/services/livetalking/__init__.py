"""LiveTalking service module"""

from app.services.livetalking.livetalking_service import (
    LiveTalkingService,
    livetalking_service,
)
from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.services.livetalking.cli_service import (
    LiveTalkingCLIService,
    livetalking_cli_service,
    AvatarGenerationResult,
    VideoGenerationResult,
)

__all__ = [
    # HTTP API service (for WebRTC streaming)
    "LiveTalkingService",
    "livetalking_service",
    # CLI service (for local avatar/video generation)
    "LiveTalkingCLIService",
    "livetalking_cli_service",
    "AvatarGenerationResult",
    "VideoGenerationResult",
    # Config
    "LiveTalkingSettings",
]
