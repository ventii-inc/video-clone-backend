"""PaymentHistory model for payment transaction logs"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


class PaymentType(str, PyEnum):
    SUBSCRIPTION = "subscription"
    ADDITIONAL_MINUTES = "additional_minutes"


class PaymentStatus(str, PyEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"


class PaymentHistory(Base):
    """Stores payment transaction history"""

    __tablename__ = "payment_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stripe_payment_intent_id = Column(String(100), nullable=True, index=True)
    stripe_invoice_id = Column(String(100), nullable=True)
    payment_type = Column(String(30), default=PaymentType.SUBSCRIPTION.value, nullable=False)
    amount_cents = Column(Integer, nullable=False)  # Amount in cents
    currency = Column(String(10), default="jpy", nullable=False)
    minutes_purchased = Column(Integer, nullable=True)  # For additional_minutes payments
    status = Column(String(20), default=PaymentStatus.PENDING.value, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="payment_history")

    def __repr__(self):
        return f"<PaymentHistory(id={self.id}, type='{self.payment_type}', amount={self.amount_cents})>"
