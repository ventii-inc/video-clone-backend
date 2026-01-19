"""Avatar job service for managing the avatar generation queue"""

import os
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.models import AvatarJob, VideoModel
from app.models.avatar_job import JobStatus
from app.models.video_model import ModelStatus
from app.services.avatar_job.runpod_client import runpod_client
from app.services.s3 import s3_service
from app.utils import logger


class AvatarJobService:
    """Service for managing avatar generation job queue"""

    def __init__(self):
        self._max_concurrent: Optional[int] = None

    @property
    def max_concurrent(self) -> int:
        """Maximum concurrent jobs allowed"""
        if self._max_concurrent is None:
            self._max_concurrent = int(os.getenv("AVATAR_MAX_CONCURRENT", "3"))
        return self._max_concurrent

    async def create_job(
        self, video_model_id: UUID, user_id: int, db: AsyncSession
    ) -> AvatarJob:
        """
        Create a new avatar generation job.

        Args:
            video_model_id: ID of the video model to process
            user_id: ID of the user who owns the video model
            db: Database session

        Returns:
            The created AvatarJob
        """
        # Check if job already exists for this video model
        existing = await db.execute(
            select(AvatarJob).where(
                AvatarJob.video_model_id == video_model_id,
                AvatarJob.status.in_(
                    [JobStatus.PENDING.value, JobStatus.PROCESSING.value]
                ),
            )
        )
        existing_job = existing.scalar_one_or_none()

        if existing_job:
            logger.info(
                f"Job already exists for video_model {video_model_id}: {existing_job.id}"
            )
            return existing_job

        job = AvatarJob(
            video_model_id=video_model_id,
            user_id=user_id,
            status=JobStatus.PENDING.value,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        logger.info(f"Created avatar job {job.id} for video_model {video_model_id}")
        return job

    async def get_running_count(self, db: AsyncSession) -> int:
        """Get the number of currently running jobs"""
        result = await db.execute(
            select(func.count(AvatarJob.id)).where(
                AvatarJob.status == JobStatus.PROCESSING.value
            )
        )
        return result.scalar() or 0

    async def get_pending_count(self, db: AsyncSession) -> int:
        """Get the number of pending jobs"""
        result = await db.execute(
            select(func.count(AvatarJob.id)).where(
                AvatarJob.status == JobStatus.PENDING.value
            )
        )
        return result.scalar() or 0

    async def get_pending_jobs(
        self, db: AsyncSession, limit: int = 10
    ) -> List[AvatarJob]:
        """Get pending jobs ordered by creation time (FIFO)"""
        result = await db.execute(
            select(AvatarJob)
            .where(AvatarJob.status == JobStatus.PENDING.value)
            .order_by(AvatarJob.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_jobs_completed_today(self, db: AsyncSession) -> int:
        """Get count of jobs completed today"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(func.count(AvatarJob.id)).where(
                and_(
                    AvatarJob.status == JobStatus.COMPLETED.value,
                    AvatarJob.completed_at >= today_start,
                )
            )
        )
        return result.scalar() or 0

    async def get_jobs_failed_today(self, db: AsyncSession) -> int:
        """Get count of jobs failed today"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(func.count(AvatarJob.id)).where(
                and_(
                    AvatarJob.status == JobStatus.FAILED.value,
                    AvatarJob.completed_at >= today_start,
                )
            )
        )
        return result.scalar() or 0

    async def can_start_new_job(self, db: AsyncSession) -> bool:
        """Check if we can start a new job based on concurrent limit"""
        running = await self.get_running_count(db)
        return running < self.max_concurrent

    async def process_pending_jobs(self, db: AsyncSession) -> int:
        """
        Process pending jobs up to the concurrent limit.

        Returns:
            Number of jobs started
        """
        jobs_started = 0
        running = await self.get_running_count(db)
        available_slots = self.max_concurrent - running

        if available_slots <= 0:
            logger.info(
                f"No available slots for new jobs (running={running}, max={self.max_concurrent})"
            )
            return 0

        pending_jobs = await self.get_pending_jobs(db, limit=available_slots)

        for job in pending_jobs:
            success = await self.trigger_job(job, db)
            if success:
                jobs_started += 1

        if jobs_started > 0:
            logger.info(f"Started {jobs_started} avatar generation jobs")

        return jobs_started

    async def trigger_job(self, job: AvatarJob, db: AsyncSession) -> bool:
        """
        Trigger a single job for processing.

        Args:
            job: The job to trigger
            db: Database session

        Returns:
            True if job was successfully triggered, False otherwise
        """
        # Get the video model to get the source video
        result = await db.execute(
            select(VideoModel).where(VideoModel.id == job.video_model_id)
        )
        video_model = result.scalar_one_or_none()

        if not video_model:
            logger.error(f"Video model not found for job {job.id}")
            await self.mark_failed(job.id, "Video model not found", db)
            return False

        if not video_model.source_video_key:
            logger.error(f"No source video for job {job.id}")
            await self.mark_failed(job.id, "No source video uploaded", db)
            return False

        # Generate presigned URL for the video
        video_url = await s3_service.generate_presigned_url(
            video_model.source_video_key, expiration=7200  # 2 hours
        )

        if not video_url:
            logger.error(f"Could not generate presigned URL for job {job.id}")
            await self.mark_failed(job.id, "Could not generate download URL", db)
            return False

        # Update job status to processing
        job.status = JobStatus.PROCESSING.value
        job.started_at = datetime.utcnow()
        job.attempts += 1

        # Update video model status
        video_model.status = ModelStatus.PROCESSING.value
        video_model.processing_started_at = datetime.utcnow()

        await db.commit()

        # Trigger RunPod (this is async and will take time)
        # For now, we do it synchronously. In production, consider using
        # a background task or message queue for better reliability
        s3_bucket = os.getenv("AVATAR_S3_BUCKET", s3_service.bucket_name)

        response = await runpod_client.generate_avatar(
            video_url=video_url,
            avatar_id=str(job.video_model_id),
            model="wav2lip",
            s3_bucket=s3_bucket,
            s3_prefix=f"avatars/{job.user_id}",
        )

        if response.success:
            # Job completed successfully
            await self.mark_completed(
                job.id,
                avatar_s3_key=f"avatars/{job.user_id}/{job.video_model_id}.tar",
                upload_url=response.upload_url,
                runpod_job_id=response.job_id,
                db=db,
            )
            return True
        else:
            # Check if we should retry
            if job.attempts < job.max_attempts:
                # Reset to pending for retry
                job.status = JobStatus.PENDING.value
                job.error_message = f"Attempt {job.attempts} failed: {response.error}"
                await db.commit()
                logger.warning(
                    f"Job {job.id} failed, will retry. "
                    f"Attempts: {job.attempts}/{job.max_attempts}"
                )
                return False
            else:
                await self.mark_failed(
                    job.id,
                    f"Max attempts reached. Last error: {response.error}",
                    db,
                )
                return False

    async def mark_completed(
        self,
        job_id: UUID,
        avatar_s3_key: str,
        db: AsyncSession,
        upload_url: Optional[str] = None,
        runpod_job_id: Optional[str] = None,
    ) -> None:
        """Mark a job as completed and update the video model"""
        result = await db.execute(select(AvatarJob).where(AvatarJob.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            logger.error(f"Job not found: {job_id}")
            return

        job.status = JobStatus.COMPLETED.value
        job.completed_at = datetime.utcnow()
        job.avatar_s3_key = avatar_s3_key
        job.error_message = None
        if runpod_job_id:
            job.runpod_job_id = runpod_job_id

        # Update video model
        vm_result = await db.execute(
            select(VideoModel).where(VideoModel.id == job.video_model_id)
        )
        video_model = vm_result.scalar_one_or_none()

        if video_model:
            video_model.status = ModelStatus.COMPLETED.value
            video_model.model_data_key = avatar_s3_key
            video_model.processing_completed_at = datetime.utcnow()
            video_model.error_message = None

        await db.commit()

        logger.info(
            f"Job {job_id} completed successfully. Avatar key: {avatar_s3_key}"
        )

        # Process next pending job
        await self.process_pending_jobs(db)

    async def mark_failed(
        self, job_id: UUID, error_message: str, db: AsyncSession
    ) -> None:
        """Mark a job as failed and update the video model"""
        result = await db.execute(select(AvatarJob).where(AvatarJob.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            logger.error(f"Job not found: {job_id}")
            return

        job.status = JobStatus.FAILED.value
        job.completed_at = datetime.utcnow()
        job.error_message = error_message

        # Update video model
        vm_result = await db.execute(
            select(VideoModel).where(VideoModel.id == job.video_model_id)
        )
        video_model = vm_result.scalar_one_or_none()

        if video_model:
            video_model.status = ModelStatus.FAILED.value
            video_model.error_message = error_message
            video_model.processing_completed_at = datetime.utcnow()

        await db.commit()

        logger.error(f"Job {job_id} failed: {error_message}")

        # Process next pending job
        await self.process_pending_jobs(db)

    async def retry_job(self, job_id: UUID, db: AsyncSession) -> Optional[AvatarJob]:
        """
        Retry a failed job by resetting it to pending.

        Args:
            job_id: ID of the job to retry
            db: Database session

        Returns:
            The updated job if successful, None otherwise
        """
        result = await db.execute(select(AvatarJob).where(AvatarJob.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            logger.error(f"Job not found: {job_id}")
            return None

        if job.status != JobStatus.FAILED.value:
            logger.warning(f"Cannot retry job {job_id} with status {job.status}")
            return None

        # Reset job for retry
        job.status = JobStatus.PENDING.value
        job.attempts = 0
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.runpod_job_id = None

        # Reset video model status
        vm_result = await db.execute(
            select(VideoModel).where(VideoModel.id == job.video_model_id)
        )
        video_model = vm_result.scalar_one_or_none()

        if video_model:
            video_model.status = ModelStatus.PENDING.value
            video_model.error_message = None

        await db.commit()
        await db.refresh(job)

        logger.info(f"Job {job_id} reset for retry")

        # Try to process it immediately if slots available
        await self.process_pending_jobs(db)

        return job


# Singleton instance
avatar_job_service = AvatarJobService()
