"""Shooter release-foot estimation from backend-neutral player geometry."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from shotsight2.domain.calibration import ImagePoint
from shotsight2.domain.court import NormalizedCourtCoordinate


@dataclass(frozen=True, slots=True)
class ImageBoundingBox:
    """Axis-aligned player box in image pixels."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (self.left, self.top, self.right, self.bottom)):
            raise ValueError("Bounding box coordinates must be finite")
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("Bounding box must have positive area")


@dataclass(frozen=True, slots=True)
class ReleasePlayerObservation:
    """Player geometry sampled at or immediately around shot release."""

    bounding_box: ImageBoundingBox
    frame_width: int
    frame_height: int
    left_ankle: ImagePoint | None = None
    right_ankle: ImagePoint | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("Frame dimensions must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Observation confidence must be between zero and one")


def estimate_release_foot_position(observation: ReleasePlayerObservation) -> ImagePoint:
    """Estimate floor contact from ankles, falling back to box bottom-center."""
    ankles = tuple(point for point in (observation.left_ankle, observation.right_ankle) if point is not None)
    if ankles:
        return ImagePoint(
            sum(point.x for point in ankles) / len(ankles),
            sum(point.y for point in ankles) / len(ankles),
        )
    box = observation.bounding_box
    return ImagePoint((box.left + box.right) / 2.0, box.bottom)


def indicative_coordinate(observation: ReleasePlayerObservation) -> NormalizedCourtCoordinate:
    """Create a usable image-relative chart position when calibration is weak."""
    point = estimate_release_foot_position(observation)
    return NormalizedCourtCoordinate(
        min(1.0, max(0.0, 1.0 - point.y / observation.frame_height)),
        min(1.0, max(0.0, point.x / observation.frame_width)),
    )
