"""Internal avatar backend endpoints for machine-to-machine communication"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import VideoModel, AvatarJob
from app.models.video_model import ModelStatus
from app.services.api_key import get_api_key
from app.services.avatar_job import avatar_job_service
from app.services.s3 import s3_service
from app.schemas.avatar_backend import (
    PendingVideoItem,
    PendingVideosResponse,
    AvatarCompleteRequest,
    AvatarCompleteResponse,
)
from app.schemas.avatar_job import (
    JobQueueStatusResponse,
    RetryJobResponse,
    AvatarJobResponse,
)
from app.utils import logger

router = APIRouter(prefix="/internal/avatar", tags=["Internal Avatar Backend"])


@router.get("/pending-videos", response_model=PendingVideosResponse)
async def get_pending_videos(
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> PendingVideosResponse:
    """
    Get list of videos pending avatar processing.

    Returns video models with status 'pending' or 'uploading' that have
    a source video uploaded and ready for avatar generation.

    Requires X-API-Key header for authentication.
    """
    # Query for video models that are ready for avatar processing
    # They should have a source video key but no model data key yet
    query = (
        select(VideoModel)
        .where(
            VideoModel.status.in_([ModelStatus.PENDING.value, ModelStatus.UPLOADING.value]),
            VideoModel.source_video_key.isnot(None),
            VideoModel.model_data_key.is_(None),
        )
        .order_by(VideoModel.created_at.asc())
    )

    result = await db.execute(query)
    video_models = result.scalars().all()

    # Build response with presigned download URLs
    videos = []
    for model in video_models:
        download_url = await s3_service.generate_presigned_url(
            model.source_video_key, expiration=3600  # 1 hour
        )

        if download_url:
            videos.append(
                PendingVideoItem(
                    model_id=model.id,
                    user_id=model.user_id,
                    s3_key=model.source_video_key,
                    download_url=download_url,
                    created_at=model.created_at,
                )
            )
        else:
            logger.warning(
                f"Could not generate presigned URL for model {model.id}, "
                f"s3_key: {model.source_video_key}"
            )

    logger.info(f"Returning {len(videos)} pending videos for avatar processing")
    return PendingVideosResponse(videos=videos)


@router.post("/{model_id}/complete", response_model=AvatarCompleteResponse)
async def mark_avatar_complete(
    model_id: UUID,
    request: AvatarCompleteRequest,
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> AvatarCompleteResponse:
    """
    Mark avatar processing as complete for a video model.

    Called by the avatar backend after successfully generating and uploading
    the avatar TAR file to S3.

    If error_message is provided, the model is marked as failed instead.

    Requires X-API-Key header for authentication.
    """
    # Find the video model
    query = select(VideoModel).where(VideoModel.id == model_id)
    result = await db.execute(query)
    video_model = result.scalar_one_or_none()

    if not video_model:
        logger.warning(f"Video model not found: {model_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video model with id {model_id} not found",
        )

    # Update the model based on success or failure
    if request.error_message:
        video_model.status = ModelStatus.FAILED.value
        video_model.error_message = request.error_message
        video_model.processing_completed_at = datetime.utcnow()
        logger.error(
            f"Avatar processing failed for model {model_id}: {request.error_message}"
        )
    else:
        video_model.status = ModelStatus.COMPLETED.value
        video_model.model_data_key = request.s3_key
        video_model.processing_completed_at = datetime.utcnow()
        video_model.error_message = None
        logger.info(
            f"Avatar processing completed for model {model_id}, "
            f"avatar_key: {request.s3_key}"
        )

    await db.commit()
    await db.refresh(video_model)

    return AvatarCompleteResponse(
        success=True,
        model_id=video_model.id,
        status=video_model.status,
    )


@router.get("/jobs/status", response_model=JobQueueStatusResponse)
async def get_job_queue_status(
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> JobQueueStatusResponse:
    """
    Get the current status of the avatar job queue.

    Returns counts of running, pending jobs and the max concurrent limit.

    Requires X-API-Key header for authentication.
    """
    running = await avatar_job_service.get_running_count(db)
    pending = await avatar_job_service.get_pending_count(db)
    completed_today = await avatar_job_service.get_jobs_completed_today(db)
    failed_today = await avatar_job_service.get_jobs_failed_today(db)

    return JobQueueStatusResponse(
        running=running,
        pending=pending,
        max_concurrent=avatar_job_service.max_concurrent,
        completed_today=completed_today,
        failed_today=failed_today,
    )


@router.post("/jobs/{job_id}/retry", response_model=RetryJobResponse)
async def retry_failed_job(
    job_id: UUID,
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> RetryJobResponse:
    """
    Retry a failed avatar generation job.

    Resets the job to pending status and attempts to process it again.

    Requires X-API-Key header for authentication.
    """
    job = await avatar_job_service.retry_job(job_id, db)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found or cannot be retried",
        )

    return RetryJobResponse(
        success=True,
        job_id=job.id,
        message="Job reset for retry",
        new_status=job.status,
    )


@router.get("/jobs/{job_id}", response_model=AvatarJobResponse)
async def get_job_details(
    job_id: UUID,
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> AvatarJobResponse:
    """
    Get details of a specific avatar job.

    Requires X-API-Key header for authentication.
    """
    result = await db.execute(select(AvatarJob).where(AvatarJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return AvatarJobResponse.model_validate(job)
