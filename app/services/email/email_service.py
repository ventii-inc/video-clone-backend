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


@dataclass
class TrainingFailureData:
    """Data for training failure email."""

    user_name: str
    model_name: str
    model_type: str  # "video" or "voice"
    error_message: Optional[str] = None
    dashboard_url: Optional[str] = None


@dataclass
class VideoGenerationCompletionData:
    """Data for video generation completion email."""

    user_name: str
    video_title: str
    duration_seconds: Optional[int] = None
    video_url: Optional[str] = None
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
        model_type_display = "ビデオアバター" if data.model_type == "video" else "ボイスモデル"
        subject = f"{model_type_display}のトレーニングが完了しました"

        dashboard_section = ""
        if data.dashboard_url:
            dashboard_section = f"""
                <p>
                    <a href="{data.dashboard_url}" class="button">ダッシュボードで確認</a>
                </p>
                <p style="font-size: 12px; color: #666;">
                    リンク: <a href="{data.dashboard_url}">{data.dashboard_url}</a>
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
            <h1>トレーニング完了</h1>
        </div>
        <div class="content">
            <p>{data.user_name} 様</p>

            <p>{model_type_display}のトレーニングが完了し、ご利用いただける状態になりました。</p>

            <div class="model-info">
                <strong>モデル詳細:</strong><br>
                <strong>名前:</strong> {data.model_name}<br>
                <strong>種類:</strong> {model_type_display}
            </div>

            {dashboard_section}

            <p>新しい{model_type_display}を使って、動画の生成を開始できます。</p>

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

    async def send_training_failure_email(
        self,
        to_email: str,
        data: TrainingFailureData,
    ) -> bool:
        """
        Send training failure notification email.

        Args:
            to_email: Recipient email address
            data: Training failure data

        Returns:
            True if email sent successfully, False otherwise
        """
        model_type_display = "ビデオアバター" if data.model_type == "video" else "ボイスモデル"
        subject = f"{model_type_display}のトレーニングが失敗しました"

        error_section = ""
        if data.error_message:
            error_section = f"""
                <div class="error-message">
                    <strong>エラー内容:</strong><br>
                    {data.error_message}
                </div>
            """

        dashboard_section = ""
        if data.dashboard_url:
            dashboard_section = f"""
                <p>
                    <a href="{data.dashboard_url}" class="button">ダッシュボードで確認</a>
                </p>
                <p style="font-size: 12px; color: #666;">
                    リンク: <a href="{data.dashboard_url}">{data.dashboard_url}</a>
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
        .header {{ background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
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
            border-left: 4px solid #e74c3c;
        }}
        .error-message {{
            background: #fdf2f2;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
            color: #c0392b;
            font-family: monospace;
            font-size: 14px;
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
            <h1>トレーニング失敗</h1>
        </div>
        <div class="content">
            <p>{data.user_name} 様</p>

            <p>{model_type_display}のトレーニング中にエラーが発生しました。</p>

            <div class="model-info">
                <strong>モデル詳細:</strong><br>
                <strong>名前:</strong> {data.model_name}<br>
                <strong>種類:</strong> {model_type_display}<br>
                <strong>状態:</strong> 失敗
                {error_section}
            </div>

            <p>別の動画をアップロードして、再度お試しください。顔がはっきり映っている動画をご使用ください。</p>

            {dashboard_section}

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
                f"SES training failure email sent to {to_email}, MessageId: {response['MessageId']}"
            )
            return True

        except ClientError as e:
            logger.error(
                f"SES error sending training failure email to {to_email}: {e.response['Error']['Message']}"
            )
            return False
        except Exception as e:
            logger.error(f"Error sending training failure email to {to_email}: {str(e)}")
            return False

    async def send_video_generation_completion_email(
        self,
        to_email: str,
        data: VideoGenerationCompletionData,
    ) -> bool:
        """
        Send video generation completion notification email.

        Args:
            to_email: Recipient email address
            data: Video generation completion data

        Returns:
            True if email sent successfully, False otherwise
        """
        subject = "動画の生成が完了しました"

        duration_display = ""
        if data.duration_seconds:
            minutes = data.duration_seconds // 60
            seconds = data.duration_seconds % 60
            if minutes > 0:
                duration_display = f"{minutes}分{seconds}秒"
            else:
                duration_display = f"{seconds}秒"

        video_section = ""
        if data.video_url:
            video_section = f"""
                <p>
                    <a href="{data.video_url}" class="button">動画を見る</a>
                </p>
            """

        dashboard_section = ""
        if data.dashboard_url:
            dashboard_section = f"""
                <p>
                    <a href="{data.dashboard_url}" class="button-secondary">ダッシュボードで確認</a>
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
        .header {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
        .button {{
            display: inline-block;
            padding: 12px 24px;
            background: #11998e;
            color: white !important;
            text-decoration: none;
            border-radius: 6px;
            margin: 20px 0;
        }}
        .button-secondary {{
            display: inline-block;
            padding: 10px 20px;
            background: #666;
            color: white !important;
            text-decoration: none;
            border-radius: 6px;
            margin: 10px 0;
            font-size: 14px;
        }}
        .video-info {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #11998e;
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
            <h1>動画の生成が完了しました</h1>
        </div>
        <div class="content">
            <p>{data.user_name} 様</p>

            <p>動画の生成が完了し、視聴いただける状態になりました。</p>

            <div class="video-info">
                <strong>動画の詳細:</strong><br>
                <strong>タイトル:</strong> {data.video_title or "無題"}<br>
                {f'<strong>再生時間:</strong> {duration_display}<br>' if duration_display else ''}
            </div>

            {video_section}
            {dashboard_section}

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
                f"SES video generation completion email sent to {to_email}, MessageId: {response['MessageId']}"
            )
            return True

        except ClientError as e:
            logger.error(
                f"SES error sending video generation completion email to {to_email}: {e.response['Error']['Message']}"
            )
            return False
        except Exception as e:
            logger.error(f"Error sending video generation completion email to {to_email}: {str(e)}")
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
