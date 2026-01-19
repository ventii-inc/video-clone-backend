"""Schemas for avatar job tracking"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AvatarJobCreate(BaseModel):
    """Schema for creating a new avatar job"""

    video_model_id: UUID = Field(..., description="ID of the video model to process")


class AvatarJobResponse(BaseModel):
    """Response schema for an avatar job"""

    id: UUID
    video_model_id: UUID
    user_id: int
    status: str
    attempts: int
    max_attempts: int
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    runpod_job_id: Optional[str] = None
    avatar_s3_key: Optional[str] = None

    class Config:
        from_attributes = True


class JobQueueStatusResponse(BaseModel):
    """Response schema for job queue status"""

    running: int = Field(..., description="Number of jobs currently processing")
    pending: int = Field(..., description="Number of jobs waiting in queue")
    max_concurrent: int = Field(..., description="Maximum concurrent jobs allowed")
    completed_today: int = Field(
        default=0, description="Number of jobs completed today"
    )
    failed_today: int = Field(default=0, description="Number of jobs failed today")


class RetryJobResponse(BaseModel):
    """Response after retrying a failed job"""

    success: bool
    job_id: UUID
    message: str
    new_status: str
