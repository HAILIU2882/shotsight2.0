# Shot Lifecycle Engine Tasks

## Goal

Convert associated ball and player tracks into complete released shot attempts.

## Dependencies

Ball tracks, player association, rim geometry, camera-segment boundaries.

## Checklist

- [x] `SHT-001` Define lifecycle states, events, evidence, confidence, and attempt-candidate models.
- [x] `SHT-002` Implement possessed-ball state entry and exit rules.
- [x] `SHT-003` Detect release as ball separation from the associated shooter.
- [x] `SHT-004` Reject shooting motion without ball release.
- [x] `SHT-005` Track free-flight observations after release.
- [x] `SHT-006` Detect immediate blocks after a valid release.
- [x] `SHT-007` Detect rim approach and interaction windows.
- [x] `SHT-008` Detect air-ball completion away from the rim.
- [x] `SHT-009` Close attempts at a terminal result or bounded uncertainty timeout.
- [x] `SHT-010` Prevent duplicate attempts from one release lifecycle.
- [x] `SHT-011` Prevent lifecycles from crossing unstable camera ranges.
- [x] `SHT-012` Store release time, result window, raw evidence references, and confidence.
- [x] `SHT-013` Add deterministic tests for jump shots, layups, dunks, hooks, free throws, blocked shots, air balls, passes, pump fakes, and incomplete tracks.
- [ ] `SHT-014` Add benchmark evaluation for shot-event precision and recall.
  - Blocked: `scripts/evaluate_shot_lifecycle.py` provides the comparison
    interface, but no ground-truth shot-event annotation file exists yet.

## Completion Criteria

- [x] Only released balls can create automatic attempts.
- [x] Blocked shots and air balls are counted.
- [x] Every attempt is traceable to timestamped evidence.
