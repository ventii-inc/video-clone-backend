"""
Model Progress Calculation Service

This module provides simulated progress tracking for model generation (video/voice).
Since we don't have real-time progress from the training process, we estimate progress
based on elapsed time since processing started.

LOGIC:
-------
1. We assume model generation takes approximately 10 minutes (600 seconds)
2. Progress is calculated linearly based on elapsed time: (elapsed / total) * 100
3. Progress is CAPPED at 80% while status is "processing" to prevent showing 100% prematurely
4. Only when the DB status is "completed" do we return 100%
5. For "failed" status, we return the last known progress (capped at the failure point)
6. For "pending"/"uploading" status, progress stays at the initial value (0-10%)

This approach ensures:
- Users see steady progress updates during polling (every 3-4 seconds)
- Progress never shows 100% until the model is actually ready
- Failed models show where they failed in the pipeline

STAGE MAPPING:
--------------
Based on elapsed time, we also estimate the current processing stage:
- 0-10%:   "uploading" / "analyzing"
- 10-30%:  "preparing" / "extracting"
- 30-80%:  "training"
- 80-99%:  "finalizing"
- 100%:    "completed"
"""

from datetime import datetime
from typing import Tuple


# Configuration: Estimated total processing time in seconds
VIDEO_MODEL_ESTIMATED_DURATION = 600  # 10 minutes for video model (avatar training)
VOICE_MODEL_ESTIMATED_DURATION = 120  # 2 minutes for voice model (voice cloning)
VIDEO_GENERATION_ESTIMATED_DURATION = 180  # 3 minutes for video generation (TTS + lip-sync)

# Maximum progress to show while still processing (prevents showing 100% too early)
MAX_PROCESSING_PROGRESS = 80


def calculate_video_model_progress(
    status: str,
    processing_started_at: datetime | None,
    stored_progress: int = 0,
    stored_stage: str = "pending",
) -> Tuple[int, str]:
    """
    Calculate simulated progress for video model generation.

    Args:
        status: Current model status (pending, uploading, processing, completed, failed)
        processing_started_at: When processing started (from DB)
        stored_progress: Progress value stored in DB (used as minimum)
        stored_stage: Processing stage stored in DB

    Returns:
        Tuple of (progress_percent, processing_stage)

    Logic:
        - For completed: Always return (100, "completed")
        - For failed: Return stored progress or estimated progress at failure
        - For processing: Calculate based on elapsed time, capped at 80%
        - For pending/uploading: Return stored progress (0-10%)
    """
    # Completed models always show 100%
    if status == "completed":
        return 100, "completed"

    # Failed models show where they failed
    if status == "failed":
        # Use stored progress if available, otherwise estimate based on time
        if stored_progress > 0:
            return stored_progress, stored_stage
        return _estimate_progress_at_failure(processing_started_at, VIDEO_MODEL_ESTIMATED_DURATION)

    # Pending or uploading - use stored values (early stage)
    if status in ("pending", "uploading"):
        return stored_progress, stored_stage

    # Processing - calculate time-based progress
    if status == "processing":
        if not processing_started_at:
            # No start time recorded, return stored progress
            return max(stored_progress, 10), stored_stage or "preparing"

        progress, stage = _calculate_time_based_progress(
            processing_started_at,
            VIDEO_MODEL_ESTIMATED_DURATION,
            model_type="video"
        )

        # Use maximum of stored and calculated progress (never go backwards)
        return max(progress, stored_progress), stage

    # Unknown status - return stored values
    return stored_progress, stored_stage


def calculate_voice_model_progress(
    status: str,
    processing_started_at: datetime | None,
    stored_progress: int = 0,
    stored_stage: str = "pending",
) -> Tuple[int, str]:
    """
    Calculate simulated progress for voice model generation.

    Args:
        status: Current model status (pending, uploading, processing, completed, failed)
        processing_started_at: When processing started (from DB)
        stored_progress: Progress value stored in DB (used as minimum)
        stored_stage: Processing stage stored in DB

    Returns:
        Tuple of (progress_percent, processing_stage)

    Logic:
        - Same as video model but with shorter estimated duration (2 minutes)
    """
    # Completed models always show 100%
    if status == "completed":
        return 100, "completed"

    # Failed models show where they failed
    if status == "failed":
        if stored_progress > 0:
            return stored_progress, stored_stage
        return _estimate_progress_at_failure(processing_started_at, VOICE_MODEL_ESTIMATED_DURATION)

    # Pending or uploading - use stored values (early stage)
    if status in ("pending", "uploading"):
        return stored_progress, stored_stage

    # Processing - calculate time-based progress
    if status == "processing":
        if not processing_started_at:
            return max(stored_progress, 10), stored_stage or "analyzing"

        progress, stage = _calculate_time_based_progress(
            processing_started_at,
            VOICE_MODEL_ESTIMATED_DURATION,
            model_type="voice"
        )

        return max(progress, stored_progress), stage

    return stored_progress, stored_stage


def _calculate_time_based_progress(
    started_at: datetime,
    estimated_duration: int,
    model_type: str = "video"
) -> Tuple[int, str]:
    """
    Calculate progress based on elapsed time since processing started.

    Progress is calculated linearly but capped at MAX_PROCESSING_PROGRESS (80%)
    to prevent showing 100% before the model is actually completed in the DB.

    Args:
        started_at: When processing started
        estimated_duration: Estimated total duration in seconds
        model_type: "video" or "voice" (affects stage names)

    Returns:
        Tuple of (progress_percent, processing_stage)
    """
    now = datetime.utcnow()
    elapsed_seconds = (now - started_at).total_seconds()

    # Calculate raw progress percentage
    raw_progress = (elapsed_seconds / estimated_duration) * 100

    # Cap at MAX_PROCESSING_PROGRESS while still processing
    # This ensures we never show 100% until DB status is "completed"
    progress = min(int(raw_progress), MAX_PROCESSING_PROGRESS)

    # Ensure progress is at least 10% once processing has started
    progress = max(progress, 10)

    # Determine stage based on progress
    stage = _get_stage_for_progress(progress, model_type)

    return progress, stage


def _get_stage_for_progress(progress: int, model_type: str = "video") -> str:
    """
    Map progress percentage to processing stage name.

    Stages are designed to match the actual pipeline:
    - Early stages (0-30%): Preparation/analysis
    - Middle stages (30-80%): Actual training/processing
    - Late stages (80-100%): Finalization/upload

    Args:
        progress: Current progress percentage
        model_type: "video" or "voice"

    Returns:
        Processing stage string
    """
    if progress >= 100:
        return "completed"

    if model_type == "video":
        # Video model stages (avatar training)
        if progress < 10:
            return "uploading"
        elif progress < 20:
            return "preparing"
        elif progress < 80:
            return "training"
        else:
            return "finalizing"
    else:
        # Voice model stages (voice cloning)
        if progress < 10:
            return "uploading"
        elif progress < 30:
            return "analyzing"
        elif progress < 60:
            return "extracting"
        elif progress < 80:
            return "training"
        else:
            return "finalizing"


def _estimate_progress_at_failure(
    started_at: datetime | None,
    estimated_duration: int
) -> Tuple[int, str]:
    """
    Estimate what progress was when the model failed.

    This helps show users approximately where in the pipeline
    the failure occurred.

    Args:
        started_at: When processing started
        estimated_duration: Estimated total duration

    Returns:
        Tuple of (progress_percent, processing_stage)
    """
    if not started_at:
        return 0, "failed"

    now = datetime.utcnow()
    elapsed_seconds = (now - started_at).total_seconds()

    # Calculate what progress would have been at failure
    raw_progress = (elapsed_seconds / estimated_duration) * 100
    progress = min(int(raw_progress), 99)  # Cap at 99% for failed
    progress = max(progress, 0)

    return progress, "failed"


def calculate_generated_video_progress(
    status: str,
    processing_started_at: datetime | None,
    stored_progress: int = 0,
    stored_stage: str = "queued",
    input_text: str | None = None,
) -> Tuple[int, str]:
    """
    Calculate simulated progress for video generation (TTS + lip-sync).

    Provides smooth 1% increments based on elapsed time, capped at 78%
    to leave room for actual completion at 100%.

    Args:
        status: Current generation status (queued, processing, completed, failed)
        processing_started_at: When processing started (from DB)
        stored_progress: Progress value stored in DB (used as minimum)
        stored_stage: Processing stage stored in DB
        input_text: Optional input text to estimate duration based on word count

    Returns:
        Tuple of (progress_percent, processing_stage)

    Progress Timeline (slower, irregular intervals):
        - 0-10s:    1% → 5%    (preparing) - slow increment
        - 10s+:     5% → 78%   (generating) - irregular 1-3% bumps every 7-30s
        - 220s+:    78%        (capped until completion)
    """
    # Completed videos always show 100%
    if status == "completed":
        return 100, "completed"

    # Failed videos show where they failed
    if status == "failed":
        if stored_progress > 0:
            return stored_progress, stored_stage
        return _estimate_progress_at_failure(
            processing_started_at, VIDEO_GENERATION_ESTIMATED_DURATION
        )

    # Queued - use stored values (early stage)
    if status == "queued":
        return stored_progress, stored_stage

    # Processing - calculate smooth time-based progress
    if status == "processing":
        if not processing_started_at:
            return max(stored_progress, 1), stored_stage or "preparing"

        # Calculate estimated duration based on text length if provided
        estimated_duration = _estimate_video_generation_duration(input_text)

        progress, stage = _calculate_smooth_video_generation_progress(
            processing_started_at,
            estimated_duration,
        )

        # Never go backwards - use max of stored and calculated
        return max(progress, stored_progress), stage

    # Unknown status - return stored values
    return stored_progress, stored_stage


def _estimate_video_generation_duration(input_text: str | None) -> int:
    """
    Estimate video generation duration based on input text length.

    Args:
        input_text: The text to be converted to speech

    Returns:
        Estimated duration in seconds

    Formula:
        - Base: 120 seconds for up to 100 words
        - Additional: +20 seconds per 50 words beyond 100
        - Maximum: 600 seconds (10 minutes)
    """
    if not input_text:
        return VIDEO_GENERATION_ESTIMATED_DURATION  # Default 180 seconds

    word_count = len(input_text.split())

    if word_count <= 100:
        return 120  # 2 minutes for short texts

    # Add time for longer texts
    additional_words = word_count - 100
    additional_time = (additional_words // 50) * 20

    return min(120 + additional_time, 600)


def _calculate_smooth_video_generation_progress(
    started_at: datetime,
    estimated_duration: int,
) -> Tuple[int, str]:
    """
    Calculate progress with slower, irregular increments for natural feel.

    Progress phases:
        Phase 1 (0-10s):  1% → 5%   - Preparing (slow)
        Phase 2 (10s+):   5% → 78%  - Generating (irregular intervals)

    Uses predefined time buckets with varying intervals and increment sizes
    to create natural-feeling progress that appears random but is deterministic.

    Args:
        started_at: When processing started
        estimated_duration: Estimated total duration in seconds (unused, kept for API)

    Returns:
        Tuple of (progress_percent, processing_stage)
    """
    now = datetime.utcnow()
    elapsed = (now - started_at).total_seconds()

    # Phase 1: 0-10 seconds → 1% to 5% (preparing)
    if elapsed < 10:
        # Slow increment: ~0.4% per second
        progress = 1 + int(elapsed * 0.4)
        return min(progress, 5), "preparing"

    # Phase 2: 10+ seconds → 5% to 78% (generating)
    # Use irregular time buckets for natural-feeling progression
    # Each tuple: (elapsed_since_phase2_start, progress_percent)
    phase_elapsed = elapsed - 10

    # Irregular progression buckets: (time_threshold, progress_at_threshold)
    # Creates varying intervals (7s, 8s, 10s, 15s, etc.) and increments (2%, 3%, 5%, etc.)
    PROGRESS_BUCKETS = [
        (0, 5),       # Start at 5%
        (8, 7),       # +2% over 8s
        (15, 9),      # +2% over 7s
        (25, 12),     # +3% over 10s
        (35, 15),     # +3% over 10s
        (50, 20),     # +5% over 15s
        (70, 27),     # +7% over 20s
        (95, 35),     # +8% over 25s
        (120, 45),    # +10% over 25s
        (150, 55),    # +10% over 30s
        (180, 65),    # +10% over 30s
        (220, 72),    # +7% over 40s
        (999999, 78), # Cap at 78%
    ]

    # Find current bucket and interpolate within it
    prev_time, prev_progress = 0, 5
    for bucket_time, bucket_progress in PROGRESS_BUCKETS:
        if phase_elapsed < bucket_time:
            # Interpolate within this bucket
            bucket_duration = bucket_time - prev_time
            bucket_increment = bucket_progress - prev_progress
            time_in_bucket = phase_elapsed - prev_time
            progress = prev_progress + int((time_in_bucket / bucket_duration) * bucket_increment)
            return min(progress, 78), "generating"
        prev_time, prev_progress = bucket_time, bucket_progress

    # Fallback: cap at 78%
    return 78, "generating"
