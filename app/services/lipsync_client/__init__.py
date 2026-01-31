"""LipSync remote service client for communicating with Lip-Sync-Experiment"""

from app.services.lipsync_client.lipsync_client import (
    LipSyncClient,
    LipSyncResponse,
    lipsync_client,
)

__all__ = ["LipSyncClient", "LipSyncResponse", "lipsync_client"]
