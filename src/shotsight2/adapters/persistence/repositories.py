"""Domain-oriented SQLite repository implementations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from shotsight2.adapters.persistence.database import SQLiteDatabase
from shotsight2.domain import (
    AnalysisJob,
    AnalysisRun,
    AnalysisStage,
    Artifact,
    BackupMetadata,
    BallTrack,
    Calibration,
    CameraSegment,
    EffectiveShotAttempt,
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
from shotsight2.domain.persistence import JsonObject, JsonValue


def _timestamp(value: datetime) -> str:
    """Serialize an aware timestamp in normalized UTC form."""
    if value.tzinfo is None:
        raise ValueError("Persisted timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _optional_timestamp(value: datetime | None) -> str | None:
    """Serialize an optional timestamp."""
    return None if value is None else _timestamp(value)


def _datetime(value: str) -> datetime:
    """Parse a persisted ISO-8601 timestamp."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    """Parse an optional persisted timestamp."""
    return None if value is None else _datetime(value)


def _json(value: JsonValue) -> str:
    """Serialize JSON deterministically for diagnostics and reproducibility."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _json_value(value: str) -> JsonValue:
    """Decode a JSON value from SQLite."""
    return cast(JsonValue, json.loads(value))


def _json_object(value: str) -> JsonObject:
    """Decode a JSON object and reject corrupt non-object content."""
    decoded = _json_value(value)
    if not isinstance(decoded, dict):
        raise ValueError("Expected a JSON object")
    return decoded


def _row_text(row: sqlite3.Row, key: str) -> str:
    """Read a required text value from an internal SQLite row."""
    return cast(str, row[key])


def _video(row: sqlite3.Row) -> Video:
    return Video(
        id=_row_text(row, "id"),
        filename=_row_text(row, "filename"),
        original_artifact_id=_row_text(row, "original_artifact_id"),
        size_bytes=int(row["size_bytes"]),
        duration_seconds=float(row["duration_seconds"]),
        width=int(row["width"]),
        height=int(row["height"]),
        fps=float(row["fps"]),
        codec=_row_text(row, "codec"),
        container=_row_text(row, "container"),
        created_at=_datetime(_row_text(row, "created_at")),
        status=VideoStatus(_row_text(row, "status")),
        rotation_degrees=int(row["rotation_degrees"]),
        audio_codecs=tuple(cast(list[str], json.loads(_row_text(row, "audio_codecs_json")))),
    )


def _run(row: sqlite3.Row) -> AnalysisRun:
    error = row["error_json"]
    return AnalysisRun(
        id=_row_text(row, "id"),
        video_id=_row_text(row, "video_id"),
        status=RunStatus(_row_text(row, "status")),
        backend_name=_row_text(row, "backend_name"),
        backend_version=_row_text(row, "backend_version"),
        configuration=_json_object(_row_text(row, "configuration_json")),
        progress=float(row["progress"]),
        stage=AnalysisStage(_row_text(row, "stage")),
        started_at=_datetime(_row_text(row, "started_at")),
        completed_at=_optional_datetime(cast(str | None, row["completed_at"])),
        error=None if error is None else _json_object(cast(str, error)),
        published=bool(row["published"]),
    )


def _job(row: sqlite3.Row) -> AnalysisJob:
    error = row["error_json"]
    return AnalysisJob(
        id=_row_text(row, "id"),
        video_id=_row_text(row, "video_id"),
        run_id=_row_text(row, "run_id"),
        status=JobStatus(_row_text(row, "status")),
        stage=AnalysisStage(_row_text(row, "stage")),
        progress=float(row["progress"]),
        error=None if error is None else _json_object(cast(str, error)),
        claimed_by=cast(str | None, row["claimed_by"]),
        claimed_at=_optional_datetime(cast(str | None, row["claimed_at"])),
        heartbeat_at=_optional_datetime(cast(str | None, row["heartbeat_at"])),
        created_at=_datetime(_row_text(row, "created_at")),
        updated_at=_datetime(_row_text(row, "updated_at")),
    )


def _segment(row: sqlite3.Row) -> CameraSegment:
    return CameraSegment(
        id=_row_text(row, "id"),
        analysis_run_id=_row_text(row, "analysis_run_id"),
        start_seconds=float(row["start_seconds"]),
        end_seconds=float(row["end_seconds"]),
        stability_status=_row_text(row, "stability_status"),
        confidence=float(row["confidence"]),
        representative_artifact_id=cast(str | None, row["representative_artifact_id"]),
    )


def _calibration(row: sqlite3.Row) -> Calibration:
    return Calibration(
        id=_row_text(row, "id"),
        segment_id=_row_text(row, "segment_id"),
        source=_row_text(row, "source"),
        rim_geometry=_json_object(_row_text(row, "rim_geometry_json")),
        court_points=_json_object(_row_text(row, "court_points_json")),
        confidence=float(row["confidence"]),
        indicative_only=bool(row["indicative_only"]),
        created_at=_datetime(_row_text(row, "created_at")),
    )


def _player(row: sqlite3.Row) -> PlayerTrack:
    return PlayerTrack(
        id=_row_text(row, "id"),
        analysis_run_id=_row_text(row, "analysis_run_id"),
        video_id=_row_text(row, "video_id"),
        local_label=_row_text(row, "local_label"),
        display_name=_row_text(row, "display_name"),
        confidence=float(row["confidence"]),
        observations_artifact_id=cast(str | None, row["observations_artifact_id"]),
    )


def _ball(row: sqlite3.Row) -> BallTrack:
    return BallTrack(
        id=_row_text(row, "id"),
        segment_id=_row_text(row, "segment_id"),
        observations_artifact_id=_row_text(row, "observations_artifact_id"),
        backend_name=_row_text(row, "backend_name"),
        coverage=float(row["coverage"]),
        identity_switches=int(row["identity_switches"]),
    )


def _attempt(row: sqlite3.Row) -> ShotAttempt:
    return ShotAttempt(
        id=_row_text(row, "id"),
        analysis_run_id=_row_text(row, "analysis_run_id"),
        shooter_track_id=cast(str | None, row["shooter_track_id"]),
        release_seconds=float(row["release_seconds"]),
        automatic_outcome=ShotOutcome(_row_text(row, "automatic_outcome")),
        shot_type=_row_text(row, "shot_type"),
        confidence=float(row["confidence"]),
        review_status=ReviewStatus(_row_text(row, "review_status")),
        evidence=_json_object(_row_text(row, "evidence_json")),
        manual=bool(row["manual"]),
    )


def _location(row: sqlite3.Row) -> ShotLocation:
    return ShotLocation(
        id=_row_text(row, "id"),
        shot_attempt_id=_row_text(row, "shot_attempt_id"),
        court_x_m=None if row["court_x_m"] is None else float(row["court_x_m"]),
        court_y_m=None if row["court_y_m"] is None else float(row["court_y_m"]),
        normalized_x=float(row["normalized_x"]),
        normalized_y=float(row["normalized_y"]),
        region=_row_text(row, "region"),
        indicative=bool(row["indicative"]),
    )


def _correction(row: sqlite3.Row) -> ReviewCorrection:
    return ReviewCorrection(
        id=_row_text(row, "id"),
        shot_attempt_id=_row_text(row, "shot_attempt_id"),
        field=_row_text(row, "field"),
        previous_value=_json_value(_row_text(row, "previous_value_json")),
        corrected_value=_json_value(_row_text(row, "corrected_value_json")),
        created_at=_datetime(_row_text(row, "created_at")),
    )


def _artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=_row_text(row, "id"),
        video_id=_row_text(row, "video_id"),
        analysis_run_id=cast(str | None, row["analysis_run_id"]),
        kind=_row_text(row, "kind"),
        logical_path=_row_text(row, "logical_path"),
        version=_row_text(row, "version"),
        size_bytes=int(row["size_bytes"]),
        created_at=_datetime(_row_text(row, "created_at")),
    )


def _insert_attempt(connection: sqlite3.Connection, attempt: ShotAttempt) -> None:
    connection.execute(
        """
        INSERT INTO shot_attempts(
            id, analysis_run_id, shooter_track_id, release_seconds,
            automatic_outcome, shot_type, confidence, review_status,
            evidence_json, manual
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt.id,
            attempt.analysis_run_id,
            attempt.shooter_track_id,
            attempt.release_seconds,
            attempt.automatic_outcome.value,
            attempt.shot_type,
            attempt.confidence,
            attempt.review_status.value,
            _json(attempt.evidence),
            int(attempt.manual),
        ),
    )


def _upsert_location(connection: sqlite3.Connection, location: ShotLocation) -> None:
    connection.execute(
        """
        INSERT INTO shot_locations(
            id, shot_attempt_id, court_x_m, court_y_m, normalized_x,
            normalized_y, region, indicative
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(shot_attempt_id) DO UPDATE SET
            id = excluded.id,
            court_x_m = excluded.court_x_m,
            court_y_m = excluded.court_y_m,
            normalized_x = excluded.normalized_x,
            normalized_y = excluded.normalized_y,
            region = excluded.region,
            indicative = excluded.indicative
        """,
        (
            location.id,
            location.shot_attempt_id,
            location.court_x_m,
            location.court_y_m,
            location.normalized_x,
            location.normalized_y,
            location.region,
            int(location.indicative),
        ),
    )


def _insert_artifact(connection: sqlite3.Connection, artifact: Artifact) -> None:
    connection.execute(
        """
        INSERT INTO artifacts(
            id, video_id, analysis_run_id, kind, logical_path,
            version, size_bytes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact.id,
            artifact.video_id,
            artifact.analysis_run_id,
            artifact.kind,
            artifact.logical_path,
            artifact.version,
            artifact.size_bytes,
            _timestamp(artifact.created_at),
        ),
    )


class SQLiteVideoRepository:
    """SQLite implementation of video metadata persistence."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create(self, video: Video) -> None:
        """Insert one validated video."""
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO videos(
                    id, filename, original_artifact_id, size_bytes,
                    duration_seconds, width, height, fps, codec, container,
                    status, created_at, rotation_degrees, audio_codecs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video.id,
                    video.filename,
                    video.original_artifact_id,
                    video.size_bytes,
                    video.duration_seconds,
                    video.width,
                    video.height,
                    video.fps,
                    video.codec,
                    video.container,
                    video.status.value,
                    _timestamp(video.created_at),
                    video.rotation_degrees,
                    _json(list(video.audio_codecs)),
                ),
            )

    def get(self, video_id: str) -> Video | None:
        """Return a video by identifier."""
        with self._database.read() as connection:
            row = connection.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
            return None if row is None else _video(row)

    def list(self) -> list[Video]:
        """List videos newest first."""
        with self._database.read() as connection:
            rows = connection.execute("SELECT * FROM videos ORDER BY created_at DESC, id").fetchall()
            return [_video(row) for row in rows]

    def mark_deleting(self, video_id: str) -> None:
        """Mark a video before filesystem cleanup begins."""
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE videos SET status = ? WHERE id = ?",
                (VideoStatus.DELETING.value, video_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(video_id)

    def delete(self, video_id: str) -> None:
        """Delete video metadata and all database-owned children."""
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM videos WHERE id = ?", (video_id,))


class SQLiteAnalysisRunRepository:
    """SQLite analysis lifecycle and atomic publication implementation."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create(self, run: AnalysisRun) -> None:
        """Insert an unpublished analysis run."""
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs(
                    id, video_id, status, backend_name, backend_version,
                    configuration_json, progress, stage, started_at,
                    completed_at, error_json, published
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.video_id,
                    run.status.value,
                    run.backend_name,
                    run.backend_version,
                    _json(run.configuration),
                    run.progress,
                    run.stage.value,
                    _timestamp(run.started_at),
                    _optional_timestamp(run.completed_at),
                    None if run.error is None else _json(run.error),
                    int(run.published),
                ),
            )

    def get(self, run_id: str) -> AnalysisRun | None:
        """Return an analysis run by identifier."""
        with self._database.read() as connection:
            row = connection.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
            return None if row is None else _run(row)

    def list_for_video(self, video_id: str, *, published_only: bool = False) -> list[AnalysisRun]:
        """List runs newest first, optionally restricting to the published run."""
        query = "SELECT * FROM analysis_runs WHERE video_id = ?"
        if published_only:
            query += " AND published = 1"
        query += " ORDER BY started_at DESC, id"
        with self._database.read() as connection:
            return [_run(row) for row in connection.execute(query, (video_id,)).fetchall()]

    def update_progress(self, run_id: str, progress: float, stage: AnalysisStage) -> None:
        """Persist bounded pipeline progress."""
        if not 0 <= progress <= 1:
            raise ValueError("progress must be between zero and one")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE analysis_runs SET progress = ?, stage = ?, status = ? WHERE id = ?",
                (progress, stage.value, RunStatus.RUNNING.value, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)

    def fail(self, run_id: str, error: JsonObject) -> None:
        """Mark an unpublished run failed while retaining diagnostics."""
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error_json = ?, published = 0
                WHERE id = ?
                """,
                (RunStatus.FAILED.value, _json(error), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)

    def publish_completed(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
        artifacts: Sequence[Artifact],
    ) -> None:
        """Replace run outputs and expose them atomically as the latest result."""
        attempt_ids = {attempt.id for attempt in attempts}
        if any(attempt.analysis_run_id != run_id for attempt in attempts):
            raise ValueError("All attempts must belong to the published run")
        if any(location.shot_attempt_id not in attempt_ids for location in locations):
            raise ValueError("Every location must belong to a supplied attempt")
        if any(artifact.analysis_run_id != run_id for artifact in artifacts):
            raise ValueError("All artifacts must belong to the published run")

        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT video_id FROM analysis_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            video_id = _row_text(row, "video_id")
            if any(artifact.video_id != video_id for artifact in artifacts):
                raise ValueError("All artifacts must belong to the run video")

            connection.execute("DELETE FROM shot_attempts WHERE analysis_run_id = ?", (run_id,))
            connection.execute("DELETE FROM artifacts WHERE analysis_run_id = ?", (run_id,))
            for attempt in attempts:
                _insert_attempt(connection, attempt)
            for location in locations:
                _upsert_location(connection, location)
            for artifact in artifacts:
                _insert_artifact(connection, artifact)

            connection.execute(
                "UPDATE analysis_runs SET published = 0 WHERE video_id = ? AND id != ?",
                (video_id, run_id),
            )
            completed_at = _timestamp(datetime.now(UTC))
            connection.execute(
                """
                UPDATE analysis_runs
                SET status = ?, progress = 1, stage = ?, completed_at = ?,
                    error_json = NULL, published = 1
                WHERE id = ?
                """,
                (RunStatus.COMPLETED.value, AnalysisStage.FINALIZING.value, completed_at, run_id),
            )


class SQLiteJobRepository:
    """SQLite implementation for durable worker job state."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create(self, job: AnalysisJob) -> None:
        """Insert a queued or historical job."""
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analysis_jobs(
                    id, video_id, run_id, status, stage, progress, error_json,
                    claimed_by, claimed_at, heartbeat_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.video_id,
                    job.run_id,
                    job.status.value,
                    job.stage.value,
                    job.progress,
                    None if job.error is None else _json(job.error),
                    job.claimed_by,
                    _optional_timestamp(job.claimed_at),
                    _optional_timestamp(job.heartbeat_at),
                    _timestamp(job.created_at),
                    _timestamp(job.updated_at),
                ),
            )

    def get(self, job_id: str) -> AnalysisJob | None:
        """Return one job."""
        with self._database.read() as connection:
            row = connection.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
            return None if row is None else _job(row)

    def list_for_video(self, video_id: str) -> list[AnalysisJob]:
        """List jobs newest first for a video."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_jobs WHERE video_id = ? ORDER BY created_at DESC, id",
                (video_id,),
            ).fetchall()
            return [_job(row) for row in rows]

    def list_active(self) -> list[AnalysisJob]:
        """List queued and running jobs."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_jobs WHERE status IN (?, ?) ORDER BY created_at, id",
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchall()
            return [_job(row) for row in rows]

    def update_state(
        self,
        job_id: str,
        status: JobStatus,
        stage: AnalysisStage,
        progress: float,
        *,
        error: JsonObject | None = None,
    ) -> None:
        """Update job state and its modification timestamp."""
        if not 0 <= progress <= 1:
            raise ValueError("progress must be between zero and one")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, stage = ?, progress = ?, error_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    stage.value,
                    progress,
                    None if error is None else _json(error),
                    _timestamp(datetime.now(UTC)),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)


class SQLiteCameraSegmentRepository:
    """SQLite implementation for camera segments."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def replace_for_run(self, run_id: str, segments: Sequence[CameraSegment]) -> None:
        """Replace all camera segments for an unpublished analysis run."""
        if any(segment.analysis_run_id != run_id for segment in segments):
            raise ValueError("All segments must belong to the requested run")
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM camera_segments WHERE analysis_run_id = ?", (run_id,))
            connection.executemany(
                """
                INSERT INTO camera_segments(
                    id, analysis_run_id, start_seconds, end_seconds,
                    stability_status, confidence, representative_artifact_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.analysis_run_id,
                        item.start_seconds,
                        item.end_seconds,
                        item.stability_status,
                        item.confidence,
                        item.representative_artifact_id,
                    )
                    for item in segments
                ],
            )

    def list_for_run(self, run_id: str) -> list[CameraSegment]:
        """List camera segments in timeline order."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM camera_segments WHERE analysis_run_id = ? ORDER BY start_seconds, id",
                (run_id,),
            ).fetchall()
            return [_segment(row) for row in rows]


class SQLiteCalibrationRepository:
    """SQLite implementation for append-only calibration versions."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def add(self, calibration: Calibration) -> None:
        """Append a calibration version."""
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO calibrations(
                    id, segment_id, source, rim_geometry_json, court_points_json,
                    confidence, indicative_only, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    calibration.id,
                    calibration.segment_id,
                    calibration.source,
                    _json(calibration.rim_geometry),
                    _json(calibration.court_points),
                    calibration.confidence,
                    int(calibration.indicative_only),
                    _timestamp(calibration.created_at),
                ),
            )

    def list_for_segment(self, segment_id: str) -> list[Calibration]:
        """List calibration versions oldest first."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM calibrations WHERE segment_id = ? ORDER BY created_at, id",
                (segment_id,),
            ).fetchall()
            return [_calibration(row) for row in rows]

    def latest_for_segment(self, segment_id: str) -> Calibration | None:
        """Return the newest calibration version."""
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM calibrations WHERE segment_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (segment_id,),
            ).fetchone()
            return None if row is None else _calibration(row)


class SQLitePlayerTrackRepository:
    """SQLite implementation for player tracks."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def replace_for_run(self, run_id: str, tracks: Sequence[PlayerTrack]) -> None:
        """Replace all player tracks for an analysis run."""
        if any(track.analysis_run_id != run_id for track in tracks):
            raise ValueError("All player tracks must belong to the requested run")
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM player_tracks WHERE analysis_run_id = ?", (run_id,))
            connection.executemany(
                """
                INSERT INTO player_tracks(
                    id, analysis_run_id, video_id, local_label, display_name,
                    confidence, observations_artifact_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.analysis_run_id,
                        item.video_id,
                        item.local_label,
                        item.display_name,
                        item.confidence,
                        item.observations_artifact_id,
                    )
                    for item in tracks
                ],
            )

    def list_for_run(self, run_id: str) -> list[PlayerTrack]:
        """List player tracks in local-label order."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM player_tracks WHERE analysis_run_id = ? ORDER BY local_label, id",
                (run_id,),
            ).fetchall()
            return [_player(row) for row in rows]

    def list_for_video(self, video_id: str) -> list[PlayerTrack]:
        """List player tracks across video analysis history."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM player_tracks WHERE video_id = ? ORDER BY analysis_run_id, local_label, id",
                (video_id,),
            ).fetchall()
            return [_player(row) for row in rows]


class SQLiteBallTrackRepository:
    """SQLite implementation for ball-track metadata."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def replace_for_run(self, run_id: str, tracks: Sequence[BallTrack]) -> None:
        """Replace ball tracks for all segments owned by a run."""
        with self._database.transaction() as connection:
            valid_segment_ids = {
                _row_text(row, "id")
                for row in connection.execute(
                    "SELECT id FROM camera_segments WHERE analysis_run_id = ?",
                    (run_id,),
                ).fetchall()
            }
            if any(track.segment_id not in valid_segment_ids for track in tracks):
                raise ValueError("All ball tracks must belong to a segment in the requested run")
            connection.execute(
                """
                DELETE FROM ball_tracks
                WHERE segment_id IN (
                    SELECT id FROM camera_segments WHERE analysis_run_id = ?
                )
                """,
                (run_id,),
            )
            connection.executemany(
                """
                INSERT INTO ball_tracks(
                    id, segment_id, observations_artifact_id, backend_name,
                    coverage, identity_switches
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.segment_id,
                        item.observations_artifact_id,
                        item.backend_name,
                        item.coverage,
                        item.identity_switches,
                    )
                    for item in tracks
                ],
            )

    def list_for_run(self, run_id: str) -> list[BallTrack]:
        """List ball tracks in camera-segment order."""
        with self._database.read() as connection:
            rows = connection.execute(
                """
                SELECT ball_tracks.*
                FROM ball_tracks
                JOIN camera_segments ON camera_segments.id = ball_tracks.segment_id
                WHERE camera_segments.analysis_run_id = ?
                ORDER BY camera_segments.start_seconds, ball_tracks.id
                """,
                (run_id,),
            ).fetchall()
            return [_ball(row) for row in rows]


class SQLiteShotLocationRepository:
    """SQLite implementation for automatic location records."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get_for_attempt(self, attempt_id: str) -> ShotLocation | None:
        """Return an attempt's automatic location."""
        with self._database.read() as connection:
            row = connection.execute(
                "SELECT * FROM shot_locations WHERE shot_attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            return None if row is None else _location(row)

    def upsert(self, location: ShotLocation) -> None:
        """Insert or replace an attempt's automatic location."""
        with self._database.transaction() as connection:
            _upsert_location(connection, location)


class SQLiteReviewCorrectionRepository:
    """SQLite implementation for append-only correction history."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def add(self, correction: ReviewCorrection) -> None:
        """Append one correction."""
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO review_corrections(
                    id, shot_attempt_id, field, previous_value_json,
                    corrected_value_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    correction.id,
                    correction.shot_attempt_id,
                    correction.field,
                    _json(correction.previous_value),
                    _json(correction.corrected_value),
                    _timestamp(correction.created_at),
                ),
            )

    def list_for_attempt(self, attempt_id: str) -> list[ReviewCorrection]:
        """Return correction history in deterministic application order."""
        with self._database.read() as connection:
            rows = connection.execute(
                """
                SELECT * FROM review_corrections
                WHERE shot_attempt_id = ?
                ORDER BY created_at, id
                """,
                (attempt_id,),
            ).fetchall()
            return [_correction(row) for row in rows]

    def delete(self, correction_id: str) -> None:
        """Remove one correction so the prior effective value is restored."""
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM review_corrections WHERE id = ?", (correction_id,))


def _corrected_location(value: JsonValue, automatic: ShotLocation | None) -> ShotLocation | None:
    """Build a corrected location from a complete JSON object."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Location correction must be an object or null")
    attempt_id = automatic.shot_attempt_id if automatic is not None else cast(str, value["shot_attempt_id"])
    location_id = automatic.id if automatic is not None else cast(str, value["id"])
    x_value = value.get("court_x_m")
    y_value = value.get("court_y_m")
    return ShotLocation(
        id=location_id,
        shot_attempt_id=attempt_id,
        court_x_m=None if x_value is None else float(cast(float | int, x_value)),
        court_y_m=None if y_value is None else float(cast(float | int, y_value)),
        normalized_x=float(cast(float | int, value["normalized_x"])),
        normalized_y=float(cast(float | int, value["normalized_y"])),
        region=cast(str, value["region"]),
        indicative=cast(bool, value["indicative"]),
    )


class SQLiteShotAttemptRepository:
    """SQLite implementation preserving automatic evidence and corrections."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def replace_automatic_results(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
    ) -> None:
        """Atomically replace automatic attempt and location rows for a run."""
        attempt_ids = {attempt.id for attempt in attempts}
        if any(attempt.analysis_run_id != run_id for attempt in attempts):
            raise ValueError("All attempts must belong to the requested run")
        if any(location.shot_attempt_id not in attempt_ids for location in locations):
            raise ValueError("Every location must belong to a supplied attempt")
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM shot_attempts WHERE analysis_run_id = ?", (run_id,))
            for attempt in attempts:
                _insert_attempt(connection, attempt)
            for location in locations:
                _upsert_location(connection, location)

    def list_for_run(self, run_id: str) -> list[ShotAttempt]:
        """List immutable attempt evidence in release order."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM shot_attempts WHERE analysis_run_id = ? ORDER BY release_seconds, id",
                (run_id,),
            ).fetchall()
            return [_attempt(row) for row in rows]

    def list_effective(self, video_id: str) -> list[EffectiveShotAttempt]:
        """Project the published run through each field's latest correction."""
        with self._database.read() as connection:
            rows = connection.execute(
                """
                SELECT shot_attempts.*
                FROM shot_attempts
                JOIN analysis_runs ON analysis_runs.id = shot_attempts.analysis_run_id
                WHERE analysis_runs.video_id = ? AND analysis_runs.published = 1
                ORDER BY shot_attempts.release_seconds, shot_attempts.id
                """,
                (video_id,),
            ).fetchall()
            return [self._effective(connection, _attempt(row)) for row in rows]

    @staticmethod
    def _effective(connection: sqlite3.Connection, attempt: ShotAttempt) -> EffectiveShotAttempt:
        location_row = connection.execute(
            "SELECT * FROM shot_locations WHERE shot_attempt_id = ?",
            (attempt.id,),
        ).fetchone()
        location = None if location_row is None else _location(location_row)
        corrections = [
            _correction(row)
            for row in connection.execute(
                """
                SELECT * FROM review_corrections
                WHERE shot_attempt_id = ?
                ORDER BY created_at, id
                """,
                (attempt.id,),
            ).fetchall()
        ]
        latest = {correction.field: correction.corrected_value for correction in corrections}
        shooter = latest.get("shooter_track_id", attempt.shooter_track_id)
        outcome = latest.get("outcome", attempt.automatic_outcome.value)
        shot_type = latest.get("shot_type", attempt.shot_type)
        review_status = latest.get("review_status", attempt.review_status.value)
        removed = latest.get("removed", False)
        if "location" in latest:
            location = _corrected_location(latest["location"], location)
        if shooter is not None and not isinstance(shooter, str):
            raise ValueError("Corrected shooter_track_id must be text or null")
        if not isinstance(outcome, str) or not isinstance(shot_type, str) or not isinstance(review_status, str):
            raise ValueError("Corrected attempt values have invalid types")
        if not isinstance(removed, bool):
            raise ValueError("Corrected removed value must be boolean")
        return EffectiveShotAttempt(
            automatic=attempt,
            shooter_track_id=shooter,
            outcome=ShotOutcome(outcome),
            shot_type=shot_type,
            review_status=ReviewStatus(review_status),
            location=location,
            removed=removed,
        )


class SQLiteArtifactRepository:
    """SQLite implementation for artifact metadata."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def add(self, artifact: Artifact) -> None:
        """Insert metadata after the artifact store has made content durable."""
        with self._database.transaction() as connection:
            _insert_artifact(connection, artifact)

    def list_for_run(self, run_id: str) -> list[Artifact]:
        """List artifacts for an analysis run."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE analysis_run_id = ? ORDER BY kind, id",
                (run_id,),
            ).fetchall()
            return [_artifact(row) for row in rows]

    def list_for_video(self, video_id: str) -> list[Artifact]:
        """List source and derived artifact metadata for a video."""
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE video_id = ? ORDER BY created_at, id",
                (video_id,),
            ).fetchall()
            return [_artifact(row) for row in rows]


class SQLiteDiagnosticRepository:
    """Read diagnostic metadata without copying media or generated artifacts."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def backup_metadata(self) -> BackupMetadata:
        """Return database-only metadata suitable for a backup manifest."""
        with self._database.read() as connection:
            video_row = connection.execute("SELECT COUNT(*) AS count FROM videos").fetchone()
            run_row = connection.execute("SELECT COUNT(*) AS count FROM analysis_runs").fetchone()
        return BackupMetadata(
            schema_version=self._database.schema_version(),
            database_path=str(self._database.path),
            database_size_bytes=_database_size(self._database.path),
            video_count=0 if video_row is None else int(video_row["count"]),
            analysis_run_count=0 if run_row is None else int(run_row["count"]),
            generated_at=datetime.now(UTC),
        )


def _database_size(path: Path) -> int:
    """Sum SQLite database, WAL, and shared-memory sidecar sizes."""
    candidates: Iterable[Path] = (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    return sum(candidate.stat().st_size for candidate in candidates if candidate.exists())
