"""Application API: router registration and error handler wiring."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from shotsight2.api.errors import register_error_handlers
from shotsight2.api.routers import (
    analysis,
    artifacts,
    attempts,
    health,
    players,
    preferences,
    segments,
    tracking,
    videos,
)


def register_routes(app: FastAPI) -> None:
    """Attach JSON routes under `/api` and safe legacy operational aliases."""
    register_error_handlers(app)
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(videos.router)
    api.include_router(analysis.router)
    api.include_router(segments.router)
    api.include_router(players.router)
    api.include_router(attempts.router)
    api.include_router(tracking.router)
    api.include_router(artifacts.router)
    api.include_router(preferences.router)
    app.include_router(api)

    # These legacy paths do not collide with HTML pages and remain useful to
    # local launch scripts, media elements, and existing health monitors.
    app.include_router(health.router, include_in_schema=False)
    app.include_router(artifacts.router, include_in_schema=False)
