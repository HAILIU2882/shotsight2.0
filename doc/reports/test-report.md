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
