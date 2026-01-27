"""Video models router for CRUD operations"""

import asyncio
import os
import time
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db import get_db
from app.models import User, VideoModel
from app.models.video_model import ModelStatus, ProcessingStage
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.services.avatar_job import avatar_job_service
from app.services.video import extract_thumbnail, video_service
from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.utils import logger
from app.utils.constants import MAX_VIDEO_MODELS_PER_USER
from app.schemas.common import MessageResponse, PaginationMeta
from app.schemas.video_model import (
    VideoModelResponse,
    VideoModelBrief,
    VideoModelListResponse,
    VideoModelUpdate,
    AvatarReadyRequest,
    DirectUploadResponse,
)

router = APIRouter(prefix="/models/video", tags=["Video Models"])


ALLOWED_VIDEO_TYPES = ["video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"]
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


def map_public_status(status: str) -> str:
    """Map internal status to public API status (processing/completed/failed)."""
    if status in ("pending", "uploading", "processing"):
        return "processing"
    return status  # completed, failed stay the same


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
    total_start = time.perf_counter()
    timings = {}

    # Build query - show all models for the user
    query = select(VideoModel).where(VideoModel.user_id == user.id)

    if status:
        query = query.where(VideoModel.status == status)

    # Get total count - build count query directly with same filters (more efficient)
    t0 = time.perf_counter()
    count_query = select(func.count(VideoModel.id)).where(VideoModel.user_id == user.id)
    if status:
        count_query = count_query.where(VideoModel.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    timings["count_query"] = (time.perf_counter() - t0) * 1000

    # Apply pagination
    query = query.order_by(VideoModel.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)

    t0 = time.perf_counter()
    result = await db.execute(query)
    models = result.scalars().all()
    timings["main_query"] = (time.perf_counter() - t0) * 1000

    # Generate presigned URLs for thumbnails in parallel
    t0 = time.perf_counter()

    # Create briefs first without URLs
    model_briefs = []
    models_with_thumbnails = []
    for i, m in enumerate(models):
        brief = VideoModelBrief.model_validate(m)
        brief.status = map_public_status(m.status)
        model_briefs.append(brief)
        if m.thumbnail_key:
            models_with_thumbnails.append((i, m.thumbnail_key))

    # Generate all presigned URLs in parallel
    if models_with_thumbnails:
        thumbnail_tasks = [
            s3_service.generate_presigned_url(key)
            for _, key in models_with_thumbnails
        ]
        thumbnail_urls = await asyncio.gather(*thumbnail_tasks, return_exceptions=True)

        # Assign URLs back to briefs
        for (idx, _), url in zip(models_with_thumbnails, thumbnail_urls):
            if isinstance(url, str):  # Not an exception
                model_briefs[idx].thumbnail_url = url
            else:
                logger.warning(f"Failed to generate presigned URL: {url}")

    timings["presigned_urls_total"] = (time.perf_counter() - t0) * 1000
    timings["presigned_urls_count"] = len(models_with_thumbnails)

    timings["total"] = (time.perf_counter() - total_start) * 1000

    logger.info(
        f"[PERF] list_video_models: "
        f"count_query={timings['count_query']:.1f}ms, "
        f"main_query={timings['main_query']:.1f}ms, "
        f"presigned_urls_total={timings['presigned_urls_total']:.1f}ms "
        f"(count={timings['presigned_urls_count']}, parallel), "
        f"TOTAL={timings['total']:.1f}ms"
    )

    return VideoModelListResponse(
        models=model_briefs,
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

    response = VideoModelResponse.model_validate(model)
    # Generate thumbnail URL from thumbnail_key if available
    if model.thumbnail_key:
        response.thumbnail_url = await s3_service.generate_presigned_url(model.thumbnail_key)

    return response


@router.post("/upload", response_model=DirectUploadResponse, status_code=status.HTTP_201_CREATED)
async def direct_upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Video file to upload"),
    name: str = Form(..., min_length=1, max_length=100, description="Model name"),
    duration_seconds: int = Form(..., gt=0, description="Video duration in seconds"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload video directly to server and trigger avatar generation.

    Flow:
    1. Validate and save video file locally
    2. Create model record
    3. Trigger parallel background tasks:
       - Upload video to S3
       - Generate avatar (which uploads to S3 when complete)
    """
    # Check model creation limit (bypass if user has flag set)
    if not user.bypass_model_limit:
        count_result = await db.execute(
            select(func.count()).where(VideoModel.user_id == user.id)
        )
        current_count = count_result.scalar()
        if current_count >= MAX_VIDEO_MODELS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum number of video models ({MAX_VIDEO_MODELS_PER_USER}) reached",
            )

    # Validate content type
    if file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(ALLOWED_VIDEO_TYPES)}",
        )

    # Read file to get size and content
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # Create model record with initial progress
    model = VideoModel(
        user_id=user.id,
        name=name,
        file_size_bytes=file_size,
        duration_seconds=duration_seconds,
        status=ModelStatus.UPLOADING.value,
        progress_percent=5,  # 5% - File received, starting processing
        processing_stage=ProcessingStage.UPLOADING.value,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)

    # Save raw file locally (processing happens in background)
    settings = LiveTalkingSettings()
    Path(settings.VIDEO_LOCAL_PATH).mkdir(parents=True, exist_ok=True)

    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    local_path = os.path.join(settings.VIDEO_LOCAL_PATH, f"{model.id}_raw{ext}")

    with open(local_path, "wb") as f:
        f.write(content)

    model.local_video_path = local_path
    logger.info(f"Saved raw video: {local_path}")

    # Generate S3 key for the video
    s3_key = s3_service.generate_s3_key(
        user_id=str(user.id),
        filename=file.filename or f"{model.id}.mp4",
        media_type="training-videos",
        unique_id=str(model.id),
    )
    model.source_video_key = s3_key
    await db.commit()

    # Create avatar generation job
    job = await avatar_job_service.create_job(
        video_model_id=model.id,
        user_id=user.id,
        db=db,
    )
    logger.info(f"Created avatar job {job.id} for video model {model.id}")

    # Background tasks: S3 upload, thumbnail, and trigger avatar processing
    # These run async - if they fail, recovery script will retry stuck uploads
    background_tasks.add_task(
        process_upload_background_tasks,
        model_id=model.id,
        user_id=user.id,
        local_path=local_path,
        s3_key=s3_key,
    )

    return DirectUploadResponse(
        model=VideoModelBrief.model_validate(model),
        job_id=job.id,
        message="Video uploaded, processing started",
    )


async def process_upload_background_tasks(
    model_id: UUID,
    user_id: int,
    local_path: str,
    s3_key: str,
):
    """
    Background task to process video, upload to S3, generate thumbnail, and trigger avatar processing.

    Flow:
    1. Process video (trim 60s, 25fps, remove audio)
    2. In parallel: upload to S3, generate thumbnail, trigger avatar processing
    """
    from app.db import get_db_session

    # Step 1: Process video first (required before S3 upload and avatar training)
    raw_path = local_path  # local_path is the raw file
    processed_path = local_path.replace("_raw", "")  # Remove _raw suffix for processed file

    try:
        _, processed_duration, _ = await video_service.process_training_video(raw_path, processed_path)
        logger.info(f"Processed video: {processed_path} (duration: {processed_duration:.2f}s)")

        # Update model with processed info
        async with get_db_session() as db:
            result = await db.execute(
                select(VideoModel).where(VideoModel.id == model_id)
            )
            model = result.scalar_one_or_none()
            if model:
                model.duration_seconds = int(processed_duration)
                model.file_size_bytes = os.path.getsize(processed_path)
                model.local_video_path = processed_path  # Update to processed path
                await db.commit()

        # Clean up raw file
        if os.path.exists(raw_path):
            os.remove(raw_path)

    except Exception as e:
        logger.error(f"Video processing failed for model {model_id}: {e}")
        # Mark model as failed
        async with get_db_session() as db:
            result = await db.execute(
                select(VideoModel).where(VideoModel.id == model_id)
            )
            model = result.scalar_one_or_none()
            if model:
                model.status = ModelStatus.FAILED.value
                model.error_message = f"Video processing failed: {str(e)}"
                await db.commit()
        return

    # Step 2: Run S3 upload, thumbnail generation, and avatar processing in parallel
    async def upload_to_s3():
        """Upload the processed video file to S3."""
        try:
            success = await s3_service.upload_file(processed_path, s3_key)
            if success:
                logger.info(f"S3 upload complete: {s3_key}")
                async with get_db_session() as db:
                    result = await db.execute(
                        select(VideoModel).where(VideoModel.id == model_id)
                    )
                    model = result.scalar_one_or_none()
                    if model:
                        model.progress_percent = 10  # S3 upload done
                        await db.commit()
            else:
                logger.error(f"S3 upload failed: {s3_key}")
        except Exception as e:
            logger.error(f"S3 upload error for model {model_id}: {e}")

    async def generate_and_upload_thumbnail():
        """Extract thumbnail from processed video and upload to S3."""
        try:
            thumbnail_path = await extract_thumbnail(processed_path, timestamp=1.0)
            if not thumbnail_path:
                logger.warning(f"Failed to extract thumbnail for model {model_id}")
                return

            thumbnail_s3_key = s3_service.generate_s3_key(
                user_id=str(user_id),
                filename=f"{model_id}.jpg",
                media_type="thumbnails",
                unique_id=str(model_id),
            )

            success = await s3_service.upload_file(
                thumbnail_path, thumbnail_s3_key, content_type="image/jpeg"
            )

            if success:
                logger.info(f"Thumbnail uploaded: {thumbnail_s3_key}")
                async with get_db_session() as db:
                    result = await db.execute(
                        select(VideoModel).where(VideoModel.id == model_id)
                    )
                    model = result.scalar_one_or_none()
                    if model:
                        model.thumbnail_key = thumbnail_s3_key
                        await db.commit()
            else:
                logger.error(f"Thumbnail upload failed: {thumbnail_s3_key}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)

        except Exception as e:
            logger.error(f"Thumbnail generation error for model {model_id}: {e}")

    async def trigger_avatar_processing():
        """Trigger avatar generation job processing."""
        try:
            async with get_db_session() as db:
                await avatar_job_service.process_pending_jobs(db)
        except Exception as e:
            logger.error(f"Avatar processing trigger error for model {model_id}: {e}")

    task_names = ["upload_to_s3", "generate_thumbnail", "trigger_avatar_processing"]
    results = await asyncio.gather(
        upload_to_s3(),
        generate_and_upload_thumbnail(),
        trigger_avatar_processing(),
        return_exceptions=True,
    )

    for name, result in zip(task_names, results):
        if isinstance(result, Exception):
            logger.error(f"Background task '{name}' failed for model {model_id}: {result}")


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

    # Update model with avatar data and progress
    model.model_data_key = data.s3_key
    model.status = ModelStatus.COMPLETED.value
    model.progress_percent = 100
    model.processing_stage = ProcessingStage.COMPLETED.value
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

    # Check if model has generated videos (use count query to avoid lazy loading)
    from app.models import GeneratedVideo
    video_count_result = await db.execute(
        select(func.count(GeneratedVideo.id)).where(GeneratedVideo.video_model_id == model_id)
    )
    if video_count_result.scalar() > 0:
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
