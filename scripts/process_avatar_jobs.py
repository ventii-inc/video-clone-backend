#!/usr/bin/env python3
"""
Process pending avatar generation jobs.

Usage:
    # Process all pending jobs
    ENV=staging uv run python scripts/process_avatar_jobs.py

    # Check running jobs for completion (poll detached processes)
    ENV=staging uv run python scripts/process_avatar_jobs.py --check-running

    # Recover stuck uploads (retry S3 upload)
    ENV=staging uv run python scripts/process_avatar_jobs.py --recover-uploads

    # Reset failed jobs and process all
    ENV=staging uv run python scripts/process_avatar_jobs.py --reset-failed

    # Reset stuck processing jobs to failed
    ENV=staging uv run python scripts/process_avatar_jobs.py --reset-processing

    # Show queue status only (no processing)
    ENV=staging uv run python scripts/process_avatar_jobs.py --status

    # Reset and process a specific job by ID
    ENV=staging uv run python scripts/process_avatar_jobs.py --job-id <uuid>

    # Run as a daemon that periodically checks running jobs
    ENV=staging uv run python scripts/process_avatar_jobs.py --daemon --interval 30
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment before importing app modules
from dotenv import load_dotenv

env = os.getenv("ENV", "local")
load_dotenv(f".env.{env}")

print(f"Environment: {env}")


async def show_status():
    """Show current job queue status."""
    from sqlalchemy import select

    from app.db import get_db_session
    from app.models import AvatarJob
    from app.models.avatar_job import JobStatus
    from app.services.avatar_job import avatar_job_service
    from app.services.livetalking import livetalking_cli_service

    async with get_db_session() as db:
        running = await avatar_job_service.get_running_count(db)
        pending = await avatar_job_service.get_pending_count(db)
        completed = await avatar_job_service.get_jobs_completed_today(db)
        failed = await avatar_job_service.get_jobs_failed_today(db)

        print("\nJob Queue Status")
        print("=" * 40)
        print(f"Running:         {running}")
        print(f"Pending:         {pending}")
        print(f"Max Concurrent:  {avatar_job_service.max_concurrent}")
        print(f"Completed Today: {completed}")
        print(f"Failed Today:    {failed}")
        print("=" * 40)

        # Show details of running jobs with PIDs
        if running > 0:
            result = await db.execute(
                select(AvatarJob).where(
                    AvatarJob.status == JobStatus.PROCESSING.value,
                    AvatarJob.pid.isnot(None),
                )
            )
            running_jobs = result.scalars().all()
            if running_jobs:
                print("\nRunning Jobs (detached processes):")
                print("-" * 60)
                for job in running_jobs:
                    is_running = livetalking_cli_service.is_process_running(job.pid)
                    status_str = "alive" if is_running else "finished"
                    print(f"  Job {job.id}: PID={job.pid} ({status_str})")
                print("-" * 60)

        return pending


async def reset_failed_jobs():
    """Reset all failed jobs to pending status."""
    from sqlalchemy import update

    from app.db import get_db_session
    from app.models import AvatarJob, VideoModel
    from app.models.avatar_job import JobStatus
    from app.models.video_model import ModelStatus, ProcessingStage

    async with get_db_session() as db:
        # Get count of failed jobs
        from sqlalchemy import select, func
        result = await db.execute(
            select(func.count()).where(AvatarJob.status == JobStatus.FAILED.value)
        )
        failed_count = result.scalar()

        if failed_count == 0:
            print("No failed jobs to reset")
            return 0

        # Reset failed jobs
        await db.execute(
            update(AvatarJob)
            .where(AvatarJob.status == JobStatus.FAILED.value)
            .values(
                status=JobStatus.PENDING.value,
                attempts=0,
                error_message=None,
                started_at=None,
                completed_at=None,
                pid=None,
                output_file=None,
            )
        )

        # Also reset corresponding video models
        failed_model_ids = await db.execute(
            select(AvatarJob.video_model_id).where(
                AvatarJob.status == JobStatus.PENDING.value
            )
        )
        model_ids = [row[0] for row in failed_model_ids.fetchall()]

        if model_ids:
            await db.execute(
                update(VideoModel)
                .where(VideoModel.id.in_(model_ids))
                .where(VideoModel.status == ModelStatus.FAILED.value)
                .values(
                    status=ModelStatus.PENDING.value,
                    error_message=None,
                    progress_percent=0,
                    processing_stage=ProcessingStage.PENDING.value,
                )
            )

        await db.commit()
        print(f"Reset {failed_count} failed job(s) to pending")
        return failed_count


async def reset_processing_jobs():
    """Force reset all processing jobs to failed status."""
    from datetime import datetime

    from sqlalchemy import func, select, update

    from app.db import get_db_session
    from app.models import AvatarJob, VideoModel
    from app.models.avatar_job import JobStatus
    from app.models.video_model import ModelStatus, ProcessingStage

    async with get_db_session() as db:
        # Get count of processing jobs
        result = await db.execute(
            select(func.count()).where(AvatarJob.status == JobStatus.PROCESSING.value)
        )
        processing_count = result.scalar()

        if processing_count == 0:
            print("No processing jobs to reset")
            return 0

        # Get job IDs and video model IDs before resetting
        result = await db.execute(
            select(AvatarJob.id, AvatarJob.video_model_id).where(
                AvatarJob.status == JobStatus.PROCESSING.value
            )
        )
        jobs = result.fetchall()

        # Reset processing jobs to failed
        await db.execute(
            update(AvatarJob)
            .where(AvatarJob.status == JobStatus.PROCESSING.value)
            .values(
                status=JobStatus.FAILED.value,
                error_message="Force reset - job was stuck in processing",
                completed_at=datetime.utcnow(),
                pid=None,
                output_file=None,
            )
        )

        # Update corresponding video models
        model_ids = [job[1] for job in jobs]
        if model_ids:
            await db.execute(
                update(VideoModel)
                .where(VideoModel.id.in_(model_ids))
                .values(
                    status=ModelStatus.FAILED.value,
                    error_message="Force reset - job was stuck in processing",
                    processing_stage=ProcessingStage.FAILED.value,
                    processing_completed_at=datetime.utcnow(),
                )
            )

        await db.commit()
        print(f"Reset {processing_count} processing job(s) to failed")
        return processing_count


async def reset_specific_job(job_id: UUID):
    """Reset a specific job by ID."""
    from app.db import get_db_session
    from app.services.avatar_job import avatar_job_service

    async with get_db_session() as db:
        job = await avatar_job_service.retry_job(job_id, db)
        if job:
            print(f"Reset job {job_id} to pending (status: {job.status})")
            return True
        else:
            print(f"Could not reset job {job_id} (not found or not in failed status)")
            return False


async def process_pending_jobs():
    """Process all pending jobs."""
    from app.db import get_db_session
    from app.services.avatar_job import avatar_job_service

    async with get_db_session() as db:
        started = await avatar_job_service.process_pending_jobs(db)
        print(f"Started {started} job(s)")
        return started


async def check_running_jobs():
    """Check running jobs for completion (poll detached processes)."""
    from app.db import get_db_session
    from app.services.avatar_job import avatar_job_service

    async with get_db_session() as db:
        finalized = await avatar_job_service.check_running_jobs(db)
        print(f"Finalized {finalized} job(s)")
        return finalized


async def recover_stuck_uploads():
    """
    Recover uploads that got stuck (e.g., due to server restart).

    Finds video models with status='uploading' that have a local file but no S3 file,
    and retries the S3 upload.
    """
    import os
    from datetime import datetime, timedelta
    from sqlalchemy import text

    from app.db import get_db_session
    from app.services.s3 import s3_service

    async with get_db_session() as db:
        # Find stuck uploads (uploading for more than 5 minutes)
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        result = await db.execute(text('''
            SELECT id, name, local_video_path, source_video_key, user_id
            FROM video_models
            WHERE status = 'uploading'
            AND updated_at < :cutoff
            AND local_video_path IS NOT NULL
        '''), {'cutoff': cutoff})

        stuck = result.fetchall()
        if not stuck:
            print("No stuck uploads found")
            return 0

        print(f"Found {len(stuck)} stuck upload(s)")
        recovered = 0

        for row in stuck:
            model_id, name, local_path, s3_key, user_id = row
            print(f"  Recovering: {name} ({model_id})")

            # Check if local file exists
            if not local_path or not os.path.exists(local_path):
                print(f"    Local file missing, marking as failed")
                await db.execute(text('''
                    UPDATE video_models
                    SET status = 'failed', processing_stage = 'failed',
                        error_message = 'Local video file not found'
                    WHERE id = :id
                '''), {'id': str(model_id)})
                await db.commit()
                continue

            # Check if already on S3
            exists = await s3_service.file_exists(s3_key)
            if exists:
                print(f"    Already on S3, updating status")
                await db.execute(text('''
                    UPDATE video_models
                    SET status = 'pending', processing_stage = 'pending',
                        progress_percent = 10
                    WHERE id = :id
                '''), {'id': str(model_id)})
                await db.commit()
                recovered += 1
                continue

            # Upload to S3
            print(f"    Uploading to S3: {s3_key}")
            success = await s3_service.upload_file(local_path, s3_key)

            if success:
                print(f"    Upload successful")
                await db.execute(text('''
                    UPDATE video_models
                    SET status = 'pending', processing_stage = 'pending',
                        progress_percent = 10
                    WHERE id = :id
                '''), {'id': str(model_id)})
                await db.commit()
                recovered += 1
            else:
                print(f"    Upload failed")
                await db.execute(text('''
                    UPDATE video_models
                    SET status = 'failed', processing_stage = 'failed',
                        error_message = 'S3 upload failed during recovery'
                    WHERE id = :id
                '''), {'id': str(model_id)})
                await db.commit()

        print(f"Recovered {recovered} upload(s)")
        return recovered


async def run_daemon(interval: int):
    """
    Run as a daemon that periodically checks running jobs.

    Args:
        interval: Seconds between checks
    """
    import signal
    import sys

    print(f"Starting daemon mode, checking every {interval} seconds...")
    print("Press Ctrl+C to stop")

    running = True

    def signal_handler(signum, frame):
        nonlocal running
        print("\nShutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while running:
        try:
            # Check running jobs
            finalized = await check_running_jobs()

            # Show brief status
            from app.db import get_db_session
            from app.services.avatar_job import avatar_job_service

            async with get_db_session() as db:
                running_count = await avatar_job_service.get_running_count(db)
                pending_count = await avatar_job_service.get_pending_count(db)

            print(
                f"[{asyncio.get_event_loop().time():.0f}] "
                f"Finalized: {finalized}, Running: {running_count}, Pending: {pending_count}"
            )

            # Sleep for interval
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in daemon loop: {e}")
            await asyncio.sleep(interval)


async def main():
    parser = argparse.ArgumentParser(
        description="Process pending avatar generation jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show queue status only (no processing)",
    )
    parser.add_argument(
        "--reset-failed",
        action="store_true",
        help="Reset all failed jobs to pending before processing",
    )
    parser.add_argument(
        "--reset-processing",
        action="store_true",
        help="Force reset all processing jobs to failed status (use when jobs are stuck)",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        help="Reset and process a specific job by ID",
    )
    parser.add_argument(
        "--check-running",
        action="store_true",
        help="Check running jobs for completion (poll detached processes)",
    )
    parser.add_argument(
        "--recover-uploads",
        action="store_true",
        help="Recover stuck uploads (retry S3 upload for stuck 'uploading' models)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon that periodically checks running jobs",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Interval in seconds between checks in daemon mode (default: 30)",
    )

    args = parser.parse_args()

    # Show status
    pending = await show_status()

    if args.status:
        # Status only, don't process
        return

    # Daemon mode
    if args.daemon:
        await run_daemon(args.interval)
        return

    # Recover stuck uploads
    if args.recover_uploads:
        print("\nRecovering stuck uploads...")
        await recover_stuck_uploads()
        print("\nFinal status:")
        await show_status()
        return

    # Check running jobs
    if args.check_running:
        print("\nChecking running jobs for completion...")
        await check_running_jobs()
        print("\nFinal status:")
        await show_status()
        return

    # Reset stuck processing jobs
    if args.reset_processing:
        print("\nForce resetting stuck processing jobs...")
        await reset_processing_jobs()
        print("\nFinal status:")
        await show_status()
        return

    # Reset specific job if requested
    if args.job_id:
        job_uuid = UUID(args.job_id)
        await reset_specific_job(job_uuid)
        pending = await show_status()

    # Reset failed jobs if requested
    if args.reset_failed:
        await reset_failed_jobs()
        pending = await show_status()

    # Process pending jobs
    if pending > 0:
        print("\nProcessing pending jobs...")
        await process_pending_jobs()
        print("\nFinal status:")
        await show_status()
    else:
        print("\nNo pending jobs to process")


if __name__ == "__main__":
    asyncio.run(main())
