"""Regression tests for production-style FastAPI runtime wiring."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from shotsight2.adapters.persistence import SQLiteVideoRepository
from shotsight2.config import Settings
from shotsight2.domain import Video, VideoStatus
from shotsight2.main import create_app


def test_create_app_wires_local_runtime_for_home_page(tmp_path: Path) -> None:
    """The real app factory should render `/` without test-only overrides."""
    application = create_app(
        Settings(
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'database' / 'shotsight2.db'}",
            tracking_backend=None,
        )
    )

    response = TestClient(application).get("/")

    assert response.status_code == 200
    assert "Video Library" in response.text
    assert "No videos uploaded yet." in response.text


def test_create_app_wires_local_runtime_for_health_page(tmp_path: Path) -> None:
    """The local runtime should also satisfy optional health dependencies."""
    application = create_app(
        Settings(
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'database' / 'shotsight2.db'}",
            tracking_backend=None,
        )
    )

    response = TestClient(application).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_combined_app_prefers_html_video_detail_page(tmp_path: Path) -> None:
    """The local app should not show raw API JSON after an upload redirect."""
    application = create_app(
        Settings(
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'database' / 'shotsight2.db'}",
            tracking_backend=None,
        )
    )
    SQLiteVideoRepository(application.state.runtime.database).create(
        Video(
            id="video-routing",
            filename="routing.mov",
            original_artifact_id="artifact-routing",
            size_bytes=1024,
            duration_seconds=10.0,
            width=640,
            height=360,
            fps=30.0,
            codec="h264",
            container="mov",
            created_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
            status=VideoStatus.READY,
        )
    )

    response = TestClient(application).get("/videos/video-routing")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Video Detail" in response.text
    assert "routing.mov" in response.text

    api_response = TestClient(application).get("/api/videos/video-routing")
    assert api_response.status_code == 200
    assert api_response.headers["content-type"].startswith("application/json")
    assert api_response.json()["card"]["video_id"] == "video-routing"


def test_combined_app_has_no_html_json_method_path_collisions(tmp_path: Path) -> None:
    """UI and JSON resource routes must have distinct canonical paths."""
    application = create_app(
        Settings(
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'database' / 'shotsight2.db'}",
            tracking_backend=None,
        )
    )
    registrations = [
        (route.path, method)
        for route in application.routes
        if isinstance(route, APIRoute)
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST", "PATCH", "DELETE", "PUT"}
    ]

    assert registrations.count(("/videos/{video_id}", "GET")) == 1
    assert registrations.count(("/api/videos/{video_id}", "GET")) == 1
    assert registrations.count(("/videos/{video_id}/attempts", "GET")) == 1
    assert registrations.count(("/api/videos/{video_id}/attempts", "GET")) == 1
