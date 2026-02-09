#!/usr/bin/env python3
"""
Video Generation CLI Runner

Generates lip-synced video from avatar and text with live progress display.

Usage:
    # Generate video with default voice
    ENV=staging uv run python scripts/run_video.py \\
      --avatar-id test-6s-upload \\
      --text "Hello, this is a test video" \\
      --user-id 1

    # With custom voice model
    ENV=staging uv run python scripts/run_video.py \\
      --avatar-id test-6s-upload \\
      --text "Hello world" \\
      --voice-id 2d51c64b93bc4ecfaa391f0592201f6e \\
      --user-id 1

    # Skip S3 upload
    ENV=staging uv run python scripts/run_video.py \\
      --avatar-id test-6s-upload \\
      --text "Test" \\
      --no-upload

Note: Uses asyncio.create_subprocess_exec with argument list (safe from shell injection).
"""

import argparse
import asyncio
import json
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from uuid import uuid4

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_file = os.getenv("ENV", "local")
load_dotenv(f".env.{env_file}")


def format_progress_bar(progress: int, width: int = 30) -> str:
    """Create a text progress bar."""
    filled = int(width * progress / 100)
    bar = "=" * filled + "-" * (width - filled)
    return f"[{bar}] {progress}%"


def clear_line():
    """Clear the current terminal line."""
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def print_progress(step: str, message: str, progress: int):
    """Print formatted progress to terminal."""
    bar = format_progress_bar(progress)
    clear_line()
    sys.stdout.write(f"{bar} | {step}: {message}")
    sys.stdout.flush()


async def ensure_avatar_local(avatar_id: str, user_id: int) -> str:
    """
    Ensure avatar exists locally, downloading from S3 if needed.

    Returns:
        Local avatar path if found, None otherwise
    """
    from app.services.livetalking.livetalking_config import LiveTalkingSettings
    from app.services.s3 import s3_service

    settings = LiveTalkingSettings()
    local_avatar_path = os.path.join(settings.LIVETALKING_ROOT, "data", "avatars", avatar_id)

    if os.path.exists(local_avatar_path):
        print(f"  Avatar found locally: {local_avatar_path}")
        return local_avatar_path

    # Try to download from S3
    print(f"  Avatar not found locally, checking S3...")
    s3_key = f"avatars/{user_id}/{avatar_id}.tar"

    if not await s3_service.file_exists(s3_key):
        print(f"  Avatar not found in S3: {s3_key}")
        return None

    print(f"  Downloading from S3: {s3_key}")

    # Download to temp file
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        success = await s3_service.download_file(s3_key, tmp_path)
        if not success:
            print(f"  Failed to download avatar from S3")
            return None

        # Extract TAR
        avatars_dir = os.path.join(settings.LIVETALKING_ROOT, "data", "avatars")
        os.makedirs(avatars_dir, exist_ok=True)

        with tarfile.open(tmp_path, "r") as tar:
            tar.extractall(avatars_dir)

        print(f"  Extracted avatar to: {local_avatar_path}")
        return local_avatar_path

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def run_video_generation(
    avatar_id: str,
    text: str,
    output_path: str,
    voice_id: str = None,
) -> dict:
    """
    Run video generation using LiveTalking's benchmark_e2e.py.

    Uses asyncio.create_subprocess_exec with argument list (safe from injection).

    Args:
        avatar_id: Avatar ID to use
        text: Text to synthesize
        output_path: Output video path
        voice_id: Fish TTS voice/reference ID

    Returns:
        Result dict with success status and metrics
    """
    from app.services.livetalking.livetalking_config import LiveTalkingSettings
    settings = LiveTalkingSettings()

    python_path = os.path.join(settings.LIVETALKING_VENV, "bin", "python")
    script_path = os.path.join(settings.LIVETALKING_ROOT, "benchmark_e2e.py")
    work_dir = settings.LIVETALKING_ROOT

    if not os.path.exists(python_path):
        return {"success": False, "error": f"LiveTalking venv not found: {settings.LIVETALKING_VENV}"}

    if not os.path.exists(script_path):
        return {"success": False, "error": f"benchmark_e2e.py not found: {script_path}"}

    # Build command as list (safe from shell injection)
    cmd = [
        python_path,
        script_path,
        "--mode", "cold",
        "--avatar_id", avatar_id,
        "--text", text,
        "--output", output_path,
    ]

    if voice_id:
        cmd.extend(["--ref_file", voice_id])

    print(f"\nStarting video generation...")
    print(f"  Avatar: {avatar_id}")
    print(f"  Text: {text[:50]}{'...' if len(text) > 50 else ''}")
    print(f"  Voice ID: {voice_id or 'default'}")
    print(f"  Output: {output_path}")
    print()

    start_time = time.time()
    result = None
    current_step = "Initializing"

    try:
        # Set up environment
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{settings.LIVETALKING_ROOT}:{settings.LIVETALKING_ROOT}/wav2lip"

        # Using create_subprocess_exec with list args (safe from shell injection)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
            env=env,
        )

        # Read output and show progress
        step_progress = {
            "Loading Wav2Lip": 10,
            "Avatar already exists": 15,
            "Loading avatar": 20,
            "Generating audio": 40,
            "Processing audio": 50,
            "Running Wav2Lip": 60,
            "Inference": 80,
            "Encoding video": 90,
        }

        output_lines = []
        while True:
            line = await process.stdout.readline()
            if not line:
                break

            line_str = line.decode().strip()
            output_lines.append(line_str)

            if not line_str:
                continue

            # Update progress based on output
            for step_text, progress in step_progress.items():
                if step_text.lower() in line_str.lower():
                    current_step = step_text
                    print_progress(current_step, line_str[:40], progress)
                    break

        await process.wait()
        print()  # New line after progress

        # Check if output file was created
        if process.returncode == 0 and os.path.exists(output_path):
            elapsed = time.time() - start_time
            file_size = os.path.getsize(output_path)

            result = {
                "success": True,
                "output_path": output_path,
                "file_size": file_size,
                "generation_time": round(elapsed, 2),
            }

            # Try to parse JSON result from output
            for line in output_lines:
                if line.startswith("{") and "audio_duration" in line:
                    try:
                        data = json.loads(line)
                        result["audio_duration"] = data.get("audio_duration")
                        result["inference_time"] = data.get("inference_time")
                        break
                    except json.JSONDecodeError:
                        pass

            print_progress("Complete", f"Video generated in {elapsed:.1f}s", 100)
            print()
        else:
            error_output = "\n".join(output_lines[-10:])  # Last 10 lines
            result = {
                "success": False,
                "error": f"Generation failed (exit code {process.returncode}): {error_output[:500]}"
            }

    except Exception as e:
        result = {"success": False, "error": str(e)}

    return result


async def upload_to_s3(output_path: str, user_id: int, video_id: str) -> str:
    """Upload video to S3."""
    from app.services.s3 import s3_service

    print(f"\nUploading to S3...")
    s3_key = f"generated-videos/{user_id}/{video_id}.mp4"

    await s3_service.upload_file(output_path, s3_key, content_type="video/mp4")
    print(f"  Uploaded: {s3_key}")

    return s3_key


def print_summary(result: dict, s3_key: str = None):
    """Print final summary."""
    print("\n" + "=" * 50)

    if result.get("success"):
        print("Video generated successfully!")
        print("=" * 50)
        print(f"  Output:      {result.get('output_path', 'N/A')}")
        print(f"  File size:   {result.get('file_size', 0) / 1024:.1f} KB")
        print(f"  Duration:    {result.get('audio_duration', 'N/A')}s")
        print(f"  Gen time:    {result.get('generation_time', 'N/A')}s")
        if s3_key:
            print(f"  S3 Key:      {s3_key}")
    else:
        print("Video generation FAILED!")
        print("=" * 50)
        print(f"  Error: {result.get('error', 'Unknown error')}")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description="Generate lip-synced video from avatar and text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--avatar-id", "-a",
        type=str,
        required=True,
        help="Avatar ID to use (must exist in S3 or locally)"
    )
    parser.add_argument(
        "--text", "-t",
        type=str,
        required=True,
        help="Text to synthesize for lip-sync"
    )
    parser.add_argument(
        "--user-id", "-u",
        type=int,
        default=1,
        help="User ID for S3 paths (default: 1)"
    )
    parser.add_argument(
        "--voice-id", "-v",
        type=str,
        default=None,
        help="Fish TTS voice/reference ID (default: use default voice)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output video path (default: auto-generated)"
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip S3 upload"
    )

    args = parser.parse_args()

    # Ensure avatar exists locally
    print("Checking avatar...")
    avatar_path = await ensure_avatar_local(args.avatar_id, args.user_id)

    if not avatar_path:
        print(f"\nError: Avatar '{args.avatar_id}' not found locally or in S3")
        print(f"  Checked S3 key: avatars/{args.user_id}/{args.avatar_id}.tar")
        sys.exit(1)

    # Generate output path if not specified
    video_id = str(uuid4())
    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(tempfile.gettempdir(), f"{video_id}.mp4")

    # Run video generation
    result = await run_video_generation(
        avatar_id=args.avatar_id,
        text=args.text,
        output_path=output_path,
        voice_id=args.voice_id,
    )

    s3_key = None

    # Upload to S3 if successful and not skipped
    if result.get("success") and not args.no_upload:
        try:
            s3_key = await upload_to_s3(output_path, args.user_id, video_id)
        except Exception as e:
            print(f"\nWarning: S3 upload failed: {e}")

    # Print summary
    print_summary(result, s3_key)

    # Exit with appropriate code
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    asyncio.run(main())
