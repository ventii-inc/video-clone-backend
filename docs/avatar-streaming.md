# Avatar Streaming API Documentation

This document describes the Avatar Streaming API that integrates with the LiveTalking server for real-time avatar video streaming with lip-sync capabilities.

## Overview

The Avatar Streaming API provides endpoints to:
- Establish WebRTC connections with the LiveTalking server
- Send text for text-to-speech (TTS) processing
- Control recording sessions
- Download and store recordings to S3

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│                 │     │                      │     │                 │
│    Frontend     │◄───►│  video-clone-backend │◄───►│   LiveTalking   │
│    (WebRTC)     │     │      (FastAPI)       │     │    Server       │
│                 │     │                      │     │                 │
└────────┬────────┘     └──────────────────────┘     └─────────────────┘
         │                                                    ▲
         │              Direct WebRTC Connection              │
         └────────────────────────────────────────────────────┘
```

The backend acts as a proxy for control operations (TTS, recording) while the frontend establishes a direct WebRTC connection with LiveTalking for video streaming.

## Configuration

### Environment Variables

Add these to your `.env.local`, `.env.staging`, or `.env.production`:

```bash
# LiveTalking Server Configuration
LIVETALKING_URL=http://localhost:8010    # LiveTalking server URL
LIVETALKING_API_KEY=                      # Optional API key for authentication
LIVETALKING_TIMEOUT=30                    # HTTP request timeout (seconds)
LIVETALKING_DOWNLOAD_TIMEOUT=120          # Recording download timeout (seconds)
```

## API Endpoints

All endpoints are prefixed with `/api/v1/avatar`.

### 1. Get Session URLs

Get the URLs needed to establish a WebRTC connection with LiveTalking.

**Endpoint:** `GET /api/v1/avatar/session`

**Authentication:** Required (Firebase JWT)

**Response:**
```json
{
  "webrtc_url": "http://localhost:8010/offer",
  "human_url": "http://localhost:8010/human",
  "record_url": "http://localhost:8010/record"
}
```

**Example:**
```bash
curl -H "Authorization: Bearer <firebase_token>" \
  http://localhost:8000/api/v1/avatar/session
```

---

### 2. Send Text for TTS

Send text to the avatar for text-to-speech processing. The avatar will speak the provided text.

**Endpoint:** `POST /api/v1/avatar/send-text`

**Authentication:** Required (Firebase JWT)

**Request Body:**
```json
{
  "session_id": 123456789,
  "text": "Hello, welcome to our platform!",
  "interrupt": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | integer | Yes | WebRTC session ID from the `/offer` response |
| `text` | string | Yes | Text to speak (1-5000 characters) |
| `interrupt` | boolean | No | Interrupt current speech (default: true) |

**Response:**
```json
{
  "success": true,
  "message": "Text sent successfully"
}
```

**Example:**
```bash
curl -X POST \
  -H "Authorization: Bearer <firebase_token>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": 123456789, "text": "Hello world!", "interrupt": true}' \
  http://localhost:8000/api/v1/avatar/send-text
```

---

### 3. Control Recording

Start or stop recording the avatar session.

**Endpoint:** `POST /api/v1/avatar/recording`

**Authentication:** Required (Firebase JWT)

**Request Body:**
```json
{
  "session_id": 123456789,
  "action": "start"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | integer | Yes | WebRTC session ID |
| `action` | string | Yes | Either `"start"` or `"stop"` |

**Response:**
```json
{
  "success": true,
  "message": "Recording started"
}
```

**Examples:**
```bash
# Start recording
curl -X POST \
  -H "Authorization: Bearer <firebase_token>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": 123456789, "action": "start"}' \
  http://localhost:8000/api/v1/avatar/recording

# Stop recording
curl -X POST \
  -H "Authorization: Bearer <firebase_token>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": 123456789, "action": "stop"}' \
  http://localhost:8000/api/v1/avatar/recording
```

---

### 4. Download Recording

Download the latest recording and save it to S3. Returns a presigned URL for immediate access.

**Endpoint:** `POST /api/v1/avatar/recording/download`

**Authentication:** Required (Firebase JWT)

**Request Body:**
```json
{
  "session_id": 123456789,
  "title": "My Avatar Recording"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | integer | Yes | WebRTC session ID |
| `title` | string | No | Optional title for the recording (max 255 chars) |

**Response:**
```json
{
  "success": true,
  "message": "Recording downloaded and saved",
  "recording_id": "550e8400-e29b-41d4-a716-446655440000",
  "download_url": "https://s3.amazonaws.com/bucket/...",
  "s3_key": "avatar-recordings/user123/550e8400-e29b-41d4-a716-446655440000.mp4"
}
```

**Example:**
```bash
curl -X POST \
  -H "Authorization: Bearer <firebase_token>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": 123456789, "title": "Demo Recording"}' \
  http://localhost:8000/api/v1/avatar/recording/download
```

---

### 5. Health Check

Check if the LiveTalking server is available. This endpoint does not require authentication.

**Endpoint:** `GET /api/v1/avatar/health`

**Authentication:** Not required

**Response:**
```json
{
  "livetalking_available": true,
  "livetalking_url": "http://localhost:8010"
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/avatar/health
```

## Frontend Integration Guide

### Step 1: Get Session URLs

```javascript
const response = await fetch('/api/v1/avatar/session', {
  headers: {
    'Authorization': `Bearer ${firebaseToken}`
  }
});
const { webrtc_url, human_url, record_url } = await response.json();
```

### Step 2: Establish WebRTC Connection

```javascript
const pc = new RTCPeerConnection();

// Add tracks for receiving video/audio
pc.ontrack = (event) => {
  const video = document.getElementById('avatar-video');
  video.srcObject = event.streams[0];
};

// Create and send offer directly to LiveTalking
const offer = await pc.createOffer();
await pc.setLocalDescription(offer);

const response = await fetch(webrtc_url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    sdp: offer.sdp,
    type: offer.type
  })
});

const answer = await response.json();
await pc.setRemoteDescription(answer);

// Store session ID from the response for later API calls
const sessionId = answer.sessionid;
```

### Step 3: Send Text to Avatar

```javascript
async function sendText(text) {
  await fetch('/api/v1/avatar/send-text', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${firebaseToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      text: text,
      interrupt: true
    })
  });
}
```

### Step 4: Record Session

```javascript
async function startRecording() {
  await fetch('/api/v1/avatar/recording', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${firebaseToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      action: 'start'
    })
  });
}

async function stopRecording() {
  await fetch('/api/v1/avatar/recording', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${firebaseToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      action: 'stop'
    })
  });
}

async function downloadRecording() {
  const response = await fetch('/api/v1/avatar/recording/download', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${firebaseToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      title: 'My Recording'
    })
  });

  const { download_url } = await response.json();
  // Use download_url to play or download the video
}
```

## Error Handling

### HTTP Status Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 401 | Unauthorized - Invalid or missing Firebase token |
| 404 | Recording not found |
| 422 | Validation error - Check request body |
| 503 | LiveTalking server unavailable |

### Error Response Format

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Errors

**503 Service Unavailable**
```json
{
  "detail": "LiveTalking server unavailable: Connection refused"
}
```
*Solution: Ensure LiveTalking server is running at the configured URL.*

**404 Not Found (Recording)**
```json
{
  "detail": "No recording found. Make sure you stopped recording before downloading."
}
```
*Solution: Call the stop recording endpoint before attempting to download.*

**422 Validation Error**
```json
{
  "detail": [
    {
      "loc": ["body", "text"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    }
  ]
}
```
*Solution: Ensure all required fields are provided with valid values.*

## Running the Services

### Start video-clone-backend

```bash
cd /path/to/video-clone-backend
python main.py
# Server runs on http://localhost:8000
```

### Start LiveTalking

```bash
cd /path/to/LiveTalking
source venv/bin/activate
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
# Server runs on http://localhost:8010
```

## Monitoring

Use the health endpoint for monitoring:

```bash
# Simple health check
curl http://localhost:8000/api/v1/avatar/health

# With jq for formatted output
curl -s http://localhost:8000/api/v1/avatar/health | jq .
```

Example monitoring script:
```bash
#!/bin/bash
while true; do
  STATUS=$(curl -s http://localhost:8000/api/v1/avatar/health | jq -r '.livetalking_available')
  if [ "$STATUS" != "true" ]; then
    echo "ALERT: LiveTalking is unavailable!"
  fi
  sleep 30
done
```
