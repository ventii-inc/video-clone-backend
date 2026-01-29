"""Abuse prevention service for email-based tracking of free plan usage."""

from app.services.abuse_prevention.abuse_prevention_service import (
    abuse_prevention_service,
    AbusePreventionService,
)

__all__ = ["abuse_prevention_service", "AbusePreventionService"]
