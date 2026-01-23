"""Voice model schemas for CRUD operations"""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field

from app.schemas.common import UploadInfo, PaginationMeta


ModelStatus = Literal["pending", "uploading", "processing", "completed", "failed"]
SourceType = Literal["upload", "recording"]
Visibility = Literal["private", "public", "unlist"]


class VoiceModelCreate(BaseModel):
    """Voice model creation request"""
    name: str = Field(..., min_length=1, max_length=100)
    file_name: str = Field(..., description="Original file name with extension")
    file_size_bytes: int = Field(..., gt=0, le=104857600, description="Max 100MB")
    content_type: str = Field(..., description="MIME type (audio/mpeg, etc.)")
    source_type: SourceType = Field(default="upload")


class VoiceModelUpdate(BaseModel):
    """Voice model update request"""
    name: str | None = Field(None, min_length=1, max_length=100)
    visibility: Visibility | None = Field(None, description="Model visibility: private, public, or unlist")


class VoiceModelUploadCompleteRequest(BaseModel):
    """Request to mark upload as complete"""
    duration_seconds: int = Field(..., gt=0, description="Audio duration in seconds")


class VoiceModelResponse(BaseModel):
    """Voice model response"""
    id: UUID
    name: str
    source_audio_url: str | None
    source_type: SourceType
    duration_seconds: int | None
    file_size_bytes: int | None
    status: ModelStatus
    visibility: Visibility = "private"
    error_message: str | None = None
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VoiceModelBrief(BaseModel):
    """Brief voice model info for lists and references"""
    id: UUID
    name: str
    source_type: SourceType
    duration_seconds: int | None
    status: ModelStatus
    visibility: Visibility = "private"
    created_at: datetime

    class Config:
        from_attributes = True


class VoiceModelCreateResponse(BaseModel):
    """Response when creating a voice model"""
    model: VoiceModelBrief
    upload: UploadInfo


class VoiceModelListResponse(BaseModel):
    """Paginated list of voice models"""
    models: list[VoiceModelBrief]
    pagination: PaginationMeta


class DirectVoiceUploadResponse(BaseModel):
    """Response when uploading voice directly to server"""
    model: VoiceModelBrief
    message: str
