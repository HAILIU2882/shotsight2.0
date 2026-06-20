# Analysis Pipeline Orchestrator Tasks

## Goal

Execute the full analysis as an ordered, observable, atomic, and replaceable
pipeline.

## Dependencies

All analysis services, repositories, artifact store, job service, backend
selection.

## Checklist

- [x] `PIP-001` Define immutable analysis configuration and stage-result types.
- [x] `PIP-002` Create an unpublished `AnalysisRun` and versioned run workspace.
- [x] `PIP-003` Implement ordered stage execution from validation through finalization.
- [x] `PIP-004` Update job stage and progress before and after each stage.
- [x] `PIP-005` Pass identifiers and artifact references between stages instead of hidden global state.
- [x] `PIP-006` Select and record the tracking backend before tracking begins.
- [x] `PIP-007` Stop the pipeline when a required stage fails.
- [x] `PIP-008` Clean temporary artifacts while preserving diagnostics and prior completed runs.
- [x] `PIP-009` Publish structured records and final artifacts atomically.
- [x] `PIP-010` Keep the previous completed analysis visible until new publication succeeds.
- [x] `PIP-011` Implement full restart as a new run after failure or tracking repair.
- [x] `PIP-012` Record stage durations, configuration, model versions, and frame counts.
- [x] `PIP-013` Add pipeline tests with fake stage implementations for success, failure at every stage, cleanup, and republish.
- [x] `PIP-014` Compose the ten production stages from real local adapters without importing FastAPI.
- [x] `PIP-015` Resolve each queue message to its uploaded original and run-specific analysis proxy.
- [x] `PIP-016` Give the worker claim exclusive ownership of terminal job settlement.
- [x] `PIP-017` Compensate promoted run files when a stage or final publication fails.
- [x] `PIP-018` Add real SQLite, filesystem, FFmpeg, and worker-process integration coverage.
- [x] `PIP-019` Launch and supervise the native web and worker processes together.

## Completion Criteria

- [x] Partial results are never presented as completed analysis.
- [x] Every stage is independently replaceable and testable.
- [x] A full fake pipeline passes without loading media or AI models.
- [x] A generated no-shot video reaches atomic publication through the production worker.
- [x] Failed publication leaves no orphan non-diagnostic run artifacts.
- [x] Distinct queued videos are processed from their own uploaded media.
