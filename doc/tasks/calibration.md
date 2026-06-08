# Calibration Module Tasks

## Goal

Create and version automatic or user-corrected rim and NBA court calibration for
each stable camera segment.

## Dependencies

Camera segments, proposal/tracking services, calibration repository, court
mapping.

## Checklist

- [x] `CAL-001` Define calibration geometry, source, confidence, validity, and indicative-only types.
- [x] `CAL-002` Define required NBA reference points and validation constraints.
- [x] `CAL-003` Implement automatic rim proposal selection from backend observations.
- [x] `CAL-004` Implement automatic court-reference proposal ingestion.
- [x] `CAL-005` Calculate calibration confidence and reasons for uncertainty.
- [x] `CAL-006` Persist an automatic calibration for every stable segment.
- [x] `CAL-007` Fall back to indicative coordinates when a valid homography cannot be created.
- [x] `CAL-008` Validate user-corrected rim and court points.
- [x] `CAL-009` Version corrections instead of overwriting automatic calibration evidence.
- [x] `CAL-010` Trigger location and two/three-point recalculation after correction.
- [x] `CAL-011` Add tests for valid NBA geometry, incomplete markings, non-standard courts, invalid point order, and multiple camera segments.
- [x] `CAL-012` Expose representative frame and active geometry in a presentation-ready model.

## Completion Criteria

- [x] Every stable segment has an automatic or indicative calibration record.
- [x] Corrections never require rerunning object tracking.
- [x] Invalid calibration cannot produce falsely precise coordinates.

## Verification

- Full repository coverage: 93.60%.
- `uv run --extra dev --extra vision mypy --strict src tests`: passed.
- `uv run --extra dev --extra vision ruff check src tests`: passed.
- `uv run --extra dev --extra vision ruff format --check src tests`: passed.
- `git diff --check`: passed.
