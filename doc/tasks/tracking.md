# Tracking Module Tasks

## Goal

Produce backend-neutral basketball, player, and rim tracks with confidence,
visibility, masks, and repair prompts.

## Dependencies

`TrackingBackend`, backend selection, camera segments, media frames, track
repositories.

## Checklist

- [x] `TRK-001` Define the `TrackingBackend` protocol and capability flags from the detailed design.
- [x] `TRK-002` Define prompt, session, frame-batch, observation, visibility, and summary models.
- [x] `TRK-003` Add contract tests reusable by every backend adapter.
- [x] `TRK-004` Implement tracking-session orchestration per stable camera segment.
- [x] `TRK-005` Generate automatic prompts for basketball, players, and rim.
- [x] `TRK-006` Persist observations with timestamps, local IDs, geometry, confidence, and provenance.
- [x] `TRK-007` Detect track loss, occlusion, and implausible identity switches.
- [x] `TRK-008` Add basketball motion, size, continuity, and body-overlap plausibility checks.
- [x] `TRK-009` Accept saved user point/box prompts at a timestamp.
- [x] `TRK-010` Reset all session state at camera-segment boundaries.
- [x] `TRK-011` Implement MLX SAM 3 Image keyframe detection adapter.
- [x] `TRK-012` Implement and benchmark a lightweight inter-frame tracker for the MLX backend.
- [x] `TRK-013` Implement the official SAM 3.1 video adapter behind optional imports.
- [x] `TRK-014` Implement the OpenCV/lightweight fallback adapter.
- [x] `TRK-015` Add backend contract tests and representative-video evaluation scripts.
- [x] `TRK-016` Record track coverage, reinitializations, and identity-switch metrics.

## Completion Criteria

- [x] All implemented and lazy-boundary backends produce the same observation contract in contract tests.
- [x] Missing optional backends do not prevent application startup.
- [x] Ball tracks can be repaired by a persisted user prompt and full reanalysis.

## Verification

- 171 tests passed.
- Full repository coverage: 91.81%.
- `PYTHONPATH=src .../pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`: passed.
- `PYTHONPATH=src .../mypy --strict src tests`: passed.
- `.../ruff check src tests scripts`: passed.
- `.../ruff format --check src tests scripts`: passed.
- Representative OpenCV fallback evaluation:
  - Command: `PYTHONPATH=src .../python scripts/evaluate_tracking.py --video /Users/hailiu/Desktop/bball_pt2.mov --maximum-seconds 30 --sampling-fps 10`
  - Video duration: 91.233 seconds.
  - Evaluated duration: 30.0 seconds at 10 FPS.
  - Elapsed time: 0.547 seconds.
  - Processing FPS: 548.33.
  - Ball track coverage: 1.0.
  - Reinitializations: 0.
  - Identity switches: 0.
  - Lost events: 0.
  - Occlusion events: 0.
  - Observation counts: basketball 300, rim 300, player 0.
  - Ground truth: unavailable, so this validates runnable metrics and pipeline behavior, not real tracking accuracy.
- Representative MLX SAM 3 evaluation on Apple Silicon:
  - Runtime: Python 3.13.12, `mlx-sam3` 0.1.0, public `mlx-community/sam3-image` weights.
  - Fresh-process setup validation: explicit source paths avoid Python 3.13's skipped editable hooks; `import shotsight2` and `import sam3` succeed outside the project directory, and the tokenizer asset is present.
  - Backend/app health smoke: the Python 3.13 MLX environment reports `mlx-sam3` ready and selected through `GET /health` without loading model weights.
  - Command: `PYTHONPATH=src .venv-mlx/bin/python scripts/evaluate_tracking.py --video data/uploads/video-3479fe147f334a3684b8f89d37efa5a5/original.mp4 --backend mlx-sam3 --maximum-seconds 5 --sampling-fps 2`.
  - Evaluated frames: 10 over 5 seconds; elapsed time: 10.03 seconds; processing rate: 1.00 FPS.
  - Ball track coverage: 0.6; basketball observations: 6; identity switches: 0.
  - A separate 17-frame diagnostic scan found compact basketball boxes with confidence up to 0.86.
  - Ground truth remains unavailable, so these metrics validate real execution, throughput, and observation plumbing rather than an accuracy claim.
