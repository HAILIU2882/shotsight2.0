"""Analysis job lifecycle service tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteDatabase,
    SQLiteJobRepository,
    SQLiteVideoRepository,
)
from shotsight2.domain import AnalysisStage, JobStatus, RunStatus, Video
from shotsight2.domain.jobs import QueueMessage
from shotsight2.domain.persistence import JsonObject
from shotsight2.ports.jobs import WorkerQueue
from shotsight2.services import (
    ActiveAnalysisJobError,
    AnalysisConfiguration,
    AnalysisFailure,
    AnalysisJobService,
    InvalidAnalysisJobTransitionError,
    VideoNotReadyError,
)

NOW = datetime(2026, 6, 7, 8, 0, tzinfo=UTC)


class RecordingQueue(WorkerQueue):
    """Queue fake that can assert persistence occurred before enqueue."""

    def __init__(
        self,
        *,
        database: SQLiteDatabase,
        fail_enqueue: bool = False,
        alive_workers: frozenset[str] = frozenset(),
    ) -> None:
        self.messages: list[QueueMessage] = []
        self.enqueue_saw_persisted_job = False
        self.fail_enqueue = fail_enqueue
        self.alive_workers = alive_workers
        self.database = database

    def enqueue(self, message: QueueMessage, *, enqueued_at: datetime) -> bool:
        stored_job = SQLiteJobRepository(self.database).get(message.job_id)
        stored_run = SQLiteAnalysisRunRepository(self.database).get(message.run_id)
        self.enqueue_saw_persisted_job = stored_job is not None and stored_run is not None
        if self.fail_enqueue:
            raise RuntimeError("queue unavailable")
        self.messages.append(message)
        return True

    def claim(
        self,
        worker_id: str,
        *,
        claimed_at: datetime,
        stale_after: timedelta,
    ) -> None:
        raise NotImplementedError

    def acknowledge(self, claim: object, *, acknowledged_at: datetime) -> None:
        raise NotImplementedError

    def fail(
        self,
        claim: object,
        error: JsonObject,
        *,
        failed_at: datetime,
    ) -> None:
        raise NotImplementedError

    def heartbeat(
        self,
        worker_id: str,
        *,
        heartbeat_at: datetime,
        job_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    def stop_worker(self, worker_id: str, *, stopped_at: datetime) -> None:
        raise NotImplementedError

    def is_worker_alive(
        self,
        worker_id: str,
        *,
        checked_at: datetime,
        stale_after: timedelta,
    ) -> bool:
        return worker_id in self.alive_workers


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    result = SQLiteDatabase(tmp_path / "analysis-job.db")
    result.migrate()
    return result


@pytest.fixture
def video() -> Video:
    return Video(
        id="video-1",
        filename="training.mov",
        original_artifact_id="original-1",
        size_bytes=1_000,
        duration_seconds=60.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        container="mov",
        created_at=NOW,
    )


@pytest.fixture
def configuration() -> AnalysisConfiguration:
    return AnalysisConfiguration(
        backend_name="opencv-cpu",
        backend_version="1.0",
        values={"profile": "balanced", "sample_fps": 12},
    )


def service(database: SQLiteDatabase, queue: RecordingQueue, ids: list[str] | None = None) -> AnalysisJobService:
    id_values = ids or ["run-1", "job-1", "run-2", "job-2", "run-3", "job-3"]

    def next_id() -> str:
        return id_values.pop(0)

    return AnalysisJobService(
        videos=SQLiteVideoRepository(database),
        runs=SQLiteAnalysisRunRepository(database),
        jobs=SQLiteJobRepository(database),
        queue=queue,
        clock=lambda: NOW,
        id_factory=next_id,
    )


def seed_video(database: SQLiteDatabase, video: Video) -> None:
    SQLiteVideoRepository(database).create(video)


def test_creates_run_and_job_then_enqueues_identifier(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    queue = RecordingQueue(database=database)
    created = service(database, queue).request_analysis(video.id, configuration)

    assert queue.enqueue_saw_persisted_job
    assert queue.messages == [QueueMessage("job-1", video.id, "run-1")]
    assert created.job.status is JobStatus.QUEUED
    assert created.run.status is RunStatus.PENDING
    assert created.run.configuration == {"profile": "balanced", "sample_fps": 12}


def test_rejects_missing_non_ready_and_concurrent_analysis(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    queue = RecordingQueue(database=database)
    analysis_jobs = service(database, queue)
    with pytest.raises(VideoNotReadyError):
        analysis_jobs.request_analysis("missing", configuration)

    seed_video(database, replace(video, status=video.status.DELETING))
    with pytest.raises(VideoNotReadyError):
        analysis_jobs.request_analysis(video.id, configuration)

    SQLiteVideoRepository(database).delete(video.id)
    seed_video(database, video)
    analysis_jobs.request_analysis(video.id, configuration)
    with pytest.raises(ActiveAnalysisJobError):
        analysis_jobs.request_reanalysis(video.id, configuration)


def test_queue_enqueue_failure_becomes_durable_failure(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    queue = RecordingQueue(database=database, fail_enqueue=True)

    with pytest.raises(RuntimeError, match="queue unavailable"):
        service(database, queue).request_analysis(video.id, configuration)

    job = SQLiteJobRepository(database).get("job-1")
    run = SQLiteAnalysisRunRepository(database).get("run-1")
    assert job is not None and job.status is JobStatus.FAILED
    assert run is not None and run.status is RunStatus.FAILED
    assert job.error == {
        "category": "QUEUE_ENQUEUE_FAILED",
        "message": "queue unavailable",
        "stage": "VALIDATING",
    }


def test_progress_is_monotonic_and_terminal_transitions_record_errors(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    analysis_jobs = service(database, RecordingQueue(database=database))
    created = analysis_jobs.request_analysis(video.id, configuration)

    running = analysis_jobs.mark_running(created.job.id)
    assert running.job.status is JobStatus.RUNNING
    progress = analysis_jobs.update_progress(created.job.id, AnalysisStage.TRACKING, 0.4)
    assert progress.job.stage is AnalysisStage.TRACKING
    assert progress.run.status is RunStatus.RUNNING

    with pytest.raises(InvalidAnalysisJobTransitionError, match="monotonic"):
        analysis_jobs.update_progress(created.job.id, AnalysisStage.TRACKING, 0.3)
    with pytest.raises(ValueError, match="Cannot transition analysis stage"):
        analysis_jobs.update_progress(created.job.id, AnalysisStage.PREPROCESSING, 0.5)

    failed = analysis_jobs.mark_failed(
        created.job.id,
        AnalysisFailure(
            category="TRACKING_FAILED",
            message="tracker lost the ball",
            stage=AnalysisStage.TRACKING,
            diagnostic_reference="diag/tracking.json",
        ),
    )
    assert failed.job.status is JobStatus.FAILED
    assert failed.run.status is RunStatus.FAILED
    assert failed.job.error == {
        "category": "TRACKING_FAILED",
        "message": "tracker lost the ball",
        "stage": "TRACKING",
        "diagnostic_reference": "diag/tracking.json",
    }
    with pytest.raises(ValueError, match="Cannot transition analysis job"):
        analysis_jobs.mark_completed(created.job.id)


def test_cancel_and_completed_terminal_transitions(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    analysis_jobs = service(database, RecordingQueue(database=database))
    first = analysis_jobs.request_analysis(video.id, configuration)
    cancelled = analysis_jobs.cancel(first.job.id, message="user stopped analysis")
    assert cancelled.job.status is JobStatus.CANCELLED
    assert cancelled.run.status is RunStatus.FAILED
    assert cancelled.job.error == {
        "category": "CANCELLED",
        "message": "user stopped analysis",
        "stage": "VALIDATING",
    }

    second = analysis_jobs.request_analysis(video.id, configuration)
    analysis_jobs.update_progress(second.job.id, AnalysisStage.FINALIZING, 1.0)
    completed = analysis_jobs.mark_completed(second.job.id)
    assert completed.job.status is JobStatus.COMPLETED
    assert completed.job.progress == 1.0
    assert analysis_jobs.current_job() is None


def test_retry_failed_job_creates_new_run_without_mutating_failed_run(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    queue = RecordingQueue(database=database)
    analysis_jobs = service(database, queue)
    first = analysis_jobs.request_analysis(video.id, configuration)
    failed = analysis_jobs.mark_failed(
        first.job.id,
        AnalysisFailure("PIPELINE_FAILED", "boom", AnalysisStage.PREPROCESSING),
    )

    retry = analysis_jobs.retry_failed_job(first.job.id)

    original_job = SQLiteJobRepository(database).get(first.job.id)
    original_run = SQLiteAnalysisRunRepository(database).get(first.run.id)
    assert original_job == failed.job
    assert original_run == failed.run
    assert retry.job.id == "job-2"
    assert retry.run.id == "run-2"
    assert retry.run.configuration == failed.run.configuration
    assert queue.messages[-1] == QueueMessage("job-2", video.id, "run-2")


def test_reanalysis_after_completed_run_starts_from_stage_one(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    analysis_jobs = service(database, RecordingQueue(database=database))
    first = analysis_jobs.request_analysis(video.id, configuration)
    analysis_jobs.update_progress(first.job.id, AnalysisStage.FINALIZING, 1.0)
    analysis_jobs.mark_completed(first.job.id)

    next_configuration = AnalysisConfiguration("opencv-cpu", "1.1", {"profile": "quality"})
    second = analysis_jobs.request_reanalysis(video.id, next_configuration)

    assert second.job.stage is AnalysisStage.VALIDATING
    assert second.job.progress == 0.0
    assert second.run.configuration == {"profile": "quality"}


def test_abandoned_running_jobs_are_failed_and_worker_liveness_is_queryable(
    database: SQLiteDatabase,
    video: Video,
    configuration: AnalysisConfiguration,
) -> None:
    seed_video(database, video)
    queue = RecordingQueue(database=database, alive_workers=frozenset(("worker-1",)))
    analysis_jobs = service(database, queue)
    created = analysis_jobs.request_analysis(video.id, configuration)
    SQLiteJobRepository(database).update_state(
        created.job.id,
        JobStatus.RUNNING,
        AnalysisStage.PREPROCESSING,
        0.2,
    )
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE analysis_jobs
            SET claimed_by = ?, claimed_at = ?, heartbeat_at = ?
            WHERE id = ?
            """,
            (
                "dead-worker",
                (NOW - timedelta(minutes=10)).isoformat(),
                (NOW - timedelta(minutes=10)).isoformat(),
                created.job.id,
            ),
        )

    abandoned = analysis_jobs.mark_abandoned_running_jobs(
        checked_at=NOW,
        stale_after=timedelta(minutes=5),
    )
    liveness = analysis_jobs.worker_liveness(
        "worker-1",
        checked_at=NOW,
        stale_after=timedelta(seconds=30),
    )

    assert len(abandoned) == 1
    assert abandoned[0].job.status is JobStatus.FAILED
    assert abandoned[0].job.error == {
        "category": "WORKER_ABANDONED",
        "message": "Analysis worker stopped heartbeating before the job reached a terminal state",
        "stage": "PREPROCESSING",
        "diagnostic_reference": "dead-worker",
    }
    assert liveness.alive
    assert liveness.current_job is None
