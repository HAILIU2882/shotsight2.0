# Camera Segment Module Tasks

## Goal

Separate stable camera viewpoints from setup and camera-movement ranges.

## Dependencies

Media frame source, camera-segment repository, configuration.

## Checklist

- [ ] `SEG-001` Define stable, unstable, and transition segment domain types.
- [ ] `SEG-002` Implement low-resolution frame sampling for camera-motion analysis.
- [ ] `SEG-003` Implement global-motion and scene-change feature extraction.
- [ ] `SEG-004` Classify setup motion and mid-video camera changes.
- [ ] `SEG-005` Merge short noisy classifications into stable ranges.
- [ ] `SEG-006` Enforce minimum stable-segment duration.
- [ ] `SEG-007` Produce stable segment start/end timestamps and confidence.
- [ ] `SEG-008` Choose and store a representative frame for each stable segment.
- [ ] `SEG-009` Mark unstable ranges so downstream tracking and shot logic skip them.
- [ ] `SEG-010` Reset calibration and tracking scopes at every stable-segment boundary.
- [ ] `SEG-011` Add tests for fixed camera, setup movement, one angle change, repeated bumps, hard cuts, and short videos.
- [ ] `SEG-012` Add benchmark diagnostics showing detected boundaries over a source timeline.

## Completion Criteria

- [ ] Stable segments are deterministic for the same configuration.
- [ ] Downstream modules receive no continuous track across a camera change.
- [ ] Boundary evaluation can be compared with manually labeled timestamps.

