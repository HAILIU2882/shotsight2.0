# Tracking Module Tasks

## Goal

Produce backend-neutral basketball, player, and rim tracks with confidence,
visibility, masks, and repair prompts.

## Dependencies

`TrackingBackend`, backend selection, camera segments, media frames, track
repositories.

## Checklist

- [ ] `TRK-001` Define the `TrackingBackend` protocol and capability flags from the detailed design.
- [ ] `TRK-002` Define prompt, session, frame-batch, observation, visibility, and summary models.
- [ ] `TRK-003` Add contract tests reusable by every backend adapter.
- [ ] `TRK-004` Implement tracking-session orchestration per stable camera segment.
- [ ] `TRK-005` Generate automatic prompts for basketball, players, and rim.
- [ ] `TRK-006` Persist observations with timestamps, local IDs, geometry, confidence, and provenance.
- [ ] `TRK-007` Detect track loss, occlusion, and implausible identity switches.
- [ ] `TRK-008` Add basketball motion, size, continuity, and body-overlap plausibility checks.
- [ ] `TRK-009` Accept saved user point/box prompts at a timestamp.
- [ ] `TRK-010` Reset all session state at camera-segment boundaries.
- [ ] `TRK-011` Implement MLX SAM 3 Image keyframe detection adapter.
- [ ] `TRK-012` Implement and benchmark a lightweight inter-frame tracker for the MLX backend.
- [ ] `TRK-013` Implement the official SAM 3.1 video adapter behind optional imports.
- [ ] `TRK-014` Implement the OpenCV/lightweight fallback adapter.
- [ ] `TRK-015` Add backend contract tests and representative-video evaluation scripts.
- [ ] `TRK-016` Record track coverage, reinitializations, and identity-switch metrics.

## Completion Criteria

- [ ] All backends produce the same observation contract.
- [ ] Missing optional backends do not prevent application startup.
- [ ] Ball tracks can be repaired by a persisted user prompt and full reanalysis.

