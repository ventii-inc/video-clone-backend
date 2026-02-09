# Direct Video Upload API

This document describes the direct video upload endpoint for frontend integration.

## Overview

The direct upload endpoint allows frontends to upload video files directly to the backend server, which then handles S3 storage and avatar generation in parallel. This simplifies the upload flow compared to the presigned URL approach.

## Endpoint

```
POST /api/v1/models/video/upload
```

**Content-Type:** `multipart/form-data`

**Authentication:** Required (Firebase Bearer token)

## Request

### Form Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | Video file (max 500MB) |
| `name` | string | Yes | Display name for the model (1-100 chars) |
| `duration_seconds` | integer | Yes | Video duration in seconds (must be > 0) |

### Allowed Video Types

- `video/mp4`
- `video/quicktime`
- `video/x-msvideo`
- `video/webm`

## Response

**Status:** `201 Created`

```json
{
  "model": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "My Avatar",
    "thumbnail_url": null,
    "duration_seconds": 30,
    "status": "uploading",
    "created_at": "2024-01-21T08:00:00Z"
  },
  "job_id": "660e8400-e29b-41d4-a716-446655440001",
  "message": "Video uploaded, processing started"
}
```

## Error Responses

| Status | Error | Description |
|--------|-------|-------------|
| 400 | Invalid content type | File type not in allowed list |
| 400 | File too large | File exceeds 500MB limit |
| 401 | Unauthorized | Missing or invalid auth token |

## Frontend Implementation

### JavaScript/TypeScript (Fetch API)

```typescript
async function uploadVideo(
  file: File,
  name: string,
  durationSeconds: number,
  authToken: string
): Promise<DirectUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', name);
  formData.append('duration_seconds', durationSeconds.toString());

  const response = await fetch('/api/v1/models/video/upload', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${authToken}`,
    },
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Upload failed');
  }

  return response.json();
}
```

### React Example with Progress

```tsx
import { useState } from 'react';

function VideoUploader() {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const handleUpload = async (file: File, name: string, duration: number) => {
    setUploading(true);
    setProgress(0);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);
    formData.append('duration_seconds', duration.toString());

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        setProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.onload = () => {
      setUploading(false);
      if (xhr.status === 201) {
        const response = JSON.parse(xhr.responseText);
        console.log('Upload complete:', response);
        // Start polling for model status
        pollModelStatus(response.model.id);
      } else {
        console.error('Upload failed:', xhr.responseText);
      }
    };

    xhr.onerror = () => {
      setUploading(false);
      console.error('Upload error');
    };

    xhr.open('POST', '/api/v1/models/video/upload');
    xhr.setRequestHeader('Authorization', `Bearer ${authToken}`);
    xhr.send(formData);
  };

  return (
    <div>
      {uploading && <progress value={progress} max={100} />}
      {/* File input UI */}
    </div>
  );
}
```

### Axios Example

```typescript
import axios from 'axios';

async function uploadVideo(file: File, name: string, durationSeconds: number) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', name);
  formData.append('duration_seconds', durationSeconds.toString());

  const response = await axios.post('/api/v1/models/video/upload', formData, {
    headers: {
      'Authorization': `Bearer ${authToken}`,
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total!);
      console.log(`Upload progress: ${percent}%`);
    },
  });

  return response.data;
}
```

## Polling for Status

After upload, poll the model status to track avatar generation progress:

```typescript
async function pollModelStatus(modelId: string): Promise<void> {
  const poll = async () => {
    const response = await fetch(`/api/v1/models/video/${modelId}`, {
      headers: { 'Authorization': `Bearer ${authToken}` },
    });
    const model = await response.json();

    switch (model.status) {
      case 'uploading':
      case 'processing':
        // Still processing, poll again
        setTimeout(poll, 5000);
        break;
      case 'completed':
        console.log('Avatar ready!', model);
        break;
      case 'failed':
        console.error('Processing failed:', model.error_message);
        break;
    }
  };

  poll();
}
```

## Model Status Flow

```
uploading → processing → completed
                      ↘ failed
```

| Status | Description |
|--------|-------------|
| `uploading` | Video received, S3 upload and avatar job queued |
| `processing` | Avatar generation in progress |
| `completed` | Avatar ready for video generation |
| `failed` | Processing failed (check `error_message`) |

## Getting Video Duration

Use the HTML5 video element to get duration before upload:

```typescript
function getVideoDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    video.preload = 'metadata';

    video.onloadedmetadata = () => {
      URL.revokeObjectURL(video.src);
      resolve(Math.ceil(video.duration));
    };

    video.onerror = () => {
      URL.revokeObjectURL(video.src);
      reject(new Error('Failed to load video metadata'));
    };

    video.src = URL.createObjectURL(file);
  });
}

// Usage
const duration = await getVideoDuration(file);
await uploadVideo(file, 'My Avatar', duration, authToken);
```

## cURL Example

```bash
curl -X POST "http://localhost:8000/api/v1/models/video/upload" \
  -H "Authorization: Bearer <FIREBASE_TOKEN>" \
  -F "file=@/path/to/video.mp4" \
  -F "name=My Avatar" \
  -F "duration_seconds=30"
```

## Comparison with Presigned URL Flow

| Aspect | Direct Upload | Presigned URL |
|--------|--------------|---------------|
| Frontend complexity | Lower | Higher (2-step process) |
| Server load | Higher (receives file) | Lower (S3 handles upload) |
| Upload progress | Native browser progress | Requires separate tracking |
| Large files | May timeout | Better for very large files |
| Recommended for | Files < 100MB | Files > 100MB |

The presigned URL flow (`POST /models/video` + `POST /models/video/{id}/upload-complete`) remains available for large file uploads or when direct server upload is not preferred.
