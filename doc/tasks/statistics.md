# Statistics Module Tasks

## Goal

Calculate deterministic aggregate results from effective shot attempts.

## Dependencies

Effective attempt query, player tracks, review corrections.

## Checklist

- [x] `STA-001` Define video, player, shot-type, and review-status summary models.
- [x] `STA-002` Calculate attempts, makes, misses, and shooting percentage.
- [x] `STA-003` Define zero-attempt percentage behavior.
- [x] `STA-004` Calculate two-point and three-point attempts, makes, and percentages.
- [x] `STA-005` Calculate player-level breakdowns.
- [x] `STA-006` Calculate reviewed, automatic, and low-confidence counts.
- [x] `STA-007` Exclude deleted attempts and use latest effective corrections.
- [x] `STA-008` Recalculate immediately after any review or calibration-dependent change.
- [x] `STA-009` Add deterministic tests for empty, all-made, all-missed, mixed, uncertain, corrected, deleted, multiplayer, and renamed-player datasets.
- [x] `STA-010` Expose chart-ready grouped data without presentation formatting.

## Completion Criteria

- [x] All UI totals derive from one statistics implementation.
- [x] Automatic evidence changes only after reanalysis; review changes affect effective totals immediately.
- [x] Percentages and breakdowns are fully covered by unit tests.
