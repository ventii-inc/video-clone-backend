# Model Progress API

## Overview

Both video and voice model endpoints now return progress tracking fields. Progress is calculated based on elapsed time since processing started.

## Endpoints

```
GET /api/v1/models/video/{id}
GET /api/v1/models/video
GET /api/v1/models/voice/{id}
GET /api/v1/models/voice
```

## New Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `progress_percent` | `number` | Progress from 0-100 |
| `processing_stage` | `string` | Current stage (see below) |
| `estimated_remaining_seconds` | `number \| null` | Estimated time left (detail endpoint only) |

## Example Responses

### Video Model (Processing)
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Avatar",
  "status": "processing",
  "progress_percent": 45,
  "processing_stage": "training",
  "estimated_remaining_seconds": 330,
  "thumbnail_url": "https://...",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Voice Model (Processing)
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Voice",
  "status": "processing",
  "progress_percent": 60,
  "processing_stage": "extracting",
  "estimated_remaining_seconds": 48,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Completed Model
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Avatar",
  "status": "completed",
  "progress_percent": 100,
  "processing_stage": "completed",
  "estimated_remaining_seconds": null
}
```

### Failed Model
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Avatar",
  "status": "failed",
  "progress_percent": 23,
  "processing_stage": "failed",
  "error_message": "Video quality too low for model training"
}
```

## Processing Stages

### Video Model
| Stage | Progress | Japanese | English |
|-------|----------|----------|---------|
| `uploading` | 0-10% | アップロード中 | Uploading |
| `preparing` | 10-20% | 準備中 | Preparing |
| `training` | 20-80% | モデルを学習中 | Training model |
| `finalizing` | 80-99% | 完了処理中 | Finalizing |
| `completed` | 100% | 完了 | Completed |

### Voice Model
| Stage | Progress | Japanese | English |
|-------|----------|----------|---------|
| `uploading` | 0-10% | アップロード中 | Uploading |
| `analyzing` | 10-30% | 音声を分析中 | Analyzing audio |
| `extracting` | 30-60% | 声の特徴を抽出中 | Extracting voice |
| `training` | 60-80% | モデルを学習中 | Training model |
| `finalizing` | 80-99% | 完了処理中 | Finalizing |
| `completed` | 100% | 完了 | Completed |

## Important Notes

1. **Progress caps at 80%** while `status` is `"processing"` - this prevents showing 100% before the model is actually ready

2. **100% only when completed** - progress jumps to 100% only when `status` becomes `"completed"`

3. **Estimated times**:
   - Video model: ~10 minutes total
   - Voice model: ~2 minutes total

4. **Polling recommendation**: Poll every 3-4 seconds while `status === "processing"`

## Frontend Usage Example

```typescript
// Polling loop
async function pollModelProgress(modelId: string) {
  while (true) {
    const model = await api.get(`/models/video/${modelId}`)

    // Update UI
    updateProgressBar(model.progress_percent)
    updateStageText(model.processing_stage)

    if (model.estimated_remaining_seconds) {
      updateRemainingTime(model.estimated_remaining_seconds)
    }

    // Stop polling when done
    if (model.status === "completed" || model.status === "failed") {
      break
    }

    await sleep(4000) // 4 seconds
  }
}
```

## Status Flow

```
pending → uploading → processing → completed
                          ↓
                       failed
```

Progress only actively increases during `processing` status.
