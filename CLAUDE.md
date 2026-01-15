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

## Architecture

**Stack:** FastAPI + SQLAlchemy 2.0 + PostgreSQL

**Structure:**
```
main.py              # App entry point, loads env files before imports
app/
  config.py          # Pydantic Settings for typed configuration
  db/
    database.py      # SQLAlchemy engine, session factory, Base
    __init__.py      # Exports: get_db, get_db_session, engine, SessionLocal, Base
  models/
    __init__.py      # Import models here, exports Base
  services/
    s3/
      s3_config.py   # S3Settings (Pydantic) with S3_ env prefix
      s3_service.py  # S3Service: upload, presigned URLs, delete, etc.
      __init__.py    # Exports: s3_service, S3Service, s3_settings
```

**Database Session Patterns:**
- `get_db()` - FastAPI dependency for route injection (use with `Depends(get_db)`)
- `get_db_session()` - Context manager for standalone operations (auto-commits on success, rolls back on error)

**Adding New Models:**
1. Create model file in `app/models/`
2. Import the model in `app/models/__init__.py` to register with Base
3. Models inherit from `Base` imported from `app.db`

**S3 Service Usage:**
```python
from app.services.s3 import s3_service

# Upload a file
await s3_service.upload_file("/path/to/file.mp4", "videos/user123/video.mp4")

# Upload file object (from FastAPI UploadFile)
await s3_service.upload_fileobj(file.file, "videos/user123/video.mp4", content_type="video/mp4")

# Generate presigned URL for download/streaming
url = await s3_service.generate_presigned_url("videos/user123/video.mp4")

# Generate presigned URL for upload
upload_url = await s3_service.generate_presigned_upload_url("videos/user123/video.mp4", content_type="video/mp4")

# Check if file exists
exists = await s3_service.file_exists("videos/user123/video.mp4")

# Delete a file
await s3_service.delete_file("videos/user123/video.mp4")

# Generate S3 key helper
s3_key = s3_service.generate_s3_key("user123", "video.mp4", media_type="videos")
```
