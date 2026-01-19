"""Video models router for CRUD operations"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db import get_db
from app.models import User, VideoModel
from app.models.video_model import ModelStatus
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.services.ai import ai_service
from app.schemas.common import MessageResponse, PaginationMeta
from app.schemas.video_model import (
    VideoModelCreate,
    VideoModelResponse,
    VideoModelBrief,
    VideoModelListResponse,
    VideoModelUpdate,
    VideoModelCreateResponse,
    UploadCompleteRequest,
    AvatarReadyRequest,
)
from app.schemas.common import UploadInfo

router = APIRouter(prefix="/models/video", tags=["Video Models"])


ALLOWED_VIDEO_TYPES = ["video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"]
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


@router.get("", response_model=VideoModelListResponse)
async def list_video_models(
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List user's video models with optional status filter.
    """
    # Build query
    query = select(VideoModel).where(VideoModel.user_id == user.id)

    if status:
        query = query.where(VideoModel.status == status)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    query = query.order_by(VideoModel.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    models = result.scalars().all()

    return VideoModelListResponse(
        models=[VideoModelBrief.model_validate(m) for m in models],
        pagination=PaginationMeta(
            page=page,
            limit=limit,
            total=total,
            total_pages=(total + limit - 1) // limit,
        ),
    )


@router.get("/{model_id}", response_model=VideoModelResponse)
async def get_video_model(
    model_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get video model details by ID.
    """
    result = await db.execute(
        select(VideoModel).where(
            VideoModel.id == model_id,
            VideoModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video model not found",
        )

    return VideoModelResponse.model_validate(model)


@router.post("", response_model=VideoModelCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_video_model(
    data: VideoModelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new video model and get presigned upload URL.

    Flow:
    1. Create model record with 'pending' status
    2. Generate presigned URL for S3 upload
    3. Return model info and upload URL
    4. Client uploads directly to S3
    5. Client calls /upload-complete when done
    """
    # Validate content type
    if data.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(ALLOWED_VIDEO_TYPES)}",
        )

    # Validate file size
    if data.file_size_bytes > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Create model record
    model = VideoModel(
        user_id=user.id,
        name=data.name,
        file_size_bytes=data.file_size_bytes,
        status=ModelStatus.PENDING.value,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)

    # Generate S3 key and presigned URL
    s3_key = s3_service.generate_s3_key(
        user_id=str(user.id),
        filename=data.file_name,
        media_type="training-videos",
        unique_id=str(model.id),
    )

    presigned_url = await s3_service.generate_presigned_upload_url(
        s3_key=s3_key,
        content_type=data.content_type,
        expires_in=3600,
    )

    # Store S3 key
    model.source_video_key = s3_key
    await db.commit()

    return VideoModelCreateResponse(
        model=VideoModelBrief.model_validate(model),
        upload=UploadInfo(
            presigned_url=presigned_url,
            s3_key=s3_key,
            expires_in_seconds=3600,
        ),
    )


@router.post("/{model_id}/upload-complete", response_model=dict)
async def complete_upload(
    model_id: UUID,
    data: UploadCompleteRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark upload as complete and trigger AI processing.
    """
    result = await db.execute(
        select(VideoModel).where(
            VideoModel.id == model_id,
            VideoModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video model not found",
        )

    if model.status != ModelStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete upload for model in '{model.status}' status",
        )

    # Verify file exists in S3
    if model.source_video_key:
        exists = await s3_service.file_exists(model.source_video_key)
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload not found. Please upload the file first.",
            )

        # Get presigned URL for viewing
        model.source_video_url = await s3_service.generate_presigned_url(model.source_video_key)

    # Update model
    model.duration_seconds = data.duration_seconds
    model.status = ModelStatus.UPLOADING.value
    await db.commit()

    # Start AI processing in background
    # Note: In production, this should use a proper job queue
    background_tasks.add_task(
        process_video_model_task,
        model_id=model.id,
    )

    return {
        "model": VideoModelBrief.model_validate(model).model_dump(),
        "message": "Video model is now being processed",
    }


async def process_video_model_task(model_id: UUID):
    """Background task to process video model."""
    from app.db import get_db_session

    async with get_db_session() as db:
        await ai_service.process_video_model(model_id, db)


@router.post("/{model_id}/avatar-ready", response_model=dict)
async def avatar_ready(
    model_id: UUID,
    data: AvatarReadyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Callback endpoint for avatar backend to notify when TAR file is uploaded.

    Called by the avatar processing service after it uploads the avatar TAR to S3.
    This marks the video model as completed and ready for video generation.

    Note: This endpoint is intended for internal service-to-service communication.
    Consider adding API key authentication for production use.
    """
    from datetime import datetime

    result = await db.execute(
        select(VideoModel).where(VideoModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video model not found",
        )

    if model.status not in [ModelStatus.PROCESSING.value, ModelStatus.UPLOADING.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot update avatar for model in '{model.status}' status",
        )

    # Verify the TAR file exists in S3
    exists = await s3_service.file_exists(data.s3_key)
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Avatar TAR file not found in S3",
        )

    # Update model with avatar data
    model.model_data_key = data.s3_key
    model.status = ModelStatus.COMPLETED.value
    model.processing_completed_at = datetime.utcnow()
    await db.commit()

    return {
        "message": "Avatar ready, model marked as completed",
        "model_id": str(model.id),
        "model_data_key": model.model_data_key,
        "status": model.status,
    }


@router.patch("/{model_id}", response_model=VideoModelResponse)
async def update_video_model(
    model_id: UUID,
    data: VideoModelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update video model name.
    """
    result = await db.execute(
        select(VideoModel).where(
            VideoModel.id == model_id,
            VideoModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video model not found",
        )

    model.name = data.name
    await db.commit()
    await db.refresh(model)

    return VideoModelResponse.model_validate(model)


@router.delete("/{model_id}", response_model=MessageResponse)
async def delete_video_model(
    model_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a video model.

    Note: Cannot delete if model has associated generated videos.
    """
    result = await db.execute(
        select(VideoModel).where(
            VideoModel.id == model_id,
            VideoModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video model not found",
        )

    # Check if model has generated videos
    if model.generated_videos and len(model.generated_videos) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete model that has generated videos",
        )

    # Delete from S3 if exists
    if model.source_video_key:
        try:
            await s3_service.delete_file(model.source_video_key)
        except Exception:
            pass  # Ignore S3 errors on delete

    await db.delete(model)
    await db.commit()

    return MessageResponse(message="Video model deleted successfully")
