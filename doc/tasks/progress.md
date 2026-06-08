# ShotSight 2.0 Module Progress

## Usage

- Mark a module complete only when every checklist item and completion criterion
  in the linked module file is complete.
- Complete modules in dependency order unless a task explicitly uses a fake or
  in-memory adapter.
- Update this file in the same commit that completes a module.

## Foundation and Infrastructure

- [x] [Persistence](persistence.md)
- [x] [Artifact Store](artifact-store.md)
- [x] [Media Processing](media-processing.md)
- [x] [Worker Queue](worker-queue.md)
- [x] [Tracking Backend Selection](tracking-backend-selection.md)

## Core Application

- [x] [Video Ingestion](video-ingestion.md)
- [x] [Analysis Job](analysis-job.md)
- [x] [Video Library](video-library.md)
- [ ] [Application API](application-api.md)
- [ ] [Presentation](presentation.md)
- [x] [Deletion](deletion.md)

## Analysis Pipeline

- [x] [Camera Segment](camera-segment.md)
- [x] [Calibration](calibration.md)
- [ ] [Tracking](tracking.md)
- [ ] [Track Association](track-association.md)
- [ ] [Shot Lifecycle](shot-lifecycle.md)
- [ ] [Outcome Classification](outcome-classification.md)
- [x] [Court Mapping](court-mapping.md)
- [ ] [Artifact Rendering](artifact-rendering.md)
- [x] [Statistics](statistics.md)
- [ ] [Review](review.md)
- [ ] [Analysis Pipeline Orchestrator](analysis-pipeline.md)

## Overall Release Gates

- [ ] All 22 module checklists are complete.
- [ ] End-to-end upload, analysis, review, reanalysis, and deletion tests pass.
- [ ] Vision benchmark metrics are documented for every supported backend.
- [ ] macOS, Windows, and Linux installation smoke tests pass.
- [ ] The requirements traceability matrix has no unimplemented requirement.
