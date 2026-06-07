"""FastAPI entrypoint for the ShotSight 2.0 local web application."""

from fastapi import FastAPI

from shotsight2.config import settings


def create_app() -> FastAPI:
    """Create the application without initializing unimplemented vision services."""
    application = FastAPI(title="ShotSight 2.0", version="0.1.0")

    @application.get("/health")
    def health() -> dict[str, str | bool]:
        """Report whether the minimal local service is running."""
        return {
            "status": "ok",
            "environment": settings.env,
            "sam3_enabled": settings.enable_sam3,
        }

    return application


app = create_app()

