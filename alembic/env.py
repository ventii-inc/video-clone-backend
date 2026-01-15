"""Alembic migration environment configuration"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import environment configuration
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_config import get_database_url

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base and all models to ensure they're registered
from app.db.database import Base
from app.models import *  # noqa: F401, F403

# Set target metadata for autogenerate
target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    Determine which database objects to include in migrations.

    Only include objects that are defined in our models (compare_to is not None).
    This prevents Alembic from trying to drop tables that exist in DB but not in models.
    """
    if compare_to is None and type_ == "table":
        return False
    return True


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = get_database_url(os.getenv("ENV"))

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    db_url = get_database_url(os.getenv("ENV"))

    engine = create_engine(db_url)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
