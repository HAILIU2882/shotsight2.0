"""Backend-neutral models for tracking capability discovery and selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

type ConfigurationValue = str | int | float | bool | None
type BackendConfiguration = dict[str, ConfigurationValue]


class TrackingBackendName(StrEnum):
    """Stable identifiers for locally supported tracking backend families."""

    MLX_SAM3 = "mlx-sam3"
    SAM3_CUDA = "sam3-cuda"
    OPENCV_CPU = "opencv-cpu"


class DeviceType(StrEnum):
    """Device classes exposed to backend selection and analysis provenance."""

    APPLE_SILICON = "apple-silicon"
    NVIDIA_CUDA = "nvidia-cuda"
    CPU = "cpu"


class BackendHealthState(StrEnum):
    """Readiness states returned by a lazy backend capability probe."""

    READY = "ready"
    UNAVAILABLE = "unavailable"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class SystemProfile:
    """Operating-system and hardware facts used by the selection policy."""

    operating_system: str
    architecture: str
    python_version: str
    total_memory_bytes: int | None

    @property
    def is_apple_silicon(self) -> bool:
        """Return whether the host is an arm64-based macOS device."""
        normalized_architecture = self.architecture.lower()
        return self.operating_system.lower() == "darwin" and normalized_architecture in {
            "arm64",
            "aarch64",
        }


@dataclass(frozen=True, slots=True)
class BackendDevice:
    """Concrete compute device reported by a ready backend."""

    device_type: DeviceType
    name: str
    index: int | None = None
    memory_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Feature flags that downstream tracking code may safely rely upon."""

    text_prompts: bool
    point_prompts: bool
    box_prompts: bool
    mask_prompts: bool
    native_video_memory: bool
    multi_object_tracking: bool
    batch_support: bool
    mask_output: bool
    supported_devices: tuple[DeviceType, ...]
    maximum_recommended_resolution: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class BackendHealth:
    """Capability and readiness result for one registered backend."""

    name: TrackingBackendName
    display_name: str
    state: BackendHealthState
    capabilities: BackendCapabilities
    reason: str
    version: str | None = None
    model: str | None = None
    device: BackendDevice | None = None
    configuration: BackendConfiguration | None = None

    @property
    def is_ready(self) -> bool:
        """Return whether selection may use this backend."""
        return self.state is BackendHealthState.READY


@dataclass(frozen=True, slots=True)
class AnalysisBackendRecord:
    """Reproducible backend provenance stored with an analysis run."""

    backend_name: str
    backend_version: str | None
    model: str | None
    device_type: str
    device_name: str
    configuration: BackendConfiguration


@dataclass(frozen=True, slots=True)
class BackendSelectionResult:
    """Selected backend plus an ordered explanation of any fallback."""

    selected: BackendHealth
    requested_backend: TrackingBackendName | None
    fallback_reasons: tuple[str, ...]
    considered_backends: tuple[BackendHealth, ...]

    def to_analysis_record(
        self,
        analysis_configuration: BackendConfiguration | None = None,
    ) -> AnalysisBackendRecord:
        """Create the backend portion of a reproducible analysis-run record."""
        if self.selected.device is None:
            raise ValueError("A selected backend must report a concrete device.")

        configuration = dict(self.selected.configuration or {})
        configuration.update(analysis_configuration or {})
        if self.fallback_reasons:
            configuration["fallback_reason"] = " ".join(self.fallback_reasons)

        return AnalysisBackendRecord(
            backend_name=self.selected.name.value,
            backend_version=self.selected.version,
            model=self.selected.model,
            device_type=self.selected.device.device_type.value,
            device_name=self.selected.device.name,
            configuration=configuration,
        )


@dataclass(frozen=True, slots=True)
class BackendCapabilityStatus:
    """Route-neutral health data that the application API can expose."""

    system: SystemProfile
    backends: tuple[BackendHealth, ...]
    selected_backend: TrackingBackendName | None
    selection_error: str | None
