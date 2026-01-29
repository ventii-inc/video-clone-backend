"""Firebase authentication middleware and utilities"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from firebase_admin import auth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import User
from app.services.firebase.firebase_config import get_firebase_app

logger = logging.getLogger(__name__)


@dataclass
class TokenData:
    """Decoded Firebase token data"""

    uid: str
    email: Optional[str] = None
    name: Optional[str] = None
    email_verified: bool = False


def verify_token(id_token: str) -> TokenData:
    """
    Verify a Firebase ID token and extract user data (synchronous version).

    Args:
        id_token: The Firebase ID token to verify

    Returns:
        TokenData: The decoded token data

    Raises:
        HTTPException: If token verification fails
    """
    # Ensure Firebase is initialized
    get_firebase_app()

    try:
        decoded_token = auth.verify_id_token(id_token)

        return TokenData(
            uid=decoded_token["uid"],
            email=decoded_token.get("email"),
            name=decoded_token.get("name"),
            email_verified=decoded_token.get("email_verified", False),
        )
    except auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except auth.RevokedIdTokenError:
        raise HTTPException(status_code=401, detail="Token has been revoked")
    except auth.InvalidIdTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def verify_token_async(id_token: str) -> TokenData:
    """
    Verify a Firebase ID token and extract user data (non-blocking async version).

    Uses asyncio.to_thread() to avoid blocking the event loop during
    the synchronous Firebase SDK call.

    Args:
        id_token: The Firebase ID token to verify

    Returns:
        TokenData: The decoded token data

    Raises:
        HTTPException: If token verification fails
    """
    # Ensure Firebase is initialized
    get_firebase_app()

    try:
        decoded_token = await asyncio.to_thread(auth.verify_id_token, id_token)

        return TokenData(
            uid=decoded_token["uid"],
            email=decoded_token.get("email"),
            name=decoded_token.get("name"),
            email_verified=decoded_token.get("email_verified", False),
        )
    except auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except auth.RevokedIdTokenError:
        raise HTTPException(status_code=401, detail="Token has been revoked")
    except auth.InvalidIdTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


def get_token_from_header(request: Request) -> str:
    """
    Extract Bearer token from Authorization header.

    Args:
        request: The FastAPI request object

    Returns:
        str: The extracted token

    Raises:
        HTTPException: If Authorization header is missing or invalid
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        raise HTTPException(
            status_code=401, detail="Authorization header missing"
        )

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid authorization header format. Expected 'Bearer <token>'"
        )

    return auth_header.split("Bearer ")[1]


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """
    FastAPI dependency to get the current authenticated user.

    This dependency:
    1. Extracts the Bearer token from the Authorization header
    2. Verifies the token with Firebase (non-blocking)
    3. Looks up or creates the user in the database
    4. Returns the User object

    Args:
        request: The FastAPI request object
        db: SQLAlchemy async database session

    Returns:
        User: The authenticated user

    Raises:
        HTTPException: If authentication fails or user not found
    """
    token = get_token_from_header(request)
    token_data = await verify_token_async(token)

    if not token_data.email:
        raise HTTPException(
            status_code=401, detail="Email not found in token"
        )

    # Look up user by Firebase UID
    result = await db.execute(select(User).where(User.firebase_uid == token_data.uid))
    user = result.scalar_one_or_none()

    if not user:
        # Check if user exists by email (could have been created differently)
        result = await db.execute(select(User).where(User.email == token_data.email))
        user = result.scalar_one_or_none()

        if user:
            # Update firebase_uid if user exists but uid doesn't match
            user.firebase_uid = token_data.uid
            await db.commit()
        else:
            raise HTTPException(
                status_code=404, detail="User not found. Please register first."
            )

    return user


async def get_current_user_or_create(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """
    FastAPI dependency to get or create the current authenticated user.

    Similar to get_current_user but creates the user if they don't exist.

    Args:
        request: The FastAPI request object
        db: SQLAlchemy async database session

    Returns:
        User: The authenticated user (existing or newly created)

    Raises:
        HTTPException: If authentication fails
    """
    token = get_token_from_header(request)
    token_data = await verify_token_async(token)

    if not token_data.email:
        raise HTTPException(
            status_code=401, detail="Email not found in token"
        )

    # Look up user by Firebase UID
    result = await db.execute(select(User).where(User.firebase_uid == token_data.uid))
    user = result.scalar_one_or_none()

    if not user:
        # Check if user exists by email
        result = await db.execute(select(User).where(User.email == token_data.email))
        user = result.scalar_one_or_none()

        if user:
            # Update firebase_uid if user exists but uid doesn't match
            user.firebase_uid = token_data.uid
        else:
            # Create new user
            user = User(
                firebase_uid=token_data.uid,
                email=token_data.email,
                name=token_data.name,
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)

    return user


async def get_optional_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    FastAPI dependency to optionally get the current user.

    Returns None if no valid token is provided instead of raising an exception.

    Args:
        request: The FastAPI request object
        db: SQLAlchemy async database session

    Returns:
        Optional[User]: The authenticated user or None
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    try:
        token = auth_header.split("Bearer ")[1]
        token_data = await verify_token_async(token)

        if not token_data.email:
            return None

        result = await db.execute(select(User).where(User.firebase_uid == token_data.uid))
        user = result.scalar_one_or_none()
        return user
    except HTTPException:
        return None
    except Exception:
        return None
