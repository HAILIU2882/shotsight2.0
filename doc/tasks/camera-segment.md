# Camera Segment Module Tasks

## Goal

Separate stable camera viewpoints from setup and camera-movement ranges.

## Dependencies

Media frame source, camera-segment repository, configuration.

## Checklist

- [x] `SEG-001` Define stable, unstable, and transition segment domain types.
- [x] `SEG-002` Implement low-resolution frame sampling for camera-motion analysis.
- [x] `SEG-003` Implement global-motion and scene-change feature extraction.
- [x] `SEG-004` Classify setup motion and mid-video camera changes.
- [x] `SEG-005` Merge short noisy classifications into stable ranges.
- [x] `SEG-006` Enforce minimum stable-segment duration.
- [x] `SEG-007` Produce stable segment start/end timestamps and confidence.
- [x] `SEG-008` Choose and store a representative frame for each stable segment.
- [x] `SEG-009` Mark unstable ranges so downstream tracking and shot logic skip them.
- [x] `SEG-010` Reset calibration and tracking scopes at every stable-segment boundary.
- [x] `SEG-011` Add tests for fixed camera, setup movement, one angle change, repeated bumps, hard cuts, and short videos.
- [x] `SEG-012` Add benchmark diagnostics showing detected boundaries over a source timeline.

## Completion Criteria

- [x] Stable segments are deterministic for the same configuration.
- [x] Downstream modules receive no continuous track across a camera change.
- [x] Boundary evaluation can be compared with manually labeled timestamps.

## Verification

- Full repository test suite after merging Persistence: 81 passed.
- Camera Segment module suite: 16 passed.
- Camera Segment coverage: 96.39%.
- `mypy --strict src/shotsight2 tests`: passed.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- Generated deterministic fixtures cover fixed camera, setup movement, one
  angle change, repeated bumps, hard cuts, short footage, representative-frame
  extraction, scope resets, and JSON timeline diagnostics with manual boundary
  evaluation.
- The service converts rich timeline ranges to the canonical persistence
  `CameraSegment` contract and round-trips them through the real file-backed
  `SQLiteCameraSegmentRepository`, retaining representative frame paths in the
  current `representative_artifact_id` field.
