"""FastAPI entrypoint for the ShotSight 2.0 local web application."""

from fastapi import FastAPI

from shotsight2.adapters.backend_probes import (
    BackendProbeConfig,
    BackendRegistry,
    create_default_registry,
)
from shotsight2.api import register_routes
from shotsight2.api.routers.health import (
    get_backend_registry,
    get_settings,
    get_system_profile,
)
from shotsight2.config import Settings, settings
from shotsight2.domain.tracking_backends import SystemProfile


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

    register_routes(application)

    from shotsight2.presentation import register_presentation

    register_presentation(application)

    application.dependency_overrides[get_settings] = lambda: application_settings
    application.dependency_overrides[get_backend_registry] = lambda: registry
    if system_profile is not None:
        application.dependency_overrides[get_system_profile] = lambda: system_profile

    return application


app = create_app()
