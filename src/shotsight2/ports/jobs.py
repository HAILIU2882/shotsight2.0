"""Worker queue contracts independent of SQLite and process management."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from shotsight2.domain.jobs import ClaimedJob, QueueMessage
from shotsight2.domain.persistence import JsonObject


class WorkerQueue(Protocol):
    """Durably transfer identifier-only jobs to one local worker."""

    def enqueue(self, message: QueueMessage, *, enqueued_at: datetime) -> bool: ...

    def claim(
        self,
        worker_id: str,
        *,
        claimed_at: datetime,
        stale_after: timedelta,
    ) -> ClaimedJob | None: ...

    def acknowledge(self, claim: ClaimedJob, *, acknowledged_at: datetime) -> None: ...

    def fail(
        self,
        claim: ClaimedJob,
        error: JsonObject,
        *,
        failed_at: datetime,
    ) -> None: ...

    def heartbeat(
        self,
        worker_id: str,
        *,
        heartbeat_at: datetime,
        job_id: str | None = None,
    ) -> None: ...

    def stop_worker(self, worker_id: str, *, stopped_at: datetime) -> None: ...

    def is_worker_alive(
        self,
        worker_id: str,
        *,
        checked_at: datetime,
        stale_after: timedelta,
    ) -> bool: ...
