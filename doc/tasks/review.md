# Review Module Tasks

## Goal

Allow complete human correction while preserving automatic predictions and
audit history.

## Dependencies

Attempt, player, correction, calibration, and location repositories; statistics.

## Checklist

- [ ] `REV-001` Define correction command, field, source, prior value, new value, and timestamp models.
- [ ] `REV-002` Implement player rename while preserving local track ID.
- [ ] `REV-003` Implement make/miss/uncertain override.
- [ ] `REV-004` Implement shooter attribution override.
- [ ] `REV-005` Implement shot-type override.
- [ ] `REV-006` Implement calibrated or indicative location override.
- [ ] `REV-007` Implement manual attempt creation with required evidence timestamps.
- [ ] `REV-008` Implement effective attempt removal without deleting automatic evidence.
- [ ] `REV-009` Build effective values from automatic records plus latest corrections.
- [ ] `REV-010` Trigger statistics recalculation after each accepted change.
- [ ] `REV-011` Order the review queue by low confidence and unresolved uncertainty.
- [ ] `REV-012` Add validation for invalid shooter, timestamp, location, type, and outcome changes.
- [ ] `REV-013` Add tests for correction history, repeated edits, undo-by-new-correction, manual attempts, removal, and aggregate updates.

## Completion Criteria

- [ ] The user can correct every requested automatic field.
- [ ] Automatic values remain available for evaluation.
- [ ] Every effective result is explainable from its correction history.

