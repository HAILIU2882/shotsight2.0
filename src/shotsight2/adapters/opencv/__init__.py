"""OpenCV adapters used by camera stability analysis."""

from shotsight2.adapters.opencv.frame_source import OpenCVFrameSource, OpenCVFrameSourceError
from shotsight2.adapters.opencv.tracking import (
    OpenCVTrackingBackend,
    OpenCVTrackingError,
    OpenCVTrackingFrameSource,
)

__all__ = [
    "OpenCVFrameSource",
    "OpenCVFrameSourceError",
    "OpenCVTrackingBackend",
    "OpenCVTrackingError",
    "OpenCVTrackingFrameSource",
]
