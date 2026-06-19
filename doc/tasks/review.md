# Review Module Tasks

## Goal

Allow complete human correction while preserving automatic predictions and
audit history.

## Dependencies

Attempt, player, correction, calibration, and location repositories; statistics.

## Checklist

- [x] `REV-001` Define correction command, field, source, prior value, new value, and timestamp models.
- [x] `REV-002` Implement player rename while preserving local track ID.
- [x] `REV-003` Implement make/miss/uncertain override.
- [x] `REV-004` Implement shooter attribution override.
- [x] `REV-005` Implement shot-type override.
- [x] `REV-006` Implement calibrated or indicative location override.
- [x] `REV-007` Implement manual attempt creation with required evidence timestamps.
- [x] `REV-008` Implement effective attempt removal without deleting automatic evidence.
- [x] `REV-009` Build effective values from automatic records plus latest corrections.
- [x] `REV-010` Trigger statistics recalculation after each accepted change.
- [x] `REV-011` Order the review queue by low confidence and unresolved uncertainty.
- [x] `REV-012` Add validation for invalid shooter, timestamp, location, type, and outcome changes.
- [x] `REV-013` Add tests for correction history, repeated edits, undo-by-new-correction, manual attempts, removal, and aggregate updates.

## Completion Criteria

- [x] The user can correct every requested automatic field.
- [x] Automatic values remain available for evaluation.
- [x] Every effective result is explainable from its correction history.
