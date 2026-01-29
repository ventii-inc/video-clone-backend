# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Run development server with hot reload
python main.py
# or
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Install dependencies
uv sync

# Add a new dependency
uv add <package-name>

# Run database migrations
ENV=local alembic upgrade head

# Create a new migration
ENV=local alembic revision --autogenerate -m "Description"

# Check migration status
ENV=local alembic current
```

## Environment Configuration

The app loads environment variables from `.env.{ENV}` files based on the `ENV` variable:
- `.env.local` - Local development
- `.env.staging` - Staging environment
- `.env.production` - Production environment

Set `ENV=local` (default) to use `.env.local`.

Required environment variables:
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` - PostgreSQL connection
- `S3_AWS_REGION`, `S3_AWS_ACCESS_KEY_ID`, `S3_AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME` - AWS S3 configuration
- `FIREBASE_CREDENTIALS_FILE` - Path to Firebase service account JSON file

Optional environment variables:
- `SENTRY_DSN` - Sentry error tracking (disabled in debug mode)
- `CORS_ORIGINS` - Comma-separated list of additional CORS origins
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STANDARD`, `STRIPE_PRICE_MINUTES` - Stripe billing
- `FISH_AUDIO_API_KEY` - Fish Audio voice cloning and TTS
- `LIVETALKING_ROOT`, `LIVETALKING_VENV`, `LIVETALKING_MODE` - LiveTalking avatar generation (cli/api/auto)
- `AVATAR_API_KEY` - API key for backend-to-backend avatar endpoints
- `AVATAR_MAX_CONCURRENT` - Max concurrent avatar generation jobs (default: 3)
- `AVATAR_JOB_CHECK_INTERVAL` - Interval in seconds for background job status checks (default: 10)

## Architecture

**Stack:** FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Firebase Auth + S3

**API Pattern:**
- All API routes are prefixed with `/api/v1` (defined in `app/utils/constants.py`)
- Routers use tags for OpenAPI grouping
- User authentication: Firebase token in `Authorization: Bearer <token>` header
- Backend-to-backend auth: API key in `X-API-Key` header (see `app/services/api_key/`)

**Key Modules:**
- `app/routers/` - API endpoints (auth, users, video_models, voice_models, generate, videos, dashboard, billing, settings, avatar, avatar_backend)
- `app/models/` - SQLAlchemy models (User, UserProfile, VideoModel, VoiceModel, GeneratedVideo, Subscription, AvatarJob, etc.)
- `app/schemas/` - Pydantic request/response schemas
- `app/services/` - Business logic services (see Service Layer below)
- `app/utils/` - Helpers (logger, constants, response_utils, sentry_utils)
- `app/middleware/` - Performance monitoring middleware

**Service Layer:**
- `firebase/` - Firebase auth, token verification, user dependencies
- `s3/` - S3 file uploads, downloads, presigned URLs
- `stripe/` - Stripe payments, subscriptions, webhooks
- `fish_audio/` - Voice cloning and TTS via Fish Audio API
- `livetalking/` - Avatar generation via CLI subprocess or RunPod API
- `avatar_job/` - Avatar generation job queue with concurrency control
- `scheduler/` - Background task scheduler for periodic job status checks
- `video/` - Video generation orchestration
- `audio/` - Audio processing utilities
- `progress/` - Progress tracking for long-running operations
- `usage_service.py` - Credit/minutes tracking per billing period

**Avatar Generation Pipeline:**
1. User uploads video → `VideoModel` created with `status=PENDING`
2. `AvatarJob` queued → job processor checks concurrent slots
3. Execution mode chosen (CLI local or RunPod API based on GPU availability)
4. Progress tracked via `ProcessingStage` enum (PENDING → PREPARING → TRAINING → FINALIZING → COMPLETED)
5. Result uploaded to S3 as `.tar` archive → email notification sent

**Database Session Patterns:**
- `get_db()` - Async FastAPI dependency for route injection (use with `Depends(get_db)`)
- `get_db_session()` - Async context manager for standalone operations (auto-commits on success, rolls back on error)
- `get_sync_db()` / `get_sync_db_session()` - Sync versions for non-async contexts (e.g., Alembic)

**Adding New Features:**
1. Create model in `app/models/` → import in `app/models/__init__.py`
2. Create schema in `app/schemas/` → import in `app/schemas/__init__.py`
3. Create router in `app/routers/` → import in `app/routers/__init__.py` → register in `main.py`
4. Run `ENV=local alembic revision --autogenerate -m "Description"` → `ENV=local alembic upgrade head`

**Response Utilities:**
```python
from app.utils.response_utils import success, error_response, not_found_error, validation_error

# Success response
return success(data={"id": 123}, message="Created successfully")

# Error responses
return not_found_error("Video model")
return validation_error("Invalid file type", details={"field": "video"})
return error_response("CUSTOM_ERROR", "Something went wrong", status_code=400)
```

**Firebase Auth Usage:**
```python
from fastapi import Depends
from app.services.firebase import get_current_user, get_current_user_or_create, get_optional_user
from app.models import User

# Protected route - requires existing user
@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user)):
    return {"email": user.email, "name": user.name}

# Auto-create user on first login
@router.post("/login")
async def login(user: User = Depends(get_current_user_or_create)):
    return {"message": "Welcome", "user_id": user.id}

# Optional auth - returns None if not authenticated
@router.get("/public")
async def public_route(user: User | None = Depends(get_optional_user)):
    return {"authenticated": user is not None}
```

**API Key Auth (Backend-to-Backend):**
```python
from fastapi import Depends
from app.services.api_key import get_api_key

@router.post("/internal/callback")
async def internal_callback(api_key: str = Depends(get_api_key)):
    # Protected by X-API-Key header
    pass
```

**S3 Service Usage:**
```python
from app.services.s3 import s3_service

await s3_service.upload_file("/path/to/file.mp4", "videos/user123/video.mp4")
await s3_service.upload_fileobj(file.file, "videos/user123/video.mp4", content_type="video/mp4")
await s3_service.download_file("videos/user123/video.mp4", "/local/path.mp4")
url = await s3_service.generate_presigned_url("videos/user123/video.mp4")
upload_url = await s3_service.generate_presigned_upload_url("videos/user123/video.mp4", content_type="video/mp4")
exists = await s3_service.file_exists("videos/user123/video.mp4")
await s3_service.delete_file("videos/user123/video.mp4")
s3_key = s3_service.generate_s3_key("user123", "video.mp4", media_type="videos")
```

**Fish Audio Service (Voice Cloning & TTS):**
```python
from app.services.fish_audio import fish_audio_service

# Clone voice from audio bytes
result = await fish_audio_service.clone_voice(audio_data, "Voice Name", visibility="private")
if result.success:
    model_id = result.model_id

# Generate speech from cloned voice
tts_result = await fish_audio_service.text_to_speech("Hello world", reference_id=model_id)
if tts_result.success:
    audio_path = tts_result.audio_path
```

**Avatar Job Service:**
```python
from app.services.avatar_job import avatar_job_service

# Create and queue a job
job = await avatar_job_service.create_job(video_model_id, user_id, db)

# Process pending jobs (respects AVATAR_MAX_CONCURRENT)
jobs_started = await avatar_job_service.process_pending_jobs(db)

# Retry a failed job
job = await avatar_job_service.retry_job(job_id, db)
```

**Firebase Setup:**
1. Download service account JSON from Firebase Console
2. Save as `firebase-credentials-dev.json` (local) or `firebase-credentials.json` (production)
3. Set `FIREBASE_CREDENTIALS_FILE` in `.env.{ENV}` if using custom path

## AWS Database Commands

**Staging Aurora Serverless (Tokyo):**
```bash
# Start the staging database
aws rds start-db-cluster --region ap-northeast-1 --db-cluster-identifier video-clone-stg-cluster

# Stop the staging database
aws rds stop-db-cluster --region ap-northeast-1 --db-cluster-identifier video-clone-stg-cluster

# Check database status
aws rds describe-db-clusters --region ap-northeast-1 --db-cluster-identifier video-clone-stg-cluster --query 'DBClusters[0].Status' --output text
```

Note: Aurora automatically restarts stopped clusters after 7 days.
