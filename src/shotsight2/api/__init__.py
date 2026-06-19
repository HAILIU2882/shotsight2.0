"""Application API: router registration and error handler wiring."""

from __future__ import annotations

from fastapi import FastAPI

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
    """Attach all API routers and error handlers to a FastAPI application."""
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(videos.router)
    app.include_router(analysis.router)
    app.include_router(segments.router)
    app.include_router(players.router)
    app.include_router(attempts.router)
    app.include_router(tracking.router)
    app.include_router(artifacts.router)
    app.include_router(preferences.router)
