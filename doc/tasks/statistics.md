# Statistics Module Tasks

## Goal

Calculate deterministic aggregate results from effective shot attempts.

## Dependencies

Effective attempt query, player tracks, review corrections.

## Checklist

- [ ] `STA-001` Define video, player, shot-type, and review-status summary models.
- [ ] `STA-002` Calculate attempts, makes, misses, and shooting percentage.
- [ ] `STA-003` Define zero-attempt percentage behavior.
- [ ] `STA-004` Calculate two-point and three-point attempts, makes, and percentages.
- [ ] `STA-005` Calculate player-level breakdowns.
- [ ] `STA-006` Calculate reviewed, automatic, and low-confidence counts.
- [ ] `STA-007` Exclude deleted attempts and use latest effective corrections.
- [ ] `STA-008` Recalculate immediately after any review or calibration-dependent change.
- [ ] `STA-009` Add deterministic tests for empty, all-made, all-missed, mixed, uncertain, corrected, deleted, multiplayer, and renamed-player datasets.
- [ ] `STA-010` Expose chart-ready grouped data without presentation formatting.

## Completion Criteria

- [ ] All UI totals derive from one statistics implementation.
- [ ] Automatic evidence changes only after reanalysis; review changes affect effective totals immediately.
- [ ] Percentages and breakdowns are fully covered by unit tests.

