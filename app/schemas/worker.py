"""Schemas for worker endpoints (RunPod worker mode)"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# Request schemas for submitting jobs to worker
class AvatarJobRequest(BaseModel):
    """Request to execute avatar generation on worker"""

    job_id: UUID = Field(..., description="Unique job identifier from API server")
    video_model_id: UUID = Field(..., description="Video model being processed")
    user_id: int = Field(..., description="Owner of the job")
    video_url: str = Field(..., description="Presigned URL to download source video")
    callback_url: str = Field(..., description="URL to call back with progress/completion")
    options: Optional[dict] = Field(
        default=None,
        description="Optional processing options (max_frames, img_size, model)"
    )


class VideoJobRequest(BaseModel):
    """Request to execute video generation on worker"""

    video_id: UUID = Field(..., description="Generated video ID")
    avatar_id: UUID = Field(..., description="Avatar (video model) to use")
    text: str = Field(..., description="Text to synthesize into speech")
    voice_model_id: Optional[UUID] = Field(
        default=None, description="Voice model for TTS"
    )
    callback_url: str = Field(..., description="URL to call back with completion")
    options: Optional[dict] = Field(
        default=None,
        description="Optional generation options"
    )


# Response schemas from worker endpoints
class WorkerHealthResponse(BaseModel):
    """Health check response from worker"""

    status: str = Field(..., description="Worker status: healthy, degraded, unhealthy")
    mode: str = Field(default="worker", description="Backend mode (always 'worker')")
    gpu_available: bool = Field(..., description="Whether GPU is available")
    gpu_name: Optional[str] = Field(default=None, description="GPU model name if available")
    processing_slots: int = Field(..., description="Number of available processing slots")
    current_jobs: int = Field(..., description="Number of jobs currently processing")


class WorkerCapacityResponse(BaseModel):
    """Capacity information from worker"""

    available_slots: int = Field(..., description="Number of slots available for new jobs")
    max_concurrent: int = Field(..., description="Maximum concurrent jobs allowed")
    current_jobs: int = Field(..., description="Jobs currently being processed")
    queue_depth: int = Field(default=0, description="Jobs waiting in local queue")


class JobSubmitResponse(BaseModel):
    """Response after submitting a job to worker"""

    success: bool = Field(..., description="Whether job was accepted")
    job_id: UUID = Field(..., description="The job ID")
    message: str = Field(..., description="Status message")
    queue_position: Optional[int] = Field(
        default=None, description="Position in queue if not immediately started"
    )


# Callback schemas (worker → API server)
class JobProgressCallback(BaseModel):
    """Progress update sent from worker to API server"""

    stage: str = Field(..., description="Current processing stage")
    progress_percent: int = Field(..., description="Progress percentage (0-100)")
    message: Optional[str] = Field(default=None, description="Optional status message")


class JobCompletionCallback(BaseModel):
    """Completion callback sent from worker to API server"""

    status: str = Field(..., description="Job status: 'completed' or 'failed'")
    s3_key: Optional[str] = Field(
        default=None, description="S3 key where result was uploaded (on success)"
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
