"""LiveTalking service configuration"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


def _get_project_root() -> Path:
    """Get the root directory of this project (video-clone-backend)."""
    # This file is at: app/services/livetalking/livetalking_config.py
    # Project root is 4 levels up
    return Path(__file__).resolve().parent.parent.parent.parent


def _get_default_livetalking_root() -> str:
    """Get default LiveTalking root as sibling directory to this repo."""
    # Assumes structure:
    # /path/to/
    # ├── video-clone-backend/           (this repo)
    # └── Lip-Sync-Experiments/
    #     └── LiveTalking/               (LiveTalking repo)
    return str(_get_project_root().parent / "Lip-Sync-Experiments" / "LiveTalking")


def _resolve_path(path: str) -> str:
    """Resolve a path, handling relative paths from project root."""
    if not path:
        return path

    p = Path(path)

    # If absolute, return as-is
    if p.is_absolute():
        return str(p)

    # If relative, resolve from project root's parent (sibling directory)
    # e.g., "../livetalking" -> /path/to/livetalking
    resolved = (_get_project_root().parent / p).resolve()
    return str(resolved)


class LiveTalkingSettings(BaseSettings):
    """Settings for LiveTalking server connection and CLI execution"""

    # ===================
    # HTTP API Settings (for WebRTC streaming)
    # ===================

    # LiveTalking server URL (e.g., http://localhost:8010 or https://livetalking.example.com)
    LIVETALKING_URL: str = os.getenv("LIVETALKING_URL", "http://localhost:8010")

    # Optional API key for securing communication between backends
    LIVETALKING_API_KEY: str = os.getenv("LIVETALKING_API_KEY", "")

    # Timeout for HTTP requests to LiveTalking (seconds)
    LIVETALKING_TIMEOUT: int = int(os.getenv("LIVETALKING_TIMEOUT", "30"))

    # Timeout for downloading recordings (seconds)
    LIVETALKING_DOWNLOAD_TIMEOUT: int = int(os.getenv("LIVETALKING_DOWNLOAD_TIMEOUT", "120"))

    # ===================
    # CLI Settings (for local subprocess execution)
    # ===================

    # Root directory of LiveTalking installation
    # Supports relative paths (e.g., "../livetalking" for sibling directory)
    # Default: sibling "livetalking" directory next to this repo
    LIVETALKING_ROOT: str = _resolve_path(
        os.getenv("LIVETALKING_ROOT", _get_default_livetalking_root())
    )

    # Path to LiveTalking virtual environment
    # Default: {LIVETALKING_ROOT}/venv
    LIVETALKING_VENV: str = _resolve_path(
        os.getenv("LIVETALKING_VENV", "")
    ) or os.path.join(
        _resolve_path(os.getenv("LIVETALKING_ROOT", _get_default_livetalking_root())),
        "venv"
    )

    # Local path for storing avatar files
    # Default: {LIVETALKING_ROOT}/data/avatars
    AVATAR_LOCAL_PATH: str = _resolve_path(
        os.getenv("AVATAR_LOCAL_PATH", "")
    ) or os.path.join(
        _resolve_path(os.getenv("LIVETALKING_ROOT", _get_default_livetalking_root())),
        "data", "avatars"
    )

    # Local path for storing training video files
    # Default: {LIVETALKING_ROOT}/data/videos
    VIDEO_LOCAL_PATH: str = _resolve_path(
        os.getenv("VIDEO_LOCAL_PATH", "")
    ) or os.path.join(
        _resolve_path(os.getenv("LIVETALKING_ROOT", _get_default_livetalking_root())),
        "data", "videos"
    )

    # Timeout for avatar generation CLI (seconds) - typically 5-30 minutes
    LIVETALKING_AVATAR_TIMEOUT: int = int(os.getenv("LIVETALKING_AVATAR_TIMEOUT", "1800"))

    # Timeout for video generation CLI (seconds) - varies by text length
    LIVETALKING_VIDEO_TIMEOUT: int = int(os.getenv("LIVETALKING_VIDEO_TIMEOUT", "600"))

    # ===================
    # Execution Mode
    # ===================

    # Execution mode for avatar/video generation:
    # "cli"  = Always use subprocess execution (same server)
    # "api"  = Always use HTTP/RunPod API calls (remote server)
    # "auto" = Check GPU availability, use API if RTX 5090 available, else CLI
    LIVETALKING_MODE: str = os.getenv("LIVETALKING_MODE", "cli")

    class Config:
        env_prefix = ""
