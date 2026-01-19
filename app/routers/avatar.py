"""Avatar streaming router for LiveTalking integration"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.services.firebase import get_current_user
from app.services.livetalking import livetalking_service
from app.schemas.avatar import (
    CreateSessionResponse,
    SendTextRequest,
    RecordingControlRequest,
    DownloadRecordingRequest,
    MessageResponse,
    RecordingResponse,
    HealthCheckResponse,
)

router = APIRouter(prefix="/avatar", tags=["Avatar Streaming"])


@router.get("/session", response_model=CreateSessionResponse)
async def create_session(
    user: User = Depends(get_current_user),
):
    """
    Get LiveTalking connection URLs for WebRTC streaming.

    Returns URLs that the frontend will use to establish
    direct WebRTC connection with LiveTalking server.

    The frontend should:
    1. Use webrtc_url to POST WebRTC offer and receive answer
    2. Use human_url to send text for TTS
    3. Use record_url to control recording
    """
    try:
        session_info = await livetalking_service.create_session()
        return CreateSessionResponse(**session_info)
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LiveTalking server unavailable: {str(e)}",
        )


@router.post("/send-text", response_model=MessageResponse)
async def send_text(
    data: SendTextRequest,
    user: User = Depends(get_current_user),
):
    """
    Send text to avatar for TTS processing.

    The avatar will speak the provided text using the configured TTS engine.
    """
    try:
        await livetalking_service.send_text(
            session_id=data.session_id,
            text=data.text,
            interrupt=data.interrupt,
        )
        return MessageResponse(success=True, message="Text sent successfully")
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )


@router.post("/recording", response_model=MessageResponse)
async def control_recording(
    data: RecordingControlRequest,
    user: User = Depends(get_current_user),
):
    """
    Start or stop recording the avatar session.

    Use action='start' to begin recording, 'stop' to end recording.
    """
    try:
        if data.action == "start":
            await livetalking_service.start_recording(data.session_id)
            message = "Recording started"
        else:
            await livetalking_service.stop_recording(data.session_id)
            message = "Recording stopped"

        return MessageResponse(success=True, message=message)
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )


@router.post("/recording/download", response_model=RecordingResponse)
async def download_recording(
    data: DownloadRecordingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the latest recording and save to S3.

    After stopping a recording, use this endpoint to download it
    and store it permanently in S3. Returns a presigned URL for
    immediate playback/download.
    """
    try:
        recording_id = str(uuid.uuid4())

        url = await livetalking_service.download_and_upload_to_s3(
            user_id=str(user.id),
            recording_id=recording_id,
        )

        if not url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No recording found. Make sure you stopped recording before downloading.",
            )

        return RecordingResponse(
            success=True,
            message="Recording downloaded and saved",
            recording_id=recording_id,
            download_url=url,
            s3_key=f"avatar-recordings/{user.id}/{recording_id}.mp4",
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )


@router.get("/health", response_model=HealthCheckResponse)
async def check_livetalking_health():
    """
    Check if LiveTalking server is available.

    This endpoint does not require authentication and can be used
    for monitoring and status checks.
    """
    is_healthy = await livetalking_service.health_check()
    return HealthCheckResponse(
        livetalking_available=is_healthy,
        livetalking_url=livetalking_service.base_url,
    )
