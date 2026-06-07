# Court Mapping Module Tasks

## Goal

Map shooter release positions to NBA court coordinates or clearly labeled
indicative positions.

## Dependencies

Calibration, shooter track, shot attempts, shot-location repository.

## Checklist

- [ ] `CRT-001` Define NBA court dimensions, coordinate origin, axes, and units in one domain module.
- [ ] `CRT-002` Define named court regions and two-point/three-point boundaries.
- [ ] `CRT-003` Estimate shooter release foot position in image coordinates.
- [ ] `CRT-004` Compute and validate segment-specific homography.
- [ ] `CRT-005` Transform valid release positions into court meters.
- [ ] `CRT-006` Determine named region from court coordinates.
- [ ] `CRT-007` Determine two-point or three-point classification.
- [ ] `CRT-008` Generate normalized indicative coordinates when homography is unavailable.
- [ ] `CRT-009` Mark every location as calibrated or indicative.
- [ ] `CRT-010` Recompute locations after calibration, shooter, or manual location correction.
- [ ] `CRT-011` Add tests for NBA corners, arc boundary, paint, midrange, half court, invalid homography, and non-standard courts.
- [ ] `CRT-012` Add calibrated-location error evaluation against ground truth.

## Completion Criteria

- [ ] Metric coordinates are emitted only for valid calibration.
- [ ] Every attempt has a usable chart position or an explicit missing reason.
- [ ] Two/three-point classification is reproducible from stored geometry.

