"""Email service configuration."""

from pydantic_settings import BaseSettings


class SESSettings(BaseSettings):
    """AWS SES configuration."""

    AWS_REGION: str = "ap-northeast-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    SES_FROM_EMAIL: str = "support@ventii.jp"
    SEND_FROM_NAME: str = "Ventii Video Clone"

    class Config:
        env_prefix = "EMAIL_"


ses_settings = SESSettings()
