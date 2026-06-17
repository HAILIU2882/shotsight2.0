"""SQLite contracts for tracking observations and repair prompts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteCameraSegmentRepository,
    SQLiteTrackingObservationRepository,
    SQLiteTrackingPromptRepository,
    SQLiteVideoRepository,
)
from shotsight2.adapters.persistence.database import SQLiteDatabase
from shotsight2.domain import AnalysisRun, AnalysisStage, CameraSegment, RunStatus, Video
from shotsight2.domain.tracking import (
    BoundingBox,
    ImagePoint,
    ObservationProvenance,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingPrompt,
    TrackObservation,
    VisibilityState,
)


def test_tracking_prompt_and_observation_round_trip(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "tracking.db")
    database.migrate()
    now = datetime(2026, 6, 9, tzinfo=UTC)
    video = Video("video", "clip.mov", "original", 10, 2, 200, 100, 10, "h264", "mov", now)
    run = AnalysisRun(
        "run",
        video.id,
        RunStatus.PENDING,
        "opencv-cpu",
        "1",
        {},
        0,
        AnalysisStage.TRACKING,
        now,
    )
    segment = CameraSegment("segment", run.id, 0, 2, "stable", 1)
    SQLiteVideoRepository(database).create(video)
    SQLiteAnalysisRunRepository(database).create(run)
    SQLiteCameraSegmentRepository(database).replace_for_run(run.id, [segment])
    prompt = TrackingPrompt(
        "prompt",
        segment.id,
        0.5,
        TrackedObjectClass.BASKETBALL,
        PromptKind.POINT,
        PromptSource.USER,
        point=ImagePoint(40, 30),
    )
    prompt_repository = SQLiteTrackingPromptRepository(database)
    prompt_repository.add(prompt)
    box = BoundingBox(35, 25, 10, 10)
    observation = TrackObservation(
        "observation",
        segment.id,
        5,
        0.5,
        TrackedObjectClass.BASKETBALL,
        "ball-1",
        box,
        box.centroid,
        0.91,
        VisibilityState.VISIBLE,
        False,
        ObservationProvenance("opencv-cpu", "4.13", "heuristic", "session", prompt.id, True),
    )
    observation_repository = SQLiteTrackingObservationRepository(database)
    observation_repository.replace_for_segment(segment.id, [observation])

    assert prompt_repository.list_for_segment(segment.id) == [prompt]
    assert observation_repository.list_for_segment(segment.id) == [observation]
    assert observation_repository.list_for_run(run.id) == [observation]
