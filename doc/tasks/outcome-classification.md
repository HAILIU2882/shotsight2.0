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

## Completion Criteria

- [x] A make requires downward rim-crossing evidence.
- [x] Uncertain evidence is never silently forced into a confident result.
- [x] Automatic and effective outcomes remain independently queryable.

## Blocked

- `OUT-010` has an evaluation interface in
  `scripts/evaluate_outcome_classification.py`, but benchmark metrics remain
  blocked because no ground-truth make/miss outcome labels and matching
  prediction file exist in the repository or documented local fixtures.
