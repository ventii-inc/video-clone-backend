"""Progress tracking service for video model processing.

Progress ranges:
- 0-10%:   Uploading to S3
- 10-20%:  Preparing (downloading, setting up for processing)
- 20-80%:  LiveTalking avatar training (asymptotic, never reaches 80% on its own)
- 80-100%: Finalizing (uploading results) - only reaches 100% on completion
"""

import logging
import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.video_model import VideoModel, ProcessingStage

logger = logging.getLogger(__name__)

# Progress range constants
PROGRESS_UPLOAD_START = 0
PROGRESS_UPLOAD_END = 10
PROGRESS_PREPARE_START = 10
PROGRESS_PREPARE_END = 20
PROGRESS_TRAINING_START = 20
PROGRESS_TRAINING_END = 80  # Never actually reaches this during training
PROGRESS_FINALIZE_START = 80
PROGRESS_FINALIZE_END = 100

# Expected training time in seconds (used for asymptotic calculation)
# This should be tuned based on actual training times
EXPECTED_TRAINING_TIME_SECONDS = 300  # 5 minutes expected


def calculate_expected_generation_time(text: str) -> float:
    """
    Calculate expected video generation time based on word count.

    Formula:
    - Base time for first 200 words: 240 seconds (4 minutes)
    - Each additional 100 words: +30 seconds

    Progress 80-100% is reserved for actual completion only.

    Examples:
        50 words  -> 240s (4 min)
        200 words -> 240s (4 min)
        300 words -> 270s (4.5 min)
        500 words -> 330s (5.5 min)
        1000 words -> 480s (8 min)

    Args:
        text: The input text for video generation

    Returns:
        Expected generation time in seconds
    """
    word_count = len(text.split())

    # Base time for first 200 words: 4 minutes
    base_seconds = 240.0

    # Additional time for words beyond 200: 30 seconds per 100 words
    if word_count > 200:
        extra_words = word_count - 200
        additional_seconds = (extra_words / 100) * 30
    else:
        additional_seconds = 0.0

    return base_seconds + additional_seconds


def calculate_training_progress(
    elapsed_seconds: float,
    expected_seconds: float = EXPECTED_TRAINING_TIME_SECONDS,
    start_percent: int = PROGRESS_TRAINING_START,
    max_percent: int = PROGRESS_TRAINING_END - 2,  # Cap at 78%, never reach 80%
) -> int:
    """
    Calculate asymptotic progress for the training phase.

    Uses an exponential decay formula that slows down as it approaches the max.
    The progress will move quickly at first, then slow down significantly,
    never actually reaching the max_percent until training completes.

    Args:
        elapsed_seconds: Time elapsed since training started
        expected_seconds: Expected total training time (for scaling)
        start_percent: Starting percentage (20%)
        max_percent: Maximum percentage to reach (78%, leaving room for 80-100% finalization)

    Returns:
        Progress percentage between start_percent and max_percent
    """
    if elapsed_seconds <= 0:
        return start_percent

    # Asymptotic formula: progress = max * (1 - e^(-k*t))
    # Where k is tuned so that at expected_seconds, we reach ~63% of the range
    k = 1.0 / expected_seconds

    # Calculate progress within the training range (0 to 1)
    normalized_progress = 1 - math.exp(-k * elapsed_seconds)

    # Scale to the actual percentage range
    range_size = max_percent - start_percent
    progress = start_percent + int(range_size * normalized_progress)

    # Ensure we never exceed max_percent
    return min(progress, max_percent)


async def update_video_model_progress(
    db: AsyncSession,
    model_id: UUID,
    stage: ProcessingStage,
    progress_percent: Optional[int] = None,
) -> None:
    """
    Update the progress of a video model.

    Args:
        db: Database session
        model_id: Video model ID
        stage: Current processing stage
        progress_percent: Optional explicit progress percentage. If not provided,
                         will be inferred from the stage.
    """
    # Determine progress percent from stage if not explicitly provided
    if progress_percent is None:
        progress_percent = _get_stage_progress(stage)

    stmt = (
        update(VideoModel)
        .where(VideoModel.id == model_id)
        .values(
            processing_stage=stage.value,
            progress_percent=progress_percent,
        )
    )

    await db.execute(stmt)
    await db.commit()

    logger.debug(f"Updated video model {model_id} progress: stage={stage.value}, percent={progress_percent}")


def _get_stage_progress(stage: ProcessingStage) -> int:
    """Get the default progress percentage for a stage."""
    stage_progress = {
        ProcessingStage.PENDING: 0,
        ProcessingStage.UPLOADING: PROGRESS_UPLOAD_START,
        ProcessingStage.PREPARING: PROGRESS_PREPARE_START,
        ProcessingStage.TRAINING: PROGRESS_TRAINING_START,
        ProcessingStage.FINALIZING: PROGRESS_FINALIZE_START,
        ProcessingStage.COMPLETED: 100,
        ProcessingStage.FAILED: 0,  # Keep last progress on failure
    }
    return stage_progress.get(stage, 0)


class VideoModelProgressTracker:
    """
    Context manager for tracking video model processing progress.

    Automatically updates progress at different stages and handles
    the asymptotic training progress calculation.

    Usage:
        async with VideoModelProgressTracker(db, model_id) as tracker:
            await tracker.set_uploading()
            # ... upload file ...
            await tracker.set_uploading_progress(50)  # 5% (half of 0-10%)
            # ... finish upload ...
            await tracker.set_preparing()
            # ... prepare for training ...
            await tracker.start_training()
            # ... training runs, progress auto-calculated ...
            await tracker.set_finalizing()
            # ... upload results ...
            await tracker.set_completed()
    """

    def __init__(self, db: AsyncSession, model_id: UUID):
        self.db = db
        self.model_id = model_id
        self.training_started_at: Optional[datetime] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Don't change progress on exception - let caller handle failure
        pass

    async def _update(self, stage: ProcessingStage, progress: Optional[int] = None) -> None:
        """Update progress in database."""
        await update_video_model_progress(self.db, self.model_id, stage, progress)

    async def set_uploading(self) -> None:
        """Set stage to uploading (0-10%)."""
        await self._update(ProcessingStage.UPLOADING, PROGRESS_UPLOAD_START)

    async def set_uploading_progress(self, sub_percent: int) -> None:
        """
        Set upload progress within the uploading stage.

        Args:
            sub_percent: Progress within upload stage (0-100)
        """
        # Map 0-100 to 0-10%
        progress = PROGRESS_UPLOAD_START + int((PROGRESS_UPLOAD_END - PROGRESS_UPLOAD_START) * sub_percent / 100)
        await self._update(ProcessingStage.UPLOADING, progress)

    async def set_preparing(self) -> None:
        """Set stage to preparing (10-20%)."""
        await self._update(ProcessingStage.PREPARING, PROGRESS_PREPARE_START)

    async def set_preparing_progress(self, sub_percent: int) -> None:
        """
        Set prepare progress within the preparing stage.

        Args:
            sub_percent: Progress within prepare stage (0-100)
        """
        # Map 0-100 to 10-20%
        progress = PROGRESS_PREPARE_START + int((PROGRESS_PREPARE_END - PROGRESS_PREPARE_START) * sub_percent / 100)
        await self._update(ProcessingStage.PREPARING, progress)

    async def start_training(self) -> None:
        """Start training stage (20-80%)."""
        self.training_started_at = datetime.utcnow()
        await self._update(ProcessingStage.TRAINING, PROGRESS_TRAINING_START)

    async def update_training_progress(self) -> int:
        """
        Update training progress based on elapsed time.

        Call this periodically during training to update progress.
        Uses asymptotic formula that never reaches 80%.

        Returns:
            Current progress percentage
        """
        if self.training_started_at is None:
            self.training_started_at = datetime.utcnow()

        elapsed = (datetime.utcnow() - self.training_started_at).total_seconds()
        progress = calculate_training_progress(elapsed)
        await self._update(ProcessingStage.TRAINING, progress)
        return progress

    async def set_finalizing(self) -> None:
        """Set stage to finalizing (80-100%)."""
        await self._update(ProcessingStage.FINALIZING, PROGRESS_FINALIZE_START)

    async def set_finalizing_progress(self, sub_percent: int) -> None:
        """
        Set finalize progress within the finalizing stage.

        Args:
            sub_percent: Progress within finalize stage (0-100)
        """
        # Map 0-100 to 80-99% (100% only on completed)
        progress = PROGRESS_FINALIZE_START + int((PROGRESS_FINALIZE_END - 1 - PROGRESS_FINALIZE_START) * sub_percent / 100)
        await self._update(ProcessingStage.FINALIZING, progress)

    async def set_completed(self) -> None:
        """Set stage to completed (100%)."""
        await self._update(ProcessingStage.COMPLETED, 100)

    async def set_failed(self, keep_progress: bool = True) -> None:
        """
        Set stage to failed.

        Args:
            keep_progress: If True, keeps current progress. If False, resets to 0.
        """
        progress = None if keep_progress else 0
        await self._update(ProcessingStage.FAILED, progress)
