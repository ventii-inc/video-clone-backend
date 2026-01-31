"""Internal avatar backend endpoints for machine-to-machine communication"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import VideoModel, AvatarJob, User, GeneratedVideo
from app.models.video_model import ModelStatus, ProcessingStage
from app.models.avatar_job import JobStatus
from app.models.generated_video import GenerationStatus, VideoGenerationStage
from app.services.api_key import get_api_key
from app.services.avatar_job import avatar_job_service
from app.services.email import TrainingCompletionData, TrainingFailureData, VideoGenerationCompletionData, get_email_service
from app.services.usage_service import usage_service
from app.services.s3 import s3_service
from app.services.progress import update_video_model_progress
from app.schemas.avatar_backend import (
    PendingVideoItem,
    PendingVideosResponse,
    AvatarCompleteRequest,
    AvatarCompleteResponse,
    JobCallbackRequest,
    JobCallbackResponse,
    JobProgressRequest,
    JobProgressResponse,
    VideoCallbackRequest,
)
from app.schemas.avatar_job import (
    JobQueueStatusResponse,
    RetryJobResponse,
    AvatarJobResponse,
)
from app.utils import logger

router = APIRouter(prefix="/internal/avatar", tags=["Internal Avatar Backend"])
video_router = APIRouter(prefix="/internal/videos", tags=["Internal Video Backend"])


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


@router.post("/jobs/{job_id}/callback", response_model=JobCallbackResponse)
async def job_callback(
    job_id: UUID,
    request: JobCallbackRequest,
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> JobCallbackResponse:
    """
    Receive completion callback from remote LipSync service.

    Called by the Lip-Sync-Experiment service when job processing completes
    (either successfully or with an error).

    Requires X-API-Key header for authentication.
    """
    # Find the job
    result = await db.execute(select(AvatarJob).where(AvatarJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        logger.warning(f"Callback received for unknown job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Find the associated video model
    video_result = await db.execute(
        select(VideoModel).where(VideoModel.id == job.video_model_id)
    )
    video_model = video_result.scalar_one_or_none()

    if not video_model:
        logger.error(f"Video model not found for job {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video model for job {job_id} not found",
        )

    # Fetch user for email notification
    user_result = await db.execute(select(User).where(User.id == job.user_id))
    user = user_result.scalar_one_or_none()

    # Update based on callback status
    if request.status == "completed" and request.s3_key:
        # Success - update job and video model
        job.status = JobStatus.COMPLETED.value
        job.completed_at = datetime.utcnow()
        job.avatar_s3_key = request.s3_key
        job.error_message = None

        video_model.status = ModelStatus.COMPLETED.value
        video_model.model_data_key = request.s3_key
        video_model.processing_stage = ProcessingStage.COMPLETED.value
        video_model.progress_percent = 100
        video_model.processing_completed_at = datetime.utcnow()
        video_model.error_message = None

        logger.info(
            f"Job {job_id} completed successfully, s3_key={request.s3_key}, "
            f"frames={request.frame_count}, time={request.processing_time_seconds}s"
        )
        message = "Job marked as completed"

        # Send completion email
        if user and user.email:
            try:
                email_service = get_email_service()
                await email_service.send_training_completion_email(
                    to_email=user.email,
                    data=TrainingCompletionData(
                        user_name=user.name or "there",
                        model_name=video_model.name if video_model else "Your Avatar",
                        model_type="video",
                        dashboard_url=None,
                    ),
                )
                logger.info(f"Sent completion email to {user.email} for job {job_id}")
            except Exception as e:
                logger.error(f"Failed to send completion email for job {job_id}: {e}")

    else:
        # Failure - update with error info
        error_message = request.error_message or "Unknown error"
        job.status = JobStatus.FAILED.value
        job.completed_at = datetime.utcnow()
        job.error_message = error_message

        video_model.status = ModelStatus.FAILED.value
        video_model.processing_stage = ProcessingStage.FAILED.value
        video_model.error_message = error_message
        video_model.processing_completed_at = datetime.utcnow()

        logger.error(
            f"Job {job_id} failed: {request.error_message} (code: {request.error_code})"
        )
        message = "Job marked as failed"

        # Send failure email
        if user and user.email:
            try:
                email_service = get_email_service()
                await email_service.send_training_failure_email(
                    to_email=user.email,
                    data=TrainingFailureData(
                        user_name=user.name or "there",
                        model_name=video_model.name if video_model else "Your Avatar",
                        model_type="video",
                        error_message=error_message,
                        dashboard_url=None,
                    ),
                )
                logger.info(f"Sent failure email to {user.email} for job {job_id}")
            except Exception as e:
                logger.error(f"Failed to send failure email for job {job_id}: {e}")

    await db.commit()

    return JobCallbackResponse(success=True, message=message)


@router.post("/jobs/{job_id}/progress", response_model=JobProgressResponse)
async def job_progress(
    job_id: UUID,
    request: JobProgressRequest,
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> JobProgressResponse:
    """
    Receive progress update from remote LipSync service.

    Called by the Lip-Sync-Experiment service to update job progress
    during processing.

    Requires X-API-Key header for authentication.
    """
    # Find the job
    result = await db.execute(select(AvatarJob).where(AvatarJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        logger.warning(f"Progress update received for unknown job: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Map stage string to ProcessingStage enum
    try:
        stage = ProcessingStage(request.stage.lower())
    except ValueError:
        logger.warning(f"Unknown processing stage: {request.stage}")
        # Default to training if unknown
        stage = ProcessingStage.TRAINING

    # Update the video model progress
    await update_video_model_progress(
        db=db,
        model_id=job.video_model_id,
        stage=stage,
        progress_percent=request.progress_percent,
    )

    logger.debug(
        f"Job {job_id} progress update: stage={stage.value}, "
        f"progress={request.progress_percent}%, message={request.message}"
    )

    return JobProgressResponse(success=True)


def _calculate_minutes_from_duration(duration_seconds: int | None) -> int:
    """Calculate billable minutes from video duration in seconds.

    Rounds up to nearest minute, minimum 1 minute.
    """
    if not duration_seconds or duration_seconds <= 0:
        return 1  # Minimum 1 minute charge
    # Round up to nearest minute
    return max(1, (duration_seconds + 59) // 60)


@video_router.post("/{video_id}/callback", response_model=JobCallbackResponse)
async def video_callback(
    video_id: UUID,
    request: VideoCallbackRequest,
    _api_key: str = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
) -> JobCallbackResponse:
    """
    Receive video generation callback from worker.

    Called by the worker service when video generation completes
    (either successfully or with an error).

    Requires X-API-Key header for authentication.
    """
    # Find the video
    result = await db.execute(
        select(GeneratedVideo).where(GeneratedVideo.id == video_id)
    )
    video = result.scalar_one_or_none()

    if not video:
        logger.warning(f"Video callback received for unknown video: {video_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video {video_id} not found",
        )

    # Fetch user for email notification
    user_result = await db.execute(select(User).where(User.id == video.user_id))
    user = user_result.scalar_one_or_none()

    # Update based on callback status
    if request.status == "completed" and request.s3_key:
        # Success - update video record
        video.status = GenerationStatus.COMPLETED.value
        video.processing_stage = VideoGenerationStage.COMPLETED.value
        video.progress_percent = 100
        video.output_video_key = request.s3_key
        video.processing_completed_at = datetime.utcnow()
        video.error_message = None

        if request.duration:
            video.duration_seconds = int(request.duration)

        logger.info(
            f"Video {video_id} completed successfully, s3_key={request.s3_key}, "
            f"duration={request.duration}s, time={request.processing_time_seconds}s"
        )
        message = "Video marked as completed"

        await db.commit()

        # Deduct credits based on actual video duration
        minutes_used = _calculate_minutes_from_duration(video.duration_seconds)
        try:
            await usage_service.deduct_credits(video.user_id, minutes_used, db)
            video.credits_used = minutes_used
            await db.commit()
            logger.info(
                f"Deducted {minutes_used} minutes for video {video_id} "
                f"(duration: {video.duration_seconds}s)"
            )
        except ValueError as e:
            logger.warning(f"Credit deduction issue for video {video_id}: {e}")
            video.credits_used = minutes_used
            await db.commit()

        # Send completion email
        if user and user.email:
            try:
                email_service = get_email_service()
                await email_service.send_video_generation_completion_email(
                    to_email=user.email,
                    data=VideoGenerationCompletionData(
                        user_name=user.name or user.email.split("@")[0],
                        video_title=video.title or "Untitled Video",
                        duration_seconds=video.duration_seconds,
                        dashboard_url="https://ventii.jp/dashboard/videos",
                    ),
                )
                logger.info(f"Sent video completion email to {user.email} for video {video_id}")
            except Exception as e:
                logger.error(f"Failed to send video completion email for video {video_id}: {e}")

    else:
        # Failure - update with error info
        error_message = request.error_message or "Unknown error"
        video.status = GenerationStatus.FAILED.value
        video.processing_stage = VideoGenerationStage.FAILED.value
        video.error_message = error_message
        video.processing_completed_at = datetime.utcnow()

        logger.error(f"Video {video_id} failed: {request.error_message}")
        message = "Video marked as failed"

        await db.commit()

    return JobCallbackResponse(success=True, message=message)
