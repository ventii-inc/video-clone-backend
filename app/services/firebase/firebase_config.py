"""Firebase Admin SDK configuration and initialization"""

import os
import logging

import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger(__name__)

# Track initialization state
_firebase_app = None


def get_credentials_file() -> str:
    """Get the Firebase credentials file path based on environment"""
    env = os.getenv("ENV", "local")

    # Check for explicit credentials file path
    cred_file = os.getenv("FIREBASE_CREDENTIALS_FILE")
    if cred_file:
        return cred_file

    # Default file naming convention
    if env == "production":
        return "firebase-credentials.json"
    else:
        return "firebase-credentials-dev.json"


def initialize_firebase() -> firebase_admin.App:
    """
    Initialize Firebase Admin SDK.

    This function should be called once at application startup.
    It uses lazy initialization and caches the app instance.

    Returns:
        firebase_admin.App: The initialized Firebase app instance

    Raises:
        FileNotFoundError: If the credentials file is not found
        ValueError: If the credentials file is invalid
    """
    global _firebase_app

    if _firebase_app is not None:
        return _firebase_app

    cred_file = get_credentials_file()

    if not os.path.exists(cred_file):
        logger.warning(
            f"Firebase credentials file not found: {cred_file}. "
            "Firebase authentication will not work until credentials are provided."
        )
        raise FileNotFoundError(
            f"Firebase credentials file not found: {cred_file}. "
            "Please provide a valid Firebase service account JSON file."
        )

    try:
        cred = credentials.Certificate(cred_file)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info(f"Firebase initialized with credentials from: {cred_file}")
        return _firebase_app
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        raise


def get_firebase_app() -> firebase_admin.App:
    """
    Get the Firebase app instance, initializing if necessary.

    Returns:
        firebase_admin.App: The Firebase app instance
    """
    global _firebase_app

    if _firebase_app is None:
        return initialize_firebase()

    return _firebase_app


def is_firebase_initialized() -> bool:
    """Check if Firebase has been initialized"""
    return _firebase_app is not None
