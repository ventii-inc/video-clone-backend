"""Test Fish Audio TTS for text repetition issues.

Usage:
    uv run python scripts/test_fish_audio_repetition.py --reference-id YOUR_ID
    uv run python scripts/test_fish_audio_repetition.py --reference-id YOUR_ID --chunk-length 200
    uv run python scripts/test_fish_audio_repetition.py --reference-id YOUR_ID --runs 5
    uv run python scripts/test_fish_audio_repetition.py --reference-id YOUR_ID --text "カスタムテキスト"
"""

import argparse
import json
import os
import re
import sys
import tempfile

import httpx
from dotenv import load_dotenv
from google import genai


DEFAULT_TEXT = (
    "どうも、とうまです。今日は、自分の動画と音声をAIに学習させて、"
    "自分のビデオクローンを作れるサービス「クローンスタジオ」の話をします。"
    " これ、結論めっちゃシンプルで、一回ちゃんと撮るだけで、"
    "あとはAIが自分っぽく喋ってくれるようになります。"
    "つまり、動画を出すたびに毎回撮影しなくてよくなる。"
    " 例えば、営業の説明動画、採用の会社紹介、問い合わせ対応、SNSのショート動画。"
    "毎回同じ説明してるなってやつ、全部クローンに任せられます。"
    " しかも、台本を入れたら、自分の見た目と声で動画が出てくるから、"
    "テキストだけより伝わるし、信頼も取りやすい。"
    " 使い方も簡単で、素材アップして学習して、台本入れて生成。"
    "興味ある人は、まずデモ見てみてください。リンクからどうぞ。"
)


def load_env_keys() -> tuple[str, str]:
    for env_file in [".env.local", ".env.staging", ".env.production"]:
        if os.path.exists(env_file):
            load_dotenv(env_file)
    fish_key = os.getenv("FISH_AUDIO_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    return fish_key, gemini_key


def call_fish_audio(
    text: str,
    reference_id: str,
    api_key: str,
    chunk_length: int | None = None,
    repetition_penalty: float | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> bytes:
    payload = {
        "text": text,
        "reference_id": reference_id,
        "prosody": {"volume": 0},
        "normalize": True,
        "format": "wav",
        "latency": "normal",
        "speed": 1.0,
    }
    if chunk_length is not None:
        payload["chunk_length"] = chunk_length
    if repetition_penalty is not None:
        payload["repetition_penalty"] = repetition_penalty
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if response.status_code != 200:
            print(f"Fish Audio error {response.status_code}: {response.text}")
            sys.exit(1)
        return response.content


def transcribe_with_gemini(audio_bytes: bytes, client: genai.Client) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        uploaded = client.files.upload(file=tmp_path)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                uploaded,
                "Transcribe this Japanese audio exactly as spoken, word for word. "
                "Output only the transcription in Japanese, nothing else.",
            ],
        )
        return response.text.strip()
    finally:
        os.unlink(tmp_path)


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
    # Strip markdown code fences if present
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
    parser = argparse.ArgumentParser(description="Test Fish Audio TTS for repetition")
    parser.add_argument("--chunk-length", type=int, default=None, help="chunk_length param (omit to use Fish Audio default)")
    parser.add_argument("--runs", type=int, default=1, help="Number of test runs")
    parser.add_argument("--text", type=str, default=DEFAULT_TEXT, help="Text to synthesize")
    parser.add_argument("--reference-id", type=str, required=True, help="Fish Audio voice reference ID")
    parser.add_argument("--repetition-penalty", type=float, default=None, help="Repetition penalty (Fish Audio default: 1.2, try 1.5 or 2.0)")
    parser.add_argument("--temperature", type=float, default=None, help="Sampling temperature (omit to use Fish Audio default)")
    parser.add_argument("--top-p", type=float, default=None, help="Top-p sampling (omit to use Fish Audio default)")
    parser.add_argument("--save-audio", action="store_true", help="Save audio files to current directory")
    args = parser.parse_args()

    fish_api_key, gemini_api_key = load_env_keys()
    if not fish_api_key:
        print("Error: FISH_AUDIO_API_KEY not found in .env files")
        sys.exit(1)
    if not gemini_api_key:
        print("Error: GEMINI_API_KEY not found in .env files")
        sys.exit(1)

    gemini_client = genai.Client(api_key=gemini_api_key)
    chunk_label = f"chunk_length={args.chunk_length}" if args.chunk_length else "no chunk_length (default)"
    penalty_label = f"repetition_penalty={args.repetition_penalty}" if args.repetition_penalty else "no repetition_penalty (default 1.2)"
    temp_label = f"temperature={args.temperature}" if args.temperature is not None else "no temperature (default)"
    top_p_label = f"top_p={args.top_p}" if args.top_p is not None else "no top_p (default)"

    print(f"Config: {chunk_label}, {penalty_label}, {temp_label}, {top_p_label}, runs={args.runs}")
    print(f"Text length: {len(args.text)} chars")
    print(f"Reference ID: {args.reference_id}")
    print()
    print(f"Input text:\n  {args.text}")
    print("=" * 60)

    results = []

    for i in range(args.runs):
        print(f"\n--- Run {i + 1}/{args.runs} ({chunk_label}) ---")

        print("Generating TTS...")
        audio = call_fish_audio(
            args.text,
            args.reference_id,
            fish_api_key,
            args.chunk_length,
            args.repetition_penalty,
            args.temperature,
            args.top_p,
        )
        print(f"Audio size: {len(audio):,} bytes")

        if args.save_audio:
            filename = f"test_run{i+1}_chunk{args.chunk_length or 'default'}.wav"
            with open(filename, "wb") as f:
                f.write(audio)
            print(f"Saved: {filename}")

        print("Transcribing...")
        transcript = transcribe_with_gemini(audio, gemini_client)
        print(f"\nTranscript:\n  {transcript}")

        print("\nChecking for repetition...")
        transcript_clean = re.sub(r'[\s\u3000]+', '', transcript)
        has_repetition, repeated_phrases = detect_repetition(args.text, transcript_clean, gemini_client)
        results.append(has_repetition)

        if has_repetition:
            print(f"  REPEATED phrases found:")
            for r in repeated_phrases:
                print(f"    - \"{r}\"")
        else:
            print(f"  No repetition detected")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Config: {chunk_label}, {penalty_label}, {temp_label}, {top_p_label}")
    total = len(results)
    bad = sum(results)
    good = total - bad
    print(f"Runs: {total}  |  Clean: {good}  |  Repeated: {bad}")
    if bad > 0:
        print(f"Repetition rate: {bad}/{total} ({bad/total*100:.0f}%)")
    else:
        print("No repetition detected in any run")


if __name__ == "__main__":
    main()
