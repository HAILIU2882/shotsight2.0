# Court Mapping Module Tasks

## Goal

Map shooter release positions to NBA court coordinates or clearly labeled
indicative positions.

## Dependencies

Calibration, shooter track, shot attempts, shot-location repository.

## Checklist

- [x] `CRT-001` Define NBA court dimensions, coordinate origin, axes, and units in one domain module.
- [x] `CRT-002` Define named court regions and two-point/three-point boundaries.
- [x] `CRT-003` Estimate shooter release foot position in image coordinates.
- [x] `CRT-004` Compute and validate segment-specific homography.
- [x] `CRT-005` Transform valid release positions into court meters.
- [x] `CRT-006` Determine named region from court coordinates.
- [x] `CRT-007` Determine two-point or three-point classification.
- [x] `CRT-008` Generate normalized indicative coordinates when homography is unavailable.
- [x] `CRT-009` Mark every location as calibrated or indicative.
- [x] `CRT-010` Recompute locations after calibration, shooter, or manual location correction.
- [x] `CRT-011` Add tests for NBA corners, arc boundary, paint, midrange, half court, invalid homography, and non-standard courts.
- [x] `CRT-012` Add calibrated-location error evaluation against ground truth.

## Completion Criteria

- [x] Metric coordinates are emitted only for valid calibration.
- [x] Every attempt has a usable chart position or an explicit missing reason.
- [x] Two/three-point classification is reproducible from stored geometry.

## Verification

- 161 repository tests passed.
- Full repository coverage: 93.98%.
- `PYTHONPATH=src .../pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`: passed.
- `PYTHONPATH=src .../mypy --strict src tests`: passed.
- `.../ruff check src tests`: passed.
- `.../ruff format --check src tests`: passed.
- `git diff --check`: passed.
