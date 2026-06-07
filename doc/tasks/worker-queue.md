# Worker Queue Module Tasks

## Goal

Deliver durable local job identifiers to one analysis worker without moving
video frames through inter-process communication.

## Dependencies

Job repository, process lifecycle utilities, configuration.

## Checklist

- [x] `QUE-001` Define the worker queue port with enqueue, claim, acknowledge, fail, and heartbeat operations.
- [x] `QUE-002` Choose and document the initial SQLite-backed claim strategy.
- [x] `QUE-003` Implement an atomic single-consumer job claim.
- [x] `QUE-004` Implement worker heartbeat persistence.
- [x] `QUE-005` Implement graceful worker startup and shutdown.
- [x] `QUE-006` Implement stale-claim detection after an unexpected worker exit.
- [x] `QUE-007` Ensure queue messages contain identifiers only.
- [x] `QUE-008` Add polling backoff so an idle worker does not busy-loop.
- [x] `QUE-009` Add process-level logging with job and run correlation IDs.
- [x] `QUE-010` Add tests for duplicate enqueue, concurrent claim attempts, worker death, restart, acknowledgement, and failure.
- [x] `QUE-011` Add a CLI command to run the worker independently from FastAPI.

## Completion Criteria

- [x] One and only one worker claims a queued job.
- [x] Restarting the worker does not lose durable job state.
- [x] No frame or model tensor is serialized through the queue.

## SQLite Claim Strategy

`SQLiteWorkerQueue.claim` uses the Persistence module's short
`BEGIN IMMEDIATE` transaction boundary. Within one write transaction it:

1. refuses a new claim while any non-stale `RUNNING` job exists;
2. selects the oldest stale `RUNNING` job before queued work;
3. updates the selected row with the worker ID, claim timestamp, and heartbeat;
4. commits before returning the identifier-only message.

This serializes concurrent claim attempts, preserves the one-active-analysis
invariant, and leaves an abruptly abandoned claim durable for recovery after
its heartbeat deadline.

## Verification

- Full suite: `pytest -p no:cacheprovider -q` passed, 78 tests.
- Queue coverage: 13 tests passed with 91.56% across the queue adapter, domain,
  port, worker process, and CLI modules (`--cov-fail-under=80`).
- `mypy --strict src/shotsight2` passed for 31 source files.
- `ruff check --no-cache .` passed.
- `ruff format --check --no-cache .` passed for 45 files.
- Tests cover duplicate enqueue, eight concurrent claim attempts, stale claim
  protection and recovery, active heartbeat renewal, graceful stop, abrupt
  child-process death and restart, acknowledge/fail state, bounded polling
  backoff, identifier-only messages, correlated logging, and independent CLI
  startup.
