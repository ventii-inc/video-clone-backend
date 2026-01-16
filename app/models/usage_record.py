"""UsageRecord model for tracking monthly usage"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class UsageRecord(Base):
    """Tracks monthly usage per user for billing purposes"""

    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("user_id", "period_year", "period_month", name="uq_user_period"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period_year = Column(Integer, nullable=False)  # e.g., 2024
    period_month = Column(Integer, nullable=False)  # 1-12
    base_minutes = Column(Integer, default=0, nullable=False)  # Base plan minutes
    used_minutes = Column(Integer, default=0, nullable=False)  # Minutes consumed
    additional_minutes_purchased = Column(Integer, default=0, nullable=False)  # Extra minutes bought
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="usage_records")

    @property
    def remaining_minutes(self) -> int:
        """Calculate remaining minutes for this period"""
        return (self.base_minutes + self.additional_minutes_purchased) - self.used_minutes

    @property
    def total_available_minutes(self) -> int:
        """Total available minutes (base + purchased)"""
        return self.base_minutes + self.additional_minutes_purchased

    def __repr__(self):
        return f"<UsageRecord(user_id={self.user_id}, period={self.period_year}-{self.period_month:02d}, used={self.used_minutes})>"
