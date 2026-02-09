#!/usr/bin/env python3
"""
Test Gemini End-Frame Detection + Video Looping Pipeline

This script tests the Gemini video analysis and reverse-append looping pipeline.

Usage:
    # Test just ffmpeg functions (no API key needed)
    ENV=local uv run python scripts/test_video_loop.py --ffmpeg-only test_6s.mp4

    # Test full pipeline (default) - runs Gemini, then FFmpeg with Gemini's trim value
    ENV=local uv run python scripts/test_video_loop.py test_6s.mp4

    # Keep intermediate files for inspection
    ENV=local uv run python scripts/test_video_loop.py --keep-files test_6s.mp4
"""

import argparse
import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_file = os.getenv("ENV", "local")
load_dotenv(f".env.{env_file}")

# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(title: str):
    """Print a section header."""
    print()
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE}{title}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}")
    print()


def print_pass(message: str):
    """Print a PASS result."""
    print(f"  {GREEN}✓ PASS{RESET}: {message}")


def print_fail(message: str):
    """Print a FAIL result."""
    print(f"  {RED}✗ FAIL{RESET}: {message}")


def print_info(message: str):
    """Print an info message."""
    print(f"  {YELLOW}ℹ INFO{RESET}: {message}")


async def test_ffmpeg_functions(video_path: str, temp_dir: str) -> bool:
    """
    Test FFmpeg functions only (no Gemini API key needed).

    Tests:
    - get_video_duration / get_video_info
    - trim_video_to_timestamp (hardcoded 4s trim)
    - reverse_video
    - concat_videos

    Returns True if all tests pass.
    """
    from app.services.video import (
        get_video_duration,
        get_video_info,
        trim_video_to_timestamp,
        reverse_video,
        concat_videos,
        video_service,
    )

    print_header("FFmpeg Functions Test (--ffmpeg-only)")
    all_passed = True

    # Check FFmpeg availability
    print("Checking FFmpeg availability...")
    if video_service.is_ffmpeg_available():
        print_pass("FFmpeg and FFprobe are available")
    else:
        print_fail("FFmpeg or FFprobe not found. Please install FFmpeg.")
        return False

    # Test get_video_info
    print()
    print("Testing get_video_info()...")
    video_info = await get_video_info(video_path)
    if video_info:
        print_pass(f"Got video info: duration={video_info['duration']:.2f}s, fps={video_info.get('fps')}")
        original_duration = video_info["duration"]
    else:
        print_fail("Could not get video info")
        return False

    # Test get_video_duration
    print()
    print("Testing get_video_duration()...")
    duration = await get_video_duration(video_path)
    if duration and abs(duration - original_duration) < 0.01:
        print_pass(f"Got consistent duration: {duration:.2f}s")
    else:
        print_fail(f"Duration mismatch or error: got {duration}, expected {original_duration:.2f}")
        all_passed = False

    # Test trim_video_to_timestamp - trim to 4 seconds (hardcoded for ffmpeg-only test)
    print()
    trim_target = min(4.0, original_duration - 0.5)  # Trim to 4s or less
    if trim_target < 1.0:
        print_info(f"Video too short ({original_duration:.2f}s) to test trimming, skipping trim test")
        trimmed_path = video_path
        trimmed_duration = original_duration
    else:
        print(f"Testing trim_video_to_timestamp() - trimming to {trim_target:.2f}s...")
        trimmed_path = os.path.join(temp_dir, "trimmed.mp4")

        success = await trim_video_to_timestamp(video_path, trimmed_path, trim_target)
        if success and os.path.exists(trimmed_path):
            trimmed_duration = await get_video_duration(trimmed_path)
            file_size = os.path.getsize(trimmed_path)

            # Allow ±0.5s tolerance for ffmpeg timing
            if trimmed_duration and abs(trimmed_duration - trim_target) <= 0.5:
                print_pass(f"Trimmed video created: {trimmed_duration:.2f}s, {file_size / 1024:.1f} KB")
            else:
                print_fail(f"Trimmed duration {trimmed_duration:.2f}s, expected ~{trim_target:.2f}s (±0.5s)")
                all_passed = False
        else:
            print_fail(f"Failed to trim video")
            all_passed = False
            trimmed_path = video_path
            trimmed_duration = original_duration

    # Test reverse_video
    print()
    print(f"Testing reverse_video()...")
    reversed_path = os.path.join(temp_dir, "reversed.mp4")

    # Use trimmed video (or original if trim skipped)
    source_for_reverse = trimmed_path if os.path.exists(trimmed_path) else video_path

    success = await reverse_video(source_for_reverse, reversed_path)
    if success and os.path.exists(reversed_path):
        reversed_duration = await get_video_duration(reversed_path)
        file_size = os.path.getsize(reversed_path)

        expected_duration = trimmed_duration if 'trimmed_duration' in dir() else original_duration
        if reversed_duration and abs(reversed_duration - expected_duration) <= 0.5:
            print_pass(f"Reversed video created: {reversed_duration:.2f}s, {file_size / 1024:.1f} KB")
        else:
            print_fail(f"Reversed duration {reversed_duration:.2f}s, expected ~{expected_duration:.2f}s (±0.5s)")
            all_passed = False
    else:
        print_fail("Failed to reverse video")
        all_passed = False
        reversed_path = None

    # Test concat_videos
    print()
    print("Testing concat_videos()...")
    if reversed_path and os.path.exists(reversed_path):
        concat_path = os.path.join(temp_dir, "concat.mp4")

        success = await concat_videos([source_for_reverse, reversed_path], concat_path)
        if success and os.path.exists(concat_path):
            concat_duration = await get_video_duration(concat_path)
            file_size = os.path.getsize(concat_path)

            expected_concat = expected_duration * 2
            if concat_duration and abs(concat_duration - expected_concat) <= 1.0:
                print_pass(f"Concatenated video created: {concat_duration:.2f}s (≈2x), {file_size / 1024:.1f} KB")
            else:
                print_fail(f"Concat duration {concat_duration:.2f}s, expected ~{expected_concat:.2f}s (±1.0s)")
                all_passed = False
        else:
            print_fail("Failed to concatenate videos")
            all_passed = False
    else:
        print_info("Skipping concat test (reverse failed)")
        all_passed = False

    return all_passed


async def test_gemini_and_loop(video_path: str, temp_dir: str) -> bool:
    """
    Test the full pipeline: Gemini analysis → FFmpeg trim/reverse/concat.

    This shows exactly what Gemini returns and verifies FFmpeg uses that value.

    Requires GEMINI_API_KEY to be set.

    Returns True if all tests pass.
    """
    from app.services.gemini import gemini_service
    from app.services.gemini.gemini_config import GeminiSettings
    from app.services.video import (
        get_video_duration,
        get_video_info,
        trim_video_to_timestamp,
        reverse_video,
        concat_videos,
        video_service,
    )

    print_header("Step 1: Gemini Analysis")

    # Check configuration
    settings = GeminiSettings()
    print("Checking Gemini configuration...")
    api_key_display = f"{'*' * 10}...{settings.GEMINI_API_KEY[-4:]}" if settings.GEMINI_API_KEY else "NOT SET"
    print(f"  GEMINI_API_KEY: {api_key_display}")
    print(f"  GEMINI_MODEL: {settings.GEMINI_MODEL}")
    print()

    if not settings.GEMINI_API_KEY:
        print_fail("GEMINI_API_KEY is not set")
        print_info("Set GEMINI_API_KEY in your .env.{ENV} file")
        return False

    print_pass("Gemini configuration valid")
    print()

    # Get original video info
    video_info = await get_video_info(video_path)
    if not video_info:
        print_fail("Could not get video info")
        return False

    original_duration = video_info["duration"]
    print(f"Input video: {video_path}")
    print(f"Original duration: {original_duration:.2f}s")
    print()

    # Run Gemini analysis
    print("Running Gemini analysis...")
    print("(This may take 30-60 seconds for file upload and processing)")
    print()

    result = await gemini_service.analyze_end_frames(video_path)

    if not result.success:
        print_fail(f"Gemini analysis failed: {result.error}")
        return False

    print_pass("Gemini analysis completed")
    print()
    print(f"{BOLD}Gemini Result:{RESET}")
    print(f"  has_anomaly: {result.analysis.has_anomaly}")
    print(f"  trim_to_seconds: {result.analysis.trim_to_seconds}")
    print(f"  description: {result.analysis.description}")
    print()

    # Validate Gemini response
    all_passed = True

    if not isinstance(result.analysis.has_anomaly, bool):
        print_fail(f"has_anomaly should be bool, got {type(result.analysis.has_anomaly)}")
        all_passed = False

    if result.analysis.has_anomaly:
        if result.analysis.trim_to_seconds is None:
            print_fail("has_anomaly=True but trim_to_seconds is None")
            all_passed = False
        elif result.analysis.trim_to_seconds < 3.0:
            print_fail(f"trim_to_seconds ({result.analysis.trim_to_seconds}) is less than minimum (3.0)")
            all_passed = False

    if not all_passed:
        return False

    # Step 2: FFmpeg operations using Gemini's trim value
    print_header("Step 2: FFmpeg Operations (using Gemini result)")

    # Check FFmpeg availability
    if not video_service.is_ffmpeg_available():
        print_fail("FFmpeg or FFprobe not found")
        return False

    # Determine trim target from Gemini result
    if result.analysis.has_anomaly and result.analysis.trim_to_seconds:
        trim_target = result.analysis.trim_to_seconds
        print(f"Gemini detected anomaly → trimming to {trim_target:.2f}s")
        print()

        # Trim video
        trimmed_path = os.path.join(temp_dir, "trimmed.mp4")
        success = await trim_video_to_timestamp(video_path, trimmed_path, trim_target)

        if not success or not os.path.exists(trimmed_path):
            print_fail("Failed to trim video")
            return False

        trimmed_duration = await get_video_duration(trimmed_path)
        if not trimmed_duration:
            print_fail("Could not get trimmed video duration")
            return False

        # Allow ±0.5s tolerance
        if abs(trimmed_duration - trim_target) <= 0.5:
            print_pass(f"Trimmed video: {trimmed_duration:.2f}s (target: {trim_target:.2f}s)")
        else:
            print_fail(f"Trimmed duration {trimmed_duration:.2f}s, expected ~{trim_target:.2f}s (±0.5s)")
            all_passed = False

        source_for_reverse = trimmed_path
        expected_single_duration = trimmed_duration
    else:
        print("Gemini found no anomaly → using original video (no trim)")
        print()
        source_for_reverse = video_path
        expected_single_duration = original_duration
        print_pass(f"Using original video: {original_duration:.2f}s")

    # Reverse video
    print()
    reversed_path = os.path.join(temp_dir, "reversed.mp4")
    success = await reverse_video(source_for_reverse, reversed_path)

    if not success or not os.path.exists(reversed_path):
        print_fail("Failed to reverse video")
        return False

    reversed_duration = await get_video_duration(reversed_path)
    if reversed_duration and abs(reversed_duration - expected_single_duration) <= 0.5:
        print_pass(f"Reversed video: {reversed_duration:.2f}s")
    else:
        print_fail(f"Reversed duration {reversed_duration:.2f}s, expected ~{expected_single_duration:.2f}s")
        all_passed = False

    # Concatenate videos
    print()
    looped_path = os.path.join(temp_dir, "looped.mp4")
    success = await concat_videos([source_for_reverse, reversed_path], looped_path)

    if not success or not os.path.exists(looped_path):
        print_fail("Failed to concatenate videos")
        return False

    looped_duration = await get_video_duration(looped_path)
    expected_looped = expected_single_duration * 2

    if looped_duration and abs(looped_duration - expected_looped) <= 1.0:
        print_pass(f"Looped video: {looped_duration:.2f}s (≈2x {expected_single_duration:.2f}s)")
    else:
        print_fail(f"Looped duration {looped_duration:.2f}s, expected ~{expected_looped:.2f}s (±1.0s)")
        all_passed = False

    # Summary
    print_header("Step 3: Verification Summary")

    print(f"Original video:  {original_duration:.2f}s")
    if result.analysis.has_anomaly:
        print(f"Gemini trim_to:  {result.analysis.trim_to_seconds:.2f}s")
        print(f"Trimmed video:   {trimmed_duration:.2f}s")
    else:
        print(f"Gemini trim_to:  None (no anomaly)")
    print(f"Reversed video:  {reversed_duration:.2f}s")
    print(f"Looped video:    {looped_duration:.2f}s (expected: {expected_looped:.2f}s)")
    print()

    file_size = os.path.getsize(looped_path)
    print_info(f"Output file size: {file_size / 1024:.1f} KB")

    return all_passed


async def main():
    parser = argparse.ArgumentParser(
        description="Test Gemini end-frame detection + video looping pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test FFmpeg only (no API key needed)
  ENV=local uv run python scripts/test_video_loop.py --ffmpeg-only test_6s.mp4

  # Test full pipeline: Gemini analysis → FFmpeg with Gemini's trim value
  ENV=local uv run python scripts/test_video_loop.py test_6s.mp4

  # Keep output files for inspection
  ENV=local uv run python scripts/test_video_loop.py --keep-files test_6s.mp4
        """,
    )

    parser.add_argument(
        "video",
        type=str,
        help="Path to video file to test with"
    )
    parser.add_argument(
        "--ffmpeg-only",
        action="store_true",
        help="Only test FFmpeg functions (no Gemini API key needed, uses hardcoded 4s trim)"
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Keep intermediate/output files for inspection (default: clean up)"
    )

    args = parser.parse_args()

    # Validate video path
    if not os.path.exists(args.video):
        print(f"{RED}ERROR{RESET}: Video file not found: {args.video}")
        sys.exit(1)

    video_path = os.path.abspath(args.video)

    # Create temp directory
    temp_dir = tempfile.mkdtemp(prefix="video_loop_test_")
    print(f"{BOLD}Temp directory:{RESET} {temp_dir}")
    print(f"{BOLD}Input video:{RESET} {video_path}")

    success = True

    try:
        if args.ffmpeg_only:
            success = await test_ffmpeg_functions(video_path, temp_dir)
        else:
            # Full pipeline: Gemini analysis → FFmpeg with Gemini's trim value
            success = await test_gemini_and_loop(video_path, temp_dir)

        # Summary
        print()
        print(f"{BOLD}{'=' * 60}{RESET}")
        if success:
            print(f"{GREEN}{BOLD}ALL TESTS PASSED{RESET}")
        else:
            print(f"{RED}{BOLD}SOME TESTS FAILED{RESET}")
        print(f"{BOLD}{'=' * 60}{RESET}")

    finally:
        if args.keep_files:
            print()
            print(f"{YELLOW}Keeping temp files at:{RESET} {temp_dir}")
            # List files in temp dir
            for f in os.listdir(temp_dir):
                fpath = os.path.join(temp_dir, f)
                size = os.path.getsize(fpath) if os.path.isfile(fpath) else 0
                print(f"  {f} ({size / 1024:.1f} KB)")
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            print()
            print(f"Cleaned up temp directory: {temp_dir}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
