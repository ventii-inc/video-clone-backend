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


class ProcessingStage(str, PyEnum):
    """Stages of video model processing for progress tracking"""
    PENDING = "pending"           # 0% - Waiting to start
    UPLOADING = "uploading"       # 0-10% - Uploading to S3
    PREPARING = "preparing"       # 10-20% - Downloading/preparing for processing
    TRAINING = "training"         # 20-80% - LiveTalking avatar training
    FINALIZING = "finalizing"     # 80-100% - Uploading results, cleanup
    COMPLETED = "completed"       # 100% - Done
    FAILED = "failed"             # Error state


class VideoModel(Base):
    """Stores user's video clone models created from uploaded videos"""

    __tablename__ = "video_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    source_video_url = Column(String(500), nullable=True)
    source_video_key = Column(String(500), nullable=True)  # S3 key
    local_video_path = Column(String(500), nullable=True)  # Local file path for CLI processing
    model_data_url = Column(String(500), nullable=True)  # Presigned URL for model data
    model_data_key = Column(String(500), nullable=True)  # S3 key for avatar TAR file
    thumbnail_url = Column(String(500), nullable=True)  # Deprecated: use thumbnail_key
    thumbnail_key = Column(String(500), nullable=True)  # S3 key for thumbnail
    execution_mode = Column(String(10), nullable=True)  # "cli" or "api" - how avatar was generated
    duration_seconds = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    status = Column(String(20), default=ModelStatus.PENDING.value, nullable=False, index=True)
    progress_percent = Column(Integer, default=0, nullable=False)  # 0-100
    processing_stage = Column(String(20), default=ProcessingStage.PENDING.value, nullable=False)
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
