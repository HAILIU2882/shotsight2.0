"""Product readiness projection from durable queue and worker state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from shotsight2.ports.jobs import ReadinessQueryError, WorkerReadinessQuery


class AvailabilityState(StrEnum):
    """Availability state shared by database and queue components."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class WorkerReadinessState(StrEnum):
    """Operational state derived from the latest persisted worker heartbeat."""

    READY = "ready"
    MISSING = "missing"
    STALE = "stale"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    """Database availability without leaking connection details."""

    status: AvailabilityState


@dataclass(frozen=True, slots=True)
class QueueReadiness:
    """Queue availability and durable active-work counts."""

    status: AvailabilityState
    queued_jobs: int | None
    running_jobs: int | None


@dataclass(frozen=True, slots=True)
class WorkerReadiness:
    """Latest worker identity and heartbeat freshness, when known."""

    status: WorkerReadinessState
    worker_id: str | None
    heartbeat_at: datetime | None
    age_seconds: float | None
    stale_after_seconds: float


@dataclass(frozen=True, slots=True)
class ProductReadiness:
    """Structured readiness report for analysis operations."""

    status: str
    checked_at: datetime
    database: DatabaseReadiness
    queue: QueueReadiness
    worker: WorkerReadiness

    @property
    def ready(self) -> bool:
        """Return whether analysis work can be accepted and processed."""
        return self.status == "ready"


class ProductReadinessService:
    """Evaluate analysis readiness while keeping web liveness independent."""

    def __init__(
        self,
        query: WorkerReadinessQuery,
        *,
        stale_after: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("Worker readiness stale timeout must be positive")
        self._query = query
        self._stale_after = stale_after
        self._clock = clock or (lambda: datetime.now(UTC))

    def check(self) -> ProductReadiness:
        """Build a failure-safe report from the latest persisted runtime state."""
        checked_at = self._clock()
        try:
            snapshot = self._query.inspect_runtime()
        except ReadinessQueryError as error:
            return self._unavailable(checked_at, database_available=error.database_available)
        except Exception:
            return self._unavailable(checked_at, database_available=False)

        worker = snapshot.latest_worker
        if worker is None:
            worker_readiness = self._worker(WorkerReadinessState.MISSING)
        elif worker.stopped_at is not None:
            worker_readiness = self._worker(
                WorkerReadinessState.STOPPED,
                worker_id=worker.worker_id,
                heartbeat_at=worker.heartbeat_at,
                checked_at=checked_at,
            )
        elif worker.heartbeat_at <= checked_at - self._stale_after:
            worker_readiness = self._worker(
                WorkerReadinessState.STALE,
                worker_id=worker.worker_id,
                heartbeat_at=worker.heartbeat_at,
                checked_at=checked_at,
            )
        else:
            worker_readiness = self._worker(
                WorkerReadinessState.READY,
                worker_id=worker.worker_id,
                heartbeat_at=worker.heartbeat_at,
                checked_at=checked_at,
            )
        ready = worker_readiness.status is WorkerReadinessState.READY
        return ProductReadiness(
            status="ready" if ready else "not_ready",
            checked_at=checked_at,
            database=DatabaseReadiness(AvailabilityState.AVAILABLE),
            queue=QueueReadiness(
                AvailabilityState.AVAILABLE,
                queued_jobs=snapshot.queued_jobs,
                running_jobs=snapshot.running_jobs,
            ),
            worker=worker_readiness,
        )

    def _unavailable(self, checked_at: datetime, *, database_available: bool) -> ProductReadiness:
        return ProductReadiness(
            status="not_ready",
            checked_at=checked_at,
            database=DatabaseReadiness(
                AvailabilityState.AVAILABLE if database_available else AvailabilityState.UNAVAILABLE
            ),
            queue=QueueReadiness(AvailabilityState.UNAVAILABLE, queued_jobs=None, running_jobs=None),
            worker=self._worker(WorkerReadinessState.UNKNOWN),
        )

    def _worker(
        self,
        status: WorkerReadinessState,
        *,
        worker_id: str | None = None,
        heartbeat_at: datetime | None = None,
        checked_at: datetime | None = None,
    ) -> WorkerReadiness:
        age_seconds = None
        if heartbeat_at is not None and checked_at is not None:
            age_seconds = max(0.0, (checked_at - heartbeat_at).total_seconds())
        return WorkerReadiness(
            status=status,
            worker_id=worker_id,
            heartbeat_at=heartbeat_at,
            age_seconds=age_seconds,
            stale_after_seconds=self._stale_after.total_seconds(),
        )
