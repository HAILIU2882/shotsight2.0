"""Regression tests for production-style FastAPI runtime wiring."""

from pathlib import Path

from fastapi.testclient import TestClient

from shotsight2.config import Settings
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
