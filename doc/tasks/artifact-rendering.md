# Artifact Rendering Module Tasks

## Goal

Generate atomic, versioned replay, full-video, shot-chart, heatmap, and tracking
artifacts from stored analysis records.

## Dependencies

Media processing, artifact store, tracks, attempts, calibration, localization.

## Checklist

- [x] `RND-001` Define artifact kinds, render configuration, and version identifiers.
- [x] `RND-002` Define overlay primitives for ball, rim, players, confidence, trajectory, and events.
- [x] `RND-003` Render one replay window per attempt with bounded source timestamps.
- [x] `RND-004` Render the full annotated tracking video.
- [x] `RND-005` Render player labels using current display names.
- [x] `RND-006` Render uncertain, occluded, and tracking-lost states distinctly.
- [x] `RND-007` Generate shot-chart data and image/SVG output.
- [x] `RND-008` Generate heatmap data and output.
- [x] `RND-009` Apply the selected English or Chinese overlay locale.
- [x] `RND-010` Write raw output to temporary paths and atomically promote successful artifacts.
- [x] `RND-011` Record codec, dimensions, duration, size, configuration, and logical path.
- [x] `RND-012` Clean partial renders on failure.
- [x] `RND-013` Add tests for clipping boundaries, missing observations, localization, artifact versioning, and encode failure.
- [x] `RND-014` Add visual regression fixtures for representative overlay frames.
- [x] `RND-015` Decode the source sequentially and reuse timestamp indexes instead of seeking and scanning all observations per output frame.
- [x] `RND-016` Fail rendering explicitly when source decode ends before the complete expected frame sequence.
- [x] `RND-017` Roll back already promoted outputs and remaining temporary files when any later artifact promotion fails.
- [x] `RND-018` Bound replays around persisted lifecycle start/result evidence, with release-centered fallback for older or manual attempts.

## Completion Criteria

- [x] Every completed run has all required artifacts or fails before publication.
- [x] Rendering is reproducible from stored records without rerunning inference.
- [x] Physical paths never leak into presentation models.

## Notes

- Full-video rendering is implemented through stored tracking observations,
  deterministic overlay-frame generation, and the existing media adapter encode
  boundary.
- Deterministic SVG overlay-frame regression fixtures are covered in tests.
- A generated one-second source with audio is decoded, annotated, encoded, and
  decoded again in the test suite. The smoke verifies overlay-region pixel
  changes, duration, dimensions, and retained audio without committing media.
- Human-approved visual-regression comparison against representative real
  basketball snapshots remains blocked until approved baselines are available;
  see `doc/reports/blocked.md`.
