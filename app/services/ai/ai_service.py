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
from app.models.generated_video import GeneratedVideo, GenerationStatus
from app.services.s3 import s3_service
from app.services.video import video_service, get_video_duration
from app.services.livetalking import livetalking_cli_service
from app.services.livetalking.livetalking_config import LiveTalkingSettings

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
    ) -> None:
        """Process a voice model (mock implementation).

        In production, this would:
        1. Download source audio from S3
        2. Send to AI API for voice cloning
        3. Store trained model data
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

        # Simulate processing time
        await asyncio.sleep(self.VOICE_MODEL_PROCESSING_TIME)

        # Mock success
        model.status = VoiceModelStatus.COMPLETED.value
        model.processing_completed_at = datetime.utcnow()
        model.model_data_url = f"s3://mock-bucket/models/voice/{model_id}/model.bin"

        await db.commit()
        logger.info(f"Voice model processing completed: {model_id}")

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
        video.processing_started_at = datetime.utcnow()
        video.queue_position = None
        await db.commit()

        mode = self._get_mode()

        if mode == "cli":
            await self._generate_video_cli(video, db)
        else:
            await self._generate_video_mock(video, db)

    async def _generate_video_cli(
        self,
        video: GeneratedVideo,
        db: AsyncSession,
    ) -> None:
        """Generate video using LiveTalking CLI."""
        try:
            # Get the video model to get avatar_id
            video_model_result = await db.execute(
                select(VideoModel).where(VideoModel.id == video.video_model_id)
            )
            video_model = video_model_result.scalar_one_or_none()

            if not video_model:
                raise ValueError("Video model not found")

            avatar_id = str(video.video_model_id)

            # Update progress
            video.progress_percent = 10
            await db.commit()

            # Generate output path
            output_filename = f"{video.id}.mp4"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

            # Get voice model for TTS reference (if applicable)
            voice_model_result = await db.execute(
                select(VoiceModel).where(VoiceModel.id == video.voice_model_id)
            )
            voice_model = voice_model_result.scalar_one_or_none()
            ref_file = voice_model.model_data_url if voice_model else None

            # Update progress
            video.progress_percent = 20
            await db.commit()

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

            if not result.success:
                raise ValueError(result.error or "Video generation failed")

            # Update video record with results
            video.status = GenerationStatus.COMPLETED.value
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
            logger.info(f"CLI video generation completed: {video.id}")

        except Exception as e:
            logger.error(f"CLI video generation failed: {e}")
            video.status = GenerationStatus.FAILED.value
            video.error_message = str(e)[:500]
            video.processing_completed_at = datetime.utcnow()
            await db.commit()

    async def _generate_video_mock(
        self,
        video: GeneratedVideo,
        db: AsyncSession,
    ) -> None:
        """Generate video using mock implementation (for development)."""
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
        video.processing_completed_at = datetime.utcnow()
        video.progress_percent = 100
        video.duration_seconds = estimated_duration
        video.file_size_bytes = estimated_duration * 500000  # ~500KB per second
        # Set S3 key for generated video
        video.output_video_key = f"generated-videos/{video.user_id}/{video.id}.mp4"
        video.thumbnail_url = f"https://picsum.photos/seed/{video.id}/640/360"

        await db.commit()
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
