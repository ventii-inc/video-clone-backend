"""Video model schemas for CRUD operations"""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.common import UploadInfo, PaginationMeta


ModelStatus = Literal["pending", "uploading", "processing", "completed", "failed"]
ProcessingStage = Literal["pending", "uploading", "preparing", "training", "finalizing", "completed", "failed"]


class VideoModelCreate(BaseModel):
    """Video model creation request"""
    name: str = Field(..., min_length=1, max_length=100)
    file_name: str = Field(..., description="Original file name with extension")
    file_size_bytes: int = Field(..., gt=0, le=524288000, description="Max 500MB")
    content_type: str = Field(..., description="MIME type (video/mp4, etc.)")


class VideoModelUpdate(BaseModel):
    """Video model update request"""
    name: str = Field(..., min_length=1, max_length=100)


class UploadCompleteRequest(BaseModel):
    """Request to mark upload as complete"""
    duration_seconds: int = Field(..., gt=0, description="Video duration in seconds")


class AvatarReadyRequest(BaseModel):
    """Request from avatar backend when TAR file is uploaded"""
    s3_key: str = Field(..., description="S3 key of the uploaded avatar TAR file")


class VideoModelResponse(BaseModel):
    """Video model response"""
    id: UUID
    name: str
    source_video_url: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    file_size_bytes: int | None
    status: ModelStatus
    progress_percent: int = 0
    processing_stage: ProcessingStage = "pending"
    error_message: str | None = None
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VideoModelBrief(BaseModel):
    """Brief video model info for lists and references"""
    id: UUID
    name: str
    thumbnail_url: str | None
    duration_seconds: int | None
    status: ModelStatus
    progress_percent: int = 0
    processing_stage: ProcessingStage = "pending"
    created_at: datetime

    class Config:
        from_attributes = True


class VideoModelCreateResponse(BaseModel):
    """Response when creating a video model"""
    model: VideoModelBrief
    upload: UploadInfo


class VideoModelListResponse(BaseModel):
    """Paginated list of video models"""
    models: list[VideoModelBrief]
    pagination: PaginationMeta


class DirectUploadResponse(BaseModel):
    """Response when uploading video directly to server"""
    model: VideoModelBrief
    job_id: UUID
    message: str
