# API Specification - AI Clone Video Generation Service

## Overview

This document defines the complete API specification for the AI Clone Video Generation backend service. The service allows users to create AI clones of themselves using video and voice samples, then generate new videos from text input.

**Base URL**: `/api/v1`
**Authentication**: Firebase JWT Bearer Token
**Content-Type**: `application/json` (unless specified otherwise)

---

## Table of Contents

1. [Database Models](#1-database-models)
2. [Authentication APIs](#2-authentication-apis)
3. [User Profile APIs](#3-user-profile-apis)
4. [Video Model APIs](#4-video-model-apis)
5. [Voice Model APIs](#5-voice-model-apis)
6. [Video Generation APIs](#6-video-generation-apis)
7. [Generated Videos APIs](#7-generated-videos-apis)
8. [Usage & Dashboard APIs](#8-usage--dashboard-apis)
9. [Billing APIs](#9-billing-apis)
10. [Settings APIs](#10-settings-apis)
11. [Common Response Formats](#11-common-response-formats)

---

## 1. Database Models

### 1.1 User
Already exists. Stores basic user information from Firebase auth.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| firebase_uid | String | Firebase user ID (unique) |
| email | String | User email |
| name | String | Display name |
| avatar_url | String? | Profile image URL |
| created_at | DateTime | Account creation timestamp |
| updated_at | DateTime | Last update timestamp |

### 1.2 UserProfile
Stores onboarding survey data and user preferences.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| usage_type | Enum | `personal` / `business` |
| company_size | String? | Company size (if business) |
| role | String | User's role/position |
| use_cases | JSON | Array of selected use cases |
| referral_source | String | How user found the service |
| onboarding_completed | Boolean | Whether onboarding is done |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### 1.3 VideoModel
Stores user's video clone models.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| name | String | Model display name |
| source_video_url | String | Original uploaded video S3 URL |
| source_video_key | String | S3 key for source video |
| model_data_url | String? | Processed model data URL (from AI) |
| thumbnail_url | String? | Auto-generated thumbnail |
| duration_seconds | Integer | Source video duration |
| file_size_bytes | Integer | Source file size |
| status | Enum | `pending` / `uploading` / `processing` / `completed` / `failed` |
| error_message | String? | Error details if failed |
| processing_started_at | DateTime? | When AI processing started |
| processing_completed_at | DateTime? | When AI processing finished |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### 1.4 VoiceModel
Stores user's voice clone models.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| name | String | Model display name |
| source_audio_url | String | Original uploaded audio S3 URL |
| source_audio_key | String | S3 key for source audio |
| model_data_url | String? | Processed model data URL (from AI) |
| source_type | Enum | `upload` / `recording` |
| duration_seconds | Integer | Source audio duration |
| file_size_bytes | Integer | Source file size |
| status | Enum | `pending` / `uploading` / `processing` / `completed` / `failed` |
| error_message | String? | Error details if failed |
| processing_started_at | DateTime? | When AI processing started |
| processing_completed_at | DateTime? | When AI processing finished |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### 1.5 GeneratedVideo
Stores videos generated from clone models.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| video_model_id | UUID | FK → video_models |
| voice_model_id | UUID | FK → voice_models |
| title | String? | User-defined title |
| input_text | Text | Text to be spoken |
| input_text_language | String | Language code (e.g., `ja`, `en`) |
| output_video_url | String? | Generated video S3 URL |
| output_video_key | String? | S3 key for output video |
| thumbnail_url | String? | Video thumbnail |
| resolution | Enum | `720p` / `1080p` |
| duration_seconds | Integer? | Generated video duration |
| file_size_bytes | Integer? | Output file size |
| credits_used | Integer | Minutes consumed |
| status | Enum | `queued` / `processing` / `completed` / `failed` |
| error_message | String? | Error details if failed |
| queue_position | Integer? | Position in processing queue |
| processing_started_at | DateTime? | When generation started |
| processing_completed_at | DateTime? | When generation finished |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### 1.6 Subscription
Stores Stripe subscription information.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users (unique) |
| stripe_customer_id | String | Stripe customer ID |
| stripe_subscription_id | String? | Stripe subscription ID |
| plan_type | Enum | `free` / `standard` |
| status | Enum | `active` / `canceled` / `past_due` / `trialing` |
| monthly_minutes_limit | Integer | Base minutes per month |
| current_period_start | DateTime | Billing period start |
| current_period_end | DateTime | Billing period end |
| canceled_at | DateTime? | When subscription was canceled |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

### 1.7 UsageRecord
Tracks monthly usage per user.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| period_year | Integer | Year (e.g., 2024) |
| period_month | Integer | Month (1-12) |
| base_minutes | Integer | Base plan minutes |
| used_minutes | Integer | Minutes used |
| additional_minutes_purchased | Integer | Extra minutes bought |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

**Unique constraint**: (user_id, period_year, period_month)

### 1.8 PaymentHistory
Stores payment transaction history.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| stripe_payment_intent_id | String | Stripe payment intent ID |
| payment_type | Enum | `subscription` / `additional_minutes` |
| amount_cents | Integer | Amount in cents |
| currency | String | Currency code (e.g., `jpy`) |
| minutes_purchased | Integer? | Minutes bought (if applicable) |
| status | Enum | `succeeded` / `failed` / `pending` |
| created_at | DateTime | Payment timestamp |

### 1.9 UserSettings
Stores user preferences and settings.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users (unique) |
| email_notifications | Boolean | Email notification preference |
| language | String | UI language (`ja` / `en`) |
| default_resolution | Enum | `720p` / `1080p` |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

---

## 2. Authentication APIs

### 2.1 Login / Register
Verify Firebase token and login or create user.

**Endpoint**: `POST /auth/login`

**Headers**:
```
Authorization: Bearer <firebase_id_token>
```

**Request Body**: None required (user info extracted from token)

**Response** `200 OK`:
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "John Doe",
    "avatar_url": "https://...",
    "created_at": "2024-01-15T10:00:00Z"
  },
  "is_new_user": false,
  "onboarding_completed": true
}
```

**Response** `201 Created` (new user):
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "John Doe",
    "avatar_url": null,
    "created_at": "2024-01-15T10:00:00Z"
  },
  "is_new_user": true,
  "onboarding_completed": false
}
```

### 2.2 Get Current User
Get authenticated user's information.

**Endpoint**: `GET /auth/me`

**Headers**:
```
Authorization: Bearer <firebase_id_token>
```

**Response** `200 OK`:
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "John Doe",
    "avatar_url": "https://...",
    "created_at": "2024-01-15T10:00:00Z"
  },
  "profile": {
    "usage_type": "personal",
    "role": "creator",
    "onboarding_completed": true
  },
  "subscription": {
    "plan_type": "standard",
    "status": "active",
    "current_period_end": "2024-02-15T10:00:00Z"
  }
}
```

---

## 3. User Profile APIs

### 3.1 Create/Update Profile (Onboarding)
Submit onboarding survey data.

**Endpoint**: `POST /users/profile`

**Request Body**:
```json
{
  "usage_type": "business",
  "company_size": "11-50",
  "role": "manager",
  "use_cases": ["marketing", "training", "support"],
  "referral_source": "search"
}
```

**Field Validations**:
- `usage_type`: Required. Enum: `personal`, `business`
- `company_size`: Required if `usage_type` is `business`. Values: `1-10`, `11-50`, `51-200`, `201-1000`, `1001+`
- `role`: Required. Values: `executive`, `manager`, `staff`, `freelancer`, `other`
- `use_cases`: Required. Array of: `marketing`, `training`, `support`, `social`, `presentation`, `other`
- `referral_source`: Required. Values: `search`, `social`, `referral`, `ads`, `media`, `other`

**Response** `200 OK`:
```json
{
  "profile": {
    "id": "uuid",
    "user_id": "uuid",
    "usage_type": "business",
    "company_size": "11-50",
    "role": "manager",
    "use_cases": ["marketing", "training", "support"],
    "referral_source": "search",
    "onboarding_completed": true,
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-15T10:00:00Z"
  }
}
```

### 3.2 Get Profile

**Endpoint**: `GET /users/profile`

**Response** `200 OK`:
```json
{
  "profile": {
    "id": "uuid",
    "user_id": "uuid",
    "usage_type": "business",
    "company_size": "11-50",
    "role": "manager",
    "use_cases": ["marketing", "training", "support"],
    "referral_source": "search",
    "onboarding_completed": true,
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-15T10:00:00Z"
  }
}
```

---

## 4. Video Model APIs

### 4.1 List Video Models

**Endpoint**: `GET /models/video`

**Query Parameters**:
- `status` (optional): Filter by status
- `page` (optional): Page number (default: 1)
- `limit` (optional): Items per page (default: 20, max: 100)

**Response** `200 OK`:
```json
{
  "models": [
    {
      "id": "uuid",
      "name": "My Video Clone",
      "thumbnail_url": "https://...",
      "duration_seconds": 120,
      "status": "completed",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 5,
    "total_pages": 1
  }
}
```

### 4.2 Get Video Model Details

**Endpoint**: `GET /models/video/{id}`

**Response** `200 OK`:
```json
{
  "model": {
    "id": "uuid",
    "name": "My Video Clone",
    "source_video_url": "https://...",
    "thumbnail_url": "https://...",
    "duration_seconds": 120,
    "file_size_bytes": 52428800,
    "status": "completed",
    "error_message": null,
    "processing_started_at": "2024-01-15T10:05:00Z",
    "processing_completed_at": "2024-01-15T10:15:00Z",
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-15T10:15:00Z"
  }
}
```

### 4.3 Create Video Model (Initiate Upload)

**Endpoint**: `POST /models/video`

**Request Body**:
```json
{
  "name": "My Video Clone",
  "file_name": "recording.mp4",
  "file_size_bytes": 52428800,
  "content_type": "video/mp4"
}
```

**Field Validations**:
- `name`: Required. 1-100 characters
- `file_name`: Required. Must have valid video extension (mp4, mov, avi, webm)
- `file_size_bytes`: Required. Max 500MB (524288000 bytes)
- `content_type`: Required. Must be valid video MIME type

**Response** `201 Created`:
```json
{
  "model": {
    "id": "uuid",
    "name": "My Video Clone",
    "status": "pending",
    "created_at": "2024-01-15T10:00:00Z"
  },
  "upload": {
    "presigned_url": "https://s3.amazonaws.com/bucket/...",
    "s3_key": "videos/user-id/model-id/source.mp4",
    "expires_in_seconds": 3600
  }
}
```

### 4.4 Complete Video Model Upload
Mark upload as complete and trigger AI processing.

**Endpoint**: `POST /models/video/{id}/upload-complete`

**Request Body**:
```json
{
  "duration_seconds": 120
}
```

**Response** `200 OK`:
```json
{
  "model": {
    "id": "uuid",
    "name": "My Video Clone",
    "status": "processing",
    "created_at": "2024-01-15T10:00:00Z"
  },
  "message": "Video model is now being processed"
}
```

### 4.5 Update Video Model

**Endpoint**: `PATCH /models/video/{id}`

**Request Body**:
```json
{
  "name": "Updated Name"
}
```

**Response** `200 OK`:
```json
{
  "model": {
    "id": "uuid",
    "name": "Updated Name",
    "status": "completed",
    "updated_at": "2024-01-15T11:00:00Z"
  }
}
```

### 4.6 Delete Video Model

**Endpoint**: `DELETE /models/video/{id}`

**Response** `200 OK`:
```json
{
  "message": "Video model deleted successfully"
}
```

**Response** `400 Bad Request` (if model is in use):
```json
{
  "error": {
    "code": "MODEL_IN_USE",
    "message": "Cannot delete model that has generated videos"
  }
}
```

---

## 5. Voice Model APIs

### 5.1 List Voice Models

**Endpoint**: `GET /models/voice`

**Query Parameters**:
- `status` (optional): Filter by status
- `source_type` (optional): Filter by `upload` or `recording`
- `page` (optional): Page number (default: 1)
- `limit` (optional): Items per page (default: 20, max: 100)

**Response** `200 OK`:
```json
{
  "models": [
    {
      "id": "uuid",
      "name": "My Voice Clone",
      "source_type": "upload",
      "duration_seconds": 60,
      "status": "completed",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 3,
    "total_pages": 1
  }
}
```

### 5.2 Get Voice Model Details

**Endpoint**: `GET /models/voice/{id}`

**Response** `200 OK`:
```json
{
  "model": {
    "id": "uuid",
    "name": "My Voice Clone",
    "source_audio_url": "https://...",
    "source_type": "upload",
    "duration_seconds": 60,
    "file_size_bytes": 5242880,
    "status": "completed",
    "error_message": null,
    "processing_started_at": "2024-01-15T10:02:00Z",
    "processing_completed_at": "2024-01-15T10:05:00Z",
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-15T10:05:00Z"
  }
}
```

### 5.3 Create Voice Model (Initiate Upload)

**Endpoint**: `POST /models/voice`

**Request Body**:
```json
{
  "name": "My Voice Clone",
  "file_name": "voice_sample.mp3",
  "file_size_bytes": 5242880,
  "content_type": "audio/mpeg",
  "source_type": "upload"
}
```

**Field Validations**:
- `name`: Required. 1-100 characters
- `file_name`: Required. Must have valid audio extension (mp3, wav, m4a, aac, webm)
- `file_size_bytes`: Required. Max 100MB (104857600 bytes)
- `content_type`: Required. Must be valid audio MIME type
- `source_type`: Required. Enum: `upload`, `recording`

**Response** `201 Created`:
```json
{
  "model": {
    "id": "uuid",
    "name": "My Voice Clone",
    "source_type": "upload",
    "status": "pending",
    "created_at": "2024-01-15T10:00:00Z"
  },
  "upload": {
    "presigned_url": "https://s3.amazonaws.com/bucket/...",
    "s3_key": "voices/user-id/model-id/source.mp3",
    "expires_in_seconds": 3600
  }
}
```

### 5.4 Complete Voice Model Upload

**Endpoint**: `POST /models/voice/{id}/upload-complete`

**Request Body**:
```json
{
  "duration_seconds": 60
}
```

**Response** `200 OK`:
```json
{
  "model": {
    "id": "uuid",
    "name": "My Voice Clone",
    "status": "processing",
    "created_at": "2024-01-15T10:00:00Z"
  },
  "message": "Voice model is now being processed"
}
```

### 5.5 Update Voice Model

**Endpoint**: `PATCH /models/voice/{id}`

**Request Body**:
```json
{
  "name": "Updated Voice Name"
}
```

**Response** `200 OK`:
```json
{
  "model": {
    "id": "uuid",
    "name": "Updated Voice Name",
    "status": "completed",
    "updated_at": "2024-01-15T11:00:00Z"
  }
}
```

### 5.6 Delete Voice Model

**Endpoint**: `DELETE /models/voice/{id}`

**Response** `200 OK`:
```json
{
  "message": "Voice model deleted successfully"
}
```

---

## 6. Video Generation APIs

### 6.1 Generate Video
Start a new video generation job.

**Endpoint**: `POST /generate`

**Request Body**:
```json
{
  "video_model_id": "uuid",
  "voice_model_id": "uuid",
  "title": "Product Introduction",
  "input_text": "Hello, welcome to our product demonstration...",
  "language": "ja",
  "resolution": "1080p"
}
```

**Field Validations**:
- `video_model_id`: Required. Must be a completed video model owned by user
- `voice_model_id`: Required. Must be a completed voice model owned by user
- `title`: Optional. Max 200 characters
- `input_text`: Required. 1-5000 characters
- `language`: Required. Enum: `ja`, `en`
- `resolution`: Optional. Enum: `720p`, `1080p`. Default: `720p`

**Response** `201 Created`:
```json
{
  "video": {
    "id": "uuid",
    "title": "Product Introduction",
    "status": "queued",
    "queue_position": 3,
    "estimated_duration_seconds": 45,
    "credits_used": 1,
    "created_at": "2024-01-15T10:00:00Z"
  },
  "usage": {
    "minutes_used": 51,
    "minutes_remaining": 49,
    "minutes_limit": 100
  }
}
```

**Response** `402 Payment Required` (insufficient credits):
```json
{
  "error": {
    "code": "INSUFFICIENT_CREDITS",
    "message": "Not enough minutes remaining",
    "details": {
      "required_minutes": 2,
      "available_minutes": 1
    }
  }
}
```

### 6.2 Get Generation Status

**Endpoint**: `GET /generate/{id}/status`

**Response** `200 OK` (processing):
```json
{
  "video": {
    "id": "uuid",
    "status": "processing",
    "queue_position": null,
    "progress_percent": 45,
    "estimated_remaining_seconds": 30,
    "processing_started_at": "2024-01-15T10:01:00Z"
  }
}
```

**Response** `200 OK` (completed):
```json
{
  "video": {
    "id": "uuid",
    "status": "completed",
    "output_video_url": "https://...",
    "thumbnail_url": "https://...",
    "duration_seconds": 45,
    "file_size_bytes": 15728640,
    "processing_completed_at": "2024-01-15T10:02:30Z"
  }
}
```

**Response** `200 OK` (failed):
```json
{
  "video": {
    "id": "uuid",
    "status": "failed",
    "error_message": "Face detection failed in video model",
    "processing_started_at": "2024-01-15T10:01:00Z"
  }
}
```

---

## 7. Generated Videos APIs

### 7.1 List Generated Videos

**Endpoint**: `GET /videos`

**Query Parameters**:
- `status` (optional): Filter by status
- `video_model_id` (optional): Filter by video model
- `voice_model_id` (optional): Filter by voice model
- `sort` (optional): `created_at`, `title`. Default: `created_at`
- `order` (optional): `asc`, `desc`. Default: `desc`
- `page` (optional): Page number (default: 1)
- `limit` (optional): Items per page (default: 20, max: 100)

**Response** `200 OK`:
```json
{
  "videos": [
    {
      "id": "uuid",
      "title": "Product Introduction",
      "thumbnail_url": "https://...",
      "duration_seconds": 45,
      "resolution": "1080p",
      "status": "completed",
      "video_model": {
        "id": "uuid",
        "name": "My Clone"
      },
      "voice_model": {
        "id": "uuid",
        "name": "My Voice"
      },
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 15,
    "total_pages": 1
  }
}
```

### 7.2 Get Video Details

**Endpoint**: `GET /videos/{id}`

**Response** `200 OK`:
```json
{
  "video": {
    "id": "uuid",
    "title": "Product Introduction",
    "input_text": "Hello, welcome to our product demonstration...",
    "input_text_language": "ja",
    "output_video_url": "https://...",
    "thumbnail_url": "https://...",
    "duration_seconds": 45,
    "file_size_bytes": 15728640,
    "resolution": "1080p",
    "credits_used": 1,
    "status": "completed",
    "video_model": {
      "id": "uuid",
      "name": "My Clone",
      "thumbnail_url": "https://..."
    },
    "voice_model": {
      "id": "uuid",
      "name": "My Voice"
    },
    "processing_started_at": "2024-01-15T10:01:00Z",
    "processing_completed_at": "2024-01-15T10:02:30Z",
    "created_at": "2024-01-15T10:00:00Z"
  }
}
```

### 7.3 Get Video Download URL
Get a fresh presigned URL for downloading.

**Endpoint**: `GET /videos/{id}/download`

**Response** `200 OK`:
```json
{
  "download_url": "https://s3.amazonaws.com/...",
  "file_name": "product-introduction.mp4",
  "expires_in_seconds": 3600
}
```

### 7.4 Delete Video

**Endpoint**: `DELETE /videos/{id}`

**Response** `200 OK`:
```json
{
  "message": "Video deleted successfully"
}
```

### 7.5 Regenerate Video
Create a new generation with the same settings.

**Endpoint**: `POST /videos/{id}/regenerate`

**Request Body** (optional overrides):
```json
{
  "input_text": "Updated text content...",
  "resolution": "1080p"
}
```

**Response** `201 Created`:
```json
{
  "video": {
    "id": "uuid-new",
    "title": "Product Introduction",
    "status": "queued",
    "queue_position": 1,
    "created_at": "2024-01-15T11:00:00Z"
  }
}
```

---

## 8. Usage & Dashboard APIs

### 8.1 Get Dashboard Summary

**Endpoint**: `GET /dashboard`

**Response** `200 OK`:
```json
{
  "usage": {
    "minutes_used": 51,
    "minutes_remaining": 49,
    "minutes_limit": 100,
    "additional_minutes": 0,
    "period_start": "2024-01-01",
    "period_end": "2024-01-31"
  },
  "models": {
    "video_models_count": 2,
    "voice_models_count": 3
  },
  "recent_videos": [
    {
      "id": "uuid",
      "title": "Product Introduction",
      "thumbnail_url": "https://...",
      "status": "completed",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "subscription": {
    "plan_type": "standard",
    "status": "active",
    "current_period_end": "2024-02-01T00:00:00Z"
  }
}
```

### 8.2 Get Current Usage

**Endpoint**: `GET /usage`

**Response** `200 OK`:
```json
{
  "usage": {
    "period_year": 2024,
    "period_month": 1,
    "base_minutes": 100,
    "used_minutes": 51,
    "additional_minutes_purchased": 0,
    "remaining_minutes": 49
  }
}
```

### 8.3 Get Usage History

**Endpoint**: `GET /usage/history`

**Query Parameters**:
- `months` (optional): Number of months to retrieve (default: 6, max: 12)

**Response** `200 OK`:
```json
{
  "history": [
    {
      "period_year": 2024,
      "period_month": 1,
      "base_minutes": 100,
      "used_minutes": 51,
      "additional_minutes_purchased": 20
    },
    {
      "period_year": 2023,
      "period_month": 12,
      "base_minutes": 100,
      "used_minutes": 87,
      "additional_minutes_purchased": 0
    }
  ]
}
```

---

## 9. Billing APIs

### 9.1 Create Checkout Session
Create Stripe checkout for subscription.

**Endpoint**: `POST /billing/checkout`

**Request Body**:
```json
{
  "plan_type": "standard",
  "success_url": "https://app.example.com/billing/success",
  "cancel_url": "https://app.example.com/billing/cancel"
}
```

**Response** `200 OK`:
```json
{
  "checkout_url": "https://checkout.stripe.com/...",
  "session_id": "cs_..."
}
```

### 9.2 Create Customer Portal Session
Create Stripe customer portal for managing subscription.

**Endpoint**: `POST /billing/portal`

**Request Body**:
```json
{
  "return_url": "https://app.example.com/settings/billing"
}
```

**Response** `200 OK`:
```json
{
  "portal_url": "https://billing.stripe.com/..."
}
```

### 9.3 Get Subscription Details

**Endpoint**: `GET /billing/subscription`

**Response** `200 OK`:
```json
{
  "subscription": {
    "plan_type": "standard",
    "status": "active",
    "monthly_minutes_limit": 100,
    "current_period_start": "2024-01-01T00:00:00Z",
    "current_period_end": "2024-02-01T00:00:00Z",
    "cancel_at_period_end": false
  },
  "payment_method": {
    "brand": "visa",
    "last4": "4242",
    "exp_month": 12,
    "exp_year": 2025
  }
}
```

### 9.4 Purchase Additional Minutes

**Endpoint**: `POST /billing/purchase-minutes`

**Request Body**:
```json
{
  "quantity": 2,
  "success_url": "https://app.example.com/generate?purchased=true",
  "cancel_url": "https://app.example.com/generate"
}
```

**Note**: Each quantity unit = 20 minutes = ¥1,000

**Response** `200 OK`:
```json
{
  "checkout_url": "https://checkout.stripe.com/...",
  "session_id": "cs_...",
  "minutes_to_add": 40,
  "amount_jpy": 2000
}
```

### 9.5 Get Payment History

**Endpoint**: `GET /billing/invoices`

**Query Parameters**:
- `page` (optional): Page number (default: 1)
- `limit` (optional): Items per page (default: 10, max: 50)

**Response** `200 OK`:
```json
{
  "invoices": [
    {
      "id": "uuid",
      "stripe_invoice_id": "in_...",
      "payment_type": "subscription",
      "amount_cents": 500000,
      "currency": "jpy",
      "status": "succeeded",
      "created_at": "2024-01-01T00:00:00Z"
    },
    {
      "id": "uuid",
      "stripe_invoice_id": "in_...",
      "payment_type": "additional_minutes",
      "amount_cents": 100000,
      "currency": "jpy",
      "minutes_purchased": 20,
      "status": "succeeded",
      "created_at": "2024-01-10T15:30:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 10,
    "total": 5,
    "total_pages": 1
  }
}
```

### 9.6 Stripe Webhook

**Endpoint**: `POST /webhooks/stripe`

**Headers**:
```
Stripe-Signature: t=...,v1=...,v0=...
```

**Handled Events**:
- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`

**Response** `200 OK`:
```json
{
  "received": true
}
```

---

## 10. Settings APIs

### 10.1 Get Settings

**Endpoint**: `GET /settings`

**Response** `200 OK`:
```json
{
  "settings": {
    "email_notifications": true,
    "language": "ja",
    "default_resolution": "720p"
  }
}
```

### 10.2 Update Settings

**Endpoint**: `PATCH /settings`

**Request Body**:
```json
{
  "email_notifications": false,
  "language": "en",
  "default_resolution": "1080p"
}
```

**Response** `200 OK`:
```json
{
  "settings": {
    "email_notifications": false,
    "language": "en",
    "default_resolution": "1080p",
    "updated_at": "2024-01-15T10:00:00Z"
  }
}
```

### 10.3 Update Avatar

**Endpoint**: `POST /settings/avatar`

**Request Body**:
```json
{
  "file_name": "avatar.jpg",
  "content_type": "image/jpeg"
}
```

**Response** `200 OK`:
```json
{
  "upload": {
    "presigned_url": "https://s3.amazonaws.com/...",
    "s3_key": "avatars/user-id/avatar.jpg",
    "expires_in_seconds": 3600
  }
}
```

### 10.4 Confirm Avatar Upload

**Endpoint**: `POST /settings/avatar/confirm`

**Response** `200 OK`:
```json
{
  "avatar_url": "https://cdn.example.com/avatars/user-id/avatar.jpg"
}
```

### 10.5 Request Data Export

**Endpoint**: `POST /account/export`

**Response** `202 Accepted`:
```json
{
  "message": "Data export request received. You will receive an email when ready.",
  "estimated_completion": "2024-01-15T12:00:00Z"
}
```

### 10.6 Delete Account

**Endpoint**: `DELETE /account`

**Request Body**:
```json
{
  "confirmation": "DELETE"
}
```

**Response** `200 OK`:
```json
{
  "message": "Account scheduled for deletion. You have 30 days to recover."
}
```

---

## 11. Common Response Formats

### Success Response
```json
{
  "data": { ... },
  "message": "Optional success message"
}
```

### Error Response
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable error message",
    "details": { ... }
  }
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `UNAUTHORIZED` | 401 | Invalid or missing authentication |
| `FORBIDDEN` | 403 | User doesn't have permission |
| `NOT_FOUND` | 404 | Resource not found |
| `VALIDATION_ERROR` | 422 | Request validation failed |
| `INSUFFICIENT_CREDITS` | 402 | Not enough minutes remaining |
| `MODEL_IN_USE` | 400 | Cannot delete model with dependencies |
| `MODEL_NOT_READY` | 400 | Model is still processing |
| `PROCESSING_ERROR` | 500 | AI processing failed |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |

### Pagination Format
```json
{
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 100,
    "total_pages": 5
  }
}
```

---

## Appendix: Enums Reference

### Model Status
- `pending` - Created, waiting for upload
- `uploading` - Upload in progress
- `processing` - AI is processing the model
- `completed` - Ready to use
- `failed` - Processing failed

### Video Generation Status
- `queued` - Waiting in queue
- `processing` - Generation in progress
- `completed` - Ready for download
- `failed` - Generation failed

### Subscription Status
- `active` - Active subscription
- `canceled` - Canceled but still active until period end
- `past_due` - Payment failed
- `trialing` - In trial period

### Plan Types
- `free` - Free tier (if applicable)
- `standard` - ¥5,000/month plan

### Resolutions
- `720p` - 1280x720
- `1080p` - 1920x1080

### Languages
- `ja` - Japanese
- `en` - English
