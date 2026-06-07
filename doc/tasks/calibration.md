# Calibration Module Tasks

## Goal

Create and version automatic or user-corrected rim and NBA court calibration for
each stable camera segment.

## Dependencies

Camera segments, proposal/tracking services, calibration repository, court
mapping.

## Checklist

- [ ] `CAL-001` Define calibration geometry, source, confidence, validity, and indicative-only types.
- [ ] `CAL-002` Define required NBA reference points and validation constraints.
- [ ] `CAL-003` Implement automatic rim proposal selection from backend observations.
- [ ] `CAL-004` Implement automatic court-reference proposal ingestion.
- [ ] `CAL-005` Calculate calibration confidence and reasons for uncertainty.
- [ ] `CAL-006` Persist an automatic calibration for every stable segment.
- [ ] `CAL-007` Fall back to indicative coordinates when a valid homography cannot be created.
- [ ] `CAL-008` Validate user-corrected rim and court points.
- [ ] `CAL-009` Version corrections instead of overwriting automatic calibration evidence.
- [ ] `CAL-010` Trigger location and two/three-point recalculation after correction.
- [ ] `CAL-011` Add tests for valid NBA geometry, incomplete markings, non-standard courts, invalid point order, and multiple camera segments.
- [ ] `CAL-012` Expose representative frame and active geometry in a presentation-ready model.

## Completion Criteria

- [ ] Every stable segment has an automatic or indicative calibration record.
- [ ] Corrections never require rerunning object tracking.
- [ ] Invalid calibration cannot produce falsely precise coordinates.

