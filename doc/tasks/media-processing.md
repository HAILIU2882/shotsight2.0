# Media Processing Module Tasks

## Goal

Provide cross-platform FFmpeg/ffprobe operations for probing, normalization,
frame access, clipping, and encoding.

## Dependencies

Media tool port, artifact store, FFmpeg executable, analysis configuration.

## Checklist

- [ ] `MED-001` Define media metadata, proxy profile, clip, and encode contracts.
- [ ] `MED-002` Detect and report FFmpeg and ffprobe availability and versions.
- [ ] `MED-003` Implement structured ffprobe JSON parsing.
- [ ] `MED-004` Implement proxy generation with orientation normalization.
- [ ] `MED-005` Normalize variable frame-rate sources to the selected analysis rate.
- [ ] `MED-006` Implement Quality, Balanced, and Speed profile configuration.
- [ ] `MED-007` Downscale 4K sources without upscaling smaller sources.
- [ ] `MED-008` Record actual proxy dimensions, FPS, codec, and command configuration.
- [ ] `MED-009` Implement timestamp-based frame extraction.
- [ ] `MED-010` Implement per-attempt replay clipping with bounded start/end times.
- [ ] `MED-011` Implement annotated-video encoding from rendered frames or overlays.
- [ ] `MED-012` Parse subprocess errors without invoking a shell command string.
- [ ] `MED-013` Add disk-space checks before large proxy and render operations.
- [ ] `MED-014` Add adapter tests using generated constant-frame, variable-rate, rotated, short, and corrupt fixtures.

## Completion Criteria

- [ ] Media operations behave consistently on macOS, Windows, and Linux.
- [ ] Every generated artifact is written atomically.
- [ ] FFmpeg failures produce structured diagnostics.

