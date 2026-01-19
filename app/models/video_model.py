"""VideoModel for user's video clone models"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class ModelStatus(str, PyEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoModel(Base):
    """Stores user's video clone models created from uploaded videos"""

    __tablename__ = "video_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    source_video_url = Column(String(500), nullable=True)
    source_video_key = Column(String(500), nullable=True)  # S3 key
    model_data_url = Column(String(500), nullable=True)  # Presigned URL for model data
    model_data_key = Column(String(500), nullable=True)  # S3 key for avatar TAR file
    thumbnail_url = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    status = Column(String(20), default=ModelStatus.PENDING.value, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    processing_completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="video_models")
    generated_videos = relationship("GeneratedVideo", back_populates="video_model")
    avatar_jobs = relationship("AvatarJob", back_populates="video_model", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<VideoModel(id={self.id}, name='{self.name}', status='{self.status}')>"
