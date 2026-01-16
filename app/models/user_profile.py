"""UserProfile model for onboarding survey data"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class UserProfile(Base):
    """Stores onboarding survey data and user preferences"""

    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    usage_type = Column(String(20), nullable=True)  # personal, business
    company_size = Column(String(20), nullable=True)  # 1-10, 11-50, 51-200, 201-1000, 1001+
    role = Column(String(50), nullable=True)  # executive, manager, staff, freelancer, other
    use_cases = Column(JSON, nullable=True)  # Array of use cases
    referral_source = Column(String(50), nullable=True)  # search, social, referral, ads, media, other
    onboarding_completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="profile")

    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id}, usage_type='{self.usage_type}')>"
