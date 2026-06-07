"""Tests for lazy capability probes and deterministic backend selection."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from shotsight2.adapters.backend_probes import (
    BackendProbeConfig,
    BackendRegistry,
    create_default_registry,
)
from shotsight2.domain.tracking_backends import (
    BackendCapabilities,
    BackendDevice,
    BackendHealth,
    BackendHealthState,
    DeviceType,
    SystemProfile,
    TrackingBackendName,
)
from shotsight2.services.tracking_backend_selection import (
    BackendSelectionError,
    TrackingBackendSelector,
    build_backend_capability_status,
)

APPLE = SystemProfile("Darwin", "arm64", "3.12.0", 64 * 1024**3)
LINUX = SystemProfile("Linux", "x86_64", "3.12.0", 32 * 1024**3)
TEST_CPU_DEVICE = BackendDevice(DeviceType.CPU, "Test CPU")


def test_registry_creation_does_not_import_optional_packages() -> None:
    """Registering probes must not import MLX, PyTorch, SAM 3, or OpenCV."""
    imported: list[str] = []

    def importer(name: str) -> ModuleType:
        imported.append(name)
        raise AssertionError("Optional package imported eagerly.")

    registry = create_default_registry(
        BackendProbeConfig(),
        module_finder=lambda _: False,
        module_importer=importer,
    )

    assert registry.names() == (
        TrackingBackendName.MLX_SAM3,
        TrackingBackendName.SAM3_CUDA,
        TrackingBackendName.OPENCV_CPU,
    )
    assert imported == []


def test_apple_silicon_selects_ready_mlx_backend(tmp_path: Path) -> None:
    """Apple Silicon should prefer MLX when its runtime and model are ready."""
    model_path = tmp_path / "sam3-image"
    model_path.mkdir()
    modules = {
        "mlx": _module("mlx", "0.30.0"),
        "mlx_sam3": _module("mlx_sam3", "0.1.0"),
    }
    registry = create_default_registry(
        BackendProbeConfig(mlx_model_path=model_path),
        module_finder=lambda name: name in modules,
        module_importer=modules.__getitem__,
    )

    selection = TrackingBackendSelector(registry).select(APPLE)

    assert selection.selected.name is TrackingBackendName.MLX_SAM3
    assert selection.selected.device is not None
    assert selection.selected.device.device_type is DeviceType.APPLE_SILICON
    assert selection.fallback_reasons == ()


def test_apple_silicon_falls_back_to_cpu_when_mlx_model_is_missing() -> None:
    """A missing MLX model should produce a visible CPU fallback reason."""
    modules = {"mlx", "mlx_sam3", "cv2"}
    cv2_module = _module("cv2", "4.11.0")
    registry = create_default_registry(
        BackendProbeConfig(),
        module_finder=lambda name: name in modules,
        module_importer=lambda name: cv2_module if name == "cv2" else _module(name),
    )

    selection = TrackingBackendSelector(registry).select(APPLE)

    assert selection.selected.name is TrackingBackendName.OPENCV_CPU
    assert "model path is not configured" in selection.fallback_reasons[0]
    record = selection.to_analysis_record({"sampling_fps": 12})
    assert record.backend_name == "opencv-cpu"
    assert record.backend_version == "4.11.0"
    assert record.device_type == "cpu"
    assert record.configuration["sampling_fps"] == 12
    assert "fallback_reason" in record.configuration


def test_linux_selects_ready_cuda_backend(tmp_path: Path) -> None:
    """A supported NVIDIA environment should select official SAM 3.1."""
    model_path = tmp_path / "sam3.pt"
    model_path.touch()
    torch_module = _module("torch", "2.7.0")
    torch_module.cuda = _FakeCuda()
    torch_module.version = SimpleNamespace(cuda="12.6")
    modules = {
        "torch": torch_module,
        "sam3": _module("sam3", "3.1.0"),
    }
    registry = create_default_registry(
        BackendProbeConfig(sam3_model_path=model_path),
        module_finder=lambda name: name in modules,
        module_importer=modules.__getitem__,
    )

    selection = TrackingBackendSelector(registry).select(LINUX)

    assert selection.selected.name is TrackingBackendName.SAM3_CUDA
    assert selection.selected.device is not None
    assert selection.selected.device.name == "NVIDIA Test GPU"
    assert selection.selected.configuration == {
        "model_path": str(model_path),
        "cuda_version": "12.6",
    }


def test_cpu_only_environment_selects_fallback() -> None:
    """A non-Apple machine with no CUDA runtime should use OpenCV."""
    cv2_module = _module("cv2", "4.11.0")
    registry = create_default_registry(
        BackendProbeConfig(),
        module_finder=lambda name: name == "cv2",
        module_importer=lambda _: cv2_module,
    )

    first = TrackingBackendSelector(registry).select(LINUX)
    second = TrackingBackendSelector(registry).select(LINUX)

    assert first.selected.name is TrackingBackendName.OPENCV_CPU
    assert first == second
    assert "PyTorch is not installed" in first.fallback_reasons[0]


def test_unhealthy_preferred_backend_falls_back_with_reason() -> None:
    """An import failure is unhealthy, visible, and does not block CPU fallback."""
    registry = create_default_registry(
        BackendProbeConfig(mlx_model_path=Path(__file__)),
        module_finder=lambda name: name in {"mlx", "mlx_sam3", "cv2"},
        module_importer=lambda name: (
            (_ for _ in ()).throw(RuntimeError("broken Metal runtime")) if name == "mlx" else _module(name, "4.11.0")
        ),
    )

    selection = TrackingBackendSelector(registry).select(APPLE)

    assert selection.selected.name is TrackingBackendName.OPENCV_CPU
    assert "broken Metal runtime" in selection.fallback_reasons[0]


def test_requested_backend_override_is_validated() -> None:
    """Overrides must name a registered and ready backend."""
    registry = _registry_with_reports(
        _health(TrackingBackendName.MLX_SAM3, BackendHealthState.UNAVAILABLE, "model missing"),
        _health(TrackingBackendName.OPENCV_CPU, BackendHealthState.READY, "ready"),
    )
    selector = TrackingBackendSelector(registry)

    with pytest.raises(BackendSelectionError, match="model missing"):
        selector.select(APPLE, TrackingBackendName.MLX_SAM3)
    with pytest.raises(BackendSelectionError, match="Unknown tracking backend"):
        selector.select(APPLE, "not-a-backend")

    selected = selector.select(APPLE, "opencv-cpu")
    assert selected.selected.name is TrackingBackendName.OPENCV_CPU
    assert selected.requested_backend is TrackingBackendName.OPENCV_CPU


def test_no_ready_backend_returns_health_selection_error() -> None:
    """Health integration should remain usable when no backend can run."""
    registry = create_default_registry(
        BackendProbeConfig(),
        module_finder=lambda _: False,
        module_importer=lambda name: _module(name),
    )

    status = build_backend_capability_status(registry, system=APPLE)

    assert status.selected_backend is None
    assert status.selection_error is not None
    assert "No compatible tracking backend" in status.selection_error
    assert len(status.backends) == 3


def test_ready_backend_requires_device_for_analysis_record() -> None:
    """Incomplete probe output must never become persisted provenance."""
    selection = TrackingBackendSelector(
        _registry_with_reports(_health(TrackingBackendName.OPENCV_CPU, BackendHealthState.READY, "ready", device=None))
    ).select(LINUX)

    with pytest.raises(ValueError, match="concrete device"):
        selection.to_analysis_record()


def test_registry_rejects_duplicates_and_unknown_names() -> None:
    """Registry errors should identify configuration defects clearly."""
    registry = BackendRegistry()
    report = _health(TrackingBackendName.OPENCV_CPU, BackendHealthState.READY, "ready")
    registry.register(report.name, lambda _: report)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(report.name, lambda _: report)
    with pytest.raises(KeyError, match="not registered"):
        registry.probe(TrackingBackendName.MLX_SAM3, APPLE)


class _FakeCuda:
    def is_available(self) -> bool:
        return True

    def device_count(self) -> int:
        return 1

    def get_device_properties(self, _: int) -> SimpleNamespace:
        return SimpleNamespace(total_memory=24 * 1024**3)

    def get_device_name(self, _: int) -> str:
        return "NVIDIA Test GPU"


def _module(name: str, version: str | None = None) -> ModuleType:
    module = ModuleType(name)
    if version is not None:
        module.__version__ = version
    return module


def _capabilities() -> BackendCapabilities:
    return BackendCapabilities(
        text_prompts=False,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=False,
        native_video_memory=False,
        multi_object_tracking=True,
        batch_support=False,
        mask_output=False,
        supported_devices=(DeviceType.CPU,),
    )


def _health(
    name: TrackingBackendName,
    state: BackendHealthState,
    reason: str,
    *,
    device: BackendDevice | None = TEST_CPU_DEVICE,
) -> BackendHealth:
    return BackendHealth(
        name=name,
        display_name=name.value,
        state=state,
        capabilities=_capabilities(),
        reason=reason,
        device=device,
    )


def _registry_with_reports(*reports: BackendHealth) -> BackendRegistry:
    registry = BackendRegistry()
    for report in reports:
        registry.register(report.name, lambda _, value=report: value)
    return registry
