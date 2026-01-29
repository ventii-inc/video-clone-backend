"""Subscription model for Stripe subscription tracking"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class PlanType(str, PyEnum):
    FREE = "free"
    STANDARD = "standard"
    SHOT = "shot"


class SubscriptionStatus(str, PyEnum):
    INCOMPLETE = "incomplete"  # Customer created but no payment completed
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"


class Subscription(Base):
    """Stores Stripe subscription information for users"""

    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    stripe_customer_id = Column(String(100), nullable=True, index=True)
    stripe_subscription_id = Column(String(100), nullable=True, index=True)
    plan_type = Column(String(20), default=PlanType.FREE.value, nullable=False)
    status = Column(String(20), default=SubscriptionStatus.INCOMPLETE.value, nullable=False)
    monthly_minutes_limit = Column(Integer, default=0, nullable=False)  # 0 for free, 100 for standard
    monthly_video_training_limit = Column(Integer, default=1, nullable=False)  # Training limit per month
    monthly_voice_training_limit = Column(Integer, default=1, nullable=False)  # Training limit per month
    is_one_time_purchase = Column(Boolean, default=False, nullable=False)  # True for Shot plan
    is_lifetime = Column(Boolean, default=False, nullable=False)  # True for Free plan (never resets)
    auto_charge_enabled = Column(Boolean, default=True, nullable=False)  # Auto-charge for Standard plan
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Cached payment method info (updated via webhooks)
    card_brand = Column(String(20), nullable=True)  # "visa", "mastercard", etc.
    card_last4 = Column(String(4), nullable=True)  # "4242"
    card_exp_month = Column(SmallInteger, nullable=True)  # 1-12
    card_exp_year = Column(SmallInteger, nullable=True)  # 2025

    # Relationships
    user = relationship("User", back_populates="subscription")

    def __repr__(self):
        return f"<Subscription(user_id={self.user_id}, plan='{self.plan_type}', status='{self.status}')>"
