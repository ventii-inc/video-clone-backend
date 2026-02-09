# LiveTalking CLI Operations Integration

This document describes how the Video Clone Backend integrates with LiveTalking using CLI operations when both services are deployed on the same server.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Same Server                                 │
│                                                                          │
│  ┌─────────────────────────┐       ┌─────────────────────────────────┐  │
│  │  video-clone-backend/   │       │  Lip-Sync-Experiments/          │  │
│  │  (FastAPI API)          │       │  └── LiveTalking/               │  │
│  │                         │       │      ├── venv/                  │  │
│  │  Port: 8000             │ ────> │      ├── wav2lip/               │  │
│  │                         │subprocess    ├── benchmark_e2e.py       │  │
│  └─────────────────────────┘       │      └── data/avatars/          │  │
│           │                        └─────────────────────────────────┘  │
│           │                                        │                     │
│           v                                        v                     │
│  ┌─────────────────────────┐       ┌─────────────────────────────────┐  │
│  │  PostgreSQL             │       │  Local Avatar Storage           │  │
│  │  Database               │       │  .../LiveTalking/data/avatars/  │  │
│  └─────────────────────────┘       └─────────────────────────────────┘  │
│                                                    │                     │
└────────────────────────────────────────────────────│─────────────────────┘
                                                     │
                                                     v
                                        ┌───────────────────────┐
                                        │  AWS S3               │
                                        │  (Backup Storage)     │
                                        │  avatars/{user}/{id}  │
                                        │  generated-videos/... │
                                        └───────────────────────┘
```

---

## Operations

### Operation 1: Generate Avatar

Creates a preprocessed avatar from a source video.

#### Flow

```
1. User uploads training video via API
2. Video stored in S3: training-videos/{user_id}/{uuid}.mp4
3. AvatarJob created in database (status: pending)
4. Job processor picks up job:
   a. Downloads video from S3 to temp file
   b. Executes: python wav2lip/genavatar.py --avatar_id {uuid} --video_path {temp}
   c. Moves output from LiveTalking's data/avatars/ to AVATAR_LOCAL_PATH
   d. Creates TAR archive of avatar directory
   e. Uploads TAR to S3: avatars/{user_id}/{uuid}.tar
   f. Updates database: VideoModel.status = completed
```

#### CLI Command Executed

```bash
source ~/livetalking/venv/bin/activate && \
python wav2lip/genavatar.py \
    --avatar_id <video_model_uuid> \
    --video_path /tmp/downloaded_video.mp4 \
    --img_size 256 \
    --pads 0 10 0 0 \
    --face_det_batch_size 16
```

#### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `avatar_id` | UUID from VideoModel | Unique identifier for the avatar |
| `video_path` | Temp file path | Downloaded from S3 |
| `img_size` | 256 | Face crop size (256 for wav2lip256) |
| `pads` | 0 10 0 0 | Padding for face detection |
| `face_det_batch_size` | 16 | Batch size for face detection |

#### Output Structure

```
~/livetalking/data/avatars/{avatar_id}/
├── face_imgs/           # Cropped face frames (256x256 PNG)
│   ├── 00000000.png
│   ├── 00000001.png
│   └── ...
├── full_imgs/           # Original video frames (PNG)
│   ├── 00000000.png
│   ├── 00000001.png
│   └── ...
└── coords.pkl           # Face bounding box coordinates
```

#### S3 Backup

After local generation, avatar is archived and uploaded:

```
S3 Key: avatars/{user_id}/{avatar_id}.tar
Contents: TAR of the avatar directory
```

---

### Operation 2: Generate Video

Creates a lip-synced video from an avatar and input text.

#### Flow

```
1. User submits generation request via API with text
2. GeneratedVideo record created (status: queued)
3. Background task starts:
   a. Ensures avatar exists locally (downloads from S3 if needed)
   b. Executes: python benchmark_e2e.py --mode cold --avatar_id {uuid} --text "{text}"
   c. Uploads output video to S3
   d. Updates database: GeneratedVideo.status = completed
```

#### CLI Command Executed

```bash
source ~/livetalking/venv/bin/activate && \
python benchmark_e2e.py \
    --mode cold \
    --avatar_id <avatar_uuid> \
    --text "Your input text here" \
    --output /tmp/{generated_video_uuid}.mp4 \
    --ref_file <voice_model_ref>  # Optional TTS reference
```

#### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `mode` | cold | Standalone generation mode |
| `avatar_id` | UUID | Must match existing avatar |
| `text` | User input | Text to synthesize and lip-sync |
| `output` | Temp path | Output video location |
| `ref_file` | Optional | Fish TTS voice reference ID |

#### Output

```
/tmp/{generated_video_uuid}.mp4
→ Uploaded to S3: generated-videos/{user_id}/{uuid}.mp4
```

---

## Configuration

### Environment Variables

```bash
# Execution mode (required)
LIVETALKING_MODE=cli                    # "cli" or "api"

# LiveTalking paths - supports relative or absolute paths
# Relative paths are resolved from parent of video-clone-backend (sibling directories)
#
# Default assumes this directory structure:
#   /path/to/
#   ├── video-clone-backend/         (this repo)
#   └── Lip-Sync-Experiments/
#       └── LiveTalking/             (LiveTalking repo)

# Option 1: Relative paths (recommended for sibling repos)
LIVETALKING_ROOT=../Lip-Sync-Experiments/LiveTalking
LIVETALKING_VENV=../Lip-Sync-Experiments/LiveTalking/venv
AVATAR_LOCAL_PATH=../Lip-Sync-Experiments/LiveTalking/data/avatars

# Option 2: Absolute paths
# LIVETALKING_ROOT=/home/ubuntu/Lip-Sync-Experiments/LiveTalking
# LIVETALKING_VENV=/home/ubuntu/Lip-Sync-Experiments/LiveTalking/venv
# AVATAR_LOCAL_PATH=/home/ubuntu/Lip-Sync-Experiments/LiveTalking/data/avatars

# Timeouts (seconds)
LIVETALKING_AVATAR_TIMEOUT=1800         # 30 minutes for avatar gen
LIVETALKING_VIDEO_TIMEOUT=600           # 10 minutes for video gen

# S3 Configuration (existing)
S3_BUCKET_NAME=your-bucket
S3_AWS_REGION=ap-northeast-1
S3_AWS_ACCESS_KEY_ID=xxx
S3_AWS_SECRET_ACCESS_KEY=xxx
```

### Default Paths

If not specified, defaults assume sibling directory structure:

| Variable | Default |
|----------|---------|
| `LIVETALKING_ROOT` | `../Lip-Sync-Experiments/LiveTalking` |
| `LIVETALKING_VENV` | `{LIVETALKING_ROOT}/venv` |
| `AVATAR_LOCAL_PATH` | `{LIVETALKING_ROOT}/data/avatars` |

### Path Resolution

Paths are resolved as follows:

```
Relative path: ../Lip-Sync-Experiments/LiveTalking
                    ↓
Project root:  /path/to/video-clone-backend
                    ↓
Resolved:      /path/to/Lip-Sync-Experiments/LiveTalking
```

---

## Storage Strategy

### Dual Storage (Local + S3)

Avatars are stored in **both** locations for optimal performance and reliability:

| Location | Purpose | Format |
|----------|---------|--------|
| Local disk | Fast access during video generation | Directory with PNGs |
| S3 | Backup, disaster recovery | TAR archive |

### Why Both?

1. **Local Storage**
   - Zero latency for video generation
   - No download required for each video
   - Required by LiveTalking CLI

2. **S3 Backup**
   - Server can be rebuilt/replaced
   - Avatars persist across deployments
   - Recovery script restores from S3

---

## Recovery Script

If the server needs to be rebuilt, use the recovery script to restore avatars:

### Usage

```bash
# Set environment
export ENV=staging  # or production

# List all avatars in S3
python scripts/recover_avatars.py --list-only

# Dry run (see what would be downloaded)
python scripts/recover_avatars.py --dry-run

# Recover all avatars
python scripts/recover_avatars.py

# Recover specific user's avatars
python scripts/recover_avatars.py --user-id 42

# Recover single avatar
python scripts/recover_avatars.py --avatar-id abc123-def456

# Custom output directory
python scripts/recover_avatars.py --output-dir /data/avatars
```

### Example Output

```
Avatar Recovery Script
==================================================
Output directory: /home/ubuntu/livetalking/data/avatars
S3 bucket: video-clone-prod
==================================================

Scanning S3 for avatar TAR files...
Found 15 avatar(s) in S3

[1/15] abc123-def456-789
  Downloading: avatars/42/abc123-def456-789.tar...
  Extracting to: /home/ubuntu/livetalking/data/avatars/abc123-def456-789
  SUCCESS: abc123-def456-789 (150 frames)

[2/15] xyz789-uvw012-345
  SKIP: xyz789-uvw012-345 (already exists locally)

==================================================
Recovery Complete
==================================================
Downloaded: 10
Skipped:    5
Failed:     0
Total:      15
```

---

## API Integration

### Avatar Job Trigger (Internal)

The `avatar_job_service` automatically routes to CLI or API based on `LIVETALKING_MODE`:

```python
# app/services/avatar_job/avatar_job_service.py

async def trigger_job(self, job: AvatarJob, db: AsyncSession) -> bool:
    mode = self._get_execution_mode()

    if mode == "cli":
        return await self._trigger_job_cli(job, video_model, db)
    else:
        return await self._trigger_job_api(job, video_model, db)
```

### Video Generation (Internal)

The `ai_service` handles video generation with mode switching:

```python
# app/services/ai/ai_service.py

async def generate_video(self, video_id: UUID, db: AsyncSession) -> None:
    mode = self._get_mode()

    if mode == "cli":
        await self._generate_video_cli(video, db)
    else:
        await self._generate_video_mock(video, db)
```

---

## Health Check

Verify CLI integration is working:

```python
from app.services.livetalking import livetalking_cli_service

result = await livetalking_cli_service.health_check()
print(result)
# {
#     "cli_available": True,
#     "livetalking_root_exists": True,
#     "venv_exists": True,
#     "avatar_path_exists": True,
#     "python_version": "Python 3.10.12",
#     "error": None
# }
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "venv not found" | Wrong LIVETALKING_VENV path | Verify path: `ls -la ~/livetalking/venv/bin/python` |
| "Command timed out" | Long video or slow GPU | Increase `LIVETALKING_AVATAR_TIMEOUT` |
| "No face detected" | Bad source video | Use video with clear, single face |
| "Avatar not found" | Missing local + S3 | Run recovery script or re-upload |
| "Permission denied" | File permissions | Ensure FastAPI user can access LiveTalking paths |

### Debug Commands

```bash
# Test LiveTalking venv
source ~/livetalking/venv/bin/activate && python --version

# Test avatar generation manually
cd ~/livetalking
source venv/bin/activate
python wav2lip/genavatar.py --avatar_id test --video_path /path/to/video.mp4

# Check avatar exists
ls -la ~/livetalking/data/avatars/

# Check S3 avatars
aws s3 ls s3://your-bucket/avatars/ --recursive
```

---

## File Reference

| Component | Path |
|-----------|------|
| CLI Service | `app/services/livetalking/cli_service.py` |
| Config | `app/services/livetalking/livetalking_config.py` |
| Avatar Job Service | `app/services/avatar_job/avatar_job_service.py` |
| AI Service | `app/services/ai/ai_service.py` |
| Recovery Script | `scripts/recover_avatars.py` |
| Local Avatars | `{AVATAR_LOCAL_PATH}/{avatar_id}/` |
| S3 Avatars | `s3://{bucket}/avatars/{user_id}/{avatar_id}.tar` |
| S3 Videos | `s3://{bucket}/generated-videos/{user_id}/{uuid}.mp4` |

---

## Switching Modes

### CLI Mode (Same Server)

```bash
# .env.staging
LIVETALKING_MODE=cli
LIVETALKING_ROOT=/home/ubuntu/livetalking
```

### API Mode (Remote RunPod)

```bash
# .env.staging
LIVETALKING_MODE=api
RUNPOD_API_KEY=xxx
RUNPOD_ENDPOINT_ID=yyy
```

The system automatically uses the correct implementation based on the mode.
