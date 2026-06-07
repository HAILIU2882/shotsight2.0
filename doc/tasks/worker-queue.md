# Worker Queue Module Tasks

## Goal

Deliver durable local job identifiers to one analysis worker without moving
video frames through inter-process communication.

## Dependencies

Job repository, process lifecycle utilities, configuration.

## Checklist

- [ ] `QUE-001` Define the worker queue port with enqueue, claim, acknowledge, fail, and heartbeat operations.
- [ ] `QUE-002` Choose and document the initial SQLite-backed claim strategy.
- [ ] `QUE-003` Implement an atomic single-consumer job claim.
- [ ] `QUE-004` Implement worker heartbeat persistence.
- [ ] `QUE-005` Implement graceful worker startup and shutdown.
- [ ] `QUE-006` Implement stale-claim detection after an unexpected worker exit.
- [ ] `QUE-007` Ensure queue messages contain identifiers only.
- [ ] `QUE-008` Add polling backoff so an idle worker does not busy-loop.
- [ ] `QUE-009` Add process-level logging with job and run correlation IDs.
- [ ] `QUE-010` Add tests for duplicate enqueue, concurrent claim attempts, worker death, restart, acknowledgement, and failure.
- [ ] `QUE-011` Add a CLI command to run the worker independently from FastAPI.

## Completion Criteria

- [ ] One and only one worker claims a queued job.
- [ ] Restarting the worker does not lose durable job state.
- [ ] No frame or model tensor is serialized through the queue.

