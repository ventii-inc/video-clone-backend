"""Generated videos router for managing generated videos"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import User, GeneratedVideo, VideoModel, VoiceModel
from app.models.generated_video import GenerationStatus
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.services.ai import ai_service
from app.services.usage_service import usage_service
from app.schemas.common import MessageResponse, PaginationMeta
from app.schemas.generated_video import (
    GeneratedVideoResponse,
    GeneratedVideoListItem,
    GeneratedVideoListResponse,
    DownloadUrlResponse,
    GenerateVideoRequest,
    GenerateVideoResponse,
    GeneratedVideoBrief,
    UsageInfo,
)
from app.schemas.video_model import VideoModelBrief
from app.schemas.voice_model import VoiceModelBrief

router = APIRouter(prefix="/videos", tags=["Generated Videos"])


@router.get("", response_model=GeneratedVideoListResponse)
async def list_videos(
    status_filter: str | None = None,
    video_model_id: UUID | None = None,
    voice_model_id: UUID | None = None,
    sort: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List user's generated videos with optional filters.
    """
    query = select(GeneratedVideo).where(GeneratedVideo.user_id == user.id)

    # Apply filters
    if status_filter:
        query = query.where(GeneratedVideo.status == status_filter)

    if video_model_id:
        query = query.where(GeneratedVideo.video_model_id == video_model_id)

    if voice_model_id:
        query = query.where(GeneratedVideo.voice_model_id == voice_model_id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply sorting
    sort_column = getattr(GeneratedVideo, sort, GeneratedVideo.created_at)
    if order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    # Apply pagination and eager load relationships
    query = query.options(
        selectinload(GeneratedVideo.video_model),
        selectinload(GeneratedVideo.voice_model),
    )
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    videos = result.scalars().all()

    # Build response
    items = []
    for video in videos:
        items.append(
            GeneratedVideoListItem(
                id=video.id,
                title=video.title,
                thumbnail_url=video.thumbnail_url,
                duration_seconds=video.duration_seconds,
                resolution=video.resolution,
                status=video.status,
                video_model=VideoModelBrief.model_validate(video.video_model) if video.video_model else None,
                voice_model=VoiceModelBrief.model_validate(video.voice_model) if video.voice_model else None,
                created_at=video.created_at,
            )
        )

    return GeneratedVideoListResponse(
        videos=items,
        pagination=PaginationMeta(
            page=page,
            limit=limit,
            total=total,
            total_pages=(total + limit - 1) // limit if total > 0 else 0,
        ),
    )


@router.get("/{video_id}", response_model=GeneratedVideoResponse)
async def get_video(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get generated video details by ID.
    """
    result = await db.execute(
        select(GeneratedVideo)
        .where(
            GeneratedVideo.id == video_id,
            GeneratedVideo.user_id == user.id,
        )
        .options(
            selectinload(GeneratedVideo.video_model),
            selectinload(GeneratedVideo.voice_model),
        )
    )
    video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated video not found",
        )

    return GeneratedVideoResponse(
        id=video.id,
        title=video.title,
        input_text=video.input_text,
        input_text_language=video.input_text_language,
        output_video_url=video.output_video_url,
        thumbnail_url=video.thumbnail_url,
        duration_seconds=video.duration_seconds,
        file_size_bytes=video.file_size_bytes,
        resolution=video.resolution,
        credits_used=video.credits_used,
        status=video.status,
        error_message=video.error_message,
        video_model=VideoModelBrief.model_validate(video.video_model) if video.video_model else None,
        voice_model=VoiceModelBrief.model_validate(video.voice_model) if video.voice_model else None,
        processing_started_at=video.processing_started_at,
        processing_completed_at=video.processing_completed_at,
        created_at=video.created_at,
    )


@router.get("/{video_id}/download", response_model=DownloadUrlResponse)
async def get_download_url(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a fresh presigned URL for downloading the video.
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

    if video.status != GenerationStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video is not ready for download",
        )

    if not video.output_video_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found",
        )

    # Generate fresh presigned URL
    download_url = await s3_service.generate_presigned_url(
        video.output_video_key,
        expires_in=3600,
    )

    # Generate filename
    title_slug = (video.title or "video").lower().replace(" ", "-")[:50]
    filename = f"{title_slug}-{str(video.id)[:8]}.mp4"

    return DownloadUrlResponse(
        download_url=download_url,
        file_name=filename,
        expires_in_seconds=3600,
    )


@router.delete("/{video_id}", response_model=MessageResponse)
async def delete_video(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a generated video.
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

    # Delete from S3 if exists
    if video.output_video_key:
        try:
            await s3_service.delete_file(video.output_video_key)
        except Exception:
            pass  # Ignore S3 errors on delete

    await db.delete(video)
    await db.commit()

    return MessageResponse(message="Video deleted successfully")


@router.post("/{video_id}/regenerate", response_model=GenerateVideoResponse, status_code=status.HTTP_201_CREATED)
async def regenerate_video(
    video_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Regenerate a video with the same settings.
    """
    result = await db.execute(
        select(GeneratedVideo).where(
            GeneratedVideo.id == video_id,
            GeneratedVideo.user_id == user.id,
        )
    )
    original = result.scalar_one_or_none()

    if not original:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated video not found",
        )

    # Estimate credits needed
    credits_needed = await usage_service.estimate_credits_needed(len(original.input_text))

    # Check credits
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

    # Create new video record
    new_video = GeneratedVideo(
        user_id=user.id,
        video_model_id=original.video_model_id,
        voice_model_id=original.voice_model_id,
        title=original.title,
        input_text=original.input_text,
        input_text_language=original.input_text_language,
        resolution=original.resolution,
        credits_used=credits_needed,
        status=GenerationStatus.QUEUED.value,
        queue_position=1,
    )
    db.add(new_video)
    await db.commit()
    await db.refresh(new_video)

    # Deduct credits
    usage_record = await usage_service.deduct_credits(user.id, credits_needed, db)

    # Start generation
    background_tasks.add_task(
        generate_video_task,
        video_id=new_video.id,
    )

    return GenerateVideoResponse(
        video=GeneratedVideoBrief(
            id=new_video.id,
            title=new_video.title,
            status=new_video.status,
            queue_position=new_video.queue_position,
            credits_used=new_video.credits_used,
            created_at=new_video.created_at,
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
