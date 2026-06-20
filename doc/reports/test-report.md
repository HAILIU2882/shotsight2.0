# Test Report

## Baseline

- Date: 2026-06-07
- Platform: macOS on Apple Silicon
- Python: 3.12
- Result before environment resynchronization:
  - `mypy --strict`: passed.
  - `ruff check`: passed.
  - `pytest`: collection blocked because the editable package link was missing.
  - `ruff format --check`: seven existing Python files required formatting.
- Corrective environment actions:
  - `uv sync --all-extras`
  - `uv pip install --python .venv/bin/python -e '.[vision,dev]'`
- Rerun result:
  - `mypy --strict`: passed.
  - `ruff check`: passed.
  - `pytest` and coverage: still blocked because the generated editable `.pth`
    file is present but is not added to `sys.path` by this local Python
    environment.
  - `ruff format --check`: the same seven initial scaffold files require
    formatting.

The first owning foundation module must repair the package/test configuration
and baseline formatting before its module can pass the quality gate.

## Environment Validation

- Docker CLI `29.5.3` and Colima `0.10.3` installed successfully with Homebrew.
- Colima started with 4 CPUs, 8 GB memory, and a 40 GB requested disk profile.
- Baseline Docker image `shotsight2:baseline` built successfully.
- Temporary container health response on port `4174`:
  `{"status":"ok","environment":"development","sam3_enabled":false}`.

## Required Real-Video Fixture

- Path: `/Users/hailiu/Desktop/bball_pt2.mov`
- Container: QuickTime/MOV
- Video codec: H.264
- Resolution: 640x360
- Frame rate: 60 FPS
- Duration: 91.228 seconds
- Size: 44,784,379 bytes
- Repository policy: external fixture; never copied or committed.

## Completed Module Validation

### Persistence

- Merged to `main` on 2026-06-07.
- 13 module tests passed.
- Independent coverage result: 93.62%.
- Full `mypy --strict`, Ruff lint, and formatting checks passed.
- SQLite migrations, transactions, publication, repository contracts, and
  foreign-key behavior were reviewed before merge.

### Artifact Store

- Merged to `main` on 2026-06-07.
- 17 module tests passed.
- Independent coverage result: 94.41%.
- `mypy --strict`, Ruff lint, and module formatting checks passed.
- Diff and filesystem safety behavior were reviewed before merge.

### Media Processing

- Merged to `main` on 2026-06-07.
- 22 module tests passed against generated FFmpeg fixtures.
- Independent coverage result: 93.84%.
- `mypy --strict`, Ruff lint, and module formatting checks passed.
- FFmpeg subprocess, atomic-output, and diagnostic behavior were reviewed
  before merge.

### Tracking Backend Selection

- Merged to `main` on 2026-06-07 after one review-fix cycle.
- 12 module and health-integration tests passed.
- Independent coverage result: 91.99%.
- Full `mypy --strict`, Ruff lint, and formatting checks passed.
- `/health` now reports lazy backend capability probes without importing
  optional AI packages at application startup.

### Foundation Integration

- 65 tests passed after merging Persistence, Artifact Store, Media Processing,
  and Tracking Backend Selection.
- Full strict mypy, Ruff lint, and Ruff format checks passed on the integrated
  `main` tree.

### Camera Segment

- Merged to `main` on 2026-06-08 after one review-fix cycle.
- 81 tests passed in the module worktree.
- Independent coverage result: 96.26%.
- Full `mypy --strict`, Ruff lint, and formatting checks passed.
- Review fix replaced a duplicate repository port with the canonical SQLite
  camera-segment repository contract and added a real persistence integration
  test.

### Worker Queue

- Merged to `main` on 2026-06-08 after one review-fix cycle.
- 94 tests passed in the integrated Worker Queue branch.
- Independent module coverage result: 90.87%.
- Full `mypy --strict`, Ruff lint, Ruff format, and `git diff --check`
  checks passed.
- Review fix repaired strict typing for correlated log records and removed a
  migration whitespace violation before merge.

### Worker Queue Heartbeat Fix

- Merged to `main` on 2026-06-08.
- 14 focused worker tests passed with 90.09% focused coverage.
- Full integrated gates passed after merge.
- Fix stops and joins the heartbeat thread before acknowledging or failing a
  completed job, eliminating the observed unhandled thread warning.

### Analysis Job

- Merged to `main` on 2026-06-08.
- Independent coverage result: 94.42%.
- Full `mypy --strict`, Ruff lint, Ruff format, and `git diff --check`
  checks passed.
- The service creates immutable analysis runs, enqueues identifier-only queue
  messages, enforces one active job, persists progress/errors, and implements
  retry/reanalysis as new full runs.

### Video Ingestion

- Revalidated on 2026-06-20 after replacing whole-file multipart reads in the
  API and presentation routes with direct file-stream ingestion.
- Regression tests prove the service uses configured bounded read sizes and
  removes temporary artifacts without creating database rows when a file
  stream exceeds the limit or is interrupted.
- Full validation passed with 449 tests and 91.84% coverage; strict mypy over
  149 files, Ruff lint, and Ruff format checks also passed.
- Merged to `main` on 2026-06-08 after updating against Analysis Job.
- 114 tests passed in the integrated Video Ingestion branch.
- Independent focused coverage result: 90.79%.
- Full `mypy --strict`, Ruff lint, Ruff format, and `git diff --check`
  checks passed.
- The service streams uploads into temporary artifact storage, enforces size,
  duration, and 4K limits, probes media before promotion, persists READY video
  metadata, and removes artifacts on rejection or persistence failure.

### Statistics

- Merged to `main` on 2026-06-08.
- Independent focused coverage result: 100%.
- Full `mypy --strict`, Ruff lint, Ruff format, and `git diff --check`
  checks passed.
- The module calculates correction-aware totals, player breakdowns,
  two/three-point summaries, review/low-confidence counts, and chart-ready
  grouped shot data from effective attempts.

### Video Library

- Merged to `main` on 2026-06-08 after updating against Statistics.
- 129 tests passed in the integrated Video Library branch.
- Independent focused coverage result: 95.69%.
- Full `mypy --strict`, Ruff lint, Ruff format, and `git diff --check`
  checks passed.
- The service provides read-only video cards, video details, analysis status,
  published-result summaries, safe artifact references, and storage usage
  projections.

### Calibration

- Merged to `main` on 2026-06-09 after updating against Statistics and Video
  Library.
- Independent focused coverage result: 90.30%.
- Full `mypy --strict`, Ruff lint, Ruff format, and `git diff --check`
  checks passed.
- The module versions automatic and user-corrected rim/NBA court calibration per
  stable segment, supports indicative calibration when geometry is incomplete,
  and emits a recalculation request after correction.

### Deletion

- Completed in `codex/deletion` on 2026-06-09.
- 134 tests passed in the deletion worktree.
- Integrated coverage result: 94.03%.
- Full `mypy --strict`, Ruff lint, Ruff format, coverage, and `git diff --check`
  checks passed.
- The module inventories video-owned records and filesystem artifacts, rejects
  active jobs, marks videos deleting before cleanup, preserves shared model
  assets, leaves retryable `CLEANUP_INCOMPLETE` state on artifact failure, and
  deletes database rows in dependency order after successful artifact cleanup.

### Court Mapping

- Completed in `codex/court-mapping` on 2026-06-09.
- 161 tests passed with integrated coverage of 93.98%.
- Full strict mypy, Ruff lint, Ruff format, coverage, and `git diff --check`
  checks passed.
- The module defines a rim-centered NBA court in meters, named regions and
  heatmap buckets, validates image-to-court homographies, estimates release-foot
  positions, classifies NBA two/three geometry including corner lines, provides
  indicative fallback positions, and recalculates derived locations after
  calibration or shooter changes.

### Tracking

- Partially completed in `codex/tracking` on 2026-06-17.
- 171 tests passed with integrated coverage of 91.81%.
- Full strict mypy, Ruff lint, Ruff format, and coverage gates passed.
- The module defines backend-neutral tracking prompts, frame batches, sessions,
  observations, provenance, visibility states, quality events, and metrics.
- It adds reusable backend contract tests, segment-scoped orchestration,
  automatic basketball/player/rim prompts, saved user point/box repair prompts,
  SQLite persistence for prompts and observations, OpenCV fallback tracking,
  and lazy optional boundaries for MLX SAM 3 Image and official SAM 3.1 video.
- OpenCV fallback representative-video evaluation used
  `/Users/hailiu/Desktop/bball_pt2.mov` for the first 30.0 seconds at 10 FPS:
  - Elapsed time: 0.547 seconds.
  - Processing FPS: 548.33.
  - Ball track coverage: 1.0.
  - Reinitializations: 0.
  - Identity switches: 0.
  - Lost events: 0.
  - Occlusion events: 0.
  - Observation counts: basketball 300, rim 300, player 0.
  - Ground truth was unavailable, so these metrics validate runnable processing
    and reporting, not real-world tracking accuracy.
- At the time of this 2026-06-17 run, real MLX execution was blocked. This
  historical result is superseded by the 2026-06-20 MLX integration entry below.

### Track Association

- Completed in `codex/track-association` on 2026-06-17.
- 180 tests passed with integrated coverage of 92.08%.
- Full strict mypy, Ruff lint, Ruff format, coverage, and `git diff --check`
  gates passed.
- The module defines video-local player identities, association confidence,
  deterministic `Player N` labels, adjacent-frame and compatible camera-segment
  links, possession candidates with short-gap carry, shooter attribution at
  release, explicit ambiguity flags, display-name renaming that preserves track
  IDs, and persisted shot-attribution evidence references.
- Tests cover single player, multiple players, handoff, occlusion, crossing
  players, camera change, ambiguous release, persistence, and migration
  behavior.

### Shot Lifecycle

- Partially completed in `codex/shot-lifecycle` on 2026-06-18.

- 191 tests passed with integrated coverage of 91.98%.
- Full strict mypy, Ruff lint, Ruff format, coverage, and `git diff --check`
  gates passed.
- The module defines lifecycle states, events, evidence, confidence, terminal
  lifecycle types, ignored release candidates, and ShotAttempt-compatible
  automatic candidates that defer make/miss outcome classification.
- The service consumes stable camera segments, possession frames, ball/rim
  observations, and calibration rim geometry to detect release, free flight,
  immediate blocks, rim interactions, air balls, and bounded uncertainty without
  crossing unstable camera ranges or duplicating one release lifecycle.
- Deterministic tests cover jump shots, layups, dunks, hooks, free throws,
  blocked shots, air balls, passes, pump fakes, incomplete tracks, duplicate
  rim observations, and unstable camera ranges.
- `scripts/evaluate_shot_lifecycle.py` provides the precision/recall comparison
  interface, but benchmark metrics are blocked because no ground-truth
  shot-event annotation file exists.

### Outcome Classification

- Partially completed in `codex/outcome-classification` on 2026-06-18.
- 202 tests passed with integrated coverage of 91.90%.
- Full strict mypy, Ruff lint, Ruff format, coverage, and `git diff --check`
  gates passed.
- The module defines automatic outcome evidence, component confidence, and a
  calibrated image-space rim crossing volume, then classifies lifecycle
  candidates into made, missed, or uncertain attempts without moving make/miss
  logic into Shot Lifecycle.
- Deterministic tests cover swish, rim make, backboard make, rim miss,
  backboard miss, air ball, blocked shot, occluded rim evidence, tracking loss,
  and review override independence between automatic and effective outcomes.
- `scripts/evaluate_outcome_classification.py` provides the make/miss accuracy
  and uncertainty calibration comparison interface, but benchmark metrics are
  blocked because no ground-truth outcome label file and matching prediction
  file exist.

### Artifact Rendering

- Completed in `codex/artifact-rendering` on 2026-06-19.
- 216 tests passed with integrated coverage of 91.25%.
- Full strict mypy, Ruff lint, Ruff format, coverage, and `git diff --check`
  gates passed.
- The module defines rendering artifact kinds, reproducible render
  configuration/version identifiers, localized English/Chinese overlay labels,
  overlay primitives and states, bounded replay windows, full annotated-video
  rendering through the media adapter boundary, deterministic shot-chart and
  heatmap JSON/SVG outputs, artifact-store temporary staging and promotion,
  cleanup on encode failure, metadata artifacts, and deterministic SVG overlay
  frame regression fixtures.
- True real-video visual-regression comparison against approved ground-truth
  snapshots remains blocked; deterministic overlay-frame regression is covered
  by unit tests.

### Artifact Rendering Reliability and Performance Corrections

- Completed in `codex/artifact-reliability` on 2026-06-20.
- Full-video rendering now decodes source frames sequentially and builds one
  bisect-based timestamp index for nearby observations and ball trajectories,
  eliminating per-output-frame seeks and full observation scans.
- Rendering raises an explicit incomplete-decode error if the source ends
  before every expected output frame is written.
- Multi-artifact promotion now uses compensating rollback: a later promotion
  failure removes prior promoted outputs and every remaining temporary file.
- Replay windows use persisted lifecycle possession/result evidence when valid,
  while manual, legacy, or malformed evidence conservatively falls back to the
  release-centered window.
- A generated one-second H.264/AAC smoke uses real OpenCV and FFmpeg, decodes
  the rendered output, verifies overlay-region pixel changes, checks expected
  duration and dimensions, and confirms audio retention.
- Focused command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/artifact_rendering/test_artifact_rendering.py`
  passed: 11 tests.
- Full coverage gate:
  `COVERAGE_FILE=/private/tmp/shotsight2-artifact-reliability.coverage PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`
  passed: 450 tests, total coverage 92.15%.
- `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests`
  passed: no issues in 149 source files.
- Ruff lint, Ruff format check, and `git diff --check` passed.

### Review

- Completed in `codex/review` on 2026-06-19.
- 55 new review tests; 271 total tests passed with integrated coverage of 86.72%.
- Full strict mypy, Ruff lint, Ruff format, coverage, and `git diff --check`
  gates passed on both the worktree and main after merge.
- The module defines `CorrectionField` (outcome, shooter_track_id, shot_type,
  location, removed, review_status), an append-only `ReviewService` that
  preserves automatic evidence and audit history, player display-name rename
  without track-ID change, manual attempt creation with required release
  timestamp, effective removal via `removed=True` correction, and
  `restore_attempt` undo by new correction.
- Review queue orders uncertain-unreviewed attempts first, then
  low-confidence-unreviewed, then reviewed attempts, breaking ties by release
  time.
- Extended `ShotAttemptRepository` port and `SQLiteShotAttemptRepository`
  adapter with `add_manual_attempt` so manually created shots appear in
  `list_effective` projections.
- Tests cover correction field values, queue ordering, all override operations,
  validation errors, repeated edits, undo-by-new-correction, manual attempts,
  removal/restore, aggregate updates, and SQLite integration paths.

### Analysis Pipeline Orchestrator

- Completed in `codex/analysis-pipeline` on 2026-06-19.
- 46 new pipeline tests; integrated pipeline gates passed with 84% coverage.
- Full strict mypy, Ruff lint, Ruff format, and `git diff --check` gates passed.
- The module defines `StageResult` and `PipelineContext` immutable types for
  threading identifiers and accumulated results between stages without hidden
  global state.
- `AnalysisPipelineOrchestrator` accepts a sequence of `(StageSpec, PipelineStageRunner)`
  pairs; each stage is independently injectable and replaceable without modifying
  the orchestrator.
- Progress is updated before and after each stage via a narrow `JobProgressPort`.
- Stage failure stops the pipeline immediately; failure category, message, and
  stage are persisted via `mark_failed`; temporary artifacts are cleaned with
  `preserve_diagnostics=True`.
- Atomic publication via `PublishPort.publish_completed` is called only after
  all stages succeed, ensuring the prior completed run remains visible until
  the new one is published (PIP-010).
- Full restart after failure is handled externally by
  `AnalysisJobService.retry_failed_job` — each pipeline invocation is isolated
  per run with no shared mutable state between calls.
- `DEFAULT_STAGE_SPECS` defines the 10-stage order (VALIDATING → FINALIZING)
  with progress bounds used as the default when no custom specs are provided.
- Tests cover success, failure at every stage index (parametrized 0–9), cleanup
  behavior, republish ordering, context propagation, stage duration recording,
  and `PipelineStageError` category forwarding.

### Application API

- Reconciled progress documentation on 2026-06-19 after confirming the API
  package and tests are present on `main`.
- Focused validation command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/application_api tests/presentation`
- Result: 127 focused API and Presentation tests passed.
- API tests cover error translation, video library/detail/upload/delete,
  analysis start/status, job lookup, segment calibration correction, player
  rename, attempt CRUD, tracking prompt submission, artifact streaming with
  range requests, language preferences, route registration, and OpenAPI
  structure.

### Presentation

- Reconciled progress documentation on 2026-06-19 after confirming the
  Presentation checklist was complete and focused tests passed.
- The local virtual environment was missing the already-declared `jinja2`
  dependency, so `uv pip install --python .venv/bin/python 'jinja2>=3.1,<4'`
  installed `jinja2==3.1.6` and `markupsafe==3.0.3`.
- Focused validation command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/application_api tests/presentation`
- Result: 127 focused API and Presentation tests passed.
- Presentation tests cover package registration, shell and locale switching,
  translation completeness, library, upload, video detail, analysis progress,
  calibration, players, attempt review, statistics/artifact links, tracking
  repair, deletion confirmation, and accessibility/error states.

### Artifact Rendering Duplicate Destination Guard

- Patched on `main` on 2026-06-19.
- Added a duplicate destination guard before any staged rendering artifact is
  promoted, preventing distinct attempt IDs that sanitize to the same replay
  filename from publishing a partial artifact set.
- Added a regression test for two colliding replay destination names.
- Focused validation command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/artifact_rendering/test_artifact_rendering.py`
- Result: 7 Artifact Rendering tests passed.

### Main Quality Gate After Documentation Reconciliation

- Run on 2026-06-19 after reconciling Application API/Presentation progress
  docs, adding the Artifact Rendering duplicate destination guard, and adding
  an explicit `ReviewStatus` export from `shotsight2.domain.review`.
- Local environment note: the virtual environment was missing the declared
  `jinja2` dependency; `uv pip install --python .venv/bin/python 'jinja2>=3.1,<4'`
  installed `jinja2==3.1.6` and `markupsafe==3.0.3`.
- `COVERAGE_FILE=/private/tmp/shotsight2-main-continue.coverage PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`
  passed: 437 tests passed, total coverage 91.95%.
- `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests`
  passed: no issues in 145 source files.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff check src tests scripts`
  passed.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff format --check src tests scripts`
  passed.
- `git diff --check` passed.

### End-to-End Local Workflow Release Gate

- Added on 2026-06-19 in `tests/e2e/test_local_workflow.py`.
- The test uses a migrated SQLite database and the real filesystem artifact
  store, with only media probing and queue delivery faked to avoid requiring a
  real uploaded video file or live worker process.
- Covered workflow:
  upload source bytes, persist original artifact, request analysis, publish a
  completed run, apply review correction and player rename, request
  reanalysis, publish a second completed run, verify only the newest run is
  effective, build deletion inventory, delete video-owned records and
  filesystem artifacts.
- Focused validation command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/e2e/test_local_workflow.py`
- Result: 1 end-to-end release-gate test passed.
- Additional checks run after adding the test:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests`
  passed with no issues in 147 source files, and
  `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff check tests/e2e/test_local_workflow.py`
  passed.

### Final Main Quality Gate With E2E

- Run on 2026-06-19 after adding the end-to-end release-gate workflow test.
- `COVERAGE_FILE=/private/tmp/shotsight2-main-e2e.coverage PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`
  passed: 438 tests passed, total coverage 91.95%.
- `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests`
  passed: no issues in 147 source files.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff check src tests scripts`
  passed.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff format --check src tests scripts`
  passed.
- `git diff --check` passed.

### macOS Native App Smoke

- Run on 2026-06-19 with the local virtual environment.
- Command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/python -c 'from fastapi.testclient import TestClient; from shotsight2.main import create_app; c=TestClient(create_app()); r=c.get("/health"); print(r.status_code); print(r.text[:300])'`
- Result: `/health` returned HTTP 200 on Darwin arm64 with Python 3.12.12.
- The health payload reported optional SAM/MLX backends as unavailable, which
  matches the current blocked-work entries.

### Local Runtime Wiring Fix

- Patched on 2026-06-19 after the running app returned HTTP 500 for `GET /`.
- Root cause: `create_app()` registered API and Presentation routes but did not
  install concrete dependency overrides for services such as
  `VideoLibraryService`; production startup was still reaching the
  `NotImplementedError` provider stubs in `shotsight2.api.deps`.
- Fix: `shotsight2.main.create_app()` now owns a `LocalRuntime` with migrated
  SQLite storage, filesystem artifact storage, FFmpeg media adapter, queue,
  repositories, and concrete application services. The app stores this runtime
  on `application.state.runtime` and wires the service/media/artifact
  dependencies through FastAPI overrides.
- Added `tests/test_app_runtime.py` to render `/` and `/health` through the real
  app factory without test-only service overrides.
- Focused validation command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/test_app_runtime.py tests/test_health.py tests/presentation/test_presentation.py`
- Result: 68 focused tests passed.
- Full validation:
  `COVERAGE_FILE=/private/tmp/shotsight2-runtime.coverage PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`
  passed: 440 tests passed, total coverage 92.22%.
- `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests`
  passed: no issues in 148 source files.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff check src tests scripts`
  passed.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff format --check src tests scripts`
  passed.
- `git diff --check` passed.
- Local server smoke: `curl -i http://127.0.0.1:4173/` returned HTTP 200 and
  rendered the Video Library empty state.

### Upload Redirect HTML Route Fix

- Patched on 2026-06-19 after a successful upload redirected to
  `GET /videos/{video_id}` and displayed raw JSON instead of the server-rendered
  video detail page.
- Root cause: both the Application API and Presentation layer registered
  `GET /videos/{video_id}`. In the combined local app, API routes were attached
  before presentation routes, so the upload redirect matched the JSON API route
  first.
- Fix: `create_app()` now registers the Presentation layer before the API
  routers in the combined local runtime. Standalone API tests still call
  `register_routes()` directly, so the API contract remains covered.
- Added a regression to `tests/test_app_runtime.py` that seeds a real SQLite
  video record through the app runtime and verifies `GET /videos/{id}` returns
  `text/html` with the Video Detail page.
- Focused validation command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/test_app_runtime.py tests/test_health.py tests/presentation/test_presentation.py`
- Result: 69 focused tests passed.
- Full product-readiness gate run:
  `COVERAGE_FILE=/private/tmp/shotsight2-product-readiness.coverage PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`
  passed: 441 tests passed, total coverage 92.22%.
- `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests`
  passed: no issues in 148 source files.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff check src tests scripts`
  passed.
- `/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff format --check src tests scripts`
  passed.
- `git diff --check` passed.
- Local server smoke:
  `curl -i http://127.0.0.1:4173/videos/video-3479fe147f334a3684b8f89d37efa5a5`
  returned HTTP 200 with `content-type: text/html; charset=utf-8` and rendered
  the uploaded `bball_pt2.mov` detail page.
- Remaining release blockers observed during this 2026-06-19 pass:
  - MLX was unavailable at that time; resolved by the 2026-06-20 integration.
  - Docker CLI available, but `colima status` still reports
    `colima is not running`.

### Docker/Colima Smoke

- Attempted on 2026-06-19.
- `docker --version` passed with Docker version 29.5.3.
- `which colima` found `/opt/homebrew/bin/colima`.
- `colima status` failed with `colima is not running`.
- `docker build -t shotsight2-smoke:local .` failed because Docker could not
  connect to `/Users/hailiu/.colima/default/docker.sock`.
- Result: Docker/Colima smoke remains blocked by local daemon state; see
  `doc/reports/blocked.md`.

### Requirements Traceability Audit

- Added on 2026-06-19 in `doc/reports/requirements-traceability.md`.
- The matrix maps product requirement areas to implementation evidence and
  explicitly identifies blocked or deferred requirements.
- Result: no requirement is silently omitted. After the 2026-06-20 MLX
  integration, the release gate remains unchecked for ground-truth benchmark
  labels, visual-render baselines, Docker/Colima smoke, and Windows/Linux smoke.

### Apple Silicon MLX SAM 3 Integration

- Completed on 2026-06-20 using Python 3.13.12 and `mlx-sam3` 0.1.0 on Apple Silicon.
- Added a concrete, lazily imported MLX runtime that adapts upstream image detections into ShotSight sessions, prompts, observations, confidence, provenance, and segment metrics.
- Added spatial inter-frame association and point-to-box prompt adaptation because the upstream MLX image port has no native video memory or point-prompt method.
- Corrected backend discovery from the nonexistent `mlx_sam3` import to the upstream `sam3` module and allowed documented first-run weight download from `mlx-community/sam3-image`.
- Added reproducible `scripts/setup-mlx.sh` and `scripts/run-mlx.sh`. Setup uses an ignored pinned editable checkout because the upstream wheel omits its tokenizer asset.
- Real app health smoke in `.venv-mlx`: HTTP 200, selected backend `mlx-sam3`, backend state `ready`.
- Real model smoke loaded the public 3.5 GB weights and processed uploaded basketball frames. A 17-frame scan produced compact basketball detections with confidence up to 0.86.
- Repeatable five-second benchmark: 10 sampled frames, 10.03 seconds elapsed, 1.00 processing FPS, 0.6 ball coverage, six basketball observations, and zero reported identity switches.
- Full validation: 446 tests passed with 91.83% total coverage; strict mypy passed for 149 source files; Ruff lint and format checks passed; `git diff --check` passed.
- No ground-truth ball labels exist yet, so this closes runtime implementation and execution tasks without claiming tracking accuracy.

### Production Analysis Worker Corrective Integration

- Completed on 2026-06-20 with a FastAPI-free production worker composition.
- The worker now resolves each `QueueMessage` through SQLite to that video's
  original artifact, creates a run-specific proxy, and executes validation,
  preprocessing, camera segmentation, automatic calibration, tracking, shot
  detection/outcome classification, indicative mapping, rendering, statistics,
  and finalization in order.
- Terminal ownership is exact: the pipeline updates run progress and
  publication/failure, while `WorkerProcess` alone acknowledges or fails its
  claimed job. No production path marks the same claim terminal twice.
- Promoted proxy, calibration-frame, track, and render outputs are compensated
  after a failed stage or publication. Successful runs retain published files
  and remove temporary work; failed runs may retain only diagnostic reports.
- `scripts/run.sh` and `scripts/run-mlx.sh` now use `scripts/run-native.sh` to
  supervise the web server and worker as one native application lifecycle.

Focused real-adapter validation:

- Command:
  `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q tests/e2e/test_production_pipeline.py tests/analysis_pipeline tests/worker_queue -vv`
- Result: 66 tests passed, including four production-worker integrations and
  cleanup-error settlement regressions.
- A generated 2.4-second, 160x90 no-shot video produced one or more stable
  camera records, zero attempts, a published completed run, analysis proxy,
  tracking data, annotated video, chart/heatmap outputs, and render metadata.
- A corrupt uploaded artifact failed both its job and run without
  `ClaimLostError`.
- Sequential 160x90 and 128x96 uploads produced annotated videos at exactly
  their own dimensions, proving job-bound media resolution.
- An injected publication failure after real rendering left the video inventory
  with only its original upload and no published artifact rows.

Native process smoke:

- `scripts/run-native.sh` started Uvicorn on `127.0.0.1:4187` and a separate
  worker against an isolated temporary database.
- `GET /health` returned HTTP 200; SQLite reported the worker heartbeat as
  active.
- One `Ctrl-C` stopped both processes, the worker logged `worker_stopped`,
  SQLite recorded `stopped_at`, and port 4187 no longer accepted connections.

Full quality gates:

- `PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`
  passed: 450 tests, 92.51% total coverage.
- Strict mypy passed with no issues in 152 source files.
- Ruff lint passed; Ruff format check reported 155 files formatted.
- Native shell syntax checks and `git diff --check` passed.
