"""OpenCV-backed low-resolution frame sampling."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np

from shotsight2.ports.camera_segments import GrayFrame, SampledFrame


class OpenCVFrameSourceError(RuntimeError):
    """Raised when OpenCV cannot decode the requested media source."""


class OpenCVFrameSource:
    """Sample deterministic grayscale frames by media timestamp."""

    def sample(
        self,
        source: Path,
        *,
        duration_seconds: float,
        interval_seconds: float,
        analysis_width: int,
    ) -> Iterator[SampledFrame]:
        """Yield low-resolution frames, including both timeline endpoints."""

        if duration_seconds <= 0 or interval_seconds <= 0 or analysis_width <= 0:
            raise ValueError("Duration, interval, and analysis width must be positive")
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise OpenCVFrameSourceError(f"Unable to open camera-analysis source: {source}")
        try:
            for timestamp in _sample_timestamps(duration_seconds, interval_seconds):
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
                decoded, frame = capture.read()
                if not decoded or frame is None:
                    if timestamp == duration_seconds:
                        continue
                    raise OpenCVFrameSourceError(f"Unable to decode camera-analysis frame at {timestamp:.3f}s")
                yield SampledFrame(
                    timestamp_seconds=timestamp,
                    pixels=_prepare_frame(frame, analysis_width),
                )
        finally:
            capture.release()


def _sample_timestamps(duration_seconds: float, interval_seconds: float) -> tuple[float, ...]:
    count = int(duration_seconds / interval_seconds)
    timestamps = [round(index * interval_seconds, 9) for index in range(count + 1)]
    if duration_seconds - timestamps[-1] > 1e-6:
        timestamps.append(duration_seconds)
    else:
        timestamps[-1] = duration_seconds
    return tuple(timestamps)


def _prepare_frame(
    frame: np.ndarray[tuple[int, ...], np.dtype[Any]],
    analysis_width: int,
) -> GrayFrame:
    height, width = frame.shape[:2]
    resized = frame
    if width > analysis_width:
        target_height = max(1, round(height * analysis_width / width))
        resized = cv2.resize(
            frame,
            (analysis_width, target_height),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return cast(GrayFrame, cv2.GaussianBlur(gray, (5, 5), 0))
