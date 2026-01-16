"""Generated video schemas for video generation and management"""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta
from app.schemas.video_model import VideoModelBrief
from app.schemas.voice_model import VoiceModelBrief


GenerationStatus = Literal["queued", "processing", "completed", "failed"]
Resolution = Literal["720p", "1080p"]
Language = Literal["ja", "en"]


class GenerateVideoRequest(BaseModel):
    """Request to generate a new video"""
    video_model_id: UUID
    voice_model_id: UUID
    title: str | None = Field(None, max_length=200)
    input_text: str = Field(..., min_length=1, max_length=5000)
    language: Language = Field(default="ja")
    resolution: Resolution = Field(default="720p")


class UsageInfo(BaseModel):
    """Usage information after generation"""
    minutes_used: int
    minutes_remaining: int
    minutes_limit: int


class GenerateVideoResponse(BaseModel):
    """Response when starting video generation"""
    video: "GeneratedVideoBrief"
    usage: UsageInfo


class GeneratedVideoBrief(BaseModel):
    """Brief generated video info"""
    id: UUID
    title: str | None
    status: GenerationStatus
    queue_position: int | None
    estimated_duration_seconds: int | None = None
    credits_used: int
    created_at: datetime

    class Config:
        from_attributes = True


class GeneratedVideoResponse(BaseModel):
    """Full generated video response"""
    id: UUID
    title: str | None
    input_text: str
    input_text_language: Language
    output_video_url: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    file_size_bytes: int | None
    resolution: Resolution
    credits_used: int
    status: GenerationStatus
    error_message: str | None = None
    video_model: VideoModelBrief | None
    voice_model: VoiceModelBrief | None
    processing_started_at: datetime | None
    processing_completed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class GeneratedVideoListItem(BaseModel):
    """Generated video item for list view"""
    id: UUID
    title: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    resolution: Resolution
    status: GenerationStatus
    video_model: VideoModelBrief | None
    voice_model: VoiceModelBrief | None
    created_at: datetime

    class Config:
        from_attributes = True


class GeneratedVideoListResponse(BaseModel):
    """Paginated list of generated videos"""
    videos: list[GeneratedVideoListItem]
    pagination: PaginationMeta


class GenerationStatusResponse(BaseModel):
    """Generation status polling response"""
    video: "GenerationStatusDetail"


class GenerationStatusDetail(BaseModel):
    """Detailed generation status"""
    id: UUID
    status: GenerationStatus
    queue_position: int | None = None
    progress_percent: int | None = None
    estimated_remaining_seconds: int | None = None
    output_video_url: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None

    class Config:
        from_attributes = True


class DownloadUrlResponse(BaseModel):
    """Response for video download URL"""
    download_url: str
    file_name: str
    expires_in_seconds: int = 3600


# Update forward references
GenerateVideoResponse.model_rebuild()
GenerationStatusResponse.model_rebuild()
