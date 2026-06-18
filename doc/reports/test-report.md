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
- Blocked validation remains for real MLX SAM 3 Image execution and MLX
  inter-frame benchmarking because optional packages `mlx_sam3` and `sam3` are
  not installed and no authorized local runtime bridge or weights are present.

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
