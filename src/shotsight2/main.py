"""FastAPI entrypoint for the ShotSight 2.0 local web application."""

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI

from shotsight2.adapters.backend_probes import (
    BackendProbeConfig,
    BackendRegistry,
    create_default_registry,
)
from shotsight2.config import Settings, settings
from shotsight2.domain.tracking_backends import SystemProfile
from shotsight2.services.tracking_backend_selection import build_backend_capability_status


def create_app(
    application_settings: Settings = settings,
    *,
    backend_registry: BackendRegistry | None = None,
    system_profile: SystemProfile | None = None,
) -> FastAPI:
    """Create the app while deferring optional vision imports until health probes."""
    application = FastAPI(title="ShotSight 2.0", version="0.1.0")
    registry = backend_registry or create_default_registry(
        BackendProbeConfig(
            mlx_model_path=application_settings.mlx_model_path,
            sam3_model_path=application_settings.sam3_model_path,
            cpu_model_path=application_settings.cpu_tracking_model_path,
        )
    )

    @application.get("/health")
    def health() -> dict[str, Any]:
        """Report web health and lazily evaluated tracking capabilities."""
        backend_status = build_backend_capability_status(
            registry,
            system=system_profile,
            requested_backend=application_settings.tracking_backend,
        )
        return {
            "status": "ok",
            "environment": application_settings.env,
            "sam3_enabled": application_settings.enable_sam3,
            "tracking": asdict(backend_status),
        }

    return application


app = create_app()
