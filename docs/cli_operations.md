# Wav2Lip CLI Operations

Two standalone operations for lip-sync video generation.

---

## Operation 1: Generate Avatar

Creates a preprocessed avatar from a source video.

### CLI Usage

```bash
python wav2lip/genavatar.py --avatar_id <id> --video_path <path> [options]
```

#### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--avatar_id` | Yes | `wav2lip_avatar1` | Unique identifier for the avatar |
| `--video_path` | Yes | - | Path to source video file |
| `--img_size` | No | `96` | Face crop size in pixels (use 256 for wav2lip256) |
| `--pads` | No | `0 10 0 0` | Padding (top, bottom, left, right) to include chin |
| `--nosmooth` | No | `false` | Disable smoothing face detections over temporal window |
| `--face_det_batch_size` | No | `16` | Batch size for face detection |
| `--s3_bucket` | No | - | S3 bucket for avatar upload |
| `--s3_prefix` | No | `avatars` | S3 key prefix |
| `--presigned_url` | No | `false` | Generate presigned URL after S3 upload |
| `--presigned_expires` | No | `3600` | Presigned URL expiration in seconds |

#### Example

```bash
# Basic usage (96x96 face crops)
python wav2lip/genavatar.py --avatar_id my-avatar --video_path ./data/source.mp4

# High-resolution avatar (256x256 for wav2lip256 model)
python wav2lip/genavatar.py --avatar_id my-avatar --video_path ./data/source.mp4 --img_size 256

# With custom padding to include more chin
python wav2lip/genavatar.py --avatar_id my-avatar --video_path ./data/source.mp4 --pads 10 20 10 10

# Upload to S3 with presigned URL
python wav2lip/genavatar.py --avatar_id my-avatar --video_path ./data/source.mp4 --s3_bucket my-bucket --presigned_url
```

### Programmatic Interface

```python
generate_avatar(video_path: str, avatar_id: str, img_size: int = 256) -> dict
```

#### Inputs

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `video_path` | str | Yes | - | Path to source video file |
| `avatar_id` | str | Yes | - | Unique identifier for the avatar |
| `img_size` | int | No | 256 | Face crop size in pixels |

#### Output

```json
{
  "success": true,
  "avatar_path": "./data/avatars/my-avatar",
  "frame_count": 150,
  "generation_time": 12.5
}
```

#### Example

```python
result = generate_avatar(
    video_path="./data/source_video.mp4",
    avatar_id="my-avatar",
    img_size=256
)
```

---

## Operation 2: Generate Video

Creates a lip-synced video from an avatar and audio file.

### CLI Usage

Use `benchmark_e2e.py` in cold start mode for standalone video generation:

```bash
python benchmark_e2e.py --mode cold --avatar_id <id> [options]
```

#### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--mode` | No | `cold` | Benchmark mode: `cold` (standalone) or `warm` (running server) |
| `--avatar_id` | No | `demo-avatar4` | Avatar ID to use (must exist or provide `--video_path`) |
| `--video_path` | No | `./data/demo-avatar-4.mp4` | Source video for avatar generation if avatar doesn't exist |
| `--text` | No | (Japanese sample) | Text to synthesize for lip-sync |
| `--ref_file` | No | `2d51c64b93bc4ecfaa391f0592201f6e` | Fish TTS reference voice ID |
| `--preset` | No | - | Preset config: `avatar4-30s` uses 30s demo video |
| `--output` | No | `output_cold.mp4` | Output video path |
| `--results_file` | No | `benchmark_e2e_results.json` | Results JSON file |

**Warm start mode** (requires running `app.py`):

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--server_url` | No | `http://localhost:8010` | Server URL for warm benchmark |
| `--sessionid` | No | auto-detect | Session ID from browser/server logs |

#### Example

```bash
# Cold start: Generate video from existing avatar
python benchmark_e2e.py --mode cold --avatar_id my-avatar --text "Hello world"

# Cold start: Generate avatar and video (if avatar doesn't exist)
python benchmark_e2e.py --mode cold --avatar_id new-avatar --video_path ./data/source.mp4

# Cold start with preset (30s avatar video)
python benchmark_e2e.py --mode cold --preset avatar4-30s

# Warm start: Test against running server (requires app.py running)
python benchmark_e2e.py --mode warm --server_url http://localhost:8010 --text "Hello world"
```

### Programmatic Interface

#### Class: VideoGenerator

```python
generator = VideoGenerator(model_path="./models/wav2lip.pth")
```

#### Method: generate_video

```python
generate_video(
    avatar_id: str,
    audio_path: str,
    output_path: str,
    fps: int = 25,
    batch_size: int = 8
) -> dict
```

#### Inputs

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `avatar_id` | str | Yes | - | Avatar ID (must exist) |
| `audio_path` | str | Yes | - | Path to audio file (WAV, 16kHz) |
| `output_path` | str | Yes | - | Output video path |
| `fps` | int | No | 25 | Output video frame rate |
| `batch_size` | int | No | 8 | Inference batch size |

#### Output

```json
{
  "device": "cuda",
  "model_load_time": 1.2,
  "avatar_load_time": 0.8,
  "audio_process_time": 0.3,
  "audio_duration": 5.2,
  "inference_time": 2.1,
  "total_frames": 130,
  "inference_fps": 61.9,
  "video_encode_time": 1.5,
  "total_time": 5.9,
  "output_path": "./output.mp4"
}
```

#### Example

```python
generator = VideoGenerator()

result = generator.generate_video(
    avatar_id="my-avatar",
    audio_path="./speech.wav",
    output_path="./output.mp4"
)
```

---

## Complete Workflow

```python
# Step 1: Create avatar (one-time)
generate_avatar(
    video_path="./data/person.mp4",
    avatar_id="person-avatar"
)

# Step 2: Generate videos (reusable generator)
generator = VideoGenerator()

result = generator.generate_video(
    avatar_id="person-avatar",
    audio_path="./audio1.wav",
    output_path="./video1.mp4"
)

result = generator.generate_video(
    avatar_id="person-avatar",
    audio_path="./audio2.wav",
    output_path="./video2.mp4"
)
```

---

## Audio Requirements

- Format: WAV
- Sample rate: 16kHz (will be resampled if different)
- Channels: Mono

---

## Avatar Structure

Generated avatars are stored in `./data/avatars/<avatar_id>/`:

```
data/avatars/my-avatar/
├── face_imgs/       # Cropped face frames (256x256 PNG)
├── full_imgs/       # Original video frames (PNG)
└── coords.pkl       # Bounding box coordinates
```
