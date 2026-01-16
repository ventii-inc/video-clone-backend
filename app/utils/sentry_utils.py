"""Sentry error tracking utilities."""

import functools
import os
from typing import Any, Callable, TypeVar

from app.utils.environment import is_debug, get_environment

# Type variable for generic function wrapping
F = TypeVar("F", bound=Callable[..., Any])

# Track if Sentry has been initialized
_sentry_initialized = False


def configure_sentry(dsn_env_var: str = "SENTRY_DSN") -> bool:
    """Initialize Sentry for error tracking.

    Only initializes in non-debug environments (staging/production).
    Requires SENTRY_DSN environment variable to be set.

    Args:
        dsn_env_var: Environment variable name containing the Sentry DSN

    Returns:
        True if Sentry was initialized, False otherwise
    """
    global _sentry_initialized

    if _sentry_initialized:
        return True

    # Skip in debug/local mode
    if is_debug():
        return False

    dsn = os.getenv(dsn_env_var)
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=get_environment(),
            traces_sample_rate=1.0,  # Capture 100% of transactions
            profiles_sample_rate=0.1,  # Profile 10% of transactions
            enable_tracing=True,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            # Set to True to send PII data (be careful in production)
            send_default_pii=False,
        )

        _sentry_initialized = True
        return True

    except ImportError:
        # sentry-sdk not installed
        return False
    except Exception:
        # Failed to initialize
        return False


def is_sentry_initialized() -> bool:
    """Check if Sentry has been initialized.

    Returns:
        True if Sentry is initialized
    """
    return _sentry_initialized


def capture_exception(exception: Exception) -> None:
    """Capture an exception and send it to Sentry.

    Args:
        exception: The exception to capture
    """
    if not _sentry_initialized:
        return

    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exception)
    except Exception:
        pass  # Don't let Sentry errors break the application


def capture_message(message: str, level: str = "info") -> None:
    """Capture a message and send it to Sentry.

    Args:
        message: The message to capture
        level: Log level (debug, info, warning, error, fatal)
    """
    if not _sentry_initialized:
        return

    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def wrap_with_sentry(func: F) -> F:
    """Decorator to wrap async functions with Sentry error capture.

    Use this for background tasks to ensure exceptions are captured.

    Args:
        func: The async function to wrap

    Returns:
        Wrapped function that captures exceptions to Sentry
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            capture_exception(e)
            raise  # Re-raise to allow normal error handling

    return wrapper  # type: ignore


def set_user_context(user_id: int | str, email: str | None = None) -> None:
    """Set the user context for Sentry events.

    Args:
        user_id: User ID
        email: User email (optional)
    """
    if not _sentry_initialized:
        return

    try:
        import sentry_sdk
        sentry_sdk.set_user({
            "id": str(user_id),
            "email": email,
        })
    except Exception:
        pass


def clear_user_context() -> None:
    """Clear the user context."""
    if not _sentry_initialized:
        return

    try:
        import sentry_sdk
        sentry_sdk.set_user(None)
    except Exception:
        pass
