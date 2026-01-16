"""User schemas for responses"""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    """User basic response"""
    id: int
    email: EmailStr
    name: str | None
    avatar_url: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileSummary(BaseModel):
    """Profile summary for user details"""
    usage_type: str | None
    role: str | None
    onboarding_completed: bool

    class Config:
        from_attributes = True


class SubscriptionSummary(BaseModel):
    """Subscription summary for user details"""
    plan_type: str
    status: str
    current_period_end: datetime | None

    class Config:
        from_attributes = True


class UserWithDetailsResponse(BaseModel):
    """User response with profile and subscription details"""
    user: UserResponse
    profile: ProfileSummary | None
    subscription: SubscriptionSummary | None


class LoginResponse(BaseModel):
    """Login endpoint response"""
    user: UserResponse
    is_new_user: bool
    onboarding_completed: bool
