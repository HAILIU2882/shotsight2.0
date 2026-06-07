"""SQLite queue correctness and recovery tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import timedelta
from pathlib import Path

import pytest

from shotsight2.adapters.persistence import SQLiteDatabase, SQLiteJobRepository
from shotsight2.adapters.sqlite_queue import ClaimLostError, SQLiteWorkerQueue
from shotsight2.domain import JobStatus
from shotsight2.domain.jobs import QueueMessage
from tests.worker_queue.conftest import NOW, seed_run


def test_messages_contain_identifiers_only() -> None:
    """Queue IPC must never gain frame, tensor, or arbitrary payload fields."""
    assert [field.name for field in fields(QueueMessage)] == ["job_id", "video_id", "run_id"]
    with pytest.raises(ValueError, match="must not be empty"):
        QueueMessage("", "video-1", "run-1")


def test_duplicate_enqueue_is_idempotent_and_conflicts_are_rejected(
    queue: SQLiteWorkerQueue,
) -> None:
    """The same durable message is accepted once without masking identifier conflicts."""
    message = QueueMessage("job-1", "video-1", "run-1")

    assert queue.enqueue(message, enqueued_at=NOW) is True
    assert queue.enqueue(message, enqueued_at=NOW) is False
    with pytest.raises(ValueError, match="already queued"):
        queue.enqueue(QueueMessage("other-job", "video-1", "run-1"), enqueued_at=NOW)


def test_concurrent_claims_allow_one_active_job(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
) -> None:
    """SQLite serialization and the live-claim guard enforce one active analysis."""
    seed_run(database, video_id="video-2", run_id="run-2")
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)
    queue.enqueue(QueueMessage("job-2", "video-2", "run-2"), enqueued_at=NOW)

    def claim(worker_number: int) -> str | None:
        result = SQLiteWorkerQueue(database).claim(
            f"worker-{worker_number}",
            claimed_at=NOW,
            stale_after=timedelta(seconds=30),
        )
        return None if result is None else result.message.job_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(claim, range(8)))

    assert [result for result in results if result is not None] == ["job-1"]
    assert [job.status for job in SQLiteJobRepository(database).list_active()] == [
        JobStatus.RUNNING,
        JobStatus.QUEUED,
    ]


def test_stale_claim_is_recovered_after_heartbeat_expires(
    queue: SQLiteWorkerQueue,
) -> None:
    """A fresh heartbeat protects ownership until its stale deadline."""
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)
    first = queue.claim("worker-1", claimed_at=NOW, stale_after=timedelta(seconds=10))
    assert first is not None

    queue.heartbeat("worker-1", heartbeat_at=NOW + timedelta(seconds=8), job_id="job-1")
    assert (
        queue.claim(
            "worker-2",
            claimed_at=NOW + timedelta(seconds=17),
            stale_after=timedelta(seconds=10),
        )
        is None
    )
    recovered = queue.claim(
        "worker-2",
        claimed_at=NOW + timedelta(seconds=19),
        stale_after=timedelta(seconds=10),
    )

    assert recovered is not None
    assert recovered.message == first.message
    assert recovered.worker_id == "worker-2"
    with pytest.raises(ClaimLostError):
        queue.acknowledge(first, acknowledged_at=NOW + timedelta(seconds=20))


def test_acknowledge_failure_and_worker_liveness_are_persisted(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
) -> None:
    """Terminal states, structured errors, and idle worker health survive reads."""
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)
    claim = queue.claim("worker-1", claimed_at=NOW, stale_after=timedelta(seconds=30))
    assert claim is not None
    queue.heartbeat("worker-1", heartbeat_at=NOW + timedelta(seconds=1), job_id="job-1")
    assert queue.is_worker_alive(
        "worker-1",
        checked_at=NOW + timedelta(seconds=2),
        stale_after=timedelta(seconds=5),
    )

    queue.fail(
        claim,
        {"code": "PIPELINE_FAILED", "retryable": False},
        failed_at=NOW + timedelta(seconds=2),
    )
    failed = SQLiteJobRepository(database).get("job-1")
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert failed.error == {"code": "PIPELINE_FAILED", "retryable": False}

    seed_run(database, video_id="video-2", run_id="run-2")
    queue.enqueue(QueueMessage("job-2", "video-2", "run-2"), enqueued_at=NOW)
    completed_claim = queue.claim(
        "worker-1",
        claimed_at=NOW + timedelta(seconds=3),
        stale_after=timedelta(seconds=30),
    )
    assert completed_claim is not None
    queue.acknowledge(completed_claim, acknowledged_at=NOW + timedelta(seconds=4))
    completed = SQLiteJobRepository(database).get("job-2")
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.progress == 1

    queue.stop_worker("worker-1", stopped_at=NOW + timedelta(seconds=5))
    assert not queue.is_worker_alive(
        "worker-1",
        checked_at=NOW + timedelta(seconds=5),
        stale_after=timedelta(seconds=30),
    )


def test_worker_death_leaves_claim_for_restart(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
) -> None:
    """An abrupt child-process exit leaves durable state that a restart reclaims."""
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)
    source_root = Path(__file__).parents[2] / "src"
    child_code = "\n".join(
        (
            "import os",
            "from datetime import UTC, datetime, timedelta",
            "from pathlib import Path",
            "from shotsight2.adapters.persistence import SQLiteDatabase",
            "from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue",
            f"database = SQLiteDatabase(Path({str(database.path)!r}))",
            "queue = SQLiteWorkerQueue(database)",
            "claim = queue.claim(",
            "    'dead-worker',",
            f"    claimed_at=datetime.fromisoformat({NOW.isoformat()!r}),",
            "    stale_after=timedelta(seconds=10),",
            ")",
            "os._exit(7 if claim is not None else 8)",
        )
    )
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    result = subprocess.run(
        [sys.executable, "-c", child_code],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 7, result.stderr
    abandoned = SQLiteJobRepository(database).get("job-1")
    assert abandoned is not None and abandoned.status is JobStatus.RUNNING

    restarted = queue.claim(
        "restarted-worker",
        claimed_at=NOW + timedelta(seconds=11),
        stale_after=timedelta(seconds=10),
    )
    assert restarted is not None
    queue.acknowledge(restarted, acknowledged_at=NOW + timedelta(seconds=12))
    completed = SQLiteJobRepository(database).get("job-1")
    assert completed is not None and completed.status is JobStatus.COMPLETED


def test_failure_json_is_deterministic(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
) -> None:
    """Failure diagnostics are serialized predictably for support logs."""
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)
    claim = queue.claim("worker-1", claimed_at=NOW, stale_after=timedelta(seconds=10))
    assert claim is not None
    queue.fail(claim, {"z": 1, "a": 2}, failed_at=NOW)

    with database.read() as connection:
        stored = connection.execute("SELECT error_json FROM analysis_jobs WHERE id = 'job-1'").fetchone()
    assert stored is not None
    assert json.loads(str(stored["error_json"])) == {"a": 2, "z": 1}
    assert str(stored["error_json"]) == '{"a":2,"z":1}'
