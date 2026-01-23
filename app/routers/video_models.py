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
from app.services.ai import ai_service
from app.services.avatar_job import avatar_job_service
from app.services.video import extract_thumbnail
from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.utils import logger
from app.utils.constants import MAX_VIDEO_MODELS_PER_USER
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
    DirectUploadResponse,
)
from app.schemas.common import UploadInfo

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

    # Get total count
    t0 = time.perf_counter()
    count_query = select(func.count()).select_from(query.subquery())
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

    # Generate presigned URLs for thumbnails
    t0 = time.perf_counter()
    model_briefs = []
    thumbnail_timings = []
    for m in models:
        brief = VideoModelBrief.model_validate(m)
        # Map internal status to public status (pending/uploading → processing)
        brief.status = map_public_status(m.status)
        # Generate thumbnail URL from thumbnail_key if available
        if m.thumbnail_key:
            t_thumb = time.perf_counter()
            brief.thumbnail_url = await s3_service.generate_presigned_url(m.thumbnail_key)
            thumbnail_timings.append((time.perf_counter() - t_thumb) * 1000)
        model_briefs.append(brief)
    timings["presigned_urls_total"] = (time.perf_counter() - t0) * 1000
    timings["presigned_urls_individual"] = thumbnail_timings

    timings["total"] = (time.perf_counter() - total_start) * 1000

    logger.info(
        f"[PERF] list_video_models: "
        f"count_query={timings['count_query']:.1f}ms, "
        f"main_query={timings['main_query']:.1f}ms, "
        f"presigned_urls_total={timings['presigned_urls_total']:.1f}ms "
        f"(count={len(thumbnail_timings)}, each={thumbnail_timings if thumbnail_timings else 'N/A'}), "
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
        expiration=3600,
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

    # Save file locally
    settings = LiveTalkingSettings()
    Path(settings.VIDEO_LOCAL_PATH).mkdir(parents=True, exist_ok=True)

    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    local_path = os.path.join(settings.VIDEO_LOCAL_PATH, f"{model.id}{ext}")

    with open(local_path, "wb") as f:
        f.write(content)

    model.local_video_path = local_path
    logger.info(f"Saved video locally: {local_path}")

    # Generate S3 key for the video
    s3_key = s3_service.generate_s3_key(
        user_id=str(user.id),
        filename=file.filename or f"{model.id}.mp4",
        media_type="training-videos",
        unique_id=str(model.id),
    )
    model.source_video_key = s3_key
    await db.commit()

    # Upload to S3 synchronously (ensures it completes before returning)
    logger.info(f"Uploading video to S3: {s3_key}")
    s3_success = await s3_service.upload_file(local_path, s3_key)
    if not s3_success:
        # Clean up and fail
        model.status = ModelStatus.FAILED.value
        model.processing_stage = ProcessingStage.FAILED.value
        model.error_message = "Failed to upload video to S3"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload video to S3",
        )

    logger.info(f"S3 upload complete: {s3_key}")
    model.progress_percent = 10  # 10% - S3 upload complete
    await db.commit()

    # Create avatar generation job
    job = await avatar_job_service.create_job(
        video_model_id=model.id,
        user_id=user.id,
        db=db,
    )
    logger.info(f"Created avatar job {job.id} for video model {model.id}")

    # Background tasks for non-critical work (thumbnail) and triggering job processing
    background_tasks.add_task(
        process_upload_background_tasks,
        model_id=model.id,
        user_id=user.id,
        local_path=local_path,
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
):
    """
    Background task for non-critical post-upload work.

    S3 upload is now done synchronously before returning.
    This handles thumbnail generation and triggers avatar processing.
    These are non-critical - if they fail, they can be retried.
    """
    from app.db import get_db_session

    async def generate_and_upload_thumbnail():
        """Extract thumbnail from video and upload to S3."""
        try:
            # Extract thumbnail from video
            thumbnail_path = await extract_thumbnail(local_path, timestamp=1.0)
            if not thumbnail_path:
                logger.warning(f"Failed to extract thumbnail for model {model_id}")
                return

            # Generate S3 key for thumbnail
            thumbnail_s3_key = s3_service.generate_s3_key(
                user_id=str(user_id),
                filename=f"{model_id}.jpg",
                media_type="thumbnails",
                unique_id=str(model_id),
            )

            # Upload thumbnail to S3
            success = await s3_service.upload_file(
                thumbnail_path, thumbnail_s3_key, content_type="image/jpeg"
            )

            if success:
                logger.info(f"Thumbnail uploaded: {thumbnail_s3_key}")
                # Update model with thumbnail key
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

            # Clean up temp thumbnail file
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

    # Run thumbnail generation and avatar processing in parallel
    task_names = ["generate_thumbnail", "trigger_avatar_processing"]
    results = await asyncio.gather(
        generate_and_upload_thumbnail(),
        trigger_avatar_processing(),
        return_exceptions=True,
    )

    # Log any exceptions from background tasks
    for name, result in zip(task_names, results):
        if isinstance(result, Exception):
            logger.error(f"Background task '{name}' failed for model {model_id}: {result}")


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

        # Save local copy for CLI processing
        settings = LiveTalkingSettings()
        if settings.LIVETALKING_MODE == "cli":
            try:
                # Ensure local video directory exists
                Path(settings.VIDEO_LOCAL_PATH).mkdir(parents=True, exist_ok=True)

                # Get file extension from S3 key
                ext = os.path.splitext(model.source_video_key)[1] or ".mp4"
                local_path = os.path.join(settings.VIDEO_LOCAL_PATH, f"{model.id}{ext}")

                # Download from S3 to local
                logger.info(f"Downloading video to local: {local_path}")
                success = await s3_service.download_file(model.source_video_key, local_path)

                if success:
                    model.local_video_path = local_path
                    logger.info(f"Saved local video copy: {local_path}")
                else:
                    logger.warning(f"Failed to save local video copy for model {model.id}")
            except Exception as e:
                logger.warning(f"Error saving local video copy: {e}")
                # Continue without local copy - CLI will download from S3 as fallback

    # Update model with progress
    model.duration_seconds = data.duration_seconds
    model.status = ModelStatus.UPLOADING.value
    model.progress_percent = 8  # 8% - Upload verified, queuing for processing
    model.processing_stage = ProcessingStage.UPLOADING.value
    await db.commit()

    # Create avatar generation job
    job = await avatar_job_service.create_job(
        video_model_id=model.id,
        user_id=user.id,
        db=db,
    )

    logger.info(f"Created avatar job {job.id} for video model {model.id}")

    # Process pending jobs (will trigger this job if slots available)
    background_tasks.add_task(
        process_avatar_jobs_task,
    )

    # Generate thumbnail if not already present
    if not model.thumbnail_key and model.source_video_key:
        background_tasks.add_task(
            generate_thumbnail_task,
            model_id=model.id,
            user_id=user.id,
            video_s3_key=model.source_video_key,
        )

    return {
        "model": VideoModelBrief.model_validate(model).model_dump(),
        "job_id": str(job.id),
        "message": "Video uploaded, avatar generation job queued",
    }


async def process_avatar_jobs_task():
    """Background task to process pending avatar jobs."""
    from app.db import get_db_session

    async with get_db_session() as db:
        await avatar_job_service.process_pending_jobs(db)


async def generate_thumbnail_task(
    model_id: UUID,
    user_id: int,
    video_s3_key: str,
):
    """
    Background task to generate and upload thumbnail for a video model.
    Downloads video from S3 if needed, extracts thumbnail, uploads to S3.
    """
    import tempfile
    from app.db import get_db_session

    temp_video_path = None
    thumbnail_path = None

    try:
        # Download video from S3 to temp file
        ext = os.path.splitext(video_s3_key)[1] or ".mp4"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            temp_video_path = tmp.name

        success = await s3_service.download_file(video_s3_key, temp_video_path)
        if not success:
            logger.error(f"Failed to download video for thumbnail: {video_s3_key}")
            return

        # Extract thumbnail
        thumbnail_path = await extract_thumbnail(temp_video_path, timestamp=1.0)
        if not thumbnail_path:
            logger.warning(f"Failed to extract thumbnail for model {model_id}")
            return

        # Generate S3 key for thumbnail
        thumbnail_s3_key = s3_service.generate_s3_key(
            user_id=str(user_id),
            filename=f"{model_id}.jpg",
            media_type="thumbnails",
            unique_id=str(model_id),
        )

        # Upload thumbnail to S3
        success = await s3_service.upload_file(
            thumbnail_path, thumbnail_s3_key, content_type="image/jpeg"
        )

        if success:
            logger.info(f"Thumbnail uploaded: {thumbnail_s3_key}")
            # Update model with thumbnail key
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

    except Exception as e:
        logger.error(f"Thumbnail generation task error: {e}")
    finally:
        # Clean up temp files
        if temp_video_path and os.path.exists(temp_video_path):
            os.remove(temp_video_path)
        if thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)


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
