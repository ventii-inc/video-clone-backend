# Direct Voice Upload API

This document describes the direct voice upload endpoint for frontend integration.

## Overview

The direct upload endpoint allows frontends to upload audio files directly to the backend server, which then handles S3 storage and Fish Audio voice cloning in parallel.

## Endpoint

```
POST /api/v1/models/voice/upload
```

**Content-Type:** `multipart/form-data`

**Authentication:** Required (Firebase Bearer token)

## Request

### Form Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `file` | File | Yes | - | Audio file (max 100MB) |
| `name` | string | Yes | - | Display name for the model (1-100 chars) |
| `duration_seconds` | integer | Yes | - | Audio duration in seconds (must be > 0) |
| `source_type` | string | No | "upload" | Source type: "upload" or "recording" |

### Allowed Audio Types

- `audio/mpeg`, `audio/mp3`
- `audio/wav`, `audio/x-wav`
- `audio/mp4`, `audio/m4a`, `audio/x-m4a`
- `audio/aac`
- `audio/webm`

## Response

**Status:** `201 Created`

```json
{
  "model": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "My Voice",
    "source_type": "upload",
    "duration_seconds": 45,
    "status": "uploading",
    "created_at": "2024-01-21T08:00:00Z"
  },
  "message": "Audio uploaded, voice cloning started"
}
```

## Error Responses

| Status | Error | Description |
|--------|-------|-------------|
| 400 | Invalid content type | File type not in allowed list |
| 400 | File too large | File exceeds 100MB limit |
| 400 | Invalid source_type | Must be "upload" or "recording" |
| 401 | Unauthorized | Missing or invalid auth token |

## Frontend Implementation

### JavaScript/TypeScript (Fetch API)

```typescript
interface DirectVoiceUploadResponse {
  model: {
    id: string;
    name: string;
    source_type: 'upload' | 'recording';
    duration_seconds: number;
    status: string;
    created_at: string;
  };
  message: string;
}

async function uploadVoice(
  file: File,
  name: string,
  durationSeconds: number,
  authToken: string,
  sourceType: 'upload' | 'recording' = 'upload'
): Promise<DirectVoiceUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', name);
  formData.append('duration_seconds', durationSeconds.toString());
  formData.append('source_type', sourceType);

  const response = await fetch('/api/v1/models/voice/upload', {
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

### React Example with Recording Support

```tsx
import { useState, useRef } from 'react';

function VoiceUploader() {
  const [uploading, setUploading] = useState(false);
  const [recording, setRecording] = useState(false);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  // Upload from file input
  const handleFileUpload = async (file: File) => {
    const duration = await getAudioDuration(file);
    await uploadVoice(file, 'My Voice', duration, authToken, 'upload');
  };

  // Start recording
  const startRecording = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder.current = new MediaRecorder(stream);
    chunks.current = [];

    mediaRecorder.current.ondataavailable = (e) => {
      chunks.current.push(e.data);
    };

    mediaRecorder.current.onstop = async () => {
      const blob = new Blob(chunks.current, { type: 'audio/webm' });
      const file = new File([blob], 'recording.webm', { type: 'audio/webm' });
      const duration = await getAudioDuration(file);
      await uploadVoice(file, 'My Recording', duration, authToken, 'recording');
    };

    mediaRecorder.current.start();
    setRecording(true);
  };

  // Stop recording
  const stopRecording = () => {
    mediaRecorder.current?.stop();
    setRecording(false);
  };

  return (
    <div>
      <input type="file" accept="audio/*" onChange={(e) => {
        const file = e.target.files?.[0];
        if (file) handleFileUpload(file);
      }} />

      <button onClick={recording ? stopRecording : startRecording}>
        {recording ? 'Stop Recording' : 'Start Recording'}
      </button>
    </div>
  );
}
```

### Axios Example with Progress

```typescript
import axios from 'axios';

async function uploadVoice(
  file: File,
  name: string,
  durationSeconds: number,
  sourceType: 'upload' | 'recording' = 'upload',
  onProgress?: (percent: number) => void
) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', name);
  formData.append('duration_seconds', durationSeconds.toString());
  formData.append('source_type', sourceType);

  const response = await axios.post('/api/v1/models/voice/upload', formData, {
    headers: {
      'Authorization': `Bearer ${authToken}`,
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total!);
      onProgress?.(percent);
    },
  });

  return response.data;
}
```

## Polling for Status

After upload, poll the model status to track voice cloning progress:

```typescript
async function pollVoiceModelStatus(modelId: string): Promise<void> {
  const poll = async () => {
    const response = await fetch(`/api/v1/models/voice/${modelId}`, {
      headers: { 'Authorization': `Bearer ${authToken}` },
    });
    const model = await response.json();

    switch (model.status) {
      case 'uploading':
      case 'processing':
        // Still processing, poll again
        setTimeout(poll, 3000);
        break;
      case 'completed':
        console.log('Voice model ready!', model);
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
| `uploading` | Audio received, S3 upload and voice cloning queued |
| `processing` | Voice cloning in progress (Fish Audio) |
| `completed` | Voice model ready for video generation |
| `failed` | Processing failed (check `error_message`) |

## Getting Audio Duration

Use the HTML5 audio element to get duration before upload:

```typescript
function getAudioDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const audio = document.createElement('audio');
    audio.preload = 'metadata';

    audio.onloadedmetadata = () => {
      URL.revokeObjectURL(audio.src);
      resolve(Math.ceil(audio.duration));
    };

    audio.onerror = () => {
      URL.revokeObjectURL(audio.src);
      reject(new Error('Failed to load audio metadata'));
    };

    audio.src = URL.createObjectURL(file);
  });
}

// Usage
const duration = await getAudioDuration(file);
await uploadVoice(file, 'My Voice', duration, authToken);
```

## cURL Example

```bash
# Upload from file
curl -X POST "http://localhost:8000/api/v1/models/voice/upload" \
  -H "Authorization: Bearer <FIREBASE_TOKEN>" \
  -F "file=@/path/to/audio.mp3" \
  -F "name=My Voice" \
  -F "duration_seconds=45" \
  -F "source_type=upload"

# For recording
curl -X POST "http://localhost:8000/api/v1/models/voice/upload" \
  -H "Authorization: Bearer <FIREBASE_TOKEN>" \
  -F "file=@/path/to/recording.webm" \
  -F "name=My Recording" \
  -F "duration_seconds=30" \
  -F "source_type=recording"
```

## Notes

### Audio Trimming
- Audio longer than 60 seconds is automatically trimmed to 60 seconds for voice cloning
- The `duration_seconds` in the response reflects the original duration
- Fish Audio processes the trimmed version

### Parallel Processing
When you upload audio:
1. S3 upload and voice cloning start **in parallel**
2. S3 upload stores the original audio for playback
3. Voice cloning (Fish Audio) creates the voice model for TTS

### Comparison with Presigned URL Flow

| Aspect | Direct Upload | Presigned URL |
|--------|--------------|---------------|
| Frontend complexity | Lower | Higher (2-step process) |
| Server load | Higher (receives file) | Lower (S3 handles upload) |
| Upload progress | Native browser progress | Requires separate tracking |
| Recommended for | Most use cases | Very large files (>50MB) |

The presigned URL flow (`POST /models/voice` + `POST /models/voice/{id}/upload-complete`) remains available for large file uploads.
