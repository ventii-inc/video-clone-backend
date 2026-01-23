"""AI service for video/voice model processing and video generation.

Supports two modes:
- CLI mode: Uses local LiveTalking subprocess for avatar/video generation
- Mock mode: Simulates processing for development/testing

Set LIVETALKING_MODE=cli in environment to use CLI mode.
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.video_model import VideoModel, ModelStatus as VideoModelStatus
from app.models.voice_model import VoiceModel, ModelStatus as VoiceModelStatus
from app.models.generated_video import GeneratedVideo, GenerationStatus, VideoGenerationStage
from app.services.progress import calculate_training_progress
from app.db import get_db_session
from app.models.user import User
from app.services.s3 import s3_service
from app.services.email import VideoGenerationCompletionData, get_email_service
from app.services.usage_service import usage_service
from app.services.video import video_service, get_video_duration
from app.services.audio import audio_service, get_audio_duration
from app.services.livetalking import livetalking_cli_service
from app.services.livetalking.livetalking_config import LiveTalkingSettings
from app.services.fish_audio import fish_audio_service

logger = logging.getLogger(__name__)


class AIService:
    """AI service for video/voice model processing and video generation.

    Supports two modes based on LIVETALKING_MODE:
    - "cli": Uses local LiveTalking subprocess (same server deployment)
    - "api"/"mock": Uses mock implementation for development/testing

    In full production with remote LiveTalking, integrate with:
    - Video clone model training API
    - Voice clone model training API
    - Lip-sync video generation API
    """

    # Simulated processing times (in seconds) for mock mode
    VIDEO_MODEL_PROCESSING_TIME = 5  # Real: 5-30 minutes
    VOICE_MODEL_PROCESSING_TIME = 3  # Real: 2-10 minutes
    VIDEO_GENERATION_TIME = 4  # Real: varies by text length

    # Expected video generation time for progress calculation (seconds)
    EXPECTED_VIDEO_GENERATION_TIME = 60  # Typical video generation takes ~60 seconds

    def _calculate_minutes_from_duration(self, duration_seconds: int | None) -> int:
        """Calculate billable minutes from video duration in seconds.

        Rounds up to nearest minute, minimum 1 minute.
        """
        if not duration_seconds or duration_seconds <= 0:
            return 1  # Minimum 1 minute charge
        # Round up to nearest minute
        return max(1, (duration_seconds + 59) // 60)

    async def _send_video_completion_email(
        self,
        video: GeneratedVideo,
        db: AsyncSession,
    ) -> None:
        """Send email notification when video generation completes."""
        try:
            # Fetch user for email notification
            user_result = await db.execute(
                select(User).where(User.id == video.user_id)
            )
            user = user_result.scalar_one_or_none()

            if user and user.email:
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
                logger.info(f"Sent video completion email to {user.email} for video {video.id}")
        except Exception as e:
            logger.warning(f"Failed to send video completion email for video {video.id}: {e}")

    async def _deduct_credits_for_video(
        self,
        video: GeneratedVideo,
        db: AsyncSession,
    ) -> None:
        """Deduct credits based on actual video duration after generation completes."""
        minutes_used = self._calculate_minutes_from_duration(video.duration_seconds)

        try:
            await usage_service.deduct_credits(video.user_id, minutes_used, db)
            video.credits_used = minutes_used
            await db.commit()
            logger.info(
                f"Deducted {minutes_used} minutes for video {video.id} "
                f"(duration: {video.duration_seconds}s)"
            )
        except ValueError as e:
            # Insufficient credits - log but don't fail the video
            # Video was already generated, so we still charge what we can
            logger.warning(f"Credit deduction issue for video {video.id}: {e}")
            video.credits_used = minutes_used
            await db.commit()

    def _get_mode(self) -> str:
        """Get execution mode from settings."""
        settings = LiveTalkingSettings()
        return settings.LIVETALKING_MODE

    async def process_video_model(
        self,
        model_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Process a video model (mock implementation).

        In production, this would:
        1. Download source video from S3
        2. Trim to 60 seconds if longer (for training videos)
        3. Send to AI API for face/motion extraction
        4. Store trained model data
        5. Generate thumbnail
        """
        logger.info(f"Starting video model processing: {model_id}")

        # Get the model
        result = await db.execute(
            select(VideoModel).where(VideoModel.id == model_id)
        )
        model = result.scalar_one_or_none()

        if not model:
            logger.error(f"Video model not found: {model_id}")
            return

        # Update status to processing
        model.status = VideoModelStatus.PROCESSING.value
        model.processing_started_at = datetime.utcnow()
        await db.commit()

        # Process training video: download, trim if needed, re-upload
        try:
            await self._process_training_video(model, db)
        except Exception as e:
            logger.error(f"Failed to process training video: {e}")
            model.status = VideoModelStatus.FAILED.value
            model.error_message = f"Video processing failed: {str(e)}"
            await db.commit()
            return

        # Simulate AI processing time
        await asyncio.sleep(self.VIDEO_MODEL_PROCESSING_TIME)

        # Mock success - update model with processed data paths
        model.status = VideoModelStatus.COMPLETED.value
        model.processing_completed_at = datetime.utcnow()
        # Set S3 key for avatar TAR file
        model.model_data_key = f"avatars/{model.user_id}/{model_id}.tar"
        model.thumbnail_url = f"https://picsum.photos/seed/{model_id}/320/180"  # Mock thumbnail

        await db.commit()
        logger.info(f"Video model processing completed: {model_id}")

    async def _process_training_video(
        self,
        model: VideoModel,
        db: AsyncSession,
    ) -> None:
        """
        Download, trim (if needed), and re-upload training video.

        Training videos are trimmed to a maximum of 60 seconds.
        """
        if not model.source_video_key:
            logger.warning(f"No source video key for model {model.id}")
            return

        # Create temp directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Determine file extension from s3 key
            ext = os.path.splitext(model.source_video_key)[1] or ".mp4"
            input_path = os.path.join(temp_dir, f"input{ext}")
            output_path = os.path.join(temp_dir, f"output{ext}")

            # Download video from S3
            logger.info(f"Downloading video from S3: {model.source_video_key}")
            success = await s3_service.download_file(model.source_video_key, input_path)

            if not success:
                raise ValueError(f"Failed to download video from S3: {model.source_video_key}")

            # Process (trim if needed)
            try:
                final_path, duration, was_trimmed = await video_service.process_training_video(
                    input_path, output_path
                )

                # Update duration on model
                model.duration_seconds = int(duration)

                if was_trimmed:
                    logger.info(f"Video was trimmed to {duration}s, re-uploading to S3")

                    # Get file size of trimmed video
                    model.file_size_bytes = os.path.getsize(final_path)

                    # Re-upload trimmed video to same S3 key
                    content_type = s3_service._get_content_type(final_path)
                    await s3_service.upload_file(
                        final_path,
                        model.source_video_key,
                        content_type=content_type,
                    )
                    logger.info(f"Trimmed video uploaded to S3: {model.source_video_key}")
                else:
                    logger.info(f"Video duration is {duration}s, no trimming needed")
                    # Update file size from original
                    model.file_size_bytes = os.path.getsize(input_path)

                await db.commit()

            except ValueError as e:
                # If trimming fails but we can still get duration, continue
                duration = await get_video_duration(input_path)
                if duration:
                    model.duration_seconds = int(duration)
                    model.file_size_bytes = os.path.getsize(input_path)
                    await db.commit()
                    logger.warning(f"Trim failed but continuing with original video: {e}")
                else:
                    raise

    async def process_voice_model(
        self,
        model_id: UUID,
        db: AsyncSession,
        local_audio_path: str | None = None,
    ) -> None:
        """Process a voice model using Fish Audio voice cloning.

        Steps:
        1. Download source audio from S3 (or use local file if provided)
        2. Trim to 60 seconds if longer
        3. Send to Fish Audio API for voice cloning
        4. Store the Fish Audio model ID for TTS generation

        Args:
            model_id: Voice model ID to process
            db: Database session
            local_audio_path: Optional path to local audio file (skips S3 download)
        """
        logger.info(f"Starting voice model processing: {model_id}")

        # Get the model
        result = await db.execute(
            select(VoiceModel).where(VoiceModel.id == model_id)
        )
        model = result.scalar_one_or_none()

        if not model:
            logger.error(f"Voice model not found: {model_id}")
            return

        # Update status to processing
        model.status = VoiceModelStatus.PROCESSING.value
        model.processing_started_at = datetime.utcnow()
        await db.commit()

        # Check if Fish Audio is configured
        if not fish_audio_service.is_configured():
            logger.warning("Fish Audio not configured, using mock mode")
            await self._process_voice_model_mock(model, db)
            return

        try:
            # Process training audio: download (or use local file), trim if needed, re-upload
            await self._process_training_audio(model, db, local_audio_path=local_audio_path)

            # Get presigned URL for the (possibly trimmed) source audio
            if not model.source_audio_key:
                raise ValueError("No source audio key found")

            audio_url = await s3_service.generate_presigned_url(
                model.source_audio_key, expires_in=3600
            )

            # Clone voice using Fish Audio
            clone_result = await fish_audio_service.clone_voice_from_url(
                audio_url=audio_url,
                title=model.name,
                description=f"Voice model for user {model.user_id}",
            )

            if not clone_result.success:
                raise ValueError(clone_result.error or "Voice cloning failed")

            # Store Fish Audio model ID
            model.status = VoiceModelStatus.COMPLETED.value
            model.processing_completed_at = datetime.utcnow()
            model.reference_id = clone_result.model_id  # Store Fish Audio model ID

            await db.commit()
            logger.info(
                f"Voice model processing completed: {model_id}, "
                f"fish_audio_id={clone_result.model_id}"
            )

        except Exception as e:
            logger.error(f"Voice model processing failed: {e}")
            model.status = VoiceModelStatus.FAILED.value
            model.error_message = str(e)[:500]
            model.processing_completed_at = datetime.utcnow()
            await db.commit()

    async def _process_training_audio(
        self,
        model: VoiceModel,
        db: AsyncSession,
        local_audio_path: str | None = None,
    ) -> None:
        """
        Download (or use local file), trim (if needed), and re-upload training audio.

        Training audio is trimmed to a maximum of 60 seconds.

        Args:
            model: Voice model to process
            db: Database session
            local_audio_path: Optional path to local audio file (skips S3 download)
        """
        if not model.source_audio_key and not local_audio_path:
            logger.warning(f"No source audio key or local path for model {model.id}")
            return

        # Create temp directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Determine file extension from s3 key or local path
            source_path = local_audio_path or model.source_audio_key
            ext = os.path.splitext(source_path)[1] or ".wav"
            output_path = os.path.join(temp_dir, f"output{ext}")

            # Use local file if provided, otherwise download from S3
            if local_audio_path and os.path.exists(local_audio_path):
                input_path = local_audio_path
                logger.info(f"Using local audio file: {local_audio_path}")
            else:
                input_path = os.path.join(temp_dir, f"input{ext}")
                # Download audio from S3
                logger.info(f"Downloading audio from S3: {model.source_audio_key}")
                success = await s3_service.download_file(model.source_audio_key, input_path)

                if not success:
                    raise ValueError(f"Failed to download audio from S3: {model.source_audio_key}")

            # Process (trim if needed)
            try:
                final_path, duration, was_trimmed = await audio_service.process_training_audio(
                    input_path, output_path
                )

                # Update duration on model
                model.duration_seconds = int(duration)

                if was_trimmed:
                    logger.info(f"Audio was trimmed to {duration}s, re-uploading to S3")

                    # Get file size of trimmed audio
                    model.file_size_bytes = os.path.getsize(final_path)

                    # Re-upload trimmed audio to same S3 key
                    content_type = s3_service._get_content_type(final_path)
                    await s3_service.upload_file(
                        final_path,
                        model.source_audio_key,
                        content_type=content_type,
                    )
                    logger.info(f"Trimmed audio uploaded to S3: {model.source_audio_key}")
                else:
                    logger.info(f"Audio duration is {duration}s, no trimming needed")
                    # Update file size from original
                    model.file_size_bytes = os.path.getsize(input_path)

                await db.commit()

            except ValueError as e:
                # If trimming fails but we can still get duration, continue
                duration = await get_audio_duration(input_path)
                if duration:
                    model.duration_seconds = int(duration)
                    model.file_size_bytes = os.path.getsize(input_path)
                    await db.commit()
                    logger.warning(f"Trim failed but continuing with original audio: {e}")
                else:
                    raise

    async def _process_voice_model_mock(
        self,
        model: VoiceModel,
        db: AsyncSession,
    ) -> None:
        """Mock voice model processing for development."""
        await asyncio.sleep(self.VOICE_MODEL_PROCESSING_TIME)

        model.status = VoiceModelStatus.COMPLETED.value
        model.processing_completed_at = datetime.utcnow()
        model.reference_id = f"mock://fish-audio/{model.id}"

        await db.commit()
        logger.info(f"Mock voice model processing completed: {model.id}")

    async def generate_video(
        self,
        video_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Generate a video from text using clone models.

        Supports two modes:
        - CLI mode: Uses LiveTalking CLI for actual generation
        - Mock mode: Simulates processing for development

        Steps:
        1. Load video and voice clone models
        2. Generate speech audio from text (TTS)
        3. Generate lip-synced video
        4. Upload to S3
        """
        logger.info(f"Starting video generation: {video_id}")

        # Get the generated video record
        result = await db.execute(
            select(GeneratedVideo).where(GeneratedVideo.id == video_id)
        )
        video = result.scalar_one_or_none()

        if not video:
            logger.error(f"Generated video not found: {video_id}")
            return

        # Update status to processing
        video.status = GenerationStatus.PROCESSING.value
        video.processing_stage = VideoGenerationStage.PREPARING.value
        video.progress_percent = 5
        video.processing_started_at = datetime.utcnow()
        video.queue_position = None
        await db.commit()

        mode = self._get_mode()

        if mode == "cli":
            await self._generate_video_cli(video, db)
        else:
            await self._generate_video_mock(video, db)

    async def _run_video_progress_updater(
        self,
        video_id: UUID,
        expected_seconds: float = None,
    ) -> None:
        """
        Periodically update video generation progress using asymptotic formula.

        This runs concurrently with the actual generation, updating progress
        from 20% toward 78% (never reaching 80% until actual completion).
        Uses its own DB session since the main session is held during CLI.
        """
        if expected_seconds is None:
            expected_seconds = self.EXPECTED_VIDEO_GENERATION_TIME

        start_time = datetime.utcnow()

        while True:
            try:
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                # Calculate progress from 20-78% (asymptotic, slows down)
                progress = calculate_training_progress(
                    elapsed_seconds=elapsed,
                    expected_seconds=expected_seconds,
                    start_percent=20,
                    max_percent=78,  # Cap at 78%, leaving room for 80-100% on completion
                )

                # Update in DB using fresh session
                async with get_db_session() as update_db:
                    result = await update_db.execute(
                        select(GeneratedVideo).where(GeneratedVideo.id == video_id)
                    )
                    video = result.scalar_one_or_none()
                    if video and video.status == GenerationStatus.PROCESSING.value:
                        video.progress_percent = progress
                        await update_db.commit()
                        logger.debug(f"Video {video_id} progress: {progress}%")

                await asyncio.sleep(2)  # Update every 2 seconds

            except asyncio.CancelledError:
                # Task was cancelled (generation completed)
                logger.debug(f"Progress updater cancelled for video {video_id}")
                raise
            except Exception as e:
                logger.warning(f"Error updating video progress: {e}")
                await asyncio.sleep(2)  # Continue despite errors

    async def _generate_video_cli(
        self,
        video: GeneratedVideo,
        db: AsyncSession,
    ) -> None:
        """Generate video using LiveTalking CLI."""
        progress_task = None

        try:
            # Set preparing stage
            video.processing_stage = VideoGenerationStage.PREPARING.value
            video.progress_percent = 10
            await db.commit()

            # Get the video model to get avatar_id
            video_model_result = await db.execute(
                select(VideoModel).where(VideoModel.id == video.video_model_id)
            )
            video_model = video_model_result.scalar_one_or_none()

            if not video_model:
                raise ValueError("Video model not found")

            avatar_id = str(video.video_model_id)

            # Generate output path
            output_filename = f"{video.id}.mp4"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

            # Get voice model for TTS reference (if applicable)
            voice_model_result = await db.execute(
                select(VoiceModel).where(VoiceModel.id == video.voice_model_id)
            )
            voice_model = voice_model_result.scalar_one_or_none()
            ref_file = voice_model.reference_id if voice_model else None

            # Update to generating stage and start progress updater
            video.processing_stage = VideoGenerationStage.GENERATING.value
            video.progress_percent = 20
            await db.commit()

            # Start concurrent progress updater
            progress_task = asyncio.create_task(
                self._run_video_progress_updater(video.id)
            )

            # Run CLI video generation
            logger.info(f"Running CLI video generation for {video.id}")
            result = await livetalking_cli_service.generate_video(
                avatar_id=avatar_id,
                text=video.input_text,
                output_path=output_path,
                user_id=video.user_id,
                ref_file=ref_file,
                upload_to_s3=True,
            )

            # Cancel progress updater now that generation is complete
            if progress_task:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

            if not result.success:
                raise ValueError(result.error or "Video generation failed")

            # Update video record with results - COMPLETED
            video.status = GenerationStatus.COMPLETED.value
            video.processing_stage = VideoGenerationStage.COMPLETED.value
            video.processing_completed_at = datetime.utcnow()
            video.progress_percent = 100
            video.duration_seconds = int(result.duration) if result.duration else None
            video.output_video_key = result.s3_key

            # Get file size
            if os.path.exists(output_path):
                video.file_size_bytes = os.path.getsize(output_path)
                # Clean up local file
                os.remove(output_path)

            await db.commit()

            # Deduct credits based on actual video duration
            await self._deduct_credits_for_video(video, db)

            # Send email notification
            await self._send_video_completion_email(video, db)

            logger.info(f"CLI video generation completed: {video.id}")

        except Exception as e:
            # Cancel progress updater on error
            if progress_task:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

            logger.error(f"CLI video generation failed: {e}")
            video.status = GenerationStatus.FAILED.value
            video.processing_stage = VideoGenerationStage.FAILED.value
            video.error_message = str(e)[:500]
            video.processing_completed_at = datetime.utcnow()
            await db.commit()

    async def _generate_video_mock(
        self,
        video: GeneratedVideo,
        db: AsyncSession,
    ) -> None:
        """Generate video using mock implementation (for development)."""
        # Set generating stage
        video.processing_stage = VideoGenerationStage.GENERATING.value

        # Simulate progress updates
        for progress in [25, 50, 75, 100]:
            await asyncio.sleep(self.VIDEO_GENERATION_TIME / 4)
            video.progress_percent = progress
            await db.commit()

        # Calculate mock duration based on text length
        # Rough estimate: ~150 characters per minute of speech
        text_length = len(video.input_text)
        estimated_duration = max(10, int(text_length / 2.5))  # Minimum 10 seconds

        # Mock success
        video.status = GenerationStatus.COMPLETED.value
        video.processing_stage = VideoGenerationStage.COMPLETED.value
        video.processing_completed_at = datetime.utcnow()
        video.progress_percent = 100
        video.duration_seconds = estimated_duration
        video.file_size_bytes = estimated_duration * 500000  # ~500KB per second
        # Set S3 key for generated video
        video.output_video_key = f"generated-videos/{video.user_id}/{video.id}.mp4"
        video.thumbnail_url = f"https://picsum.photos/seed/{video.id}/640/360"

        await db.commit()

        # Deduct credits based on actual video duration
        await self._deduct_credits_for_video(video, db)

        # Send email notification
        await self._send_video_completion_email(video, db)

        logger.info(f"Mock video generation completed: {video.id}")

    async def fail_video_model(
        self,
        model_id: UUID,
        error_message: str,
        db: AsyncSession,
    ) -> None:
        """Mark a video model as failed."""
        result = await db.execute(
            select(VideoModel).where(VideoModel.id == model_id)
        )
        model = result.scalar_one_or_none()

        if model:
            model.status = VideoModelStatus.FAILED.value
            model.error_message = error_message
            await db.commit()

    async def fail_voice_model(
        self,
        model_id: UUID,
        error_message: str,
        db: AsyncSession,
    ) -> None:
        """Mark a voice model as failed."""
        result = await db.execute(
            select(VoiceModel).where(VoiceModel.id == model_id)
        )
        model = result.scalar_one_or_none()

        if model:
            model.status = VoiceModelStatus.FAILED.value
            model.error_message = error_message
            await db.commit()

    async def fail_video_generation(
        self,
        video_id: UUID,
        error_message: str,
        db: AsyncSession,
    ) -> None:
        """Mark a video generation as failed."""
        result = await db.execute(
            select(GeneratedVideo).where(GeneratedVideo.id == video_id)
        )
        video = result.scalar_one_or_none()

        if video:
            video.status = GenerationStatus.FAILED.value
            video.error_message = error_message
            await db.commit()


# Global instance
ai_service = AIService()
