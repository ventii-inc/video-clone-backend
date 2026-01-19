"""Avatar streaming schemas"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# Request schemas
class CreateSessionResponse(BaseModel):
    """Response for creating a new avatar streaming session"""

    webrtc_url: str = Field(..., description="URL for WebRTC offer endpoint")
    human_url: str = Field(..., description="URL for sending text to avatar")
    record_url: str = Field(..., description="URL for recording control")


class SendTextRequest(BaseModel):
    """Request to send text to avatar for TTS"""

    session_id: int = Field(..., description="WebRTC session ID")
    text: str = Field(..., min_length=1, max_length=5000, description="Text to speak")
    interrupt: bool = Field(default=True, description="Interrupt current speech")


class RecordingControlRequest(BaseModel):
    """Request to control recording"""

    session_id: int = Field(..., description="WebRTC session ID")
    action: str = Field(..., pattern="^(start|stop)$", description="Recording action: start or stop")


class DownloadRecordingRequest(BaseModel):
    """Request to download and save recording to S3"""

    session_id: int = Field(..., description="WebRTC session ID")
    title: Optional[str] = Field(default=None, max_length=255, description="Title for the recording")


# Response schemas
class MessageResponse(BaseModel):
    """Simple message response"""

    success: bool
    message: str


class RecordingResponse(BaseModel):
    """Response with recording information"""

    success: bool
    message: str
    recording_id: Optional[str] = None
    download_url: Optional[str] = None
    s3_key: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """Health check response for LiveTalking service"""

    livetalking_available: bool
    livetalking_url: str
