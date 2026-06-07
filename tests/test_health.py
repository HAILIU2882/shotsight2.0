"""Smoke tests for the initial application scaffold."""

from fastapi.testclient import TestClient

from shotsight2.adapters.backend_probes import BackendRegistry
from shotsight2.config import Settings
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
