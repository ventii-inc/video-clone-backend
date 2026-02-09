#!/usr/bin/env python3
"""
Generate Firebase custom token for testing purposes.

Usage:
    ENV=staging python scripts/generate_test_token.py
    ENV=staging python scripts/generate_test_token.py --email other@example.com
"""

import argparse
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment-specific .env file
env = os.getenv("ENV", "local")
env_file = f".env.{env}"
if os.path.exists(env_file):
    load_dotenv(env_file)
    print(f"Loaded environment from: {env_file}")

import requests
from firebase_admin import auth

from app.services.firebase import initialize_firebase, get_firebase_app


def get_firebase_api_key() -> str:
    """Get Firebase Web API key from credentials file or environment."""
    # Try environment variable first
    api_key = os.getenv("FIREBASE_API_KEY")
    if api_key:
        return api_key

    # Try to get from firebase config file
    env = os.getenv("ENV", "local")
    config_file = f"firebase-config-{env}.json" if env != "production" else "firebase-config.json"

    if os.path.exists(config_file):
        with open(config_file) as f:
            config = json.load(f)
            return config.get("apiKey", "")

    return ""


def create_custom_token(uid: str, email: str) -> str:
    """Create a Firebase custom token."""
    initialize_firebase()

    # Create custom token with additional claims
    custom_token = auth.create_custom_token(uid, {
        "email": email,
        "email_verified": True,
    })

    return custom_token.decode() if isinstance(custom_token, bytes) else custom_token


def exchange_custom_token_for_id_token(custom_token: str, api_key: str) -> str:
    """Exchange custom token for ID token using Firebase Auth REST API."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={api_key}"

    response = requests.post(url, json={
        "token": custom_token,
        "returnSecureToken": True,
    })

    if response.status_code != 200:
        raise Exception(f"Failed to exchange token: {response.text}")

    data = response.json()
    return data["idToken"]


def get_or_create_firebase_user(email: str) -> str:
    """Get existing Firebase user or create one, return UID."""
    initialize_firebase()

    try:
        user = auth.get_user_by_email(email)
        print(f"Found existing Firebase user: {user.uid}")
        return user.uid
    except auth.UserNotFoundError:
        # Create new user
        user = auth.create_user(
            email=email,
            email_verified=True,
        )
        print(f"Created new Firebase user: {user.uid}")
        return user.uid


def main():
    parser = argparse.ArgumentParser(description="Generate Firebase test token")
    parser.add_argument(
        "--email",
        default="rrfunde@gmail.com",
        help="Email for the test user (default: rrfunde@gmail.com)"
    )
    parser.add_argument(
        "--custom-only",
        action="store_true",
        help="Only generate custom token (don't exchange for ID token)"
    )
    args = parser.parse_args()

    print(f"Generating token for: {args.email}")
    print("-" * 50)

    # Get or create Firebase user
    uid = get_or_create_firebase_user(args.email)

    # Create custom token
    custom_token = create_custom_token(uid, args.email)
    print(f"\nCustom Token:\n{custom_token}")

    if args.custom_only:
        return

    # Try to exchange for ID token
    api_key = get_firebase_api_key()
    if not api_key:
        print("\n⚠️  No FIREBASE_API_KEY found. Set it to exchange for ID token.")
        print("   Export: export FIREBASE_API_KEY=your_web_api_key")
        print("   Or create firebase-config-local.json with {\"apiKey\": \"...\"}")
        return

    try:
        id_token = exchange_custom_token_for_id_token(custom_token, api_key)
        print(f"\nID Token (use this for API calls):\n{id_token}")
        print(f"\nUsage:")
        print(f'curl -H "Authorization: Bearer {id_token[:50]}..." ...')
    except Exception as e:
        print(f"\n⚠️  Failed to exchange token: {e}")
        print("   Use the custom token above with Firebase client SDK instead.")


if __name__ == "__main__":
    main()
