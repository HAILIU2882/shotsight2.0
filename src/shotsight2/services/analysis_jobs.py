"""Route-neutral lifecycle service for local analysis jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from shotsight2.domain import AnalysisJob, AnalysisRun, AnalysisStage, JobStatus, RunStatus, VideoStatus
from shotsight2.domain.jobs import (
    ACTIVE_JOB_STATUSES,
    QueueMessage,
    validate_job_transition,
    validate_stage_transition,
)
from shotsight2.domain.persistence import JsonObject
from shotsight2.ports.jobs import WorkerQueue
from shotsight2.ports.repositories import AnalysisRunRepository, JobRepository, VideoRepository

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class AnalysisConfiguration:
    """Immutable worker configuration captured when an analysis run is requested."""

    backend_name: str
    backend_version: str
    values: JsonObject


@dataclass(frozen=True, slots=True)
class AnalysisJobSnapshot:
    """Current durable job state paired with its immutable run configuration."""

    job: AnalysisJob
    run: AnalysisRun


@dataclass(frozen=True, slots=True)
class WorkerLiveness:
    """Route-neutral worker health projection."""

    worker_id: str
    alive: bool
    checked_at: datetime
    stale_after: timedelta
    current_job: AnalysisJobSnapshot | None


@dataclass(frozen=True, slots=True)
class AnalysisFailure:
    """Structured failure details persisted for jobs and analysis runs."""

    category: str
    message: str
    stage: AnalysisStage
    diagnostic_reference: str | None = None

    def to_json(self) -> JsonObject:
        """Return deterministic diagnostics suitable for repository storage."""
        result: JsonObject = {
            "category": self.category,
            "message": self.message,
            "stage": self.stage.value,
        }
        if self.diagnostic_reference is not None:
            result["diagnostic_reference"] = self.diagnostic_reference
        return result


class AnalysisJobError(RuntimeError):
    """Base error for analysis job lifecycle violations."""


class ActiveAnalysisJobError(AnalysisJobError):
    """Raised when a new run is requested while another job is active."""


class AnalysisJobNotFoundError(AnalysisJobError):
    """Raised when a requested job does not exist."""


class AnalysisRunNotFoundError(AnalysisJobError):
    """Raised when a job points at a missing analysis run."""


class VideoNotReadyError(AnalysisJobError):
    """Raised when analysis is requested for a missing or non-ready video."""


class InvalidAnalysisJobTransitionError(AnalysisJobError):
    """Raised when a lifecycle update violates state, stage, or progress rules."""


class AnalysisJobService:
    """Own analysis job creation, progress, retry, reanalysis, and status queries."""

    def __init__(
        self,
        *,
        videos: VideoRepository,
        runs: AnalysisRunRepository,
        jobs: JobRepository,
        queue: WorkerQueue,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._videos = videos
        self._runs = runs
        self._jobs = jobs
        self._queue = queue
        self._clock = clock or _utc_now
        self._id_factory = id_factory or _uuid

    def request_analysis(self, video_id: str, configuration: AnalysisConfiguration) -> AnalysisJobSnapshot:
        """Create a fresh run for a ready video and signal the worker queue."""
        video = self._videos.get(video_id)
        if video is None or video.status is not VideoStatus.READY:
            raise VideoNotReadyError(f"Video {video_id} is not ready for analysis")
        return self._create_run_and_job(video_id, configuration)

    def request_reanalysis(self, video_id: str, configuration: AnalysisConfiguration) -> AnalysisJobSnapshot:
        """Run full analysis again from stage one for a ready video."""
        return self.request_analysis(video_id, configuration)

    def retry_failed_job(self, failed_job_id: str) -> AnalysisJobSnapshot:
        """Retry a failed job as a new analysis run without mutating the failed run."""
        failed_job = self._get_job(failed_job_id)
        if failed_job.status is not JobStatus.FAILED:
            raise InvalidAnalysisJobTransitionError("Only failed analysis jobs can be retried")
        failed_run = self._get_run(failed_job.run_id)
        configuration = AnalysisConfiguration(
            backend_name=failed_run.backend_name,
            backend_version=failed_run.backend_version,
            values=failed_run.configuration,
        )
        return self._create_run_and_job(failed_job.video_id, configuration)

    def mark_running(self, job_id: str) -> AnalysisJobSnapshot:
        """Record that a worker has started executing a queued job."""
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.RUNNING)
        self._jobs.update_state(job.id, JobStatus.RUNNING, job.stage, job.progress)
        run = self._get_run(job.run_id)
        if run.status is RunStatus.PENDING:
            self._runs.update_progress(run.id, run.progress, run.stage)
        return self._snapshot(job.id)

    def update_progress(self, job_id: str, stage: AnalysisStage, progress: float) -> AnalysisJobSnapshot:
        """Persist monotonic worker progress to both the job and its analysis run."""
        job = self._get_job(job_id)
        if job.status is JobStatus.QUEUED:
            self.mark_running(job.id)
            job = self._get_job(job.id)
        if job.status is not JobStatus.RUNNING:
            raise InvalidAnalysisJobTransitionError("Only running analysis jobs can report progress")
        if not 0 <= progress <= 1:
            raise InvalidAnalysisJobTransitionError("Progress must be between zero and one")
        if progress < job.progress:
            raise InvalidAnalysisJobTransitionError("Analysis progress must be monotonic")
        validate_stage_transition(job.stage, stage)
        self._runs.update_progress(job.run_id, progress, stage)
        self._jobs.update_state(job.id, JobStatus.RUNNING, stage, progress)
        return self._snapshot(job.id)

    def mark_completed(self, job_id: str) -> AnalysisJobSnapshot:
        """Mark the durable job completed after the pipeline publishes the run."""
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.COMPLETED)
        self._jobs.update_state(job.id, JobStatus.COMPLETED, AnalysisStage.FINALIZING, 1.0)
        return self._snapshot(job.id)

    def mark_failed(self, job_id: str, failure: AnalysisFailure) -> AnalysisJobSnapshot:
        """Durably record an analysis failure on both the job and run."""
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.FAILED)
        error = failure.to_json()
        self._runs.fail(job.run_id, error)
        self._jobs.update_state(job.id, JobStatus.FAILED, failure.stage, job.progress, error=error)
        return self._snapshot(job.id)

    def cancel(self, job_id: str, *, message: str = "Analysis job was cancelled") -> AnalysisJobSnapshot:
        """Cancel a queued or running job and preserve cancellation diagnostics."""
        job = self._get_job(job_id)
        validate_job_transition(job.status, JobStatus.CANCELLED)
        failure = AnalysisFailure(
            category="CANCELLED",
            message=message,
            stage=job.stage,
        )
        error = failure.to_json()
        self._runs.fail(job.run_id, error)
        self._jobs.update_state(job.id, JobStatus.CANCELLED, job.stage, job.progress, error=error)
        return self._snapshot(job.id)

    def mark_abandoned_running_jobs(self, *, checked_at: datetime, stale_after: timedelta) -> list[AnalysisJobSnapshot]:
        """Fail running jobs whose worker heartbeat or claim has gone stale."""
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        snapshots: list[AnalysisJobSnapshot] = []
        stale_before = checked_at - stale_after
        for job in self._jobs.list_active():
            if job.status is not JobStatus.RUNNING:
                continue
            last_seen = job.heartbeat_at or job.claimed_at or job.updated_at
            if last_seen > stale_before:
                continue
            snapshots.append(
                self.mark_failed(
                    job.id,
                    AnalysisFailure(
                        category="WORKER_ABANDONED",
                        message="Analysis worker stopped heartbeating before the job reached a terminal state",
                        stage=job.stage,
                        diagnostic_reference=job.claimed_by,
                    ),
                )
            )
        return snapshots

    def current_job(self) -> AnalysisJobSnapshot | None:
        """Return the oldest queued/running job, if one exists."""
        active = self._jobs.list_active()
        return None if not active else self._snapshot(active[0].id)

    def worker_liveness(
        self,
        worker_id: str,
        *,
        stale_after: timedelta,
        checked_at: datetime | None = None,
    ) -> WorkerLiveness:
        """Query worker liveness without exposing queue internals to routes."""
        now = checked_at or self._clock()
        return WorkerLiveness(
            worker_id=worker_id,
            alive=self._queue.is_worker_alive(worker_id, checked_at=now, stale_after=stale_after),
            checked_at=now,
            stale_after=stale_after,
            current_job=self.current_job(),
        )

    def _create_run_and_job(self, video_id: str, configuration: AnalysisConfiguration) -> AnalysisJobSnapshot:
        self._reject_active_job()
        now = self._clock()
        run_id = self._id_factory()
        job_id = self._id_factory()
        run = AnalysisRun(
            id=run_id,
            video_id=video_id,
            status=RunStatus.PENDING,
            backend_name=configuration.backend_name,
            backend_version=configuration.backend_version,
            configuration=configuration.values,
            progress=0.0,
            stage=AnalysisStage.VALIDATING,
            started_at=now,
        )
        job = AnalysisJob(
            id=job_id,
            video_id=video_id,
            run_id=run_id,
            status=JobStatus.QUEUED,
            stage=AnalysisStage.VALIDATING,
            progress=0.0,
            created_at=now,
            updated_at=now,
        )
        self._runs.create(run)
        self._jobs.create(job)
        try:
            self._queue.enqueue(QueueMessage(job_id, video_id, run_id), enqueued_at=now)
        except Exception as error:
            failure = AnalysisFailure(
                category="QUEUE_ENQUEUE_FAILED",
                message=str(error),
                stage=AnalysisStage.VALIDATING,
            )
            failure_json = failure.to_json()
            self._runs.fail(run_id, failure_json)
            self._jobs.update_state(job_id, JobStatus.FAILED, AnalysisStage.VALIDATING, 0.0, error=failure_json)
            raise
        return self._snapshot(job_id)

    def _reject_active_job(self) -> None:
        active = [job for job in self._jobs.list_active() if job.status in ACTIVE_JOB_STATUSES]
        if active:
            raise ActiveAnalysisJobError(f"Analysis job {active[0].id} is already active")

    def _get_job(self, job_id: str) -> AnalysisJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise AnalysisJobNotFoundError(job_id)
        return job

    def _get_run(self, run_id: str) -> AnalysisRun:
        run = self._runs.get(run_id)
        if run is None:
            raise AnalysisRunNotFoundError(run_id)
        return run

    def _snapshot(self, job_id: str) -> AnalysisJobSnapshot:
        job = self._get_job(job_id)
        return AnalysisJobSnapshot(job=job, run=self._get_run(job.run_id))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())
