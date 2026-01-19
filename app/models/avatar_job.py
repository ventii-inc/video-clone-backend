"""AvatarJob model for tracking avatar generation jobs"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class JobStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AvatarJob(Base):
    """Tracks avatar generation jobs sent to RunPod"""

    __tablename__ = "avatar_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("video_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(
        String(20), default=JobStatus.PENDING.value, nullable=False, index=True
    )

    # Retry tracking
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # RunPod tracking
    runpod_job_id = Column(String(100), nullable=True, index=True)

    # Result
    avatar_s3_key = Column(String(500), nullable=True)

    # Relationships
    user = relationship("User", back_populates="avatar_jobs")
    video_model = relationship("VideoModel", back_populates="avatar_jobs")

    def __repr__(self):
        return f"<AvatarJob(id={self.id}, status='{self.status}', video_model_id={self.video_model_id})>"
