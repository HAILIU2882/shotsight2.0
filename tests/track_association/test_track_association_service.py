"""Track association service rules."""

from __future__ import annotations

from shotsight2.domain import CameraSegment, ReleaseEvent
from shotsight2.domain.track_association import AssociationDecision
from shotsight2.domain.tracking import (
    BoundingBox,
    ObservationProvenance,
    TrackedObjectClass,
    TrackObservation,
    VisibilityState,
)
from shotsight2.services.track_association import TrackAssociationConfig, TrackAssociationService


def test_single_player_gets_deterministic_label_possession_and_shooter() -> None:
    service = TrackAssociationService()
    observations = (
        _player("p0", "segment-1", 0, 0.0, "backend-p1", 40, 40),
        _player("p1", "segment-1", 1, 0.1, "backend-p1", 42, 40),
        _ball("b1", "segment-1", 1, 0.1, 65, 55),
    )

    result = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=observations,
        release_events=(ReleaseEvent("release-1", "run-1", "segment-1", 1, 0.12, "b1"),),
    )

    assert [player.local_label for player in result.players] == ["Player 1"]
    assert result.players[0].display_name == "Player 1"
    assert result.possession_frames[-1].player_track_id == result.players[0].id
    assert result.shooter_attributions[0].player_track_id == result.players[0].id
    assert result.shooter_attributions[0].confidence.decision is AssociationDecision.ASSOCIATED

    repeated = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=tuple(reversed(observations)),
    )
    assert repeated.players[0].id == result.players[0].id


def test_multiple_players_and_handoff_change_possession_owner() -> None:
    service = TrackAssociationService()
    result = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=(
            _player("p1-f0", "segment-1", 0, 0.0, "left", 30, 40),
            _player("p2-f0", "segment-1", 0, 0.0, "right", 130, 40),
            _player("p1-f1", "segment-1", 1, 0.1, "left", 32, 40),
            _player("p2-f1", "segment-1", 1, 0.1, "right", 128, 40),
            _ball("b0", "segment-1", 0, 0.0, 55, 58),
            _ball("b1", "segment-1", 1, 0.1, 130, 58),
        ),
    )

    assert [player.local_label for player in result.players] == ["Player 1", "Player 2"]
    assert result.possession_frames[0].player_track_id == result.players[0].id
    assert result.possession_frames[1].player_track_id == result.players[1].id


def test_possession_is_carried_across_short_occlusion_gap() -> None:
    service = TrackAssociationService(config=TrackAssociationConfig(possession_gap_seconds=0.5))
    result = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=(
            _player("p0", "segment-1", 0, 0.0, "player", 30, 40),
            _player("p3", "segment-1", 3, 0.3, "player", 35, 40),
            _ball("b0", "segment-1", 0, 0.0, 55, 58),
            _ball("b2", "segment-1", 2, 0.2, 180, 20),
        ),
    )

    assert result.possession_frames[1].player_track_id == result.players[0].id
    assert result.possession_frames[1].carried is True


def test_crossing_players_keep_local_identity_links() -> None:
    service = TrackAssociationService()
    result = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=(
            _player("a0", "segment-1", 0, 0.0, "a", 40, 40),
            _player("b0", "segment-1", 0, 0.0, "b", 95, 40),
            _player("a1", "segment-1", 1, 0.1, "a", 70, 40),
            _player("b1", "segment-1", 1, 0.1, "b", 65, 40),
            _player("a2", "segment-1", 2, 0.2, "a", 100, 40),
            _player("b2", "segment-1", 2, 0.2, "b", 35, 40),
        ),
    )

    links_by_source = {
        link.source_local_track_id: link.player_track_id for link in result.observation_links if link.frame_index == 2
    }
    assert links_by_source["a"] != links_by_source["b"]
    assert links_by_source["a"] == next(
        link.player_track_id for link in result.observation_links if link.observation_id == "a0"
    )
    assert links_by_source["b"] == next(
        link.player_track_id for link in result.observation_links if link.observation_id == "b0"
    )


def test_compatible_tracks_link_across_camera_segments_without_cross_video_identity() -> None:
    service = TrackAssociationService()
    segments = (_segment("segment-1", "run-1", 0, 1), _segment("segment-2", "run-1", 1, 2))
    observations = (
        _player("p-old", "segment-1", 9, 0.9, "old-view-track", 50, 40),
        _player("p-new", "segment-2", 10, 1.1, "new-view-track", 54, 42),
    )

    result = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=segments,
        observations=observations,
    )
    other_video = service.associate(
        analysis_run_id="run-1",
        video_id="video-2",
        segments=segments,
        observations=observations,
    )

    assert len(result.players) == 1
    assert result.identities[0].source_local_track_ids == ("new-view-track", "old-view-track")
    assert result.players[0].id != other_video.players[0].id


def test_ambiguous_release_has_no_shooter_and_is_flagged() -> None:
    service = TrackAssociationService()
    result = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=(
            _player("left", "segment-1", 0, 0.0, "left", 30, 40),
            _player("right", "segment-1", 0, 0.0, "right", 92, 40),
            _ball("ball", "segment-1", 0, 0.0, 71, 55),
        ),
        release_events=(ReleaseEvent("release-1", "run-1", "segment-1", 0, 0.02, "ball"),),
    )

    assert result.possession_frames[0].confidence.decision is AssociationDecision.AMBIGUOUS
    assert result.shooter_attributions[0].player_track_id is None
    assert result.shooter_attributions[0].confidence.ambiguous is True


def test_shot_attribution_evidence_reference_is_deterministic() -> None:
    service = TrackAssociationService()
    attribution = service.associate(
        analysis_run_id="run-1",
        video_id="video-1",
        segments=(_segment("segment-1", "run-1", 0, 1),),
        observations=(
            _player("player", "segment-1", 0, 0.0, "player", 30, 40),
            _ball("ball", "segment-1", 0, 0.0, 55, 58),
        ),
        release_events=(ReleaseEvent("release-1", "run-1", "segment-1", 0, 0.02, "ball"),),
    ).shooter_attributions[0]

    first = service.evidence_reference_for_shot(
        shot_attempt_id="attempt-1",
        analysis_run_id="run-1",
        attribution=attribution,
    )
    second = service.evidence_reference_for_shot(
        shot_attempt_id="attempt-1",
        analysis_run_id="run-1",
        attribution=attribution,
    )

    assert first == second
    assert first.observation_ids == ("ball", "player")


def _segment(segment_id: str, run_id: str, start: float, end: float) -> CameraSegment:
    return CameraSegment(segment_id, run_id, start, end, "STABLE", 1.0)


def _player(
    observation_id: str,
    segment_id: str,
    frame_index: int,
    timestamp: float,
    local_track_id: str,
    x: float,
    y: float,
) -> TrackObservation:
    box = BoundingBox(x, y, 28, 72)
    return TrackObservation(
        observation_id,
        segment_id,
        frame_index,
        timestamp,
        TrackedObjectClass.PLAYER,
        local_track_id,
        box,
        box.centroid,
        0.9,
        VisibilityState.VISIBLE,
        False,
        ObservationProvenance("test", "1", "synthetic", "session"),
    )


def _ball(
    observation_id: str,
    segment_id: str,
    frame_index: int,
    timestamp: float,
    x: float,
    y: float,
) -> TrackObservation:
    box = BoundingBox(x, y, 8, 8)
    return TrackObservation(
        observation_id,
        segment_id,
        frame_index,
        timestamp,
        TrackedObjectClass.BASKETBALL,
        "ball",
        box,
        box.centroid,
        0.88,
        VisibilityState.VISIBLE,
        False,
        ObservationProvenance("test", "1", "synthetic", "session"),
    )
