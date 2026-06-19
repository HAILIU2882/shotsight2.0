# Requirements Traceability

Last updated: 2026-06-19

This report maps the major product requirements from `doc/proposal.md` to the
implemented modules, tests, and remaining blockers. It is a release-gate audit
document, not a replacement for the detailed design.

## Status Legend

- **Implemented:** Code and tests exist on `main`.
- **Blocked:** Required external assets or runtime state are missing and are
  documented in `doc/reports/blocked.md`.
- **Deferred:** Explicitly outside the current macOS phase in `doc/prompt.md`.

## Traceability Matrix

| Requirement Area | Status | Evidence |
| --- | --- | --- |
| Local-first FastAPI app | Implemented | `src/shotsight2/main.py`, `src/shotsight2/api`, `src/shotsight2/presentation`, `tests/application_api`, `tests/presentation` |
| SQLite persistence behind repositories | Implemented | `src/shotsight2/adapters/persistence`, `tests/persistence`, `doc/tasks/persistence.md` |
| Filesystem artifact storage | Implemented | `src/shotsight2/adapters/filesystem`, `tests/artifact_store`, `doc/tasks/artifact-store.md` |
| Video upload up to configured limits | Implemented | `src/shotsight2/services/video_ingestion.py`, `tests/video_ingestion` |
| One active analysis job and worker queue | Implemented | `src/shotsight2/services/analysis_jobs.py`, `src/shotsight2/adapters/sqlite_queue.py`, `tests/analysis_job`, `tests/worker_queue` |
| Camera stability segmentation | Implemented | `src/shotsight2/services/camera_segments.py`, `tests/camera_segment` |
| Calibration and correction | Implemented | `src/shotsight2/services/calibration.py`, `tests/calibration`, presentation/API routes |
| Tracking backend selection | Implemented | `src/shotsight2/adapters/backend_probes.py`, `tests/test_tracking_backend_selection.py` |
| OpenCV fallback tracking | Implemented | `src/shotsight2/adapters/opencv/tracking.py`, `tests/tracking` |
| MLX SAM 3 Image backend validation | Implemented | `src/shotsight2/adapters/mlx_sam3.py`, `tests/tracking/test_mlx_sam3.py`, and the representative-video benchmark in `doc/tasks/tracking.md` |
| Official SAM 3.1 video backend validation | Blocked | Optional runtime/weights unavailable; see `doc/reports/blocked.md` |
| Ball/rim/player track persistence | Implemented | `src/shotsight2/domain/tracking.py`, `src/shotsight2/adapters/persistence/repositories.py`, `tests/tracking` |
| Player association and shooter attribution | Implemented | `src/shotsight2/services/track_association.py`, `tests/track_association` |
| Shot lifecycle detection | Implemented with benchmark blocked | `src/shotsight2/services/shot_lifecycle.py`, `tests/shot_lifecycle`; ground-truth benchmark labels blocked |
| Make/miss/uncertain classification | Implemented with benchmark blocked | `src/shotsight2/services/outcome_classification.py`, `tests/outcome_classification`; ground-truth labels blocked |
| Court mapping, NBA two/three, heatmap buckets | Implemented | `src/shotsight2/services/court_mapping.py`, `tests/court_mapping` |
| Replays, shot chart, heatmap, annotated video artifacts | Implemented with visual baseline blocked | `src/shotsight2/services/artifact_rendering.py`, `tests/artifact_rendering`; real-video visual baseline blocked |
| Human review and correction | Implemented | `src/shotsight2/services/review.py`, `tests/review`, API/presentation routes |
| Statistics and shot summaries | Implemented | `src/shotsight2/services/statistics.py`, `tests/statistics` |
| Complete video deletion | Implemented | `src/shotsight2/services/deletion.py`, `tests/deletion`, `tests/e2e/test_local_workflow.py` |
| Bilingual English/Chinese UI | Implemented | `src/shotsight2/presentation/i18n`, `tests/presentation` |
| End-to-end local workflow | Incomplete | Existing `tests/e2e/test_local_workflow.py` simulates analysis publication; no production worker handler or concrete stage composition exists yet |
| macOS native smoke | Implemented | `doc/reports/test-report.md` macOS native app smoke entry |
| Docker/Colima smoke | Blocked | Colima daemon not running; see `doc/reports/blocked.md` |
| Windows/Linux smoke | Deferred | Deferred by current macOS phase in `doc/prompt.md`; must not be marked complete |

## Open Release Risks

- The application is not production-ready until lifecycle/outcome benchmark
  labels, visual-render baselines, Docker/Colima smoke, and deferred
  cross-platform smoke tests are resolved.
- Current automated tests prove local service, API, presentation, and fallback
  workflow behavior, but do not prove 90-100% real-video tracking/counting
  accuracy.
