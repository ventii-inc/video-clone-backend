"""Stripe service for handling payments and subscriptions"""

import logging
from datetime import datetime
from typing import Optional

import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Subscription, PaymentHistory
from app.models.subscription import PlanType, SubscriptionStatus
from app.models.payment_history import PaymentType, PaymentStatus
from app.services.stripe.stripe_config import stripe_settings
from app.services.usage_service import usage_service

logger = logging.getLogger(__name__)


class StripeService:
    """Service for Stripe payment operations"""

    def __init__(self):
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of Stripe API key"""
        if not self._initialized:
            if not stripe_settings.stripe_secret_key:
                raise ValueError("STRIPE_SECRET_KEY not configured")
            stripe.api_key = stripe_settings.stripe_secret_key
            self._initialized = True

    async def get_or_create_customer(
        self,
        user: User,
        db: AsyncSession,
    ) -> str:
        """Get existing Stripe customer or create new one"""
        self._ensure_initialized()

        # Check if user has subscription with customer ID
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if subscription and subscription.stripe_customer_id:
            return subscription.stripe_customer_id

        # Create new Stripe customer
        customer = stripe.Customer.create(
            email=user.email,
            name=user.name,
            metadata={"user_id": str(user.id)},
        )

        # Create or update subscription record with customer ID
        if not subscription:
            subscription = Subscription(
                user_id=user.id,
                stripe_customer_id=customer.id,
            )
            db.add(subscription)
        else:
            subscription.stripe_customer_id = customer.id

        await db.commit()
        logger.info(f"Created Stripe customer {customer.id} for user {user.id}")

        return customer.id

    async def create_checkout_session(
        self,
        user: User,
        success_url: str,
        cancel_url: str,
        db: AsyncSession,
    ) -> str:
        """Create Stripe Checkout session for subscription"""
        self._ensure_initialized()

        if not stripe_settings.stripe_price_standard:
            raise ValueError("STRIPE_PRICE_STANDARD not configured")

        customer_id = await self.get_or_create_customer(user, db)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[
                {
                    "price": stripe_settings.stripe_price_standard,
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": str(user.id),
                "type": "subscription",
            },
            subscription_data={
                "metadata": {
                    "user_id": str(user.id),
                }
            },
        )

        logger.info(f"Created checkout session {session.id} for user {user.id}")
        return session.url

    async def create_minutes_checkout_session(
        self,
        user: User,
        quantity: int,
        success_url: str,
        cancel_url: str,
        db: AsyncSession,
    ) -> str:
        """Create Stripe Checkout session for purchasing additional minutes"""
        self._ensure_initialized()

        if not stripe_settings.stripe_price_minutes:
            raise ValueError("STRIPE_PRICE_MINUTES not configured")

        customer_id = await self.get_or_create_customer(user, db)
        minutes_to_add = quantity * stripe_settings.minutes_pack_quantity

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            line_items=[
                {
                    "price": stripe_settings.stripe_price_minutes,
                    "quantity": quantity,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": str(user.id),
                "type": "minutes_purchase",
                "minutes_to_add": str(minutes_to_add),
                "quantity": str(quantity),
            },
        )

        logger.info(
            f"Created minutes checkout session {session.id} for user {user.id}, "
            f"quantity={quantity}, minutes={minutes_to_add}"
        )
        return session.url

    async def create_portal_session(
        self,
        user: User,
        return_url: str,
        db: AsyncSession,
    ) -> str:
        """Create Stripe Customer Portal session"""
        self._ensure_initialized()

        customer_id = await self.get_or_create_customer(user, db)

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )

        logger.info(f"Created portal session for user {user.id}")
        return session.url

    def construct_webhook_event(
        self,
        payload: bytes,
        signature: str,
    ) -> stripe.Event:
        """Construct and verify webhook event"""
        self._ensure_initialized()

        if not stripe_settings.stripe_webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET not configured")

        return stripe.Webhook.construct_event(
            payload,
            signature,
            stripe_settings.stripe_webhook_secret,
        )

    async def handle_checkout_completed(
        self,
        session: stripe.checkout.Session,
        db: AsyncSession,
    ) -> None:
        """Handle checkout.session.completed event"""
        user_id = int(session.metadata.get("user_id"))
        checkout_type = session.metadata.get("type")

        logger.info(
            f"Processing checkout completed: user_id={user_id}, type={checkout_type}"
        )

        if checkout_type == "subscription":
            await self._handle_subscription_checkout(session, user_id, db)
        elif checkout_type == "minutes_purchase":
            await self._handle_minutes_checkout(session, user_id, db)

    async def _handle_subscription_checkout(
        self,
        session: stripe.checkout.Session,
        user_id: int,
        db: AsyncSession,
    ) -> None:
        """Handle subscription checkout completion"""
        stripe_subscription = stripe.Subscription.retrieve(session.subscription)

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if subscription:
            subscription.stripe_subscription_id = stripe_subscription.id
            subscription.plan_type = PlanType.STANDARD.value
            subscription.status = SubscriptionStatus.ACTIVE.value
            subscription.monthly_minutes_limit = stripe_settings.subscription_monthly_minutes
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_subscription.current_period_start
            )
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_subscription.current_period_end
            )
            subscription.canceled_at = None

        await db.commit()
        logger.info(f"Activated subscription for user {user_id}")

    async def _handle_minutes_checkout(
        self,
        session: stripe.checkout.Session,
        user_id: int,
        db: AsyncSession,
    ) -> None:
        """Handle minutes purchase checkout completion"""
        minutes_to_add = int(session.metadata.get("minutes_to_add", 0))
        quantity = int(session.metadata.get("quantity", 1))
        amount = quantity * stripe_settings.minutes_pack_price_jpy

        # Add minutes to user's account
        await usage_service.add_purchased_minutes(user_id, minutes_to_add, db)

        # Record payment history
        payment = PaymentHistory(
            user_id=user_id,
            stripe_payment_intent_id=session.payment_intent,
            payment_type=PaymentType.ADDITIONAL_MINUTES.value,
            amount_cents=amount,  # JPY doesn't use cents, but field is named this way
            currency="jpy",
            minutes_purchased=minutes_to_add,
            status=PaymentStatus.SUCCEEDED.value,
        )
        db.add(payment)
        await db.commit()

        logger.info(f"Added {minutes_to_add} minutes for user {user_id}")

    async def handle_subscription_updated(
        self,
        subscription: stripe.Subscription,
        db: AsyncSession,
    ) -> None:
        """Handle customer.subscription.updated event"""
        user_id = subscription.metadata.get("user_id")
        if not user_id:
            logger.warning(f"No user_id in subscription metadata: {subscription.id}")
            return

        user_id = int(user_id)

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub_record = result.scalar_one_or_none()

        if not sub_record:
            logger.warning(f"No subscription record for user {user_id}")
            return

        # Update subscription details
        sub_record.status = subscription.status
        sub_record.current_period_start = datetime.fromtimestamp(
            subscription.current_period_start
        )
        sub_record.current_period_end = datetime.fromtimestamp(
            subscription.current_period_end
        )

        if subscription.canceled_at:
            sub_record.canceled_at = datetime.fromtimestamp(subscription.canceled_at)

        await db.commit()
        logger.info(f"Updated subscription for user {user_id}: status={subscription.status}")

    async def handle_subscription_deleted(
        self,
        subscription: stripe.Subscription,
        db: AsyncSession,
    ) -> None:
        """Handle customer.subscription.deleted event"""
        user_id = subscription.metadata.get("user_id")
        if not user_id:
            logger.warning(f"No user_id in subscription metadata: {subscription.id}")
            return

        user_id = int(user_id)

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub_record = result.scalar_one_or_none()

        if sub_record:
            sub_record.plan_type = PlanType.FREE.value
            sub_record.status = SubscriptionStatus.CANCELED.value
            sub_record.monthly_minutes_limit = 0
            sub_record.stripe_subscription_id = None
            sub_record.canceled_at = datetime.utcnow()

            await db.commit()
            logger.info(f"Canceled subscription for user {user_id}")

    async def handle_invoice_paid(
        self,
        invoice: stripe.Invoice,
        db: AsyncSession,
    ) -> None:
        """Handle invoice.paid event"""
        if not invoice.subscription:
            return  # Not a subscription invoice

        # Get user from customer
        customer_id = invoice.customer
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        sub_record = result.scalar_one_or_none()

        if not sub_record:
            logger.warning(f"No subscription for customer {customer_id}")
            return

        # Record payment
        payment = PaymentHistory(
            user_id=sub_record.user_id,
            stripe_payment_intent_id=invoice.payment_intent,
            stripe_invoice_id=invoice.id,
            payment_type=PaymentType.SUBSCRIPTION.value,
            amount_cents=invoice.amount_paid,
            currency=invoice.currency,
            status=PaymentStatus.SUCCEEDED.value,
        )
        db.add(payment)
        await db.commit()

        logger.info(f"Recorded subscription payment for user {sub_record.user_id}")

    async def handle_invoice_payment_failed(
        self,
        invoice: stripe.Invoice,
        db: AsyncSession,
    ) -> None:
        """Handle invoice.payment_failed event"""
        customer_id = invoice.customer

        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        sub_record = result.scalar_one_or_none()

        if sub_record:
            sub_record.status = SubscriptionStatus.PAST_DUE.value
            await db.commit()
            logger.warning(f"Payment failed for user {sub_record.user_id}")

    async def get_default_payment_method(
        self,
        user: User,
        db: AsyncSession,
    ) -> Optional[dict]:
        """Get user's default payment method from Stripe"""
        self._ensure_initialized()

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_customer_id:
            return None

        try:
            customer = stripe.Customer.retrieve(subscription.stripe_customer_id)

            # Get default payment method
            default_pm_id = customer.invoice_settings.default_payment_method
            if not default_pm_id:
                # Try to get from default source (legacy)
                default_pm_id = customer.default_source

            if not default_pm_id:
                return None

            payment_method = stripe.PaymentMethod.retrieve(default_pm_id)

            if payment_method.type == "card":
                card = payment_method.card
                return {
                    "type": "card",
                    "brand": card.brand,
                    "last4": card.last4,
                    "exp_month": card.exp_month,
                    "exp_year": card.exp_year,
                }

            return {"type": payment_method.type}

        except stripe.StripeError as e:
            logger.error(f"Error fetching payment method: {e}")
            return None

    async def get_invoices(
        self,
        user: User,
        limit: int,
        db: AsyncSession,
    ) -> list[dict]:
        """Get user's invoices from Stripe"""
        self._ensure_initialized()

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_customer_id:
            return []

        try:
            invoices = stripe.Invoice.list(
                customer=subscription.stripe_customer_id,
                limit=limit,
            )

            return [
                {
                    "id": inv.id,
                    "amount": inv.amount_paid,
                    "currency": inv.currency,
                    "status": inv.status,
                    "created_at": datetime.fromtimestamp(inv.created).isoformat(),
                    "invoice_url": inv.hosted_invoice_url,
                    "invoice_pdf": inv.invoice_pdf,
                }
                for inv in invoices.data
            ]
        except stripe.StripeError as e:
            logger.error(f"Error fetching invoices: {e}")
            return []


# Global instance
stripe_service = StripeService()
