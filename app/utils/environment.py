"""Environment detection utilities."""

import os


def get_environment() -> str:
    """Get the current environment name.

    Returns:
        Environment name: 'local', 'staging', or 'production'
    """
    return os.getenv("ENV", "local")


def is_production() -> bool:
    """Check if running in production environment.

    Returns:
        True if ENV is 'production'
    """
    return get_environment() == "production"


def is_staging() -> bool:
    """Check if running in staging environment.

    Returns:
        True if ENV is 'staging'
    """
    return get_environment() == "staging"


def is_debug() -> bool:
    """Check if running in debug/local mode.

    Returns:
        True if ENV is 'local' or not set
    """
    return get_environment() == "local"


def is_deployed() -> bool:
    """Check if running in a deployed environment (staging or production).

    Returns:
        True if ENV is 'staging' or 'production'
    """
    return is_production() or is_staging()
