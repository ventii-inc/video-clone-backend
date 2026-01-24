"""Video generation router"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import User, VideoModel, VoiceModel, GeneratedVideo
from app.models.video_model import ModelStatus as VideoModelStatus
from app.models.voice_model import ModelStatus as VoiceModelStatus
from app.models.generated_video import GenerationStatus
from app.services.firebase import get_current_user
from app.services.ai import ai_service
from app.services.s3 import s3_service
from app.services.usage_service import usage_service
from app.schemas.generated_video import (
    GenerateVideoRequest,
    GenerateVideoResponse,
    GeneratedVideoBrief,
    GenerationStatusResponse,
    GenerationStatusDetail,
    UsageInfo,
)

router = APIRouter(prefix="/generate", tags=["Video Generation"])


@router.post("", response_model=GenerateVideoResponse, status_code=status.HTTP_201_CREATED)
async def generate_video(
    data: GenerateVideoRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a new video generation job.

    Validates models, checks credits, creates generation record,
    and starts background processing.
    """
    # Verify video model exists and is ready
    video_model_result = await db.execute(
        select(VideoModel).where(
            VideoModel.id == data.video_model_id,
            VideoModel.user_id == user.id,
        )
    )
    video_model = video_model_result.scalar_one_or_none()

    if not video_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video model not found",
        )

    if video_model.status != VideoModelStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video model is not ready. Current status: {video_model.status}",
        )

    # Verify voice model exists and is ready
    voice_model_result = await db.execute(
        select(VoiceModel).where(
            VoiceModel.id == data.voice_model_id,
            VoiceModel.user_id == user.id,
        )
    )
    voice_model = voice_model_result.scalar_one_or_none()

    if not voice_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice model not found",
        )

    if voice_model.status != VoiceModelStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Voice model is not ready. Current status: {voice_model.status}",
        )

    # Estimate credits needed
    credits_needed = await usage_service.estimate_credits_needed(len(data.input_text))

    # Check if user has sufficient credits
    has_credits = await usage_service.has_sufficient_credits(user.id, credits_needed, db)

    if not has_credits:
        remaining = await usage_service.get_remaining_minutes(user.id, db)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "INSUFFICIENT_CREDITS",
                "message": "Not enough minutes remaining",
                "details": {
                    "required_minutes": credits_needed,
                    "available_minutes": remaining,
                },
            },
        )

    # Get queue position (count of queued videos for this user)
    queue_result = await db.execute(
        select(GeneratedVideo).where(
            GeneratedVideo.status == GenerationStatus.QUEUED.value,
        )
    )
    queue_position = len(queue_result.scalars().all()) + 1

    # Get current usage record for response (no deduction yet - will deduct after generation)
    usage_record = await usage_service.get_or_create_current_usage(user.id, db)

    # Create generated video record (credits_used will be set after generation completes)
    generated_video = GeneratedVideo(
        user_id=user.id,
        video_model_id=data.video_model_id,
        voice_model_id=data.voice_model_id,
        title=data.title,
        input_text=data.input_text,
        input_text_language=data.language,
        resolution=data.resolution,
        credits_used=0,  # Will be updated with actual duration after generation
        status=GenerationStatus.QUEUED.value,
        queue_position=queue_position,
    )
    db.add(generated_video)
    await db.commit()
    await db.refresh(generated_video)

    # Start generation in background
    background_tasks.add_task(
        generate_video_task,
        video_id=generated_video.id,
    )

    # Estimate duration based on text length
    estimated_duration = max(10, len(data.input_text) // 3)

    return GenerateVideoResponse(
        video=GeneratedVideoBrief(
            id=generated_video.id,
            title=generated_video.title,
            status=generated_video.status,
            queue_position=generated_video.queue_position,
            estimated_duration_seconds=estimated_duration,
            credits_used=credits_needed,  # Estimated - actual will be based on output duration
            created_at=generated_video.created_at,
        ),
        usage=UsageInfo(
            minutes_used=usage_record.used_minutes,
            minutes_remaining=usage_record.remaining_minutes,
            minutes_limit=usage_record.total_available_minutes,
        ),
    )


async def generate_video_task(video_id: UUID):
    """Background task to generate video."""
    from app.db import get_db_session

    async with get_db_session() as db:
        await ai_service.generate_video(video_id, db)


@router.get("/{video_id}/status", response_model=GenerationStatusResponse)
async def get_generation_status(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current generation status.

    Used for polling during video generation.
    """
    result = await db.execute(
        select(GeneratedVideo).where(
            GeneratedVideo.id == video_id,
            GeneratedVideo.user_id == user.id,
        )
    )
    video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated video not found",
        )

    # Estimate remaining time if processing
    estimated_remaining = None
    if video.status == GenerationStatus.PROCESSING.value and video.progress_percent:
        # Rough estimate based on progress
        if video.progress_percent > 0:
            elapsed = 10  # Assume ~10 seconds have passed
            estimated_remaining = int(elapsed * (100 - video.progress_percent) / video.progress_percent)

    # Generate presigned URL for completed videos
    output_video_url = None
    if video.status == GenerationStatus.COMPLETED.value and video.output_video_key:
        try:
            output_video_url = await s3_service.generate_presigned_url(video.output_video_key)
        except Exception:
            pass

    return GenerationStatusResponse(
        video=GenerationStatusDetail(
            id=video.id,
            status=video.status,
            processing_stage=video.processing_stage,
            queue_position=video.queue_position,
            progress_percent=video.progress_percent,
            estimated_remaining_seconds=estimated_remaining,
            output_video_url=output_video_url,
            thumbnail_url=video.thumbnail_url,
            duration_seconds=video.duration_seconds,
            file_size_bytes=video.file_size_bytes,
            error_message=video.error_message,
            processing_started_at=video.processing_started_at,
            processing_completed_at=video.processing_completed_at,
        )
    )
