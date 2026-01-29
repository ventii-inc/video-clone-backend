"""Audio processing service module"""

from app.services.audio.audio_service import (
    AudioService,
    audio_service,
    get_audio_duration,
    trim_audio,
    MAX_TRAINING_AUDIO_DURATION,
)

__all__ = [
    "AudioService",
    "audio_service",
    "get_audio_duration",
    "trim_audio",
    "MAX_TRAINING_AUDIO_DURATION",
]
