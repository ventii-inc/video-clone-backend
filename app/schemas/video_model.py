"""Video model schemas for CRUD operations"""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.common import PaginationMeta


ModelStatus = Literal["pending", "uploading", "processing", "completed", "failed"]
ProcessingStage = Literal["pending", "uploading", "preparing", "training", "finalizing", "completed", "failed"]


class VideoModelUpdate(BaseModel):
    """Video model update request"""
    name: str = Field(..., min_length=1, max_length=100)


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
    # Progress tracking fields (calculated from elapsed time, see model_progress.py)
    progress_percent: int = 0
    processing_stage: ProcessingStage = "pending"
    estimated_remaining_seconds: int | None = None
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


class VideoModelListResponse(BaseModel):
    """Paginated list of video models"""
    models: list[VideoModelBrief]
    pagination: PaginationMeta


class DirectUploadResponse(BaseModel):
    """Response when uploading video directly to server"""
    model: VideoModelBrief
    job_id: UUID | None = None  # Job created in background after video processing
    message: str


class UploadInitRequest(BaseModel):
    """Request to initialize a direct S3 upload"""
    name: str = Field(..., min_length=1, max_length=100, description="Model name")
    content_type: str = Field(default="video/mp4", description="MIME type of the video file")


class UploadInitResponse(BaseModel):
    """Response with presigned URL for direct S3 upload"""
    model_id: UUID
    upload_url: str
    s3_key: str
    expires_in: int = 300  # seconds


class UploadCompleteRequest(BaseModel):
    """Request to complete a direct S3 upload"""
    model_id: UUID
    duration_seconds: int = Field(..., gt=0, description="Video duration in seconds")
    file_size_bytes: int = Field(..., gt=0, description="File size in bytes")
