"""Ports used by the camera segmentation service."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

import numpy as np
import numpy.typing as npt

from shotsight2.domain.camera_segments import CameraSegmentTimeline

GrayFrame = npt.NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class SampledFrame:
    """One low-resolution grayscale frame sampled from a media source."""

    timestamp_seconds: float
    pixels: GrayFrame


class CameraFrameSource(Protocol):
    """Low-resolution deterministic frame access for motion analysis."""

    def sample(
        self,
        source: Path,
        *,
        duration_seconds: float,
        interval_seconds: float,
        analysis_width: int,
    ) -> Iterator[SampledFrame]:
        """Yield grayscale frames in ascending timestamp order."""


class CameraSegmentRepository(Protocol):
    """Persistence boundary for replacing one run's camera timeline."""

    def replace_for_run(self, analysis_run_id: UUID, timeline: CameraSegmentTimeline) -> None:
        """Atomically replace camera segmentation output for an analysis run."""
