"""TrainingUsageRecord model for tracking monthly training usage"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class TrainingUsageRecord(Base):
    """Tracks monthly training usage per user for video/voice model training limits"""

    __tablename__ = "training_usage_records"
    __table_args__ = (
        UniqueConstraint("user_id", "period_year", "period_month", name="uq_training_user_period"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period_year = Column(Integer, nullable=False)  # e.g., 2024
    period_month = Column(Integer, nullable=False)  # 1-12

    # Base training allowances from subscription plan
    base_video_trainings = Column(Integer, default=1, nullable=False)
    base_voice_trainings = Column(Integer, default=1, nullable=False)

    # Used trainings in this period
    used_video_trainings = Column(Integer, default=0, nullable=False)
    used_voice_trainings = Column(Integer, default=0, nullable=False)

    # Additional trainings from auto-charge bonuses
    additional_video_trainings = Column(Integer, default=0, nullable=False)
    additional_voice_trainings = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="training_usage_records")

    @property
    def remaining_video_trainings(self) -> int:
        """Calculate remaining video trainings for this period"""
        return (self.base_video_trainings + self.additional_video_trainings) - self.used_video_trainings

    @property
    def remaining_voice_trainings(self) -> int:
        """Calculate remaining voice trainings for this period"""
        return (self.base_voice_trainings + self.additional_voice_trainings) - self.used_voice_trainings

    @property
    def total_video_trainings(self) -> int:
        """Total available video trainings (base + additional)"""
        return self.base_video_trainings + self.additional_video_trainings

    @property
    def total_voice_trainings(self) -> int:
        """Total available voice trainings (base + additional)"""
        return self.base_voice_trainings + self.additional_voice_trainings

    def __repr__(self):
        return (
            f"<TrainingUsageRecord(user_id={self.user_id}, "
            f"period={self.period_year}-{self.period_month:02d}, "
            f"video={self.used_video_trainings}/{self.total_video_trainings}, "
            f"voice={self.used_voice_trainings}/{self.total_voice_trainings})>"
        )
