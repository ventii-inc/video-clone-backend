"""Billing router - Placeholder stubs for Stripe integration"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db
from app.models import User, Subscription
from app.services.firebase import get_current_user

router = APIRouter(prefix="/billing", tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan_type: str = "standard"
    success_url: str
    cancel_url: str


class PortalRequest(BaseModel):
    return_url: str


class PurchaseMinutesRequest(BaseModel):
    quantity: int  # Each unit = 20 minutes = ¥1,000
    success_url: str
    cancel_url: str


@router.get("/subscription")
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current subscription details.

    Returns mock data for now until Stripe is integrated.
    """
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        # Return default free subscription
        return {
            "subscription": {
                "plan_type": "free",
                "status": "active",
                "monthly_minutes_limit": 0,
                "current_period_start": None,
                "current_period_end": None,
                "cancel_at_period_end": False,
            },
            "payment_method": None,
        }

    return {
        "subscription": {
            "plan_type": subscription.plan_type,
            "status": subscription.status,
            "monthly_minutes_limit": subscription.monthly_minutes_limit,
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "cancel_at_period_end": subscription.canceled_at is not None,
        },
        "payment_method": None,  # TODO: Fetch from Stripe
    }


@router.post("/checkout")
async def create_checkout_session(
    data: CheckoutRequest,
    user: User = Depends(get_current_user),
):
    """
    Create Stripe checkout session for subscription.

    NOT IMPLEMENTED - Returns 501.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Stripe integration not yet implemented. Coming soon!",
    )


@router.post("/portal")
async def create_portal_session(
    data: PortalRequest,
    user: User = Depends(get_current_user),
):
    """
    Create Stripe customer portal session.

    NOT IMPLEMENTED - Returns 501.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Stripe integration not yet implemented. Coming soon!",
    )


@router.post("/purchase-minutes")
async def purchase_additional_minutes(
    data: PurchaseMinutesRequest,
    user: User = Depends(get_current_user),
):
    """
    Purchase additional minutes.

    NOT IMPLEMENTED - Returns 501.
    """
    # Calculate amounts
    minutes_to_add = data.quantity * 20
    amount_jpy = data.quantity * 1000

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "message": "Stripe integration not yet implemented. Coming soon!",
            "preview": {
                "minutes_to_add": minutes_to_add,
                "amount_jpy": amount_jpy,
            },
        },
    )


@router.get("/invoices")
async def get_invoices(
    page: int = 1,
    limit: int = 10,
    user: User = Depends(get_current_user),
):
    """
    Get payment/invoice history.

    Returns empty list until Stripe is integrated.
    """
    return {
        "invoices": [],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": 0,
            "total_pages": 0,
        },
    }


@router.post("/webhooks/stripe")
async def stripe_webhook():
    """
    Stripe webhook endpoint.

    NOT IMPLEMENTED - Placeholder.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Stripe webhook not yet implemented",
    )
