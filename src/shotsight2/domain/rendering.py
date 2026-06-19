"""Artifact rendering configuration, overlay primitives, and localization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from shotsight2.domain.persistence import JsonObject, JsonValue, ShotOutcome
from shotsight2.domain.tracking import BoundingBox, ImagePoint, TrackedObjectClass, VisibilityState

RENDERING_SCHEMA_VERSION = "artifact-rendering-v1"


class RenderArtifactKind(StrEnum):
    """Published artifact categories produced by the rendering module."""

    REPLAY = "REPLAY"
    ANNOTATED_VIDEO = "ANNOTATED_VIDEO"
    SHOT_CHART_DATA = "SHOT_CHART_DATA"
    SHOT_CHART_SVG = "SHOT_CHART_SVG"
    HEATMAP_DATA = "HEATMAP_DATA"
    HEATMAP_SVG = "HEATMAP_SVG"
    RENDER_METADATA = "RENDER_METADATA"


class OverlayLocale(StrEnum):
    """Supported overlay label locales."""

    ENGLISH = "en"
    CHINESE = "zh"


class OverlayState(StrEnum):
    """Visual confidence states that must remain distinguishable."""

    CERTAIN = "certain"
    UNCERTAIN = "uncertain"
    OCCLUDED = "occluded"
    TRACKING_LOST = "tracking_lost"


class OverlayLabelKey(StrEnum):
    """Stable localization keys used by generated artifacts."""

    BALL = "ball"
    RIM = "rim"
    CONFIDENCE = "confidence"
    RELEASE = "release"
    MADE = "made"
    MISSED = "missed"
    UNCERTAIN = "uncertain"
    OCCLUDED = "occluded"
    TRACKING_LOST = "tracking_lost"
    PLAYER = "player"
    INDICATIVE = "indicative"


_LABELS: dict[OverlayLocale, dict[OverlayLabelKey, str]] = {
    OverlayLocale.ENGLISH: {
        OverlayLabelKey.BALL: "Ball",
        OverlayLabelKey.RIM: "Rim",
        OverlayLabelKey.CONFIDENCE: "Confidence",
        OverlayLabelKey.RELEASE: "Release",
        OverlayLabelKey.MADE: "Made",
        OverlayLabelKey.MISSED: "Missed",
        OverlayLabelKey.UNCERTAIN: "Uncertain",
        OverlayLabelKey.OCCLUDED: "Occluded",
        OverlayLabelKey.TRACKING_LOST: "Tracking lost",
        OverlayLabelKey.PLAYER: "Player",
        OverlayLabelKey.INDICATIVE: "Indicative",
    },
    OverlayLocale.CHINESE: {
        OverlayLabelKey.BALL: "篮球",
        OverlayLabelKey.RIM: "篮筐",
        OverlayLabelKey.CONFIDENCE: "置信度",
        OverlayLabelKey.RELEASE: "出手",
        OverlayLabelKey.MADE: "命中",
        OverlayLabelKey.MISSED: "未中",
        OverlayLabelKey.UNCERTAIN: "不确定",
        OverlayLabelKey.OCCLUDED: "遮挡",
        OverlayLabelKey.TRACKING_LOST: "跟踪丢失",
        OverlayLabelKey.PLAYER: "球员",
        OverlayLabelKey.INDICATIVE: "示意",
    },
}


@dataclass(frozen=True, slots=True)
class RenderConfiguration:
    """Reproducible settings for all generated rendering artifacts."""

    locale: OverlayLocale = OverlayLocale.ENGLISH
    replay_lead_seconds: float = 3.0
    replay_trail_seconds: float = 3.0
    overlay_frames_per_second: float = 10.0
    chart_width: int = 470
    chart_height: int = 500
    heatmap_columns: int = 12
    heatmap_rows: int = 10
    trajectory_seconds: float = 1.25
    observation_tolerance_seconds: float = 0.08
    low_confidence_threshold: float = 0.50
    video_codec: str = "h264"
    schema_version: str = RENDERING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.replay_lead_seconds < 0 or self.replay_trail_seconds < 0:
            raise ValueError("Replay padding cannot be negative")
        if self.replay_lead_seconds == 0 and self.replay_trail_seconds == 0:
            raise ValueError("Replay windows must include positive duration")
        if self.overlay_frames_per_second <= 0 or self.trajectory_seconds < 0:
            raise ValueError("Overlay frame rate must be positive and trajectory duration cannot be negative")
        if self.chart_width <= 0 or self.chart_height <= 0:
            raise ValueError("Chart dimensions must be positive")
        if self.heatmap_columns <= 0 or self.heatmap_rows <= 0:
            raise ValueError("Heatmap dimensions must be positive")
        if self.observation_tolerance_seconds < 0:
            raise ValueError("Observation tolerance cannot be negative")
        if not 0 <= self.low_confidence_threshold <= 1:
            raise ValueError("Low-confidence threshold must be between zero and one")

    @property
    def version_identifier(self) -> str:
        """Return a stable version string that changes with rendering config."""

        payload = json.dumps(self.to_json(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self.schema_version}-{digest}"

    def to_json(self) -> JsonObject:
        """Serialize settings for metadata artifacts and version hashing."""

        return cast(
            JsonObject,
            {
                "schema_version": self.schema_version,
                "locale": self.locale.value,
                "replay_lead_seconds": self.replay_lead_seconds,
                "replay_trail_seconds": self.replay_trail_seconds,
                "overlay_frames_per_second": self.overlay_frames_per_second,
                "chart_width": self.chart_width,
                "chart_height": self.chart_height,
                "heatmap_columns": self.heatmap_columns,
                "heatmap_rows": self.heatmap_rows,
                "trajectory_seconds": self.trajectory_seconds,
                "observation_tolerance_seconds": self.observation_tolerance_seconds,
                "low_confidence_threshold": self.low_confidence_threshold,
                "video_codec": self.video_codec,
            },
        )


@dataclass(frozen=True, slots=True)
class ReplayWindow:
    """Bounded replay source range for one shot attempt."""

    attempt_id: str
    requested_start_seconds: float
    requested_end_seconds: float
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class OverlayObject:
    """A rendered tracked object annotation."""

    object_class: TrackedObjectClass
    track_id: str
    label: str
    box: BoundingBox
    centroid: ImagePoint
    confidence: float
    state: OverlayState


@dataclass(frozen=True, slots=True)
class OverlayTrajectory:
    """Recent ball path rendered as connected image points."""

    points: tuple[ImagePoint, ...]
    state: OverlayState


@dataclass(frozen=True, slots=True)
class OverlayEvent:
    """A timestamped event label rendered on top of video/chart context."""

    timestamp_seconds: float
    label: str
    state: OverlayState


@dataclass(frozen=True, slots=True)
class OverlayFrame:
    """Complete deterministic overlay description for one video timestamp."""

    timestamp_seconds: float
    width: int
    height: int
    objects: tuple[OverlayObject, ...]
    trajectory: OverlayTrajectory | None = None
    events: tuple[OverlayEvent, ...] = ()


def localized_label(key: OverlayLabelKey, locale: OverlayLocale) -> str:
    """Return a localized overlay label."""

    return _LABELS[locale][key]


def outcome_label(outcome: ShotOutcome, locale: OverlayLocale) -> str:
    """Return a localized make/miss/uncertain outcome label."""

    key = {
        ShotOutcome.MADE: OverlayLabelKey.MADE,
        ShotOutcome.MISSED: OverlayLabelKey.MISSED,
        ShotOutcome.UNCERTAIN: OverlayLabelKey.UNCERTAIN,
    }[outcome]
    return localized_label(key, locale)


def overlay_state(
    visibility: VisibilityState,
    confidence: float,
    *,
    low_confidence_threshold: float,
) -> OverlayState:
    """Map tracking visibility and confidence onto distinct visual states."""

    if visibility is VisibilityState.LOST:
        return OverlayState.TRACKING_LOST
    if visibility is VisibilityState.OCCLUDED:
        return OverlayState.OCCLUDED
    if confidence < low_confidence_threshold or visibility is VisibilityState.PARTIAL:
        return OverlayState.UNCERTAIN
    return OverlayState.CERTAIN


def replay_window(
    attempt_id: str,
    release_seconds: float,
    source_duration_seconds: float,
    config: RenderConfiguration,
) -> ReplayWindow:
    """Build a replay window clamped to the source media duration."""

    if release_seconds < 0:
        raise ValueError("Release timestamp cannot be negative")
    if source_duration_seconds <= 0:
        raise ValueError("Source duration must be positive")
    requested_start = release_seconds - config.replay_lead_seconds
    requested_end = release_seconds + config.replay_trail_seconds
    start = max(0.0, requested_start)
    end = min(source_duration_seconds, requested_end)
    if end <= start:
        raise ValueError("Replay window does not overlap the source duration")
    return ReplayWindow(
        attempt_id=attempt_id,
        requested_start_seconds=requested_start,
        requested_end_seconds=requested_end,
        start_seconds=start,
        end_seconds=end,
    )


def json_bytes(payload: JsonValue) -> bytes:
    """Serialize JSON artifacts deterministically."""

    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
