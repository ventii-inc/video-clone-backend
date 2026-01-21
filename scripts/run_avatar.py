#!/usr/bin/env python3
"""
Avatar Generation CLI Runner

Runs avatar generation with live progress display.
Wraps genavatar.py and shows formatted progress in terminal.

Usage:
    # Generate avatar with live progress
    ENV=staging uv run python scripts/run_avatar.py \\
      --video /path/to/video.mp4 \\
      --avatar-id test-123 \\
      --user-id 1

    # Skip S3 upload (local testing)
    ENV=staging uv run python scripts/run_avatar.py \\
      --video /path/to/video.mp4 \\
      --avatar-id test-123 \\
      --no-upload

    # Use LiveTalking environment
    ENV=staging uv run python scripts/run_avatar.py \\
      --video /path/to/video.mp4 \\
      --avatar-id test-123 \\
      --use-livetalking

Note: Uses asyncio.create_subprocess_exec with argument list (safe from shell injection).
"""

import argparse
import asyncio
import json
import os
import sys
import tarfile
import time
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_file = os.getenv("ENV", "local")
load_dotenv(f".env.{env_file}")


# Step weights for overall progress calculation
STEP_WEIGHTS = {
    "init": 0,
    "extract_frames": 20,
    "load_frames": 10,
    "face_detect": 50,
    "save_faces": 10,
    "finalize": 5,
    "upload": 5,
    "complete": 0,
}

STEP_ORDER = ["init", "extract_frames", "load_frames", "face_detect", "save_faces", "finalize", "upload", "complete"]


def get_step_index(step: str) -> int:
    """Get step index for ordering."""
    try:
        return STEP_ORDER.index(step)
    except ValueError:
        return -1


def calculate_overall_progress(step: str, step_progress: int) -> int:
    """Calculate overall progress based on step and step progress."""
    step_idx = get_step_index(step)
    if step_idx < 0:
        return 0

    # Sum weights of completed steps
    completed_weight = sum(STEP_WEIGHTS.get(s, 0) for s in STEP_ORDER[:step_idx])

    # Add current step's partial progress
    current_weight = STEP_WEIGHTS.get(step, 0)
    partial = int(current_weight * step_progress / 100)

    return min(100, completed_weight + partial)


def format_progress_bar(progress: int, width: int = 30) -> str:
    """Create a text progress bar."""
    filled = int(width * progress / 100)
    bar = "=" * filled + "-" * (width - filled)
    return f"[{bar}] {progress}%"


def clear_line():
    """Clear the current terminal line."""
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def print_progress(step: str, progress: int, message: str, overall: int):
    """Print formatted progress to terminal."""
    step_display = step.replace("_", " ").title()
    bar = format_progress_bar(overall)
    clear_line()
    sys.stdout.write(f"{bar} | {step_display}: {message}")
    sys.stdout.flush()


async def run_genavatar(
    video_path: str,
    avatar_id: str,
    output_dir: str,
    img_size: int = 256,
    use_livetalking: bool = False,
) -> dict:
    """
    Run genavatar.py with progress tracking.

    Uses asyncio.create_subprocess_exec with argument list (safe from injection).

    Args:
        video_path: Path to source video
        avatar_id: Unique avatar identifier
        output_dir: Directory for avatar output
        img_size: Face crop size (96 or 256)
        use_livetalking: Use LiveTalking's original genavatar.py (no progress)

    Returns:
        Result dict with success status and details
    """
    from app.services.livetalking.livetalking_config import LiveTalkingSettings
    settings = LiveTalkingSettings()

    # Both modes use LiveTalking's venv (has cv2, torch, face_detection)
    python_path = os.path.join(settings.LIVETALKING_VENV, "bin", "python")

    if not os.path.exists(python_path):
        return {"success": False, "error": f"LiveTalking venv not found: {settings.LIVETALKING_VENV}"}

    if use_livetalking:
        # Use LiveTalking's original version (no progress tracking)
        script_path = os.path.join(settings.LIVETALKING_ROOT, "wav2lip", "genavatar.py")
        work_dir = settings.LIVETALKING_ROOT
        output_dir = os.path.join(settings.LIVETALKING_ROOT, "data", "avatars")

        if not os.path.exists(script_path):
            return {"success": False, "error": f"LiveTalking script not found: {script_path}"}

        cmd = [
            python_path,
            script_path,
            "--video_path", video_path,
            "--avatar_id", avatar_id,
            "--img_size", str(img_size),
        ]
    else:
        # Use forked version with progress tracking
        script_path = os.path.join(Path(__file__).parent, "genavatar.py")
        work_dir = settings.LIVETALKING_ROOT  # Run in LiveTalking root for face_detection

        if not os.path.exists(script_path):
            return {"success": False, "error": f"Forked script not found: {script_path}"}

        cmd = [
            python_path,
            script_path,
            "--video_path", video_path,
            "--avatar_id", avatar_id,
            "--output_dir", output_dir,
            "--img_size", str(img_size),
            "--progress"
        ]

    print(f"\nStarting avatar generation...")
    print(f"  Video: {video_path}")
    print(f"  Avatar ID: {avatar_id}")
    print(f"  Output: {output_dir}")
    print(f"  Image size: {img_size}")
    print(f"  Script: {script_path}")
    print()

    start_time = time.time()
    result = None

    try:
        # Set up environment with PYTHONPATH for LiveTalking modules
        # face_detection is in wav2lip/ directory
        env = os.environ.copy()
        wav2lip_path = os.path.join(settings.LIVETALKING_ROOT, "wav2lip")
        pythonpath = f"{settings.LIVETALKING_ROOT}:{wav2lip_path}"
        if "PYTHONPATH" in env:
            pythonpath = f"{pythonpath}:{env['PYTHONPATH']}"
        env["PYTHONPATH"] = pythonpath

        # Using create_subprocess_exec with list args (safe from shell injection)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=env,
        )

        # Read stderr for progress updates
        while True:
            line = await process.stderr.readline()
            if not line:
                break

            line_str = line.decode().strip()
            if not line_str:
                continue

            try:
                data = json.loads(line_str)
                step = data.get("step", "unknown")
                step_progress = data.get("progress", 0)
                message = data.get("message", "")

                if "error" in data:
                    print(f"\nError: {data['error']}")
                    continue

                overall = calculate_overall_progress(step, step_progress)
                print_progress(step, step_progress, message, overall)

            except json.JSONDecodeError:
                # Not JSON, print as-is (might be error output)
                print(f"\n{line_str}")

        # Get stdout (final result)
        stdout, _ = await process.communicate()
        stdout_str = stdout.decode().strip()

        if stdout_str:
            try:
                result = json.loads(stdout_str)
            except json.JSONDecodeError:
                result = {"success": False, "error": f"Invalid output: {stdout_str}"}

        if process.returncode != 0 and not result:
            result = {"success": False, "error": f"Process exited with code {process.returncode}"}

    except Exception as e:
        result = {"success": False, "error": str(e)}

    elapsed = time.time() - start_time
    print()  # New line after progress

    if result and result.get("success"):
        result["elapsed_time"] = round(elapsed, 2)

    return result or {"success": False, "error": "Unknown error"}


async def upload_to_s3(avatar_id: str, user_id: int, avatar_path: str) -> str:
    """Upload avatar TAR to S3."""
    from app.services.s3 import s3_service

    print(f"\nUploading to S3...")
    print_progress("upload", 0, "Creating TAR archive", 95)

    # Create TAR file
    tar_path = f"{avatar_path}.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(avatar_path, arcname=avatar_id)

    print_progress("upload", 50, "Uploading to S3", 97)

    # Upload to S3
    s3_key = f"avatars/{user_id}/{avatar_id}.tar"
    await s3_service.upload_file(tar_path, s3_key, content_type="application/x-tar")

    # Cleanup TAR file
    os.remove(tar_path)

    print_progress("upload", 100, "Upload complete", 100)
    print()

    return s3_key


def print_summary(result: dict, s3_key: str = None):
    """Print final summary."""
    print("\n" + "=" * 50)

    if result.get("success"):
        print("Avatar generated successfully!")
        print("=" * 50)
        print(f"  Avatar ID:    {result.get('avatar_id', 'N/A')}")
        print(f"  Frames:       {result.get('frame_count', 'N/A')}")
        print(f"  Avatar path:  {result.get('avatar_path', 'N/A')}")
        print(f"  Gen time:     {result.get('generation_time', 'N/A')}s")
        if s3_key:
            print(f"  S3 Key:       {s3_key}")
    else:
        print("Avatar generation FAILED!")
        print("=" * 50)
        print(f"  Error: {result.get('error', 'Unknown error')}")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="Run avatar generation with live progress display",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--video", "-v",
        type=str,
        required=True,
        help="Path to source video file"
    )
    parser.add_argument(
        "--avatar-id", "-a",
        type=str,
        required=True,
        help="Unique identifier for the avatar"
    )
    parser.add_argument(
        "--user-id", "-u",
        type=int,
        default=1,
        help="User ID for S3 path (default: 1)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="./data/avatars",
        help="Output directory for avatar (default: ./data/avatars)"
    )
    parser.add_argument(
        "--img-size",
        type=int,
        default=256,
        choices=[96, 256],
        help="Face crop size: 96 for wav2lip, 256 for wav2lip256 (default: 256)"
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip S3 upload (local testing)"
    )
    parser.add_argument(
        "--use-livetalking",
        action="store_true",
        help="Use LiveTalking's genavatar.py instead of forked version"
    )

    args = parser.parse_args()

    # Validate video path
    if not os.path.exists(args.video):
        print(f"Error: Video file not found: {args.video}")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Run avatar generation
    result = await run_genavatar(
        video_path=args.video,
        avatar_id=args.avatar_id,
        output_dir=args.output_dir,
        img_size=args.img_size,
        use_livetalking=args.use_livetalking,
    )

    s3_key = None

    # Upload to S3 if successful and not skipped
    if result.get("success") and not args.no_upload:
        try:
            avatar_path = result.get("avatar_path")
            if avatar_path and os.path.exists(avatar_path):
                s3_key = await upload_to_s3(args.avatar_id, args.user_id, avatar_path)
            else:
                print(f"\nWarning: Avatar path not found, skipping S3 upload")
        except Exception as e:
            print(f"\nWarning: S3 upload failed: {e}")

    # Print summary
    print_summary(result, s3_key)

    # Exit with appropriate code
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    asyncio.run(main())
