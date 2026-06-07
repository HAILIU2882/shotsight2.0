# Artifact Rendering Module Tasks

## Goal

Generate atomic, versioned replay, full-video, shot-chart, heatmap, and tracking
artifacts from stored analysis records.

## Dependencies

Media processing, artifact store, tracks, attempts, calibration, localization.

## Checklist

- [ ] `RND-001` Define artifact kinds, render configuration, and version identifiers.
- [ ] `RND-002` Define overlay primitives for ball, rim, players, confidence, trajectory, and events.
- [ ] `RND-003` Render one replay window per attempt with bounded source timestamps.
- [ ] `RND-004` Render the full annotated tracking video.
- [ ] `RND-005` Render player labels using current display names.
- [ ] `RND-006` Render uncertain, occluded, and tracking-lost states distinctly.
- [ ] `RND-007` Generate shot-chart data and image/SVG output.
- [ ] `RND-008` Generate heatmap data and output.
- [ ] `RND-009` Apply the selected English or Chinese overlay locale.
- [ ] `RND-010` Write raw output to temporary paths and atomically promote successful artifacts.
- [ ] `RND-011` Record codec, dimensions, duration, size, configuration, and logical path.
- [ ] `RND-012` Clean partial renders on failure.
- [ ] `RND-013` Add tests for clipping boundaries, missing observations, localization, artifact versioning, and encode failure.
- [ ] `RND-014` Add visual regression fixtures for representative overlay frames.

## Completion Criteria

- [ ] Every completed run has all required artifacts or fails before publication.
- [ ] Rendering is reproducible from stored records without rerunning inference.
- [ ] Physical paths never leak into presentation models.

