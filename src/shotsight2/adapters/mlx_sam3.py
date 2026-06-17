"""Lazy MLX SAM 3 Image keyframe adapter boundary."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import cast

from shotsight2.adapters.lazy_tracking import (
    LazyTrackingBackend,
    OptionalTrackingBackendUnavailable,
    RuntimeFactory,
)
from shotsight2.domain.tracking import ModelConfig
from shotsight2.domain.tracking_backends import BackendCapabilities, DeviceType
from shotsight2.ports.tracking import TrackingBackend


class MLXSam3ImageBackend(LazyTrackingBackend):
    """Load an MLX keyframe runtime only after backend selection."""

    def __init__(self, runtime_factory: RuntimeFactory | None = None) -> None:
        super().__init__(
            BackendCapabilities(
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
            ),
            runtime_factory or _default_runtime_factory,
            "MLX SAM 3 Image backend",
        )


def _default_runtime_factory(config: ModelConfig) -> TrackingBackend:
    """Resolve the optional integration entry point without eager imports."""

    del config
    try:
        module = importlib.import_module("mlx_sam3")
    except (ImportError, ModuleNotFoundError) as error:
        raise OptionalTrackingBackendUnavailable(
            "MLX SAM 3 cannot load: optional package 'mlx_sam3' is not installed."
        ) from error
    factory = getattr(module, "create_shotsight_tracking_runtime", None)
    if not callable(factory):
        raise OptionalTrackingBackendUnavailable(
            "Installed 'mlx_sam3' does not expose the ShotSight runtime bridge. "
            "Real-model integration requires the package API and authorized local weights."
        )
    return cast(TrackingBackend, cast(Callable[[], object], factory)())
