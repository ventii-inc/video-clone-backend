"""Schemas for internal avatar backend endpoints"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PendingVideoItem(BaseModel):
    """Individual video pending avatar processing"""

    model_id: UUID = Field(..., description="Unique identifier for the video model")
    user_id: int = Field(..., description="User ID who owns this model")
    s3_key: str = Field(..., description="S3 key for the source training video")
    download_url: str = Field(..., description="Presigned URL to download the video")
    created_at: datetime = Field(..., description="When the video model was created")


class PendingVideosResponse(BaseModel):
    """Response containing list of videos pending avatar processing"""

    videos: List[PendingVideoItem] = Field(
        default_factory=list, description="List of videos pending processing"
    )


class AvatarCompleteRequest(BaseModel):
    """Request to mark avatar processing as complete"""

    s3_key: str = Field(..., description="S3 key where the avatar TAR file was uploaded")
    error_message: Optional[str] = Field(
        default=None, description="Error message if processing failed"
    )


class AvatarCompleteResponse(BaseModel):
    """Response after marking avatar processing complete"""

    success: bool = Field(..., description="Whether the operation was successful")
    model_id: UUID = Field(..., description="The model ID that was updated")
    status: str = Field(..., description="The new status of the model")


class JobCallbackRequest(BaseModel):
    """Request from remote LipSync service when job completes"""

    status: str = Field(..., description="Job status: 'completed' or 'failed'")
    s3_key: Optional[str] = Field(
        default=None, description="S3 key where avatar TAR file was uploaded (on success)"
    )
    frame_count: Optional[int] = Field(
        default=None, description="Number of frames generated"
    )
    processing_time_seconds: Optional[float] = Field(
        default=None, description="Total processing time in seconds"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if job failed"
    )
    error_code: Optional[str] = Field(
        default=None, description="Error code for categorization"
    )


class JobCallbackResponse(BaseModel):
    """Response to job callback"""

    success: bool = Field(..., description="Whether callback was processed successfully")
    message: str = Field(..., description="Status message")


class JobProgressRequest(BaseModel):
    """Request from remote LipSync service for progress updates"""

    stage: str = Field(..., description="Current processing stage")
    progress_percent: Optional[int] = Field(
        default=None, description="Progress percentage (0-100)"
    )
    message: Optional[str] = Field(
        default=None, description="Optional status message"
    )


class JobProgressResponse(BaseModel):
    """Response to progress update"""

    success: bool = Field(..., description="Whether update was processed successfully")


class VideoCallbackRequest(BaseModel):
    """Request from worker service when video generation completes"""

    status: str = Field(..., description="Job status: 'completed' or 'failed'")
    s3_key: Optional[str] = Field(
        default=None, description="S3 key where generated video was uploaded (on success)"
    )
    duration: Optional[float] = Field(
        default=None, description="Video duration in seconds"
    )
    processing_time_seconds: Optional[float] = Field(
        default=None, description="Total processing time in seconds"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if job failed"
    )
