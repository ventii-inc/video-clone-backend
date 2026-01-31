import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load environment-specific .env file BEFORE any app imports
env = os.getenv("ENV", "local")
dotenv_file = f".env.{env}"
load_dotenv(dotenv_file)

# Get backend mode: 'api' (default, full app) or 'worker' (minimal, CLI-focused)
BACKEND_MODE = os.getenv("BACKEND_MODE", "api")

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

# Conditional imports based on backend mode
if BACKEND_MODE == "api":
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
    from app.services.firebase import initialize_firebase, is_firebase_initialized
elif BACKEND_MODE == "worker":
    from app.routers import worker_router

# Initialize Sentry for error tracking (only in non-debug environments)
sentry_enabled = configure_sentry()
if sentry_enabled:
    logger.info("Sentry error tracking initialized")


if BACKEND_MODE == "api":
    async def prewarm_firebase():
        """Pre-warm Firebase by fetching Google's public keys."""
        import asyncio
        from firebase_admin import auth
        try:
            # Make a dummy verification call to force fetching public keys
            # This will fail but triggers the key fetch and caches them
            await asyncio.to_thread(auth.verify_id_token, "dummy_token")
        except Exception:
            pass  # Expected to fail, we just want to cache the keys
        logger.info("Firebase public keys pre-warmed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    if BACKEND_MODE == "api":
        # Startup - API mode
        logger.info("Initializing Firebase...")
        try:
            initialize_firebase()
            await prewarm_firebase()
        except Exception as e:
            logger.warning(f"Firebase initialization failed: {e}")

        logger.info("Starting background scheduler...")
        await scheduler_service.start()

        yield

        # Shutdown
        logger.info("Stopping background scheduler...")
        await scheduler_service.stop()
    else:
        # Worker mode - minimal startup
        logger.info(f"Worker mode startup (BACKEND_MODE={BACKEND_MODE})")
        yield
        logger.info("Worker mode shutdown")


# App title varies by mode
app_title = "Video Clone Backend" if BACKEND_MODE == "api" else "Video Clone Worker"
app_description = (
    "AI Clone Video Generation Service API"
    if BACKEND_MODE == "api"
    else "AI Clone Video Generation Worker (RunPod)"
)

app = FastAPI(
    title=app_title,
    description=app_description,
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

# Register routers based on backend mode
if BACKEND_MODE == "api":
    # Full API mode - all user-facing routers
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
elif BACKEND_MODE == "worker":
    # Worker mode - only worker endpoints
    app.include_router(worker_router, prefix=API_PREFIX)


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
    if BACKEND_MODE == "worker":
        return {"message": "Video Clone Worker (RunPod)", "version": "0.1.0", "mode": "worker"}
    return {"message": "Welcome to Video Clone Backend API", "version": "0.1.0", "mode": "api"}


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

    response = {
        "status": "healthy",
        "mode": BACKEND_MODE,
        "database": db_status,
    }

    # Add scheduler status only in API mode
    if BACKEND_MODE == "api":
        response["scheduler"] = "running" if scheduler_service._running else "stopped"

    return response


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting Video Clone Backend (env={env}, mode={BACKEND_MODE}, debug={is_debug()})")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=is_debug())
