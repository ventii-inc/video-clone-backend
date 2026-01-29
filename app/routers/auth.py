"""Authentication router for login and user info"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import User, UserProfile, Subscription
from app.models.subscription import PlanType, SubscriptionStatus
from app.services.firebase import get_current_user, get_current_user_or_create
from app.services.abuse_prevention import abuse_prevention_service
from app.services.usage_service import usage_service
from app.services.training_usage_service import training_usage_service
from app.schemas.user import LoginResponse, UserResponse, UserWithDetailsResponse, ProfileSummary, SubscriptionSummary
from app.utils.constants import PLAN_CONFIG

logger = logging.getLogger(__name__)

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
    - If user is new, creates user with free plan and returns with is_new_user=True
    """
    # Check if user has completed onboarding
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()

    onboarding_completed = profile.onboarding_completed if profile else False

    # Check if this is a new user (created in this request)
    # A simple heuristic: if no profile exists, it's a new user
    is_new_user = profile is None

    # For new users, check free plan eligibility and provision it
    if is_new_user:
        # Check if subscription already exists
        sub_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        existing_sub = sub_result.scalar_one_or_none()

        if not existing_sub:
            # Check if this email is eligible for free plan
            eligible, reason = await abuse_prevention_service.check_free_plan_eligibility(
                user.email, db
            )

            if eligible:
                # Create free plan subscription
                free_config = PLAN_CONFIG["free"]
                subscription = Subscription(
                    user_id=user.id,
                    plan_type=PlanType.FREE.value,
                    status=SubscriptionStatus.ACTIVE.value,
                    monthly_minutes_limit=free_config["minutes"],
                    monthly_video_training_limit=free_config["video_trainings"],
                    monthly_voice_training_limit=free_config["voice_trainings"],
                    is_lifetime=True,
                    is_one_time_purchase=False,
                    auto_charge_enabled=False,
                )
                db.add(subscription)
                await db.commit()
                await db.refresh(subscription)

                # Add free minutes to user's usage record
                await usage_service.add_purchased_minutes(
                    user.id, free_config["minutes"], db
                )

                # Create training usage record with free plan allowances
                await training_usage_service.get_or_create_current_usage(
                    user.id, db, subscription
                )

                # Record that this user claimed free plan
                await abuse_prevention_service.record_free_plan_claim(user.id, user.email, db)

                logger.info(f"Provisioned free plan for new user {user.id}")
            else:
                logger.info(f"User {user.id} not eligible for free plan: {reason}")

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
