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
]
