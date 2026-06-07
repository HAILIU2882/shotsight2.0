"""Shared durable queue fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteDatabase,
    SQLiteVideoRepository,
)
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
from shotsight2.domain import AnalysisRun, AnalysisStage, RunStatus, Video

NOW = datetime(2026, 6, 7, 8, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    """Create a fresh migrated queue database."""
    result = SQLiteDatabase(tmp_path / "worker-queue.db")
    result.migrate()
    return result


def seed_run(
    database: SQLiteDatabase,
    *,
    video_id: str = "video-1",
    run_id: str = "run-1",
) -> None:
    """Create aggregate roots required by the queue foreign keys."""
    SQLiteVideoRepository(database).create(
        Video(
            id=video_id,
            filename=f"{video_id}.mov",
            original_artifact_id=f"original-{video_id}",
            size_bytes=1,
            duration_seconds=1,
            width=640,
            height=480,
            fps=30,
            codec="h264",
            container="mov",
            created_at=NOW,
        )
    )
    SQLiteAnalysisRunRepository(database).create(
        AnalysisRun(
            id=run_id,
            video_id=video_id,
            status=RunStatus.PENDING,
            backend_name="test",
            backend_version="1",
            configuration={},
            progress=0,
            stage=AnalysisStage.VALIDATING,
            started_at=NOW,
        )
    )


@pytest.fixture
def queue(database: SQLiteDatabase) -> SQLiteWorkerQueue:
    """Return a queue with one valid video and run."""
    seed_run(database)
    return SQLiteWorkerQueue(database)
