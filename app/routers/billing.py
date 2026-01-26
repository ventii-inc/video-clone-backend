"""Billing router for Stripe integration"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

import stripe

from app.db import get_db
from app.models import User, Subscription
from app.services.firebase import get_current_user
from app.services.stripe import stripe_service, stripe_settings

logger = logging.getLogger(__name__)

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
    Get current subscription details including default payment method.
    """
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscription = result.scalar_one_or_none()

    # Get payment method if user has a Stripe customer
    payment_method = None
    if subscription and subscription.stripe_customer_id:
        payment_method = await stripe_service.get_default_payment_method(user, db)

    if not subscription:
        return {
            "subscription": None,
            "payment_method": None,
        }

    return {
        "subscription": {
            "plan_type": subscription.plan_type,
            "status": subscription.status,
            "monthly_minutes_limit": subscription.monthly_minutes_limit,
            "current_period_start": (
                subscription.current_period_start.isoformat()
                if subscription.current_period_start
                else None
            ),
            "current_period_end": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None
            ),
            "cancel_at_period_end": subscription.canceled_at is not None,
        },
        "payment_method": payment_method,
    }


@router.post("/checkout")
async def create_checkout_session(
    data: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create Stripe Checkout session for subscription.

    Returns checkout URL to redirect user to Stripe.
    """
    try:
        checkout_url = await stripe_service.create_checkout_session(
            user=user,
            success_url=data.success_url,
            cancel_url=data.cancel_url,
            db=db,
        )
        return {"checkout_url": checkout_url}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except stripe.StripeError as e:
        logger.error(f"Stripe error creating checkout session: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service error. Please try again.",
        )


@router.post("/portal")
async def create_portal_session(
    data: PortalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create Stripe Customer Portal session.

    Returns portal URL for managing subscription.
    """
    try:
        portal_url = await stripe_service.create_portal_session(
            user=user,
            return_url=data.return_url,
            db=db,
        )
        return {"portal_url": portal_url}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except stripe.StripeError as e:
        logger.error(f"Stripe error creating portal session: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service error. Please try again.",
        )


@router.post("/purchase-minutes")
async def purchase_additional_minutes(
    data: PurchaseMinutesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Purchase additional minutes.

    Each unit = 20 minutes = ¥1,000
    Returns checkout URL to redirect user to Stripe.
    """
    if data.quantity < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be at least 1",
        )

    if data.quantity > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum quantity is 100 units per purchase",
        )

    try:
        checkout_url = await stripe_service.create_minutes_checkout_session(
            user=user,
            quantity=data.quantity,
            success_url=data.success_url,
            cancel_url=data.cancel_url,
            db=db,
        )

        minutes_to_add = data.quantity * stripe_settings.minutes_pack_quantity
        amount_jpy = data.quantity * stripe_settings.minutes_pack_price_jpy

        return {
            "checkout_url": checkout_url,
            "preview": {
                "minutes_to_add": minutes_to_add,
                "amount_jpy": amount_jpy,
            },
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except stripe.StripeError as e:
        logger.error(f"Stripe error creating minutes checkout: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service error. Please try again.",
        )


@router.get("/invoices")
async def get_invoices(
    page: int = 1,
    limit: int = 10,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get payment/invoice history from Stripe.
    """
    if limit > 100:
        limit = 100

    invoices = await stripe_service.get_invoices(user, limit, db)

    # Simple pagination (Stripe handles this differently, but keeping API compatible)
    start = (page - 1) * limit
    end = start + limit
    paginated = invoices[start:end]

    return {
        "invoices": paginated,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": len(invoices),
            "total_pages": (len(invoices) + limit - 1) // limit if invoices else 0,
        },
    }


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Stripe webhook endpoint.

    Handles events from Stripe to update subscription status.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    try:
        event = stripe_service.construct_webhook_event(payload, signature)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload",
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    logger.info(f"Received Stripe webhook: {event.type}")

    try:
        if event.type == "checkout.session.completed":
            await stripe_service.handle_checkout_completed(event.data.object, db)

        elif event.type == "customer.subscription.updated":
            await stripe_service.handle_subscription_updated(event.data.object, db)

        elif event.type == "customer.subscription.deleted":
            await stripe_service.handle_subscription_deleted(event.data.object, db)

        elif event.type == "invoice.paid":
            await stripe_service.handle_invoice_paid(event.data.object, db)

        elif event.type == "invoice.payment_failed":
            await stripe_service.handle_invoice_payment_failed(event.data.object, db)

        else:
            logger.debug(f"Unhandled webhook event type: {event.type}")

    except Exception as e:
        logger.error(f"Error handling webhook {event.type}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing error: {str(e)}",
        )

    return {"status": "success"}


@router.get("/prices")
async def get_prices():
    """
    Get current pricing information.

    Public endpoint - no authentication required.
    """
    return {
        "subscription": {
            "name": "Standard Plan",
            "price_jpy": stripe_settings.subscription_monthly_price_jpy,
            "minutes_per_month": stripe_settings.subscription_monthly_minutes,
            "billing_period": "monthly",
        },
        "minutes_pack": {
            "name": "Additional Minutes",
            "price_jpy": stripe_settings.minutes_pack_price_jpy,
            "minutes": stripe_settings.minutes_pack_quantity,
        },
    }
