"""Backend-neutral tracking values, observations, and quality metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from shotsight2.domain.persistence import JsonObject


class TrackedObjectClass(StrEnum):
    """Object concepts owned by the tracking module."""

    BASKETBALL = "basketball"
    PLAYER = "player"
    RIM = "rim"


class PromptKind(StrEnum):
    """Prompt representations accepted across backend families."""

    CONCEPT = "concept"
    POINT = "point"
    BOX = "box"
    MASK = "mask"


class PromptSource(StrEnum):
    """Origin of a tracking prompt."""

    AUTOMATIC = "automatic"
    USER = "user"


class VisibilityState(StrEnum):
    """Visibility assigned to an object observation."""

    VISIBLE = "visible"
    PARTIAL = "partial"
    OCCLUDED = "occluded"
    LOST = "lost"


class TrackingEventKind(StrEnum):
    """Quality events emitted by orchestration."""

    TRACK_LOST = "track_lost"
    OCCLUSION = "occlusion"
    IDENTITY_SWITCH = "identity_switch"
    REINITIALIZED = "reinitialized"
    REJECTED_IMPLAUSIBLE = "rejected_implausible"


@dataclass(frozen=True, slots=True)
class ImagePoint:
    """Pixel-space point."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Pixel-space axis-aligned object bounds."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Bounding-box dimensions must be positive")

    @property
    def centroid(self) -> ImagePoint:
        """Return the center point."""

        return ImagePoint(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self) -> float:
        """Return area in pixels."""

        return self.width * self.height

    def intersection_area(self, other: BoundingBox) -> float:
        """Return intersection area with another box."""

        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.x + self.width, other.x + other.width)
        bottom = min(self.y + self.height, other.y + other.height)
        return max(0.0, right - left) * max(0.0, bottom - top)


@dataclass(frozen=True, slots=True)
class MaskReference:
    """Reference to a persisted mask without embedding binary data."""

    artifact_id: str
    frame_index: int


@dataclass(frozen=True, slots=True)
class TrackingPrompt:
    """Automatic concept or persisted user repair prompt."""

    id: str
    segment_id: str
    timestamp_seconds: float
    object_class: TrackedObjectClass
    kind: PromptKind
    source: PromptSource
    point: ImagePoint | None = None
    box: BoundingBox | None = None
    mask: MaskReference | None = None
    target_track_id: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp_seconds < 0:
            raise ValueError("Prompt timestamp cannot be negative")
        supplied = sum(value is not None for value in (self.point, self.box, self.mask))
        if self.kind is PromptKind.CONCEPT:
            if supplied or not self.text:
                raise ValueError("Concept prompts require text and no geometry")
        elif self.kind is PromptKind.POINT and (self.point is None or supplied != 1):
            raise ValueError("Point prompts require only a point")
        elif self.kind is PromptKind.BOX and (self.box is None or supplied != 1):
            raise ValueError("Box prompts require only a box")
        elif self.kind is PromptKind.MASK and (self.mask is None or supplied != 1):
            raise ValueError("Mask prompts require only a mask reference")


@dataclass(frozen=True, slots=True)
class CameraSegmentInput:
    """Stable camera range supplied to a backend."""

    id: str
    analysis_run_id: str
    start_seconds: float
    end_seconds: float
    width: int
    height: int
    fps: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("Camera segment must have a positive time range")
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("Camera segment dimensions and frame rate must be positive")


@dataclass(frozen=True, slots=True)
class TrackingFrame:
    """Decoded frame passed through the backend-neutral contract."""

    frame_index: int
    timestamp_seconds: float
    pixels: object


@dataclass(frozen=True, slots=True)
class FrameBatch:
    """Ordered frames processed together by a backend."""

    frames: tuple[TrackingFrame, ...]

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("Frame batch cannot be empty")
        timestamps = tuple(frame.timestamp_seconds for frame in self.frames)
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("Frame batch timestamps must be ascending")


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Backend model and runtime configuration."""

    model_path: str | None = None
    device: str | None = None
    options: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrackingSession:
    """Opaque segment-scoped handle shared with orchestration."""

    id: str
    segment_id: str
    backend_name: str


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    """Reproducible origin of one observation."""

    backend_name: str
    backend_version: str | None
    model: str | None
    session_id: str
    prompt_id: str | None = None
    reinitialized: bool = False


@dataclass(frozen=True, slots=True)
class TrackObservation:
    """Persistable object observation emitted for one frame."""

    id: str
    segment_id: str
    frame_index: int
    timestamp_seconds: float
    object_class: TrackedObjectClass
    local_track_id: str
    bounding_box: BoundingBox
    centroid: ImagePoint
    confidence: float
    visibility: VisibilityState
    occluded: bool
    provenance: ObservationProvenance
    mask: MaskReference | None = None

    def __post_init__(self) -> None:
        if self.frame_index < 0 or self.timestamp_seconds < 0:
            raise ValueError("Observation frame and timestamp cannot be negative")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Observation confidence must be between zero and one")
        if self.occluded != (self.visibility is VisibilityState.OCCLUDED):
            raise ValueError("Occlusion flag must agree with visibility")


@dataclass(frozen=True, slots=True)
class TrackingEvent:
    """Detected tracking-quality event."""

    kind: TrackingEventKind
    timestamp_seconds: float
    object_class: TrackedObjectClass
    local_track_id: str
    reason: str
    observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TrackingBatchResult:
    """Backend output for one frame batch."""

    observations: tuple[TrackObservation, ...]
    events: tuple[TrackingEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class TrackingMetrics:
    """Coverage and repair metrics for one stable segment."""

    expected_frames: int
    observed_frames: int
    reinitializations: int
    identity_switches: int
    lost_events: int
    occlusion_events: int

    @property
    def coverage(self) -> float:
        """Return bounded frame coverage."""

        if self.expected_frames == 0:
            return 0.0
        return min(1.0, self.observed_frames / self.expected_frames)


@dataclass(frozen=True, slots=True)
class TrackingSummary:
    """Complete segment result returned after backend shutdown."""

    session_id: str
    segment_id: str
    backend_name: str
    observations: int
    metrics: TrackingMetrics
