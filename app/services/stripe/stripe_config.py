"""Stripe configuration settings"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class StripeSettings(BaseSettings):
    """Stripe configuration loaded from environment variables"""

    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_standard: str = ""  # Price ID for standard subscription
    stripe_price_minutes: str = ""  # Price ID for minutes pack

    # Pricing configuration
    subscription_monthly_price_jpy: int = 2980
    subscription_monthly_minutes: int = 100
    minutes_pack_price_jpy: int = 1000
    minutes_pack_quantity: int = 20

    class Config:
        env_file = f".env.{os.getenv('ENV', 'local')}"
        extra = "ignore"


@lru_cache
def get_stripe_settings() -> StripeSettings:
    return StripeSettings()


stripe_settings = get_stripe_settings()
