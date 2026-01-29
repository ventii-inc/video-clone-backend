"""Usage tracking service for monitoring and managing user credits."""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.subscription import Subscription, PlanType
from app.models.usage_record import UsageRecord
from app.utils.constants import PLAN_CONFIG

logger = logging.getLogger(__name__)


class UsageService:
    """Service for tracking and managing user usage/credits."""

    async def get_or_create_current_usage(
        self,
        user_id: int,
        db: AsyncSession,
        subscription: Subscription | None = None,
    ) -> UsageRecord:
        """Get or create usage record for current billing period.

        Args:
            user_id: The user's ID
            db: Database session
            subscription: Optional pre-fetched subscription to avoid redundant query
        """
        now = datetime.utcnow()
        year = now.year
        month = now.month

        # Try to get existing record
        result = await db.execute(
            select(UsageRecord).where(
                UsageRecord.user_id == user_id,
                UsageRecord.period_year == year,
                UsageRecord.period_month == month,
            )
        )
        record = result.scalar_one_or_none()

        if record:
            return record

        # Get user's subscription to determine base minutes (only if not provided)
        if subscription is None:
            sub_result = await db.execute(
                select(Subscription).where(Subscription.user_id == user_id)
            )
            subscription = sub_result.scalar_one_or_none()

        base_minutes = 0
        if subscription:
            plan_config = PLAN_CONFIG.get(subscription.plan_type, {})
            base_minutes = plan_config.get("minutes", 0)

        # Create new record
        record = UsageRecord(
            user_id=user_id,
            period_year=year,
            period_month=month,
            base_minutes=base_minutes,
            used_minutes=0,
            additional_minutes_purchased=0,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        return record

    async def get_remaining_minutes(
        self,
        user_id: int,
        db: AsyncSession,
    ) -> int:
        """Get remaining minutes for user in current period."""
        record = await self.get_or_create_current_usage(user_id, db)
        return record.remaining_minutes

    async def has_sufficient_credits(
        self,
        user_id: int,
        required_minutes: int,
        db: AsyncSession,
    ) -> bool:
        """Check if user has enough credits for an operation."""
        remaining = await self.get_remaining_minutes(user_id, db)
        return remaining >= required_minutes

    async def deduct_credits(
        self,
        user_id: int,
        minutes: int,
        db: AsyncSession,
    ) -> UsageRecord:
        """Deduct credits from user's usage.

        Returns updated usage record.
        Raises ValueError if insufficient credits.
        """
        record = await self.get_or_create_current_usage(user_id, db)

        if record.remaining_minutes < minutes:
            raise ValueError(
                f"Insufficient credits. Required: {minutes}, Available: {record.remaining_minutes}"
            )

        record.used_minutes += minutes
        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Deducted {minutes} minutes from user {user_id}. "
            f"Remaining: {record.remaining_minutes}"
        )

        return record

    async def add_purchased_minutes(
        self,
        user_id: int,
        minutes: int,
        db: AsyncSession,
    ) -> UsageRecord:
        """Add purchased minutes to user's current period."""
        record = await self.get_or_create_current_usage(user_id, db)
        record.additional_minutes_purchased += minutes
        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Added {minutes} purchased minutes to user {user_id}. "
            f"Total available: {record.total_available_minutes}"
        )

        return record

    async def get_usage_summary(
        self,
        user_id: int,
        db: AsyncSession,
        subscription: Subscription | None = None,
    ) -> dict:
        """Get usage summary for current period.

        Args:
            user_id: The user's ID
            db: Database session
            subscription: Optional pre-fetched subscription to avoid redundant query
        """
        record = await self.get_or_create_current_usage(user_id, db, subscription)

        return {
            "period_year": record.period_year,
            "period_month": record.period_month,
            "base_minutes": record.base_minutes,
            "used_minutes": record.used_minutes,
            "additional_minutes_purchased": record.additional_minutes_purchased,
            "remaining_minutes": record.remaining_minutes,
            "total_available_minutes": record.total_available_minutes,
        }

    async def get_usage_history(
        self,
        user_id: int,
        months: int,
        db: AsyncSession,
    ) -> list[dict]:
        """Get usage history for last N months."""
        result = await db.execute(
            select(UsageRecord)
            .where(UsageRecord.user_id == user_id)
            .order_by(
                UsageRecord.period_year.desc(),
                UsageRecord.period_month.desc(),
            )
            .limit(months)
        )
        records = result.scalars().all()

        return [
            {
                "period_year": r.period_year,
                "period_month": r.period_month,
                "base_minutes": r.base_minutes,
                "used_minutes": r.used_minutes,
                "additional_minutes_purchased": r.additional_minutes_purchased,
            }
            for r in records
        ]

    async def estimate_credits_needed(
        self,
        text_length: int,
    ) -> int:
        """Estimate credits (minutes) needed for generating video from text.

        Rough estimate: ~150 characters = 1 minute of video
        """
        # Minimum 1 minute
        return max(1, (text_length + 149) // 150)

    async def check_and_auto_charge(
        self,
        user_id: int,
        required_minutes: int,
        db: AsyncSession,
    ) -> dict:
        """Check if user has sufficient credits, auto-charge if needed (Standard plan only).

        Returns dict with:
        - has_credits: bool - whether user now has sufficient credits
        - auto_charged: bool - whether auto-charge was performed
        - error: str | None - error message if applicable
        """
        from app.services.stripe import stripe_service

        record = await self.get_or_create_current_usage(user_id, db)

        if record.remaining_minutes >= required_minutes:
            return {"has_credits": True, "auto_charged": False, "error": None}

        # Get subscription to check if auto-charge is available
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return {
                "has_credits": False,
                "auto_charged": False,
                "error": "Insufficient credits. Please purchase additional minutes.",
            }

        if subscription.plan_type != PlanType.STANDARD.value:
            return {
                "has_credits": False,
                "auto_charged": False,
                "error": "Insufficient credits. Please upgrade to Standard plan for auto-charge.",
            }

        if not subscription.auto_charge_enabled:
            return {
                "has_credits": False,
                "auto_charged": False,
                "error": "Insufficient credits. Auto-charge is disabled. Please enable it or purchase minutes manually.",
            }

        # Attempt auto-charge
        charge_result = await stripe_service.process_auto_charge(user_id, db)

        if charge_result["success"]:
            # Refresh usage record
            record = await self.get_or_create_current_usage(user_id, db)
            return {
                "has_credits": record.remaining_minutes >= required_minutes,
                "auto_charged": True,
                "minutes_added": charge_result.get("minutes_added", 0),
                "error": None,
            }
        else:
            return {
                "has_credits": False,
                "auto_charged": False,
                "error": f"Auto-charge failed: {charge_result.get('error', 'Unknown error')}",
            }


# Global instance
usage_service = UsageService()
