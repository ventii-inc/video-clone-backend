"""VoiceModel for user's voice clone models"""

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
    INCOMPLETE = "incomplete"


class SourceType(str, PyEnum):
    UPLOAD = "upload"
    RECORDING = "recording"


class Visibility(str, PyEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    UNLIST = "unlist"


class VoiceModel(Base):
    """Stores user's voice clone models created from uploaded audio"""

    __tablename__ = "voice_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    source_audio_url = Column(String(500), nullable=True)
    source_audio_key = Column(String(500), nullable=True)  # S3 key
    reference_id = Column(String(500), nullable=True)  # Fish Audio model ID
    source_type = Column(String(20), default=SourceType.UPLOAD.value, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    status = Column(String(20), default=ModelStatus.PENDING.value, nullable=False, index=True)
    visibility = Column(String(20), default=Visibility.PRIVATE.value, nullable=False)
    error_message = Column(Text, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    processing_completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="voice_models")
    generated_videos = relationship("GeneratedVideo", back_populates="voice_model")

    def __repr__(self):
        return f"<VoiceModel(id={self.id}, name='{self.name}', status='{self.status}')>"
