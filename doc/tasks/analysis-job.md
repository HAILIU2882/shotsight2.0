# Analysis Job Module Tasks

## Goal

Own the lifecycle, progress, exclusivity, retry, and observability of analysis
jobs.

## Dependencies

Job repository, analysis-run repository, worker queue, worker health port.

## Checklist

- [x] `JOB-001` Define job states and analysis-stage enums from the detailed design.
- [x] `JOB-002` Define allowed state and stage transitions.
- [x] `JOB-003` Implement job creation for a ready video.
- [x] `JOB-004` Reject job creation while any active job exists.
- [x] `JOB-005` Persist immutable analysis configuration with the job.
- [x] `JOB-006` Enqueue the job identifier only after persistence succeeds.
- [x] `JOB-007` Implement worker progress updates with monotonic progress validation.
- [x] `JOB-008` Implement completed, failed, and cancelled terminal transitions.
- [x] `JOB-009` Persist structured failure category, message, stage, and diagnostic reference.
- [x] `JOB-010` Implement retry as a new full analysis run from stage one.
- [x] `JOB-011` Detect and mark abandoned running jobs after worker restart.
- [x] `JOB-012` Expose current job and worker-liveness query models.
- [x] `JOB-013` Add transition, concurrency, retry, abandonment, and progress tests.

## Completion Criteria

- [x] At most one job can be active.
- [x] Every job reaches a durable terminal or recoverable state.
- [x] Retry never mutates the failed run.

## Evidence

- `uv run --extra dev --extra vision pytest --cov=shotsight2.services.analysis_jobs --cov=shotsight2.domain.jobs --cov-fail-under=80`: 102 passed, analysis-job module coverage 94%.
- `uv run --extra dev --extra vision mypy --strict src tests`: no issues found.
- `uv run --extra dev ruff check .`: all checks passed.
- `uv run --extra dev ruff format --check .`: 58 files already formatted.
- `git diff --check`: passed.
