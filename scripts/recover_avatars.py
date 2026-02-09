#!/usr/bin/env python3
"""
Avatar Recovery Script

Downloads all avatar TAR files from S3 and extracts them to local storage.
Run this script manually when the server has issues and needs to restore
avatar data from S3 backup.

Usage:
    # Recover all avatars
    python scripts/recover_avatars.py

    # Recover avatars for specific user
    python scripts/recover_avatars.py --user-id 42

    # Recover specific avatar
    python scripts/recover_avatars.py --avatar-id abc123-def456

    # Dry run (list what would be downloaded)
    python scripts/recover_avatars.py --dry-run

    # Custom output directory
    python scripts/recover_avatars.py --output-dir /data/avatars

Environment:
    Set these environment variables or they will use defaults:
    - S3_AWS_REGION
    - S3_AWS_ACCESS_KEY_ID
    - S3_AWS_SECRET_ACCESS_KEY
    - S3_BUCKET_NAME
    - AVATAR_LOCAL_PATH (default: ~/livetalking/data/avatars)
"""

import argparse
import asyncio
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment from .env file if exists
from dotenv import load_dotenv

env_file = os.getenv("ENV", "local")
load_dotenv(f".env.{env_file}")


import aioboto3
from botocore.config import Config


class AvatarRecovery:
    """Handles downloading and extracting avatar TAR files from S3."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.dry_run = dry_run
        self.output_dir = output_dir or os.getenv(
            "AVATAR_LOCAL_PATH",
            os.path.join(Path.home(), "livetalking", "data", "avatars"),
        )

        # S3 configuration
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        self.region = os.getenv("S3_AWS_REGION", "us-east-1")
        self.access_key = os.getenv("S3_AWS_ACCESS_KEY_ID")
        self.secret_key = os.getenv("S3_AWS_SECRET_ACCESS_KEY")

        if not self.bucket_name:
            raise ValueError("S3_BUCKET_NAME environment variable is required")

        self.session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

        # Stats
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0

    async def list_avatar_tars(
        self,
        user_id: Optional[int] = None,
        avatar_id: Optional[str] = None,
    ) -> list[dict]:
        """
        List all avatar TAR files in S3.

        Args:
            user_id: Filter by user ID
            avatar_id: Filter by specific avatar ID

        Returns:
            List of dicts with 'key', 'size', 'last_modified'
        """
        prefix = "avatars/"
        if user_id:
            prefix = f"avatars/{user_id}/"

        avatars = []

        async with self.session.client("s3") as s3:
            paginator = s3.get_paginator("list_objects_v2")

            async for page in paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=prefix,
            ):
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    # Only include .tar files
                    if not key.endswith(".tar"):
                        continue

                    # Filter by avatar_id if specified
                    if avatar_id:
                        if avatar_id not in key:
                            continue

                    avatars.append(
                        {
                            "key": key,
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"],
                            "avatar_id": Path(key).stem,  # filename without .tar
                            "user_id": self._extract_user_id(key),
                        }
                    )

        return avatars

    def _extract_user_id(self, key: str) -> Optional[int]:
        """Extract user_id from S3 key like 'avatars/42/abc123.tar'"""
        parts = key.split("/")
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                pass
        return None

    async def download_and_extract(
        self,
        s3_key: str,
        avatar_id: str,
    ) -> bool:
        """
        Download TAR from S3 and extract to local directory.

        Args:
            s3_key: S3 key for the TAR file
            avatar_id: Avatar ID (used for local directory name)

        Returns:
            True if successful
        """
        local_avatar_dir = os.path.join(self.output_dir, avatar_id)

        # Check if already exists locally
        if os.path.exists(local_avatar_dir):
            print(f"  SKIP: {avatar_id} (already exists locally)")
            self.skipped += 1
            return True

        if self.dry_run:
            print(f"  [DRY RUN] Would download: {s3_key}")
            return True

        try:
            # Create temp file for download
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
                tmp_path = tmp.name

            # Download from S3
            print(f"  Downloading: {s3_key}...")
            async with self.session.client("s3") as s3:
                await s3.download_file(
                    self.bucket_name,
                    s3_key,
                    tmp_path,
                )

            # Ensure output directory exists
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            # Extract TAR
            print(f"  Extracting to: {local_avatar_dir}")
            with tarfile.open(tmp_path, "r") as tar:
                tar.extractall(self.output_dir)

            # Verify extraction
            if os.path.exists(local_avatar_dir):
                frame_count = self._count_frames(local_avatar_dir)
                print(f"  SUCCESS: {avatar_id} ({frame_count} frames)")
                self.downloaded += 1
                return True
            else:
                print(f"  ERROR: Extraction did not create expected directory")
                self.failed += 1
                return False

        except Exception as e:
            print(f"  ERROR: {e}")
            self.failed += 1
            return False
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _count_frames(self, avatar_dir: str) -> int:
        """Count PNG frames in face_imgs directory."""
        face_imgs = os.path.join(avatar_dir, "face_imgs")
        if os.path.exists(face_imgs):
            return len([f for f in os.listdir(face_imgs) if f.endswith(".png")])
        return 0

    async def recover_all(
        self,
        user_id: Optional[int] = None,
        avatar_id: Optional[str] = None,
    ) -> dict:
        """
        Recover all matching avatars from S3.

        Args:
            user_id: Filter by user ID
            avatar_id: Filter by specific avatar ID

        Returns:
            Dict with recovery stats
        """
        print(f"\nAvatar Recovery Script")
        print(f"=" * 50)
        print(f"Output directory: {self.output_dir}")
        print(f"S3 bucket: {self.bucket_name}")
        if user_id:
            print(f"User filter: {user_id}")
        if avatar_id:
            print(f"Avatar filter: {avatar_id}")
        if self.dry_run:
            print(f"Mode: DRY RUN (no actual downloads)")
        print(f"=" * 50)

        # List all matching avatars
        print(f"\nScanning S3 for avatar TAR files...")
        avatars = await self.list_avatar_tars(user_id=user_id, avatar_id=avatar_id)

        if not avatars:
            print("No avatar TAR files found in S3.")
            return {"downloaded": 0, "skipped": 0, "failed": 0, "total": 0}

        print(f"Found {len(avatars)} avatar(s) in S3\n")

        # Download and extract each
        for idx, avatar in enumerate(avatars, 1):
            print(f"[{idx}/{len(avatars)}] {avatar['avatar_id']}")
            await self.download_and_extract(
                s3_key=avatar["key"],
                avatar_id=avatar["avatar_id"],
            )

        # Print summary
        print(f"\n" + "=" * 50)
        print(f"Recovery Complete")
        print(f"=" * 50)
        print(f"Downloaded: {self.downloaded}")
        print(f"Skipped:    {self.skipped}")
        print(f"Failed:     {self.failed}")
        print(f"Total:      {len(avatars)}")

        return {
            "downloaded": self.downloaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "total": len(avatars),
        }


async def main():
    parser = argparse.ArgumentParser(
        description="Recover avatar files from S3 to local storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--user-id",
        type=int,
        help="Recover avatars for specific user ID only",
    )

    parser.add_argument(
        "--avatar-id",
        type=str,
        help="Recover specific avatar by ID",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        help="Output directory for extracted avatars (default: $AVATAR_LOCAL_PATH)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be downloaded without actually downloading",
    )

    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list avatars in S3, don't download",
    )

    args = parser.parse_args()

    try:
        recovery = AvatarRecovery(
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )

        if args.list_only:
            print(f"\nListing avatar TAR files in S3...")
            avatars = await recovery.list_avatar_tars(
                user_id=args.user_id,
                avatar_id=args.avatar_id,
            )

            if not avatars:
                print("No avatar TAR files found.")
                return

            print(f"\nFound {len(avatars)} avatar(s):\n")
            print(f"{'Avatar ID':<40} {'User':<8} {'Size':<12} {'Last Modified'}")
            print("-" * 80)

            for avatar in avatars:
                size_mb = avatar["size"] / (1024 * 1024)
                print(
                    f"{avatar['avatar_id']:<40} "
                    f"{avatar['user_id'] or 'N/A':<8} "
                    f"{size_mb:.2f} MB{'':<4} "
                    f"{avatar['last_modified'].strftime('%Y-%m-%d %H:%M')}"
                )
        else:
            await recovery.recover_all(
                user_id=args.user_id,
                avatar_id=args.avatar_id,
            )

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
