"""
Background scheduler service for periodic tasks.

This service runs background tasks on a schedule within the FastAPI application,
eliminating the need for external cron jobs.
"""

import asyncio
import os
from datetime import datetime
from typing import Optional

from app.utils import logger


class SchedulerService:
    """
    Background scheduler that runs periodic tasks.

    Currently handles:
    - Checking running avatar jobs for completion (polls detached CLI processes)
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Check interval in seconds (default: 10 seconds)
        self.check_interval = int(os.getenv("AVATAR_JOB_CHECK_INTERVAL", "10"))

    async def start(self):
        """Start the background scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_scheduler())
        logger.info(
            f"Background scheduler started (check_interval={self.check_interval}s)"
        )

    async def stop(self):
        """Stop the background scheduler gracefully."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Background scheduler stopped")

    async def _run_scheduler(self):
        """Main scheduler loop."""
        # Wait a bit before starting to let the app fully initialize
        await asyncio.sleep(5)

        while self._running:
            try:
                await self._check_avatar_jobs()
            except Exception as e:
                logger.error(f"Scheduler error in avatar job check: {e}", exc_info=True)

            # Wait for next check interval
            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break

    async def _check_avatar_jobs(self):
        """Check running avatar jobs for completion."""
        from app.db import get_db_session
        from app.services.avatar_job import avatar_job_service

        try:
            async with get_db_session() as db:
                # Check running jobs and finalize completed ones
                finalized = await avatar_job_service.check_running_jobs(db)

                if finalized > 0:
                    logger.info(f"Scheduler: Finalized {finalized} avatar job(s)")

                # Also try to start pending jobs if there's capacity
                started = await avatar_job_service.process_pending_jobs(db)

                if started > 0:
                    logger.info(f"Scheduler: Started {started} pending avatar job(s)")

        except Exception as e:
            logger.error(f"Error checking avatar jobs: {e}", exc_info=True)


# Global scheduler instance
scheduler_service = SchedulerService()
