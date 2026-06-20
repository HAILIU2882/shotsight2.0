"""Health check route: web, worker, FFmpeg, storage, and backend capability status."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from shotsight2.adapters.backend_probes import BackendRegistry
from shotsight2.config import Settings
from shotsight2.domain.tracking_backends import SystemProfile
from shotsight2.ports.artifacts import ArtifactStore
from shotsight2.ports.media import MediaTool
from shotsight2.services.readiness import ProductReadinessService
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


def get_product_readiness_service() -> ProductReadinessService:
    """Return the service that evaluates analysis-process readiness."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


@router.get("/health")
def health(
    app_settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[BackendRegistry, Depends(get_backend_registry)],
    system: Annotated[SystemProfile | None, Depends(get_system_profile)],
    media: Annotated[MediaTool | None, Depends(get_media_tool)],
    store: Annotated[ArtifactStore | None, Depends(get_artifact_store_optional)],
) -> dict[str, Any]:
    """Report web liveness while containing failures in optional diagnostics."""
    try:
        backend_status = build_backend_capability_status(
            registry,
            system=system,
            requested_backend=app_settings.tracking_backend,
        )
        tracking: dict[str, Any] = asdict(backend_status)
    except Exception:
        tracking = {
            "system": None if system is None else asdict(system),
            "backends": [],
            "selected_backend": None,
            "selection_error": "capability_probe_failed",
        }
    ffmpeg: dict[str, Any] = {
        "available": False,
        "ffmpeg_version": None,
        "ffprobe_version": None,
    }
    if media is not None:
        try:
            tool_status = media.status()
            ffmpeg = {
                "available": tool_status.available,
                "ffmpeg_version": tool_status.ffmpeg.version,
                "ffprobe_version": tool_status.ffprobe.version,
            }
        except Exception:
            ffmpeg["error"] = "probe_failed"
    storage: dict[str, Any] = {"total_bytes": None, "total_files": None}
    if store is not None:
        try:
            usage = store.storage_usage()
            storage = {"total_bytes": usage.total_bytes, "total_files": usage.total_files}
        except Exception:
            storage["error"] = "probe_failed"
    return {
        "status": "ok",
        "environment": app_settings.env,
        "sam3_enabled": app_settings.enable_sam3,
        "tracking": tracking,
        "ffmpeg": ffmpeg,
        "storage": storage,
        "analysis_readiness_url": "/ready",
    }


@router.get("/ready", response_model=None)
def readiness(
    service: Annotated[ProductReadinessService, Depends(get_product_readiness_service)],
) -> JSONResponse:
    """Report analysis readiness without coupling process liveness to worker state."""
    report = service.check()
    return JSONResponse(
        status_code=200 if report.ready else 503,
        content=jsonable_encoder(asdict(report)),
    )
