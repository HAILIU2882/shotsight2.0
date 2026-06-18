"""Outcome classification models, evidence, and confidence details."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import hypot
from typing import cast

from shotsight2.domain.persistence import JsonObject, JsonValue, ShotOutcome


class OutcomeEvidenceKind(StrEnum):
    """Evidence families used to explain automatic outcome decisions."""

    RIM_VOLUME = "rim_volume"
    DOWNWARD_ENTRY = "downward_entry"
    BELOW_RIM_CONTINUATION = "below_rim_continuation"
    RIM_EXIT = "rim_exit"
    BLOCKED_SHOT = "blocked_shot"
    AIR_BALL = "air_ball"
    OCCLUSION = "occlusion"
    TRACKING_LOSS = "tracking_loss"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RimVolumeSource(StrEnum):
    """Source of image-space rim-crossing geometry."""

    CALIBRATION = "calibration"


@dataclass(frozen=True, slots=True)
class OutcomeEvidence:
    """Reviewable evidence behind one automatic outcome classification."""

    kind: OutcomeEvidenceKind
    timestamp_seconds: float
    observation_ids: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        if self.timestamp_seconds < 0:
            raise ValueError("Outcome evidence timestamp cannot be negative")
        if not self.observation_ids:
            raise ValueError("Outcome evidence requires at least one reference")

    def to_json(self) -> JsonObject:
        """Serialize evidence for ShotAttempt.evidence."""

        return cast(
            JsonObject,
            {
                "kind": self.kind.value,
                "timestamp_seconds": self.timestamp_seconds,
                "observation_ids": list(self.observation_ids),
                "description": self.description,
            },
        )


@dataclass(frozen=True, slots=True)
class OutcomeConfidence:
    """Outcome confidence with component scores preserved for review."""

    score: float
    crossing_score: float
    continuation_score: float
    visibility_score: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (self.score, self.crossing_score, self.continuation_score, self.visibility_score):
            if not 0 <= value <= 1:
                raise ValueError("Outcome confidence values must be between zero and one")
        if not self.reasons:
            raise ValueError("Outcome confidence requires at least one reason")

    def to_json(self) -> JsonObject:
        """Serialize confidence details for review and evaluation."""

        return cast(
            JsonObject,
            {
                "score": self.score,
                "crossing_score": self.crossing_score,
                "continuation_score": self.continuation_score,
                "visibility_score": self.visibility_score,
                "reasons": list(self.reasons),
            },
        )


@dataclass(frozen=True, slots=True)
class RimCrossingVolume:
    """Image-space rim volume used for conservative make detection."""

    segment_id: str
    center_x: float
    center_y: float
    radius_x: float
    radius_y: float
    confidence: float
    evidence_id: str
    source: RimVolumeSource = RimVolumeSource.CALIBRATION

    def __post_init__(self) -> None:
        if self.radius_x <= 0 or self.radius_y <= 0:
            raise ValueError("Rim crossing radii must be positive")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Rim volume confidence must be between zero and one")

    def normalized_distance(self, x: float, y: float) -> float:
        """Return elliptical distance where values up to one are inside the rim volume."""

        dx = (x - self.center_x) / self.radius_x
        dy = (y - self.center_y) / self.radius_y
        return hypot(dx, dy)

    def contains(self, x: float, y: float) -> bool:
        """Return whether a point lies inside the calibrated rim volume."""

        return self.normalized_distance(x, y) <= 1.0

    def below_rim(self, x: float, y: float, *, margin_pixels: float, horizontal_multiplier: float) -> bool:
        """Return whether a point continues below the rim opening."""

        return (
            y >= self.center_y + self.radius_y + margin_pixels
            and abs(x - self.center_x) <= self.radius_x * horizontal_multiplier
        )

    def to_json(self) -> JsonObject:
        """Serialize the rim crossing volume used for classification."""

        return cast(
            JsonObject,
            {
                "segment_id": self.segment_id,
                "center": {"x": self.center_x, "y": self.center_y},
                "radius_x": self.radius_x,
                "radius_y": self.radius_y,
                "confidence": self.confidence,
                "evidence_id": self.evidence_id,
                "source": self.source.value,
            },
        )


@dataclass(frozen=True, slots=True)
class OutcomeClassification:
    """Automatic outcome plus its evidence and confidence."""

    outcome: ShotOutcome
    confidence: OutcomeConfidence
    evidence: tuple[OutcomeEvidence, ...]
    rim_volume: RimCrossingVolume | None

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("Outcome classifications require evidence")

    def to_json(self) -> JsonObject:
        """Serialize classification details for persisted attempt evidence."""

        payload: JsonObject = {
            "source": "outcome_classification",
            "automatic_outcome": self.outcome.value,
            "confidence": self.confidence.to_json(),
            "evidence": cast(JsonValue, [item.to_json() for item in self.evidence]),
        }
        if self.rim_volume is not None:
            payload["rim_volume"] = self.rim_volume.to_json()
        return payload
