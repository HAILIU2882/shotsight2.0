# Analysis Pipeline Orchestrator Tasks

## Goal

Execute the full analysis as an ordered, observable, atomic, and replaceable
pipeline.

## Dependencies

All analysis services, repositories, artifact store, job service, backend
selection.

## Checklist

- [ ] `PIP-001` Define immutable analysis configuration and stage-result types.
- [ ] `PIP-002` Create an unpublished `AnalysisRun` and versioned run workspace.
- [ ] `PIP-003` Implement ordered stage execution from validation through finalization.
- [ ] `PIP-004` Update job stage and progress before and after each stage.
- [ ] `PIP-005` Pass identifiers and artifact references between stages instead of hidden global state.
- [ ] `PIP-006` Select and record the tracking backend before tracking begins.
- [ ] `PIP-007` Stop the pipeline when a required stage fails.
- [ ] `PIP-008` Clean temporary artifacts while preserving diagnostics and prior completed runs.
- [ ] `PIP-009` Publish structured records and final artifacts atomically.
- [ ] `PIP-010` Keep the previous completed analysis visible until new publication succeeds.
- [ ] `PIP-011` Implement full restart as a new run after failure or tracking repair.
- [ ] `PIP-012` Record stage durations, configuration, model versions, and frame counts.
- [ ] `PIP-013` Add pipeline tests with fake stage implementations for success, failure at every stage, cleanup, and republish.

## Completion Criteria

- [ ] Partial results are never presented as completed analysis.
- [ ] Every stage is independently replaceable and testable.
- [ ] A full fake pipeline passes without loading media or AI models.

