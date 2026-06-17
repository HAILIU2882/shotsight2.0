"""Lazy official SAM 3.1 video adapter boundary."""

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


class Sam31VideoBackend(LazyTrackingBackend):
    """Load the CUDA video runtime only after capability selection."""

    def __init__(self, runtime_factory: RuntimeFactory | None = None) -> None:
        super().__init__(
            BackendCapabilities(
                text_prompts=True,
                point_prompts=True,
                box_prompts=True,
                mask_prompts=True,
                native_video_memory=True,
                multi_object_tracking=True,
                batch_support=True,
                mask_output=True,
                supported_devices=(DeviceType.NVIDIA_CUDA,),
            ),
            runtime_factory or _default_runtime_factory,
            "Official SAM 3.1 video backend",
        )


def _default_runtime_factory(config: ModelConfig) -> TrackingBackend:
    """Resolve an installed official runtime bridge without importing at startup."""

    del config
    try:
        module = importlib.import_module("sam3")
    except (ImportError, ModuleNotFoundError) as error:
        raise OptionalTrackingBackendUnavailable(
            "Official SAM 3.1 cannot load: optional package 'sam3' is not installed."
        ) from error
    factory = getattr(module, "create_shotsight_tracking_runtime", None)
    if not callable(factory):
        raise OptionalTrackingBackendUnavailable(
            "Installed 'sam3' does not expose the ShotSight runtime bridge. "
            "Real-model integration requires a compatible CUDA build, official predictor API, "
            "and authorized SAM 3.1 weights."
        )
    return cast(TrackingBackend, cast(Callable[[], object], factory)())
