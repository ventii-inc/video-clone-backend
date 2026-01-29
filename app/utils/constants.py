"""Application-wide constants."""

# API Configuration
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

# File size limits (in bytes)
MAX_VIDEO_SIZE_MB = 500
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024  # 500MB

MAX_AUDIO_SIZE_MB = 100
MAX_AUDIO_SIZE_BYTES = MAX_AUDIO_SIZE_MB * 1024 * 1024  # 100MB

MAX_AVATAR_SIZE_MB = 5
MAX_AVATAR_SIZE_BYTES = MAX_AVATAR_SIZE_MB * 1024 * 1024  # 5MB

# Processing timeouts (in seconds)
MODEL_PROCESSING_TIMEOUT = 1800  # 30 minutes
VIDEO_GENERATION_TIMEOUT = 600   # 10 minutes
UPLOAD_TIMEOUT = 300             # 5 minutes

# Presigned URL expiration (in seconds)
PRESIGNED_URL_EXPIRATION = 3600        # 1 hour
DOWNLOAD_URL_EXPIRATION = 3600         # 1 hour
STREAMING_URL_EXPIRATION = 21600       # 6 hours

# Supported file formats
ALLOWED_VIDEO_TYPES = [
    "video/mp4",
    "video/quicktime",  # .mov
    "video/x-msvideo",  # .avi
    "video/webm",
]

ALLOWED_AUDIO_TYPES = [
    "audio/mpeg",       # .mp3
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",        # .m4a
    "audio/m4a",
    "audio/x-m4a",
    "audio/aac",
    "audio/webm",
]

ALLOWED_IMAGE_TYPES = [
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
]

# Video settings
SUPPORTED_RESOLUTIONS = ["720p", "1080p"]
DEFAULT_RESOLUTION = "720p"

# Language settings
SUPPORTED_LANGUAGES = ["ja", "en"]
DEFAULT_LANGUAGE = "ja"

# Text limits
MAX_INPUT_TEXT_LENGTH = 5000
MIN_INPUT_TEXT_LENGTH = 1

# Pagination defaults
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Usage/Credits
MINUTES_PER_ADDITIONAL_PURCHASE = 20
COST_PER_ADDITIONAL_PURCHASE_JPY = 1000
STANDARD_PLAN_MONTHLY_MINUTES = 100

# Plan configuration
PLAN_CONFIG = {
    "free": {
        "minutes": 3,
        "video_trainings": 1,
        "voice_trainings": 1,
        "price_jpy": 0,
        "is_lifetime": True,  # Minutes and trainings never reset
    },
    "standard": {
        "minutes": 100,
        "video_trainings": 5,
        "voice_trainings": 5,
        "price_jpy": 2980,
        "is_lifetime": False,
    },
    "shot": {
        "minutes": 10,
        "video_trainings": 1,
        "voice_trainings": 1,
        "price_jpy": 980,
        "never_expires": True,  # One-time purchase, credits never expire
    },
}

# Auto-charge configuration (for Standard plan)
AUTO_CHARGE_MINUTES = 20
AUTO_CHARGE_PRICE_JPY = 1000
AUTO_CHARGE_BONUS_TRAININGS = 1  # Bonus training per auto-charge

# Model creation limits (legacy - now managed via PLAN_CONFIG)
MAX_VIDEO_MODELS_PER_USER = 5
MAX_VOICE_MODELS_PER_USER = 5
