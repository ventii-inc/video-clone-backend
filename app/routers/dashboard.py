"""Dashboard and usage router"""

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db import get_db
from app.models import User, VideoModel, VoiceModel, GeneratedVideo, Subscription
from app.services.firebase import get_current_user
from app.services.usage_service import usage_service
from app.schemas.generated_video import GeneratedVideoListItem
from app.schemas.video_model import VideoModelBrief
from app.schemas.voice_model import VoiceModelBrief

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard")
async def get_dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get dashboard summary including usage, models count, and recent videos.
    """
    # Get usage summary
    usage = await usage_service.get_usage_summary(user.id, db)

    # Get models count
    video_models_result = await db.execute(
        select(func.count()).select_from(VideoModel).where(VideoModel.user_id == user.id)
    )
    video_models_count = video_models_result.scalar()

    voice_models_result = await db.execute(
        select(func.count()).select_from(VoiceModel).where(VoiceModel.user_id == user.id)
    )
    voice_models_count = voice_models_result.scalar()

    # Get recent videos (last 5)
    recent_result = await db.execute(
        select(GeneratedVideo)
        .where(GeneratedVideo.user_id == user.id)
        .order_by(GeneratedVideo.created_at.desc())
        .limit(5)
    )
    recent_videos = recent_result.scalars().all()

    # Get subscription
    sub_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscription = sub_result.scalar_one_or_none()

    # Calculate period dates
    now = datetime.utcnow()
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        period_end = period_start.replace(year=now.year + 1, month=1)
    else:
        period_end = period_start.replace(month=now.month + 1)

    return {
        "usage": {
            "minutes_used": usage["used_minutes"],
            "minutes_remaining": usage["remaining_minutes"],
            "minutes_limit": usage["total_available_minutes"],
            "additional_minutes": usage["additional_minutes_purchased"],
            "period_start": period_start.date().isoformat(),
            "period_end": period_end.date().isoformat(),
        },
        "models": {
            "video_models_count": video_models_count,
            "voice_models_count": voice_models_count,
        },
        "recent_videos": [
            {
                "id": str(v.id),
                "title": v.title,
                "thumbnail_url": v.thumbnail_url,
                "status": v.status,
                "created_at": v.created_at.isoformat(),
            }
            for v in recent_videos
        ],
        "subscription": {
            "plan_type": subscription.plan_type if subscription else "free",
            "status": subscription.status if subscription else "active",
            "current_period_end": subscription.current_period_end.isoformat() if subscription and subscription.current_period_end else None,
        } if subscription else {
            "plan_type": "free",
            "status": "active",
            "current_period_end": None,
        },
    }


@router.get("/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current month usage details.
    """
    usage = await usage_service.get_usage_summary(user.id, db)
    return {"usage": usage}


@router.get("/usage/history")
async def get_usage_history(
    months: int = Query(default=6, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get usage history for the last N months.
    """
    history = await usage_service.get_usage_history(user.id, months, db)
    return {"history": history}
