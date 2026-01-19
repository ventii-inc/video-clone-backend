# LiveTalking Backend Integration Guide

This document describes how the Video Clone Backend integrates with the LiveTalking avatar generation service.

---

## Overview

```
┌─────────────────────┐         ┌─────────────────────┐
│  Video Clone API    │         │  LiveTalking/RunPod │
│  (This Backend)     │         │  (Avatar Generator) │
└─────────────────────┘         └─────────────────────┘
         │                                │
         │  1. POST /runsync              │
         │  ─────────────────────────────>│
         │  (trigger avatar generation)   │
         │                                │
         │  2. Response with result       │
         │  <─────────────────────────────│
         │  (avatar S3 URL or error)      │
         │                                │
```

---

## What We Send (Request)

### Endpoint
```
POST https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync
```

### Headers
```
Authorization: Bearer {RUNPOD_API_KEY}
Content-Type: application/json
```

### Request Body
```json
{
  "input": {
    "video_url": "https://s3.amazonaws.com/bucket/training-videos/42/abc123.mp4?X-Amz-...",
    "avatar_id": "abc123-def456-...",
    "model": "wav2lip",
    "s3_bucket": "video-clone-avatars",
    "s3_prefix": "avatars/42"
  }
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes | Presigned S3 URL to download the source training video (valid for 2 hours) |
| `avatar_id` | string | Yes | Unique identifier for the avatar (UUID format, same as our `video_model_id`) |
| `model` | string | No | Model to use: `"wav2lip"` (default) or `"musetalk"` |
| `s3_bucket` | string | No | S3 bucket where avatar TAR should be uploaded |
| `s3_prefix` | string | No | S3 key prefix, e.g., `"avatars/42"` → final key: `avatars/42/{avatar_id}.tar` |

---

## What We Expect (Response)

### Success Response
```json
{
  "id": "runpod-job-id-xxx",
  "status": "COMPLETED",
  "output": {
    "status": "success",
    "avatar_id": "abc123-def456-...",
    "model": "wav2lip",
    "num_frames": 150,
    "upload_url": "https://s3.amazonaws.com/bucket/avatars/42/abc123.tar?X-Amz-..."
  }
}
```

### Error Response
```json
{
  "id": "runpod-job-id-xxx",
  "status": "COMPLETED",
  "output": {
    "status": "error",
    "error": "Video too short, minimum 3 seconds required"
  }
}
```

Or RunPod-level failure:
```json
{
  "id": "runpod-job-id-xxx",
  "status": "FAILED",
  "error": "Worker crashed unexpectedly"
}
```

### Response Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `output.status` | string | `"success"` or `"error"` |
| `output.avatar_id` | string | The avatar_id we sent (echo back) |
| `output.model` | string | Model used for generation |
| `output.num_frames` | int | Number of frames processed |
| `output.upload_url` | string | Presigned S3 URL where avatar TAR was uploaded (only on success) |
| `output.error` | string | Error message (only on failure) |

---

## Avatar TAR File Structure

We expect the generated avatar to be packaged as a `.tar` file with this structure:

### For Wav2Lip:
```
{avatar_id}.tar
├── coords.pkl           # Face bounding box coordinates
├── full_imgs/           # Original video frames
│   ├── 00000000.png
│   └── ...
└── face_imgs/           # Cropped & resized face regions (96x96)
    ├── 00000000.png
    └── ...
```

### For MuseTalk:
```
{avatar_id}.tar
├── coords.pkl           # Face bounding box coordinates
├── mask_coords.pkl      # Mask region coordinates
├── latents.pt           # Pre-computed VAE latents
├── avator_info.json     # Metadata
├── full_imgs/           # Original frames
│   └── ...
└── mask/                # Face segmentation masks
    └── ...
```

---

## S3 Permissions Required

The LiveTalking worker needs S3 permissions to:

1. **Download** source video from our bucket (we provide presigned URL, so no credentials needed)
2. **Upload** generated avatar TAR to the output bucket

If using our S3 bucket for output, we'll provide:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `S3_BUCKET` name

Or LiveTalking can upload to its own bucket and return the presigned download URL.

---

## Job Queue Behavior

Our backend manages a job queue with these characteristics:

| Setting | Value | Description |
|---------|-------|-------------|
| Max Concurrent | 3 (configurable) | Maximum simultaneous RunPod requests |
| Max Retries | 3 | Failed jobs retry up to 3 times |
| Video URL Expiry | 2 hours | Presigned download URL validity |

### Job States
```
pending → processing → completed
                   └─→ failed (after max retries)
```

---

## Error Handling

Please return meaningful error messages for these cases:

| Scenario | Expected Error Message |
|----------|----------------------|
| Video too short | `"Video too short, minimum X seconds required"` |
| Video too long | `"Video too long, maximum X seconds allowed"` |
| Invalid video format | `"Unsupported video format: {format}"` |
| No face detected | `"No face detected in video"` |
| Multiple faces | `"Multiple faces detected, single face required"` |
| S3 upload failed | `"Failed to upload avatar to S3: {reason}"` |
| Processing timeout | `"Processing timed out after X seconds"` |

---

## Testing

### Test Request
```bash
curl -X POST "https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync" \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "video_url": "https://example.com/test-video.mp4",
      "avatar_id": "test-avatar-001",
      "model": "wav2lip"
    }
  }'
```

### Expected Response
```json
{
  "id": "xxx",
  "status": "COMPLETED",
  "output": {
    "status": "success",
    "avatar_id": "test-avatar-001",
    "num_frames": 150,
    "upload_url": "https://..."
  }
}
```

---

## Questions?

Contact the Video Clone Backend team for:
- S3 credentials for avatar upload
- Test video URLs
- Integration support

---

## Appendix: Our Internal Endpoints

For reference, our backend exposes these internal endpoints (API key protected):

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/internal/avatar/jobs/status` | Get queue status (running, pending counts) |
| `GET /api/v1/internal/avatar/jobs/{job_id}` | Get specific job details |
| `POST /api/v1/internal/avatar/jobs/{job_id}/retry` | Retry a failed job |

These are for our internal monitoring, not for LiveTalking to call.
