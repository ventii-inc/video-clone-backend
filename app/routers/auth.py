"""Authentication router for login and user info"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import User, UserProfile, Subscription
from app.services.firebase import get_current_user, get_current_user_or_create
from app.schemas.user import LoginResponse, UserResponse, UserWithDetailsResponse, ProfileSummary, SubscriptionSummary

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(
    user: User = Depends(get_current_user_or_create),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify Firebase token and login or create user.

    This endpoint handles both login and registration:
    - If user exists, returns user info
    - If user is new, creates user and returns with is_new_user=True
    """
    # Check if user has completed onboarding
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    onboarding_completed = profile.onboarding_completed if profile else False

    # Check if this is a new user (created in this request)
    # A simple heuristic: if no profile exists, it's a new user
    is_new_user = profile is None

    return LoginResponse(
        user=UserResponse.model_validate(user),
        is_new_user=is_new_user,
        onboarding_completed=onboarding_completed,
    )


@router.get("/me", response_model=UserWithDetailsResponse)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current authenticated user's information.

    Returns user details along with profile and subscription info.
    """
    # Get profile
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()

    # Get subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscription = sub_result.scalar_one_or_none()

    return UserWithDetailsResponse(
        user=UserResponse.model_validate(user),
        profile=ProfileSummary.model_validate(profile) if profile else None,
        subscription=SubscriptionSummary.model_validate(subscription) if subscription else None,
    )
