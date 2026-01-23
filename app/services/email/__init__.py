"""Email service package."""

from app.services.email.email_service import (
    EmailService,
    TrainingCompletionData,
    get_email_service,
)

__all__ = [
    "EmailService",
    "TrainingCompletionData",
    "get_email_service",
]
