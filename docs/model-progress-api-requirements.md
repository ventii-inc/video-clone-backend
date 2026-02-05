# Model Creation Progress API Requirements

## Overview

We want to show real-time progress UI for video/voice model creation (similar to how we show progress for video generation). This requires additional fields from the backend.

## Current State

### Video Generation (Already Has Progress)
```
GET /api/v1/generate/{id}/status
```
```json
{
  "video": {
    "id": "uuid",
    "status": "processing",
    "progress_percent": 45,
    "processing_stage": "rendering",
    "queue_position": null,
    "estimated_remaining_seconds": 120,
    "error_message": null,
    ...
  }
}
```

### Models (Missing Progress Fields)
```
GET /api/v1/models/video/{id}
GET /api/v1/models/voice/{id}
```
```json
{
  "id": "uuid",
  "name": "My Model",
  "status": "processing",
  // No progress details
}
```

## Required Changes

### Option A: Add Fields to Existing Model Endpoints

Add these fields to `GET /api/v1/models/video/{id}` and `GET /api/v1/models/voice/{id}`:

| Field | Type | Description |
|-------|------|-------------|
| `progress_percent` | `number` | Progress from 0-100. Should be 100 when status is "completed" |
| `processing_stage` | `string \| null` | Human-readable stage name (see below) |
| `estimated_remaining_seconds` | `number \| null` | Estimated time remaining, null if unknown |
| `error_message` | `string \| null` | Error description when status is "failed" |

### Option B: Create New Status Endpoints

Create dedicated status endpoints (like video generation has):

```
GET /api/v1/models/video/{id}/status
GET /api/v1/models/voice/{id}/status
```

## Processing Stages

Suggested stage names for frontend display:

### Video Model
| Stage Key | Japanese | English |
|-----------|----------|---------|
| `uploading` | アップロード中 | Uploading |
| `analyzing` | 動画を分析中 | Analyzing video |
| `extracting` | 特徴を抽出中 | Extracting features |
| `training` | モデルを学習中 | Training model |
| `finalizing` | 完了処理中 | Finalizing |

### Voice Model
| Stage Key | Japanese | English |
|-----------|----------|---------|
| `uploading` | アップロード中 | Uploading |
| `analyzing` | 音声を分析中 | Analyzing audio |
| `extracting` | 声の特徴を抽出中 | Extracting voice features |
| `training` | モデルを学習中 | Training model |
| `finalizing` | 完了処理中 | Finalizing |

## Example Response

### Video Model with Progress
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Avatar",
  "status": "processing",
  "progress_percent": 45,
  "processing_stage": "training",
  "estimated_remaining_seconds": 180,
  "error_message": null,
  "thumbnail_url": "https://...",
  "duration_seconds": 30,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:32:00Z"
}
```

### Failed Model
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Avatar",
  "status": "failed",
  "progress_percent": 23,
  "processing_stage": "analyzing",
  "estimated_remaining_seconds": null,
  "error_message": "Video quality too low for model training",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:31:00Z"
}
```

## Frontend Usage

The frontend will poll the model endpoint every 3-4 seconds while `status` is `"processing"` to update the progress UI.

```typescript
// Polling loop (simplified)
while (model.status === "processing") {
  await sleep(4000)
  model = await apiClient.videoModels.get(modelId)
  updateProgressUI(model.progress_percent, model.processing_stage)
}
```

## Questions for Backend

1. **Which option do you prefer?** Adding fields to existing endpoints (Option A) or creating new status endpoints (Option B)?

2. **Are these processing stages accurate?** Or should we use different stage names based on actual backend processing steps?

3. **Can you provide estimated_remaining_seconds?** If this is difficult to calculate accurately, we can make it optional and just show progress percentage.
