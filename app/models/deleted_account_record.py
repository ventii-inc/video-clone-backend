"""DeletedAccountRecord model for abuse prevention"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class DeletedAccountRecord(Base):
    """Tracks deleted accounts to prevent free plan abuse via re-registration"""

    __tablename__ = "deleted_account_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_hash = Column(String(64), nullable=False, index=True)  # SHA256 hash of email
    firebase_uid = Column(String(128), nullable=True, index=True)  # Original Firebase UID
    used_free_plan = Column(Boolean, default=False, nullable=False)  # Whether user claimed free plan
    deleted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<DeletedAccountRecord(email_hash={self.email_hash[:8]}..., used_free_plan={self.used_free_plan})>"
