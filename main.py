import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load environment-specific .env file BEFORE any app imports
env = os.getenv("ENV", "local")
dotenv_file = f".env.{env}"
load_dotenv(dotenv_file)

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware import PerformanceMiddleware
from app.utils import (
    logger,
    configure_sentry,
    is_debug,
    API_PREFIX,
)
from app.utils.sentry_utils import capture_exception
from app.routers import (
    auth_router,
    users_router,
    video_models_router,
    voice_models_router,
    generate_router,
    videos_router,
    dashboard_router,
    billing_router,
    settings_router,
    avatar_router,
    avatar_backend_router,
)
from app.services.scheduler import scheduler_service

# Initialize Sentry for error tracking (only in non-debug environments)
sentry_enabled = configure_sentry()
if sentry_enabled:
    logger.info("Sentry error tracking initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    logger.info("Starting background scheduler...")
    await scheduler_service.start()

    yield

    # Shutdown
    logger.info("Stopping background scheduler...")
    await scheduler_service.stop()


app = FastAPI(
    title="Video Clone Backend",
    description="AI Clone Video Generation Service API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# CORS configuration - allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Performance monitoring middleware
app.add_middleware(PerformanceMiddleware)

# Register routers
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(video_models_router, prefix=API_PREFIX)
app.include_router(voice_models_router, prefix=API_PREFIX)
app.include_router(generate_router, prefix=API_PREFIX)
app.include_router(videos_router, prefix=API_PREFIX)
app.include_router(dashboard_router, prefix=API_PREFIX)
app.include_router(billing_router, prefix=API_PREFIX)
app.include_router(settings_router, prefix=API_PREFIX)
app.include_router(avatar_router, prefix=API_PREFIX)
app.include_router(avatar_backend_router, prefix=API_PREFIX)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    # Log the error
    logger.error(
        f"Unhandled exception: {exc.__class__.__name__}: {exc}",
        exc_info=True,
    )

    # Capture exception to Sentry
    capture_exception(exc)

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            }
        },
    )


@app.get("/")
async def root():
    return {"message": "Welcome to Video Clone Backend API", "version": "0.1.0"}


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Try a simple query to verify database connection
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "disconnected"

    return {
        "status": "healthy",
        "database": db_status,
        "scheduler": "running" if scheduler_service._running else "stopped",
    }


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting Video Clone Backend (env={env}, debug={is_debug()})")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=is_debug())
