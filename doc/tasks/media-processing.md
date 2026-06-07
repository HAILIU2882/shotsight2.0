# Media Processing Module Tasks

## Goal

Provide cross-platform FFmpeg/ffprobe operations for probing, normalization,
frame access, clipping, and encoding.

## Dependencies

Media tool port, artifact store, FFmpeg executable, analysis configuration.

## Checklist

- [x] `MED-001` Define media metadata, proxy profile, clip, and encode contracts.
- [x] `MED-002` Detect and report FFmpeg and ffprobe availability and versions.
- [x] `MED-003` Implement structured ffprobe JSON parsing.
- [x] `MED-004` Implement proxy generation with orientation normalization.
- [x] `MED-005` Normalize variable frame-rate sources to the selected analysis rate.
- [x] `MED-006` Implement Quality, Balanced, and Speed profile configuration.
- [x] `MED-007` Downscale 4K sources without upscaling smaller sources.
- [x] `MED-008` Record actual proxy dimensions, FPS, codec, and command configuration.
- [x] `MED-009` Implement timestamp-based frame extraction.
- [x] `MED-010` Implement per-attempt replay clipping with bounded start/end times.
- [x] `MED-011` Implement annotated-video encoding from rendered frames or overlays.
- [x] `MED-012` Parse subprocess errors without invoking a shell command string.
- [x] `MED-013` Add disk-space checks before large proxy and render operations.
- [x] `MED-014` Add adapter tests using generated constant-frame, variable-rate, rotated, short, and corrupt fixtures.

## Completion Criteria

- [x] Media operations behave consistently on macOS, Windows, and Linux.
- [x] Every generated artifact is written atomically.
- [x] FFmpeg failures produce structured diagnostics.

## Verification

- `pytest --cov=shotsight2 --cov-fail-under=80`: 22 passed, 94.18% coverage.
- `mypy --strict src/shotsight2 tests`: passed.
- `ruff check .`: passed.
- `ruff format --check` for Media Processing-owned source and tests: passed.
- Integration tests used local FFmpeg 8.0.1 with generated CFR, VFR, rotated,
  short, corrupt, rendered-frame, and overlay fixtures.
