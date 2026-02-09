"""Transcribe a video file using ffmpeg + Gemini.

Extracts audio from a video via ffmpeg, transcribes it with Gemini,
and optionally checks for phrase repetition against original text.

Usage:
    uv run python scripts/transcribe_video.py --video ~/Downloads/video.mp4
    uv run python scripts/transcribe_video.py --video ~/Downloads/video.mp4 --text "original script text"
    uv run python scripts/transcribe_video.py --video ~/Downloads/video.mp4 --save-audio
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from dotenv import load_dotenv
from google import genai


def load_env_keys() -> str:
    for env_file in [".env.local", ".env.staging", ".env.production"]:
        if os.path.exists(env_file):
            load_dotenv(env_file)
    return os.getenv("GEMINI_API_KEY", "")


def extract_audio(video_path: str, output_path: str) -> None:
    """Extract audio from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error:\n{result.stderr}")
        sys.exit(1)


def transcribe_with_gemini(audio_path: str, client: genai.Client) -> str:
    """Upload audio to Gemini and get transcription."""
    uploaded = client.files.upload(file=audio_path)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            uploaded,
            "Transcribe this audio exactly as spoken, word for word. "
            "Output only the transcription, nothing else.",
        ],
    )
    return response.text.strip()


def detect_repetition(original: str, transcript: str, client: genai.Client) -> tuple[bool, list[str]]:
    """Use Gemini to compare original text vs transcript and detect repeated phrases."""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            f"Original text:\n{original}\n\n"
            f"Transcript:\n{transcript}\n\n"
            "Check if the transcript contains any CONSECUTIVE phrase repetition — "
            "a phrase of 5+ characters that appears back-to-back (the same phrase spoken twice in a row). "
            "Do NOT flag single words, short fragments, or words that naturally appear multiple times in different parts of the text. "
            "\n\n"
            "Example of REAL repetition (flag this):\n"
            "  '自分の動画と音声をAIに学習させて自分の動画と音声をAIに学習させて' — same phrase twice in a row\n"
            "Example of NOT repetition (do NOT flag):\n"
            "  '動画' appearing in '説明動画' and 'ショート動画' — same word in different contexts\n"
            "\n"
            "Respond with ONLY a JSON object, no markdown, no explanation:\n"
            '{"has_repetition": true/false, "repeated_phrases": ["phrase1", ...]}'
        ],
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0].strip()
    try:
        result = json.loads(text)
        return result.get("has_repetition", False), result.get("repeated_phrases", [])
    except json.JSONDecodeError:
        print(f"  Warning: Could not parse Gemini response: {text}")
        return False, []


def main():
    parser = argparse.ArgumentParser(description="Transcribe a video file using Gemini")
    parser.add_argument("--video", type=str, required=True, help="Path to video file")
    parser.add_argument("--text", type=str, default=None, help="Original text for repetition detection")
    parser.add_argument("--save-audio", action="store_true", help="Keep extracted WAV file")
    args = parser.parse_args()

    video_path = os.path.expanduser(args.video)
    if not os.path.exists(video_path):
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)

    gemini_api_key = load_env_keys()
    if not gemini_api_key:
        print("Error: GEMINI_API_KEY not found in .env files")
        sys.exit(1)

    gemini_client = genai.Client(api_key=gemini_api_key)

    # Extract audio
    if args.save_audio:
        base = os.path.splitext(os.path.basename(video_path))[0]
        audio_path = f"{base}.wav"
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio_path = tmp.name
        tmp.close()

    try:
        print(f"Extracting audio from: {video_path}")
        extract_audio(video_path, audio_path)
        print(f"Audio extracted: {audio_path} ({os.path.getsize(audio_path):,} bytes)")

        print("\nTranscribing with Gemini...")
        transcript = transcribe_with_gemini(audio_path, gemini_client)
        print(f"\nTranscript:\n  {transcript}")

        original = args.text if args.text else transcript
        print("\nChecking for repetition...")
        transcript_clean = re.sub(r'[\s\u3000]+', '', transcript)
        original_clean = re.sub(r'[\s\u3000]+', '', original)
        has_repetition, repeated_phrases = detect_repetition(original_clean, transcript_clean, gemini_client)
        if has_repetition:
            print("  REPEATED phrases found:")
            for r in repeated_phrases:
                print(f'    - "{r}"')
        else:
            print("  No repetition detected")
    finally:
        if not args.save_audio and os.path.exists(audio_path):
            os.unlink(audio_path)


if __name__ == "__main__":
    main()
