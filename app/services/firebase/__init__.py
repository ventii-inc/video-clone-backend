"""Firebase service module for authentication"""

from app.services.firebase.firebase_config import (
    get_firebase_app,
    initialize_firebase,
    is_firebase_initialized,
)
from app.services.firebase.firebase_auth import (
    TokenData,
    get_current_user,
    get_current_user_or_create,
    get_optional_user,
    verify_token,
    verify_token_async,
)

__all__ = [
    "get_firebase_app",
    "initialize_firebase",
    "is_firebase_initialized",
    "TokenData",
    "get_current_user",
    "get_current_user_or_create",
    "get_optional_user",
    "verify_token",
    "verify_token_async",
]
