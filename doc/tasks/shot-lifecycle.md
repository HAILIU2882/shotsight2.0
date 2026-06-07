# Shot Lifecycle Engine Tasks

## Goal

Convert associated ball and player tracks into complete released shot attempts.

## Dependencies

Ball tracks, player association, rim geometry, camera-segment boundaries.

## Checklist

- [ ] `SHT-001` Define lifecycle states, events, evidence, confidence, and attempt-candidate models.
- [ ] `SHT-002` Implement possessed-ball state entry and exit rules.
- [ ] `SHT-003` Detect release as ball separation from the associated shooter.
- [ ] `SHT-004` Reject shooting motion without ball release.
- [ ] `SHT-005` Track free-flight observations after release.
- [ ] `SHT-006` Detect immediate blocks after a valid release.
- [ ] `SHT-007` Detect rim approach and interaction windows.
- [ ] `SHT-008` Detect air-ball completion away from the rim.
- [ ] `SHT-009` Close attempts at a terminal result or bounded uncertainty timeout.
- [ ] `SHT-010` Prevent duplicate attempts from one release lifecycle.
- [ ] `SHT-011` Prevent lifecycles from crossing unstable camera ranges.
- [ ] `SHT-012` Store release time, result window, raw evidence references, and confidence.
- [ ] `SHT-013` Add deterministic tests for jump shots, layups, dunks, hooks, free throws, blocked shots, air balls, passes, pump fakes, and incomplete tracks.
- [ ] `SHT-014` Add benchmark evaluation for shot-event precision and recall.

## Completion Criteria

- [ ] Only released balls can create automatic attempts.
- [ ] Blocked shots and air balls are counted.
- [ ] Every attempt is traceable to timestamped evidence.

