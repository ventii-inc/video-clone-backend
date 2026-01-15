"""
Environment configuration for Alembic migrations.
This module provides functions to get database URLs for different environments.
"""

import os

from dotenv import load_dotenv

# Get the environment from ENV variable, default to local
env = os.getenv("ENV", "local")
dotenv_file = f".env.{env}"

# Load environment variables from the appropriate .env file
print(f"Alembic: Loading environment variables from {dotenv_file}")
load_dotenv(dotenv_file)


def get_database_url(environment: str = None) -> str:
    """
    Get the database URL for the specified environment.

    Args:
        environment: The environment to get the URL for.
            Can be 'local', 'staging', 'production', or None (uses current ENV).

    Returns:
        str: The database URL for the specified environment.
    """
    # If no specific environment is provided, use the current ENV
    if not environment:
        environment = os.getenv("ENV", "local")

    # Get database connection details from environment variables
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")

    # Construct and return the database URL
    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
