#!/usr/bin/env python3
"""
Process pending avatar generation jobs.

Usage:
    # Process all pending jobs
    ENV=staging uv run python scripts/process_avatar_jobs.py

    # Reset failed jobs and process all
    ENV=staging uv run python scripts/process_avatar_jobs.py --reset-failed

    # Show queue status only (no processing)
    ENV=staging uv run python scripts/process_avatar_jobs.py --status

    # Reset and process a specific job by ID
    ENV=staging uv run python scripts/process_avatar_jobs.py --job-id <uuid>
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
    from app.db import get_db_session
    from app.services.avatar_job import avatar_job_service

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
        "--job-id",
        type=str,
        help="Reset and process a specific job by ID",
    )

    args = parser.parse_args()

    # Show status
    pending = await show_status()

    if args.status:
        # Status only, don't process
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
