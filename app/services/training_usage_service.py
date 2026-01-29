"""Training usage service for tracking and managing model training limits."""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.subscription import Subscription, PlanType
from app.models.training_usage_record import TrainingUsageRecord
from app.utils.constants import PLAN_CONFIG

logger = logging.getLogger(__name__)


class TrainingUsageService:
    """Service for tracking and managing training usage/limits."""

    async def get_or_create_current_usage(
        self,
        user_id: int,
        db: AsyncSession,
        subscription: Subscription | None = None,
    ) -> TrainingUsageRecord:
        """Get or create training usage record for current billing period.

        For lifetime plans (Free), uses the initial signup period.
        For one-time purchases (Shot), uses the purchase period.
        For Standard plans, uses current month.

        Args:
            user_id: The user's ID
            db: Database session
            subscription: Optional pre-fetched subscription
        """
        # Get subscription if not provided
        if subscription is None:
            sub_result = await db.execute(
                select(Subscription).where(Subscription.user_id == user_id)
            )
            subscription = sub_result.scalar_one_or_none()

        # Determine period based on plan type
        now = datetime.utcnow()

        # For lifetime/one-time plans, we use a fixed period (year=0, month=0)
        # This ensures trainings never reset
        if subscription and (subscription.is_lifetime or subscription.is_one_time_purchase):
            year = 0
            month = 0
        else:
            year = now.year
            month = now.month

        # Try to get existing record
        result = await db.execute(
            select(TrainingUsageRecord).where(
                TrainingUsageRecord.user_id == user_id,
                TrainingUsageRecord.period_year == year,
                TrainingUsageRecord.period_month == month,
            )
        )
        record = result.scalar_one_or_none()

        if record:
            return record

        # Determine base trainings from plan
        base_video = 1
        base_voice = 1
        if subscription:
            plan_config = PLAN_CONFIG.get(subscription.plan_type, {})
            base_video = plan_config.get("video_trainings", 1)
            base_voice = plan_config.get("voice_trainings", 1)

        # Create new record
        record = TrainingUsageRecord(
            user_id=user_id,
            period_year=year,
            period_month=month,
            base_video_trainings=base_video,
            base_voice_trainings=base_voice,
            used_video_trainings=0,
            used_voice_trainings=0,
            additional_video_trainings=0,
            additional_voice_trainings=0,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        return record

    async def can_create_video_model(
        self,
        user_id: int,
        db: AsyncSession,
        subscription: Subscription | None = None,
    ) -> tuple[bool, str | None]:
        """Check if user can create a new video model.

        Returns:
            Tuple of (allowed, error_message)
        """
        record = await self.get_or_create_current_usage(user_id, db, subscription)

        if record.remaining_video_trainings <= 0:
            return False, (
                f"Video training limit reached "
                f"({record.used_video_trainings}/{record.total_video_trainings}). "
                "Please upgrade your plan or wait for the next billing period."
            )

        return True, None

    async def can_create_voice_model(
        self,
        user_id: int,
        db: AsyncSession,
        subscription: Subscription | None = None,
    ) -> tuple[bool, str | None]:
        """Check if user can create a new voice model.

        Returns:
            Tuple of (allowed, error_message)
        """
        record = await self.get_or_create_current_usage(user_id, db, subscription)

        if record.remaining_voice_trainings <= 0:
            return False, (
                f"Voice training limit reached "
                f"({record.used_voice_trainings}/{record.total_voice_trainings}). "
                "Please upgrade your plan or wait for the next billing period."
            )

        return True, None

    async def consume_video_training(
        self,
        user_id: int,
        db: AsyncSession,
    ) -> TrainingUsageRecord:
        """Consume one video training slot.

        Returns updated usage record.
        Raises ValueError if insufficient trainings.
        """
        record = await self.get_or_create_current_usage(user_id, db)

        if record.remaining_video_trainings <= 0:
            raise ValueError(
                f"Video training limit reached. "
                f"Used: {record.used_video_trainings}, Available: {record.total_video_trainings}"
            )

        record.used_video_trainings += 1
        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Consumed video training for user {user_id}. "
            f"Remaining: {record.remaining_video_trainings}"
        )

        return record

    async def consume_voice_training(
        self,
        user_id: int,
        db: AsyncSession,
    ) -> TrainingUsageRecord:
        """Consume one voice training slot.

        Returns updated usage record.
        Raises ValueError if insufficient trainings.
        """
        record = await self.get_or_create_current_usage(user_id, db)

        if record.remaining_voice_trainings <= 0:
            raise ValueError(
                f"Voice training limit reached. "
                f"Used: {record.used_voice_trainings}, Available: {record.total_voice_trainings}"
            )

        record.used_voice_trainings += 1
        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Consumed voice training for user {user_id}. "
            f"Remaining: {record.remaining_voice_trainings}"
        )

        return record

    async def add_bonus_trainings(
        self,
        user_id: int,
        video_trainings: int,
        voice_trainings: int,
        db: AsyncSession,
    ) -> TrainingUsageRecord:
        """Add bonus trainings (e.g., from auto-charge)."""
        record = await self.get_or_create_current_usage(user_id, db)

        record.additional_video_trainings += video_trainings
        record.additional_voice_trainings += voice_trainings
        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Added bonus trainings for user {user_id}: "
            f"+{video_trainings} video, +{voice_trainings} voice"
        )

        return record

    async def get_training_summary(
        self,
        user_id: int,
        db: AsyncSession,
        subscription: Subscription | None = None,
    ) -> dict:
        """Get training usage summary for current period."""
        record = await self.get_or_create_current_usage(user_id, db, subscription)

        return {
            "period_year": record.period_year,
            "period_month": record.period_month,
            "video_trainings": {
                "used": record.used_video_trainings,
                "total": record.total_video_trainings,
                "remaining": record.remaining_video_trainings,
                "base": record.base_video_trainings,
                "additional": record.additional_video_trainings,
            },
            "voice_trainings": {
                "used": record.used_voice_trainings,
                "total": record.total_voice_trainings,
                "remaining": record.remaining_voice_trainings,
                "base": record.base_voice_trainings,
                "additional": record.additional_voice_trainings,
            },
        }


# Global instance
training_usage_service = TrainingUsageService()
