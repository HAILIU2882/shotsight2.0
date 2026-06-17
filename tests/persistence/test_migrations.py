"""Migration, connection, transaction, and diagnostic tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from shotsight2.adapters.persistence import SQLiteDatabase, SQLiteDiagnosticRepository, SQLiteVideoRepository
from shotsight2.adapters.persistence.database import MigrationError
from shotsight2.domain import Video


def test_empty_database_upgrades_idempotently(tmp_path: Path) -> None:
    """All ordered migrations should apply exactly once."""
    database = SQLiteDatabase(tmp_path / "empty.db")

    assert database.schema_version() == 0
    assert database.migrate() == 6
    assert database.migrate() == 6

    with database.read() as connection:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        versions = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()

    assert {
        "videos",
        "analysis_runs",
        "shot_attempts",
        "review_corrections",
        "database_metadata",
        "worker_heartbeats",
        "tracking_observations",
        "tracking_prompts",
        "association_evidence_references",
    } <= tables
    assert [int(row["version"]) for row in versions] == [1, 2, 3, 4, 5, 6]


def test_missing_migrations_are_rejected(tmp_path: Path) -> None:
    """An empty migration directory must not produce an unversioned database."""
    database = SQLiteDatabase(tmp_path / "empty.db", migrations_dir=tmp_path / "missing")

    with pytest.raises(MigrationError, match="No migrations"):
        database.migrate()


def test_connection_safety_settings(database: SQLiteDatabase) -> None:
    """Connections should enable constraints and safe local concurrency."""
    with database.read() as connection:
        assert int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        assert str(connection.execute("PRAGMA journal_mode").fetchone()[0]) == "wal"
        assert int(connection.execute("PRAGMA busy_timeout").fetchone()[0]) == 5_000


def test_failed_transaction_rolls_back(database: SQLiteDatabase, video: Video) -> None:
    """A raised exception must leave no partial database state."""
    repository = SQLiteVideoRepository(database)

    with pytest.raises(RuntimeError, match="stop"):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO videos(
                    id, filename, original_artifact_id, size_bytes, duration_seconds,
                    width, height, fps, codec, container, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    video.created_at.isoformat(),
                ),
            )
            raise RuntimeError("stop")

    assert repository.get(video.id) is None


def test_foreign_keys_reject_orphans(database: SQLiteDatabase) -> None:
    """Child records cannot bypass aggregate ownership."""
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs(
                    id, video_id, status, backend_name, backend_version,
                    configuration_json, progress, stage, started_at, published
                ) VALUES ('run', 'missing', 'PENDING', 'test', '1', '{}', 0, 'VALIDATING', ?, 0)
                """,
                ("2026-06-07T08:00:00+00:00",),
            )


def test_backup_metadata_has_no_media_content(database: SQLiteDatabase, video: Video) -> None:
    """Diagnostics should report only database metadata and aggregate counts."""
    SQLiteVideoRepository(database).create(video)

    metadata = SQLiteDiagnosticRepository(database).backup_metadata()

    assert metadata.schema_version == 6
    assert metadata.video_count == 1
    assert metadata.analysis_run_count == 0
    assert metadata.database_size_bytes > 0
    assert metadata.database_path.endswith("shotsight2.db")
