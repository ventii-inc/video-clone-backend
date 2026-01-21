"""Email service configuration."""

from enum import Enum

from pydantic_settings import BaseSettings


class EmailProvider(str, Enum):
    """Email provider options."""

    GOOGLE_WORKSPACE = "google_workspace"
    AWS_SES = "aws_ses"


class SMTPSettings(BaseSettings):
    """Google Workspace SMTP configuration."""

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = "support@ventii.jp"
    SMTP_PASSWORD: str = ""
    SEND_FROM_NAME: str = "Ventii Video Clone"

    class Config:
        env_prefix = "EMAIL_"


class SESSettings(BaseSettings):
    """AWS SES configuration."""

    AWS_REGION: str = "ap-northeast-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    SES_FROM_EMAIL: str = "support@ventii.jp"
    SEND_FROM_NAME: str = "Ventii Video Clone"

    class Config:
        env_prefix = "EMAIL_"


smtp_settings = SMTPSettings()
ses_settings = SESSettings()
