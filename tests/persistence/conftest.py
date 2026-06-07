"""Shared records for SQLite repository contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shotsight2.adapters.persistence import SQLiteDatabase
from shotsight2.domain import AnalysisRun, AnalysisStage, RunStatus, Video

NOW = datetime(2026, 6, 7, 8, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    """Create and migrate a fresh file-backed database."""
    result = SQLiteDatabase(tmp_path / "shotsight2.db")
    result.migrate()
    return result


@pytest.fixture
def video() -> Video:
    """Return representative source-video metadata."""
    return Video(
        id="video-1",
        filename="training.mov",
        original_artifact_id="original-1",
        size_bytes=43_000_000,
        duration_seconds=180.5,
        width=3840,
        height=2160,
        fps=29.97,
        codec="hevc",
        container="mov",
        created_at=NOW,
    )


@pytest.fixture
def run(video: Video) -> AnalysisRun:
    """Return an unpublished analysis run."""
    return AnalysisRun(
        id="run-1",
        video_id=video.id,
        status=RunStatus.PENDING,
        backend_name="mlx-sam3",
        backend_version="0.1",
        configuration={"profile": "balanced", "sample_fps": 12},
        progress=0.0,
        stage=AnalysisStage.VALIDATING,
        started_at=NOW,
    )
