"""Liveness and worker-aware product readiness tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shotsight2.adapters.backend_probes import BackendRegistry
from shotsight2.api.routers.health import (
    get_artifact_store_optional,
    get_media_tool,
    get_product_readiness_service,
)
from shotsight2.config import Settings
from shotsight2.domain.jobs import QueueRuntimeSnapshot
from shotsight2.domain.tracking_backends import (
    BackendCapabilities,
    BackendDevice,
    BackendHealth,
    BackendHealthState,
    DeviceType,
    SystemProfile,
    TrackingBackendName,
)
from shotsight2.main import create_app
from shotsight2.ports.jobs import ReadinessQueryError
from shotsight2.services.readiness import ProductReadinessService

NOW = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


def test_health_endpoint() -> None:
    """The local service should expose selected backend capability status."""
    registry = BackendRegistry()
    registry.register(TrackingBackendName.MLX_SAM3, _unavailable_mlx)
    registry.register(TrackingBackendName.OPENCV_CPU, _ready_cpu)
    application = create_app(
        Settings(tracking_backend=None),
        backend_registry=registry,
        system_profile=SystemProfile("Darwin", "arm64", "3.12.0", 64 * 1024**3),
    )

    response = TestClient(application).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tracking"]["selected_backend"] == "opencv-cpu"
    assert payload["tracking"]["selection_error"] is None
    assert payload["analysis_readiness_url"] == "/ready"
    assert payload["tracking"]["system"]["operating_system"] == "Darwin"
    assert [backend["state"] for backend in payload["tracking"]["backends"]] == [
        "unavailable",
        "ready",
    ]
    assert "model missing" in payload["tracking"]["backends"][0]["reason"]


def test_health_endpoint_reports_invalid_backend_override() -> None:
    """An invalid configured override should be visible without failing web health."""
    registry = BackendRegistry()
    registry.register(TrackingBackendName.OPENCV_CPU, _ready_cpu)
    application = create_app(
        Settings(tracking_backend="unknown"),
        backend_registry=registry,
        system_profile=SystemProfile("Darwin", "arm64", "3.12.0", None),
    )

    response = TestClient(application).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tracking"]["selected_backend"] is None
    assert "Unknown tracking backend" in payload["tracking"]["selection_error"]


def test_health_contains_optional_diagnostic_failures() -> None:
    """Optional probes cannot turn the web liveness endpoint into a restart signal."""
    registry = BackendRegistry()
    registry.register(TrackingBackendName.OPENCV_CPU, _raise_probe_failure)
    application = create_app(
        Settings(tracking_backend=None),
        backend_registry=registry,
        system_profile=SystemProfile("Darwin", "arm64", "3.12.0", None),
    )
    application.dependency_overrides[get_media_tool] = lambda: _FailingMediaTool()
    application.dependency_overrides[get_artifact_store_optional] = lambda: _FailingArtifactStore()

    response = TestClient(application).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["tracking"]["selection_error"] == "capability_probe_failed"
    assert payload["ffmpeg"]["error"] == "probe_failed"
    assert payload["storage"]["error"] == "probe_failed"


def test_readiness_reports_missing_worker_without_breaking_liveness(tmp_path: Path) -> None:
    """A web-only process stays live while analysis readiness is unavailable."""
    application = _readiness_app(tmp_path)

    health_response = TestClient(application).get("/health")
    readiness_response = TestClient(application).get("/ready")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert readiness_response.status_code == 503
    assert readiness_response.json() == {
        "status": "not_ready",
        "checked_at": "2026-06-20T10:00:00+00:00",
        "database": {"status": "available"},
        "queue": {"status": "available", "queued_jobs": 0, "running_jobs": 0},
        "worker": {
            "status": "missing",
            "worker_id": None,
            "heartbeat_at": None,
            "age_seconds": None,
            "stale_after_seconds": 30.0,
        },
    }


def test_readiness_reports_fresh_worker_and_queue_counts(tmp_path: Path) -> None:
    """A recent non-stopped heartbeat makes the analysis process ready."""
    application = _readiness_app(tmp_path)
    application.state.runtime.worker_queue.heartbeat(
        "analysis-worker",
        heartbeat_at=NOW - timedelta(seconds=5),
    )

    response = TestClient(application).get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["worker"] == {
        "status": "ready",
        "worker_id": "analysis-worker",
        "heartbeat_at": "2026-06-20T09:59:55+00:00",
        "age_seconds": 5.0,
        "stale_after_seconds": 30.0,
    }
    assert payload["queue"] == {"status": "available", "queued_jobs": 0, "running_jobs": 0}


def test_readiness_reports_stale_worker(tmp_path: Path) -> None:
    """A heartbeat exactly at the freshness boundary is stale."""
    application = _readiness_app(tmp_path)
    application.state.runtime.worker_queue.heartbeat(
        "analysis-worker",
        heartbeat_at=NOW - timedelta(seconds=30),
    )

    response = TestClient(application).get("/ready")

    assert response.status_code == 503
    assert response.json()["worker"] == {
        "status": "stale",
        "worker_id": "analysis-worker",
        "heartbeat_at": "2026-06-20T09:59:30+00:00",
        "age_seconds": 30.0,
        "stale_after_seconds": 30.0,
    }


def test_readiness_reports_gracefully_stopped_worker(tmp_path: Path) -> None:
    """A recent heartbeat cannot hide a persisted graceful worker stop."""
    application = _readiness_app(tmp_path)
    application.state.runtime.worker_queue.heartbeat("analysis-worker", heartbeat_at=NOW)
    application.state.runtime.worker_queue.stop_worker("analysis-worker", stopped_at=NOW)

    response = TestClient(application).get("/ready")

    assert response.status_code == 503
    assert response.json()["worker"]["status"] == "stopped"
    assert response.json()["worker"]["worker_id"] == "analysis-worker"


def test_readiness_reports_database_failure_without_raising(tmp_path: Path) -> None:
    """Storage failures degrade readiness rather than crashing the endpoint."""
    application = _readiness_app(tmp_path)
    application.dependency_overrides[get_product_readiness_service] = lambda: ProductReadinessService(
        _FailingReadinessQuery(database_available=False),
        clock=lambda: NOW,
    )

    response = TestClient(application).get("/ready")

    assert response.status_code == 503
    assert response.json()["database"] == {"status": "unavailable"}
    assert response.json()["queue"] == {
        "status": "unavailable",
        "queued_jobs": None,
        "running_jobs": None,
    }
    assert response.json()["worker"]["status"] == "unknown"


def test_readiness_distinguishes_queue_failure_from_database_failure(tmp_path: Path) -> None:
    """A reachable database with unavailable queue tables remains not ready."""
    application = _readiness_app(tmp_path)
    application.dependency_overrides[get_product_readiness_service] = lambda: ProductReadinessService(
        _FailingReadinessQuery(database_available=True),
        clock=lambda: NOW,
    )

    response = TestClient(application).get("/ready")

    assert response.status_code == 503
    assert response.json()["database"] == {"status": "available"}
    assert response.json()["queue"]["status"] == "unavailable"


class _FailingReadinessQuery:
    """Deterministic failure double for storage and queue availability tests."""

    def __init__(self, *, database_available: bool) -> None:
        self._database_available = database_available

    def inspect_runtime(self) -> QueueRuntimeSnapshot:
        raise ReadinessQueryError(database_available=self._database_available)


class _FailingMediaTool:
    def status(self) -> None:
        raise RuntimeError("FFmpeg probe failed")


class _FailingArtifactStore:
    def storage_usage(self) -> None:
        raise RuntimeError("Storage probe failed")


def _readiness_app(tmp_path: Path) -> FastAPI:
    application = create_app(
        Settings(
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'database' / 'shotsight2.db'}",
            tracking_backend=None,
        )
    )
    application.dependency_overrides[get_product_readiness_service] = lambda: ProductReadinessService(
        application.state.runtime.worker_queue,
        stale_after=timedelta(seconds=30),
        clock=lambda: NOW,
    )
    return application


def _capabilities(device: DeviceType) -> BackendCapabilities:
    return BackendCapabilities(
        text_prompts=False,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=False,
        native_video_memory=False,
        multi_object_tracking=True,
        batch_support=False,
        mask_output=False,
        supported_devices=(device,),
    )


def _unavailable_mlx(_: SystemProfile) -> BackendHealth:
    return BackendHealth(
        name=TrackingBackendName.MLX_SAM3,
        display_name="MLX SAM 3",
        state=BackendHealthState.UNAVAILABLE,
        capabilities=_capabilities(DeviceType.APPLE_SILICON),
        reason="MLX model missing.",
    )


def _ready_cpu(_: SystemProfile) -> BackendHealth:
    return BackendHealth(
        name=TrackingBackendName.OPENCV_CPU,
        display_name="OpenCV CPU",
        state=BackendHealthState.READY,
        capabilities=_capabilities(DeviceType.CPU),
        reason="OpenCV ready.",
        version="4.11.0",
        model="opencv-heuristic",
        device=BackendDevice(DeviceType.CPU, "Test CPU"),
    )


def _raise_probe_failure(_: SystemProfile) -> BackendHealth:
    raise RuntimeError("Tracking probe failed")
