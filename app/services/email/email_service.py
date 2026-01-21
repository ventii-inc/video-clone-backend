"""Email service for sending notifications."""

import re
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

import boto3
from aiosmtplib import SMTP
from botocore.exceptions import ClientError

from app.services.email.email_config import (
    EmailProvider,
    ses_settings,
    smtp_settings,
)
from app.utils.logger import logger


@dataclass
class TrainingCompletionData:
    """Data for training completion email."""

    user_name: str
    model_name: str
    model_type: str  # "video" or "voice"
    dashboard_url: Optional[str] = None


class EmailService:
    """Email service supporting both SMTP and AWS SES."""

    def __init__(self, provider: EmailProvider):
        """
        Initialize email service with specified provider.

        Args:
            provider: Email provider to use (REQUIRED)
        """
        self.provider = provider
        self._ses_client = None

        if self.provider == EmailProvider.AWS_SES:
            self._ses_client = boto3.client(
                "ses",
                region_name=ses_settings.AWS_REGION,
                aws_access_key_id=ses_settings.AWS_ACCESS_KEY_ID or None,
                aws_secret_access_key=ses_settings.AWS_SECRET_ACCESS_KEY or None,
            )

    @staticmethod
    def convert_basic_markdown(text: str) -> str:
        """Convert basic markdown to HTML."""
        # Bold
        text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
        # Color
        text = re.sub(
            r"\{color:(.*?)\}(.*?)\{/color\}", r'<span style="color:\1">\2</span>', text
        )
        # Size
        text = re.sub(
            r"\{size:(.*?)\}(.*?)\{/size\}",
            r'<span style="font-size:\1">\2</span>',
            text,
        )
        # Newlines
        text = text.replace("\n", "<br>")
        return text

    async def send_email(
        self,
        to_email: str,
        subject: str,
        content: str,
        cc_email: Optional[list[str]] = None,
    ) -> bool:
        """Send email using configured provider."""
        if self.provider == EmailProvider.AWS_SES:
            return await self._send_email_ses(to_email, subject, content, cc_email)
        else:
            return await self._send_email_smtp(to_email, subject, content, cc_email)

    async def _send_email_smtp(
        self,
        to_email: str,
        subject: str,
        content: str,
        cc_email: Optional[list[str]] = None,
    ) -> bool:
        """Send email via Google Workspace SMTP."""
        try:
            html_content = f"""
            <html>
                <body>
                    {self.convert_basic_markdown(content)}
                </body>
            </html>
            """

            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = formataddr(
                (smtp_settings.SEND_FROM_NAME, smtp_settings.SMTP_USER)
            )
            message["To"] = to_email

            if cc_email:
                message["Cc"] = ", ".join(cc_email)

            text_part = MIMEText(content, "plain")
            html_part = MIMEText(html_content, "html")
            message.attach(text_part)
            message.attach(html_part)

            async with SMTP(
                hostname=smtp_settings.SMTP_HOST,
                port=smtp_settings.SMTP_PORT,
                use_tls=True,
            ) as smtp:
                await smtp.login(smtp_settings.SMTP_USER, smtp_settings.SMTP_PASSWORD)
                await smtp.send_message(message)

            logger.info(f"SMTP Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"SMTP Error sending email: {str(e)}")
            return False

    async def _send_email_ses(
        self,
        to_email: str,
        subject: str,
        content: str,
        cc_email: Optional[list[str]] = None,
    ) -> bool:
        """Send email via AWS SES."""
        try:
            html_content = f"""
            <html>
                <body>
                    {self.convert_basic_markdown(content)}
                </body>
            </html>
            """

            destination = {"ToAddresses": [to_email]}
            if cc_email:
                destination["CcAddresses"] = cc_email

            response = self._ses_client.send_email(
                Source=f"{ses_settings.SEND_FROM_NAME} <{ses_settings.SES_FROM_EMAIL}>",
                Destination=destination,
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": content, "Charset": "UTF-8"},
                        "Html": {"Data": html_content, "Charset": "UTF-8"},
                    },
                },
            )

            logger.info(f"SES Email sent successfully. MessageId: {response['MessageId']}")
            return True

        except ClientError as e:
            logger.error(f"SES Error sending email: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return False

    async def send_training_completion_email(
        self,
        to_email: str,
        data: TrainingCompletionData,
    ) -> bool:
        """
        Send training completion notification email.

        Args:
            to_email: Recipient email address
            data: Training completion data

        Returns:
            True if email sent successfully, False otherwise
        """
        model_type_display = "Video Avatar" if data.model_type == "video" else "Voice Model"
        subject = f"Your {model_type_display} Training is Complete!"

        dashboard_section = ""
        if data.dashboard_url:
            dashboard_section = f"""
                <p>
                    <a href="{data.dashboard_url}" class="button">View in Dashboard</a>
                </p>
                <p style="font-size: 12px; color: #666;">
                    Or copy this link: <a href="{data.dashboard_url}">{data.dashboard_url}</a>
                </p>
            """

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
        .button {{
            display: inline-block;
            padding: 12px 24px;
            background: #667eea;
            color: white !important;
            text-decoration: none;
            border-radius: 6px;
            margin: 20px 0;
        }}
        .model-info {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #667eea;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #666;
            font-size: 12px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Training Complete!</h1>
        </div>
        <div class="content">
            <p>Hi {data.user_name},</p>

            <p>Great news! Your {model_type_display.lower()} has finished training and is now ready to use.</p>

            <div class="model-info">
                <strong>Model Details:</strong><br>
                <strong>Name:</strong> {data.model_name}<br>
                <strong>Type:</strong> {model_type_display}
            </div>

            {dashboard_section}

            <p>You can now start generating videos using your new {model_type_display.lower()}.</p>

            <div class="footer">
                --------------------------<br>
                Ventii Video Clone<br>
                <a href="https://ventii.jp/">https://ventii.jp/</a><br>
                --------------------------
            </div>
        </div>
    </div>
</body>
</html>
"""

        if self.provider == EmailProvider.AWS_SES:
            return await self._send_html_email_ses(to_email, subject, html_content)
        else:
            return await self._send_html_email_smtp(to_email, subject, html_content)

    async def _send_html_email_smtp(
        self,
        to_email: str,
        subject: str,
        html_content: str,
    ) -> bool:
        """Send HTML email via SMTP."""
        try:
            message = MIMEMultipart()
            message["Subject"] = subject
            message["From"] = formataddr(
                (smtp_settings.SEND_FROM_NAME, smtp_settings.SMTP_USER)
            )
            message["To"] = to_email

            message.attach(MIMEText(html_content, "html", "utf-8"))

            async with SMTP(
                hostname=smtp_settings.SMTP_HOST,
                port=smtp_settings.SMTP_PORT,
                use_tls=True,
            ) as smtp:
                await smtp.login(smtp_settings.SMTP_USER, smtp_settings.SMTP_PASSWORD)
                await smtp.send_message(message)

            logger.info(f"SMTP training completion email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"SMTP error sending training completion email to {to_email}: {str(e)}")
            return False

    async def _send_html_email_ses(
        self,
        to_email: str,
        subject: str,
        html_content: str,
    ) -> bool:
        """Send HTML email via SES."""
        try:
            response = self._ses_client.send_email(
                Source=f"{ses_settings.SEND_FROM_NAME} <{ses_settings.SES_FROM_EMAIL}>",
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html_content, "Charset": "UTF-8"}},
                },
            )

            logger.info(
                f"SES training completion email sent to {to_email}, MessageId: {response['MessageId']}"
            )
            return True

        except ClientError as e:
            logger.error(
                f"SES error sending training completion email to {to_email}: {e.response['Error']['Message']}"
            )
            return False
        except Exception as e:
            logger.error(f"Error sending training completion email to {to_email}: {str(e)}")
            return False


# Singleton cache per provider
_email_service_cache: dict[EmailProvider, EmailService] = {}


def get_email_service(provider: EmailProvider) -> EmailService:
    """
    Get or create EmailService instance (singleton per provider).

    Args:
        provider: Email provider to use

    Returns:
        Cached EmailService instance for the specified provider

    Example:
        # Use Google Workspace SMTP
        email_service = get_email_service(EmailProvider.GOOGLE_WORKSPACE)

        # Use AWS SES
        email_service = get_email_service(EmailProvider.AWS_SES)
    """
    if provider not in _email_service_cache:
        _email_service_cache[provider] = EmailService(provider)

    return _email_service_cache[provider]
