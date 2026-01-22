"""
Backfill thumbnails for existing video models that don't have them.

Usage:
    ENV=staging uv run python scripts/backfill_thumbnails.py
"""

import asyncio
import os
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_session
from app.models import VideoModel
from app.services.s3 import s3_service
from app.services.video import extract_thumbnail
from app.utils import logger
from sqlalchemy import select


async def backfill_thumbnails():
    """Generate thumbnails for all video models that don't have them."""

    async with get_db_session() as db:
        # Find all video models without thumbnails that have source videos
        result = await db.execute(
            select(VideoModel).where(
                VideoModel.thumbnail_key.is_(None),
                VideoModel.source_video_key.isnot(None),
            )
        )
        models = result.scalars().all()

        logger.info(f"Found {len(models)} models without thumbnails")

        for model in models:
            logger.info(f"Processing model {model.id} ({model.name})...")

            temp_video_path = None
            thumbnail_path = None

            try:
                # Download video from S3
                ext = os.path.splitext(model.source_video_key)[1] or ".mp4"
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    temp_video_path = tmp.name

                success = await s3_service.download_file(model.source_video_key, temp_video_path)
                if not success:
                    logger.error(f"  Failed to download video: {model.source_video_key}")
                    continue

                # Extract thumbnail
                thumbnail_path = await extract_thumbnail(temp_video_path, timestamp=1.0)
                if not thumbnail_path:
                    logger.error(f"  Failed to extract thumbnail")
                    continue

                # Generate S3 key for thumbnail
                thumbnail_s3_key = s3_service.generate_s3_key(
                    user_id=str(model.user_id),
                    filename=f"{model.id}.jpg",
                    media_type="thumbnails",
                    unique_id=str(model.id),
                )

                # Upload thumbnail to S3
                success = await s3_service.upload_file(
                    thumbnail_path, thumbnail_s3_key, content_type="image/jpeg"
                )

                if success:
                    # Update model with thumbnail key
                    model.thumbnail_key = thumbnail_s3_key
                    await db.commit()
                    logger.info(f"  Thumbnail uploaded: {thumbnail_s3_key}")
                else:
                    logger.error(f"  Failed to upload thumbnail")

            except Exception as e:
                logger.error(f"  Error processing model {model.id}: {e}")
            finally:
                # Clean up temp files
                if temp_video_path and os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
                if thumbnail_path and os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)

        logger.info("Backfill complete!")


if __name__ == "__main__":
    asyncio.run(backfill_thumbnails())
