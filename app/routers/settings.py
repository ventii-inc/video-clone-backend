"""Settings router for user preferences and account management"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db
from app.models import User, UserSettings
from app.services.firebase import get_current_user
from app.services.s3 import s3_service
from app.schemas.common import MessageResponse, UploadInfo

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
        expires_in=3600,
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


@router.delete("/account")
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete user account.

    This schedules the account for deletion.
    """
    # In production, this should:
    # 1. Cancel any active subscriptions
    # 2. Schedule data deletion after grace period
    # 3. Send confirmation email

    # For now, just return a message
    return MessageResponse(
        message="Account scheduled for deletion. You have 30 days to recover."
    )
