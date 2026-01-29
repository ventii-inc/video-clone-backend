"""Abuse prevention service for tracking free plan usage and preventing abuse."""

import hashlib
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.deleted_account_record import DeletedAccountRecord
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


class AbusePreventionService:
    """Service for preventing free plan abuse via email tracking."""

    @staticmethod
    def hash_email(email: str) -> str:
        """Create SHA256 hash of email for privacy-preserving comparison."""
        return hashlib.sha256(email.lower().strip().encode()).hexdigest()

    async def check_free_plan_eligibility(
        self,
        email: str,
        db: AsyncSession,
    ) -> tuple[bool, str | None]:
        """Check if email is eligible for free plan.

        Returns:
            Tuple of (eligible, reason_if_not_eligible)
        """
        email_hash = self.hash_email(email)

        # Check if email was used before and claimed free plan
        result = await db.execute(
            select(DeletedAccountRecord).where(
                DeletedAccountRecord.email_hash == email_hash,
                DeletedAccountRecord.used_free_plan == True,
            )
        )
        record = result.scalar_one_or_none()

        if record:
            logger.info(f"Free plan ineligible: email hash {email_hash[:8]}... previously used free plan")
            return False, "This email has already claimed the free plan allowance."

        return True, None

    async def record_free_plan_claim(
        self,
        user_id: int,
        email: str,
        db: AsyncSession,
    ) -> None:
        """Record that a user has claimed their free plan allowance.

        This is called when a new user is created and gets free plan credits.
        We store this in the subscription record, not in deleted_account_records.
        """
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if subscription:
            # Mark subscription as having used lifetime free plan
            subscription.is_lifetime = True
            await db.commit()
            logger.info(f"Recorded free plan claim for user {user_id}")

    async def record_account_deletion(
        self,
        email: str,
        firebase_uid: str,
        used_free_plan: bool,
        db: AsyncSession,
    ) -> DeletedAccountRecord:
        """Record account deletion for abuse prevention.

        Called when a user deletes their account to track if they
        had used the free plan (preventing re-registration abuse).
        """
        email_hash = self.hash_email(email)

        # Check if record already exists
        result = await db.execute(
            select(DeletedAccountRecord).where(
                DeletedAccountRecord.email_hash == email_hash
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing record
            existing.firebase_uid = firebase_uid
            existing.used_free_plan = existing.used_free_plan or used_free_plan
            existing.deleted_at = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
            logger.info(f"Updated deletion record for email hash {email_hash[:8]}...")
            return existing

        # Create new record
        record = DeletedAccountRecord(
            email_hash=email_hash,
            firebase_uid=firebase_uid,
            used_free_plan=used_free_plan,
            deleted_at=datetime.utcnow(),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        logger.info(
            f"Created deletion record for email hash {email_hash[:8]}..., "
            f"used_free_plan={used_free_plan}"
        )

        return record

    async def was_free_plan_used(
        self,
        user_id: int,
        db: AsyncSession,
    ) -> bool:
        """Check if user has used their free plan allowance."""
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        return subscription is not None and subscription.is_lifetime


# Global instance
abuse_prevention_service = AbusePreventionService()
