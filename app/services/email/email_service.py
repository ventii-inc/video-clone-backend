"""Email service for sending notifications via AWS SES."""

from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.services.email.email_config import ses_settings
from app.utils.logger import logger


@dataclass
class TrainingCompletionData:
    """Data for training completion email."""

    user_name: str
    model_name: str
    model_type: str  # "video" or "voice"
    dashboard_url: Optional[str] = None


class EmailService:
    """Email service using AWS SES."""

    def __init__(self):
        """Initialize email service with AWS SES client."""
        self._ses_client = boto3.client(
            "ses",
            region_name=ses_settings.AWS_REGION,
            aws_access_key_id=ses_settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=ses_settings.AWS_SECRET_ACCESS_KEY or None,
        )

    async def send_email(
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
                    {content.replace(chr(10), "<br>")}
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


_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """
    Get or create EmailService instance (singleton).

    Returns:
        Cached EmailService instance

    Example:
        email_service = get_email_service()
        await email_service.send_email("user@example.com", "Subject", "Content")
    """
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
