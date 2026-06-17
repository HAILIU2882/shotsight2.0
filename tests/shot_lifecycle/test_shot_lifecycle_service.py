"""Shot lifecycle state-machine tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from shotsight2.domain import (
    AssociationConfidence,
    AssociationDecision,
    Calibration,
    CameraSegment,
    PossessionCandidate,
    PossessionFrame,
    ShotLifecycleTerminal,
    ShotOutcome,
)
from shotsight2.domain.tracking import (
    BoundingBox,
    ObservationProvenance,
    TrackedObjectClass,
    TrackObservation,
    VisibilityState,
)
from shotsight2.services.shot_lifecycle import ShotLifecycleResult, ShotLifecycleService, rim_geometry

NOW = datetime(2026, 6, 18, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "points"),
    [
        ("jump shot", ((100, 118), (100, 112), (100, 96), (100, 70), (100, 48), (100, 34))),
        ("layup", ((76, 92), (82, 84), (90, 66), (96, 52), (100, 42), (101, 36))),
        ("dunk", ((100, 60), (100, 55), (100, 49), (100, 43), (100, 38))),
        ("hook", ((58, 102), (62, 98), (72, 82), (84, 62), (96, 44), (102, 36))),
        ("free throw", ((100, 142), (100, 134), (100, 112), (100, 82), (100, 52), (100, 34))),
    ],
)
def test_released_shot_styles_close_at_rim_interaction(name: str, points: tuple[tuple[float, float], ...]) -> None:
    del name
    result = _detect(points)

    assert len(result.attempts) == 1
    attempt = result.attempts[0]
    candidate = result.candidates[0]
    assert candidate.terminal is ShotLifecycleTerminal.RIM_INTERACTION
    assert attempt.automatic_outcome is ShotOutcome.UNCERTAIN
    assert attempt.shot_type == "UNKNOWN"
    assert attempt.release_seconds == 0.4
    assert attempt.evidence["terminal"] == "rim_interaction"
    assert attempt.evidence["automatic_outcome_deferred"] is True
    assert isinstance(attempt.evidence["result_window"], dict)
    assert attempt.confidence > 0.6


def test_immediate_block_counts_only_after_valid_release() -> None:
    result = _detect(
        ((100, 118), (100, 112), (100, 96), (100, 78), (102, 82)),
        block_indices={3},
    )

    assert len(result.attempts) == 1
    assert result.candidates[0].terminal is ShotLifecycleTerminal.BLOCKED
    assert result.attempts[0].evidence["terminal"] == "blocked"


def test_air_ball_completes_away_from_rim_without_make_miss_classification() -> None:
    result = _detect(((136, 118), (138, 110), (144, 92), (152, 72), (166, 64), (180, 92)))

    assert len(result.attempts) == 1
    assert result.candidates[0].terminal is ShotLifecycleTerminal.AIR_BALL
    assert result.attempts[0].automatic_outcome is ShotOutcome.UNCERTAIN


def test_pass_is_rejected_because_the_ball_separates_without_shot_flight() -> None:
    result = _detect(((58, 100), (62, 100), (88, 100), (120, 100), (152, 100)))

    assert result.attempts == ()
    assert len(result.ignored_releases) == 1
    assert result.ignored_releases[0].reason.value == "not_shot_motion"


def test_pump_fake_does_not_create_release_candidate() -> None:
    observations = _balls(((100, 118), (100, 108), (100, 96), (100, 110)))
    possession = tuple(_possession_frame(ball, "player-1") for ball in observations)

    result = ShotLifecycleService().detect(
        analysis_run_id="run-1",
        segments=(_segment(),),
        observations=observations,
        possession_frames=possession,
        calibrations=(_calibration(),),
    )

    assert result.attempts == ()
    assert result.ignored_releases == ()


def test_incomplete_shot_track_closes_as_bounded_uncertainty() -> None:
    result = _detect(((100, 118), (100, 112), (100, 96), (100, 76)), calibrations=())

    assert len(result.attempts) == 1
    assert result.candidates[0].terminal is ShotLifecycleTerminal.UNCERTAIN
    assert result.attempts[0].evidence["terminal"] == "uncertain"


def test_repeated_rim_observations_do_not_duplicate_one_release_lifecycle() -> None:
    result = _detect(((100, 118), (100, 112), (100, 96), (100, 58), (100, 36), (101, 34), (102, 35)))

    assert len(result.attempts) == 1
    assert len(result.candidates) == 1


def test_lifecycle_does_not_cross_unstable_camera_range() -> None:
    observations = _balls(((100, 118), (100, 112), (100, 96), (100, 70), (100, 34)), segment_id="unstable-1")
    result = ShotLifecycleService().detect(
        analysis_run_id="run-1",
        segments=(CameraSegment("unstable-1", "run-1", 0, 2, "UNSTABLE", 0.2),),
        observations=observations,
        possession_frames=_possession(observations),
        calibrations=(_calibration(segment_id="unstable-1"),),
    )

    assert result.attempts == ()


def _detect(
    points: Sequence[tuple[float, float]],
    *,
    block_indices: set[int] | None = None,
    calibrations: Sequence[Calibration] | None = None,
) -> ShotLifecycleResult:
    observations = _balls(points)
    return ShotLifecycleService().detect(
        analysis_run_id="run-1",
        segments=(_segment(),),
        observations=observations,
        possession_frames=_possession(observations, block_indices=block_indices or set()),
        calibrations=tuple(calibrations) if calibrations is not None else (_calibration(),),
    )


def _segment(segment_id: str = "segment-1") -> CameraSegment:
    return CameraSegment(segment_id, "run-1", 0, 5, "STABLE", 0.98)


def _calibration(segment_id: str = "segment-1") -> Calibration:
    return Calibration(
        "calibration-1",
        segment_id,
        "AUTOMATIC",
        rim_geometry(100, 34, 8, 5, 0.92).to_json(),
        {"points": {}, "validity": "INDICATIVE", "confidence_reasons": []},
        0.92,
        True,
        NOW,
    )


def _balls(points: Sequence[tuple[float, float]], *, segment_id: str = "segment-1") -> tuple[TrackObservation, ...]:
    return tuple(_ball(index, point[0], point[1], segment_id=segment_id) for index, point in enumerate(points))


def _ball(index: int, x: float, y: float, *, segment_id: str) -> TrackObservation:
    box = BoundingBox(x - 4, y - 4, 8, 8)
    return TrackObservation(
        f"ball-{index}",
        segment_id,
        index,
        index * 0.2,
        TrackedObjectClass.BASKETBALL,
        "ball-track",
        box,
        box.centroid,
        0.9,
        VisibilityState.VISIBLE,
        False,
        ObservationProvenance("test", "1", "synthetic", "session"),
    )


def _possession(
    observations: Sequence[TrackObservation],
    *,
    block_indices: set[int] | None = None,
) -> tuple[PossessionFrame, ...]:
    blocked = block_indices or set()
    frames: list[PossessionFrame] = []
    for index, ball in enumerate(observations):
        if index < 2:
            frames.append(_possession_frame(ball, "player-1"))
        elif index in blocked:
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
