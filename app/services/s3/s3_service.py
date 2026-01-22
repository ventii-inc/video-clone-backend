"""S3 service for uploading and managing media files"""

import logging
import os
from typing import Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.services.s3.s3_config import S3Settings

logger = logging.getLogger(__name__)


class S3Service:
    """Service for managing S3 operations for media files"""

    def __init__(self):
        """Initialize S3 service - credentials are loaded lazily on first use"""
        self._session = None
        self._config = None

    def _get_settings(self) -> S3Settings:
        """Get fresh settings from environment.

        This ensures settings are read at usage time, not at import time
        when env vars may not be loaded yet.
        """
        return S3Settings()

    def _get_session(self):
        """Get or create aioboto3 session with current credentials.

        This ensures credentials are read from environment at usage time,
        not at import time when env vars may not be loaded yet.
        """
        settings = self._get_settings()
        region = settings.AWS_REGION
        access_key = settings.AWS_ACCESS_KEY_ID
        secret_key = settings.AWS_SECRET_ACCESS_KEY

        # Create new session if credentials changed or not initialized
        if self._session is None or getattr(self, "_cached_access_key", None) != access_key:
            self._session = aioboto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
            self._cached_access_key = access_key
            self._config = Config(
                region_name=region,
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            )
            logger.info(
                f"S3 session initialized with access key: {access_key[:8]}..."
                if access_key
                else "S3 session initialized with empty credentials"
            )

        return self._session, self._config

    @property
    def region(self) -> str:
        return self._get_settings().AWS_REGION

    @property
    def bucket_name(self) -> str:
        return self._get_settings().BUCKET_NAME

    @property
    def presigned_url_expiration(self) -> int:
        return self._get_settings().PRESIGNED_URL_EXPIRATION

    @property
    def upload_timeout(self) -> int:
        return self._get_settings().UPLOAD_TIMEOUT

    async def upload_file(
        self,
        file_path: str,
        s3_key: str,
        content_type: Optional[str] = None,
        storage_class: Optional[str] = None,
    ) -> bool:
        """
        Upload a file to S3

        Args:
            file_path: Local path to the file to upload
            s3_key: S3 key (path) where the file will be stored
            content_type: MIME type of the file (auto-detected if not provided)
            storage_class: S3 storage class (STANDARD, STANDARD_IA, GLACIER, etc.)

        Returns:
            True if upload successful, False otherwise

        Raises:
            FileNotFoundError: If the local file does not exist
            ClientError: If S3 upload fails
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")

        # Auto-detect content type if not provided
        if content_type is None:
            content_type = self._get_content_type(file_path)

        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                extra_args = {"ContentType": content_type}

                # Add cache control for video streaming
                if content_type.startswith("video/") or content_type.startswith("audio/"):
                    extra_args["CacheControl"] = "max-age=31536000"  # 1 year

                # Set storage class if specified
                if storage_class:
                    extra_args["StorageClass"] = storage_class

                logger.info(
                    f"Uploading file {file_path} to s3://{self.bucket_name}/{s3_key}"
                    + (f" (StorageClass: {storage_class})" if storage_class else "")
                )

                await s3_client.upload_file(
                    file_path, self.bucket_name, s3_key, ExtraArgs=extra_args
                )

                logger.info(f"Successfully uploaded {s3_key} to S3")
                return True

        except ClientError as e:
            logger.error(f"Failed to upload {file_path} to S3: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error uploading {file_path} to S3: {e}", exc_info=True)
            raise

    async def upload_fileobj(
        self,
        file_obj,
        s3_key: str,
        content_type: Optional[str] = None,
        storage_class: Optional[str] = None,
    ) -> bool:
        """
        Upload a file-like object to S3

        Args:
            file_obj: File-like object to upload (e.g., from FastAPI UploadFile)
            s3_key: S3 key (path) where the file will be stored
            content_type: MIME type of the file
            storage_class: S3 storage class (STANDARD, STANDARD_IA, GLACIER, etc.)

        Returns:
            True if upload successful, False otherwise

        Raises:
            ClientError: If S3 upload fails
        """
        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                extra_args = {}

                if content_type:
                    extra_args["ContentType"] = content_type
                    # Add cache control for video streaming
                    if content_type.startswith("video/") or content_type.startswith("audio/"):
                        extra_args["CacheControl"] = "max-age=31536000"  # 1 year

                # Set storage class if specified
                if storage_class:
                    extra_args["StorageClass"] = storage_class

                logger.info(f"Uploading file object to s3://{self.bucket_name}/{s3_key}")

                await s3_client.upload_fileobj(
                    file_obj, self.bucket_name, s3_key, ExtraArgs=extra_args if extra_args else None
                )

                logger.info(f"Successfully uploaded {s3_key} to S3")
                return True

        except ClientError as e:
            logger.error(f"Failed to upload file object to S3: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error uploading file object to S3: {e}", exc_info=True)
            raise

    async def generate_presigned_url(
        self, s3_key: str, expiration: Optional[int] = None, content_disposition: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a pre-signed URL for accessing a file from S3

        Args:
            s3_key: S3 key of the file
            expiration: URL expiration time in seconds (uses default if not provided)
            content_disposition: Optional Content-Disposition header (e.g., 'attachment; filename="video.mp4"')

        Returns:
            Pre-signed URL string, or None if generation fails
        """
        if expiration is None:
            expiration = self.presigned_url_expiration

        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                params = {"Bucket": self.bucket_name, "Key": s3_key}
                if content_disposition:
                    params["ResponseContentDisposition"] = content_disposition
                url = await s3_client.generate_presigned_url(
                    "get_object",
                    Params=params,
                    ExpiresIn=expiration,
                )

                logger.debug(f"Generated pre-signed URL for {s3_key}")
                return url

        except ClientError as e:
            logger.error(f"Failed to generate pre-signed URL for {s3_key}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error generating pre-signed URL for {s3_key}: {e}",
                exc_info=True,
            )
            return None

    async def generate_presigned_upload_url(
        self,
        s3_key: str,
        content_type: Optional[str] = None,
        expiration: Optional[int] = None,
    ) -> Optional[str]:
        """
        Generate a pre-signed URL for uploading a file to S3

        Args:
            s3_key: S3 key where the file will be stored
            content_type: MIME type of the file to upload
            expiration: URL expiration time in seconds (uses default if not provided)

        Returns:
            Pre-signed URL string, or None if generation fails
        """
        if expiration is None:
            expiration = self.presigned_url_expiration

        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                params = {"Bucket": self.bucket_name, "Key": s3_key}
                if content_type:
                    params["ContentType"] = content_type

                url = await s3_client.generate_presigned_url(
                    "put_object",
                    Params=params,
                    ExpiresIn=expiration,
                )

                logger.debug(f"Generated pre-signed upload URL for {s3_key}")
                return url

        except ClientError as e:
            logger.error(
                f"Failed to generate pre-signed upload URL for {s3_key}: {e}", exc_info=True
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error generating pre-signed upload URL for {s3_key}: {e}",
                exc_info=True,
            )
            return None

    async def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3

        Args:
            s3_key: S3 key to check

        Returns:
            True if file exists, False otherwise
        """
        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                await s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
                return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            logger.error(f"Error checking if {s3_key} exists: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking if {s3_key} exists: {e}", exc_info=True)
            return False

    async def download_file(self, s3_key: str, local_path: str) -> bool:
        """
        Download a file from S3 to local filesystem.

        Args:
            s3_key: S3 key of the file to download
            local_path: Local path where the file will be saved

        Returns:
            True if download successful, False otherwise

        Raises:
            ClientError: If S3 download fails
        """
        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                logger.info(f"Downloading s3://{self.bucket_name}/{s3_key} to {local_path}")

                await s3_client.download_file(self.bucket_name, s3_key, local_path)

                logger.info(f"Successfully downloaded {s3_key} to {local_path}")
                return True

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                logger.error(f"File not found in S3: {s3_key}")
            else:
                logger.error(f"Failed to download {s3_key} from S3: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error downloading {s3_key} from S3: {e}", exc_info=True)
            return False

    async def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3

        Args:
            s3_key: S3 key of the file to delete

        Returns:
            True if deletion successful, False otherwise
        """
        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                await s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
                logger.info(f"Successfully deleted {s3_key} from S3")
                return True

        except ClientError as e:
            logger.error(f"Failed to delete {s3_key} from S3: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting {s3_key} from S3: {e}", exc_info=True)
            return False

    async def get_file_size(self, s3_key: str) -> Optional[int]:
        """
        Get the size of a file in S3

        Args:
            s3_key: S3 key of the file

        Returns:
            File size in bytes, or None if file doesn't exist or error occurs
        """
        try:
            session, config = self._get_session()
            async with session.client("s3", config=config) as s3_client:
                response = await s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
                return response["ContentLength"]

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                logger.warning(f"File not found in S3: {s3_key}")
                return None
            logger.error(f"Error getting file size for {s3_key}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting file size for {s3_key}: {e}", exc_info=True)
            return None

    @staticmethod
    def _get_content_type(file_path: str) -> str:
        """
        Get MIME type based on file extension

        Args:
            file_path: Path to the file

        Returns:
            MIME type string
        """
        extension = os.path.splitext(file_path)[1].lower()

        content_types = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".json": "application/json",
        }

        return content_types.get(extension, "application/octet-stream")

    def generate_s3_key(
        self,
        user_id: str,
        filename: str,
        media_type: str = "training-videos",
        unique_id: str = None,
    ) -> str:
        """
        Generate a consistent S3 key for media files.

        Args:
            user_id: User ID for the folder structure
            filename: Original filename
            media_type: Type of media (training-videos, avatars, generated-videos)
            unique_id: Optional unique ID (model_id or video_id) to include in filename

        Returns:
            S3 key in format: {media_type}/{user_id}/{unique_id}{ext} or {media_type}/{user_id}/{filename}
        """
        if unique_id:
            # Use unique_id as the filename base, preserving original extension
            ext = os.path.splitext(filename)[1] if filename else ".mp4"
            filename = f"{unique_id}{ext}"
        return f"{media_type}/{user_id}/{filename}"


# Create singleton instance
s3_service = S3Service()
