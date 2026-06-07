"""Smoke tests for the initial application scaffold."""

from fastapi.testclient import TestClient

from shotsight2.main import app


def test_health_endpoint() -> None:
    """The local service should expose its runtime status."""
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

