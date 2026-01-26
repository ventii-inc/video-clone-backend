"""Avatar job service for managing the avatar generation queue"""

import glob
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.models import AvatarJob, User, VideoModel
from app.models.avatar_job import JobStatus
from app.models.video_model import ModelStatus, ProcessingStage
from app.services.avatar_job.runpod_client import runpod_client
from app.services.livetalking import livetalking_cli_service
from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.services.email import TrainingCompletionData, TrainingFailureData, get_email_service
from app.services.progress import update_video_model_progress
from app.services.s3 import s3_service
from app.utils import logger

# Directory for job output files
AVATAR_JOBS_OUTPUT_DIR = "/tmp/avatar_jobs"


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

    async def _get_execution_mode(self) -> str:
        """
        Determine execution mode based on GPU availability.

        Logic:
        1. If LIVETALKING_MODE is explicitly "cli" → return "cli"
        2. If LIVETALKING_MODE is "auto" or "api" → check RunPod GPU availability
        3. If GPU available → return "api"
        4. Otherwise → return "cli" (fallback)

        Returns:
            "cli" or "api"
        """
        settings = LiveTalkingSettings()

        # If explicitly set to CLI, use CLI
        if settings.LIVETALKING_MODE == "cli":
            return "cli"

        # If set to "auto" or "api", check GPU availability
        if settings.LIVETALKING_MODE in ("auto", "api"):
            gpu_available = await runpod_client.check_gpu_availability("NVIDIA RTX 5090")
            if gpu_available:
                logger.info("RTX 5090 available, using API mode")
                return "api"
            else:
                logger.info("RTX 5090 not available, falling back to CLI mode")
                return "cli"

        # Default fallback
        return "cli"

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

        # Update job status to processing
        job.status = JobStatus.PROCESSING.value
        job.started_at = datetime.utcnow()
        job.attempts += 1

        # Update video model status with progress
        video_model.status = ModelStatus.PROCESSING.value
        video_model.processing_started_at = datetime.utcnow()
        video_model.processing_stage = ProcessingStage.PREPARING.value
        video_model.progress_percent = 10  # 10% - Starting preparation

        await db.commit()

        # Choose execution mode based on GPU availability
        mode = await self._get_execution_mode()

        if mode == "cli":
            return await self._trigger_job_cli(job, video_model, db)
        else:
            return await self._trigger_job_api(job, video_model, db)

    async def _trigger_job_cli(
        self, job: AvatarJob, video_model: VideoModel, db: AsyncSession
    ) -> bool:
        """
        Trigger avatar generation via CLI as a detached subprocess.

        The subprocess runs independently of the parent server, so it survives
        server restarts. We store the PID and output file path for tracking.

        Uses local video file if available, otherwise downloads from S3.
        Auto-recovers stuck uploads: if local exists but S3 doesn't, uploads first.
        Returns immediately after spawning the process (fire-and-forget).
        """
        try:
            # Check if local video file exists
            if video_model.local_video_path and os.path.exists(video_model.local_video_path):
                video_path = video_model.local_video_path
                logger.info(f"Using local video file: {video_path}")

                # Auto-recover: if local exists but S3 doesn't, upload now
                if video_model.source_video_key:
                    s3_exists = await s3_service.file_exists(video_model.source_video_key)
                    if not s3_exists:
                        logger.info(f"S3 file missing, uploading from local: {video_model.source_video_key}")
                        await update_video_model_progress(
                            db, job.video_model_id, ProcessingStage.PREPARING, 8
                        )
                        upload_success = await s3_service.upload_file(
                            video_path, video_model.source_video_key
                        )
                        if upload_success:
                            logger.info(f"Auto-recovered S3 upload: {video_model.source_video_key}")
                        else:
                            logger.warning(f"Failed to auto-recover S3 upload, continuing with local file")

                # Update progress: preparation done, ready for training
                await update_video_model_progress(
                    db, job.video_model_id, ProcessingStage.PREPARING, 18
                )
            else:
                # Fallback: Download video from S3 to a persistent temp location
                # We can't use NamedTemporaryFile with delete=True since we return immediately
                logger.info(f"Local video not found, downloading from S3: {video_model.source_video_key}")

                # Update progress: downloading
                await update_video_model_progress(
                    db, job.video_model_id, ProcessingStage.PREPARING, 12
                )

                ext = os.path.splitext(video_model.source_video_key)[1] or ".mp4"
                # Store in job output directory so it persists
                Path(AVATAR_JOBS_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
                video_path = os.path.join(AVATAR_JOBS_OUTPUT_DIR, f"{job.id}_source{ext}")

                success = await s3_service.download_file(
                    video_model.source_video_key, video_path
                )

                if not success:
                    raise ValueError(f"Failed to download video from S3")

                # Update progress: download complete
                await update_video_model_progress(
                    db, job.video_model_id, ProcessingStage.PREPARING, 18
                )

            # Update progress: starting training (20-80% range)
            await update_video_model_progress(
                db, job.video_model_id, ProcessingStage.TRAINING, 20
            )

            # Prepare output file path
            Path(AVATAR_JOBS_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
            output_file = os.path.join(AVATAR_JOBS_OUTPUT_DIR, f"{job.id}.log")

            # Start avatar generation as detached process
            logger.info(f"Starting detached CLI avatar generation for {job.video_model_id}")
            pid = livetalking_cli_service.start_avatar_generation_detached(
                video_path=video_path,
                avatar_id=str(job.video_model_id),
                output_file=output_file,
                img_size=256,  # wav2lip256
            )

            # Store PID and output file for tracking
            job.pid = pid
            job.output_file = output_file
            await db.commit()

            logger.info(
                f"Detached avatar generation started: job={job.id}, pid={pid}, "
                f"output_file={output_file}"
            )

            # Return immediately - job will be checked later via check_running_jobs()
            return True

        except Exception as e:
            error_msg = str(e)
            logger.error(f"CLI avatar generation failed to start for {job.id}: {error_msg}")

            # Check if we should retry
            if job.attempts < job.max_attempts:
                job.status = JobStatus.PENDING.value
                job.error_message = f"Attempt {job.attempts} failed: {error_msg}"
                await db.commit()
                logger.warning(
                    f"Job {job.id} failed, will retry. "
                    f"Attempts: {job.attempts}/{job.max_attempts}"
                )
                return False
            else:
                await self.mark_failed(
                    job.id,
                    f"Max attempts reached. Last error: {error_msg}",
                    db,
                )
                return False

    async def _trigger_job_api(
        self, job: AvatarJob, video_model: VideoModel, db: AsyncSession
    ) -> bool:
        """
        Trigger avatar generation via RunPod API (remote worker).

        This is the original implementation using HTTP calls to RunPod.
        """
        # Generate presigned URL for the video
        video_url = await s3_service.generate_presigned_url(
            video_model.source_video_key, expiration=7200  # 2 hours
        )

        if not video_url:
            logger.error(f"Could not generate presigned URL for job {job.id}")
            await self.mark_failed(job.id, "Could not generate download URL", db)
            return False

        # Trigger RunPod
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
                execution_mode="api",
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

    async def check_running_jobs(self, db: AsyncSession) -> int:
        """
        Check all running CLI jobs for completion.

        This method polls detached processes to see if they've finished,
        then finalizes completed jobs (upload to S3, send notifications).

        Should be called periodically (e.g., every 30 seconds) via cron or background task.

        Returns:
            Number of jobs that were finalized
        """
        # Get all processing jobs with a PID (detached CLI jobs)
        result = await db.execute(
            select(AvatarJob).where(
                AvatarJob.status == JobStatus.PROCESSING.value,
                AvatarJob.pid.isnot(None),
            )
        )
        running_jobs = list(result.scalars().all())

        if not running_jobs:
            return 0

        jobs_finalized = 0

        for job in running_jobs:
            try:
                is_complete, result_data, error_msg = livetalking_cli_service.check_avatar_generation_result(
                    pid=job.pid,
                    output_file=job.output_file,
                    avatar_id=str(job.video_model_id),
                )

                if not is_complete:
                    # Still running
                    continue

                if result_data and result_data.get("success"):
                    # Success - finalize the job
                    await self._finalize_completed_job(job, result_data, db)
                    jobs_finalized += 1
                else:
                    # Failed
                    if job.attempts < job.max_attempts:
                        # Reset for retry
                        job.status = JobStatus.PENDING.value
                        job.error_message = f"Attempt {job.attempts} failed: {error_msg}"
                        job.pid = None
                        job.output_file = None
                        await db.commit()
                        logger.warning(
                            f"Job {job.id} failed, will retry. "
                            f"Attempts: {job.attempts}/{job.max_attempts}"
                        )
                    else:
                        await self.mark_failed(
                            job.id,
                            f"Max attempts reached. Last error: {error_msg}",
                            db,
                        )
                    jobs_finalized += 1

            except Exception as e:
                logger.error(f"Error checking job {job.id}: {e}")

        if jobs_finalized > 0:
            logger.info(f"Finalized {jobs_finalized} avatar generation jobs")
            # Try to process pending jobs now that slots may be available
            await self.process_pending_jobs(db)

        return jobs_finalized

    async def _finalize_completed_job(
        self,
        job: AvatarJob,
        result_data: dict,
        db: AsyncSession,
    ) -> None:
        """
        Finalize a completed detached job: move avatar, upload to S3, mark complete.

        Args:
            job: The completed job
            result_data: Result data from the CLI process
            db: Database session
        """
        avatar_id = str(job.video_model_id)
        settings = LiveTalkingSettings()

        # Get the avatar path
        livetalking_avatar_path = os.path.join(
            settings.LIVETALKING_ROOT, "data", "avatars", avatar_id
        )
        local_avatar_dir = os.path.join(settings.AVATAR_LOCAL_PATH, avatar_id)

        # Move avatar from LiveTalking's location to our avatar storage if needed
        livetalking_resolved = os.path.realpath(livetalking_avatar_path)
        local_resolved = os.path.realpath(local_avatar_dir)

        if livetalking_resolved != local_resolved:
            if os.path.exists(livetalking_avatar_path):
                if os.path.exists(local_avatar_dir):
                    shutil.rmtree(local_avatar_dir)
                shutil.move(livetalking_avatar_path, local_avatar_dir)
                logger.info(f"Moved avatar to {local_avatar_dir}")
        else:
            # Same path - use whatever exists
            if os.path.exists(livetalking_avatar_path):
                local_avatar_dir = livetalking_avatar_path

        # Upload to S3
        s3_key = None
        tar_path = None
        try:
            tar_path = f"{local_avatar_dir}.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(local_avatar_dir, arcname=avatar_id)

            s3_key = f"avatars/{job.user_id}/{avatar_id}.tar"
            await s3_service.upload_file(
                tar_path,
                s3_key,
                content_type="application/x-tar",
            )
            logger.info(f"Uploaded avatar TAR to S3: {s3_key}")
        except Exception as e:
            logger.error(f"Failed to upload avatar to S3: {e}")
            s3_key = f"avatars/{job.user_id}/{avatar_id}.tar"  # Still set expected key
        finally:
            if tar_path and os.path.exists(tar_path):
                os.remove(tar_path)

        # Update progress before marking complete
        await update_video_model_progress(
            db, job.video_model_id, ProcessingStage.FINALIZING, 85
        )

        # Clean up temp files
        self._cleanup_job_files(job)

        # Mark the job as completed
        await self.mark_completed(
            job.id,
            avatar_s3_key=s3_key,
            db=db,
            execution_mode="cli",
        )

        logger.info(
            f"CLI avatar generation completed: {job.video_model_id}, "
            f"frames={result_data.get('frame_count')}, s3_key={s3_key}"
        )

    def _cleanup_job_files(self, job: AvatarJob) -> None:
        """Clean up temporary files for a job."""
        try:
            # Remove output log file
            if job.output_file and os.path.exists(job.output_file):
                os.remove(job.output_file)

            # Remove downloaded source video if it was in our temp directory
            source_pattern = os.path.join(AVATAR_JOBS_OUTPUT_DIR, f"{job.id}_source*")
            for f in glob.glob(source_pattern):
                os.remove(f)
        except Exception as e:
            logger.warning(f"Error cleaning up job files for {job.id}: {e}")

    async def mark_completed(
        self,
        job_id: UUID,
        avatar_s3_key: str,
        db: AsyncSession,
        upload_url: Optional[str] = None,
        runpod_job_id: Optional[str] = None,
        execution_mode: Optional[str] = None,
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
        job.pid = None  # Clear detached process tracking
        job.output_file = None
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
            video_model.progress_percent = 100
            video_model.processing_stage = ProcessingStage.COMPLETED.value
            if execution_mode:
                video_model.execution_mode = execution_mode

        # Fetch user for email notification
        user_result = await db.execute(select(User).where(User.id == job.user_id))
        user = user_result.scalar_one_or_none()

        await db.commit()

        # Send training completion email
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
                logger.warning(f"Failed to send completion email for job {job_id}: {e}")

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
        job.pid = None  # Clear detached process tracking
        job.output_file = None

        # Update video model
        vm_result = await db.execute(
            select(VideoModel).where(VideoModel.id == job.video_model_id)
        )
        video_model = vm_result.scalar_one_or_none()

        if video_model:
            video_model.status = ModelStatus.FAILED.value
            video_model.error_message = error_message
            video_model.processing_completed_at = datetime.utcnow()
            video_model.processing_stage = ProcessingStage.FAILED.value
            # Keep current progress_percent to show where it failed

        # Fetch user for email notification
        user_result = await db.execute(select(User).where(User.id == job.user_id))
        user = user_result.scalar_one_or_none()

        await db.commit()

        # Send training failure email
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
                logger.warning(f"Failed to send failure email for job {job_id}: {e}")

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
            video_model.progress_percent = 0
            video_model.processing_stage = ProcessingStage.PENDING.value

        await db.commit()
        await db.refresh(job)

        logger.info(f"Job {job_id} reset for retry")

        # Try to process it immediately if slots available
        await self.process_pending_jobs(db)

        return job


# Singleton instance
avatar_job_service = AvatarJobService()
