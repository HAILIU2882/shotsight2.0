"""Shot lifecycle states, evidence, confidence, and attempt candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from shotsight2.domain.persistence import JsonObject, JsonValue, ReviewStatus, ShotAttempt, ShotOutcome


class ShotLifecycleState(StrEnum):
    """State machine states for one released-shot lifecycle."""

    POSSESSED = "possessed"
    RELEASED = "released"
    FLIGHT = "flight"
    IMMEDIATE_BLOCK = "immediate_block"
    RIM_INTERACTION = "rim_interaction"
    AIR_BALL = "air_ball"
    UNCERTAIN = "uncertain"


class ShotLifecycleEventKind(StrEnum):
    """Timestamped lifecycle transitions and observations."""

    POSSESSION_ENTERED = "possession_entered"
    RELEASE_DETECTED = "release_detected"
    FREE_FLIGHT_OBSERVED = "free_flight_observed"
    IMMEDIATE_BLOCK_DETECTED = "immediate_block_detected"
    RIM_APPROACH_DETECTED = "rim_approach_detected"
    RIM_INTERACTION_DETECTED = "rim_interaction_detected"
    AIR_BALL_DETECTED = "air_ball_detected"
    UNCERTAINTY_TIMEOUT = "uncertainty_timeout"


class ShotLifecycleTerminal(StrEnum):
    """Lifecycle terminal types; make/miss classification is intentionally separate."""

    RIM_INTERACTION = "rim_interaction"
    AIR_BALL = "air_ball"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class ShotLifecycleEvidenceKind(StrEnum):
    """Reviewable evidence families emitted by lifecycle detection."""

    POSSESSION = "possession"
    RELEASE = "release"
    FLIGHT = "flight"
    RIM = "rim"
    BLOCK = "block"
    RESULT = "result"
    CALIBRATION = "calibration"


class IgnoredReleaseReason(StrEnum):
    """Why a possession exit did not become an automatic attempt."""

    NOT_SHOT_MOTION = "not_shot_motion"
    UNSTABLE_SEGMENT = "unstable_segment"
    INSUFFICIENT_POSSESSION = "insufficient_possession"


@dataclass(frozen=True, slots=True)
class ShotLifecycleEvidence:
    """Raw timestamped observation references behind a lifecycle decision."""

    kind: ShotLifecycleEvidenceKind
    timestamp_seconds: float
    observation_ids: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        if self.timestamp_seconds < 0:
            raise ValueError("Evidence timestamp cannot be negative")
        if not self.observation_ids:
            raise ValueError("Lifecycle evidence requires at least one reference")

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
class ShotLifecycleConfidence:
    """Confidence score with component scores preserved for review."""

    score: float
    release_score: float
    flight_score: float
    result_score: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (self.score, self.release_score, self.flight_score, self.result_score):
            if not 0 <= value <= 1:
                raise ValueError("Lifecycle confidence values must be between zero and one")
        if not self.reasons:
            raise ValueError("Lifecycle confidence requires at least one reason")

    def to_json(self) -> JsonObject:
        """Serialize confidence details for review."""

        return cast(
            JsonObject,
            {
                "score": self.score,
                "release_score": self.release_score,
                "flight_score": self.flight_score,
                "result_score": self.result_score,
                "reasons": list(self.reasons),
            },
        )


@dataclass(frozen=True, slots=True)
class ShotLifecycleEvent:
    """One transition in the lifecycle state machine."""

    kind: ShotLifecycleEventKind
    state: ShotLifecycleState
    timestamp_seconds: float
    evidence: ShotLifecycleEvidence

    def __post_init__(self) -> None:
        if self.timestamp_seconds < 0:
            raise ValueError("Lifecycle event timestamp cannot be negative")

    def to_json(self) -> JsonObject:
        """Serialize an event for attempt evidence."""

        return cast(
            JsonObject,
            {
                "kind": self.kind.value,
                "state": self.state.value,
                "timestamp_seconds": self.timestamp_seconds,
                "evidence": self.evidence.to_json(),
            },
        )


@dataclass(frozen=True, slots=True)
class ShotAttemptCandidate:
    """ShotAttempt-compatible automatic lifecycle result."""

    id: str
    analysis_run_id: str
    segment_id: str
    shooter_track_id: str | None
    release_seconds: float
    release_frame_index: int
    release_observation_id: str
    result_start_seconds: float
    result_end_seconds: float
    terminal: ShotLifecycleTerminal
    confidence: ShotLifecycleConfidence
    evidence: tuple[ShotLifecycleEvidence, ...]
    events: tuple[ShotLifecycleEvent, ...]

    def __post_init__(self) -> None:
        if self.release_seconds < 0 or self.result_start_seconds < 0 or self.result_end_seconds < 0:
            raise ValueError("Lifecycle timestamps cannot be negative")
        if self.result_end_seconds < self.result_start_seconds:
            raise ValueError("Result window must be ordered")
        if self.result_start_seconds < self.release_seconds:
            raise ValueError("Result window cannot start before release")
        if not self.evidence:
            raise ValueError("Shot lifecycle candidates require evidence")
        if not self.events:
            raise ValueError("Shot lifecycle candidates require events")

    def to_shot_attempt(self) -> ShotAttempt:
        """Return the persistence model owned by later pipeline stages."""

        return ShotAttempt(
            id=self.id,
            analysis_run_id=self.analysis_run_id,
            shooter_track_id=self.shooter_track_id,
            release_seconds=self.release_seconds,
            automatic_outcome=ShotOutcome.UNCERTAIN,
            shot_type="UNKNOWN",
            confidence=self.confidence.score,
            review_status=ReviewStatus.UNREVIEWED,
            evidence=self.to_evidence_json(),
        )

    def to_evidence_json(self) -> JsonObject:
        """Serialize complete lifecycle evidence without classifying make/miss."""

        payload: JsonObject = {
            "source": "shot_lifecycle",
            "segment_id": self.segment_id,
            "release_seconds": self.release_seconds,
            "release_frame_index": self.release_frame_index,
            "release_observation_id": self.release_observation_id,
            "result_window": cast(
                JsonValue,
                {"start_seconds": self.result_start_seconds, "end_seconds": self.result_end_seconds},
            ),
            "terminal": self.terminal.value,
            "automatic_outcome_deferred": True,
            "confidence": self.confidence.to_json(),
            "evidence": cast(JsonValue, [item.to_json() for item in self.evidence]),
            "events": cast(JsonValue, [item.to_json() for item in self.events]),
        }
        return payload


@dataclass(frozen=True, slots=True)
class IgnoredReleaseCandidate:
    """A detected possession exit that was intentionally not counted."""

    segment_id: str
    timestamp_seconds: float
    ball_observation_id: str
    shooter_track_id: str | None
    reason: IgnoredReleaseReason
    evidence_observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.timestamp_seconds < 0:
            raise ValueError("Ignored release timestamp cannot be negative")
        if not self.evidence_observation_ids:
            raise ValueError("Ignored releases require evidence")
