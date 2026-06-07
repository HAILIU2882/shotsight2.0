# Analysis Job Module Tasks

## Goal

Own the lifecycle, progress, exclusivity, retry, and observability of analysis
jobs.

## Dependencies

Job repository, analysis-run repository, worker queue, worker health port.

## Checklist

- [ ] `JOB-001` Define job states and analysis-stage enums from the detailed design.
- [ ] `JOB-002` Define allowed state and stage transitions.
- [ ] `JOB-003` Implement job creation for a ready video.
- [ ] `JOB-004` Reject job creation while any active job exists.
- [ ] `JOB-005` Persist immutable analysis configuration with the job.
- [ ] `JOB-006` Enqueue the job identifier only after persistence succeeds.
- [ ] `JOB-007` Implement worker progress updates with monotonic progress validation.
- [ ] `JOB-008` Implement completed, failed, and cancelled terminal transitions.
- [ ] `JOB-009` Persist structured failure category, message, stage, and diagnostic reference.
- [ ] `JOB-010` Implement retry as a new full analysis run from stage one.
- [ ] `JOB-011` Detect and mark abandoned running jobs after worker restart.
- [ ] `JOB-012` Expose current job and worker-liveness query models.
- [ ] `JOB-013` Add transition, concurrency, retry, abandonment, and progress tests.

## Completion Criteria

- [ ] At most one job can be active.
- [ ] Every job reaches a durable terminal or recoverable state.
- [ ] Retry never mutates the failed run.

