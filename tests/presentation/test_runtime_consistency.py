"""Backend-selection and video-scoped repair regression tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from shotsight2.adapters.backend_probes import BackendRegistry
from shotsight2.domain import AnalysisRun, AnalysisStage, CameraSegment, RunStatus, Video, VideoStatus
from shotsight2.domain.tracking_backends import (
    BackendCapabilities,
    BackendDevice,
    BackendHealth,
    BackendHealthState,
    DeviceType,
    SystemProfile,
    TrackingBackendName,
)
from shotsight2.services.backend_configuration import AnalysisBackendConfigurationService
from shotsight2.services.tracking_backend_selection import BackendSelectionError
from shotsight2.services.tracking_repair import (
    TrackingRepairNotFoundError,
    TrackingRepairService,
    TrackingRepairUnavailableError,
)

_NOW = datetime(2026, 6, 21, tzinfo=UTC)
_APPLE = SystemProfile("Darwin", "arm64", "3.13.1", 16_000_000_000)
_CAPABILITIES = BackendCapabilities(
    text_prompts=True,
    point_prompts=True,
    box_prompts=True,
    mask_prompts=False,
    native_video_memory=False,
    multi_object_tracking=True,
    batch_support=True,
    mask_output=False,
    supported_devices=(DeviceType.APPLE_SILICON,),
)


def _health(name: TrackingBackendName, version: str, *, ready: bool = True) -> BackendHealth:
    return BackendHealth(
        name=name,
        display_name=name.value,
        state=BackendHealthState.READY if ready else BackendHealthState.UNAVAILABLE,
        capabilities=_CAPABILITIES,
        reason="ready" if ready else "not installed",
        version=version if ready else None,
        model="model",
        device=BackendDevice(DeviceType.APPLE_SILICON, "Apple M-series") if ready else None,
        configuration={"model_path": "/models/sam3"} if ready else None,
    )


def test_configured_mlx_backend_drives_form_and_submission_version() -> None:
    registry = BackendRegistry()
    registry.register(TrackingBackendName.MLX_SAM3, lambda _system: _health(TrackingBackendName.MLX_SAM3, "0.9"))
    registry.register(
        TrackingBackendName.OPENCV_CPU,
        lambda _system: _health(TrackingBackendName.OPENCV_CPU, "4.13"),
    )
    service = AnalysisBackendConfigurationService(registry, _APPLE, "mlx-sam3")

    catalog = service.catalog()
    configuration = service.resolve("mlx-sam3")

    assert next(option for option in catalog.options if option.name == "mlx-sam3").selected
    assert configuration.backend_name == "mlx-sam3"
    assert configuration.backend_version == "0.9"
    assert configuration.values["model_path"] == "/models/sam3"


def test_unavailable_backend_cannot_be_submitted_even_if_client_forges_value() -> None:
    registry = BackendRegistry()
    registry.register(
        TrackingBackendName.MLX_SAM3,
        lambda _system: _health(TrackingBackendName.MLX_SAM3, "0", ready=False),
    )
    service = AnalysisBackendConfigurationService(registry, _APPLE, None)

    with pytest.raises(BackendSelectionError, match="unavailable"):
        service.resolve("mlx-sam3")


def _video(video_id: str) -> Video:
    return Video(
        id=video_id,
        filename=f"{video_id}.mp4",
        original_artifact_id=f"original:{video_id}",
        size_bytes=1,
        duration_seconds=10,
        width=640,
        height=360,
        fps=30,
        codec="h264",
        container="mp4",
        created_at=_NOW,
        status=VideoStatus.READY,
    )


def _run(run_id: str, video_id: str) -> AnalysisRun:
    return AnalysisRun(
        id=run_id,
        video_id=video_id,
        status=RunStatus.COMPLETED,
        backend_name="opencv-cpu",
        backend_version="4.13",
        configuration={},
        progress=1,
        stage=AnalysisStage.FINALIZING,
        started_at=_NOW,
        published=True,
    )


def _segment(segment_id: str, run_id: str) -> CameraSegment:
    return CameraSegment(
        id=segment_id,
        analysis_run_id=run_id,
        start_seconds=0,
        end_seconds=10,
        stability_status="STABLE",
        confidence=1,
        representative_artifact_id=f"render:{run_id}/{segment_id}.jpg",
    )


def test_tracking_repair_context_and_submission_never_cross_video_boundary() -> None:
    videos = MagicMock()
    runs = MagicMock()
    segments = MagicMock()
    videos.get.side_effect = lambda video_id: _video(video_id) if video_id in {"v1", "v2"} else None
    runs.list_for_video.side_effect = lambda video_id: [_run(f"run-{video_id}", video_id)]
    runs.get.side_effect = lambda run_id: _run(run_id, run_id.removeprefix("run-"))
    segments.list_for_run.side_effect = lambda run_id: [_segment(f"segment-{run_id}", run_id)]
    segments.get.return_value = _segment("segment-run-v2", "run-v2")
    service = TrackingRepairService(videos, runs, segments)

    context = service.context("v1")

    assert context.run_id == "run-v1"
    assert [segment.segment_id for segment in context.segments] == ["segment-run-v1"]
    with pytest.raises(TrackingRepairNotFoundError, match="does not belong"):
        service.reject_submission("v1", "segment-run-v2")


def test_valid_completed_run_repair_is_truthfully_rejected_without_persistence() -> None:
    videos = MagicMock()
    runs = MagicMock()
    segments = MagicMock()
    videos.get.return_value = _video("v1")
    runs.get.return_value = _run("run-v1", "v1")
    segments.get.return_value = _segment("segment-v1", "run-v1")
    service = TrackingRepairService(videos, runs, segments)

    with pytest.raises(TrackingRepairUnavailableError, match="cannot be applied atomically"):
        service.reject_submission("v1", "segment-v1")
