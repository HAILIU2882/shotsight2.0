"""Lazy capability probes for optional local tracking runtimes."""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

from shotsight2.domain.tracking_backends import (
    BackendCapabilities,
    BackendConfiguration,
    BackendDevice,
    BackendHealth,
    BackendHealthState,
    DeviceType,
    SystemProfile,
    TrackingBackendName,
)

ModuleFinder = Callable[[str], bool]
ModuleImporter = Callable[[str], ModuleType]


class BackendProbe(Protocol):
    """Callable capability check stored by the backend registry."""

    def __call__(self, system: SystemProfile) -> BackendHealth:
        """Inspect one backend without importing it until this call."""
        ...


@dataclass(frozen=True, slots=True)
class BackendProbeConfig:
    """Filesystem and model settings required by optional backend probes."""

    mlx_model_path: Path | None = None
    sam3_model_path: Path | None = None
    cpu_model_path: Path | None = None


class BackendRegistry:
    """Ordered registry of backend probes with no eager AI-package imports."""

    def __init__(self) -> None:
        self._probes: dict[TrackingBackendName, BackendProbe] = {}

    def register(self, name: TrackingBackendName, probe: BackendProbe) -> None:
        """Register one probe and reject accidental duplicate ownership."""
        if name in self._probes:
            raise ValueError(f"Tracking backend '{name.value}' is already registered.")
        self._probes[name] = probe

    def probe(self, name: TrackingBackendName, system: SystemProfile) -> BackendHealth:
        """Run a named probe."""
        try:
            probe = self._probes[name]
        except KeyError as error:
            raise KeyError(f"Tracking backend '{name.value}' is not registered.") from error
        return probe(system)

    def probe_all(self, system: SystemProfile) -> tuple[BackendHealth, ...]:
        """Run all probes in stable registration order."""
        return tuple(probe(system) for probe in self._probes.values())

    def names(self) -> tuple[TrackingBackendName, ...]:
        """Return backend names in deterministic registration order."""
        return tuple(self._probes)


def inspect_system_profile() -> SystemProfile:
    """Inspect host OS, architecture, Python version, and physical memory."""
    return SystemProfile(
        operating_system=platform.system(),
        architecture=platform.machine(),
        python_version=platform.python_version(),
        total_memory_bytes=_total_memory_bytes(),
    )


def create_default_registry(
    config: BackendProbeConfig,
    *,
    module_finder: ModuleFinder | None = None,
    module_importer: ModuleImporter | None = None,
) -> BackendRegistry:
    """Create the confirmed MLX, CUDA, then CPU registry with lazy probes."""
    finder = module_finder or _module_exists
    importer = module_importer or importlib.import_module
    registry = BackendRegistry()
    registry.register(
        TrackingBackendName.MLX_SAM3,
        _create_mlx_probe(config, finder, importer),
    )
    registry.register(
        TrackingBackendName.SAM3_CUDA,
        _create_cuda_probe(config, finder, importer),
    )
    registry.register(
        TrackingBackendName.OPENCV_CPU,
        _create_cpu_probe(config, finder, importer),
    )
    return registry


def _create_mlx_probe(
    config: BackendProbeConfig,
    finder: ModuleFinder,
    importer: ModuleImporter,
) -> BackendProbe:
    capabilities = BackendCapabilities(
        text_prompts=True,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=True,
        native_video_memory=False,
        multi_object_tracking=True,
        batch_support=True,
        mask_output=True,
        supported_devices=(DeviceType.APPLE_SILICON,),
        maximum_recommended_resolution=(1008, 1008),
    )

    def probe(system: SystemProfile) -> BackendHealth:
        if not system.is_apple_silicon:
            return _unavailable(
                TrackingBackendName.MLX_SAM3,
                "MLX SAM 3 Image + temporal tracker",
                capabilities,
                "MLX requires an Apple Silicon macOS host.",
            )
        if not finder("mlx") or not finder("mlx_sam3"):
            return _unavailable(
                TrackingBackendName.MLX_SAM3,
                "MLX SAM 3 Image + temporal tracker",
                capabilities,
                "The optional 'mlx' and 'mlx_sam3' packages are not both installed.",
            )
        model_error = _model_error(config.mlx_model_path, "MLX SAM 3")
        if model_error is not None:
            return _unavailable(
                TrackingBackendName.MLX_SAM3,
                "MLX SAM 3 Image + temporal tracker",
                capabilities,
                model_error,
            )

        try:
            mlx_module = importer("mlx")
            mlx_sam3_module = importer("mlx_sam3")
        except Exception as error:
            return _unhealthy(
                TrackingBackendName.MLX_SAM3,
                "MLX SAM 3 Image + temporal tracker",
                capabilities,
                f"MLX runtime import failed: {error}",
            )

        version = _module_version(mlx_sam3_module) or _module_version(mlx_module)
        return BackendHealth(
            name=TrackingBackendName.MLX_SAM3,
            display_name="MLX SAM 3 Image + temporal tracker",
            state=BackendHealthState.READY,
            capabilities=capabilities,
            reason="Apple Silicon, MLX runtime, and local model are ready.",
            version=version,
            model=config.mlx_model_path.name if config.mlx_model_path else None,
            device=BackendDevice(
                device_type=DeviceType.APPLE_SILICON,
                name=f"Apple Silicon ({system.architecture})",
                memory_bytes=system.total_memory_bytes,
            ),
            configuration=_path_configuration("model_path", config.mlx_model_path),
        )

    return probe


def _create_cuda_probe(
    config: BackendProbeConfig,
    finder: ModuleFinder,
    importer: ModuleImporter,
) -> BackendProbe:
    capabilities = BackendCapabilities(
        text_prompts=True,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=True,
        native_video_memory=True,
        multi_object_tracking=True,
        batch_support=True,
        mask_output=True,
        supported_devices=(DeviceType.NVIDIA_CUDA,),
    )

    def probe(system: SystemProfile) -> BackendHealth:
        if not finder("torch"):
            return _unavailable(
                TrackingBackendName.SAM3_CUDA,
                "Official SAM 3.1 video",
                capabilities,
                "PyTorch is not installed.",
            )
        if not finder("sam3"):
            return _unavailable(
                TrackingBackendName.SAM3_CUDA,
                "Official SAM 3.1 video",
                capabilities,
                "The optional official 'sam3' package is not installed.",
            )
        model_error = _model_error(config.sam3_model_path, "SAM 3.1")
        if model_error is not None:
            return _unavailable(
                TrackingBackendName.SAM3_CUDA,
                "Official SAM 3.1 video",
                capabilities,
                model_error,
            )

        try:
            torch_module = importer("torch")
            sam3_module = importer("sam3")
            cuda = cast(Any, torch_module).cuda
            if not bool(cuda.is_available()) or int(cuda.device_count()) < 1:
                return _unavailable(
                    TrackingBackendName.SAM3_CUDA,
                    "Official SAM 3.1 video",
                    capabilities,
                    "PyTorch cannot access a supported NVIDIA CUDA device.",
                )
            properties = cuda.get_device_properties(0)
            device_name = str(cuda.get_device_name(0))
            memory_bytes = int(properties.total_memory)
        except Exception as error:
            return _unhealthy(
                TrackingBackendName.SAM3_CUDA,
                "Official SAM 3.1 video",
                capabilities,
                f"CUDA/SAM 3.1 runtime probe failed: {error}",
            )

        torch_version = _module_version(torch_module)
        sam_version = _module_version(sam3_module)
        versions = [value for value in (sam_version, torch_version) if value]
        return BackendHealth(
            name=TrackingBackendName.SAM3_CUDA,
            display_name="Official SAM 3.1 video",
            state=BackendHealthState.READY,
            capabilities=capabilities,
            reason="NVIDIA CUDA, official SAM 3.1, and local model are ready.",
            version=" / ".join(versions) or None,
            model=config.sam3_model_path.name if config.sam3_model_path else None,
            device=BackendDevice(
                device_type=DeviceType.NVIDIA_CUDA,
                name=device_name,
                index=0,
                memory_bytes=memory_bytes,
            ),
            configuration={
                **_path_configuration("model_path", config.sam3_model_path),
                "cuda_version": str(getattr(cast(Any, torch_module).version, "cuda", "unknown")),
            },
        )

    return probe


def _create_cpu_probe(
    config: BackendProbeConfig,
    finder: ModuleFinder,
    importer: ModuleImporter,
) -> BackendProbe:
    capabilities = BackendCapabilities(
        text_prompts=False,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=False,
        native_video_memory=False,
        multi_object_tracking=True,
        batch_support=False,
        mask_output=False,
        supported_devices=(DeviceType.CPU,),
        maximum_recommended_resolution=(960, 540),
    )

    def probe(system: SystemProfile) -> BackendHealth:
        if not finder("cv2"):
            return _unavailable(
                TrackingBackendName.OPENCV_CPU,
                "OpenCV CPU fallback",
                capabilities,
                "The optional 'opencv-python-headless' package is not installed.",
            )
        try:
            cv2_module = importer("cv2")
        except Exception as error:
            return _unhealthy(
                TrackingBackendName.OPENCV_CPU,
                "OpenCV CPU fallback",
                capabilities,
                f"OpenCV runtime import failed: {error}",
            )

        configuration = _path_configuration("model_path", config.cpu_model_path)
        configuration["quality_tier"] = "fallback"
        return BackendHealth(
            name=TrackingBackendName.OPENCV_CPU,
            display_name="OpenCV CPU fallback",
            state=BackendHealthState.READY,
            capabilities=capabilities,
            reason="OpenCV is available for CPU fallback tracking.",
            version=_module_version(cv2_module),
            model=config.cpu_model_path.name if config.cpu_model_path else "opencv-heuristic",
            device=BackendDevice(
                device_type=DeviceType.CPU,
                name=f"{system.architecture} CPU",
                memory_bytes=system.total_memory_bytes,
            ),
            configuration=configuration,
        )

    return probe


def _module_exists(module_name: str) -> bool:
    """Check a module without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _total_memory_bytes() -> int | None:
    """Read physical memory with a portable standard-library fallback."""
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
    total = page_size * page_count
    return total if total > 0 else None


def _model_error(model_path: Path | None, model_name: str) -> str | None:
    if model_path is None:
        return f"{model_name} model path is not configured."
    if not model_path.exists():
        return f"{model_name} model was not found at '{model_path}'."
    if not model_path.is_file() and not model_path.is_dir():
        return f"{model_name} model path '{model_path}' is not usable."
    return None


def _module_version(module: ModuleType) -> str | None:
    version = getattr(module, "__version__", None)
    return str(version) if version is not None else None


def _path_configuration(key: str, path: Path | None) -> BackendConfiguration:
    return {key: str(path)} if path is not None else {}


def _unavailable(
    name: TrackingBackendName,
    display_name: str,
    capabilities: BackendCapabilities,
    reason: str,
) -> BackendHealth:
    return BackendHealth(
        name=name,
        display_name=display_name,
        state=BackendHealthState.UNAVAILABLE,
        capabilities=capabilities,
        reason=reason,
    )


def _unhealthy(
    name: TrackingBackendName,
    display_name: str,
    capabilities: BackendCapabilities,
    reason: str,
) -> BackendHealth:
    return BackendHealth(
        name=name,
        display_name=display_name,
        state=BackendHealthState.UNHEALTHY,
        capabilities=capabilities,
        reason=reason,
    )
