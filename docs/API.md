# API Documentation

Base URL: `/api/v1`

---

## Authentication

All protected endpoints require a Firebase ID token in the Authorization header:

```
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

**Error Responses:**
- `401 Unauthorized` - Missing, expired, or invalid token
- `404 Not Found` - User not registered (for endpoints requiring existing user)

---

## Endpoints

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/login` | Login or register user. Creates user on first login. |
| GET | `/auth/me` | Get current user with profile and subscription details. |

**POST /auth/login Response:**
- `user` - User object (id, email, name, avatar_url, created_at)
- `is_new_user` - Boolean indicating first login
- `onboarding_completed` - Boolean indicating profile setup status

---

### User Profile

| Method | Path | Description |
|--------|------|-------------|
| POST | `/users/profile` | Create profile during onboarding |
| GET | `/users/profile` | Get user's profile |
| PATCH | `/users/profile` | Update profile fields |

**Profile Fields:**
- `usage_type` - "personal" or "business"
- `company_size` - "1-10", "11-50", "51-200", "201-1000", "1001+" (optional)
- `role` - "executive", "manager", "staff", "freelancer", "other"
- `use_cases` - Array: "marketing", "training", "support", "social", "presentation", "other"
- `referral_source` - "search", "social", "referral", "ads", "media", "other"

---

### Video Models

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models/video` | List video models (paginated) |
| GET | `/models/video/{id}` | Get video model by ID |
| POST | `/models/video` | Create video model, get upload URL |
| POST | `/models/video/{id}/upload-complete` | Mark upload done, start processing |
| PATCH | `/models/video/{id}` | Update model name |
| DELETE | `/models/video/{id}` | Delete video model |

**Query Params (GET list):** `status`, `page`, `limit`

**Create Request:**
- `name` - Display name (1-100 chars)
- `file_name` - Original filename
- `file_size_bytes` - File size (max 500MB)
- `content_type` - "video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"

**Model Status:** pending → uploading → processing → completed/failed

---

### Voice Models

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models/voice` | List voice models (paginated) |
| GET | `/models/voice/{id}` | Get voice model by ID |
| POST | `/models/voice` | Create voice model, get upload URL |
| POST | `/models/voice/{id}/upload-complete` | Mark upload done, start processing |
| PATCH | `/models/voice/{id}` | Update model name |
| DELETE | `/models/voice/{id}` | Delete voice model |

**Query Params (GET list):** `status`, `source_type`, `page`, `limit`

**Create Request:**
- `name` - Display name (1-100 chars)
- `file_name` - Original filename
- `file_size_bytes` - File size (max 100MB)
- `content_type` - "audio/mpeg", "audio/wav", "audio/mp4", "audio/webm", etc.
- `source_type` - "upload" or "recording"

---

### Video Generation

| Method | Path | Description |
|--------|------|-------------|
| POST | `/generate` | Start video generation |
| GET | `/generate/{id}/status` | Poll generation status |

**Generate Request:**
- `video_model_id` - UUID of video model
- `voice_model_id` - UUID of voice model
- `title` - Optional title (max 200 chars)
- `input_text` - Text to speak (1-5000 chars)
- `language` - "ja" or "en" (default: "ja")
- `resolution` - "720p" or "1080p" (default: "720p")

**Generate Response:**
- `video` - Generated video object with status, queue_position, credits_used
- `usage` - Current usage (minutes_used, minutes_remaining, minutes_limit)

**Status Response:**
- `status` - "queued", "processing", "completed", "failed"
- `progress_percent` - 0-100
- `output_video_url` - Available when completed
- `error_message` - Set when failed

**Error:** `402 Payment Required` - Insufficient credits

---

### Generated Videos

| Method | Path | Description |
|--------|------|-------------|
| GET | `/videos` | List generated videos (paginated) |
| GET | `/videos/{id}` | Get video details |
| GET | `/videos/{id}/download` | Get presigned download URL |
| DELETE | `/videos/{id}` | Delete generated video |
| POST | `/videos/{id}/regenerate` | Regenerate with same settings |

**Query Params (GET list):** `status_filter`, `video_model_id`, `voice_model_id`, `sort`, `order`, `page`, `limit`

**Download Response:**
- `download_url` - Presigned S3 URL
- `file_name` - Suggested filename
- `expires_in_seconds` - URL expiration time

---

### Dashboard & Usage

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Dashboard summary |
| GET | `/usage` | Current month usage |
| GET | `/usage/history` | Usage history (query: `months` 1-12) |

**Dashboard Response:**
- `usage` - minutes_used, minutes_remaining, minutes_limit, period dates
- `models` - video_models_count, voice_models_count
- `recent_videos` - Last 5 generated videos
- `subscription` - plan_type, status, current_period_end

---

### Billing

| Method | Path | Description |
|--------|------|-------------|
| GET | `/billing/subscription` | Get subscription details |
| GET | `/billing/invoices` | Get payment history |
| POST | `/billing/checkout` | Create checkout session (not implemented) |
| POST | `/billing/portal` | Open billing portal (not implemented) |
| POST | `/billing/purchase-minutes` | Buy additional minutes (not implemented) |

**Subscription Response:**
- `plan_type` - "free", "starter", "pro", etc.
- `status` - "active", "canceled", etc.
- `monthly_minutes_limit` - Included minutes
- `current_period_start/end` - Billing period dates
- `cancel_at_period_end` - Pending cancellation flag

---

### Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | Get user settings |
| PATCH | `/settings` | Update settings |
| POST | `/settings/avatar` | Get avatar upload URL |
| POST | `/settings/avatar/confirm` | Confirm avatar upload |
| POST | `/settings/account/export` | Request data export |
| DELETE | `/settings/account` | Delete account |

**Settings Fields:**
- `email_notifications` - Boolean
- `language` - Preferred language
- `default_resolution` - "720p" or "1080p"

---

### Health Check

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Welcome message |
| GET | `/health` | No | Health check with DB status |

---

## Upload Flow

For video models, voice models, and avatars:

1. **Create** - POST to create endpoint with file metadata
2. **Response** - Receive `upload_url` (presigned S3 URL)
3. **Upload** - PUT file directly to S3 using the presigned URL
4. **Confirm** - POST to `/upload-complete` or `/confirm` endpoint
5. **Poll** - GET status endpoint until processing completes

---

## Common Response Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 202 | Accepted (async operation started) |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Invalid/missing token |
| 402 | Payment Required - Insufficient credits |
| 403 | Forbidden - Not allowed |
| 404 | Not Found - Resource doesn't exist |
| 422 | Validation Error - Invalid field values |
| 501 | Not Implemented - Feature coming soon |

---

## Pagination

List endpoints support pagination:
- `page` - Page number (default: 1)
- `limit` - Items per page (default: 20, max: 100)

Response includes:
- `items` - Array of results
- `pagination` - { page, limit, total, total_pages, has_next, has_previous }
