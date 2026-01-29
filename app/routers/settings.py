"""Settings router for user preferences and account management"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

import stripe
from firebase_admin import auth

from app.db import get_db
from app.models import User, UserSettings, Subscription
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.services.abuse_prevention import abuse_prevention_service
from app.schemas.common import MessageResponse, UploadInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    email_notifications: bool
    language: str
    default_resolution: str


class SettingsUpdate(BaseModel):
    email_notifications: bool | None = None
    language: str | None = None
    default_resolution: str | None = None


class AvatarUploadRequest(BaseModel):
    file_name: str
    content_type: str


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get user settings.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Return defaults
        return SettingsResponse(
            email_notifications=True,
            language="ja",
            default_resolution="720p",
        )

    return SettingsResponse(
        email_notifications=settings.email_notifications,
        language=settings.language,
        default_resolution=settings.default_resolution,
    )


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update user settings.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create settings if not exists
        settings = UserSettings(
            user_id=user.id,
            email_notifications=data.email_notifications if data.email_notifications is not None else True,
            language=data.language or "ja",
            default_resolution=data.default_resolution or "720p",
        )
        db.add(settings)
    else:
        # Update existing
        if data.email_notifications is not None:
            settings.email_notifications = data.email_notifications
        if data.language is not None:
            settings.language = data.language
        if data.default_resolution is not None:
            settings.default_resolution = data.default_resolution

    await db.commit()
    await db.refresh(settings)

    return SettingsResponse(
        email_notifications=settings.email_notifications,
        language=settings.language,
        default_resolution=settings.default_resolution,
    )


@router.post("/avatar")
async def upload_avatar(
    data: AvatarUploadRequest,
    user: User = Depends(get_current_user),
):
    """
    Get presigned URL for avatar upload.
    """
    # Validate content type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if data.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type. Allowed: {', '.join(allowed_types)}",
        )

    # Generate S3 key
    s3_key = f"avatars/{user.id}/avatar"

    # Generate presigned URL
    presigned_url = await s3_service.generate_presigned_upload_url(
        s3_key=s3_key,
        content_type=data.content_type,
        expiration=3600,
    )

    return {
        "upload": UploadInfo(
            presigned_url=presigned_url,
            s3_key=s3_key,
            expires_in_seconds=3600,
        ).model_dump()
    }


@router.post("/avatar/confirm")
async def confirm_avatar_upload(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm avatar upload and update user profile.
    """
    s3_key = f"avatars/{user.id}/avatar"

    # Verify file exists
    exists = await s3_service.file_exists(s3_key)
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Avatar file not found. Please upload first.",
        )

    # Generate public URL
    avatar_url = await s3_service.generate_presigned_url(s3_key, expires_in=86400 * 7)

    # Update user
    user.avatar_url = avatar_url
    await db.commit()

    return {"avatar_url": avatar_url}


@router.post("/account/export", status_code=status.HTTP_202_ACCEPTED)
async def request_data_export(
    user: User = Depends(get_current_user),
):
    """
    Request a data export.

    NOT IMPLEMENTED - Placeholder.
    """
    return {
        "message": "Data export request received. You will receive an email when ready.",
        "estimated_completion": "2024-01-15T12:00:00Z",  # Mock date
    }


@router.delete("/account", response_model=MessageResponse)
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft delete user account - keeps data, frees email for re-registration.

    Flow:
    1. Record ORIGINAL email for abuse prevention (before modification)
    2. Generate unique deleted email suffix (e.g., user@example.com#deleted)
    3. Update user's email in database
    4. Cancel Stripe subscription if active
    5. Mark subscription as canceled
    6. Delete from Firebase Auth (so they can't login)
    """
    # 1. Get subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscription = sub_result.scalar_one_or_none()

    # 2. Record ORIGINAL email for abuse prevention (before modification)
    used_free_plan = subscription.is_lifetime if subscription else False
    await abuse_prevention_service.record_account_deletion(
        email=user.email,  # Original email
        firebase_uid=user.firebase_uid,
        used_free_plan=used_free_plan,
        db=db,
    )

    # 3. Generate unique deleted email suffix
    base_email = user.email
    suffix = "#deleted"
    new_email = f"{base_email}{suffix}"

    # Check if email already exists, increment suffix if needed
    counter = 1
    while True:
        existing = await db.execute(
            select(User).where(User.email == new_email)
        )
        if not existing.scalar_one_or_none():
            break
        counter += 1
        new_email = f"{base_email}{suffix}{counter}"

    # 4. Update user email
    user.email = new_email

    # 5. Cancel Stripe subscription if active
    if subscription and subscription.stripe_subscription_id:
        try:
            stripe.Subscription.cancel(subscription.stripe_subscription_id)
            logger.info(f"Canceled Stripe subscription {subscription.stripe_subscription_id} for user {user.id}")
        except stripe.StripeError as e:
            logger.error(f"Failed to cancel Stripe subscription: {e}")
        subscription.status = "canceled"

    await db.commit()

    # 6. Delete from Firebase Auth (so they can't login)
    try:
        await asyncio.to_thread(auth.delete_user, user.firebase_uid)
        logger.info(f"Deleted Firebase user {user.firebase_uid}")
    except Exception as e:
        logger.error(f"Failed to delete Firebase user: {e}")

    logger.info(f"Account soft-deleted for user {user.id}, email changed to {new_email}")

    return MessageResponse(message="Account deleted successfully")
