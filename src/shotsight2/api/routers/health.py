"""Health check route: web, worker, FFmpeg, storage, and backend capability status."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from shotsight2.adapters.backend_probes import BackendRegistry
from shotsight2.config import Settings
from shotsight2.domain.tracking_backends import SystemProfile
from shotsight2.ports.artifacts import ArtifactStore
from shotsight2.ports.media import MediaTool
from shotsight2.services.tracking_backend_selection import build_backend_capability_status

router = APIRouter(tags=["health"])


def get_settings() -> Settings:
    """Return the active application settings."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_backend_registry() -> BackendRegistry:
    """Return the backend probe registry."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_system_profile() -> SystemProfile | None:
    """Return the current system hardware profile, or None."""
    return None


def get_media_tool() -> MediaTool | None:
    """Return the media tool adapter for FFmpeg health, or None when not configured."""
    return None


def get_artifact_store_optional() -> ArtifactStore | None:
    """Return the artifact store for storage health, or None when not configured."""
    return None


@router.get("/health")
def health(
    app_settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[BackendRegistry, Depends(get_backend_registry)],
    system: Annotated[SystemProfile | None, Depends(get_system_profile)],
    media: Annotated[MediaTool | None, Depends(get_media_tool)],
    store: Annotated[ArtifactStore | None, Depends(get_artifact_store_optional)],
) -> dict[str, Any]:
    """Report web health and lazily evaluated system capability status."""
    backend_status = build_backend_capability_status(
        registry,
        system=system,
        requested_backend=app_settings.tracking_backend,
    )
    ffmpeg: dict[str, Any] = {"available": False, "version": None}
    if media is not None:
        tool_status = media.status()
        ffmpeg = {
            "available": tool_status.available,
            "ffmpeg_version": tool_status.ffmpeg.version,
            "ffprobe_version": tool_status.ffprobe.version,
        }
    storage: dict[str, Any] = {"total_bytes": None}
    if store is not None:
        usage = store.storage_usage()
        storage = {"total_bytes": usage.total_bytes, "total_files": usage.total_files}
    return {
        "status": "ok",
        "environment": app_settings.env,
        "sam3_enabled": app_settings.enable_sam3,
        "tracking": asdict(backend_status),
        "ffmpeg": ffmpeg,
        "storage": storage,
    }
