"""API routers module"""

from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from app.routers.video_models import router as video_models_router
from app.routers.voice_models import router as voice_models_router
from app.routers.generate import router as generate_router
from app.routers.videos import router as videos_router
from app.routers.dashboard import router as dashboard_router
from app.routers.billing import router as billing_router
from app.routers.settings import router as settings_router
from app.routers.avatar import router as avatar_router
from app.routers.avatar_backend import router as avatar_backend_router

__all__ = [
    "auth_router",
    "users_router",
    "video_models_router",
    "voice_models_router",
    "generate_router",
    "videos_router",
    "dashboard_router",
    "billing_router",
    "settings_router",
    "avatar_router",
    "avatar_backend_router",
]
