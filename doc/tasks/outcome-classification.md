# Outcome Classification Module Tasks

## Goal

Classify automatic makes, misses, and uncertain outcomes without losing the
underlying evidence.

## Dependencies

Shot lifecycle candidates, ball track, calibrated rim geometry.

## Checklist

- [ ] `OUT-001` Define automatic outcome, effective outcome, confidence, and evidence models.
- [ ] `OUT-002` Define the calibrated rim crossing volume in image coordinates.
- [ ] `OUT-003` Detect downward entry into the rim region.
- [ ] `OUT-004` Require below-rim continuation or equivalent evidence for a make.
- [ ] `OUT-005` Classify completed blocked shots and air balls as misses.
- [ ] `OUT-006` Classify visible non-crossing rim interactions as misses.
- [ ] `OUT-007` Mark outcomes uncertain when required evidence is missing or occluded.
- [ ] `OUT-008` Preserve automatic outcome and confidence after review override.
- [ ] `OUT-009` Add tests for swish, rim make, backboard make, rim miss, backboard miss, air ball, blocked shot, occluded rim, and tracking loss.
- [ ] `OUT-010` Add benchmark evaluation for make/miss accuracy and uncertainty calibration.

## Completion Criteria

- [ ] A make requires downward rim-crossing evidence.
- [ ] Uncertain evidence is never silently forced into a confident result.
- [ ] Automatic and effective outcomes remain independently queryable.

