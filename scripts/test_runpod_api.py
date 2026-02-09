#!/usr/bin/env python3
"""
Test RunPod API Mode for Avatar Generation

Usage:
    # Test with a video from S3 (provide the S3 key)
    ENV=staging uv run python scripts/test_runpod_api.py --s3-key videos/user1/test.mp4

    # Test with a local video (will upload to S3 first)
    ENV=staging uv run python scripts/test_runpod_api.py --video /path/to/video.mp4 --user-id 1
"""

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_file = os.getenv("ENV", "local")
load_dotenv(f".env.{env_file}")


async def test_runpod_api(s3_key: str = None, video_path: str = None, user_id: int = 1):
    """Test RunPod API avatar generation."""
    from app.services.avatar_job.runpod_client import runpod_client
    from app.services.s3 import s3_service
    from app.services.livetalking.livetalking_config import LiveTalkingSettings

    settings = LiveTalkingSettings()

    print("=" * 60)
    print("RunPod API Mode Test")
    print("=" * 60)
    print(f"LIVETALKING_MODE: {settings.LIVETALKING_MODE}")
    print(f"RUNPOD_API_KEY: {'*' * 10}...{os.getenv('RUNPOD_API_KEY', '')[-4:]}")
    print(f"RUNPOD_ENDPOINT_ID: {os.getenv('RUNPOD_ENDPOINT_ID', 'NOT SET')}")
    print()

    # Validate RunPod credentials
    if not runpod_client.api_key or not runpod_client.endpoint_id:
        print("ERROR: RunPod credentials not configured!")
        print("Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID in your .env file")
        return False

    # If local video provided, upload to S3 first
    if video_path:
        if not os.path.exists(video_path):
            print(f"ERROR: Video file not found: {video_path}")
            return False

        print(f"Uploading video to S3: {video_path}")
        s3_key = f"test-videos/{user_id}/{uuid.uuid4()}.mp4"
        await s3_service.upload_file(video_path, s3_key, content_type="video/mp4")
        print(f"Uploaded to S3: {s3_key}")
        print()

    if not s3_key:
        print("ERROR: No video specified. Use --s3-key or --video")
        return False

    # Check if video exists in S3
    print(f"Checking S3 for video: {s3_key}")
    exists = await s3_service.file_exists(s3_key)
    if not exists:
        print(f"ERROR: Video not found in S3: {s3_key}")
        return False
    print("Video found in S3")
    print()

    # Generate presigned URL
    print("Generating presigned URL...")
    video_url = await s3_service.generate_presigned_url(s3_key, expiration=7200)
    print(f"Presigned URL: {video_url[:80]}...")
    print()

    # Generate unique avatar ID for test
    avatar_id = f"test-{uuid.uuid4()}"
    s3_bucket = s3_service.bucket_name

    print("Calling RunPod API...")
    print(f"  Avatar ID: {avatar_id}")
    print(f"  Model: wav2lip")
    print(f"  S3 Bucket: {s3_bucket}")
    print(f"  S3 Prefix: avatars/{user_id}")
    print()

    # Call RunPod
    response = await runpod_client.generate_avatar(
        video_url=video_url,
        avatar_id=avatar_id,
        model="wav2lip",
        s3_bucket=s3_bucket,
        s3_prefix=f"avatars/{user_id}",
    )

    print("=" * 60)
    print("RunPod Response")
    print("=" * 60)
    print(f"Success: {response.success}")
    print(f"Job ID: {response.job_id}")
    print(f"Avatar ID: {response.avatar_id}")
    print(f"Upload URL: {response.upload_url}")
    print(f"Num Frames: {response.num_frames}")
    if response.error:
        print(f"Error: {response.error}")
    print()

    if response.success:
        # Verify avatar was uploaded to S3
        expected_s3_key = f"avatars/{user_id}/{avatar_id}.tar"
        print(f"Verifying S3 upload: {expected_s3_key}")
        exists = await s3_service.file_exists(expected_s3_key)
        print(f"Avatar in S3: {exists}")

    return response.success


async def check_health():
    """Check RunPod endpoint health."""
    from app.services.avatar_job.runpod_client import runpod_client

    print("Checking RunPod endpoint health...")
    available = await runpod_client.check_gpu_availability()
    print(f"GPU Available: {available}")
    return available


async def main():
    parser = argparse.ArgumentParser(
        description="Test RunPod API mode for avatar generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--s3-key",
        type=str,
        help="S3 key of an existing video to use for testing"
    )
    parser.add_argument(
        "--video", "-v",
        type=str,
        help="Path to local video file (will be uploaded to S3)"
    )
    parser.add_argument(
        "--user-id", "-u",
        type=int,
        default=1,
        help="User ID for S3 path (default: 1)"
    )
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="Only check endpoint health, don't run generation"
    )

    args = parser.parse_args()

    if args.health_only:
        success = await check_health()
        sys.exit(0 if success else 1)

    if not args.s3_key and not args.video:
        print("ERROR: Must provide either --s3-key or --video")
        parser.print_help()
        sys.exit(1)

    success = await test_runpod_api(
        s3_key=args.s3_key,
        video_path=args.video,
        user_id=args.user_id,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
