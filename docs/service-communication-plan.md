# Service Communication Plan: video-clone-backend ↔ Lip-Sync-Experiment

## Overview

This document outlines the architecture and implementation plan for hosting `video-clone-backend` and `Lip-Sync-Experiment` as separate services with secure communication between them.

## Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     video-clone-backend                          │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │ Avatar   │──▶│ AvatarJob    │──▶│ LiveTalking Service    │  │
│  │ Router   │   │ Service      │   │ (CLI or RunPod API)    │  │
│  └──────────┘   └──────────────┘   └────────────────────────┘  │
│                                                                  │
│  ┌──────────────────┐                                           │
│  │ Avatar Backend   │  ◀── B2B API (X-API-Key auth)             │
│  │ Router           │                                            │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

## Target Architecture

```
┌─────────────────────────────────┐      ┌─────────────────────────────────┐
│     video-clone-backend          │      │     Lip-Sync-Experiment          │
│     (API Server)                 │      │     (Processing Server)          │
│                                  │      │                                  │
│  ┌──────────┐   ┌──────────────┐│      │┌──────────────┐   ┌───────────┐ │
│  │ Avatar   │──▶│ AvatarJob    ││      ││ Job Receiver │──▶│ Avatar    │ │
│  │ Router   │   │ Service      │├─────▶││ Endpoint     │   │ Generator │ │
│  └──────────┘   └──────────────┘│ HTTP ││              │   │           │ │
│                                  │      │└──────────────┘   └───────────┘ │
│  ┌──────────────────┐           │      │         │                       │
│  │ Callback         │◀──────────┼──────┼─────────┘ (on complete)         │
│  │ Endpoint         │   HTTP    │      │                                  │
│  └──────────────────┘           │      │                                  │
└─────────────────────────────────┘      └─────────────────────────────────┘
         │                                            │
         │              ┌─────────┐                   │
         └─────────────▶│   S3    │◀──────────────────┘
                        │ (shared)│
                        └─────────┘
```

## Communication Patterns

### Pattern 1: Job Submission (Backend → Lip-Sync)

```
POST https://lipsync.example.com/api/v1/jobs
Headers:
  X-API-Key: {LIPSYNC_API_KEY}
  Content-Type: application/json

Body:
{
  "job_id": "uuid",
  "video_model_id": "uuid",
  "user_id": 123,
  "video_url": "https://s3.../presigned-url",
  "callback_url": "https://backend.example.com/api/v1/internal/avatar/callback",
  "options": {
    "max_frames": 1800,
    "img_size": 256,
    "model": "wav2lip"
  }
}

Response:
{
  "success": true,
  "job_id": "uuid",
  "status": "queued"
}
```

### Pattern 2: Progress Updates (Lip-Sync → Backend)

```
POST https://backend.example.com/api/v1/internal/avatar/{job_id}/progress
Headers:
  X-API-Key: {BACKEND_API_KEY}
  Content-Type: application/json

Body:
{
  "stage": "TRAINING",
  "progress_percent": 45,
  "message": "Processing frame 500/1800"
}

Response:
{
  "success": true
}
```

### Pattern 3: Job Completion Callback (Lip-Sync → Backend)

```
POST https://backend.example.com/api/v1/internal/avatar/{job_id}/callback
Headers:
  X-API-Key: {BACKEND_API_KEY}
  Content-Type: application/json

Body (Success):
{
  "status": "completed",
  "s3_key": "avatars/{user_id}/{video_model_id}.tar",
  "frame_count": 1800,
  "processing_time_seconds": 300
}

Body (Failure):
{
  "status": "failed",
  "error_message": "Out of memory during processing",
  "error_code": "OOM_ERROR"
}

Response:
{
  "success": true,
  "message": "Job status updated"
}
```

## API Contracts

### Lip-Sync-Experiment Endpoints (to implement)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/jobs` | POST | X-API-Key | Submit new avatar generation job |
| `/api/v1/jobs/{job_id}` | GET | X-API-Key | Get job status |
| `/api/v1/jobs/{job_id}` | DELETE | X-API-Key | Cancel running job |
| `/api/v1/health` | GET | None | Health check endpoint |
| `/api/v1/capacity` | GET | X-API-Key | Check available processing slots |

### video-clone-backend Endpoints (to add/modify)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/internal/avatar/{job_id}/callback` | POST | X-API-Key | Receive completion callback |
| `/api/v1/internal/avatar/{job_id}/progress` | POST | X-API-Key | Receive progress updates |

### Existing Endpoints (already implemented)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/internal/avatar/pending-videos` | GET | X-API-Key | List pending videos |
| `/api/v1/internal/avatar/{model_id}/complete` | POST | X-API-Key | Mark job complete |
| `/api/v1/internal/avatar/jobs/status` | GET | X-API-Key | Queue status |

## Security

### API Key Authentication

Both services use symmetric API keys for authentication:

```python
# Environment variables

# video-clone-backend
LIPSYNC_SERVICE_URL=https://lipsync.example.com
LIPSYNC_API_KEY=your-secret-key-here  # Key to call Lip-Sync

# Lip-Sync-Experiment
BACKEND_CALLBACK_URL=https://backend.example.com
BACKEND_API_KEY=your-secret-key-here  # Key to call Backend
SERVICE_API_KEY=your-secret-key-here  # Key that Backend uses to call us
```

### Request Signing (Optional Enhancement)

For additional security, implement HMAC request signing:

```python
import hmac
import hashlib
import time

def sign_request(body: str, secret: str, timestamp: int) -> str:
    message = f"{timestamp}.{body}"
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
```

### IP Whitelisting (Production)

Configure firewall rules to only allow traffic between known service IPs.

## Implementation Plan

### Phase 1: Backend Modifications (video-clone-backend)

#### Task 1.1: Add Remote Service Client
Create a new service client for communicating with Lip-Sync-Experiment.

**Files to create:**
- `app/services/lipsync_client/__init__.py`
- `app/services/lipsync_client/lipsync_client.py`
- `app/services/lipsync_client/schemas.py`

**Configuration:**
```python
# Add to environment
LIPSYNC_SERVICE_URL: str  # e.g., https://lipsync.example.com
LIPSYNC_API_KEY: str      # API key for authentication
LIPSYNC_TIMEOUT: int = 30 # Request timeout in seconds
```

#### Task 1.2: Add Callback Endpoints
Add new endpoints for receiving callbacks from Lip-Sync service.

**Files to modify:**
- `app/routers/avatar_backend.py` - Add callback and progress endpoints

**New endpoints:**
- `POST /internal/avatar/{job_id}/callback` - Receive completion notification
- `POST /internal/avatar/{job_id}/progress` - Receive progress updates

#### Task 1.3: Modify Job Trigger Logic
Update `AvatarJobService` to support remote service mode.

**Files to modify:**
- `app/services/avatar_job/avatar_job_service.py`
- `app/services/livetalking/livetalking_config.py`

**New execution mode:**
```python
class ExecutionMode(Enum):
    CLI = "cli"           # Local subprocess
    RUNPOD = "runpod"     # RunPod API (existing)
    REMOTE = "remote"     # Separate Lip-Sync service (new)
```

### Phase 2: Lip-Sync-Experiment Service

#### Task 2.1: Create FastAPI Application
Set up the FastAPI server with job management.

**Files to create:**
- `main.py` - FastAPI application entry point
- `app/routers/jobs.py` - Job endpoints
- `app/services/auth.py` - API key authentication
- `app/services/job_processor.py` - Job queue and processor
- `app/services/callback_client.py` - Callback to backend

#### Task 2.2: Implement Job Queue
Create a job queue system with concurrency control.

**Features:**
- Queue pending jobs
- Limit concurrent processing
- Track job status
- Handle failures and retries

#### Task 2.3: Implement Callback System
Send progress updates and completion notifications back to backend.

### Phase 3: Integration Testing

#### Task 3.1: Local Testing
- Run both services locally
- Test job submission and callbacks
- Verify progress updates

#### Task 3.2: Staging Deployment
- Deploy to staging environment
- Test with real S3 uploads
- Monitor performance and latency

### Phase 4: Production Deployment

#### Task 4.1: Infrastructure Setup
- Provision servers for Lip-Sync service
- Configure networking and security groups
- Set up monitoring and alerting

#### Task 4.2: Deployment
- Deploy services
- Configure environment variables
- Enable production traffic

## Configuration Reference

### video-clone-backend Environment

```bash
# Existing
AVATAR_API_KEY=xxx              # For B2B auth (incoming)
AVATAR_MAX_CONCURRENT=3         # Max concurrent jobs

# New
LIPSYNC_SERVICE_URL=https://lipsync.example.com
LIPSYNC_API_KEY=xxx             # For calling Lip-Sync service
LIPSYNC_ENABLED=true            # Toggle remote service
LIPSYNC_TIMEOUT=30              # Request timeout (seconds)
```

### Lip-Sync-Experiment Environment

```bash
# Server
HOST=0.0.0.0
PORT=8001
DEBUG=false

# Authentication
SERVICE_API_KEY=xxx             # Incoming auth from backend

# Callbacks
BACKEND_CALLBACK_URL=https://backend.example.com
BACKEND_API_KEY=xxx             # Outgoing auth to backend

# Processing
MAX_CONCURRENT_JOBS=2
JOB_TIMEOUT=600                 # Max processing time (seconds)

# S3 (shared bucket)
S3_AWS_REGION=xxx
S3_AWS_ACCESS_KEY_ID=xxx
S3_AWS_SECRET_ACCESS_KEY=xxx
S3_BUCKET_NAME=xxx
```

## Error Handling

### Retry Strategy

| Error Type | Action |
|------------|--------|
| Network timeout | Retry 3x with exponential backoff |
| 5xx from Lip-Sync | Retry 3x, then mark job failed |
| 4xx from Lip-Sync | No retry, mark job failed |
| Callback failure | Retry 5x, log error if all fail |

### Circuit Breaker

Implement circuit breaker pattern for service calls:

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failures = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
```

## Monitoring

### Metrics to Track

- Job submission latency
- Callback delivery latency
- Job processing duration
- Error rates by type
- Queue depth
- Concurrent job count

### Health Checks

Both services should expose health endpoints:

```python
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health/detailed")
async def detailed_health(api_key: str = Depends(verify_api_key)):
    return {
        "status": "healthy",
        "database": await check_db(),
        "s3": await check_s3(),
        "queue_depth": get_queue_depth(),
        "active_jobs": get_active_job_count()
    }
```

## Sequence Diagrams

### Happy Path: Job Submission to Completion

```
User          Backend           Lip-Sync          S3
 │               │                  │              │
 │ Upload Video  │                  │              │
 │──────────────▶│                  │              │
 │               │ Upload to S3     │              │
 │               │─────────────────────────────────▶
 │               │                  │              │
 │               │ Create AvatarJob │              │
 │               │──────┐           │              │
 │               │      │           │              │
 │               │◀─────┘           │              │
 │               │                  │              │
 │               │ POST /jobs       │              │
 │               │ (presigned URL)  │              │
 │               │─────────────────▶│              │
 │               │                  │              │
 │               │ { queued }       │              │
 │               │◀─────────────────│              │
 │               │                  │              │
 │               │                  │ Download     │
 │               │                  │─────────────▶│
 │               │                  │              │
 │               │                  │ Process      │
 │               │                  │──────┐       │
 │               │                  │      │       │
 │               │ POST /progress   │◀─────┘       │
 │               │◀─────────────────│              │
 │               │                  │              │
 │               │                  │ Upload .tar  │
 │               │                  │─────────────▶│
 │               │                  │              │
 │               │ POST /callback   │              │
 │               │ (completed)      │              │
 │               │◀─────────────────│              │
 │               │                  │              │
 │ Poll status   │                  │              │
 │──────────────▶│                  │              │
 │ { completed } │                  │              │
 │◀──────────────│                  │              │
```

### Failure Scenario: Processing Error

```
Backend           Lip-Sync
 │                   │
 │ POST /jobs        │
 │──────────────────▶│
 │                   │
 │ { queued }        │
 │◀──────────────────│
 │                   │
 │                   │ Process fails
 │                   │──────┐
 │                   │      │
 │ POST /callback    │◀─────┘
 │ (failed, error)   │
 │◀──────────────────│
 │                   │
 │ Mark job FAILED   │
 │ Send failure email│
```

## Next Steps

1. Review and approve this plan
2. Begin Phase 1 implementation (Backend modifications)
3. Create Lip-Sync-Experiment FastAPI scaffold
4. Implement and test locally
5. Deploy to staging
6. Production rollout

---

## Implementation Status

### Phase 1: Backend Modifications ✅ COMPLETED

| Task | Status | Files |
|------|--------|-------|
| 1.1 Create LipSync client service | ✅ Done | `app/services/lipsync_client/` |
| 1.2 Add callback/progress endpoints | ✅ Done | `app/routers/avatar_backend.py`, `app/schemas/avatar_backend.py` |
| 1.3 Integrate with AvatarJobService | ✅ Done | `app/services/avatar_job/avatar_job_service.py` |

**New files created:**
- `app/services/lipsync_client/__init__.py`
- `app/services/lipsync_client/lipsync_client.py`

**New endpoints added:**
- `POST /api/v1/internal/avatar/jobs/{job_id}/callback` - Receive completion callback
- `POST /api/v1/internal/avatar/jobs/{job_id}/progress` - Receive progress updates

**New environment variables:**
- `LIPSYNC_ENABLED` - Enable remote mode (true/false)
- `LIPSYNC_SERVICE_URL` - URL of LipSync service
- `LIPSYNC_API_KEY` - API key for LipSync service
- `LIPSYNC_TIMEOUT` - Request timeout (default: 30)
- `BACKEND_PUBLIC_URL` - This backend's public URL for callbacks

### Phase 2: Lip-Sync-Experiment Service ⏳ PENDING

Waiting for implementation on the Lip-Sync-Experiment side.

---

**Author:** Claude Code
**Date:** 2026-01-30
**Status:** Phase 1 Complete - Ready for Phase 2
