"""Deletion service tests with real SQLite and filesystem artifacts."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteBallTrackRepository,
    SQLiteCalibrationRepository,
    SQLiteCameraSegmentRepository,
    SQLiteDatabase,
    SQLiteDeletionRepository,
    SQLiteJobRepository,
    SQLitePlayerTrackRepository,
    SQLiteReviewCorrectionRepository,
    SQLiteVideoRepository,
)
from shotsight2.domain import (
    AnalysisJob,
    AnalysisRun,
    AnalysisStage,
    Artifact,
    BallTrack,
    Calibration,
    CameraSegment,
    DeletionStatus,
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
from shotsight2.domain.artifacts import ArtifactId, ArtifactInventory
from shotsight2.services.deletion import ActiveVideoAnalysisError, VideoDeletionService

NOW = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _SeededVideo:
    video: Video
    run: AnalysisRun
    artifacts: tuple[ArtifactId, ...]
    model: ArtifactId


class _FailingDeleteStore(FileSystemArtifactStore):
    """Filesystem store that simulates a one-time locked-file cleanup failure."""

    def __init__(self, roots: ArtifactStoreRoots, locked_path: Path) -> None:
        super().__init__(roots)
        self._locked_path = locked_path
        self.fail_next_delete = True

    def delete_video_tree(self, video_id: str) -> ArtifactInventory:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise PermissionError(f"locked file: {self._locked_path}")
        return super().delete_video_tree(video_id)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    result = SQLiteDatabase(tmp_path / "shotsight2.db")
    result.migrate()
    return result


@pytest.fixture
def store(tmp_path: Path) -> FileSystemArtifactStore:
    return FileSystemArtifactStore(ArtifactStoreRoots.under(tmp_path / "data"))


def test_complete_deletion_removes_all_owned_records_and_artifacts(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
) -> None:
    selected = _seed_complete_video(database, store, "video-1")
    other = _seed_complete_video(database, store, "video-2")
    service = _service(database, store)

    inventory = service.build_inventory(selected.video.id)
    result = service.delete_video(selected.video.id)

    assert inventory.record_counts.videos == 1
    assert inventory.record_counts.analysis_runs == 1
    assert inventory.record_counts.analysis_jobs == 1
    assert inventory.record_counts.camera_segments == 1
    assert inventory.record_counts.calibrations == 1
    assert inventory.record_counts.player_tracks == 1
    assert inventory.record_counts.ball_tracks == 1
    assert inventory.record_counts.shot_attempts == 1
    assert inventory.record_counts.shot_locations == 1
    assert inventory.record_counts.review_corrections == 1
    assert inventory.record_counts.artifact_metadata == 4
    assert inventory.total_bytes == sum(len(value) for value in (b"source", b"proxy", b"track", b"replay", b"rendered"))
    assert result.status is DeletionStatus.DELETED
    assert SQLiteVideoRepository(database).get(selected.video.id) is None
    assert _all_record_count(database, selected.video.id) == 0
    assert _service(database, store).build_inventory(selected.video.id).total_bytes == 0
    assert store.metadata(selected.model).size_bytes == 5
    assert store.metadata(other.artifacts[0]).size_bytes == 6
    assert store.metadata(other.model).size_bytes == 5


def test_deletion_rejects_active_analysis_job(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
) -> None:
    selected = _seed_active_video(database, store, "video-active")
    service = _service(database, store)

    with pytest.raises(ActiveVideoAnalysisError) as error:
        service.delete_video(selected.video.id)

    assert error.value.active_job_ids == ("job-video-active",)
    assert SQLiteVideoRepository(database).get(selected.video.id) == selected.video
    assert store.metadata(selected.artifacts[0]).size_bytes == 6


def test_missing_files_are_idempotently_removed_from_database(database: SQLiteDatabase) -> None:
    store = FileSystemArtifactStore(ArtifactStoreRoots.under(database.path.parent / "data"))
    selected = _seed_database_only_video(database, store, "video-missing-files")

    result = _service(database, store).delete_video(selected.video.id)

    assert result.status is DeletionStatus.DELETED
    assert result.inventory.total_bytes == 0
    assert SQLiteVideoRepository(database).get(selected.video.id) is None


def test_partial_artifact_failure_marks_cleanup_incomplete_and_can_retry(
    database: SQLiteDatabase,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    roots = ArtifactStoreRoots.under(tmp_path / "data")
    store = _FailingDeleteStore(roots, tmp_path / "data" / "uploads" / "video-locked" / "original.mp4")
    selected = _seed_complete_video(database, store, "video-locked")
    service = _service(database, store)

    with caplog.at_level(logging.INFO, logger="shotsight2.services.deletion"):
        failed = service.delete_video(selected.video.id)

    remaining = failed.failure.remaining_artifacts if failed.failure is not None else None
    assert failed.status is DeletionStatus.CLEANUP_INCOMPLETE
    assert failed.failure is not None
    assert failed.failure.error_type == "PermissionError"
    assert remaining is not None and len(remaining.artifacts) == 5
    incomplete_video = SQLiteVideoRepository(database).get(selected.video.id)
    assert incomplete_video is not None and incomplete_video.status is VideoStatus.CLEANUP_INCOMPLETE
    assert _all_record_count(database, selected.video.id) > 0
    assert str(tmp_path) not in caplog.text

    retried = service.delete_video(selected.video.id)

    assert retried.status is DeletionStatus.DELETED
    assert SQLiteVideoRepository(database).get(selected.video.id) is None
    assert _all_record_count(database, selected.video.id) == 0


def test_repeated_deletion_request_is_idempotent(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
) -> None:
    selected = _seed_complete_video(database, store, "video-repeat")
    service = _service(database, store)

    assert service.delete_video(selected.video.id).status is DeletionStatus.DELETED
    repeated = service.delete_video(selected.video.id)

    assert repeated.status is DeletionStatus.ALREADY_DELETED
    assert repeated.inventory.record_counts.total == 0
    assert repeated.inventory.total_bytes == 0


def _service(database: SQLiteDatabase, store: FileSystemArtifactStore) -> VideoDeletionService:
    return VideoDeletionService(
        videos=SQLiteVideoRepository(database),
        deletion=SQLiteDeletionRepository(database),
        artifacts=SQLiteArtifactRepository(database),
        artifact_store=store,
    )


def _seed_complete_video(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
    video_id: str,
) -> _SeededVideo:
    seeded = _seed_roots(database, store, video_id, job_status=JobStatus.COMPLETED)
    SQLiteCameraSegmentRepository(database).replace_for_run(seeded.run.id, [_segment(seeded.run.id)])
    SQLiteCalibrationRepository(database).add(_calibration(video_id))
    SQLitePlayerTrackRepository(database).replace_for_run(seeded.run.id, [_player(seeded.run.id, video_id)])
    SQLiteBallTrackRepository(database).replace_for_run(seeded.run.id, [_ball_track(video_id)])
    SQLiteAnalysisRunRepository(database).publish_completed(
        seeded.run.id,
        [_attempt(seeded.run.id)],
        [_location(video_id)],
        [_artifact_metadata(video_id, seeded.run.id, artifact_id) for artifact_id in seeded.artifacts[1:]],
    )
    SQLiteReviewCorrectionRepository(database).add(
        ReviewCorrection("correction-" + video_id, "attempt-" + video_id, "outcome", "MISSED", "MADE", NOW)
    )
    return seeded


def _seed_active_video(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
    video_id: str,
) -> _SeededVideo:
    return _seed_roots(database, store, video_id, job_status=JobStatus.RUNNING)


def _seed_database_only_video(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
    video_id: str,
) -> _SeededVideo:
    original = store.original_id(video_id, "mp4")
    video = _video(video_id, original)
    run = _run(video_id)
    SQLiteVideoRepository(database).create(video)
    SQLiteAnalysisRunRepository(database).create(run)
    SQLiteJobRepository(database).create(_job(video_id, run.id, JobStatus.COMPLETED))
    return _SeededVideo(video=video, run=run, artifacts=(original,), model=store.model_id("mlx", "shared.bin"))


def _seed_roots(
    database: SQLiteDatabase,
    store: FileSystemArtifactStore,
    video_id: str,
    *,
    job_status: JobStatus,
) -> _SeededVideo:
    original = store.original_id(video_id, "mp4")
    run = _run(video_id)
    artifacts = (
        original,
        store.proxy_id(video_id, run.id, "proxy.mp4"),
        store.track_id(video_id, run.id, "ball.json"),
        store.replay_id(video_id, run.id, "shot-1.mp4"),
        store.render_id(video_id, run.id, "tracked.mp4"),
    )
    for artifact_id, payload in zip(
        artifacts,
        (b"source", b"proxy", b"track", b"replay", b"rendered"),
        strict=True,
    ):
        store.write_atomic(artifact_id, (payload,))
    model = store.model_id("mlx", f"shared-{video_id}.bin")
    store.write_atomic(model, (b"model",))

    video = _video(video_id, original)
    SQLiteVideoRepository(database).create(video)
    SQLiteAnalysisRunRepository(database).create(run)
    SQLiteJobRepository(database).create(_job(video_id, run.id, job_status))
    return _SeededVideo(video=video, run=run, artifacts=artifacts, model=model)


def _video(video_id: str, original: ArtifactId) -> Video:
    return Video(
        id=video_id,
        filename=f"{video_id}.mp4",
        original_artifact_id=str(original),
        size_bytes=6,
        duration_seconds=12.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        container="mp4",
        created_at=NOW,
    )


def _run(video_id: str) -> AnalysisRun:
    return AnalysisRun(
        id="run-" + video_id,
        video_id=video_id,
        status=RunStatus.PENDING,
        backend_name="opencv",
        backend_version="1",
        configuration={"profile": "balanced"},
        progress=0.0,
        stage=AnalysisStage.VALIDATING,
        started_at=NOW,
    )


def _job(video_id: str, run_id: str, status: JobStatus) -> AnalysisJob:
    return AnalysisJob(
        id="job-" + video_id,
        video_id=video_id,
        run_id=run_id,
        status=status,
        stage=AnalysisStage.FINALIZING if status is JobStatus.COMPLETED else AnalysisStage.TRACKING,
        progress=1.0 if status is JobStatus.COMPLETED else 0.4,
        created_at=NOW,
        updated_at=NOW,
    )


def _segment(run_id: str) -> CameraSegment:
    return CameraSegment("segment-" + run_id.removeprefix("run-"), run_id, 0.0, 12.0, "STABLE", 0.95)


def _calibration(video_id: str) -> Calibration:
    return Calibration(
        "calibration-" + video_id,
        "segment-" + video_id,
        "AUTOMATIC",
        {"rim": [1, 2]},
        {"lane": [3, 4]},
        0.8,
        False,
        NOW,
    )


def _player(run_id: str, video_id: str) -> PlayerTrack:
    return PlayerTrack("player-" + video_id, run_id, video_id, "Player 1", "Player 1", 0.9)


def _ball_track(video_id: str) -> BallTrack:
    return BallTrack("ball-" + video_id, "segment-" + video_id, "track-observations", "opencv", 0.8, 0)


def _attempt(run_id: str) -> ShotAttempt:
    video_id = run_id.removeprefix("run-")
    return ShotAttempt(
        "attempt-" + video_id,
        run_id,
        "player-" + video_id,
        4.5,
        ShotOutcome.MISSED,
        "THREE_POINT",
        0.72,
        ReviewStatus.UNREVIEWED,
        {"release_frame": 135},
    )


def _location(video_id: str) -> ShotLocation:
    return ShotLocation(
        "location-" + video_id,
        "attempt-" + video_id,
        7.0,
        2.0,
        0.8,
        0.4,
        "RIGHT_WING_THREE",
        False,
    )


def _artifact_metadata(video_id: str, run_id: str, artifact_id: ArtifactId) -> Artifact:
    kind = {
        "proxy": "PROXY",
        "tracks": "TRACK",
        "replays": "REPLAY",
        "rendered": "RENDER",
    }[str(artifact_id).split("/")[-2]]
    logical_path = str(artifact_id).partition(":")[2]
    return Artifact(
        id=f"metadata-{video_id}-{kind.lower()}",
        video_id=video_id,
        analysis_run_id=run_id,
        kind=kind,
        logical_path=logical_path,
        version="v1",
        size_bytes=5,
        created_at=NOW,
    )


def _all_record_count(database: SQLiteDatabase, video_id: str) -> int:
    with database.read() as connection:
        return sum(
            _count(connection, table, video_id)
            for table in (
                "videos",
                "analysis_runs",
                "analysis_jobs",
                "camera_segments",
                "calibrations",
                "player_tracks",
                "ball_tracks",
                "shot_attempts",
                "shot_locations",
                "review_corrections",
                "artifacts",
            )
        )


def _count(connection: sqlite3.Connection, table: str, video_id: str) -> int:
    if table == "videos":
        row = connection.execute("SELECT COUNT(*) AS count FROM videos WHERE id = ?", (video_id,)).fetchone()
    elif table in {"analysis_runs", "analysis_jobs", "player_tracks", "artifacts"}:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE video_id = ?", (video_id,)).fetchone()
    elif table == "camera_segments":
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM camera_segments
            JOIN analysis_runs ON analysis_runs.id = camera_segments.analysis_run_id
            WHERE analysis_runs.video_id = ?
            """,
            (video_id,),
        ).fetchone()
    elif table in {"calibrations", "ball_tracks"}:
        foreign_key = "segment_id"
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table}
            JOIN camera_segments ON camera_segments.id = {table}.{foreign_key}
            JOIN analysis_runs ON analysis_runs.id = camera_segments.analysis_run_id
            WHERE analysis_runs.video_id = ?
            """,
            (video_id,),
        ).fetchone()
    elif table == "shot_attempts":
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM shot_attempts
            JOIN analysis_runs ON analysis_runs.id = shot_attempts.analysis_run_id
            WHERE analysis_runs.video_id = ?
            """,
            (video_id,),
        ).fetchone()
    else:
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table}
            JOIN shot_attempts ON shot_attempts.id = {table}.shot_attempt_id
            JOIN analysis_runs ON analysis_runs.id = shot_attempts.analysis_run_id
            WHERE analysis_runs.video_id = ?
            """,
            (video_id,),
        ).fetchone()
    return 0 if row is None else int(row["count"])
