"""Polling worker lifecycle with heartbeats and graceful shutdown."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from shotsight2.domain.jobs import ClaimedJob, QueueMessage
from shotsight2.ports.jobs import WorkerQueue

LOGGER = logging.getLogger("shotsight2.worker")


@dataclass(frozen=True, slots=True)
class PollingBackoff:
    """Bounded exponential polling delay for an idle worker."""

    initial_seconds: float = 0.1
    maximum_seconds: float = 2.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.initial_seconds <= 0 or self.maximum_seconds <= 0:
            raise ValueError("Polling delays must be positive")
        if self.initial_seconds > self.maximum_seconds:
            raise ValueError("Initial polling delay cannot exceed maximum")
        if self.multiplier < 1:
            raise ValueError("Polling multiplier must be at least one")

    def next_delay(self, current: float) -> float:
        """Increase one idle delay without exceeding the configured maximum."""
        return min(current * self.multiplier, self.maximum_seconds)


class WorkerProcess:
    """Own the claim, heartbeat, execution, and completion lifecycle."""

    def __init__(
        self,
        queue: WorkerQueue,
        handler: Callable[[QueueMessage], None],
        *,
        worker_id: str,
        stale_after: timedelta = timedelta(seconds=30),
        heartbeat_interval: timedelta = timedelta(seconds=5),
        backoff: PollingBackoff | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if stale_after <= timedelta(0) or heartbeat_interval <= timedelta(0):
            raise ValueError("Worker timing intervals must be positive")
        if heartbeat_interval >= stale_after:
            raise ValueError("Heartbeat interval must be shorter than stale timeout")
        self._queue = queue
        self._handler = handler
        self._worker_id = worker_id
        self._stale_after = stale_after
        self._heartbeat_interval = heartbeat_interval
        self._backoff = backoff or PollingBackoff()
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        *,
        stop_event: threading.Event | None = None,
        once: bool = False,
    ) -> None:
        """Poll until stopped, or perform one claim attempt when ``once`` is set."""
        stopping = stop_event or threading.Event()
        delay = self._backoff.initial_seconds
        LOGGER.info("worker_started", extra={"worker_id": self._worker_id})
        self._queue.heartbeat(self._worker_id, heartbeat_at=self._clock())
        try:
            while not stopping.is_set():
                claim = self._queue.claim(
                    self._worker_id,
                    claimed_at=self._clock(),
                    stale_after=self._stale_after,
                )
                if claim is None:
                    if once:
                        break
                    if stopping.wait(delay):
                        break
                    delay = self._backoff.next_delay(delay)
                    self._queue.heartbeat(self._worker_id, heartbeat_at=self._clock())
                    continue
                delay = self._backoff.initial_seconds
                self._execute(claim)
                if once:
                    break
        finally:
            self._queue.stop_worker(self._worker_id, stopped_at=self._clock())
            LOGGER.info("worker_stopped", extra={"worker_id": self._worker_id})

    def _execute(self, claim: ClaimedJob) -> None:
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_claim,
            args=(claim, heartbeat_stop),
            name=f"shotsight-heartbeat-{self._worker_id}",
            daemon=True,
        )
        context = {
            "worker_id": self._worker_id,
            "job_id": claim.message.job_id,
            "run_id": claim.message.run_id,
        }
        LOGGER.info("job_started", extra=context)
        heartbeat.start()
        handler_error: Exception | None = None
        try:
            self._handler(claim.message)
        except Exception as error:
            handler_error = error
        finally:
            heartbeat_stop.set()
            heartbeat.join()

        if handler_error is not None:
            LOGGER.exception("job_failed", extra=context, exc_info=handler_error)
            self._queue.fail(
                claim,
                {"type": type(handler_error).__name__, "message": str(handler_error)},
                failed_at=self._clock(),
            )
        else:
            self._queue.acknowledge(claim, acknowledged_at=self._clock())
            LOGGER.info("job_completed", extra=context)

    def _heartbeat_claim(self, claim: ClaimedJob, stopping: threading.Event) -> None:
        interval = self._heartbeat_interval.total_seconds()
        while not stopping.wait(interval):
            self._queue.heartbeat(
                self._worker_id,
                heartbeat_at=self._clock(),
                job_id=claim.message.job_id,
            )
