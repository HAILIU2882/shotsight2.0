"""Contract tests for SQLite repository families."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteAssociationEvidenceRepository,
    SQLiteBallTrackRepository,
    SQLiteCalibrationRepository,
    SQLiteCameraSegmentRepository,
    SQLiteDatabase,
    SQLiteJobRepository,
    SQLitePlayerTrackRepository,
    SQLiteReviewCorrectionRepository,
    SQLiteShotAttemptRepository,
    SQLiteShotLocationRepository,
    SQLiteVideoRepository,
)
from shotsight2.domain import (
    AnalysisJob,
    AnalysisRun,
    AnalysisStage,
    Artifact,
    AssociationEvidenceKind,
    AssociationEvidenceReference,
    BallTrack,
    Calibration,
    CameraSegment,
    JobStatus,
    PlayerTrack,
    ReviewCorrection,
    ReviewStatus,
    RunStatus,
    ShotAttempt,
    ShotLocation,
    ShotOutcome,
    Video,
    VideoStatus,
)
from tests.persistence.conftest import NOW


def seed_run(database: SQLiteDatabase, video: Video, run: AnalysisRun) -> None:
    """Insert aggregate roots required by child repositories."""
    SQLiteVideoRepository(database).create(video)
    SQLiteAnalysisRunRepository(database).create(run)


def segment(run_id: str = "run-1") -> CameraSegment:
    """Create one stable camera segment."""
    return CameraSegment("segment-1", run_id, 1.0, 180.0, "STABLE", 0.97)


def player(run_id: str = "run-1", video_id: str = "video-1") -> PlayerTrack:
    """Create one video-local player track."""
    return PlayerTrack("player-1", run_id, video_id, "Player 1", "Player 1", 0.91)


def attempt(run_id: str = "run-1", attempt_id: str = "attempt-1") -> ShotAttempt:
    """Create one automatic shot attempt."""
    return ShotAttempt(
        attempt_id,
        run_id,
        "player-1",
        12.5,
        ShotOutcome.MISSED,
        "THREE_POINT",
        0.72,
        ReviewStatus.UNREVIEWED,
        {"release_frame": 150},
    )


def location(attempt_id: str = "attempt-1") -> ShotLocation:
    """Create one calibrated location."""
    return ShotLocation(
        f"location-{attempt_id}",
        attempt_id,
        7.1,
        2.0,
        0.76,
        0.42,
        "RIGHT_WING_THREE",
        False,
    )


def artifact(run_id: str = "run-1", artifact_id: str = "replay-1") -> Artifact:
    """Create one generated replay artifact."""
    return Artifact(
        artifact_id,
        "video-1",
        run_id,
        "REPLAY",
        f"video-1/{run_id}/{artifact_id}.mp4",
        "render-v1",
        10_000,
        NOW,
    )


def evidence(attempt_id: str = "attempt-1", evidence_id: str = "evidence-1") -> AssociationEvidenceReference:
    """Create one shot-attribution evidence reference."""
    return AssociationEvidenceReference(
        evidence_id,
        "run-1",
        attempt_id,
        AssociationEvidenceKind.SHOOTER,
        "player-1",
        ("ball-150", "player-150"),
        0.84,
        False,
        "Possession immediately preceded release.",
    )


def test_video_run_and_job_lifecycle(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Aggregate roots should round-trip without exposing SQLite rows."""
    videos = SQLiteVideoRepository(database)
    runs = SQLiteAnalysisRunRepository(database)
    jobs = SQLiteJobRepository(database)
    videos.create(video)
    runs.create(run)
    job = AnalysisJob(
        "job-1",
        video.id,
        run.id,
        JobStatus.QUEUED,
        AnalysisStage.VALIDATING,
        0,
        NOW,
        NOW,
    )
    jobs.create(job)

    runs.update_progress(run.id, 0.4, AnalysisStage.TRACKING)
    jobs.update_state(job.id, JobStatus.RUNNING, AnalysisStage.TRACKING, 0.4)

    assert videos.get(video.id) == video
    assert videos.list() == [video]
    updated_run = runs.get(run.id)
    updated_job = jobs.get(job.id)
    assert updated_run is not None and updated_run.status is RunStatus.RUNNING
    assert updated_job is not None and updated_job.status is JobStatus.RUNNING
    assert jobs.list_active() == [updated_job]
    assert jobs.list_for_video(video.id) == [updated_job]

    runs.fail(run.id, {"code": "TRACKING_FAILED"})
    failed = runs.get(run.id)
    assert failed is not None and failed.error == {"code": "TRACKING_FAILED"}

    videos.mark_deleting(video.id)
    assert videos.get(video.id) == replace(video, status=VideoStatus.DELETING)
    videos.delete(video.id)
    assert runs.get(run.id) is None


def test_progress_validation_and_missing_records(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Repositories should reject invalid progress and unknown identifiers."""
    seed_run(database, video, run)
    with pytest.raises(ValueError, match="between zero and one"):
        SQLiteAnalysisRunRepository(database).update_progress(run.id, 1.1, AnalysisStage.TRACKING)
    with pytest.raises(KeyError):
        SQLiteVideoRepository(database).mark_deleting("missing")
    with pytest.raises(KeyError):
        SQLiteJobRepository(database).update_state(
            "missing",
            JobStatus.RUNNING,
            AnalysisStage.TRACKING,
            0.2,
        )


def test_segment_calibration_and_tracks(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Segment, calibration, player, and ball data should be replaceable by run."""
    seed_run(database, video, run)
    segments = SQLiteCameraSegmentRepository(database)
    calibrations = SQLiteCalibrationRepository(database)
    players = SQLitePlayerTrackRepository(database)
    balls = SQLiteBallTrackRepository(database)
    stable = segment()
    tracked_player = player()
    automatic = Calibration(
        "calibration-1",
        stable.id,
        "AUTOMATIC",
        {"cx": 100, "cy": 80},
        {"left_corner": [0, 400]},
        0.61,
        True,
        NOW,
    )
    corrected = replace(
        automatic,
        id="calibration-2",
        source="USER",
        confidence=1.0,
        indicative_only=False,
        created_at=NOW + timedelta(seconds=1),
    )
    ball = BallTrack("ball-1", stable.id, "observations-1", "mlx-sam3", 0.88, 0)

    segments.replace_for_run(run.id, [stable])
    calibrations.add(automatic)
    calibrations.add(corrected)
    players.replace_for_run(run.id, [tracked_player])
    balls.replace_for_run(run.id, [ball])

    assert segments.list_for_run(run.id) == [stable]
    assert segments.get(stable.id) == stable
    assert calibrations.list_for_segment(stable.id) == [automatic, corrected]
    assert calibrations.latest_for_segment(stable.id) == corrected
    assert players.list_for_run(run.id) == [tracked_player]
    assert players.list_for_video(video.id) == [tracked_player]
    assert balls.list_for_run(run.id) == [ball]

    players.rename_display_name(tracked_player.id, "Alice")
    renamed = players.list_for_run(run.id)[0]
    assert renamed.id == tracked_player.id
    assert renamed.local_label == tracked_player.local_label
    assert renamed.display_name == "Alice"

    replacement = replace(stable, id="segment-2", start_seconds=2.0)
    segments.replace_for_run(run.id, [replacement])
    assert balls.list_for_run(run.id) == []


def test_effective_attempts_keep_automatic_evidence(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Latest corrections should project values without rewriting model output."""
    seed_run(database, video, run)
    SQLitePlayerTrackRepository(database).replace_for_run(run.id, [player()])
    runs = SQLiteAnalysisRunRepository(database)
    attempts = SQLiteShotAttemptRepository(database)
    locations = SQLiteShotLocationRepository(database)
    corrections = SQLiteReviewCorrectionRepository(database)
    artifacts = SQLiteArtifactRepository(database)
    automatic_attempt = attempt()
    automatic_location = location()
    replay = artifact()

    runs.publish_completed(run.id, [automatic_attempt], [automatic_location], [replay])
    for item in (
        ReviewCorrection("c1", automatic_attempt.id, "outcome", "MISSED", "MADE", NOW),
        ReviewCorrection("c2", automatic_attempt.id, "shot_type", "THREE_POINT", "TWO_POINT", NOW),
        ReviewCorrection("c3", automatic_attempt.id, "removed", False, True, NOW),
    ):
        corrections.add(item)

    effective = attempts.list_effective(video.id)[0]
    assert attempts.list_for_run(run.id) == [automatic_attempt]
    assert effective.automatic == automatic_attempt
    assert effective.outcome is ShotOutcome.MADE
    assert effective.shot_type == "TWO_POINT"
    assert effective.removed is True
    assert effective.location == automatic_location
    assert locations.get_for_attempt(automatic_attempt.id) == automatic_location
    assert artifacts.list_for_run(run.id) == [replay]
    assert artifacts.list_for_video(video.id) == [replay]
    assert len(corrections.list_for_attempt(automatic_attempt.id)) == 3

    corrections.delete("c1")
    assert attempts.list_effective(video.id)[0].outcome is ShotOutcome.MISSED


def test_association_evidence_references_round_trip_and_replace(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Shot attribution evidence references should remain queryable for review."""
    seed_run(database, video, run)
    SQLitePlayerTrackRepository(database).replace_for_run(run.id, [player()])
    SQLiteShotAttemptRepository(database).replace_automatic_results(run.id, [attempt()], [location()])
    repository = SQLiteAssociationEvidenceRepository(database)
    first = evidence()
    replacement = replace(
        first,
        id="evidence-2",
        player_track_id=None,
        confidence=0.52,
        ambiguous=True,
        reason="Two players were plausible at release.",
    )

    repository.replace_for_attempt("attempt-1", [first])
    assert repository.list_for_attempt("attempt-1") == [first]
    assert repository.list_for_run(run.id) == [first]

    repository.replace_for_attempt("attempt-1", [replacement])

    assert repository.list_for_attempt("attempt-1") == [replacement]


def test_court_mapping_atomically_refreshes_location_and_shot_type(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Calibration changes should update both derived values together."""
    seed_run(database, video, run)
    SQLitePlayerTrackRepository(database).replace_for_run(run.id, [player()])
    attempts = SQLiteShotAttemptRepository(database)
    attempts.replace_automatic_results(run.id, [attempt()], [location()])
    recalculated = replace(
        location(),
        court_x_m=2.0,
        court_y_m=-6.8,
        normalized_x=0.25,
        normalized_y=0.05,
        region="LEFT_CORNER_THREE",
    )

    attempts.update_location_and_shot_type("attempt-1", recalculated, "THREE_POINT")

    assert attempts.list_for_run(run.id)[0].shot_type == "THREE_POINT"
    assert SQLiteShotLocationRepository(database).get_for_attempt("attempt-1") == recalculated


def test_court_mapping_update_rejects_cross_attempt_location(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    seed_run(database, video, run)
    repository = SQLiteShotAttemptRepository(database)
    with pytest.raises(ValueError, match="requested attempt"):
        repository.update_location_and_shot_type("attempt-1", location("attempt-2"), "TWO_POINT")


def test_court_mapping_can_clear_stale_location(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    seed_run(database, video, run)
    SQLitePlayerTrackRepository(database).replace_for_run(run.id, [player()])
    repository = SQLiteShotAttemptRepository(database)
    repository.replace_automatic_results(run.id, [attempt()], [location()])

    repository.clear_location_and_shot_type("attempt-1", "UNKNOWN")

    assert repository.list_for_run(run.id)[0].shot_type == "UNKNOWN"
    assert SQLiteShotLocationRepository(database).get_for_attempt("attempt-1") is None


def test_atomic_publication_preserves_previous_run_on_failure(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """A failed result insert must not expose a partially published run."""
    seed_run(database, video, run)
    players = SQLitePlayerTrackRepository(database)
    runs = SQLiteAnalysisRunRepository(database)
    players.replace_for_run(run.id, [player()])
    runs.publish_completed(run.id, [attempt()], [location()], [artifact()])

    second = replace(run, id="run-2", status=RunStatus.RUNNING, started_at=NOW + timedelta(minutes=1))
    runs.create(second)
    second_player = replace(player(second.id), id="player-2")
    players.replace_for_run(second.id, [second_player])
    second_attempt = attempt(second.id, "attempt-2")
    duplicate_path = replace(
        artifact(second.id, "replay-2"),
        logical_path="video-1/run-1/replay-1.mp4",
    )

    with pytest.raises(sqlite3.IntegrityError):
        runs.publish_completed(second.id, [second_attempt], [location(second_attempt.id)], [duplicate_path])

    assert [item.id for item in runs.list_for_video(video.id, published_only=True)] == [run.id]
    assert SQLiteShotAttemptRepository(database).list_for_run(second.id) == []
    assert SQLiteArtifactRepository(database).list_for_run(second.id) == []


def test_replacement_validation_and_timezones(
    database: SQLiteDatabase,
    video: Video,
    run: AnalysisRun,
) -> None:
    """Invalid aggregate membership and ambiguous timestamps are rejected."""
    seed_run(database, video, run)
    repository = SQLiteShotAttemptRepository(database)
    with pytest.raises(ValueError, match="supplied attempt"):
        repository.replace_automatic_results(run.id, [attempt()], [location("missing")])
    with pytest.raises(ValueError, match="timezone-aware"):
        SQLiteArtifactRepository(database).add(replace(artifact(), created_at=NOW.replace(tzinfo=None)))
