"""Worker endpoints for receiving jobs from API server (RunPod worker mode)"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.services.api_key import get_worker_api_key
from app.services.worker.worker_service import worker_service
from app.schemas.worker import (
    AvatarJobRequest,
    VideoJobRequest,
    WorkerHealthResponse,
    WorkerCapacityResponse,
    JobSubmitResponse,
)
from app.utils import logger

router = APIRouter(prefix="/worker", tags=["Worker"])


@router.get("/health", response_model=WorkerHealthResponse)
async def worker_health() -> WorkerHealthResponse:
    """
    Health check endpoint for worker.

    Returns worker status, GPU availability, and processing capacity.
    No authentication required for health checks.
    """
    health = await worker_service.health_check()
    return WorkerHealthResponse(**health)


@router.get("/capacity", response_model=WorkerCapacityResponse)
async def worker_capacity(
    _api_key: str = Depends(get_worker_api_key),
) -> WorkerCapacityResponse:
    """
    Get current worker capacity.

    Returns available slots and current job counts.
    Requires X-API-Key header for authentication.
    """
    return WorkerCapacityResponse(
        available_slots=worker_service.available_slots,
        max_concurrent=worker_service.max_concurrent,
        current_jobs=worker_service.current_jobs,
        queue_depth=0,  # No local queue - jobs are processed immediately or rejected
    )


@router.post("/jobs/avatar", response_model=JobSubmitResponse)
async def submit_avatar_job(
    request: AvatarJobRequest,
    background_tasks: BackgroundTasks,
    _api_key: str = Depends(get_worker_api_key),
) -> JobSubmitResponse:
    """
    Submit an avatar generation job to the worker.

    The job is executed in the background. Progress and completion
    callbacks are sent to the API server.

    Requires X-API-Key header for authentication.
    """
    # Check capacity
    if not await worker_service.can_accept_job():
        logger.warning(f"Worker at capacity, rejecting avatar job {request.job_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker at capacity",
            headers={"Retry-After": "30"},
        )

    logger.info(
        f"Accepted avatar job {request.job_id} for video_model {request.video_model_id}"
    )

    # Execute job in background
    background_tasks.add_task(
        _execute_avatar_job_async,
        job_id=request.job_id,
        video_model_id=request.video_model_id,
        user_id=request.user_id,
        video_url=request.video_url,
        callback_url=request.callback_url,
        options=request.options,
    )

    return JobSubmitResponse(
        success=True,
        job_id=request.job_id,
        message="Job accepted and queued for processing",
        queue_position=None,  # Job starts immediately
    )


@router.post("/jobs/video", response_model=JobSubmitResponse)
async def submit_video_job(
    request: VideoJobRequest,
    background_tasks: BackgroundTasks,
    _api_key: str = Depends(get_worker_api_key),
) -> JobSubmitResponse:
    """
    Submit a video generation job to the worker.

    The job is executed in the background. Results are uploaded to S3.

    Requires X-API-Key header for authentication.
    """
    # Check capacity
    if not await worker_service.can_accept_job():
        logger.warning(f"Worker at capacity, rejecting video job {request.video_id}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker at capacity",
            headers={"Retry-After": "30"},
        )

    logger.info(
        f"Accepted video job {request.video_id} with avatar {request.avatar_id}"
    )

    # Execute job in background
    # Note: video_id is used as job tracking ID, extract user_id from options or callback
    background_tasks.add_task(
        _execute_video_job_async,
        video_id=request.video_id,
        avatar_id=request.avatar_id,
        text=request.text,
        voice_model_id=request.voice_model_id,
        callback_url=request.callback_url,
        options=request.options,
    )

    return JobSubmitResponse(
        success=True,
        job_id=request.video_id,
        message="Job accepted and queued for processing",
        queue_position=None,
    )


async def _execute_avatar_job_async(
    job_id: UUID,
    video_model_id: UUID,
    user_id: int,
    video_url: str,
    callback_url: str,
    options: dict | None,
) -> None:
    """Background task wrapper for avatar job execution."""
    try:
        await worker_service.execute_avatar_job(
            job_id=job_id,
            video_model_id=video_model_id,
            user_id=user_id,
            video_url=video_url,
            callback_url=callback_url,
            options=options,
        )
    except Exception as e:
        logger.error(f"Unhandled error in avatar job {job_id}: {e}", exc_info=True)


async def _execute_video_job_async(
    video_id: UUID,
    avatar_id: UUID,
    text: str,
    voice_model_id: UUID | None,
    callback_url: str,
    options: dict | None,
) -> None:
    """Background task wrapper for video job execution."""
    try:
        # Extract user_id from options - required parameter
        user_id = (options or {}).get("user_id")
        if not user_id:
            raise ValueError("user_id is required in options for video job execution")

        await worker_service.execute_video_job(
            video_id=video_id,
            avatar_id=avatar_id,
            text=text,
            user_id=user_id,
            voice_model_id=voice_model_id,
            callback_url=callback_url,
            options=options,
        )
    except Exception as e:
        logger.error(f"Unhandled error in video job {video_id}: {e}", exc_info=True)
