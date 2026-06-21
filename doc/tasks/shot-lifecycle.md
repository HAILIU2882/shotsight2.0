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
  - `scripts/annotate_shots.py` and `scripts/match_shot_predictions.py` provide
    the local annotation and deterministic timestamp-matching workflow.
  - `scripts/evaluate_shot_lifecycle.py` counts every annotated release,
    including releases whose outcome is `UNOBSERVABLE`.
  - When predictions are empty but ground truth is not, precision is JSON
    `null` with `precision_defined: false`; recall remains numeric. Empty truth
    and empty predictions use the documented perfect-agreement convention of
    precision and recall both equal to `1.0`.
  - The private SAM3 benchmark was executed, but acceptance failed: 15 human
    releases produced zero automatic attempts, so precision is unavailable and
    recall is `0.0`. This item remains incomplete.

## Local Benchmark Workflow

Ground truth is intentionally private and outside Git at
`/Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json`.

```console
mkdir -p /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2
/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/python scripts/annotate_shots.py --video /Users/hailiu/Desktop/bball_pt2.mov --output /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json
/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/python scripts/match_shot_predictions.py --annotations /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json --automatic-attempts /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/automatic-attempts.json --output /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/matched-predictions.json --tolerance-seconds 0.25
/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/python scripts/evaluate_shot_lifecycle.py --annotations /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json --predictions /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/matched-predictions.json --tolerance-seconds 0.25 --output /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/lifecycle-report.json
```

## Completion Criteria

- [x] Only released balls can create automatic attempts.
- [x] Blocked shots and air balls are counted.
- [x] Every attempt is traceable to timestamped evidence.
