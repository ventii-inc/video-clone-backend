"""Stripe service for handling payments and subscriptions"""

import asyncio
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
            preferred_locales=["ja"],
        )

        # Create or update subscription record with customer ID
        # Status is INCOMPLETE until payment is confirmed via webhook
        if not subscription:
            subscription = Subscription(
                user_id=user.id,
                stripe_customer_id=customer.id,
                status=SubscriptionStatus.INCOMPLETE.value,
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

    async def create_shot_plan_checkout_session(
        self,
        user: User,
        success_url: str,
        cancel_url: str,
        db: AsyncSession,
    ) -> str:
        """Create Stripe Checkout session for Shot plan one-time purchase"""
        self._ensure_initialized()

        if not stripe_settings.stripe_price_shot:
            raise ValueError("STRIPE_PRICE_SHOT not configured")

        customer_id = await self.get_or_create_customer(user, db)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            line_items=[
                {
                    "price": stripe_settings.stripe_price_shot,
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": str(user.id),
                "type": "shot_plan",
            },
        )

        logger.info(f"Created Shot plan checkout session {session.id} for user {user.id}")
        return session.url

    async def process_auto_charge(
        self,
        user_id: int,
        db: AsyncSession,
    ) -> dict:
        """Process automatic charge for Standard plan user when minutes exhausted.

        Returns dict with success status and details.
        """
        self._ensure_initialized()

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return {"success": False, "error": "No subscription found"}

        if subscription.plan_type != PlanType.STANDARD.value:
            return {"success": False, "error": "Auto-charge only available for Standard plan"}

        if not subscription.auto_charge_enabled:
            return {"success": False, "error": "Auto-charge is disabled"}

        if not subscription.stripe_customer_id:
            return {"success": False, "error": "No payment method on file"}

        try:
            # Create payment intent and charge immediately
            payment_intent = stripe.PaymentIntent.create(
                amount=stripe_settings.auto_charge_price_jpy,
                currency="jpy",
                customer=subscription.stripe_customer_id,
                off_session=True,
                confirm=True,
                metadata={
                    "user_id": str(user_id),
                    "type": "auto_charge",
                },
            )

            if payment_intent.status == "succeeded":
                # Add minutes to user's account
                await usage_service.add_purchased_minutes(
                    user_id, stripe_settings.auto_charge_minutes, db
                )

                # Add bonus trainings
                from app.services.training_usage_service import training_usage_service
                await training_usage_service.add_bonus_trainings(
                    user_id,
                    video_trainings=stripe_settings.auto_charge_bonus_trainings,
                    voice_trainings=stripe_settings.auto_charge_bonus_trainings,
                    db=db,
                )

                # Record payment history
                payment = PaymentHistory(
                    user_id=user_id,
                    stripe_payment_intent_id=payment_intent.id,
                    payment_type=PaymentType.AUTO_CHARGE.value,
                    amount_cents=stripe_settings.auto_charge_price_jpy,
                    currency="jpy",
                    minutes_purchased=stripe_settings.auto_charge_minutes,
                    status=PaymentStatus.SUCCEEDED.value,
                )
                db.add(payment)
                await db.commit()

                logger.info(
                    f"Auto-charge successful for user {user_id}: "
                    f"{stripe_settings.auto_charge_minutes} minutes added, "
                    f"+{stripe_settings.auto_charge_bonus_trainings} bonus trainings"
                )

                return {
                    "success": True,
                    "minutes_added": stripe_settings.auto_charge_minutes,
                    "amount_charged": stripe_settings.auto_charge_price_jpy,
                    "bonus_trainings": stripe_settings.auto_charge_bonus_trainings,
                }
            else:
                logger.warning(f"Auto-charge payment intent status: {payment_intent.status}")
                return {"success": False, "error": f"Payment status: {payment_intent.status}"}

        except stripe.CardError as e:
            logger.warning(f"Auto-charge card error for user {user_id}: {e}")
            return {"success": False, "error": f"Card declined: {e.user_message}"}
        except stripe.StripeError as e:
            logger.error(f"Auto-charge Stripe error for user {user_id}: {e}")
            return {"success": False, "error": str(e)}

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

    def _get_session_attr(self, session, key: str, default=None):
        """Safely get attribute from session (works for both dict and StripeObject)"""
        if isinstance(session, dict):
            return session.get(key, default)
        return getattr(session, key, default)

    async def _update_payment_method_cache(
        self,
        subscription: Subscription,
        customer_id: str,
    ) -> None:
        """Fetch payment method from Stripe and cache in DB.

        Note: Does not commit - caller is responsible for committing.
        """
        self._ensure_initialized()

        try:
            # Run Stripe call in thread pool to avoid blocking
            customer = await asyncio.to_thread(
                stripe.Customer.retrieve, customer_id
            )

            default_pm_id = customer.get("invoice_settings", {}).get("default_payment_method")

            if not default_pm_id:
                # List payment methods as fallback
                pms = await asyncio.to_thread(
                    stripe.PaymentMethod.list,
                    customer=customer_id,
                    type="card",
                    limit=1,
                )
                pm_data = pms.get("data", [])
                if pm_data:
                    pm = pm_data[0]
                    card = pm.get("card", {})
                    subscription.card_brand = card.get("brand")
                    subscription.card_last4 = card.get("last4")
                    subscription.card_exp_month = card.get("exp_month")
                    subscription.card_exp_year = card.get("exp_year")
                    logger.info(f"Cached payment method (fallback) for user {subscription.user_id}")
                return

            pm = await asyncio.to_thread(stripe.PaymentMethod.retrieve, default_pm_id)
            card = pm.get("card", {})
            subscription.card_brand = card.get("brand")
            subscription.card_last4 = card.get("last4")
            subscription.card_exp_month = card.get("exp_month")
            subscription.card_exp_year = card.get("exp_year")
            logger.info(f"Cached payment method for user {subscription.user_id}")

        except stripe.StripeError as e:
            logger.error(f"Error updating payment method cache: {e}")

    async def handle_checkout_completed(
        self,
        session,  # Can be dict or StripeObject
        db: AsyncSession,
    ) -> None:
        """Handle checkout.session.completed event"""
        # Safely access metadata (works for both dict and StripeObject)
        metadata = self._get_session_attr(session, "metadata", {})
        if isinstance(metadata, dict):
            user_id_str = metadata.get("user_id")
            checkout_type = metadata.get("type")
        else:
            user_id_str = getattr(metadata, "user_id", None) or metadata.get("user_id")
            checkout_type = getattr(metadata, "type", None) or metadata.get("type")

        if not user_id_str:
            logger.error(f"No user_id in checkout session metadata: {session}")
            return

        user_id = int(user_id_str)

        logger.info(
            f"Processing checkout completed: user_id={user_id}, type={checkout_type}"
        )

        if checkout_type == "subscription":
            await self._handle_subscription_checkout(session, user_id, db)
        elif checkout_type == "minutes_purchase":
            await self._handle_minutes_checkout(session, user_id, db)
        elif checkout_type == "shot_plan":
            await self._handle_shot_plan_checkout(session, user_id, db)

    async def _handle_subscription_checkout(
        self,
        session,  # Can be dict or StripeObject
        user_id: int,
        db: AsyncSession,
    ) -> None:
        """Handle subscription checkout completion"""
        # Safely get subscription ID
        subscription_id = self._get_session_attr(session, "subscription")

        if not subscription_id:
            logger.error(f"No subscription ID in checkout session for user {user_id}")
            return

        logger.info(f"Retrieving Stripe subscription {subscription_id} for user {user_id}")
        stripe_subscription = stripe.Subscription.retrieve(subscription_id)

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logger.error(f"No subscription record found for user {user_id}")
            return

        # Get billing period - try subscription level first, fallback to items
        # (Stripe 2025-03-31+ moved these to items, but older API versions have them on subscription)
        period_start = stripe_subscription.get("current_period_start")
        period_end = stripe_subscription.get("current_period_end")

        # If not on subscription level, get from items (use dict access to avoid .items() method conflict)
        if not period_start:
            items_data = stripe_subscription.get("items", {}).get("data", [])
            if items_data:
                first_item = items_data[0]
                period_start = first_item.get("current_period_start")
                period_end = first_item.get("current_period_end")

        subscription.stripe_subscription_id = stripe_subscription.get("id")
        subscription.plan_type = PlanType.STANDARD.value
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.monthly_minutes_limit = stripe_settings.subscription_monthly_minutes
        subscription.monthly_video_training_limit = 5  # Standard plan: 5 trainings
        subscription.monthly_voice_training_limit = 5
        subscription.is_lifetime = False
        subscription.is_one_time_purchase = False
        subscription.auto_charge_enabled = True
        if period_start:
            subscription.current_period_start = datetime.fromtimestamp(period_start)
        if period_end:
            subscription.current_period_end = datetime.fromtimestamp(period_end)
        subscription.canceled_at = None

        # Cache payment method info
        await self._update_payment_method_cache(
            subscription,
            subscription.stripe_customer_id,
        )

        await db.commit()
        logger.info(f"Activated subscription for user {user_id}")

    async def _handle_minutes_checkout(
        self,
        session,  # Can be dict or StripeObject
        user_id: int,
        db: AsyncSession,
    ) -> None:
        """Handle minutes purchase checkout completion"""
        # Safely access metadata
        metadata = self._get_session_attr(session, "metadata", {})
        if isinstance(metadata, dict):
            minutes_to_add = int(metadata.get("minutes_to_add", 0))
            quantity = int(metadata.get("quantity", 1))
        else:
            minutes_to_add = int(getattr(metadata, "minutes_to_add", 0) or metadata.get("minutes_to_add", 0))
            quantity = int(getattr(metadata, "quantity", 1) or metadata.get("quantity", 1))

        amount = quantity * stripe_settings.minutes_pack_price_jpy
        payment_intent_id = self._get_session_attr(session, "payment_intent")

        # Add minutes to user's account
        await usage_service.add_purchased_minutes(user_id, minutes_to_add, db)

        # Record payment history
        payment = PaymentHistory(
            user_id=user_id,
            stripe_payment_intent_id=payment_intent_id,
            payment_type=PaymentType.ADDITIONAL_MINUTES.value,
            amount_cents=amount,  # JPY doesn't use cents, but field is named this way
            currency="jpy",
            minutes_purchased=minutes_to_add,
            status=PaymentStatus.SUCCEEDED.value,
        )
        db.add(payment)
        await db.commit()

        logger.info(f"Added {minutes_to_add} minutes for user {user_id}")

    async def _handle_shot_plan_checkout(
        self,
        session,  # Can be dict or StripeObject
        user_id: int,
        db: AsyncSession,
    ) -> None:
        """Handle Shot plan one-time purchase checkout completion"""
        payment_intent_id = self._get_session_attr(session, "payment_intent")

        # Get or create subscription record
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            # Create new subscription for Shot plan
            subscription = Subscription(
                user_id=user_id,
                plan_type=PlanType.SHOT.value,
                status=SubscriptionStatus.ACTIVE.value,
                monthly_minutes_limit=stripe_settings.shot_plan_minutes,
                monthly_video_training_limit=stripe_settings.shot_plan_video_trainings,
                monthly_voice_training_limit=stripe_settings.shot_plan_voice_trainings,
                is_one_time_purchase=True,
                is_lifetime=False,
                auto_charge_enabled=False,
            )
            db.add(subscription)
        else:
            # Upgrade to Shot plan (or add Shot plan credits)
            subscription.plan_type = PlanType.SHOT.value
            subscription.status = SubscriptionStatus.ACTIVE.value
            subscription.monthly_minutes_limit = stripe_settings.shot_plan_minutes
            subscription.monthly_video_training_limit = stripe_settings.shot_plan_video_trainings
            subscription.monthly_voice_training_limit = stripe_settings.shot_plan_voice_trainings
            subscription.is_one_time_purchase = True
            subscription.auto_charge_enabled = False

        # Add minutes to user's account (these never expire for Shot plan)
        await usage_service.add_purchased_minutes(
            user_id, stripe_settings.shot_plan_minutes, db
        )

        # Record payment history
        payment = PaymentHistory(
            user_id=user_id,
            stripe_payment_intent_id=payment_intent_id,
            payment_type=PaymentType.SHOT_PLAN.value,
            amount_cents=stripe_settings.shot_plan_price_jpy,
            currency="jpy",
            minutes_purchased=stripe_settings.shot_plan_minutes,
            status=PaymentStatus.SUCCEEDED.value,
        )
        db.add(payment)
        await db.commit()

        logger.info(
            f"Shot plan activated for user {user_id}: "
            f"{stripe_settings.shot_plan_minutes} minutes, "
            f"{stripe_settings.shot_plan_video_trainings} video trainings, "
            f"{stripe_settings.shot_plan_voice_trainings} voice trainings"
        )

    async def handle_subscription_updated(
        self,
        subscription,  # Can be dict or StripeObject
        db: AsyncSession,
    ) -> None:
        """Handle customer.subscription.updated event"""
        metadata = self._get_session_attr(subscription, "metadata", {})
        user_id = metadata.get("user_id") if isinstance(metadata, dict) else getattr(metadata, "user_id", None)
        sub_id = self._get_session_attr(subscription, "id")

        if not user_id:
            logger.warning(f"No user_id in subscription metadata: {sub_id}")
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
        subscription,  # Can be dict or StripeObject
        db: AsyncSession,
    ) -> None:
        """Handle customer.subscription.deleted event"""
        metadata = self._get_session_attr(subscription, "metadata", {})
        user_id = metadata.get("user_id") if isinstance(metadata, dict) else getattr(metadata, "user_id", None)
        sub_id = self._get_session_attr(subscription, "id")

        if not user_id:
            logger.warning(f"No user_id in subscription metadata: {sub_id}")
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
        invoice,  # Can be dict or StripeObject
        db: AsyncSession,
    ) -> None:
        """Handle invoice.paid event"""
        subscription_id = self._get_session_attr(invoice, "subscription")
        if not subscription_id:
            return  # Not a subscription invoice

        # Get user from customer
        customer_id = self._get_session_attr(invoice, "customer")
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
            stripe_payment_intent_id=self._get_session_attr(invoice, "payment_intent"),
            stripe_invoice_id=self._get_session_attr(invoice, "id"),
            payment_type=PaymentType.SUBSCRIPTION.value,
            amount_cents=self._get_session_attr(invoice, "amount_paid", 0),
            currency=self._get_session_attr(invoice, "currency", "jpy"),
            status=PaymentStatus.SUCCEEDED.value,
        )
        db.add(payment)
        await db.commit()

        logger.info(f"Recorded subscription payment for user {sub_record.user_id}")

    async def handle_invoice_payment_failed(
        self,
        invoice,  # Can be dict or StripeObject
        db: AsyncSession,
    ) -> None:
        """Handle invoice.payment_failed event"""
        customer_id = self._get_session_attr(invoice, "customer")

        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        sub_record = result.scalar_one_or_none()

        if sub_record:
            sub_record.status = SubscriptionStatus.PAST_DUE.value
            await db.commit()
            logger.warning(f"Payment failed for user {sub_record.user_id}")

    async def handle_customer_updated(
        self,
        customer,  # Can be dict or StripeObject
        db: AsyncSession,
    ) -> None:
        """Handle customer.updated event - refresh payment method cache"""
        customer_id = customer.get("id") if isinstance(customer, dict) else customer.id

        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        subscription = result.scalar_one_or_none()

        if subscription:
            await self._update_payment_method_cache(subscription, customer_id)
            await db.commit()
            logger.info(f"Refreshed payment method cache for customer {customer_id}")

    async def get_default_payment_method(
        self,
        user: User,
        db: AsyncSession,
    ) -> Optional[dict]:
        """Get user's default payment method from cached DB data"""
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.card_last4:
            return None

        return {
            "type": "card",
            "brand": subscription.card_brand,
            "last4": subscription.card_last4,
            "exp_month": subscription.card_exp_month,
            "exp_year": subscription.card_exp_year,
        }

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
            logger.info(f"Fetching invoices for customer {subscription.stripe_customer_id}")
            invoices = stripe.Invoice.list(
                customer=subscription.stripe_customer_id,
                limit=limit,
            )

            invoice_list = invoices.get("data", [])
            logger.info(f"Found {len(invoice_list)} invoices for customer {subscription.stripe_customer_id}")

            result_list = []
            for inv in invoice_list:
                created = inv.get("created")
                result_list.append({
                    "id": inv.get("id"),
                    "amount": inv.get("amount_paid"),
                    "currency": inv.get("currency"),
                    "status": inv.get("status"),
                    "created_at": datetime.fromtimestamp(created).isoformat() if created else None,
                    "invoice_url": inv.get("hosted_invoice_url"),
                    "invoice_pdf": inv.get("invoice_pdf"),
                })
            return result_list
        except stripe.StripeError as e:
            logger.error(f"Error fetching invoices: {e}")
            return []


# Global instance
stripe_service = StripeService()
