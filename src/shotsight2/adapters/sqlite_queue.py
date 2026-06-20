"""SQLite-backed durable worker queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import cast

from shotsight2.adapters.persistence.database import SQLiteDatabase
from shotsight2.domain import AnalysisStage, JobStatus
from shotsight2.domain.jobs import ClaimedJob, QueueMessage, QueueRuntimeSnapshot, WorkerHeartbeatRecord
from shotsight2.domain.persistence import JsonObject
from shotsight2.ports.jobs import ReadinessQueryError


class ClaimLostError(RuntimeError):
    """Raised when a worker mutates a job it no longer owns."""


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Queue timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _message(row: sqlite3.Row) -> QueueMessage:
    return QueueMessage(
        job_id=cast(str, row["id"]),
        video_id=cast(str, row["video_id"]),
        run_id=cast(str, row["run_id"]),
    )


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Persisted worker timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


class SQLiteWorkerQueue:
    """Claim durable jobs using short ``BEGIN IMMEDIATE`` transactions.

    Claims refuse to start while another non-stale job is running. Once that
    lease expires, the stale job is recovered before newer queued work.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def enqueue(self, message: QueueMessage, *, enqueued_at: datetime) -> bool:
        """Insert a queued payload, returning false for an exact duplicate."""
        timestamp = _timestamp(enqueued_at)
        with self._database.transaction() as connection:
            existing = connection.execute(
                "SELECT id, video_id, run_id FROM analysis_jobs WHERE id = ? OR run_id = ?",
                (message.job_id, message.run_id),
            ).fetchone()
            if existing is not None:
                if _message(existing) == message:
                    return False
                raise ValueError("Job or run identifier is already queued")
            connection.execute(
                """
                INSERT INTO analysis_jobs(
                    id, video_id, run_id, status, stage, progress, error_json,
                    claimed_by, claimed_at, heartbeat_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    message.job_id,
                    message.video_id,
                    message.run_id,
                    JobStatus.QUEUED.value,
                    AnalysisStage.VALIDATING.value,
                    timestamp,
                    timestamp,
                ),
            )
        return True

    def claim(
        self,
        worker_id: str,
        *,
        claimed_at: datetime,
        stale_after: timedelta,
    ) -> ClaimedJob | None:
        """Atomically claim queued work or recover one stale running claim."""
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        now = _timestamp(claimed_at)
        stale_before = _timestamp(claimed_at - stale_after)
        with self._database.transaction() as connection:
            live = connection.execute(
                """
                SELECT 1
                FROM analysis_jobs
                WHERE status = ?
                  AND COALESCE(heartbeat_at, claimed_at, updated_at) > ?
                LIMIT 1
                """,
                (JobStatus.RUNNING.value, stale_before),
            ).fetchone()
            if live is not None:
                return None
            row = connection.execute(
                """
                SELECT id, video_id, run_id
                FROM analysis_jobs
                WHERE status = ?
                   OR (
                       status = ?
                       AND COALESCE(heartbeat_at, claimed_at, updated_at) <= ?
                   )
                ORDER BY
                    CASE WHEN status = ? THEN 0 ELSE 1 END,
                    created_at,
                    id
                LIMIT 1
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    stale_before,
                    JobStatus.RUNNING.value,
                ),
            ).fetchone()
            if row is None:
                return None
            message = _message(row)
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, claimed_by = ?, claimed_at = ?, heartbeat_at = ?,
                    error_json = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    JobStatus.RUNNING.value,
                    worker_id,
                    now,
                    now,
                    now,
                    message.job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ClaimLostError(message.job_id)
        return ClaimedJob(message=message, worker_id=worker_id, claimed_at=claimed_at)

    def acknowledge(self, claim: ClaimedJob, *, acknowledged_at: datetime) -> None:
        """Mark an owned running job completed."""
        self._finish(
            claim,
            status=JobStatus.COMPLETED,
            finished_at=acknowledged_at,
            error_json=None,
            progress=1.0,
        )

    def fail(
        self,
        claim: ClaimedJob,
        error: JsonObject,
        *,
        failed_at: datetime,
    ) -> None:
        """Mark an owned running job failed with structured diagnostics."""
        self._finish(
            claim,
            status=JobStatus.FAILED,
            finished_at=failed_at,
            error_json=json.dumps(error, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            progress=None,
        )

    def heartbeat(
        self,
        worker_id: str,
        *,
        heartbeat_at: datetime,
        job_id: str | None = None,
    ) -> None:
        """Persist process liveness and optionally renew one owned job claim."""
        timestamp = _timestamp(heartbeat_at)
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO worker_heartbeats(worker_id, started_at, heartbeat_at, stopped_at)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(worker_id) DO UPDATE SET
                    heartbeat_at = excluded.heartbeat_at,
                    stopped_at = NULL
                """,
                (worker_id, timestamp, timestamp),
            )
            if job_id is None:
                return
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND status = ? AND claimed_by = ?
                """,
                (timestamp, timestamp, job_id, JobStatus.RUNNING.value, worker_id),
            )
            if cursor.rowcount != 1:
                raise ClaimLostError(job_id)

    def stop_worker(self, worker_id: str, *, stopped_at: datetime) -> None:
        """Record a graceful process shutdown without changing durable jobs."""
        timestamp = _timestamp(stopped_at)
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO worker_heartbeats(worker_id, started_at, heartbeat_at, stopped_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    heartbeat_at = excluded.heartbeat_at,
                    stopped_at = excluded.stopped_at
                """,
                (worker_id, timestamp, timestamp, timestamp),
            )

    def is_worker_alive(
        self,
        worker_id: str,
        *,
        checked_at: datetime,
        stale_after: timedelta,
    ) -> bool:
        """Return whether the worker has a recent heartbeat and no graceful stop."""
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        stale_before = _timestamp(checked_at - stale_after)
        with self._database.read() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM worker_heartbeats
                WHERE worker_id = ? AND stopped_at IS NULL AND heartbeat_at > ?
                """,
                (worker_id, stale_before),
            ).fetchone()
        return row is not None

    def inspect_runtime(self) -> QueueRuntimeSnapshot:
        """Return durable queue counts and the latest worker lifecycle record."""
        try:
            with self._database.read() as connection:
                connection.execute("SELECT 1").fetchone()
                try:
                    counts = connection.execute(
                        """
                        SELECT
                            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS queued_jobs,
                            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS running_jobs
                        FROM analysis_jobs
                        """,
                        (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
                    ).fetchone()
                    worker = connection.execute(
                        """
                        SELECT worker_id, started_at, heartbeat_at, stopped_at
                        FROM worker_heartbeats
                        ORDER BY (stopped_at IS NULL) DESC, heartbeat_at DESC, worker_id ASC
                        LIMIT 1
                        """
                    ).fetchone()
                except sqlite3.Error as error:
                    raise ReadinessQueryError(database_available=True) from error
        except ReadinessQueryError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise ReadinessQueryError(database_available=False) from error

        latest_worker = None
        if worker is not None:
            stopped_at = cast(str | None, worker["stopped_at"])
            latest_worker = WorkerHeartbeatRecord(
                worker_id=cast(str, worker["worker_id"]),
                started_at=_datetime(cast(str, worker["started_at"])),
                heartbeat_at=_datetime(cast(str, worker["heartbeat_at"])),
                stopped_at=None if stopped_at is None else _datetime(stopped_at),
            )
        return QueueRuntimeSnapshot(
            queued_jobs=0 if counts is None else int(counts["queued_jobs"] or 0),
            running_jobs=0 if counts is None else int(counts["running_jobs"] or 0),
            latest_worker=latest_worker,
        )

    def _finish(
        self,
        claim: ClaimedJob,
        *,
        status: JobStatus,
        finished_at: datetime,
        error_json: str | None,
        progress: float | None,
    ) -> None:
        timestamp = _timestamp(finished_at)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?,
                    progress = COALESCE(?, progress),
                    error_json = ?,
                    heartbeat_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = ? AND claimed_by = ?
                """,
                (
                    status.value,
                    progress,
                    error_json,
                    timestamp,
                    timestamp,
                    claim.message.job_id,
                    JobStatus.RUNNING.value,
                    claim.worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ClaimLostError(claim.message.job_id)
