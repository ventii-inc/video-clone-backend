"""Pydantic schemas for request/response validation"""

from app.schemas.common import (
    ErrorResponse,
    MessageResponse,
    PaginatedResponse,
    PaginationParams,
)
from app.schemas.user import UserResponse, UserWithDetailsResponse
from app.schemas.profile import (
    ProfileCreate,
    ProfileResponse,
    ProfileUpdate,
)
from app.schemas.video_model import (
    VideoModelCreate,
    VideoModelResponse,
    VideoModelListResponse,
    VideoModelUpdate,
    UploadCompleteRequest,
    UploadInfo,
)
from app.schemas.voice_model import (
    VoiceModelCreate,
    VoiceModelResponse,
    VoiceModelListResponse,
    VoiceModelUpdate,
)
from app.schemas.generated_video import (
    GenerateVideoRequest,
    GeneratedVideoResponse,
    GeneratedVideoListResponse,
    GenerationStatusResponse,
)
from app.schemas.avatar import (
    CreateSessionResponse,
    SendTextRequest,
    RecordingControlRequest,
    DownloadRecordingRequest,
    RecordingResponse,
    HealthCheckResponse,
)
from app.schemas.avatar_backend import (
    PendingVideoItem,
    PendingVideosResponse,
    AvatarCompleteRequest,
    AvatarCompleteResponse,
)
from app.schemas.avatar_job import (
    AvatarJobCreate,
    AvatarJobResponse,
    JobQueueStatusResponse,
    RetryJobResponse,
)

__all__ = [
    # Common
    "ErrorResponse",
    "MessageResponse",
    "PaginatedResponse",
    "PaginationParams",
    # User
    "UserResponse",
    "UserWithDetailsResponse",
    # Profile
    "ProfileCreate",
    "ProfileResponse",
    "ProfileUpdate",
    # Video Model
    "VideoModelCreate",
    "VideoModelResponse",
    "VideoModelListResponse",
    "VideoModelUpdate",
    "UploadCompleteRequest",
    "UploadInfo",
    # Voice Model
    "VoiceModelCreate",
    "VoiceModelResponse",
    "VoiceModelListResponse",
    "VoiceModelUpdate",
    # Generated Video
    "GenerateVideoRequest",
    "GeneratedVideoResponse",
    "GeneratedVideoListResponse",
    "GenerationStatusResponse",
    # Avatar
    "CreateSessionResponse",
    "SendTextRequest",
    "RecordingControlRequest",
    "DownloadRecordingRequest",
    "RecordingResponse",
    "HealthCheckResponse",
    # Avatar Backend (Internal)
    "PendingVideoItem",
    "PendingVideosResponse",
    "AvatarCompleteRequest",
    "AvatarCompleteResponse",
    # Avatar Job
    "AvatarJobCreate",
    "AvatarJobResponse",
    "JobQueueStatusResponse",
    "RetryJobResponse",
]
