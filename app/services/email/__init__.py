"""Email service package."""

from app.services.email.email_service import (
    EmailService,
    TrainingCompletionData,
    TrainingFailureData,
    VideoGenerationCompletionData,
    get_email_service,
)

__all__ = [
    "EmailService",
    "TrainingCompletionData",
    "TrainingFailureData",
    "VideoGenerationCompletionData",
    "get_email_service",
]
