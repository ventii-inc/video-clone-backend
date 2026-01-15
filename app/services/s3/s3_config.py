"""AWS S3 configuration for media storage"""

from pydantic_settings import BaseSettings


class S3Settings(BaseSettings):
    """AWS S3 configuration for video and media storage"""

    AWS_REGION: str = "ap-northeast-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    BUCKET_NAME: str = ""
    PRESIGNED_URL_EXPIRATION: int = 3600  # 1 hour in seconds (default)
    VIDEO_STREAMING_EXPIRATION: int = 21600  # 6 hours for video streaming
    UPLOAD_TIMEOUT: int = 300  # 5 minutes in seconds

    class Config:
        env_prefix = "S3_"


# Initialize settings
s3_settings = S3Settings()
