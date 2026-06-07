"""Worker polling, heartbeat, logging, and CLI tests."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Protocol, cast

import pytest

from shotsight2.adapters.persistence import SQLiteDatabase, SQLiteJobRepository
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
from shotsight2.domain import JobStatus
from shotsight2.domain.jobs import QueueMessage
from shotsight2.worker.cli import _database_path, _load_handler, build_parser, main
from shotsight2.worker.process import PollingBackoff, WorkerProcess
from tests.worker_queue.conftest import NOW


class CorrelatedLogRecord(Protocol):
    """Typed view of log records carrying worker correlation extras."""

    job_id: str
    run_id: str


def importable_handler(message: QueueMessage) -> None:
    """Provide a module-level callable for CLI import tests."""
    del message


def test_worker_acknowledges_and_logs_correlated_identifiers(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful handlers receive only identifiers and emit job/run context."""
    message = QueueMessage("job-1", "video-1", "run-1")
    queue.enqueue(message, enqueued_at=NOW)
    handled: list[QueueMessage] = []
    worker = WorkerProcess(queue, handled.append, worker_id="worker-1", clock=lambda: NOW)

    with caplog.at_level(logging.INFO, logger="shotsight2.worker"):
        worker.run(once=True)

    assert handled == [message]
    completed = SQLiteJobRepository(database).get(message.job_id)
    assert completed is not None and completed.status is JobStatus.COMPLETED
    job_record = cast(
        CorrelatedLogRecord, next(record for record in caplog.records if record.message == "job_completed")
    )
    assert job_record.job_id == message.job_id
    assert job_record.run_id == message.run_id


def test_worker_heartbeats_while_handler_is_running(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
) -> None:
    """A long-running handler renews its claim from a dedicated heartbeat thread."""
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)
    started = threading.Event()
    release = threading.Event()

    def blocking_handler(message: QueueMessage) -> None:
        assert message.job_id == "job-1"
        started.set()
        release.wait(timeout=2)

    worker = WorkerProcess(
        queue,
        blocking_handler,
        worker_id="worker-1",
        stale_after=timedelta(seconds=1),
        heartbeat_interval=timedelta(milliseconds=20),
    )
    thread = threading.Thread(target=worker.run, kwargs={"once": True})
    thread.start()
    assert started.wait(timeout=1)
    claimed = SQLiteJobRepository(database).get("job-1")
    assert claimed is not None and claimed.heartbeat_at is not None
    initial_heartbeat = claimed.heartbeat_at

    time.sleep(0.08)
    renewed = SQLiteJobRepository(database).get("job-1")
    release.set()
    thread.join(timeout=2)

    assert renewed is not None and renewed.heartbeat_at is not None
    assert renewed.heartbeat_at > initial_heartbeat
    assert not thread.is_alive()


def test_worker_marks_handler_exception_failed(
    database: SQLiteDatabase,
    queue: SQLiteWorkerQueue,
) -> None:
    """Unhandled analysis errors become durable failed jobs."""
    queue.enqueue(QueueMessage("job-1", "video-1", "run-1"), enqueued_at=NOW)

    def fail_handler(message: QueueMessage) -> None:
        raise LookupError(message.run_id)

    WorkerProcess(queue, fail_handler, worker_id="worker-1", clock=lambda: NOW).run(once=True)

    failed = SQLiteJobRepository(database).get("job-1")
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert failed.error == {"type": "LookupError", "message": "run-1"}


def test_polling_backoff_is_bounded() -> None:
    """Idle polling grows exponentially without becoming an unbounded sleep."""
    backoff = PollingBackoff(initial_seconds=0.25, maximum_seconds=1.0, multiplier=2)

    delays = [backoff.initial_seconds]
    for _ in range(4):
        delays.append(backoff.next_delay(delays[-1]))

    assert delays == [0.25, 0.5, 1.0, 1.0, 1.0]


def test_worker_cli_starts_independently_from_fastapi(tmp_path: Path) -> None:
    """The module CLI migrates an empty database and exits after one idle poll."""
    database_path = tmp_path / "worker-cli.db"
    source_root = Path(__file__).parents[2] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "shotsight2.worker",
            "--database",
            str(database_path),
            "--worker-id",
            "cli-worker",
            "--once",
        ],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert database_path.exists()
    database = SQLiteDatabase(database_path)
    assert database.schema_version() == 3
    with database.read() as connection:
        worker = connection.execute(
            "SELECT stopped_at FROM worker_heartbeats WHERE worker_id = 'cli-worker'"
        ).fetchone()
    assert worker is not None and worker["stopped_at"] is not None


def test_worker_cli_wiring_and_handler_validation(tmp_path: Path) -> None:
    """Direct CLI coverage validates path parsing, imports, migration, and startup."""
    database_path = tmp_path / "direct-cli.db"
    assert _database_path("sqlite:///relative.db") == Path("relative.db")
    assert _database_path("/tmp/absolute.db") == Path("/tmp/absolute.db")
    assert build_parser().prog == "shotsight-worker"
    assert _load_handler(f"{__name__}:importable_handler") is importable_handler

    with pytest.raises(ValueError, match="module:attribute"):
        _load_handler("invalid")
    with pytest.raises(TypeError, match="not callable"):
        _load_handler(f"{__name__}:NOW")

    assert (
        main(
            [
                "--database",
                str(database_path),
                "--worker-id",
                "direct-cli-worker",
                "--once",
                "--log-level",
                "DEBUG",
            ]
        )
        == 0
    )
    assert SQLiteDatabase(database_path).schema_version() == 3
