"""S3 service module for media storage"""

from app.services.s3.s3_config import S3Settings, s3_settings
from app.services.s3.s3_service import S3Service, s3_service

__all__ = ["S3Settings", "s3_settings", "S3Service", "s3_service"]
