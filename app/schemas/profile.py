"""Profile schemas for onboarding and user profile management"""

from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field


UsageType = Literal["personal", "business"]
CompanySize = Literal["1-10", "11-50", "51-200", "201-1000", "1001+"]
Role = Literal["executive", "manager", "staff", "freelancer", "other"]
UseCase = Literal["marketing", "training", "support", "social", "presentation", "other"]
ReferralSource = Literal["search", "social", "referral", "ads", "media", "other"]


class ProfileCreate(BaseModel):
    """Profile creation schema (onboarding)"""
    usage_type: UsageType
    company_size: CompanySize | None = None
    role: Role
    use_cases: list[UseCase] = Field(..., min_length=1)
    referral_source: ReferralSource


class ProfileUpdate(BaseModel):
    """Profile update schema"""
    usage_type: UsageType | None = None
    company_size: CompanySize | None = None
    role: Role | None = None
    use_cases: list[UseCase] | None = None
    referral_source: ReferralSource | None = None


class ProfileResponse(BaseModel):
    """Profile response schema"""
    id: UUID
    user_id: int
    usage_type: str | None
    company_size: str | None
    role: str | None
    use_cases: list[str] | None
    referral_source: str | None
    onboarding_completed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
