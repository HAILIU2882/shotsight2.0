"""Video-local player association and shot attribution models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AssociationDecision(StrEnum):
    """Deterministic decision state for possession and shooter attribution."""

    ASSOCIATED = "associated"
    AMBIGUOUS = "ambiguous"
    UNASSOCIATED = "unassociated"


class AssociationEvidenceKind(StrEnum):
    """Evidence families persisted for later review of shot attribution."""

    POSSESSION = "possession"
    SHOOTER = "shooter"


@dataclass(frozen=True, slots=True)
class AssociationConfidence:
    """Confidence score plus explicit ambiguity state."""

    score: float
    decision: AssociationDecision
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1:
            raise ValueError("Association confidence must be between zero and one")

    @property
    def ambiguous(self) -> bool:
        """Return whether the decision needs review."""

        return self.decision is AssociationDecision.AMBIGUOUS


@dataclass(frozen=True, slots=True)
class LocalPlayerIdentity:
    """Stable video-local player identity without biometric claims."""

    player_track_id: str
    analysis_run_id: str
    video_id: str
    local_label: str
    display_name: str
    confidence: AssociationConfidence
    source_local_track_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_local_track_ids:
            raise ValueError("A player identity needs at least one source local track")
        if not self.segment_ids:
            raise ValueError("A player identity needs at least one segment")


@dataclass(frozen=True, slots=True)
class PlayerObservationLink:
    """Link from one raw player observation to a video-local player identity."""

    observation_id: str
    segment_id: str
    frame_index: int
    timestamp_seconds: float
    source_local_track_id: str
    player_track_id: str
    confidence: AssociationConfidence


@dataclass(frozen=True, slots=True)
class PossessionCandidate:
    """Ball-to-player possession candidate for one timestamp."""

    player_track_id: str
    player_observation_id: str
    ball_observation_id: str
    timestamp_seconds: float
    distance_pixels: float
    normalized_distance: float
    confidence: AssociationConfidence


@dataclass(frozen=True, slots=True)
class PossessionFrame:
    """Best possession state at one ball observation."""

    timestamp_seconds: float
    ball_observation_id: str
    player_track_id: str | None
    candidates: tuple[PossessionCandidate, ...]
    confidence: AssociationConfidence
    carried: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseEvent:
    """Clean input from future shot lifecycle code."""

    id: str
    analysis_run_id: str
    segment_id: str
    frame_index: int
    timestamp_seconds: float
    ball_observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ShooterAttribution:
    """Shooter association for a release event."""

    release_event_id: str
    player_track_id: str | None
    confidence: AssociationConfidence
    evidence_observation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssociationEvidenceReference:
    """Persisted review reference for possession and shooter decisions."""

    id: str
    analysis_run_id: str
    shot_attempt_id: str
    kind: AssociationEvidenceKind
    player_track_id: str | None
    observation_ids: tuple[str, ...]
    confidence: float
    ambiguous: bool
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("Association evidence confidence must be between zero and one")
        if not self.observation_ids:
            raise ValueError("Association evidence needs at least one observation reference")
