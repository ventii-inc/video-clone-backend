"""API Key authentication for internal/backend-to-backend endpoints"""

import os
from fastapi import HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.utils import logger

# API Key header configuration
API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


def _get_avatar_api_key() -> str:
    """Get the avatar API key from environment variables."""
    api_key = os.getenv("AVATAR_API_KEY")
    if not api_key:
        logger.error("AVATAR_API_KEY environment variable is not set")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error",
        )
    return api_key


def verify_api_key(api_key: str) -> bool:
    """
    Verify that the provided API key matches the expected value.

    Args:
        api_key: The API key to verify

    Returns:
        True if the API key is valid, False otherwise
    """
    expected_key = _get_avatar_api_key()
    return api_key == expected_key


async def get_api_key(request: Request) -> str:
    """
    FastAPI dependency to extract and validate the API key from request headers.

    Usage:
        @router.get("/protected-endpoint")
        async def protected_route(api_key: str = Depends(get_api_key)):
            # Route is protected by API key
            pass

    Args:
        request: The FastAPI request object

    Returns:
        The validated API key string

    Raises:
        HTTPException: 401 if API key is missing or invalid
    """
    api_key = request.headers.get(API_KEY_HEADER_NAME)

    if not api_key:
        logger.warning(f"Missing API key in request to {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not verify_api_key(api_key):
        logger.warning(f"Invalid API key in request to {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key
