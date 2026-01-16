import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

db_port = os.getenv("DB_PORT", "5432")
if db_port == "None" or not db_port:
    db_port = "5432"

# Sync database URL (for Alembic migrations)
DATABASE_URL = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{db_port}/{os.getenv('DB_NAME')}"
)

# Async database URL (for FastAPI)
ASYNC_DATABASE_URL = (
    f"postgresql+asyncpg://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{db_port}/{os.getenv('DB_NAME')}"
)

# Sync engine (for migrations)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine (for FastAPI)
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async dependency for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions (background tasks)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as error:
            await session.rollback()
            raise error
        finally:
            await session.close()


# Keep sync versions for backward compatibility
def get_sync_db():
    """Sync dependency for routes that need sync access."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_sync_db_session():
    """Sync context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as error:
        db.rollback()
        raise error
    finally:
        db.close()
