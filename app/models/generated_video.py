"""GeneratedVideo model for videos generated from clone models"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class GenerationStatus(str, PyEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Resolution(str, PyEnum):
    HD = "720p"
    FULL_HD = "1080p"


class GeneratedVideo(Base):
    """Stores videos generated from video and voice clone models"""

    __tablename__ = "generated_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    video_model_id = Column(UUID(as_uuid=True), ForeignKey("video_models.id", ondelete="SET NULL"), nullable=True)
    voice_model_id = Column(UUID(as_uuid=True), ForeignKey("voice_models.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(200), nullable=True)
    input_text = Column(Text, nullable=False)
    input_text_language = Column(String(10), default="ja", nullable=False)  # ja, en
    output_video_url = Column(String(500), nullable=True)
    output_video_key = Column(String(500), nullable=True)  # S3 key
    thumbnail_url = Column(String(500), nullable=True)
    resolution = Column(String(10), default=Resolution.HD.value, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    credits_used = Column(Integer, default=0, nullable=False)  # Minutes consumed
    status = Column(String(20), default=GenerationStatus.QUEUED.value, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    queue_position = Column(Integer, nullable=True)
    progress_percent = Column(Integer, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    processing_completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="generated_videos")
    video_model = relationship("VideoModel", back_populates="generated_videos")
    voice_model = relationship("VoiceModel", back_populates="generated_videos")

    def __repr__(self):
        return f"<GeneratedVideo(id={self.id}, status='{self.status}')>"
