"""Users router for profile management"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models import User, UserProfile
from app.services.firebase import get_current_user
from app.schemas.profile import ProfileCreate, ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/profile", response_model=ProfileResponse, status_code=status.HTTP_200_OK)
async def create_or_update_profile(
    profile_data: ProfileCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or update user profile (onboarding).

    This endpoint is used to submit onboarding survey data.
    If profile exists, it updates it; otherwise creates new.
    """
    # Check for existing profile
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    if profile:
        # Update existing profile
        profile.usage_type = profile_data.usage_type
        profile.company_size = profile_data.company_size
        profile.role = profile_data.role
        profile.use_cases = profile_data.use_cases
        profile.referral_source = profile_data.referral_source
        profile.onboarding_completed = True
    else:
        # Create new profile
        profile = UserProfile(
            user_id=user.id,
            usage_type=profile_data.usage_type,
            company_size=profile_data.company_size,
            role=profile_data.role,
            use_cases=profile_data.use_cases,
            referral_source=profile_data.referral_source,
            onboarding_completed=True,
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    return ProfileResponse.model_validate(profile)


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's profile.
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Please complete onboarding.",
        )

    return ProfileResponse.model_validate(profile)


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    profile_data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Partially update user profile.
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Please complete onboarding first.",
        )

    # Update only provided fields
    update_data = profile_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    return ProfileResponse.model_validate(profile)
