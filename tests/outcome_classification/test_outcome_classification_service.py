"""Outcome classification tests over deterministic lifecycle candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from shotsight2.domain import (
    AssociationConfidence,
    AssociationDecision,
    Calibration,
    CameraSegment,
    EffectiveShotAttempt,
    OutcomeEvidenceKind,
    PossessionCandidate,
    PossessionFrame,
    ReviewCorrection,
    ReviewStatus,
    ShotAttempt,
    ShotLifecycleTerminal,
    ShotLocation,
    ShotOutcome,
)
from shotsight2.domain.tracking import (
    BoundingBox,
    ObservationProvenance,
    TrackedObjectClass,
    TrackObservation,
    VisibilityState,
)
from shotsight2.services import OutcomeClassificationService, ShotLifecycleService, rim_geometry

NOW = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "points"),
    [
        (
            "swish",
            ((100, 150), (100, 140), (100, 130), (100, 80), (100, 94), (100, 100), (100, 108)),
        ),
        (
            "rim make",
            ((98, 150), (98, 140), (98, 130), (100, 82), (94, 94), (108, 94), (100, 98), (100, 108)),
        ),
        (
            "backboard make",
            ((96, 150), (96, 140), (96, 130), (110, 82), (118, 84), (108, 92), (100, 99), (100, 108)),
        ),
    ],
)
def test_makes_require_downward_rim_entry_and_below_rim_continuation(
    name: str,
    points: tuple[tuple[float, float], ...],
) -> None:
    del name
    result = _classify(points)

    assert result.attempts[0].automatic_outcome is ShotOutcome.MADE
    assert result.attempts[0].confidence > 0.7
    evidence = _outcome_evidence_kinds(result.attempts[0])
    assert OutcomeEvidenceKind.DOWNWARD_ENTRY.value in evidence
    assert OutcomeEvidenceKind.BELOW_RIM_CONTINUATION.value in evidence


@pytest.mark.parametrize(
    ("name", "points"),
    [
        (
            "rim miss",
            ((100, 150), (100, 140), (100, 130), (100, 80), (94, 94), (88, 90), (76, 88), (66, 92)),
        ),
        (
            "backboard miss",
            ((100, 150), (100, 140), (100, 130), (108, 82), (118, 84), (116, 96), (130, 94)),
        ),
    ],
)
def test_visible_non_crossing_rim_interactions_are_misses(
    name: str,
    points: tuple[tuple[float, float], ...],
) -> None:
    del name
    result = _classify(points)

    assert result.attempts[0].automatic_outcome is ShotOutcome.MISSED
    assert result.attempts[0].confidence > 0.5
    assert OutcomeEvidenceKind.RIM_EXIT.value in _outcome_evidence_kinds(result.attempts[0])


def test_air_ball_classifies_as_miss() -> None:
    result = _classify(((136, 150), (138, 140), (144, 128), (154, 110), (170, 106), (190, 132)))

    assert result.lifecycle_terminal is ShotLifecycleTerminal.AIR_BALL
    assert result.attempts[0].automatic_outcome is ShotOutcome.MISSED
    assert OutcomeEvidenceKind.AIR_BALL.value in _outcome_evidence_kinds(result.attempts[0])


def test_completed_blocked_shot_classifies_as_miss() -> None:
    result = _classify(
        ((100, 150), (100, 140), (100, 130), (100, 116), (102, 118)),
        block_indices={3},
    )

    assert result.lifecycle_terminal is ShotLifecycleTerminal.BLOCKED
    assert result.attempts[0].automatic_outcome is ShotOutcome.MISSED
    assert OutcomeEvidenceKind.BLOCKED_SHOT.value in _outcome_evidence_kinds(result.attempts[0])


def test_occluded_rim_crossing_evidence_is_uncertain_not_forced() -> None:
    result = _classify(
        ((100, 150), (100, 140), (100, 130), (100, 80), (100, 94), (100, 100), (100, 108)),
        occluded_indices={5},
    )

    assert result.attempts[0].automatic_outcome is ShotOutcome.UNCERTAIN
    assert result.attempts[0].confidence <= 0.49
    assert OutcomeEvidenceKind.OCCLUSION.value in _outcome_evidence_kinds(result.attempts[0])


def test_tracking_loss_around_required_rim_evidence_is_uncertain_not_forced() -> None:
    result = _classify(
        ((100, 150), (100, 140), (100, 130), (100, 80), (100, 94), (100, 100), (100, 108)),
        timestamps=(0.0, 0.2, 0.4, 0.6, 1.1, 1.3, 1.5),
    )

    assert result.attempts[0].automatic_outcome is ShotOutcome.UNCERTAIN
    assert result.attempts[0].confidence <= 0.49
    assert OutcomeEvidenceKind.TRACKING_LOSS.value in _outcome_evidence_kinds(result.attempts[0])


def test_missing_calibrated_rim_volume_is_uncertain() -> None:
    result = _classify(
        ((100, 150), (100, 140), (100, 130), (100, 80), (100, 94), (100, 100), (100, 108)),
        calibrations=(),
    )

    assert result.attempts[0].automatic_outcome is ShotOutcome.UNCERTAIN
    assert result.attempts[0].confidence <= 0.49
    assert OutcomeEvidenceKind.INSUFFICIENT_EVIDENCE.value in _outcome_evidence_kinds(result.attempts[0])


def test_review_override_preserves_automatic_outcome_and_confidence_independently() -> None:
    automatic = _classify(
        ((100, 150), (100, 140), (100, 130), (100, 80), (94, 94), (88, 90), (76, 88), (66, 92))
    ).attempts[0]
    correction = ReviewCorrection("correction-1", automatic.id, "outcome", "MISSED", "MADE", NOW)

    effective = _effective_with_latest_correction(automatic, (correction,))

    assert automatic.automatic_outcome is ShotOutcome.MISSED
    assert automatic.confidence > 0.5
    assert effective.automatic.automatic_outcome is ShotOutcome.MISSED
    assert effective.automatic.confidence == automatic.confidence
    assert effective.outcome is ShotOutcome.MADE
    assert effective.review_status is ReviewStatus.REVIEWED


def _classify(
    points: Sequence[tuple[float, float]],
    *,
    block_indices: set[int] | None = None,
    occluded_indices: set[int] | None = None,
    timestamps: Sequence[float] | None = None,
    calibrations: Sequence[Calibration] | None = None,
) -> _ClassifiedScenario:
    observations = _balls(points, occluded_indices=occluded_indices or set(), timestamps=timestamps)
    lifecycle = ShotLifecycleService().detect(
        analysis_run_id="run-1",
        segments=(_segment(),),
        observations=observations,
        possession_frames=_possession(observations, block_indices=block_indices or set()),
        calibrations=(_calibration(),),
    )
    assert len(lifecycle.candidates) == 1
    result = OutcomeClassificationService().classify(
        candidates=lifecycle.candidates,
        observations=observations,
        calibrations=tuple(calibrations) if calibrations is not None else (_calibration(),),
    )
    return _ClassifiedScenario(lifecycle.candidates[0].terminal, result.attempts)


def _segment() -> CameraSegment:
    return CameraSegment("segment-1", "run-1", 0, 5, "STABLE", 0.98)


def _calibration() -> Calibration:
    return Calibration(
        "calibration-1",
        "segment-1",
        "AUTOMATIC",
        rim_geometry(100, 100, 10, 5, 0.92).to_json(),
        {"points": {}, "validity": "INDICATIVE", "confidence_reasons": []},
        0.92,
        True,
        NOW,
    )


def _balls(
    points: Sequence[tuple[float, float]],
    *,
    occluded_indices: set[int],
    timestamps: Sequence[float] | None = None,
) -> tuple[TrackObservation, ...]:
    if timestamps is not None and len(timestamps) != len(points):
        raise ValueError("timestamps must match points")
    return tuple(
        _ball(
            index,
            point[0],
            point[1],
            timestamp=index * 0.2 if timestamps is None else timestamps[index],
            visibility=VisibilityState.OCCLUDED if index in occluded_indices else VisibilityState.VISIBLE,
        )
        for index, point in enumerate(points)
    )


def _ball(
    index: int,
    x: float,
    y: float,
    *,
    timestamp: float,
    visibility: VisibilityState,
) -> TrackObservation:
    box = BoundingBox(x - 4, y - 4, 8, 8)
    return TrackObservation(
        f"ball-{index}",
        "segment-1",
        index,
        timestamp,
        TrackedObjectClass.BASKETBALL,
        "ball-track",
        box,
        box.centroid,
        0.9,
        visibility,
        visibility is VisibilityState.OCCLUDED,
        ObservationProvenance("test", "1", "synthetic", "session"),
    )


def _possession(
    observations: Sequence[TrackObservation],
    *,
    block_indices: set[int],
) -> tuple[PossessionFrame, ...]:
    frames: list[PossessionFrame] = []
    for index, ball in enumerate(observations):
        if index < 2:
            frames.append(_possession_frame(ball, "player-1"))
        elif index in block_indices:
            frames.append(_possession_frame(ball, "player-2", candidate_player_id="player-2"))
        else:
            frames.append(_possession_frame(ball, None))
    return tuple(frames)


def _possession_frame(
    ball: TrackObservation,
    player_track_id: str | None,
    *,
    candidate_player_id: str | None = None,
) -> PossessionFrame:
    candidates: tuple[PossessionCandidate, ...]
    if candidate_player_id is None:
        candidates = ()
    else:
        candidates = (
            PossessionCandidate(
                candidate_player_id,
                f"{candidate_player_id}-observation",
                ball.id,
                ball.timestamp_seconds,
                2.0,
                0.05,
                AssociationConfidence(0.9, AssociationDecision.ASSOCIATED, "Synthetic proximity."),
            ),
        )
    decision = AssociationDecision.ASSOCIATED if player_track_id is not None else AssociationDecision.UNASSOCIATED
    confidence = AssociationConfidence(0.9 if player_track_id is not None else 0, decision, "Synthetic possession.")
    return PossessionFrame(
        ball.timestamp_seconds,
        ball.id,
        player_track_id,
        candidates,
        confidence,
    )


def _outcome_evidence_kinds(attempt: ShotAttempt) -> tuple[str, ...]:
    classification = attempt.evidence["outcome_classification"]
    assert isinstance(classification, dict)
    evidence = classification["evidence"]
    assert isinstance(evidence, list)
    return tuple(str(item["kind"]) for item in evidence if isinstance(item, dict))


def _effective_with_latest_correction(
    automatic: ShotAttempt,
    corrections: Sequence[ReviewCorrection],
) -> EffectiveShotAttempt:
    latest = {correction.field: correction.corrected_value for correction in corrections}
    outcome = latest.get("outcome", automatic.automatic_outcome.value)
    assert isinstance(outcome, str)
    return EffectiveShotAttempt(
        automatic=automatic,
        shooter_track_id=automatic.shooter_track_id,
        outcome=ShotOutcome(outcome),
        shot_type=automatic.shot_type,
        review_status=ReviewStatus.REVIEWED if corrections else automatic.review_status,
        location=ShotLocation("location-1", automatic.id, None, None, 0.5, 0.5, "UNKNOWN", True),
        removed=False,
    )


@dataclass(frozen=True, slots=True)
class _ClassifiedScenario:
    lifecycle_terminal: ShotLifecycleTerminal
    attempts: tuple[ShotAttempt, ...]
