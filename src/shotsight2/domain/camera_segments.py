"""Camera stability timeline and segment value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class StabilityStatus(StrEnum):
    """Classification assigned to a contiguous camera timeline range."""

    STABLE = "stable"
    UNSTABLE = "unstable"
    TRANSITION = "transition"


@dataclass(frozen=True, slots=True)
class CameraSegmentConfig:
    """Deterministic sampling, classification, and range-cleanup policy."""

    sample_interval_seconds: float = 0.25
    analysis_width: int = 320
    motion_threshold: float = 0.012
    image_change_threshold: float = 0.08
    scene_change_threshold: float = 0.32
    noisy_range_max_seconds: float = 0.5
    transition_padding_seconds: float = 0.25
    minimum_stable_duration_seconds: float = 2.0
    representative_edge_margin_seconds: float = 0.5

    def __post_init__(self) -> None:
        positive_values = (
            self.sample_interval_seconds,
            float(self.analysis_width),
            self.motion_threshold,
            self.image_change_threshold,
            self.scene_change_threshold,
            self.minimum_stable_duration_seconds,
        )
        if any(value <= 0 for value in positive_values):
            raise ValueError("Camera segment configuration values must be positive")
        if self.noisy_range_max_seconds < 0:
            raise ValueError("Noisy range duration cannot be negative")
        if self.transition_padding_seconds < 0:
            raise ValueError("Transition padding cannot be negative")
        if self.representative_edge_margin_seconds < 0:
            raise ValueError("Representative frame margin cannot be negative")
        if self.scene_change_threshold <= self.image_change_threshold:
            raise ValueError("Scene-change threshold must exceed image-change threshold")


@dataclass(frozen=True, slots=True)
class MotionFeature:
    """Motion evidence between two sampled frames."""

    start_seconds: float
    end_seconds: float
    global_motion: float
    image_change: float
    scene_change: float
    confidence: float


@dataclass(frozen=True, slots=True)
class ClassifiedInterval:
    """A sampled interval with its raw or cleaned stability status."""

    start_seconds: float
    end_seconds: float
    status: StabilityStatus
    confidence: float
    motion: float


@dataclass(frozen=True, slots=True)
class StabilityRange:
    """A contiguous stable, unstable, or transition timeline range."""

    start_seconds: float
    end_seconds: float
    status: StabilityStatus
    confidence: float

    @property
    def duration_seconds(self) -> float:
        """Return the range duration."""

        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class CameraSegment:
    """A stable camera viewpoint with independent downstream state scopes."""

    id: str
    analysis_run_id: str
    start_seconds: float
    end_seconds: float
    confidence: float
    representative_frame: Path
    representative_timestamp_seconds: float
    calibration_scope_id: str
    tracking_scope_id: str

    @property
    def duration_seconds(self) -> float:
        """Return the stable segment duration."""

        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class CameraSegmentTimeline:
    """Complete segmentation output consumed by persistence and downstream stages."""

    analysis_run_id: str
    source: Path
    duration_seconds: float
    ranges: tuple[StabilityRange, ...]
    stable_segments: tuple[CameraSegment, ...]
    features: tuple[MotionFeature, ...]

    def status_at(self, timestamp_seconds: float) -> StabilityStatus:
        """Return the timeline status at a source timestamp."""

        if timestamp_seconds < 0 or timestamp_seconds > self.duration_seconds:
            raise ValueError("Timestamp is outside the source duration")
        for timeline_range in self.ranges:
            if timeline_range.start_seconds <= timestamp_seconds < timeline_range.end_seconds:
                return timeline_range.status
        return self.ranges[-1].status

    def should_process(self, timestamp_seconds: float) -> bool:
        """Return whether tracking and shot logic may process this timestamp."""

        return self.status_at(timestamp_seconds) is StabilityStatus.STABLE


@dataclass(frozen=True, slots=True)
class ManualBoundary:
    """A manually labeled camera boundary used for benchmark comparison."""

    timestamp_seconds: float
    label: str = ""


@dataclass(frozen=True, slots=True)
class BoundaryMatch:
    """One detected boundary matched to a manual label."""

    detected_seconds: float
    expected_seconds: float
    error_seconds: float


@dataclass(frozen=True, slots=True)
class BoundaryEvaluation:
    """Precision, recall, and timing errors for labeled camera boundaries."""

    tolerance_seconds: float
    matches: tuple[BoundaryMatch, ...]
    missed_expected_seconds: tuple[float, ...]
    extra_detected_seconds: tuple[float, ...]

    @property
    def precision(self) -> float:
        """Return detected-boundary precision."""

        denominator = len(self.matches) + len(self.extra_detected_seconds)
        return len(self.matches) / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        """Return expected-boundary recall."""

        denominator = len(self.matches) + len(self.missed_expected_seconds)
        return len(self.matches) / denominator if denominator else 1.0

    @property
    def mean_absolute_error_seconds(self) -> float | None:
        """Return mean timing error for matched boundaries."""

        if not self.matches:
            return None
        return sum(match.error_seconds for match in self.matches) / len(self.matches)
