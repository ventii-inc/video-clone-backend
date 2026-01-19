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
