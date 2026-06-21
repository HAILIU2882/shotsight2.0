# Outcome Classification Module Tasks

## Goal

Classify automatic makes, misses, and uncertain outcomes without losing the
underlying evidence.

## Dependencies

Shot lifecycle candidates, ball track, calibrated rim geometry.

## Checklist

- [x] `OUT-001` Define automatic outcome, effective outcome, confidence, and evidence models.
- [x] `OUT-002` Define the calibrated rim crossing volume in image coordinates.
- [x] `OUT-003` Detect downward entry into the rim region.
- [x] `OUT-004` Require below-rim continuation or equivalent evidence for a make.
- [x] `OUT-005` Classify completed blocked shots and air balls as misses.
- [x] `OUT-006` Classify visible non-crossing rim interactions as misses.
- [x] `OUT-007` Mark outcomes uncertain when required evidence is missing or occluded.
- [x] `OUT-008` Preserve automatic outcome and confidence after review override.
- [x] `OUT-009` Add tests for swish, rim make, backboard make, rim miss, backboard miss, air ball, blocked shot, occluded rim, and tracking loss.
- [ ] `OUT-010` Add benchmark evaluation for make/miss accuracy and uncertainty calibration.
  - `scripts/evaluate_outcome_classification.py` accepts the shared annotation
    schema, reports the explicit `excluded_unobservable_attempts` count, and
    excludes those rows from make/miss accuracy and calibration metrics.
  - Accuracy and matched-prediction rates are JSON `null` with explicit
    `*_defined: false` flags when their denominators are empty.

## Completion Criteria

- [x] A make requires downward rim-crossing evidence.
- [x] Uncertain evidence is never silently forced into a confident result.
- [x] Automatic and effective outcomes remain independently queryable.

## Blocked

- `OUT-010` has an evaluation interface in
  `scripts/evaluate_outcome_classification.py`, and the private benchmark was
  executed against 15 observable outcomes (6 made and 9 missed). The SAM3 run
  produced zero automatic attempts, leaving no matched certain predictions;
  make/miss accuracy and calibration are unavailable rather than measured at
  zero. The benchmark fails acceptance, so this item remains incomplete.

## Local Evaluation Command

After running the annotation and matching commands documented in
`doc/tasks/shot-lifecycle.md`, evaluate observable outcomes with:

```console
/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/python scripts/evaluate_outcome_classification.py --labels /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json --predictions /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/matched-predictions.json --output /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/outcome-report.json
```
